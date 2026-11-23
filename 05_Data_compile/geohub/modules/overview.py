"""Summary tab: AOI, module status and global export."""
import datetime as dt

import streamlit as st
from streamlit_folium import st_folium

from ..config import tarjeta
from ..core import export
from ..core.maps import mapa_base, agregar_aoi


def render(ctx):
    st.subheader("🏠 AOI Summary")
    aoi, rango = ctx["aoi"], ctx["rango"]
    if aoi is None:
        st.info("👈 Define an area of interest in the sidebar (file, GeoJSON, point + radius or drawing).")
        return
    c = st.columns(4)
    c[0].markdown(tarjeta("Area", f"{aoi['area_ha']:,.1f}", "ha", "Active AOI"), unsafe_allow_html=True)
    c[1].markdown(tarjeta("Centroid", f"{aoi['lat']:.3f}, {aoi['lon']:.3f}", "", "lat, lon"), unsafe_allow_html=True)
    c[2].markdown(tarjeta("Window", f"{(dt.date.fromisoformat(rango[1]) - dt.date.fromisoformat(rango[0])).days}" if rango else "—",
                          "days", f"{rango[0]} → {rango[1]}" if rango else "invalid range", "agua"), unsafe_allow_html=True)
    c[3].markdown(tarjeta("USDA coverage", "Yes" if aoi["en_eeuu"] else "No", "", "SSURGO only in the U.S.", "suelo" if aoi["en_eeuu"] else "alerta"),
                  unsafe_allow_html=True)
    m = mapa_base([aoi["lat"], aoi["lon"]], 14)
    agregar_aoi(m, aoi["geom"])
    st_folium(m, height=380, use_container_width=True, returned_objects=[], key="mapa_resumen")

    datos = st.session_state.get("datos", {})
    est = {"suelos": "🧱 Soils", "clima": "🌦️ Climate", "cultivo": "🛰️ Crop"}
    st.markdown("**Query status:** " + " · ".join(f"{n}: {'✅ queried' if k in datos else '— pending'}" for k, n in est.items()))
    if not ctx["gee_ok"]:
        st.warning("Earth Engine not connected: Climate and Crop are not available (Soils is).")

    exp = st.session_state.get("exportables", {})
    st.markdown("#### 📦 Export")
    if exp:
        meta = {"aoi": aoi, "rango": rango, "tablas": list(exp)}
        st.download_button(f"⬇️ Download ZIP ({len(exp)} tables + metadata)", export.zip_bytes(meta),
                           file_name="geohub_export.zip", mime="application/zip")
    else:
        st.caption("Tables you open in each module accumulate here so you can download them as a ZIP.")
