# ============================================================
# ui/tab_series.py — Tab 1: Series temporales ERA5
# ============================================================

import streamlit as st
import pandas as pd
import io
from streamlit_folium import st_folium

from metrics import agregar_mensual, procesar_diario
from charts import grafico_climatico, grafico_balance, grafico_diario, grafico_hr_viento
from map_utils import build_mapa, bbox_lotes


def render_tab_series(lotes: list, datos_lotes: dict, t_base: float) -> None:
    """
    Tab 1: Gráficos de series temporales ERA5.
    Si hay múltiples lotes, muestra un selector y renderiza el lote elegido.
    """
    if not datos_lotes:
        st.info("Presioná **Analizar lotes** en la barra lateral para ver los datos.")
        return

    lotes_con_datos = [l for l in lotes if l["nombre"] in datos_lotes]
    if not lotes_con_datos:
        st.info("No hay datos disponibles aún.")
        return

    # ── Selector de lote ────────────────────────────────────
    nombres = [l["nombre"] for l in lotes_con_datos]
    if len(nombres) > 1:
        lote_sel = st.selectbox(
            "🔍 Ver lote:", nombres, key="sel_lote_series"
        )
    else:
        lote_sel = nombres[0]

    lote_info = next(l for l in lotes_con_datos if l["nombre"] == lote_sel)
    datos_json = datos_lotes[lote_sel]

    # ── Cargar DataFrame ─────────────────────────────────────
    df_raw = pd.read_json(io.StringIO(datos_json))
    df_raw.index = pd.to_datetime(df_raw.index, unit="ms")
    df_raw.attrs["latitud"] = lote_info.get("lat", -30.0)

    df_mensual = agregar_mensual(df_raw, t_base)

    fecha_max   = df_raw.index.max()
    daily_inicio = fecha_max.replace(day=1).strftime("%Y-%m-%d")
    daily_fin    = fecha_max.strftime("%Y-%m-%d")
    df_diario   = procesar_diario(df_raw, daily_inicio, daily_fin, t_base)

    # ── Métricas del último mes ──────────────────────────────
    ultimo = df_mensual.iloc[-1]
    nombre_mes = ultimo["mes_año"].strftime("%B %Y").capitalize()

    st.markdown(
        f"<span style='color:{lote_info['color']}'>⬤</span> "
        f"**{lote_sel}** — Resumen {nombre_mes}",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("🌧️ Lluvia",    f"{ultimo['precip']:.1f} mm")
    m2.metric("💧 ETo PM",    f"{ultimo['eto']:.1f} mm")
    m3.metric("⚖️ Balance",   f"{ultimo['balance_hidro']:+.1f} mm")
    m4.metric("🌡️ T. media",  f"{ultimo['t_med']:.1f} °C")
    m5.metric("💧 HR media",  f"{ultimo['hr']:.0f} %")
    m6.metric("☀️ Radiación", f"{ultimo['rad']:.0f} MJ/m²")

    st.divider()

    # ── Gráficos + mapa ──────────────────────────────────────
    col_izq, col_der = st.columns([3, 1])

    with col_izq:
        st.plotly_chart(grafico_climatico(df_mensual, lote_sel), use_container_width=True)
        st.plotly_chart(grafico_balance(df_mensual, lote_sel),   use_container_width=True)
        st.plotly_chart(grafico_diario(df_diario, t_base, lote_sel), use_container_width=True)
        st.plotly_chart(grafico_hr_viento(df_mensual, lote_sel), use_container_width=True)

    with col_der:
        st.markdown("#### 🗺️ Lote")
        mapa = build_mapa(
            center=[lote_info["lat"], lote_info["lon"]],
            zoom=13,
            lotes=[lote_info],
        )
        st_folium(mapa, height=300, use_container_width=True,
                  returned_objects=[], key=f"mapa_serie_{lote_sel}")

        st.divider()
        st.markdown("#### 📋 Resumen histórico")
        resumen = df_mensual[["mes_año", "precip", "eto", "balance_hidro",
                               "t_med", "gda"]].copy()
        resumen["mes_año"] = resumen["mes_año"].dt.strftime("%b %Y")
        resumen.columns = ["Mes", "Lluvia mm", "ETo mm", "Balance mm", "T°C", "GDA"]
        st.dataframe(
            resumen.style.format({
                "Lluvia mm": "{:.1f}", "ETo mm": "{:.1f}",
                "Balance mm": "{:+.1f}", "T°C": "{:.1f}", "GDA": "{:.0f}",
            }),
            use_container_width=True, height=280,
        )

        # ── Descarga CSV ──
        csv = df_raw.reset_index().rename(columns={"fecha": "Fecha"}).to_csv(index=False)
        st.download_button(
            "⬇️ Datos diarios (.csv)",
            data=csv,
            file_name=f"era5_{lote_sel}.csv",
            mime="text/csv",
            use_container_width=True,
        )
