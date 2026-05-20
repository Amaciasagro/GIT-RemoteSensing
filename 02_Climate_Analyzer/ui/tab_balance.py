# ============================================================
# ui/tab_balance.py — Tab 3: Balance hídrico espacial
# ============================================================

import streamlit as st
import json
from streamlit_folium import st_folium

from gee_client import mapa_balance_hidrico
from map_utils import build_mapa_tematico, bbox_lotes
from config import PALETA_BALANCE, PALETA_PRECIPITACION, PALETA_TEMPERATURA


def render_tab_balance(
    lotes: list,
    fecha_inicio: str,
    fecha_fin: str,
) -> None:
    """
    Tab 3: Mapa de balance hídrico espacial.
    CHIRPS (precipitación) - ETo Hargreaves-Samani (ERA5).
    """
    st.markdown("### 💧 Balance Hídrico Espacial")
    st.caption(
        "Diferencia píxel a píxel entre la precipitación acumulada (CHIRPS) "
        "y la Evapotranspiración potencial estimada (ERA5 → Hargreaves-Samani)."
    )

    if not lotes:
        st.info("Definí al menos un lote en la barra lateral.")
        return

    # ── Config ───────────────────────────────────────────────
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        capa_visible = st.radio(
            "Capa a visualizar",
            ["Balance (P - ETo)", "Solo Precipitación (CHIRPS)", "Solo ETo (ERA5)"],
            key="balance_capa",
        )
    with col_cfg2:
        lote_sel = st.selectbox(
            "Lote de referencia",
            [l["nombre"] for l in lotes],
            key="sel_lote_balance",
        )

    lote_info = next(l for l in lotes if l["nombre"] == lote_sel)
    aoi_json  = json.dumps(lote_info["geom"])

    # ── Calcular ─────────────────────────────────────────────
    with st.spinner("⏳ Calculando balance hídrico espacial…"):
        try:
            resultado = mapa_balance_hidrico(aoi_json, fecha_inicio, fecha_fin)
        except Exception as e:
            st.error(f"Error al calcular balance hídrico: {e}")
            return

    # ── Métricas ─────────────────────────────────────────────
    st.markdown(f"#### Estadísticas — **{lote_sel}**")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🌧️ Precip. media (CHIRPS)", f"{resultado['precip_mean']:.0f} mm")
    m2.metric("💧 ETo media (ERA5-HS)",    f"{resultado['eto_mean']:.0f} mm")
    bal = resultado["balance_mean"]
    m3.metric(
        "⚖️ Balance medio",
        f"{bal:+.0f} mm",
        delta="Superávit" if bal >= 0 else "Déficit",
        delta_color="normal" if bal >= 0 else "inverse",
    )
    m4.metric("📊 Rango espacial",
              f"{resultado['balance_min']:+.0f} / {resultado['balance_max']:+.0f} mm")

    st.divider()

    # ── Selector de capa para el mapa ────────────────────────
    if "Balance" in capa_visible:
        tile_url     = resultado["tile_url_balance"]
        palette      = resultado["palette"]
        val_min, val_max = resultado["vis_min"], resultado["vis_max"]
        titulo_ley   = "Balance hídrico (mm)"
        nombre_capa  = "Balance P - ETo"
        unidad       = "mm"
    elif "Precipitación" in capa_visible:
        tile_url     = resultado["tile_url_chirps"]
        palette      = PALETA_PRECIPITACION
        val_min, val_max = 0, 800
        titulo_ley   = "Precipitación CHIRPS (mm)"
        nombre_capa  = "Precipitación CHIRPS"
        unidad       = "mm"
    else:
        tile_url     = resultado["tile_url_eto"]
        palette      = list(reversed(PALETA_TEMPERATURA))
        val_min, val_max = 0, 800
        titulo_ley   = "ETo estimada (mm)"
        nombre_capa  = "ETo Hargreaves-Samani"
        unidad       = "mm"

    # Capas extra para control de capas
    capas_extra = [
        {"tile_url": resultado["tile_url_balance"],  "nombre": "Balance P - ETo"},
        {"tile_url": resultado["tile_url_chirps"],   "nombre": "Precipitación CHIRPS"},
        {"tile_url": resultado["tile_url_eto"],      "nombre": "ETo ERA5"},
    ]

    st.markdown("#### 🗺️ Mapa de Balance Hídrico")

    center = bbox_lotes(lotes)
    mapa = build_mapa_tematico(
        center=center,
        zoom=10,
        tile_url=tile_url,
        nombre_capa=nombre_capa,
        lotes=lotes,
        palette=palette,
        val_min=val_min,
        val_max=val_max,
        titulo_leyenda=titulo_ley,
        unidad=unidad,
        capas_extra=[c for c in capas_extra if c["nombre"] != nombre_capa],
    )
    st_folium(mapa, height=480, use_container_width=True,
              returned_objects=[], key=f"mapa_balance_{lote_sel}_{capa_visible}")

    # ── Interpretación ───────────────────────────────────────
    if "Balance" in capa_visible:
        st.markdown("**Guía de colores del mapa de balance:**")
        col_a, col_b, col_c = st.columns(3)
        col_a.error("🟥 Rojo oscuro — Estrés hídrico severo (déficit > 200 mm)")
        col_b.warning("🟡 Amarillo — Condición neutra (±50 mm)")
        col_c.success("🟢 Verde oscuro — Superávit hídrico (exceso > 200 mm)")

    with st.expander("ℹ️ Metodología"):
        st.markdown("""
**Fuente precipitación:** CHIRPS (~5 km, diario)  
**Fuente temperatura/radiación:** ERA5-Land (~11 km, diario)  
**ETo:** Hargreaves-Samani simplificado (cálculo raster píxel a píxel)  
> ETo = 0.0023 × (Tmed + 17.8) × √(Tmax − Tmin) × Ra × 0.408

**Balance = P (CHIRPS) − ETo (ERA5-HS)**

La ETo se reproyecta a la resolución de CHIRPS (5 km) antes de la resta.  
El mapa refleja la distribución espacial del estrés hídrico real, útil para:
- Zonificar necesidad de riego complementario
- Identificar heterogeneidad intra-lote
- Comparar comportamiento entre lotes de un mismo campo
        """)
