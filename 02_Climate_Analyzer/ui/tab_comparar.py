# ============================================================
# ui/tab_comparar.py — Tab 5: Comparación multi-lote
# ============================================================

import streamlit as st
import pandas as pd
import io
from streamlit_folium import st_folium

from metrics import agregar_mensual, resumen_comparativo
from charts import (
    grafico_comparar_precip,
    grafico_comparar_balance,
    grafico_comparar_temperatura,
    grafico_radar_comparativo,
    grafico_barras_comparativas,
)
from map_utils import build_mapa, bbox_lotes


def render_tab_comparar(
    lotes: list,
    datos_lotes: dict,
    t_base: float,
) -> None:
    """
    Tab 5: Comparación de métricas entre múltiples lotes.
    """
    st.markdown("### 🔀 Comparación de Lotes")

    if len(lotes) < 2:
        st.info(
            "Necesitás al menos **2 lotes** definidos y analizados para comparar. "
            "Agregá más lotes en la barra lateral."
        )
        # Igual mostramos los lotes actuales en el mapa
        if lotes:
            center = bbox_lotes(lotes)
            mapa = build_mapa(center=center, zoom=10, lotes=lotes)
            st_folium(mapa, height=320, use_container_width=True,
                      returned_objects=[], key="mapa_comparar_solo")
        return

    lotes_con_datos = [l for l in lotes if l["nombre"] in datos_lotes]
    if len(lotes_con_datos) < 2:
        st.warning("Esperando datos de al menos 2 lotes. Presioná **Analizar lotes**.")
        return

    # ── Construir series mensuales para cada lote ────────────
    series_dict   = {}
    lat_dict      = {}
    for lote in lotes_con_datos:
        nombre = lote["nombre"]
        df_raw = pd.read_json(io.StringIO(datos_lotes[nombre]))
        df_raw.index = pd.to_datetime(df_raw.index, unit="ms")
        df_raw.attrs["latitud"] = lote.get("lat", -30.0)
        series_dict[nombre] = agregar_mensual(df_raw, t_base)

    # ── Resumen comparativo ──────────────────────────────────
    df_res = resumen_comparativo(
        {l["nombre"]: datos_lotes[l["nombre"]] for l in lotes_con_datos},
        t_base,
    )

    # ── Mapa con todos los lotes ─────────────────────────────
    st.markdown("#### 🗺️ Todos los lotes")
    center = bbox_lotes(lotes_con_datos)
    mapa = build_mapa(center=center, zoom=10, lotes=lotes_con_datos)
    st_folium(mapa, height=320, use_container_width=True,
              returned_objects=[], key="mapa_comparar_todos")

    st.divider()

    # ── Tabla de resumen ─────────────────────────────────────
    st.markdown("#### 📋 Tabla comparativa")
    st.dataframe(
        df_res.style.format({
            "Lluvia mm":  "{:.0f}",
            "ETo mm":     "{:.0f}",
            "Balance mm": "{:+.0f}",
            "T°C media":  "{:.1f}",
            "HR% media":  "{:.0f}",
            "GDA total":  "{:.0f}",
            "Rad MJ/m²":  "{:.0f}",
        }).background_gradient(
            subset=["Balance mm"], cmap="RdYlGn"
        ).background_gradient(
            subset=["Lluvia mm"], cmap="Blues"
        ),
        use_container_width=True,
    )

    # Descarga CSV comparativo
    csv_res = df_res.reset_index().to_csv(index=False)
    st.download_button(
        "⬇️ Descargar tabla comparativa (.csv)",
        data=csv_res,
        file_name="comparativo_lotes.csv",
        mime="text/csv",
    )

    st.divider()

    # ── Gráficos comparativos ────────────────────────────────
    st.markdown("#### 📊 Gráficos comparativos")

    tab_g1, tab_g2, tab_g3, tab_g4, tab_g5 = st.tabs([
        "🌧️ Precipitación",
        "⚖️ Balance",
        "🌡️ Temperatura",
        "🕸️ Radar",
        "📊 Barras",
    ])

    with tab_g1:
        st.plotly_chart(
            grafico_comparar_precip(series_dict), use_container_width=True
        )

    with tab_g2:
        st.plotly_chart(
            grafico_comparar_balance(series_dict), use_container_width=True
        )

    with tab_g3:
        st.plotly_chart(
            grafico_comparar_temperatura(series_dict), use_container_width=True
        )

    with tab_g4:
        st.plotly_chart(
            grafico_radar_comparativo(df_res), use_container_width=True
        )
        st.caption(
            "Valores normalizados 0–1 respecto al máximo de cada métrica entre los lotes."
        )

    with tab_g5:
        st.plotly_chart(
            grafico_barras_comparativas(df_res), use_container_width=True
        )

    # ── Análisis automático ──────────────────────────────────
    st.divider()
    st.markdown("#### 💡 Conclusiones automáticas")

    lote_mas_lluvia  = df_res["Lluvia mm"].idxmax()
    lote_menos_lluvia = df_res["Lluvia mm"].idxmin()
    lote_mejor_bal   = df_res["Balance mm"].idxmax()
    lote_mayor_gda   = df_res["GDA total"].idxmax()

    col1, col2 = st.columns(2)
    with col1:
        st.info(
            f"🌧️ **Mayor precipitación:** {lote_mas_lluvia} "
            f"({df_res.loc[lote_mas_lluvia, 'Lluvia mm']:.0f} mm)"
        )
        st.info(
            f"⚖️ **Mejor balance hídrico:** {lote_mejor_bal} "
            f"({df_res.loc[lote_mejor_bal, 'Balance mm']:+.0f} mm)"
        )
    with col2:
        st.info(
            f"📉 **Menor precipitación:** {lote_menos_lluvia} "
            f"({df_res.loc[lote_menos_lluvia, 'Lluvia mm']:.0f} mm)"
        )
        st.info(
            f"🌡️ **Mayor acumulación térmica:** {lote_mayor_gda} "
            f"({df_res.loc[lote_mayor_gda, 'GDA total']:.0f} GDA)"
        )
