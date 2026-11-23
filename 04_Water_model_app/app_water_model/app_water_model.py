# ============================================================
# 💧 Water Model — Balance hídrico superficial y modelado hidrológico 3D
# © 2026 Ariel Macías | Ingeniero agrónomo & Analista SIG
# Datos: Sentinel-2 · 3DEP · USDA-NRCS (SSURGO) · CHIRPS · ERA5-Land
# Ejecutar con:  streamlit run app_water_model.py
# ============================================================
import warnings
import numpy as np
import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")

# La configuración de página debe ser el primer comando de Streamlit
st.set_page_config(page_title="Water Model · Balance hídrico", page_icon="💧",
                   layout="wide", initial_sidebar_state="expanded")

from water_model.config import CSS_GLOBAL, CSS_WATERMARK, PROF_RADICULAR_CULTIVOS  # noqa: E402
from water_model.gee_client import init_gee, serie_clima  # noqa: E402
from water_model.pipeline import ejecutar_pipeline  # noqa: E402
from water_model import ui_tabs as ui  # noqa: E402

st.markdown(CSS_GLOBAL, unsafe_allow_html=True)
st.markdown(CSS_WATERMARK, unsafe_allow_html=True)
st.markdown("<h1 style='font-size:28px;padding:10px 0 0'>💧 Water Model · Balance hídrico superficial y subsuperficial</h1>",
            unsafe_allow_html=True)
st.caption("Suelo USDA-NRCS (Ksat, porosidad, prof. efectiva) + Sentinel-2 + CHIRPS/ERA5-Land (hietograma horario, napa e interflow) + 3DEP → acumulación, ruteo y timelapse")

# ── Estado de sesión ─────────────────────────────────────────
for k, v in {"gee_ok": False, "aoi": None, "cuenca": None}.items():
    st.session_state.setdefault(k, v)

# ── Conexión a Google Earth Engine ───────────────────────────
if not st.session_state["gee_ok"]:
    ok, metodo, err = init_gee()
    st.session_state["gee_ok"] = ok
    if not ok:
        st.error(f"❌ No se pudo conectar con Google Earth Engine ({metodo}): {err}")
        st.info("Configure `.streamlit/secrets.toml` con `[gee_service_account]` (y opcionalmente `gee_project`) "
                "o autentíquese con `earthengine authenticate`.")
        st.stop()

# ── Barra lateral organizada en pestañas ─────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Parámetros")
    t_ev, t_malla, t_mod = st.tabs(["🌧️ Evento", "🧱 Malla/Suelo", "🧮 Modelo"])

    with t_ev:
        modo_p = st.selectbox(
            "Precipitación X",
            [
                "Manual (mm)",
                "Seleccionar evento histórico real (CHIRPS último año)",
                "Máximo diario (último año)",
                "Máximo 3 días (último año)",
                "Últimos 7 días",
            ],
            help=(
                "Define el origen de la lámina de lluvia a simular: un valor manual, un evento real "
                "seleccionado interactivamente en el gráfico de barras CHIRPS + ERA5-Land Hourly, o los máximos registrados."
            ),
        )

        es_historico = modo_p.startswith("Seleccionar evento")
        if es_historico:
            aoi_act = st.session_state.get("aoi")
            if aoi_act is None:
                st.info("Defina primero el AOI en la pestaña 📍 para desplegar el gráfico de eventos CHIRPS.")
            else:
                if st.session_state.get("clima") is None:
                    try:
                        with st.spinner("Descargando serie histórica CHIRPS + ERA5-Land…"):
                            hoy = pd.Timestamp.today().normalize()
                            ini = (hoy - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
                            st.session_state["clima"] = serie_clima(
                                aoi_act["lon"], aoi_act["lat"], ini, hoy.strftime("%Y-%m-%d")
                            )
                    except Exception as e_c:  # noqa: BLE001
                        st.warning(f"No se pudo precargar CHIRPS: {e_c}")

        det_activo = st.session_state.get("detalle_evento_activo") if es_historico else None
        p_def_sidebar = float(det_activo["p_total_mm"]) if det_activo else 60.0
        dur_def_sidebar = int(det_activo["duracion_real_h"]) if det_activo else 24

        p_manual = st.number_input(
            "P del evento (mm)",
            1.0, 500.0, float(np.clip(p_def_sidebar, 1.0, 500.0)) if es_historico else 60.0, 5.0,
            disabled=not modo_p.startswith("Manual"),
            help=(
                "Milímetros totales de lluvia del evento. En modo histórico se extrae automáticamente "
                "del evento seleccionado en el gráfico CHIRPS."
            ),
        )
        dur_h = st.slider(
            "Duración del evento (h)",
            1, 72, int(np.clip(dur_def_sidebar, 1, 72)) if es_historico else 24,
            disabled=es_historico,
            help=(
                "Duración efectiva en horas de la tormenta. En modo histórico se extrae automáticamente "
                "cruzando las fechas del evento con la serie horaria de ERA5-Land."
            ),
        )
        if es_historico and det_activo:
            st.caption(
                f"🎯 **Evento activo:** `{det_activo['fecha_inicio']}` → `{det_activo['fecha_fin']}` · "
                f"**{det_activo['p_total_mm']:.1f} mm** en **{det_activo['duracion_real_h']} h** "
                f"(Imáx: **{det_activo['intensidad_max_mmh']:.1f} mm/h**)."
            )

        umbral = st.slider(
            "Umbral de encharcamiento (mm)",
            1.0, 30.0, 5.0, 0.5,
            help=(
                "Espesor mínimo de lámina superficial acumulada (mm) a partir del cual una celda se "
                "clasifica como área encharcada (Leve ≥ 1×, Moderado ≥ 2×, Severo ≥ 5× umbral)."
            ),
        )

    with t_malla:
        limite_etq = st.selectbox(
            "Límite espacial de modelado",
            [
                ("aoi", "Usar límite del AOI (solo lote principal)"),
                ("aoi_aporte_cuenca", "AOI + Aporte externo de subcuenca (WBD / Local)"),
                ("subcuenca", "Usar límite de la subcuenca completa (WBD / Local)"),
            ],
            format_func=lambda x: x[1],
            help=(
                "Define qué límite geométrico gobierna ejecutar_pipeline(...): solo el polígono del AOI, "
                "el AOI recibiendo escorrentía de su subcuenca (USGS/WBD/2017/HUC12 o archivo local), "
                "o toda la subcuenca como unidad hidrológica completa."
            ),
        )
        limite_analisis = limite_etq[0]

        nivel_wbd = st.selectbox(
            "Nivel USGS WBD (auto-consulta GEE)",
            ["HUC12", "HUC10"],
            disabled=(limite_analisis == "aoi"),
            help=(
                "Si aún no cargó una cuenca y elige modelar con subcuenca, se consultará automáticamente "
                "USGS/WBD/2017/HUC12 (o HUC10) en Google Earth Engine con .filterBounds(aoi)."
            ),
        )

        modo_prof_etq = st.selectbox(
            "Criterio de profundidad efectiva",
            [
                ("restrictivo", "Más restrictiva: min(Agronómica, Edáfica SSURGO)"),
                ("agronomica", "Agronómica / Radicular del cultivo"),
                ("edafica", "Edáfica real del perfil (SSURGO)"),
            ],
            format_func=lambda x: x[1],
            help=(
                "Define cómo calcular el volumen total de retención del perfil: el modo 'Más restrictiva' "
                "compara la profundidad radicular del cultivo con la profundidad efectiva real de SSURGO "
                "(limitada por roca o capas densas) y utiliza el menor de ambos valores."
            ),
        )
        modo_prof = modo_prof_etq[0]

        cultivo_sel = st.selectbox(
            "Cultivo de referencia (prof. radicular)",
            list(PROF_RADICULAR_CULTIVOS.keys()),
            help="Preselecciona la profundidad radicular típica de distintos cultivos extensivos o permite ajustarla manualmente.",
        )
        prof_preset = PROF_RADICULAR_CULTIVOS[cultivo_sel]
        prof_cm = st.slider(
            "Profundidad agronómica / radicular (cm)",
            30, 200, int(prof_preset) if prof_preset is not None else 100, 10,
            disabled=(modo_prof == "edafica" or prof_preset is not None),
            help="Profundidad radicular objetivo (cm) para integrar capacidad de campo, PMP, AWC, porosidad y Ksat.",
        )
        if prof_preset is not None:
            prof_cm = int(prof_preset)

        dias_s2 = st.slider(
            "Ventana Sentinel-2 (días)",
            15, 120, 45, 5,
            help="Cantidad de días previos a hoy empleados para construir el mosaico libre de nubes de Sentinel-2 (NDVI, NDWI, SAVI, LAI).",
        )
        res_m = st.selectbox(
            "Resolución de malla (m)",
            [0, 10, 20, 30, 50],
            format_func=lambda x: "Automática" if x == 0 else f"{x} m",
            help="Tamaño de celda (m) de la grilla de modelado UTM. 'Automática' ajusta entre 10 y 50 m según la superficie del lote/cuenca.",
        )
        suavizado = st.slider(
            "Suavizado del DEM (iteraciones)",
            0, 3, 1,
            help="Aplica pasadas de filtro 3×3 al modelo de elevación (3DEP) para atenuar microrruido de píxel sin perder las líneas de drenaje.",
        )

    with t_mod:
        peso_ndwi = st.slider(
            "Peso del NDWI en humedad antecedente",
            0.0, 1.0, 0.3, 0.05,
            help=(
                "Ponderación espacial entre la humedad volumétrica superficial de ERA5-Land (0 = solo ERA5) "
                "y el índice hídrico espectral NDWI de Sentinel-2 (1 = solo NDWI) para estimar la condición antecedente."
            ),
        )
        n_iter = st.slider(
            "Iteraciones de ruteo",
            100, 1500, 500, 50,
            help="Número máximo de pasos del autómata celular 2D para el escurrimiento superficial hacia bajos y depresiones.",
        )

    run = st.button(
        "▶️ Ejecutar modelo",
        type="primary",
        use_container_width=True,
        disabled=st.session_state["aoi"] is None,
        help="Descarga/actualiza las capas espaciales y ejecuta el balance hídrico con los parámetros y el hietograma del evento elegido.",
    )
    if st.session_state["aoi"] is None:
        st.caption("Defina primero el AOI en la pestaña 📍.")

# ── Contenedor de carga arriba del panel de selección de evento ──
contenedor_carga = st.container()

# ── Panel interactivo de barras de precipitación CHIRPS + Hietograma ERA5 ──
det_panel = None
if modo_p.startswith("Seleccionar evento") and st.session_state.get("aoi") is not None:
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
            detalle_evento=det_usar if modo_p.startswith("Seleccionar evento") else None,
            dias_s2=dias_s2,
            res_m=res_m,
            suavizado=suavizado,
            peso_ndwi=peso_ndwi,
            n_iter=n_iter,
        ))

with contenedor_carga:
    for aviso in st.session_state.get("avisos", []):
        st.warning(aviso)

# ── Pestañas principales ─────────────────────────────────────
tabs = st.tabs(["📍 AOI", "🧱 Suelo", "🌦️ Clima y vegetación", "💧 Balance hídrico", "🗺️ Mapa 2D", "🧊 Modelo 3D"])
for tab, fn in zip(tabs, (ui.render_tab_aoi, ui.render_tab_suelo, ui.render_tab_clima,
                          ui.render_tab_balance, ui.render_tab_mapa, ui.render_tab_3d)):
    with tab:
        try:
            fn()
        except Exception as e:  # noqa: BLE001  (una pestaña con error no debe tumbar la app)
            st.error(f"Error al renderizar la pestaña: {e}")
