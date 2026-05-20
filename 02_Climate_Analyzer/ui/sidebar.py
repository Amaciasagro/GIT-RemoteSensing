# ============================================================
# ui/sidebar.py — Sidebar: multi-lote + parámetros
# ============================================================

import streamlit as st
import json
from shapely.geometry import shape
from config import COLORES_LOTES, T_BASE_DEFAULT
from map_utils import cargar_aoi_desde_archivo, centroide_y_area


def render_sidebar() -> tuple:
    """
    Renderiza el sidebar completo.
    Retorna (anios, t_base, t_helada, t_calor, run_btn)
    """
    with st.sidebar:
        st.markdown("## 🌦️ Climate Analyzer")
        st.caption("ERA5-Land · CHIRPS · Google Earth Engine")
        st.divider()

        # ── Parámetros generales ──────────────────────────────
        st.markdown("### ⚙️ Parámetros")
        col1, col2 = st.columns(2)
        with col1:
            anios = st.number_input("Años atrás", 1, 10, 5)
        with col2:
            t_base_ui = st.number_input(
                "T base GDA (°C)", 0.0, 15.0,
                float(st.session_state.get("t_base", T_BASE_DEFAULT)), 1.0,
                help="Temperatura base para Grados Día Acumulados",
            )

        col3, col4 = st.columns(2)
        with col3:
            t_helada = st.number_input(
                "Umbral helada (°C)", -5.0, 10.0,
                float(st.session_state.get("t_helada", 3.0)), 0.5,
                help="Tmin < umbral → día de helada",
            )
        with col4:
            t_calor = st.number_input(
                "Umbral calor (°C)", 25.0, 45.0,
                float(st.session_state.get("t_calor", 35.0)), 0.5,
                help="Tmax > umbral → día de estrés térmico",
            )

        st.divider()

        # ── Gestión de lotes ─────────────────────────────────
        st.markdown("### 📍 Lotes")

        lotes = st.session_state.get("lotes", [])

        # Nombre del nuevo lote
        nuevo_nombre = st.text_input(
            "Nombre del lote",
            value=f"Lote {len(lotes) + 1}",
            key="input_nombre_lote",
        )
        # Color automático (siguiente en el ciclo)
        color_auto = COLORES_LOTES[len(lotes) % len(COLORES_LOTES)]

        tab_dibujo, tab_archivo = st.tabs(["✏️ Dibujar", "📂 Archivo"])

        with tab_dibujo:
            st.caption("Dibujá un polígono en el mapa y confirmá.")
            if st.button("✅ Agregar polígono dibujado", use_container_width=True,
                         type="primary", key="btn_confirm_draw"):
                dibujado = st.session_state.get("ultimo_dibujo")
                if dibujado:
                    geom = dibujado.get("geometry") or dibujado
                    _agregar_lote(nuevo_nombre, geom, color_auto)
                    st.success(f"'{nuevo_nombre}' agregado.")
                else:
                    st.warning("Dibujá un polígono primero.")

        with tab_archivo:
            subidos = st.file_uploader(
                "Subir .shp (zip) o .geojson",
                type=["zip", "geojson", "shp"],
                accept_multiple_files=True,
                key="file_uploader_lote",
            )
            if st.button("📌 Agregar desde archivo", use_container_width=True,
                         key="btn_upload_lote"):
                if subidos:
                    geom = cargar_aoi_desde_archivo(subidos)
                    if geom:
                        _agregar_lote(nuevo_nombre, geom, color_auto)
                        st.success(f"'{nuevo_nombre}' cargado.")
                    else:
                        st.error("No se encontró geometría válida.")
                else:
                    st.warning("Seleccioná un archivo primero.")

        # ── Lista de lotes activos ────────────────────────────
        lotes = st.session_state.get("lotes", [])
        if lotes:
            st.markdown(f"**{len(lotes)} lote(s) definido(s):**")
            for i, lote in enumerate(lotes):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(
                        f"<span style='color:{lote['color']}'>⬤</span> "
                        f"**{lote['nombre']}** — {lote.get('area_ha', 0):.1f} ha",
                        unsafe_allow_html=True,
                    )
                with col_b:
                    if st.button("🗑️", key=f"del_lote_{i}",
                                 help=f"Eliminar {lote['nombre']}"):
                        st.session_state["lotes"].pop(i)
                        st.session_state["datos_lotes"] = {}
                        st.rerun()

            if st.button("🗑️ Limpiar todos", use_container_width=True,
                         key="btn_clear_all"):
                st.session_state["lotes"] = []
                st.session_state["datos_lotes"] = {}
                st.rerun()
        else:
            st.info("Sin lotes definidos aún.")

        st.divider()

        # ── Botón analizar ────────────────────────────────────
        run_btn = st.button(
            "🛰️ Analizar lotes",
            use_container_width=True,
            type="primary",
            disabled=len(st.session_state.get("lotes", [])) == 0,
        )

    return anios, t_base_ui, t_helada, t_calor, run_btn


def _agregar_lote(nombre: str, geom: dict, color: str) -> None:
    """Agrega un lote a session_state['lotes']."""
    if "lotes" not in st.session_state:
        st.session_state["lotes"] = []

    # Evitar duplicados por nombre
    nombres_existentes = [l["nombre"] for l in st.session_state["lotes"]]
    nombre_final = nombre
    sufijo = 2
    while nombre_final in nombres_existentes:
        nombre_final = f"{nombre} ({sufijo})"
        sufijo += 1

    try:
        lat, lon, area_ha = centroide_y_area(geom)
    except Exception:
        lat, lon, area_ha = -30.0, -63.0, 0.0

    st.session_state["lotes"].append({
        "nombre":  nombre_final,
        "geom":    geom,
        "color":   color,
        "lat":     lat,
        "lon":     lon,
        "area_ha": area_ha,
    })
    # Invalidar datos anteriores para forzar recálculo
    st.session_state["datos_lotes"] = {}
