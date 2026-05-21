# ============================================================
# 🌦️ Climate Analyzer — Streamlit App
# Autor: Ariel Macías | Agrónomo · GIS & Remote Sensing
# Fuente de datos: ERA5-Land (ECMWF) + CHIRPS via Google Earth Engine
# ============================================================

import streamlit as st
import pandas as pd
import json
import warnings
from streamlit_folium import st_folium

warnings.filterwarnings("ignore")

# ── Configuración de página (debe ir primero) ────────────────
st.set_page_config(
    page_title="Climate Analyzer · ERA5 + CHIRPS",
    page_icon="🌦️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports propios ──────────────────────────────────────────
from config import CSS_GLOBAL, CSS_WATERMARK
from gee_client import init_gee, descargar_era5
from map_utils import build_mapa, bbox_lotes, exportar_mapa_html
from ui.sidebar import render_sidebar
from ui.tab_series import render_tab_series
from ui.tab_anomalias import render_tab_anomalias
from ui.tab_balance import render_tab_balance
from ui.tab_riesgos import render_tab_riesgos
from ui.tab_comparar import render_tab_comparar

# ── CSS global ───────────────────────────────────────────────
st.markdown(CSS_GLOBAL, unsafe_allow_html=True)
st.markdown(CSS_WATERMARK, unsafe_allow_html=True)

st.markdown(
    "<h1 style='font-size:28px; padding:20px 0 10px;'>"
    "🌦️ Climate Analyzer · ERA5 + CHIRPS</h1>",
    unsafe_allow_html=True,
)


# ════════════════════════════════════════════════════════════
# SESSION STATE — valores iniciales
# ════════════════════════════════════════════════════════════
DEFAULTS = {
    "lotes":        [],       # Lista de dicts {nombre, geom, color, lat, lon, area_ha}
    "datos_lotes":  {},       # {nombre_lote: datos_json_str (ERA5)}
    "gee_ok":       False,
    "ultimo_dibujo": None,
    "map_center":   [-32.0, -63.0],
    "map_zoom":     5,
    "t_base":       10.0,
    "t_helada":     3.0,
    "t_calor":      35.0,
    "analizado":    False,
}
for key, val in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ════════════════════════════════════════════════════════════
# GEE — Inicialización
# ════════════════════════════════════════════════════════════
if not st.session_state["gee_ok"]:
    ok, err = init_gee()  # 👈 Cambiado: antes tenías ok, metodo, err
    st.session_state["gee_ok"] = ok
    if not ok:
        st.error(f"❌ Error al conectar con Google Earth Engine: {err}")
        st.info("Verificá las credenciales en los Secrets de Streamlit.")
        st.stop()


# ════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════
anios, t_base, t_helada, t_calor, run_btn = render_sidebar()

# Persistir parámetros en session_state
st.session_state["t_base"]   = t_base
st.session_state["t_helada"] = t_helada
st.session_state["t_calor"]  = t_calor


# ════════════════════════════════════════════════════════════
# PANTALLA INICIAL — sin lotes definidos
# ════════════════════════════════════════════════════════════
lotes = st.session_state["lotes"]

if not lotes:
    st.markdown("### 📍 Definí el área de interés")
    st.caption(
        "Dibujá un polígono en el mapa o subí un archivo (.shp / .geojson) "
        "en la barra lateral. Podés agregar múltiples lotes para compararlos."
    )
    mapa_inicial = build_mapa(
        center=st.session_state["map_center"],
        zoom=st.session_state["map_zoom"],
        allow_draw=True,
    )
    resultado = st_folium(
        mapa_inicial, height=520, use_container_width=True,
        returned_objects=["last_active_drawing"],
        key="mapa_inicial",
    )
    if resultado and resultado.get("last_active_drawing"):
        st.session_state["ultimo_dibujo"] = resultado["last_active_drawing"]
    st.info("👈 Dibujá o subí un lote en la barra lateral para empezar.")
    st.stop()


# ════════════════════════════════════════════════════════════
# PANTALLA CON LOTES — mapa de dibujo si aún no se analizó
# ════════════════════════════════════════════════════════════
if not st.session_state["analizado"]:
    st.markdown(
        f"**{len(lotes)} lote(s) definido(s).** "
        "Podés seguir agregando lotes o presionar **Analizar lotes** en la barra lateral."
    )
    # Mostrar lotes actuales en el mapa de dibujo
    center = bbox_lotes(lotes)
    mapa_previo = build_mapa(
        center=center,
        zoom=10 if len(lotes) == 1 else 8,
        lotes=lotes,
        allow_draw=True,
    )
    resultado = st_folium(
        mapa_previo, height=420, use_container_width=True,
        returned_objects=["last_active_drawing"],
        key="mapa_con_lotes",
    )
    if resultado and resultado.get("last_active_drawing"):
        st.session_state["ultimo_dibujo"] = resultado["last_active_drawing"]


# ════════════════════════════════════════════════════════════
# ANÁLISIS — descarga ERA5 para cada lote nuevo
# ════════════════════════════════════════════════════════════
if run_btn and lotes:
    fecha_fin = pd.Timestamp.today().normalize()
    fecha_ini = fecha_fin - pd.DateOffset(years=int(anios))
    f_ini_str = fecha_ini.strftime("%Y-%m-%d")
    f_fin_str = fecha_fin.strftime("%Y-%m-%d")

    # Fechas para mapas temáticos: siempre últimos 12 meses
    # Los acumulados raster tienen sentido comparados contra el histórico
    # solo con períodos equivalentes (1 año), sin importar lo que el
    # usuario eligió para las series temporales.
    f_ini_mapas = (fecha_fin - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    f_fin_mapas = f_fin_str

    lotes_pendientes = [
        l for l in lotes if l["nombre"] not in st.session_state["datos_lotes"]
    ]

    if lotes_pendientes:
        prog = st.progress(0, text="Descargando ERA5-Land…")
        for idx, lote in enumerate(lotes_pendientes):
            prog.progress(
                (idx) / len(lotes_pendientes),
                text=f"⏳ Descargando ERA5 — {lote['nombre']}…",
            )
            try:
                datos_json = descargar_era5(
                    json.dumps(lote["geom"]),
                    f_ini_str,
                    f_fin_str,
                )
                st.session_state["datos_lotes"][lote["nombre"]] = datos_json
            except Exception as e:
                st.error(f"Error en {lote['nombre']}: {e}")

        prog.progress(1.0, text="✅ Descarga completa")

    # Actualizar center/zoom al primer lote
    if lotes:
        first = lotes[0]
        st.session_state["map_center"] = [first["lat"], first["lon"]]
        st.session_state["map_zoom"]   = 12

    st.session_state["analizado"] = True
    st.rerun()


# ════════════════════════════════════════════════════════════
# DASHBOARD CON DATOS
# ════════════════════════════════════════════════════════════
if st.session_state["analizado"] and st.session_state["datos_lotes"]:

    # Fechas del período analizado
    fecha_fin = pd.Timestamp.today().normalize()
    fecha_ini = fecha_fin - pd.DateOffset(years=int(anios))
    f_ini_str = fecha_ini.strftime("%Y-%m-%d")
    f_fin_str = fecha_fin.strftime("%Y-%m-%d")

    # Fechas para mapas temáticos: siempre últimos 12 meses
    # Los acumulados raster tienen sentido comparados contra el histórico
    # solo con períodos equivalentes (1 año), sin importar lo que el
    # usuario eligió para las series temporales.
    f_ini_mapas = (fecha_fin - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    f_fin_mapas = f_fin_str

    # ── Dos pestañas principales ──────────────────────────────
    st.markdown("""
    <style>
    /* Tabs principales más grandes y destacados */
    div[data-testid="stTabs"] > div:first-child > div {
        gap: 6px;
    }
    div[data-testid="stTabs"] > div:first-child button {
        font-size: 15px !important;
        font-weight: 600 !important;
        padding: 10px 28px !important;
        border-radius: 8px 8px 0 0 !important;
    }
    /* Sub-tabs más compactos */
    div[data-testid="stTabs"] div[data-testid="stTabs"] button {
        font-size: 12px !important;
        font-weight: 500 !important;
        padding: 6px 16px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    tab_graficos, tab_mapas = st.tabs([
        "📊  Gráficos",
        "🗺️  Mapas Temáticos",
    ])

    # ── PESTAÑA 1: GRÁFICOS ───────────────────────────────────
    with tab_graficos:
        st.markdown(
            "<p style='color:#7a99b8; font-size:13px; margin-bottom:12px;'>"
            "Series temporales ERA5-Land · Métricas agronómicas · Comparación entre lotes"
            "</p>",
            unsafe_allow_html=True,
        )
        sub_series, sub_comparar = st.tabs([
            "📈 Series temporales",
            "🔀 Comparar lotes",
        ])

        with sub_series:
            render_tab_series(
                lotes=st.session_state["lotes"],
                datos_lotes=st.session_state["datos_lotes"],
                t_base=t_base,
            )

        with sub_comparar:
            render_tab_comparar(
                lotes=st.session_state["lotes"],
                datos_lotes=st.session_state["datos_lotes"],
                t_base=t_base,
            )

    # ── PESTAÑA 2: MAPAS TEMÁTICOS ────────────────────────────
    with tab_mapas:
        st.markdown(
            "<p style='color:#7a99b8; font-size:13px; margin-bottom:12px;'>"
            "Visualización espacial píxel a píxel · CHIRPS + ERA5 · Google Earth Engine"
            "</p>",
            unsafe_allow_html=True,
        )
        sub_anom, sub_bal, sub_riesgo = st.tabs([
            "🌧️ Anomalías CHIRPS",
            "💧 Balance hídrico",
            "🌡️ Riesgo térmico",
        ])

        with sub_anom:
            render_tab_anomalias(
                lotes=st.session_state["lotes"],
                fecha_inicio=f_ini_mapas,
                fecha_fin=f_fin_mapas,
            )

        with sub_bal:
            render_tab_balance(
                lotes=st.session_state["lotes"],
                fecha_inicio=f_ini_mapas,
                fecha_fin=f_fin_mapas,
            )

        with sub_riesgo:
            render_tab_riesgos(
                lotes=st.session_state["lotes"],
                fecha_inicio=f_ini_mapas,
                fecha_fin=f_fin_mapas,
                t_helada=t_helada,
                t_calor=t_calor,
            )

    # ── Footer ───────────────────────────────────────────────
    st.divider()
    n_lotes = len(st.session_state["datos_lotes"])
    st.caption(
        f"🛰️ ERA5-Land (ECMWF) · CHIRPS (UCSB-CHG) · Google Earth Engine · "
        f"{n_lotes} lote(s) analizados · "
        f"Período: {fecha_ini.strftime('%b %Y')} → {fecha_fin.strftime('%b %Y')} · "
        f"T base GDA: {t_base:.0f}°C"
    )
