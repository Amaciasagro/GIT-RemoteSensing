"""Soils module (USA_Soils_Analisis): SSURGO via USDA-NRCS — edaphic properties, textures and profiles."""
import folium
import pandas as pd
import streamlit as st
from shapely.geometry import shape
from streamlit_folium import st_folium

from ..config import tarjeta, TEXTURA_ES
from ..core import state, export, charts
from ..core.maps import mapa_base, agregar_aoi
from ..services import usda


def _cards(items):
    for c, it in zip(st.columns(len(items)), items):
        c.markdown(tarjeta(*it), unsafe_allow_html=True)


def render(ctx):
    st.subheader("🧱 Soils · USDA-NRCS SSURGO")
    aoi = ctx["aoi"]
    if aoi is None:
        st.info("Define an AOI in the sidebar.")
        return
    if not aoi["en_eeuu"]:
        st.warning("The AOI is outside the U.S.: SSURGO/USDA-NRCS only covers that territory.")
        return

    c1, c2 = st.columns([3, 1])
    prof = c1.slider("Depth to integrate (cm)", 30, 200, 100, 10, key="suelo_prof")
    firma = state.firma(aoi["id"], prof)
    if c2.button("🔎 Query soils", type="primary", use_container_width=True, key="suelo_btn"):
        with st.spinner("Querying USDA polygons and horizons…"):
            try:
                gdf, tabla, hors, avisos = usda.consultar_suelos(shape(aoi["geom"]), aoi["bounds"], prof)
                tabla, prom = usda.ponderar_por_area(gdf, tabla, shape(aoi["geom"]))
                state.guardar("suelos", dict(gdf=gdf, tabla=tabla, hors=hors, prom=prom, avisos=avisos), firma)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not obtain soil information: {e}. It may be a temporary service failure "
                         "from USDA or an AOI without soil mapping (water, urban, unsurveyed area).")
                return
    d, vigente = state.obtener("suelos", firma)
    if d is None:
        st.info("Press **Query soils** to download the AOI information.")
        return
    if not vigente:
        st.warning("The AOI or depth changed since the last query: query again.")
    for a in d["avisos"]:
        st.warning(a)

    t, p = d["tabla"], d["prom"]
    ponderado = t["pct_aoi"].notna().any()
    _cards([("Dominant texture", TEXTURA_ES.get(p["textura_dom"], p["textura_dom"]), "", f"HSG {p['hsg_dom']}", "suelo"),
            ("Field cap.", f"{p['fc_mm']:.0f}", "mm", f"0–{p['depth_cm']:.0f} cm", "suelo"),
            ("Wilting point", f"{p['wp_mm']:.0f}", "mm", "PMP", "suelo"),
            ("Available water", f"{p['awc_mm']:.0f}", "mm", "FC − PWP", "agua"),
            ("Ksat", f"{p['ksat_mmh']:.1f}", "mm/h", "harmonic mean per profile", "agua")])
    st.caption(("Area-weighted averages within the AOI. " if ponderado else
                "No polygons: units are averaged without area weighting. ") +
               "FC and PWP are interpreted as % volumetric; SSURGO gaps are filled with values by textural class.")

    tab_mapa, tab_tabla, tab_perfil = st.tabs(["🗺️ Texture map", "📋 Map units", "📉 Profiles"])
    with tab_mapa:
        if d["gdf"] is None:
            st.info("The polygon service was not available; only tabular data is available.")
        else:
            idx = t.set_index("mukey")
            g = d["gdf"].copy()
            for col in ("textura", "muname", "awc_mm", "pct_aoi"):
                g[col] = g["mukey"].map(idx[col])
            g["awc_mm"], g["pct_aoi"] = g["awc_mm"].round(1), g["pct_aoi"].round(1)
            paleta = ["#e9c46a", "#f4a261", "#e76f51", "#8ab17d", "#2a9d8f", "#264653", "#b5838d", "#6d6875",
                      "#90be6d", "#43aa8b", "#577590", "#f9c74f"]
            col = {k: paleta[i % 12] for i, k in enumerate(sorted(g["textura"].dropna().unique()))}
            m = mapa_base([aoi["lat"], aoi["lon"]], 14)
            folium.GeoJson(g[["mukey", "muname", "textura", "awc_mm", "pct_aoi", "geometry"]].to_json(), name="Textures",
                           style_function=lambda f: {"fillColor": col.get(f["properties"]["textura"], "#888"),
                                                     "color": "#0b1320", "weight": 1, "fillOpacity": 0.55},
                           tooltip=folium.GeoJsonTooltip(["mukey", "muname", "textura", "awc_mm", "pct_aoi"])).add_to(m)
            agregar_aoi(m, aoi["geom"])
            folium.LayerControl().add_to(m)
            st_folium(m, height=460, use_container_width=True, returned_objects=[], key="mapa_suelos")
            st.caption("Colors by textural class: " + " · ".join(f"<span style='color:{c}'>■</span> {TEXTURA_ES.get(k, k)}"
                                                                  for k, c in col.items()), unsafe_allow_html=True)
    with tab_tabla:
        out = t.copy()
        out["textura"] = out["textura"].map(lambda x: TEXTURA_ES.get(x, x))
        cols = ["mukey", "muname", "compname", "textura", "hsg", "pct_aoi", "area_ha", "depth_cm", "fc_mm", "wp_mm",
                "awc_mm", "ksat_mmh", "sand", "silt", "clay"]
        out = out[cols].round(2)
        st.dataframe(out, use_container_width=True, hide_index=True)
        export.boton_csv(out, "suelos_unidades", "dl_suelos_t")
        export.registrar("suelos_unidades", out)
    with tab_perfil:
        h = d["hors"]
        mk = st.selectbox("Map unit (mukey)", list(t["mukey"]), key="suelo_mk")
        hm = h[h["mukey"] == mk]
        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.fig_perfil(hm), use_container_width=True)
        c2.plotly_chart(charts.fig_ternario(h), use_container_width=True)
        cols = ["mukey", "compname", "hzname", "hzdept_r", "hzdepb_r", "sandtotal_r", "silttotal_r", "claytotal_r",
                "dbthirdbar_r", "ksat_r", "wthirdbar_r", "wfifteenbar_r", "awc_r"]
        st.dataframe(hm[cols], use_container_width=True, hide_index=True)
        export.boton_csv(h[cols], "suelos_horizontes", "dl_suelos_h")
        export.registrar("suelos_horizontes", h[cols])
