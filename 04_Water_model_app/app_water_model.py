# ============================================================
# 💧 Water Model — Surface water balance and 3D hydrological modeling
# © 2026 Ariel Macías | Agronomist & GIS Analyst
# Datos: Sentinel-2 · 3DEP · USDA-NRCS (SSURGO) · CHIRPS · ERA5-Land
# Run with:  streamlit run app_water_model.py
# ============================================================
import warnings
import numpy as np
import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")

# Page configuration must be the first Streamlit command
st.set_page_config(page_title="Water Model · Water balance", page_icon="💧",
                   layout="wide", initial_sidebar_state="expanded")

from water_model.config import CSS_GLOBAL, CSS_WATERMARK, PROF_RADICULAR_CULTIVOS  # noqa: E402
from water_model.gee_client import init_gee, serie_clima  # noqa: E402
from water_model.pipeline import ejecutar_pipeline  # noqa: E402
from water_model import ui_tabs as ui  # noqa: E402

st.markdown(CSS_GLOBAL, unsafe_allow_html=True)
st.markdown(CSS_WATERMARK, unsafe_allow_html=True)
st.markdown("<h1 style='font-size:28px;padding:10px 0 0'>💧 Water Model · Surface and subsurface water balance</h1>",
            unsafe_allow_html=True)
st.caption("USDA-NRCS soil (Ksat, porosity, effective depth) + Sentinel-2 + CHIRPS/ERA5-Land (hourly hyetograph, water table and interflow) + 3DEP → accumulation, routing and timelapse")

# ── Session state ────────────────────────────────────────────
for k, v in {"gee_ok": False, "aoi": None, "cuenca": None}.items():
    st.session_state.setdefault(k, v)

# ── Google Earth Engine connection ───────────────────────────
if not st.session_state["gee_ok"]:
    ok, metodo, err = init_gee()
    st.session_state["gee_ok"] = ok
    if not ok:
        st.error(f"❌ Could not connect to Google Earth Engine ({metodo}): {err}")
        st.info("Configure `.streamlit/secrets.toml` with `[gee_service_account]` (and optionally `gee_project`) "
                "or authenticate with `earthengine authenticate`.")
        st.stop()

# ── Sidebar organized in tabs ────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Parameters")
    t_ev, t_malla, t_mod = st.tabs(["🌧️ Event", "🧱 Grid/Soil", "🧮 Model"])

    with t_ev:
        modo_p = st.selectbox(
            "Precipitation X",
            [
                "Manual (mm)",
                "Select real historical event (CHIRPS last year)",
                "Daily maximum (last year)",
                "3-day maximum (last year)",
                "Last 7 days",
            ],
            help=(
                "Defines the source of the rainfall depth to simulate: a manual value, a real event "
                "interactively selected in the CHIRPS + ERA5-Land Hourly bar chart, or the recorded maxima."
            ),
        )

        es_historico = modo_p.startswith("Select")
        if es_historico:
            aoi_act = st.session_state.get("aoi")
            if aoi_act is None:
                st.info("Define the AOI first in the 📍 tab to display the CHIRPS event chart.")
            else:
                if st.session_state.get("clima") is None:
                    try:
                        with st.spinner("Downloading CHIRPS + ERA5-Land historical series…"):
                            hoy = pd.Timestamp.today().normalize()
                            ini = (hoy - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
                            st.session_state["clima"] = serie_clima(
                                aoi_act["lon"], aoi_act["lat"], ini, hoy.strftime("%Y-%m-%d")
                            )
                    except Exception as e_c:  # noqa: BLE001
                        st.warning(f"Could not preload CHIRPS: {e_c}")

        det_activo = st.session_state.get("detalle_evento_activo") if es_historico else None
        p_def_sidebar = float(det_activo["p_total_mm"]) if det_activo else 60.0
        dur_def_sidebar = int(det_activo["duracion_real_h"]) if det_activo else 24

        p_manual = st.number_input(
            "Event P (mm)",
            1.0, 500.0, float(np.clip(p_def_sidebar, 1.0, 500.0)) if es_historico else 60.0, 5.0,
            disabled=not modo_p.startswith("Manual"),
            help=(
                "Total millimetres of rainfall of the event. In historical mode it is extracted automatically "
                "from the event selected in the CHIRPS chart."
            ),
        )
        dur_h = st.slider(
            "Event duration (h)",
            1, 72, int(np.clip(dur_def_sidebar, 1, 72)) if es_historico else 24,
            disabled=es_historico,
            help=(
                "Effective storm duration in hours. In historical mode it is extracted automatically "
                "by crossing the event dates with the ERA5-Land hourly series."
            ),
        )
        if es_historico and det_activo:
            st.caption(
                f"🎯 **Active event:** `{det_activo['fecha_inicio']}` → `{det_activo['fecha_fin']}` · "
                f"**{det_activo['p_total_mm']:.1f} mm** in **{det_activo['duracion_real_h']} h** "
                f"(Imax: **{det_activo['intensidad_max_mmh']:.1f} mm/h**)."
            )

        umbral = st.slider(
            "Ponding threshold (mm)",
            1.0, 30.0, 5.0, 0.5,
            help=(
                "Minimum accumulated surface water depth (mm) above which a cell is "
                "classified as a ponded area (Mild ≥ 1×, Moderate ≥ 2×, Severe ≥ 5× threshold)."
            ),
        )

    with t_malla:
        limite_etq = st.selectbox(
            "Spatial modeling boundary",
            [
                ("aoi", "Use AOI boundary (main field only)"),
                ("aoi_aporte_cuenca", "AOI + External sub-basin inflow (WBD / Local)"),
                ("subcuenca", "Use the whole sub-basin boundary (WBD / Local)"),
            ],
            format_func=lambda x: x[1],
            help=(
                "Defines which geometric boundary governs ejecutar_pipeline(...): only the AOI polygon, "
                "the AOI receiving runoff from its sub-basin (USGS/WBD/2017/HUC12 or local file), "
                "or the whole sub-basin as a complete hydrological unit."
            ),
        )
        limite_analisis = limite_etq[0]

        nivel_wbd = st.selectbox(
            "USGS WBD level (GEE auto-query)",
            ["HUC12", "HUC10"],
            disabled=(limite_analisis == "aoi"),
            help=(
                "If you have not loaded a basin yet and choose to model with sub-basin, "
                "USGS/WBD/2017/HUC12 (or HUC10) will be queried automatically in Google Earth Engine with .filterBounds(aoi)."
            ),
        )

        modo_prof_etq = st.selectbox(
            "Effective depth criterion",
            [
                ("restrictivo", "Most restrictive: min(Agronomic, SSURGO soil depth)"),
                ("agronomica", "Agronomic / Crop root depth"),
                ("edafica", "Real soil depth of the profile (SSURGO)"),
            ],
            format_func=lambda x: x[1],
            help=(
                "Defines how to compute the total retention volume of the profile: the 'Most restrictive' mode "
                "compares the crop root depth with the real effective depth from SSURGO "
                "(limited by rock or dense layers) and uses the lower of the two values."
            ),
        )
        modo_prof = modo_prof_etq[0]

        cultivo_sel = st.selectbox(
            "Reference crop (root depth)",
            list(PROF_RADICULAR_CULTIVOS.keys()),
            help="Preselects the typical root depth of different field crops or lets you adjust it manually.",
        )
        prof_preset = PROF_RADICULAR_CULTIVOS[cultivo_sel]
        prof_cm = st.slider(
            "Agronomic / root depth (cm)",
            30, 200, int(prof_preset) if prof_preset is not None else 100, 10,
            disabled=(modo_prof == "edafica" or prof_preset is not None),
            help="Target root depth (cm) to integrate field capacity, PWP, AWC, porosity and Ksat.",
        )
        if prof_preset is not None:
            prof_cm = int(prof_preset)

        dias_s2 = st.slider(
            "Sentinel-2 window (days)",
            15, 120, 45, 5,
            help="Number of days before today used to build the cloud-free Sentinel-2 mosaic (NDVI, NDWI, SAVI, LAI).",
        )
        res_m = st.selectbox(
            "Grid resolution (m)",
            [0, 10, 20, 30, 50],
            format_func=lambda x: "Automatic" if x == 0 else f"{x} m",
            help="Cell size (m) of the UTM modeling grid. 'Automatic' adjusts between 10 and 50 m according to the field/basin area.",
        )
        suavizado = st.slider(
            "DEM smoothing (iterations)",
            0, 3, 1,
            help="Applies 3×3 filter passes to the elevation model (3DEP) to attenuate pixel micro-noise without losing the drainage lines.",
        )

    with t_mod:
        peso_ndwi = st.slider(
            "NDWI weight in antecedent moisture",
            0.0, 1.0, 0.3, 0.05,
            help=(
                "Spatial weighting between ERA5-Land surface volumetric moisture (0 = ERA5 only) "
                "and the Sentinel-2 spectral water index NDWI (1 = NDWI only) to estimate the antecedent condition."
            ),
        )
        n_iter = st.slider(
            "Routing iterations",
            100, 1500, 500, 50,
            help="Maximum number of 2D cellular-automaton steps for surface runoff towards low areas and depressions.",
        )

    run = st.button(
        "▶️ Run model",
        type="primary",
        use_container_width=True,
        disabled=st.session_state["aoi"] is None,
        help="Downloads/updates the spatial layers and runs the water balance with the parameters and the hyetograph of the chosen event.",
    )
    if st.session_state["aoi"] is None:
        st.caption("Define the AOI first in the 📍 tab.")

# ── Loading container above the event selection panel ──
contenedor_carga = st.container()

# ── Interactive CHIRPS precipitation bars + ERA5 Hyetograph panel ──
det_panel = None
if modo_p.startswith("Select") and st.session_state.get("aoi") is not None:
    det_panel = ui.render_panel_selector_historico()

if run:
    det_usar = det_panel or st.session_state.get("detalle_evento_activo")
    with contenedor_carga:
        ejecutar_pipeline(dict(
            modo_p=modo_p,
            p_manual=p_manual,
            dur_h=dur_h,
            umbral=umbral,
            prof_cm=prof_cm,
            modo_prof=modo_prof,
            limite_analisis=limite_analisis,
            nivel_wbd=nivel_wbd,
            evento_hist_fecha=det_usar["fecha_pico"] if det_usar else st.session_state.get("evento_chirps_fecha_str"),
            evento_hist_ventana_completa=st.session_state.get("chk_ventana_tormenta", True),
            detalle_evento=det_usar if modo_p.startswith("Select") else None,
            dias_s2=dias_s2,
            res_m=res_m,
            suavizado=suavizado,
            peso_ndwi=peso_ndwi,
            n_iter=n_iter,
        ))

with contenedor_carga:
    for aviso in st.session_state.get("avisos", []):
        st.warning(aviso)

# ── Main tabs ────────────────────────────────────────────────
tabs = st.tabs(["📍 AOI", "🧱 Soil", "🌦️ Climate and vegetation", "💧 Water balance", "🗺️ 2D Map", "🧊 3D Model"])
for tab, fn in zip(tabs, (ui.render_tab_aoi, ui.render_tab_suelo, ui.render_tab_clima,
                          ui.render_tab_balance, ui.render_tab_mapa, ui.render_tab_3d)):
    with tab:
        try:
            fn()
        except Exception as e:  # noqa: BLE001  (a tab with an error must not bring the app down)
            st.error(f"Error rendering the tab: {e}")
