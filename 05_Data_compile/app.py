# ============================================================
# 🌍 GeoHub — USDA Soils · CHIRPS/ERA5-Land Climate · Crop Monitoring
# © 2026 Ariel Macías | Agronomist & GIS Analyst
# Run with:  streamlit run app.py
# ============================================================
import warnings
import streamlit as st

warnings.filterwarnings("ignore")
st.set_page_config(page_title="GeoHub · Soils, Climate & Crops", page_icon="🌍", layout="wide",
                   initial_sidebar_state="expanded")

from geohub.config import CSS_GLOBAL, CSS_WATERMARK  # noqa: E402
from geohub.core.sidebar import render_sidebar  # noqa: E402
from geohub.services.gee import init_gee  # noqa: E402
from geohub.modules import overview, soils, climate, crop  # noqa: E402

st.markdown(CSS_GLOBAL, unsafe_allow_html=True)
st.markdown(CSS_WATERMARK, unsafe_allow_html=True)
st.markdown("<h1 style='font-size:28px;padding:10px 0 0'>🌍 GeoHub · Soils · Climate · Crops</h1>", unsafe_allow_html=True)
st.caption("USDA SSURGO · CHIRPS · ERA5-Land · Sentinel-2 / Landsat — query and visualization over a shared AOI")

# GEE is optional for Soils: if it fails, only Climate and Crop are disabled
if "gee_ok" not in st.session_state:
    ok, metodo, err = init_gee()
    st.session_state.update(gee_ok=ok, gee_msg="" if ok else f"({metodo}) {err}")
if not st.session_state["gee_ok"]:
    st.warning("⚠️ Could not connect to Google Earth Engine "
               f"{st.session_state['gee_msg'][:160]}. Configure `[gee_service_account]` in `.streamlit/secrets.toml` "
               "or run `earthengine authenticate`. The Soils module is still available.")

aoi, rango = render_sidebar()
ctx = dict(aoi=aoi, rango=rango, gee_ok=st.session_state["gee_ok"])

tabs = st.tabs(["🏠 Summary", "🧱 Soils", "🌦️ Climate", "🛰️ Crop"])
for tab, mod in zip(tabs, (overview, soils, climate, crop)):
    with tab:
        try:
            mod.render(ctx)
        except Exception as e:  # noqa: BLE001  (a module with an error does not take down the rest)
            st.error(f"Unexpected error in the module: {e}")
