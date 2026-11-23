"""Crop module (Crop_monitor): Sentinel-2 / Landsat vegetation indices as time series."""
import json

import folium
import numpy as np
import pandas as pd
import streamlit as st
import branca.colormap as bcm
from streamlit_folium import st_folium

from ..config import tarjeta, INDICES
from ..core import state, export, charts
from ..core.maps import mapa_base, agregar_aoi
from ..services import gee


def estadisticas(df, cols):
    """Summary table per index: n, mean, std dev, min/max with date, latest value and change."""
    filas = []
    for c in cols:
        s = df[["fecha", c]].dropna()
        if s.empty:
            continue
        filas.append(dict(indice=c, n=len(s), media=s[c].mean(), desvio=s[c].std(), minimo=s[c].min(),
                          fecha_min=s.loc[s[c].idxmin(), "fecha"].date(), maximo=s[c].max(),
                          fecha_max=s.loc[s[c].idxmax(), "fecha"].date(), ultimo=s[c].iloc[-1],
                          delta_ultimo=s[c].iloc[-1] - s[c].iloc[-2] if len(s) > 1 else np.nan))
    return pd.DataFrame(filas).round(3)


def _cards(items):
    for c, it in zip(st.columns(len(items)), items):
        c.markdown(tarjeta(*it), unsafe_allow_html=True)


def render(ctx):
    st.subheader("🛰️ Crop · Vegetation indices")
    aoi, rango = ctx["aoi"], ctx["rango"]
    if aoi is None or rango is None:
        st.info("Define an AOI and a valid date range in the sidebar.")
        return
    if not ctx["gee_ok"]:
        st.error("Google Earth Engine is not connected: this module is not available.")
        return
    f_ini, f_fin = rango
    gj = json.dumps(aoi["geom"])

    c = st.columns([2, 1, 1])
    sensor_nom = c[0].selectbox("Sensor", list(gee.SENSORES), key="crop_sensor")
    nubes = c[1].slider("Max. scene cloudiness (%)", 5, 90, 40, 5, key="crop_nubes")
    sensor = gee.SENSORES[sensor_nom]
    firma = state.firma(aoi["id"], f_ini, f_fin, sensor, nubes)
    if c[2].button("🔎 Query", type="primary", use_container_width=True, key="crop_btn"):
        with st.spinner("Computing per-image indices in Earth Engine…"):
            try:
                df = gee.serie_vegetacion(gj, f_ini, f_fin, sensor, nubes)
                state.guardar("cultivo", df, firma)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not query the vegetation: {e}")
                return
    df, vigente = state.obtener("cultivo", firma)
    if df is None:
        st.info("Press **Query** to compute the AOI series.")
        return
    if not vigente:
        st.warning("AOI, dates or sensor changed since the last query: query again.")
    if df.empty:
        st.error("No usable images in the range. Widen the time window or raise the cloudiness threshold.")
        return

    c = st.columns([2, 1, 1])
    sel = c[0].multiselect("Indices", list(INDICES), default=["NDVI", "NDWI"], format_func=lambda k: f"{k} · {INDICES[k][0]}")
    min_valid = c[1].slider("Min. valid coverage (%)", 0, 100, 30, 5, help="Percentage of cloud-free AOI pixels.")
    suav = c[2].checkbox("Smooth (3-obs. moving average)")
    if not sel:
        st.info("Select at least one index.")
        return
    d = df[df["valid"] >= min_valid].copy()
    descartadas = len(df) - len(d)
    if descartadas:
        st.warning(f"{descartadas} of {len(df)} dates discarded for valid coverage < {min_valid}%.")
    if d.empty:
        st.error("No date meets the minimum coverage: lower the threshold.")
        return
    if len(d) < 3:
        st.warning("Too few observations (< 3): the series does not allow trends to be seen.")
    if suav:
        d[sel] = d[sel].rolling(3, min_periods=1, center=True).mean()

    u = d.iloc[-1]
    huecos = d["fecha"].diff().dt.days.max()
    _cards([("Observations", f"{len(d)}", "", f"{sensor_nom.split(' (')[0]}", ""),
            (f"{sel[0]} latest", f"{u[sel[0]]:.2f}", "", f"{u['fecha']:%d-%b-%Y}", ""),
            (f"{sel[0]} max.", f"{d[sel[0]].max():.2f}", "", f"{d.loc[d[sel[0]].idxmax(), 'fecha']:%d-%b-%Y}", "agua"),
            ("Longest gap", f"{huecos:.0f}" if pd.notna(huecos) else "—", "days", "between observations", "alerta")])
    st.plotly_chart(charts.fig_indices(d, sel), use_container_width=True)

    t1, t2, t3 = st.tabs(["📊 Statistics", "🗺️ Composite map", "📋 Data"])
    with t1:
        est = estadisticas(d, sel)
        st.dataframe(est, use_container_width=True, hide_index=True)
        export.boton_csv(est, "cultivo_estadisticas", "dl_crop_e")
        export.registrar("cultivo_estadisticas", est)
    with t2:
        idx = st.selectbox("Index to map", list(INDICES), key="crop_mapa_idx")
        if st.checkbox("Load composite (range median)", key="crop_mapa_on"):
            try:
                url = gee.url_mapa_indice(gj, f_ini, f_fin, sensor, nubes, idx)
                m = mapa_base([aoi["lat"], aoi["lon"]], 14)
                folium.TileLayer(tiles=url, attr="Google Earth Engine", name=f"{idx} (mediana)", overlay=True).add_to(m)
                agregar_aoi(m, aoi["geom"])
                _, vmin, vmax, pal = INDICES[idx]
                bcm.LinearColormap(pal, vmin=vmin, vmax=vmax, caption=f"{idx}").add_to(m)
                folium.LayerControl().add_to(m)
                st_folium(m, height=480, use_container_width=True, returned_objects=[], key=f"mapa_crop_{idx}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not generate the map: {e}")
    with t3:
        out = d[["fecha", *sel, "valid"]].rename(columns={"valid": "cobertura_valida_pct"}).round(3)
        st.dataframe(out, use_container_width=True, hide_index=True)
        export.boton_csv(out, "cultivo_serie", "dl_crop_d")
        export.registrar("cultivo_serie", out)
