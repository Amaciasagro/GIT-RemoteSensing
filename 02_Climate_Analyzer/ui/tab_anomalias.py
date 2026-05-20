# ============================================================
# ui/tab_anomalias.py — Tab 2: Anomalías CHIRPS
# ============================================================

import streamlit as st
import json
import pandas as pd
from streamlit_folium import st_folium

from gee_client import mapa_anomalia_chirps
from map_utils import build_mapa_tematico, bbox_lotes, exportar_mapa_html
from config import PALETA_ANOMALIA, CHIRPS_BASELINE_YEARS


def render_tab_anomalias(
    lotes: list,
    fecha_inicio: str,
    fecha_fin: str,
) -> None:
    """
    Tab 2: Mapa de anomalías de precipitación CHIRPS.
    Calcula: Precipitación período - Promedio histórico mismo rango.
    """
    st.markdown("### 🌧️ Anomalías de Precipitación CHIRPS")

    # Calcular y mostrar el período efectivo (máx 365 días)
    fin_dt   = pd.to_datetime(fecha_fin)
    ini_dt   = pd.to_datetime(fecha_inicio)
    if (fin_dt - ini_dt).days > 365:
        ini_dt = fin_dt - pd.Timedelta(days=365)
    periodo_label = f"{ini_dt.strftime('%d %b %Y')} → {fin_dt.strftime('%d %b %Y')}"

    st.caption(
        f"Período analizado: **{periodo_label}** · "
        f"Comparado contra el promedio histórico de los últimos "
        f"{CHIRPS_BASELINE_YEARS} años para el mismo rango de días."
    )

    if not lotes:
        st.info("Definí al menos un lote en la barra lateral.")
        return

    # ── Selector de visualización ────────────────────────────
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        tipo_mapa = st.radio(
            "Tipo de anomalía",
            ["Absoluta (mm)", "Porcentual (%)"],
            horizontal=True,
            key="anomalia_tipo",
        )
    with col_cfg2:
        lote_nombres = [l["nombre"] for l in lotes]
        lote_sel = st.selectbox("Lote a analizar", lote_nombres, key="sel_lote_anomalia")

    lote_info  = next(l for l in lotes if l["nombre"] == lote_sel)
    aoi_json   = json.dumps(lote_info["geom"])

    # ── Calcular (cacheado) ──────────────────────────────────
    with st.spinner("⏳ Calculando anomalía CHIRPS…"):
        try:
            resultado = mapa_anomalia_chirps(aoi_json, fecha_inicio, fecha_fin)
        except Exception as e:
            st.error(f"Error al calcular anomalía: {e}")
            return

    tile_url = (resultado["tile_url_pct"]
                if "Porcentual" in tipo_mapa
                else resultado["tile_url"])
    unidad   = "%" if "Porcentual" in tipo_mapa else "mm"
    val_min  = -100 if "Porcentual" in tipo_mapa else resultado["vis_min"]
    val_max  =  100 if "Porcentual" in tipo_mapa else resultado["vis_max"]

    # ── Métricas ─────────────────────────────────────────────
    st.markdown(f"#### Estadísticas — **{lote_sel}**")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🌧️ Lluvia período",      f"{resultado['precip_actual_mm']:.0f} mm")
    m2.metric("📊 Promedio histórico",  f"{resultado['precip_hist_mm']:.0f} mm")
    anom_mm = resultado["anomalia_mm"]
    m3.metric(
        "⚠️ Anomalía media",
        f"{anom_mm:+.0f} mm",
        delta=f"{'Déficit' if anom_mm < 0 else 'Exceso'}",
        delta_color="inverse" if anom_mm < 0 else "normal",
    )
    m4.metric("📉 Anomalía mínima", f"{resultado['anomalia_min']:+.0f} mm")
    m5.metric("📈 Anomalía máxima", f"{resultado['anomalia_max']:+.0f} mm")

    st.divider()

    # ── Interpretación rápida ────────────────────────────────
    anom_pct = resultado["anomalia_pct"]
    if anom_pct <= -30:
        nivel, color_alerta = "⚠️ Déficit hídrico severo", "red"
    elif anom_pct <= -10:
        nivel, color_alerta = "🟠 Déficit moderado", "orange"
    elif anom_pct >= 30:
        nivel, color_alerta = "🔵 Exceso significativo", "blue"
    elif anom_pct >= 10:
        nivel, color_alerta = "🟢 Leve exceso", "green"
    else:
        nivel, color_alerta = "✅ Condición normal", "green"

    st.markdown(
        f"<div style='background:#111c2a; border-radius:8px; "
        f"padding:10px 16px; border-left: 4px solid {color_alerta};'>"
        f"<b>Condición hídrica:</b> {nivel} "
        f"(<b>{anom_pct:+.1f}%</b> respecto al promedio histórico)"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### 🗺️ Mapa de Anomalía")

    center = bbox_lotes(lotes)
    mapa = build_mapa_tematico(
        center=center,
        zoom=10,
        tile_url=tile_url,
        nombre_capa=f"Anomalía {unidad}",
        lotes=lotes,
        palette=resultado["palette"],
        val_min=val_min,
        val_max=val_max,
        titulo_leyenda=f"Anomalía de precipitación ({unidad})",
        unidad=unidad,
    )
    st_folium(mapa, height=480, use_container_width=True,
              returned_objects=[], key=f"mapa_anomalia_{lote_sel}_{tipo_mapa}")
    html_bytes = exportar_mapa_html(mapa)
    st.download_button(
        "⬇️ Descargar mapa (.html)",
        data=html_bytes,
        file_name=f"anomalia_chirps_{lote_sel}.html",
        mime="text/html",
    )
# ── Nota metodológica ────────────────────────────────────
with st.expander("ℹ️ Metodología"):
    st.markdown(f"""
**Fuente:** CHIRPS (Climate Hazards Group InfraRed Precipitation with Station data)  
**Resolución espacial:** ~5 km (~0.05°)  
**Período de referencia (baseline):** últimos {CHIRPS_BASELINE_YEARS} años calendario  
**Cálculo:**
- Precipitación acumulada del período analizado (mm)
- Promedio histórico del mismo rango de días-del-año sobre el baseline
- Anomalía absoluta = Actual − Histórico (mm)  
- Anomalía porcentual = (Actual − Histórico) / Histórico × 100 (%)

**Interpretación del mapa:**  
🟥 Tonos rojos → déficit hídrico (lluvia < normal)  
⬜ Blanco → condición normal  
🟦 Tonos azules → exceso de lluvia  
        """)
