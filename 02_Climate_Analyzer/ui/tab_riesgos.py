# ============================================================
# ui/tab_riesgos.py — Tab 4: Riesgo térmico (heladas / calor)
# ============================================================

import streamlit as st
import json
from streamlit_folium import st_folium

from gee_client import mapa_riesgo_termico
from map_utils import build_mapa_tematico, bbox_lotes
from config import PALETA_HELADAS, PALETA_CALOR


def render_tab_riesgos(
    lotes: list,
    fecha_inicio: str,
    fecha_fin: str,
    t_helada: float,
    t_calor: float,
) -> None:
    """
    Tab 4: Mapas de días con riesgo de helada y estrés térmico por calor.
    Conteo de días por píxel ERA5 en que Tmin < t_helada o Tmax > t_calor.
    """
    st.markdown("### 🌡️ Zonificación de Riesgo Térmico")
    st.caption(
        f"Conteo de días por píxel (ERA5-Land) con Tmin < **{t_helada:.1f}°C** "
        f"(helada) o Tmax > **{t_calor:.1f}°C** (estrés térmico)."
    )

    if not lotes:
        st.info("Definí al menos un lote en la barra lateral.")
        return

    # ── Config ───────────────────────────────────────────────
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        riesgo_tipo = st.radio(
            "Tipo de riesgo",
            ["🧊 Heladas (Tmin)", "🔥 Calor extremo (Tmax)"],
            key="riesgo_tipo",
        )
    with col_cfg2:
        lote_sel = st.selectbox(
            "Lote de referencia",
            [l["nombre"] for l in lotes],
            key="sel_lote_riesgo",
        )

    lote_info = next(l for l in lotes if l["nombre"] == lote_sel)
    aoi_json  = json.dumps(lote_info["geom"])

    # ── Calcular ─────────────────────────────────────────────
    with st.spinner("⏳ Contando días de riesgo térmico…"):
        try:
            resultado = mapa_riesgo_termico(
                aoi_json, fecha_inicio, fecha_fin, t_helada, t_calor
            )
        except Exception as e:
            st.error(f"Error al calcular riesgos térmicos: {e}")
            return

    n_dias = resultado["n_dias_total"]

    # ── Métricas ─────────────────────────────────────────────
    st.markdown(f"#### Estadísticas — **{lote_sel}** ({n_dias} días analizados)")

    es_helada = "Heladas" in riesgo_tipo

    if es_helada:
        dias_m = resultado["helada_dias_mean"]
        dias_x = resultado["helada_dias_max"]
        pct    = dias_m / n_dias * 100 if n_dias > 0 else 0
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(f"🧊 Días helada (media)", f"{dias_m:.1f}")
        col2.metric("📍 Días helada (máx px)", f"{dias_x:.0f}")
        col3.metric("📊 % días con helada", f"{pct:.1f}%")
        col4.metric("🌡️ Umbral", f"Tmin < {t_helada:.1f}°C")

        # Alerta
        if pct > 20:
            st.error(f"⚠️ Riesgo ALTO: {pct:.0f}% de los días registraron helada.")
        elif pct > 10:
            st.warning(f"🟠 Riesgo MODERADO: {pct:.0f}% de los días con helada.")
        else:
            st.success(f"✅ Riesgo bajo: {pct:.0f}% de los días con helada.")

    else:
        dias_m = resultado["calor_dias_mean"]
        dias_x = resultado["calor_dias_max"]
        pct    = dias_m / n_dias * 100 if n_dias > 0 else 0
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🔥 Días calor extremo (media)", f"{dias_m:.1f}")
        col2.metric("📍 Días calor (máx px)", f"{dias_x:.0f}")
        col3.metric("📊 % días con calor extremo", f"{pct:.1f}%")
        col4.metric("🌡️ Umbral", f"Tmax > {t_calor:.1f}°C")

        if pct > 20:
            st.error(f"⚠️ Estrés térmico ALTO: {pct:.0f}% de los días.")
        elif pct > 10:
            st.warning(f"🟠 Estrés térmico MODERADO: {pct:.0f}% de los días.")
        else:
            st.success(f"✅ Estrés térmico bajo: {pct:.0f}% de los días.")

    st.divider()

    # ── Mapa ─────────────────────────────────────────────────
    st.markdown("#### 🗺️ Mapa de Riesgo Térmico")

    if es_helada:
        tile_url    = resultado["tile_url_helada"]
        palette     = resultado["palette_helada"]
        vis         = resultado["vis_helada"]
        titulo_ley  = f"Días con Tmin < {t_helada:.1f}°C"
        nombre_capa = "Días de helada"
        capa_extra  = [{"tile_url": resultado["tile_url_calor"],
                        "nombre": "Días calor extremo"}]
    else:
        tile_url    = resultado["tile_url_calor"]
        palette     = resultado["palette_calor"]
        vis         = resultado["vis_calor"]
        titulo_ley  = f"Días con Tmax > {t_calor:.1f}°C"
        nombre_capa = "Días calor extremo"
        capa_extra  = [{"tile_url": resultado["tile_url_helada"],
                        "nombre": "Días de helada"}]

    center = bbox_lotes(lotes)
    mapa = build_mapa_tematico(
        center=center,
        zoom=10,
        tile_url=tile_url,
        nombre_capa=nombre_capa,
        lotes=lotes,
        palette=palette,
        val_min=vis["min"],
        val_max=vis["max"],
        titulo_leyenda=titulo_ley,
        unidad="días",
        capas_extra=capa_extra,
    )
    st_folium(mapa, height=480, use_container_width=True,
              returned_objects=[], key=f"mapa_riesgo_{lote_sel}_{riesgo_tipo}")

    # ── Guía de colores ──────────────────────────────────────
    if es_helada:
        st.caption(
            "🟦 Azul intenso = más días con helada · "
            "⬜ Blanco = sin días de helada"
        )
    else:
        st.caption(
            "🔴 Rojo intenso = más días de calor extremo · "
            "🟡 Amarillo = pocos días de estrés térmico"
        )

    with st.expander("ℹ️ Metodología"):
        st.markdown(f"""
**Fuente:** ERA5-Land (ECMWF) · Resolución ~11 km · Datos diarios  
**Cálculo:** Para cada píxel y cada día del período, se evalúa:
- Helada: `Tmin (°C) < {t_helada:.1f}°C` → suma de días TRUE
- Calor extremo: `Tmax (°C) > {t_calor:.1f}°C` → suma de días TRUE

Los umbrales son ajustables en la barra lateral.

**Aplicaciones agronómicas:**
- Selección de híbridos/variedades tolerantes
- Definición de fechas de siembra seguras
- Identificación de zonas topográficas de mayor riesgo (hondonadas, lomas)
- Cuantificación de riesgo para seguros agrícolas
        """)
