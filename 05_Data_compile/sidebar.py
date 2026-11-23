"""Shared sidebar: AOI selector (4 methods) and time window."""
import datetime as dt
import streamlit as st
from streamlit_folium import st_folium

from . import state
from .aoi import (gdf_desde_geojson, gdf_desde_archivo, gdf_desde_punto, normalizar_aoi)
from .maps import mapa_base, agregar_aoi

MAX_DIAS = 1826   # ~5 years: reasonable limit for daily series via getInfo
_dialog = getattr(st, "dialog", None) or getattr(st, "experimental_dialog")


def _fijar(fn):
    """Tries to build the AOI; if it fails, shows a warning. Returns True if it was set."""
    try:
        st.session_state["aoi"] = normalizar_aoi(fn())
    except Exception as e:  # noqa: BLE001
        st.error(f"Invalid AOI: {e}")
        return False
    state.limpiar()
    return True


@_dialog("✏️ Draw AOI", width="large")
def _dialogo_dibujo():
    aoi = st.session_state.get("aoi")
    m = mapa_base([aoi["lat"], aoi["lon"]] if aoi else [39.5, -98.35], 14 if aoi else 4, dibujo=True)
    if aoi:
        agregar_aoi(m, aoi["geom"])
    sal = st_folium(m, height=450, use_container_width=True, returned_objects=["last_active_drawing"], key="dlg_mapa")
    dib = sal.get("last_active_drawing") if sal else None
    if dib and st.button("✅ Use this polygon", type="primary"):
        if _fijar(lambda: gdf_desde_geojson(dib)):
            st.rerun()


def render_sidebar():
    """Draws the sidebar. Returns (aoi | None, (f_ini, f_fin) | None)."""
    with st.sidebar:
        st.markdown("### 📍 Area of interest")
        metodo = st.radio("Method", ["📁 File", "📋 GeoJSON", "📌 Point + radius", "✏️ Draw"],
                          horizontal=True, label_visibility="collapsed")
        ok = False
        if metodo == "📁 File":
            f = st.file_uploader("Shapefile (.zip) or GeoJSON", type=["zip", "geojson", "json"])
            if f and st.button("Load AOI", type="primary", use_container_width=True):
                ok = _fijar(lambda: gdf_desde_archivo(f))
        elif metodo == "📋 GeoJSON":
            txt = st.text_area("Paste the GeoJSON", height=130)
            if txt.strip() and st.button("Load AOI", type="primary", use_container_width=True):
                ok = _fijar(lambda: gdf_desde_geojson(txt))
        elif metodo == "📌 Point + radius":
            c1, c2 = st.columns(2)
            lat = c1.number_input("Latitude", -90.0, 90.0, 42.03, 0.001, format="%.5f")
            lon = c2.number_input("Longitude", -180.0, 180.0, -93.60, 0.001, format="%.5f")
            r = st.number_input("Radius (m)", 50, 5000, 300, 50)
            if st.button("Create AOI", type="primary", use_container_width=True):
                ok = _fijar(lambda: gdf_desde_punto(lat, lon, r))
        else:
            if st.button("Open drawing map", type="primary", use_container_width=True):
                _dialogo_dibujo()
        if ok:
            st.rerun()

        aoi = st.session_state.get("aoi")
        if aoi:
            st.success(f"Active AOI · {aoi['area_ha']:,.1f} ha")
            st.caption(f"Centroid: {aoi['lat']:.4f}, {aoi['lon']:.4f}" + ("" if aoi["en_eeuu"] else " · outside the U.S."))
            if st.button("🗑️ Remove AOI", use_container_width=True):
                st.session_state.pop("aoi", None)
                state.limpiar()
                st.rerun()

        st.markdown("### 📅 Time window")
        hoy = dt.date.today()
        atajos = {"Last 30 days": 30, "Last 90 days": 90, "Last 180 days": 180, "Last year": 365, "Custom": None}
        a = st.selectbox("Preset", list(atajos), index=2)
        if atajos[a]:
            ini, fin = hoy - dt.timedelta(days=atajos[a]), hoy
        else:
            r = st.date_input("Range", value=(hoy - dt.timedelta(days=180), hoy), max_value=hoy)
            if not isinstance(r, (tuple, list)) or len(r) != 2:
                st.warning("Select a start and end date.")
                return aoi, None
            ini, fin = r
        if ini >= fin:
            st.error("The start date must be earlier than the end date.")
            return aoi, None
        if (fin - ini).days > MAX_DIAS:
            st.error(f"Maximum range: {MAX_DIAS} days (~5 years).")
            return aoi, None
        st.caption(f"{ini:%d %b %Y} → {fin:%d %b %Y} · {(fin - ini).days} days")
        return aoi, (ini.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"))
