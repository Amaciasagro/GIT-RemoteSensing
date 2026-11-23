"""Pestañas de la interfaz: AOI + Cuenca Zonal, Suelo (Ksat/Porosidad/Prof. Efectiva), Clima, Balance + Timelapse, Mapa 2D y Modelo 3D."""
import numpy as np
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

from .config import tarjeta, TEXTURA_ES
from .geo_utils import gdf_desde_geojson, gdf_desde_archivo, normalizar_aoi, normalizar_cuenca, normalizar_red_drenaje
from .gee_client import obtener_textura_s2_evento, obtener_textura_esri_malla, obtener_textura_google_malla
from .map_utils import mapa_base, agregar_aoi, agregar_red_drenaje, mapa_resultado, mapa_comparativo_2d, CAPAS, TERRENO, VERDES, CALIDOS, HUMEDAD
from .pipeline import limpiar_resultados, listar_eventos_chirps, extraer_detalle_evento, obtener_cuenca_wbd_gee, obtener_red_drenaje
from . import plots


def _cols_tarjetas(items):
    """Muestra una fila de tarjetas: items = [(titulo, valor, unidad, sub, tipo), ...]."""
    cols = st.columns(len(items))
    for c, it in zip(cols, items):
        c.markdown(tarjeta(*it), unsafe_allow_html=True)


def _fijar_aoi(fn):
    try:
        st.session_state["aoi"] = normalizar_aoi(fn())
    except Exception as e:  # noqa: BLE001
        st.error(f"AOI no válido: {e}")
        return False
    limpiar_resultados()
    return True


def _fijar_cuenca(fn, fuente="Archivo local", nivel="Local"):
    try:
        aoi = st.session_state.get("aoi")
        st.session_state["cuenca"] = normalizar_cuenca(fn(), aoi=aoi, fuente=fuente, nivel=nivel)
    except LookupError as e_lk:
        avisos = st.session_state.setdefault("avisos", [])
        msg = f"⚠️ Sin intersección entre la cuenca y el AOI: {e_lk}"
        if msg not in avisos:
            avisos.append(msg)
        st.warning(msg)
        return False
    except Exception as e:  # noqa: BLE001
        st.error(f"Cuenca no válida: {e}")
        return False
    limpiar_resultados()
    return True


# ── Panel visual de selección de eventos históricos (CHIRPS + ERA5 Horario) ─
def render_panel_selector_historico(solo_dia_pico=False):
    """
    Despliega el gráfico de barras interactivo de precipitación histórica (estilo Climate Analyzer),
    permite seleccionar una tormenta haciendo clic en la barra o mediante el selector,
    y extrae automáticamente milímetros acumulados, inicio/fin, duración real (ERA5-Land Hourly)
    y el hietograma horario de intensidad que alimenta al modelo hidrológico.
    """
    aoi = st.session_state.get("aoi")
    clima = st.session_state.get("clima")
    if aoi is None or clima is None or clima.empty:
        return None

    with st.expander("🌧️ Selección Visual de Evento Histórico (CHIRPS + Hietograma Horario ERA5-Land)", expanded=True):
        c_per, c_ev, c_opt = st.columns([1.2, 2.2, 1.1])
        periodo = c_per.selectbox(
            "Ventana temporal del gráfico",
            ["Último año (365 días)", "Últimos 6 meses", "Últimos 3 meses", "Rango personalizado"],
            key="chirps_ventana_grafico",
            help="Filtre el período visible en el gráfico de barras para identificar tormentas con mayor claridad.",
        )

        df_c = clima.copy().sort_values("fecha").reset_index(drop=True)
        f_max_d = df_c["fecha"].max()
        if periodo == "Últimos 6 meses":
            df_c = df_c[df_c["fecha"] >= (f_max_d - pd.Timedelta(days=180))]
        elif periodo == "Últimos 3 meses":
            df_c = df_c[df_c["fecha"] >= (f_max_d - pd.Timedelta(days=90))]
        elif periodo == "Rango personalizado":
            r_ini, r_fin = st.date_input(
                "Seleccione inicio y fin del período",
                value=(df_c["fecha"].min().date(), f_max_d.date()),
                min_value=df_c["fecha"].min().date(),
                max_value=f_max_d.date(),
                key="chirps_rango_fechas",
            )
            df_c = df_c[(df_c["fecha"].dt.date >= r_ini) & (df_c["fecha"].dt.date <= r_fin)]

        eventos = listar_eventos_chirps(df_c, min_mm=2.0)
        if not eventos:
            st.warning("No se registraron lluvias ≥ 2 mm en la ventana seleccionada.")
            return None

        fechas_disp = [e["fecha_str"] for e in eventos]
        f_guardada = st.session_state.get("evento_chirps_fecha_str")
        idx_def = fechas_disp.index(f_guardada) if f_guardada in fechas_disp else 0

        ev_elegido = c_ev.selectbox(
            "Tormenta seleccionada (ordenada de mayor a menor magnitud)",
            eventos,
            index=idx_def,
            format_func=lambda x: f"🏆 {x['label']}" if x == eventos[0] else x["label"],
            key="sel_evento_chirps_main",
            help="Las tormentas están ordenadas de mayor a menor milimetraje diario para identificar de inmediato los eventos extremos.",
        )
        ventana_completa = c_opt.checkbox(
            "Integrar días contiguos de la tormenta",
            value=not solo_dia_pico,
            key="chk_ventana_tormenta",
            help="Si se activa, suma automáticamente los días consecutivos de lluvia de la misma tormenta (inicio a fin del frente).",
        )

        fecha_activa_str = ev_elegido["fecha_str"]
        cache_ev = st.session_state.setdefault("cache_detalle_eventos", {})

        def _obtener_detalle_cacheado(f_str):
            clave_ev = (aoi["id"], str(f_str), bool(ventana_completa))
            if clave_ev not in cache_ev:
                cache_ev[clave_ev] = extraer_detalle_evento(
                    df_c, aoi["lon"], aoi["lat"],
                    f_str,
                    solo_dia_pico=not ventana_completa,
                )
            return cache_ev[clave_ev]

        # Extraer detalles automáticos y hietograma horario ERA5-Land para la fecha activa (con caché en sesión)
        det = _obtener_detalle_cacheado(fecha_activa_str)

        # Gráfico de barras interactivo CHIRPS (soporta clic directo sobre cualquier barra)
        fig_barras = plots.fig_selector_eventos_chirps(
            df_c,
            fecha_sel=fecha_activa_str,
            f_ini_ev=det["fecha_inicio"] if det else None,
            f_fin_ev=det["fecha_fin"] if det else None,
        )
        try:
            sel_chart = st.plotly_chart(
                fig_barras,
                use_container_width=True,
                on_select="rerun",
                selection_mode="points",
                key="plotly_selector_chirps",
            )
            pts = sel_chart.get("selection", {}).get("points", []) if isinstance(sel_chart, dict) else getattr(getattr(sel_chart, "selection", None), "points", [])
            if pts:
                f_clic = str(pts[0].get("x", ""))[:10]
                if f_clic and f_clic != fecha_activa_str:
                    st.session_state["evento_chirps_fecha_str"] = f_clic
                    fecha_activa_str = f_clic
                    det = _obtener_detalle_cacheado(fecha_activa_str)
        except TypeError:
            # Respaldo para versiones de Streamlit sin on_select en plotly_chart
            st.plotly_chart(fig_barras, use_container_width=True)

        st.session_state["evento_chirps_fecha_str"] = fecha_activa_str
        st.session_state["detalle_evento_activo"] = det

        if det is not None:
            _cols_tarjetas([
                ("Lluvia total evento", f"{det['p_total_mm']:.1f}", "mm", f"Día pico ({det['fecha_pico_str']}): {det['p_pico_mm']:.1f} mm", "agua"),
                ("Inicio → Fin", det["fecha_inicio"], "", f"Hasta {det['fecha_fin']} ({det['n_dias']} día/s)", ""),
                ("Duración real (ERA5)", f"{det['duracion_real_h']}", "h", f"Horas efectivas de lluvia ({det['fuente_horaria']})", "suelo"),
                ("Intensidad pico / media", f"{det['intensidad_max_mmh']:.1f}", "mm/h", f"Intensidad media: {det['intensidad_media_mmh']:.2f} mm/h", "alerta"),
            ])
            st.plotly_chart(plots.fig_hietograma_evento(det), use_container_width=True, key="plt_hieto_selector_top")
            st.caption(
                "✅ **Integrado con el motor hidrológico:** Al pulsar **▶️ Ejecutar modelo**, el balance SCS-CN, "
                "la infiltración horaria de Green-Ampt ($K_{sat}$) y el ruteo 2D utilizarán automáticamente "
                f"**P = {det['p_total_mm']:.1f} mm**, **Duración = {det['duracion_real_h']} h** y este **hietograma horario**."
            )
        return det


# ── 1. AOI y Cuenca Zonal ────────────────────────────────────────────────────
def render_tab_aoi():
    st.subheader("📍 Área de interés (EE. UU.) y Cuenca Zonal Aportante")
    metodo = st.radio(
        "Método de delimitación del lote principal (AOI)",
        ["✏️ Dibujar en el mapa", "📁 Subir Shapefile (.zip) / GeoJSON", "📋 Pegar GeoJSON"],
        horizontal=True,
        key="aoi_metodo",
        help="Elija cómo definir el polígono del lote agrícola principal que desea evaluar.",
    )
    aoi = st.session_state.get("aoi")
    cuenca = st.session_state.get("cuenca")
    ok = False
    if metodo.startswith("✏️"):
        centro, zoom = ([aoi["lat"], aoi["lon"]], 14 if cuenca else 15) if aoi else ([39.5, -98.35], 4)
        m = mapa_base(centro, zoom, dibujo=True, satelite_primero=True)
        if aoi:
            agregar_aoi(m, aoi["geom"], cuenca_geom=cuenca["geom"] if cuenca else None, cuenca_meta=cuenca)
            folium.LayerControl(collapsed=True).add_to(m)
        sal = st_folium(m, height=500, use_container_width=True, returned_objects=["last_active_drawing"], key="mapa_dibujo")
        dib = sal.get("last_active_drawing") if sal else None
        if dib and st.button("✅ Usar polígono dibujado", type="primary"):
            ok = _fijar_aoi(lambda: gdf_desde_geojson(dib))
    elif metodo.startswith("📁"):
        f = st.file_uploader(
            "Shapefile comprimido (.zip), GeoPackage (.gpkg) o GeoJSON del lote",
            type=["zip", "gpkg", "shp", "geojson", "json"],
            key="up_aoi_file",
            help="Suba el límite de su lote en formato .zip (Shapefile), .gpkg (GeoPackage) o .geojson.",
        )
        if f and st.button("✅ Cargar AOI", type="primary"):
            ok = _fijar_aoi(lambda: gdf_desde_archivo(f))
    else:
        txt = st.text_area(
            "GeoJSON (Feature, FeatureCollection o geometría)",
            height=180,
            help="Pegue directamente el texto JSON de un polígono GeoJSON en EPSG:4326.",
        )
        if txt.strip() and st.button("✅ Cargar AOI", type="primary"):
            ok = _fijar_aoi(lambda: gdf_desde_geojson(txt))
    if ok:
        st.rerun()

    aoi = st.session_state.get("aoi")
    if aoi:
        # ── Integración con USGS WBD (HUC12 / HUC10 en GEE) o carga local (.shp / .gpkg / .geojson) ──
        with st.expander("🌊 Subcuenca Hidrológica USGS WBD (HUC12 / HUC10 en GEE) o Archivo Local (.shp / .gpkg)", expanded=True):
            st.caption(
                "Obtenga automáticamente la subcuenca oficial del **Watershed Boundary Dataset (`USGS/WBD/2017/HUC12` o `HUC10`)** "
                "en Google Earth Engine filtrada por `.filterBounds(aoi)`, o suba su propio archivo vectorial local (`.zip`, `.gpkg`, `.shp`, `.geojson`)."
            )
            c_orig, c_act, c_del = st.columns([2.6, 1.3, 1.0])
            origen_cuenca = c_orig.radio(
                "Fuente de la subcuenca",
                [
                    "🛰️ GEE: USGS/WBD/2017/HUC12 (Subwatershed)",
                    "🛰️ GEE: USGS/WBD/2017/HUC10 (Watershed)",
                    "📂 Archivo local (.zip Shapefile, .gpkg, .shp, .geojson)",
                ],
                horizontal=True,
                key="origen_cuenca_sel",
                help="HUC12 corresponde a subcuencas locales (~4,000–16,000 ha); HUC10 a cuencas mayores; o cargue un archivo propio.",
            )

            if origen_cuenca.startswith("🛰️"):
                nivel_wbd = "HUC10" if "HUC10" in origen_cuenca else "HUC12"
                if c_act.button(f"🔍 Consultar {nivel_wbd} en GEE", type="primary", use_container_width=True):
                    with st.spinner(f"Consultando USGS/WBD/2017/{nivel_wbd} con .filterBounds(aoi)…"):
                        limpiar_resultados()
                        c_res = obtener_cuenca_wbd_gee(aoi, nivel=nivel_wbd)
                    if c_res is not None:
                        st.success(f"Subcuenca {nivel_wbd} cargada: **{c_res['huc_codigo']} — {c_res['nombre']}** ({c_res['area_ha']:,.1f} ha)")
                    st.rerun()
            else:
                f_cuenca = st.file_uploader(
                    "Archivo de cuenca zonal (.zip Shapefile, .gpkg GeoPackage, .shp o .geojson)",
                    type=["zip", "gpkg", "shp", "geojson", "json"],
                    key="up_cuenca_file",
                    help="Polígono(s) de la cuenca o subcuencas que intersectan o rodean al lote principal.",
                )
                if c_act.button("📌 Cargar archivo local", disabled=f_cuenca is None, type="primary", use_container_width=True):
                    if _fijar_cuenca(lambda: gdf_desde_archivo(f_cuenca), fuente=f"Local ({f_cuenca.name})", nivel="Local"):
                        st.rerun()

            if cuenca and c_del.button("🗑️ Quitar subcuenca", use_container_width=True):
                st.session_state.pop("cuenca", None)
                limpiar_resultados()
                st.rerun()

            cuenca = st.session_state.get("cuenca")
            if cuenca:
                _cols_tarjetas([
                    (f"Código {cuenca.get('nivel', 'HUC')}", cuenca.get("huc_codigo", "—"), "", f"Fuente: {cuenca.get('fuente', 'WBD')}", "agua"),
                    ("Nombre de subcuenca", cuenca.get("nombre", "—"), "", f"Estado(s): {cuenca.get('states', 'US')}", "agua"),
                    ("Área total subcuenca", f"{cuenca['area_ha']:,.1f}", "ha", f"{cuenca['n_subcuencas']} polígono(s)", "agua"),
                    ("Área aportante externa", f"{cuenca['area_externa_ha']:,.1f}", "ha", f"Relación Cuenca/AOI: {cuenca['area_ha']/max(aoi['area_ha'], 0.1):.1f}×", "suelo"),
                ])
                if cuenca.get("subcuencas"):
                    df_sub = pd.DataFrame(cuenca["subcuencas"]).rename(columns={
                        "huc": "Código HUC", "nombre": "Nombre Subcuenca",
                        "area_ha": "Área (ha)", "states": "Estado(s)",
                        "tohuc": "Drena hacia HUC", "fuente": "Colección / Fuente",
                    })
                    st.dataframe(df_sub, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("**🏞️ Red de Drenaje (`WWF/HydroSHEDS/v1/FreeFlowingRivers` en GEE, respaldo `NHD_FLOWLINE` o Archivo Local `.shp`/`.gpkg`)**")
            c_rd0, c_rd1, c_rd2, c_rd3 = st.columns([1.6, 2.0, 1.3, 0.9])
            pref_gee_red = c_rd0.selectbox(
                "Colección GEE preferida",
                ["HydroSHEDS (WWF/FreeFlowingRivers)", "NHD (NHD_FLOWLINE)"],
                key="pref_gee_red_sel",
                help="Prioriza WWF/HydroSHEDS/v1/FreeFlowingRivers (con respaldo en NHD_FLOWLINE) o viceversa al consultar con .filterBounds(aoi).",
            )
            f_red = c_rd1.file_uploader(
                "Red de drenaje local opcional (.zip Shapefile, .gpkg, .shp, .geojson)",
                type=["zip", "gpkg", "shp", "geojson", "json"],
                key="up_red_drenaje_file",
                help="Si no sube un archivo, se consultará automáticamente WWF/HydroSHEDS/v1/FreeFlowingRivers (con respaldo en NHD_FLOWLINE / DEM D8).",
            )
            if c_rd2.button("🛰️ Consultar HydroSHEDS / NHD", use_container_width=True):
                st.session_state.pop("red_drenaje", None)
                pref_k = "NHD" if "NHD" in pref_gee_red else "HydroSHEDS"
                with st.spinner(f"Consultando {pref_gee_red} con .filterBounds(aoi)…"):
                    red_g = obtener_red_drenaje(aoi, cuenca=cuenca, grid=st.session_state.get("grid"), preferir=pref_k)
                if red_g:
                    st.success(f"Red cargada ({red_g['fuente']}): {red_g['n_tramos']} tramos ({red_g['longitud_total_km']} km)")
                st.rerun()
            if f_red is not None and c_rd2.button("📌 Cargar red local", type="primary", use_container_width=True):
                try:
                    red_l = normalizar_red_drenaje(
                        gdf_desde_archivo(f_red), aoi=aoi, cuenca=cuenca, fuente=f"Local ({f_red.name})"
                    )
                    st.session_state["red_drenaje"] = red_l
                    st.rerun()
                except Exception as e_rl:  # noqa: BLE001
                    st.error(f"No se pudo cargar la red de drenaje local: {e_rl}")
            if st.session_state.get("red_drenaje") and c_rd3.button("🗑️ Quitar red", use_container_width=True):
                st.session_state.pop("red_drenaje", None)
                st.rerun()

            red_act = st.session_state.get("red_drenaje")
            if red_act:
                st.caption(
                    f"🏞️ **Red de drenaje activa:** `{red_act['fuente']}` · "
                    f"**{red_act['n_tramos']} tramos** · Longitud total: **{red_act['longitud_total_km']} km**."
                )

        cuenca = st.session_state.get("cuenca")
        red_act = st.session_state.get("red_drenaje")
        tarjetas_aoi = [
            ("Área del lote (AOI)", f"{aoi['area_ha']:,.1f}", "ha", "Lote principal", ""),
            ("Latitud", f"{aoi['lat']:.4f}", "°", "centroide AOI", ""),
            ("Longitud", f"{aoi['lon']:.4f}", "°", "centroide AOI", ""),
        ]
        if cuenca:
            tarjetas_aoi.append((
                f"Subcuenca {cuenca.get('nivel', 'HUC')}", f"{cuenca['area_ha']:,.1f}", "ha",
                f"{cuenca.get('huc_codigo', '')} · {cuenca.get('nombre', '')}", "agua",
            ))
        _cols_tarjetas(tarjetas_aoi)

        if not metodo.startswith("✏️"):
            m = mapa_base([aoi["lat"], aoi["lon"]], 13 if cuenca else 15, satelite_primero=True)
            agregar_aoi(m, aoi["geom"], cuenca_geom=cuenca["geom"] if cuenca else None, cuenca_meta=cuenca)
            if red_act:
                agregar_red_drenaje(m, red_act)
            folium.LayerControl(collapsed=True).add_to(m)
            st_folium(m, height=440, use_container_width=True, returned_objects=[], key="mapa_aoi_vista")
        st.success("AOI listo. Elija en la barra lateral si desea modelar sobre el **AOI** o sobre la **Subcuenca** y pulse **▶️ Ejecutar modelo**.")
    else:
        st.info("Dibuje o cargue un polígono dentro de EE. UU. para comenzar.")


# ── 2. Suelo ─────────────────────────────────────────────────────────────────
def render_tab_suelo():
    st.subheader("🧱 Propiedades hidrofísicas del suelo (SSURGO / USDA-NRCS)")
    s = st.session_state.get("suelo")
    if not s:
        st.info("Ejecute el modelo para consultar los suelos.")
        return
    tabla = s["tabla"]
    sg, g = st.session_state["suelo_grid"], st.session_state["grid"]
    m = g["mascara"]
    mean = lambda k: float(np.nanmean(sg[k][m])) if k in sg else 0.0
    tex_dom = pd.Series(sg["textura"][m]).mode().iloc[0]
    hsg_dom = pd.Series(sg["hsg"][m]).mode().iloc[0]

    prof_ef = mean("depth_cm")
    prof_agro = mean("prof_agro_cm") if "prof_agro_cm" in sg else prof_ef
    prof_edaf = mean("prof_ssurgo_cm") if "prof_ssurgo_cm" in sg else prof_ef
    limitante = "Edáfica SSURGO" if prof_edaf < prof_agro else "Agronómica / Radicular"

    _cols_tarjetas([
        ("Textura dominante", TEXTURA_ES.get(tex_dom, tex_dom), "", f"Grupo hidrológico HSG {hsg_dom}", "suelo"),
        ("Profundidad efectiva", f"{prof_ef:.0f}", "cm", f"Agron.: {prof_agro:.0f} cm · SSURGO: {prof_edaf:.0f} cm ({limitante})", "suelo"),
        ("Agua disponible (AWC)", f"{mean('awc_mm'):.0f}", "mm", f"CC: {mean('fc_mm'):.0f} mm · PMP: {mean('wp_mm'):.0f} mm", "agua"),
        ("Ksat inf. / perc.", f"{mean('ksat_sup_mmh'):.1f} / {mean('ksat_min_mmh'):.1f}", "mm/h", f"Media armónica: {mean('ksat_mmh'):.1f} mm/h", "agua"),
        ("Porosidad / Dens. ap.", f"{mean('porosidad')*100:.1f}%", "", f"DA: {mean('da_gcm3'):.2f} g/cm³ · Macroporos: {mean('gs_mm'):.0f} mm", "suelo"),
    ])
    st.caption(
        f"**Fuente:** {s['fuente']} · **Criterio de profundidad:** `{s.get('modo_prof', 'restrictivo')}`. "
        "La tasa máxima de infiltración básica está gobernada por la $K_{sat}$ superficial y la succión capilar ($\\psi$), "
        "mientras que la velocidad de percolación profunda e interflow está controlada por la $K_{sat}$ del horizonte más restrictivo."
    )

    # Mapa de texturas
    if s["gdf"] is not None:
        t = tabla.set_index("mukey")
        gdf = s["gdf"].copy()
        gdf["textura"] = gdf["mukey"].map(t["textura"])
        gdf["textura_es"] = gdf["textura"].map(lambda x: TEXTURA_ES.get(x, str(x)))
        gdf["muname"] = gdf["mukey"].map(t["muname"])
        gdf["compname"] = gdf["mukey"].map(t["compname"]) if "compname" in t.columns else gdf["muname"]
        gdf["awc_mm"] = gdf["mukey"].map(t["awc_mm"]).round(1)
        gdf["ksat_mmh"] = gdf["mukey"].map(t["ksat_mmh"]).round(1)
        paleta = ["#e9c46a", "#f4a261", "#e76f51", "#8ab17d", "#2a9d8f", "#264653", "#b5838d", "#6d6875",
                  "#90be6d", "#43aa8b", "#577590", "#f9c74f"]
        col = {k: paleta[i % 12] for i, k in enumerate(sorted(gdf["textura"].dropna().unique()))}
        mp = mapa_base([st.session_state["aoi"]["lat"], st.session_state["aoi"]["lon"]], 15, satelite_primero=True)
        folium.GeoJson(
            gdf[["mukey", "muname", "compname", "textura", "textura_es", "awc_mm", "ksat_mmh", "geometry"]].to_json(),
            name="Unidades edáficas (SSURGO)",
            style_function=lambda f: {
                "fillColor": col.get(f["properties"].get("textura"), "#888"),
                "color": "#0b1320",
                "weight": 1.4,
                "fillOpacity": 0.58,
            },
            highlight_function=lambda _: {
                "weight": 3.2,
                "color": "#ffffff",
                "fillOpacity": 0.82,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["mukey", "muname", "compname", "textura_es", "awc_mm", "ksat_mmh"],
                aliases=["🔑 MUKey:", "📍 Unidad Cartográfica:", "🌱 Serie dom.:", "🎨 Textura:", "💧 AWC (mm):", "⏬ Ksat arm. (mm/h):"],
                sticky=True,
            ),
        ).add_to(mp)
        cuenca = st.session_state.get("cuenca")
        # agregar_aoi dibuja únicamente la línea perimetral con interactive=False por encima de las UC
        # para que los límites del AOI y la cuenca se vean con total claridad sin bloquear el tooltip de las UC
        agregar_aoi(mp, st.session_state["aoi"]["geom"], cuenca_geom=cuenca["geom"] if cuenca else None)
        folium.LayerControl().add_to(mp)
        st_folium(mp, height=420, use_container_width=True, returned_objects=[], key="mapa_suelos")

    tb = tabla.copy()
    tb["textura"] = tb["textura"].map(lambda x: TEXTURA_ES.get(x, x))
    if "porosidad" in tb.columns:
        tb["porosidad_pct"] = (tb["porosidad"] * 100.0).round(1)
    cols_mostrar = [c for c in (
        "mukey", "muname", "compname", "textura", "hsg",
        "depth_cm", "prof_ssurgo_cm", "da_gcm3", "porosidad_pct",
        "fc_mm", "wp_mm", "awc_mm", "ksat_sup_mmh", "ksat_mmh", "ksat_min_mmh",
    ) if c in tb.columns]
    st.dataframe(tb[cols_mostrar].round(2), use_container_width=True, hide_index=True)

    if s["horizontes"] is not None:
        mk = st.selectbox(
            "Perfil detallado por horizonte (mukey)",
            list(tabla["mukey"]),
            help="Seleccione una unidad cartográfica para inspeccionar su granulometría, Ksat y porosidad por estrato.",
        )
        h = s["horizontes"]
        st.plotly_chart(plots.fig_perfil(h[h["mukey"] == mk]), use_container_width=True, key="plt_perfil_suelo")


# ── 3. Clima y vegetación ────────────────────────────────────────────────────
def render_tab_clima():
    st.subheader("🌦️ Clima (CHIRPS + ERA5-Land) y vegetación (Sentinel-2)")
    clima, ind = st.session_state.get("clima"), st.session_state.get("indices")
    if clima is None and ind is None:
        st.info("Sin datos todavía (ejecute el modelo) o los servicios no respondieron.")
        return
    if clima is not None and not clima.empty:
        # Si la tabla en sesión provino de una versión previa sin t_min / t_max, actualizarla automáticamente
        if ("t_min" not in clima.columns or not clima["t_min"].notna().any()) and st.session_state.get("aoi"):
            try:
                from .gee_client import serie_clima as _sc_refresh
                aoi_c = st.session_state["aoi"]
                hoy_c = pd.Timestamp.today().normalize()
                ini_c = (hoy_c - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
                clima = _sc_refresh(aoi_c["lon"], aoi_c["lat"], ini_c, hoy_c.strftime("%Y-%m-%d"))
                st.session_state["clima"] = clima
            except Exception:
                pass
        p = clima["p_chirps"].fillna(clima["p_era5"]).fillna(0)
        sw4_med = float(clima["swvl4"].dropna().tail(30).mean()) if "swvl4" in clima and not clima["swvl4"].dropna().empty else np.nan
        t_min_txt = f"Mín: {clima['t_min'].min():.1f}°C · Máx: {clima['t_max'].max():.1f}°C" if ("t_min" in clima and clima["t_min"].notna().any()) else "ERA5-Land"
        sub_sw = f"{t_min_txt} · Hum. prof.: {sw4_med:.2f} m³/m³" if np.isfinite(sw4_med) else t_min_txt
        _cols_tarjetas([
            ("P últimos 30 d", f"{p.tail(30).sum():.0f}", "mm", "CHIRPS/ERA5", "agua"),
            ("P últimos 365 d", f"{p.sum():.0f}", "mm", "acumulada anual", "agua"),
            ("Máx. diaria", f"{p.max():.0f}", "mm", str(clima['fecha'].iloc[int(p.idxmax())].date()), "alerta"),
            ("T media (rango)", f"{clima['t2m'].mean():.1f}", "°C", sub_sw, ""),
        ])
        st.plotly_chart(plots.fig_clima(clima), use_container_width=True, key="plt_clima_serie")
    if ind is not None and not ind.empty:
        u = ind.iloc[-1]
        _cols_tarjetas([("NDVI", f"{u['NDVI']:.2f}", "", str(u["fecha"].date()), ""),
                        ("NDWI", f"{u['NDWI']:.2f}", "", "último dato", "agua"),
                        ("SAVI", f"{u['SAVI']:.2f}", "", "último dato", ""),
                        ("LAI", f"{u['LAI']:.2f}", "m²/m²", "último dato", "")])
        st.plotly_chart(plots.fig_indices(ind), use_container_width=True, key="plt_indices_s2")


# ── 4. Balance y Timelapse ───────────────────────────────────────────────────
def render_tab_balance():
    st.subheader("💧 Balance hídrico del evento, dinámica de napa y secuencia temporal")
    r = st.session_state.get("resultado")
    if not r:
        st.info("Ejecute el modelo desde la barra lateral.")
        return
    b = r["balance"]
    ev = f" ({pd.to_datetime(r['fecha_evento']).strftime('%Y-%m-%d')})" if r.get("fecha_evento") is not None else " (Manual)"
    pct_enc = 100 * r["area_enc_ha"] / max(r["area_aoi_ha"], 1e-9)

    _cols_tarjetas([
        ("Precipitación", f"{r['p_mm']:.1f}", "mm", f"Evento{ev}", "agua"),
        ("Escorrentía / Cuenca", f"{b['escorrentia']:.1f}", "mm", f"CN {b['cn_medio']:.0f} · Aporte ext.: +{b.get('aporte_cuenca_mm', 0.0):.1f} mm", "alerta"),
        ("Recarga / Interflow", f"{b['humedad_suelo']:.1f}", "mm", f"Interflow lat.: {b.get('flujo_subsuperficial', 0.0):.1f} mm", ""),
        ("Napa / Ascenso cap.", f"{b.get('prof_napa_m', 2.2):.2f}", "m", f"Ascenso capilar: +{b.get('ascenso_capilar', 0.0):.1f} mm", "suelo"),
        ("Área encharcada", f"{r['area_enc_ha']:.2f}", "ha", f"{pct_enc:.1f}% del AOI (máx. {r['lamina_max']:.0f} mm)", "alerta"),
    ])

    c1, c2 = st.columns([1.25, 1])
    c1.plotly_chart(plots.fig_balance_evento(b), use_container_width=True, key="plt_balance_evento")
    with c2:
        st.markdown("**Componentes físicos de superficie y subsuperficie (mm, media del AOI)**")
        st.dataframe(pd.DataFrame({
            "Componente hidrológico": [
                "Lámina superficial acumulada final",
                "Flujo lateral subsuperficial (Interflow)",
                "Percolación profunda (controlada por Ksat_min)",
                "Ascenso capilar desde nivel freático",
                "Aporte superficial de cuenca externa al AOI",
                "Re-infiltración desde depresiones",
                "Exportación neta fuera del AOI",
                "Profundidad media estimada de napa (m)",
            ],
            "Valor": [
                b["lamina_final"],
                b.get("flujo_subsuperficial", 0.0),
                b["drenaje_profundo"],
                b.get("ascenso_capilar", 0.0),
                b.get("aporte_cuenca_mm", 0.0),
                b["reinfiltracion"],
                b["salida_neta"],
                b.get("prof_napa_m", 2.2),
            ],
        }).round(2), hide_index=True, use_container_width=True)
        st.caption(
            f"Resolución de malla: {r['res_m']:.0f} m · Duración efectiva: {r.get('duracion_h', 24):.0f} h · Escenas S2: {r['n_s2']}"
            + (f" · ERA5 sup.: {r['swvl1']:.3f} m³/m³" if r.get("swvl1") is not None else "")
            + (f" · ERA5 prof. (capa 4): {r['swvl4']:.3f} m³/m³" if r.get("swvl4") is not None and np.isfinite(r["swvl4"]) else "")
        )

    det_ev = r.get("detalle_evento")
    if det_ev is not None and "df" in det_ev:
        with st.expander(
            f"⏱️ Hietograma Horario Real aplicado en la simulación ({det_ev['fecha_inicio']} → {det_ev['fecha_fin']} · "
            f"{det_ev['p_total_mm']:.1f} mm en {det_ev['duracion_real_h']} h · Imáx {det_ev['intensidad_max_mmh']:.1f} mm/h)",
            expanded=True,
        ):
            st.plotly_chart(plots.fig_hietograma_evento(det_ev), use_container_width=True, key="plt_hieto_tab_balance")

    # ── Secuencia temporal (Timelapse) ──
    secuencia = r.get("timelapse", [])
    if secuencia:
        st.markdown("---")
        st.markdown("### ⏱️ Simulación por pasos temporales (*Timelapse* del Evento)")
        st.caption(
            "Deslice el control cronológico para inspeccionar cómo el agua ingresa al perfil, satura los poros, "
            "acumula lámina en las depresiones topográficas y luego drena o se evapotranspira en los días posteriores."
        )
        paso_idx = st.slider(
            "Avance cronológico de la simulación",
            min_value=1, max_value=len(secuencia), value=4, step=1,
            format="Paso %d",
            key="tl_slider_balance",
            help="Avance o retroceda en el tiempo desde el inicio de la lluvia hasta +7 días poslluvia.",
        )
        st.session_state["tl_paso_activo"] = paso_idx
        actual = secuencia[paso_idx - 1]
        _cols_tarjetas([
            ("Fase activa", actual["etiqueta"].split("·")[-1].strip(), "", f"Fecha ref.: {actual['fecha_txt']}", "agua"),
            ("Lámina media", f"{actual['lamina_media_mm']:.1f}", "mm", f"Máx. en bajos: {actual['lamina_max_mm']:.1f} mm", "agua"),
            ("Área encharcada", f"{actual['area_enc_ha']:.2f}", "ha", f"Umbral ≥ {r['umbral']:g} mm", "alerta"),
            ("Humedad del perfil", f"{actual['humedad_media_pct']:.1f}", "% AWC", f"Infiltración acum.: {actual['infiltracion_acum_mm']:.1f} mm", "suelo"),
        ])
        st.plotly_chart(plots.fig_timelapse(secuencia, paso_actual=paso_idx), use_container_width=True, key="plt_timelapse_balance")

    bd = st.session_state.get("balance_diario")
    if bd is not None:
        st.plotly_chart(plots.fig_balance_diario(bd), use_container_width=True, key="plt_balance_diario_anual")
        with st.expander("Tabla del balance diario (último año)"):
            st.dataframe(bd.round(2), use_container_width=True, hide_index=True)


# ── 5. Mapa 2D ───────────────────────────────────────────────────────────────
def render_tab_mapa():
    st.subheader("🗺️ Mapa temático 2D, subcuencas por magnitud y red de drenaje jerárquica")
    r = st.session_state.get("resultado")
    if not r:
        st.info("Ejecute el modelo desde la barra lateral.")
        return
    cuenca = st.session_state.get("cuenca")
    red_dren = st.session_state.get("red_drenaje") or r.get("red_drenaje")
    secuencia = r.get("timelapse", [])
    lista_capas = list(CAPAS)

    c_modo, c_tl, c_s2, c_op = st.columns([1.8, 1.15, 1.35, 0.9])
    modo_comp = c_modo.radio(
        "Modo de visualización",
        ["🗺️ Mapa único", "🔀 Comparar dos mapas temáticos"],
        horizontal=True,
        key="mapa2d_modo_vis",
        help="Visualice un único mapa temático o compare simultáneamente dos capas temáticas con zoom y desplazamiento sincronizados.",
    )
    es_comparacion = modo_comp.startswith("🔀")
    modo_tl = c_tl.checkbox(
        "⏱️ Usar paso del Timelapse",
        value=False,
        help="Si se activa, el mapa muestra la evolución espacial de la lámina de agua o humedad en el paso temporal elegido.",
    )
    usar_s2_2d = c_s2.checkbox(
        "🛰️ Base Sentinel-2 (fecha evento)",
        value=False,
        help="Superpone como imagen base la captura Sentinel-2 sin nubes de la fecha más próxima al evento (igual que en el Modelo 3D).",
    )
    op = c_op.slider("Opacidad", 0.2, 1.0, 0.8, 0.05, help="Transparencia de la capa raster sobre la imagen satelital.")

    if not es_comparacion:
        capa = st.selectbox(
            "Variable temática raster",
            lista_capas,
            index=0,
            key="mapa2d_capa_unica",
            help="Seleccione la capa espacial a visualizar sobre el mapa satelital/oscuro.",
        )
        capa_der = None
    else:
        col_m1, col_m2 = st.columns(2)
        capa = col_m1.selectbox(
            "Variable temática 1 (Mapa izquierdo)",
            lista_capas,
            index=0,
            key="mapa2d_capa_izq",
            help="Primera variable temática a comparar (panel izquierdo).",
        )
        idx_def_der = 7 if len(lista_capas) > 7 else min(2, len(lista_capas) - 1)
        capa_der = col_m2.selectbox(
            "Variable temática 2 (Mapa derecho)",
            lista_capas,
            index=idx_def_der,
            key="mapa2d_capa_der",
            help="Segunda variable temática a comparar (panel derecho).",
        )

    s2_rgb_2d, s2_fecha_2d = None, None
    malla_2d = st.session_state.get("grid", {}).get("malla")
    if usar_s2_2d and malla_2d is not None:
        f_ev_2d = pd.to_datetime(r["fecha_evento"]).strftime("%Y-%m-%d") if r.get("fecha_evento") is not None else None
        try:
            with st.spinner("Cargando imagen Sentinel-2 de la fecha disponible…"):
                s2_rgb_2d, s2_fecha_2d, nub_2d, dt_2d, fte_2d = obtener_textura_s2_evento(malla_2d, f_ev_2d)
            st.caption(f"🛰️ **Imagen Sentinel-2 activa en mapa 2D:** Captura del **`{s2_fecha_2d}`** (±{dt_2d} d · nubosidad {nub_2d:.1f}% · {fte_2d}).")
        except Exception as e_s2m:  # noqa: BLE001
            st.warning(f"No se pudo cargar la captura Sentinel-2 ({e_s2m}).")

    # Controles de estilizado de subcuencas por magnitud (promedio o máximo) y superposición de red de drenaje HydroSHEDS
    c_sub1, c_sub2, c_sub3, c_sub4, c_sub5 = st.columns([1.5, 1.1, 1.4, 1.1, 1.1])
    metricas_opciones = {
        "Lámina / Encharcamiento (mm)": "lamina",
        "Escorrentía superficial (mm)": "escorrentia",
        "Infiltración acumulada (mm)": "infiltracion",
        "Balance neto retenido (mm)": "balance",
        "Humedad del suelo (% AWC)": "humedad",
    }
    nom_met_sub = c_sub1.selectbox(
        "Métrica de subcuenca (color y borde)",
        list(metricas_opciones.keys()),
        disabled=cuenca is None,
        help="Variable derivada de ejecutar_pipeline(...) que gobierna el color y grosor de borde de cada subcuenca.",
    )
    est_sub = c_sub2.radio(
        "Estadístico subcuenca",
        ["Promedio", "Máximo"],
        horizontal=True,
        disabled=cuenca is None,
        help="Elija entre el valor promedio o el valor máximo dentro de cada subcuenca HUC12/HUC10/Local.",
    )
    criterios_red = {
        "Combinado (Jerarquía + Descarga + Acum.)": "grosor_px",
        "Jerarquía / Orden (RIV_ORD / Strahler)": "grosor_jerarquia_px",
        "Descarga media (DIS_AV_CMS m³/s)": "grosor_descarga_px",
        "Acumulación / Área (UPLAND_SKM km²)": "grosor_acumulacion_px",
    }
    crit_red_etq = c_sub3.selectbox(
        "Grosor de cauces (HydroSHEDS/NHD)",
        list(criterios_red.keys()),
        help="Define qué atributo de HydroSHEDS/NHD gobierna el grosor variable de las líneas de drenaje.",
    )
    criterio_grosor_red = criterios_red[crit_red_etq]
    mostrar_red_2d = c_sub4.checkbox(
        "🏞️ Red de drenaje",
        value=True,
        help="Muestra los cauces (WWF/HydroSHEDS/v1/FreeFlowingRivers / NHD_FLOWLINE / DEM D8) con grosor variable.",
    )
    recortar_aoi = True
    if cuenca is not None:
        recortar_aoi = c_sub5.checkbox(
            "Recortar solo al AOI",
            value=False,
            key="mapa2d_recortar_aoi",
            help="Desmarque para visualizar el raster sobre toda la subcuenca modelada.",
        )

    campo_met_sub = None
    etq_met_sub = None
    if cuenca is not None:
        base_m = metricas_opciones[nom_met_sub]
        suf_m = "mean_pct" if (base_m == "humedad" and est_sub == "Promedio") else (
            "max_pct" if base_m == "humedad" else ("mean_mm" if est_sub == "Promedio" else "max_mm")
        )
        campo_met_sub = f"{base_m}_{suf_m}"
        etq_met_sub = f"{nom_met_sub} ({est_sub})"

    def _extraer_arr_timelapse(nombre_c, paso_d):
        clave_c = CAPAS[nombre_c][0]
        if clave_c == "lamina":
            return paso_d["lamina"]
        if clave_c == "categoria":
            from .hydro_model import clases_encharcamiento
            return clases_encharcamiento(paso_d["lamina"], r["umbral"])
        if clave_c == "humedad1_pct":
            return paso_d["humedad_pct"]
        return None

    arr_override = None
    arr_override_der = None
    sub_tl_izq = None
    sub_tl_der = None
    sufijo_key = f"est_{campo_met_sub}_{mostrar_red_2d}_{criterio_grosor_red}"
    if modo_tl and secuencia:
        if not es_comparacion:
            paso_m = st.slider(
                "Paso temporal a visualizar en el mapa 2D",
                min_value=1, max_value=len(secuencia),
                value=int(st.session_state.get("tl_paso_activo", 4)),
                key="tl_slider_mapa2d",
                help="Explore espacialmente cómo crece y se disipa el encharcamiento paso a paso.",
            )
            paso_info = secuencia[paso_m - 1]
            st.info(
                f"⏱️ **{paso_info['etiqueta']}** ({paso_info['fecha_txt']}) — "
                f"Lámina media: **{paso_info['lamina_media_mm']:.1f} mm** · "
                f"Área encharcada: **{paso_info['area_enc_ha']:.2f} ha** · "
                f"Humedad del suelo: **{paso_info['humedad_media_pct']:.1f}% AWC**"
            )
            arr_override = _extraer_arr_timelapse(capa, paso_info)
            sufijo_key = f"tl_{paso_m}_{campo_met_sub}_{mostrar_red_2d}_{criterio_grosor_red}"
        else:
            ct1, ct2 = st.columns(2)
            paso_m1 = ct1.slider(
                "Paso temporal Mapa 1 (Izquierdo)",
                min_value=1, max_value=len(secuencia),
                value=int(st.session_state.get("tl_paso_activo", 4)),
                key="tl_slider_mapa2d_izq",
            )
            paso_m2 = ct2.slider(
                "Paso temporal Mapa 2 (Derecho)",
                min_value=1, max_value=len(secuencia),
                value=min(len(secuencia), int(st.session_state.get("tl_paso_activo", 4)) + 2),
                key="tl_slider_mapa2d_der",
            )
            p_info1 = secuencia[paso_m1 - 1]
            p_info2 = secuencia[paso_m2 - 1]
            ct1.caption(
                f"⏱️ **{p_info1['etiqueta']}** ({p_info1['fecha_txt']}) · "
                f"Lámina: **{p_info1['lamina_media_mm']:.1f} mm** · Humedad: **{p_info1['humedad_media_pct']:.1f}%**"
            )
            ct2.caption(
                f"⏱️ **{p_info2['etiqueta']}** ({p_info2['fecha_txt']}) · "
                f"Lámina: **{p_info2['lamina_media_mm']:.1f} mm** · Humedad: **{p_info2['humedad_media_pct']:.1f}%**"
            )
            arr_override = _extraer_arr_timelapse(capa, p_info1)
            arr_override_der = _extraer_arr_timelapse(capa_der, p_info2)
            sub_tl_izq = p_info1["etiqueta"]
            sub_tl_der = p_info2["etiqueta"]
            sufijo_key = f"tl_{paso_m1}_{paso_m2}_{campo_met_sub}_{mostrar_red_2d}_{criterio_grosor_red}"

    if not es_comparacion:
        mp = mapa_resultado(
            r, capa, op, st.session_state["aoi"]["geom"], r["umbral"],
            cuenca_geom=cuenca["geom"] if cuenca else None,
            cuenca_meta=cuenca,
            recortar_aoi=recortar_aoi,
            arr_override=arr_override,
            campo_metrica_sub=campo_met_sub,
            etiqueta_metrica_sub=etq_met_sub,
            red_drenaje=red_dren if mostrar_red_2d else None,
            criterio_grosor_red=criterio_grosor_red,
            s2_rgb=s2_rgb_2d,
            s2_fecha=s2_fecha_2d,
        )
        st_folium(mp, height=560, use_container_width=True, returned_objects=[], key=f"mapa_res_{capa}_{recortar_aoi}_{usar_s2_2d}_{sufijo_key}")
    else:
        mp_comp = mapa_comparativo_2d(
            r, capa, capa_der, op, st.session_state["aoi"]["geom"], r["umbral"],
            cuenca_geom=cuenca["geom"] if cuenca else None,
            cuenca_meta=cuenca,
            recortar_aoi=recortar_aoi,
            arr_override_izq=arr_override,
            arr_override_der=arr_override_der,
            campo_metrica_sub=campo_met_sub,
            etiqueta_metrica_sub=etq_met_sub,
            red_drenaje=red_dren if mostrar_red_2d else None,
            criterio_grosor_red=criterio_grosor_red,
            s2_rgb=s2_rgb_2d,
            s2_fecha=s2_fecha_2d,
            subtitulo_izq=sub_tl_izq,
            subtitulo_der=sub_tl_der,
        )
        st_folium(
            mp_comp, height=560, use_container_width=True, returned_objects=[],
            key=f"mapa_comp_{capa}_{capa_der}_{recortar_aoi}_{usar_s2_2d}_{sufijo_key}",
        )

    if cuenca and cuenca.get("subcuencas") and campo_met_sub:
        with st.expander(f"📊 Métricas hidrológicas por subcuenca — Activo: {etq_met_sub}", expanded=True):
            df_sm = pd.DataFrame(cuenca["subcuencas"])
            cols_sm = [c for c in (
                "huc", "nombre", "area_ha", campo_met_sub,
                "lamina_mean_mm", "lamina_max_mm", "escorrentia_mean_mm", "escorrentia_max_mm",
                "balance_mean_mm", "area_enc_ha", "pct_enc",
            ) if c in df_sm.columns]
            cols_unicas = list(dict.fromkeys(cols_sm))
            st.dataframe(df_sm[cols_unicas], use_container_width=True, hide_index=True)

    if red_dren and mostrar_red_2d:
        st.caption(
            f"🏞️ **Red de drenaje superpuesta:** `{red_dren.get('fuente', 'NHD')}` · "
            f"**{red_dren.get('n_tramos', 0)} tramos** ({red_dren.get('longitud_total_km', 0)} km) con grosor escalado por jerarquía/acumulación."
        )

    cat = r["arrays"]["categoria"][r["mascara"]]
    ha = r["res_m"] ** 2 / 1e4
    _cols_tarjetas([(n, f"{(cat == k).sum() * ha:.2f}", "ha", f"{100 * (cat == k).mean():.1f}% del dominio evaluado", t)
                    for k, n, t in ((1, "Encharcamiento leve", ""), (2, "Moderado", "agua"), (3, "Severo", "alerta"))])


# ── 6. Modelo 3D ─────────────────────────────────────────────────────────────
def _puente_js_camara_3d():
    """
    Inyecta un puente ligero en JavaScript que lee en tiempo real la cámara 3D (`getCamera()`:
    eye, center, up) mientras el usuario rota, desplaza o hace zoom con el mouse en el gráfico Plotly 3D.
    Al pulsar el botón de generar GIF (o 'Congelar vista 3D actual y Generar GIF'), congela esa orientación
    exacta del mouse, la envía a Streamlit y dispara la generación del GIF desde esa ubicación.
    """
    import streamlit.components.v1 as components

    html_code = """
    <div id="bar_cam3d" style="font-family:'Segoe UI',sans-serif;background:#111c2e;border:1px solid #1f3350;
         border-left:4px solid #00f5d4;border-radius:9px;padding:10px 14px;display:flex;flex-wrap:wrap;
         align-items:center;justify-content:space-between;gap:10px;color:#dce6f2;box-sizing:border-box;">
      <div style="font-size:12.5px;line-height:1.4;">
        <span style="color:#00f5d4;font-weight:700;">🎥 Orientación 3D en vivo (mueva el modelo 3D de arriba con el mouse):</span>
        <span id="lbl_cam3d" style="color:#e8f1fb;margin-left:6px;font-family:monospace;font-size:12.5px;">
          Azimut: 45°  |  Inclinación: 27°  |  Zoom/Dist.: 2.05
        </span>
      </div>
      <button id="btn_freeze_gif" style="background:linear-gradient(135deg,#00b4d8,#0077b6);color:#ffffff;
              border:none;border-radius:7px;padding:8px 16px;font-weight:700;font-size:12.5px;cursor:pointer;
              box-shadow:0 2px 6px rgba(0,180,216,0.35);white-space:nowrap;">
        📸 Congelar esta vista 3D del mouse y Generar GIF
      </button>
    </div>
    <script>
    (function() {
      const pdoc = window.parent.document;
      let lastCam = {azim: 45, elev: 27, dist: 2.05, eye: {x: 1.35, y: 1.35, z: 0.85}, center: {x: 0, y: 0, z: 0}};

      function ocultarInputPuente() {
        const inp = pdoc.querySelector('input[aria-label="cam3d_bridge_input"]');
        if (inp) {
          let box = inp.closest('div[data-testid="stTextInput"]');
          if (box) {
            box.style.position = 'fixed';
            box.style.left = '-9999px';
            box.style.width = '1px';
            box.style.height = '1px';
            box.style.opacity = '0';
            box.style.pointerEvents = 'none';
          }
        }
      }

      function leerCamaraPlotly() {
        ocultarInputPuente();
        const plots = pdoc.querySelectorAll('.js-plotly-plot');
        let gd = null;
        for (let i = 0; i < plots.length; i++) {
          if (plots[i]._fullLayout && plots[i]._fullLayout.scene && plots[i]._fullLayout.scene._scene) {
            gd = plots[i];
            break;
          }
        }
        if (!gd) return null;
        try {
          const cam = gd._fullLayout.scene._scene.getCamera();
          if (!cam || !cam.eye) return null;
          const cx = (cam.center && cam.center.x) || 0;
          const cy = (cam.center && cam.center.y) || 0;
          const cz = (cam.center && cam.center.z) || 0;
          const vx = cam.eye.x - cx;
          const vy = cam.eye.y - cy;
          const vz = cam.eye.z - cz;
          const dist = Math.max(Math.hypot(vx, vy, vz), 0.35);
          const elev = Math.round(Math.max(5, Math.min(88, Math.atan2(vz, Math.hypot(vx, vy)) * 180 / Math.PI)));
          const azim = Math.round(((Math.atan2(vy, vx) * 180 / Math.PI) + 360) % 360);
          lastCam = {
            azim: azim,
            elev: elev,
            dist: Number(dist.toFixed(2)),
            eye: {x: Number(cam.eye.x.toFixed(4)), y: Number(cam.eye.y.toFixed(4)), z: Number(cam.eye.z.toFixed(4))},
            center: {x: Number(cx.toFixed(4)), y: Number(cy.toFixed(4)), z: Number(cz.toFixed(4))}
          };
          const lbl = document.getElementById('lbl_cam3d');
          if (lbl) {
            lbl.textContent = 'Azimut: ' + azim + '°  |  Inclinación: ' + elev + '°  |  Zoom/Dist.: ' + dist.toFixed(2);
          }
          return lastCam;
        } catch (e) {
          return null;
        }
      }

      function enviarCamaraAStreamlit(autoGen) {
        leerCamaraPlotly();
        const inp = pdoc.querySelector('input[aria-label="cam3d_bridge_input"]');
        if (!inp) return;
        const payload = JSON.stringify({
          azim: lastCam.azim,
          elev: lastCam.elev,
          dist: lastCam.dist,
          eye: lastCam.eye,
          center: lastCam.center,
          auto_gen: Boolean(autoGen),
          ts: Date.now()
        });
        const nativeSetter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(inp, payload);
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        inp.dispatchEvent(new Event('change', {bubbles: true}));
        inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
      }

      const btn = document.getElementById('btn_freeze_gif');
      if (btn) {
        btn.addEventListener('click', function() {
          btn.textContent = '⏳ Congelando orientación y generando GIF 3D...';
          enviarCamaraAStreamlit(true);
        });
      }

      setInterval(leerCamaraPlotly, 250);
      setTimeout(leerCamaraPlotly, 100);
    })();
    </script>
    """
    components.html(html_code, height=64, scrolling=False)


def render_tab_3d():
    import json as _json

    st.subheader("🧊 Modelo 3D: relieve + lámina de agua + red de drenaje y evolución temporal")
    r = st.session_state.get("resultado")
    if not r:
        st.info("Ejecute el modelo desde la barra lateral.")
        return
    red_dren = st.session_state.get("red_drenaje") or r.get("red_drenaje")

    # Procesar orientación congelada desde el mouse del visor 3D si fue enviada por el puente JS
    if "cam3d_state" not in st.session_state:
        st.session_state["cam3d_state"] = dict(
            azim=45.0, elev=27.0, dist=2.05,
            eye=dict(x=1.35, y=1.35, z=0.85),
            center=dict(x=0.0, y=0.0, z=0.0),
            last_ts=0,
        )
    disparar_gif_auto = False
    bridge_raw = st.text_input("cam3d_bridge_input", value="", key="cam3d_bridge_widget", label_visibility="collapsed")
    if bridge_raw and bridge_raw.strip().startswith("{"):
        try:
            datos_cam = _json.loads(bridge_raw)
            ts_nuevo = int(datos_cam.get("ts", 0))
            if ts_nuevo != st.session_state["cam3d_state"].get("last_ts", 0):
                st.session_state["cam3d_state"] = dict(
                    azim=float(datos_cam.get("azim", 45.0)),
                    elev=float(datos_cam.get("elev", 27.0)),
                    dist=float(datos_cam.get("dist", 2.05)),
                    eye=datos_cam.get("eye"),
                    center=datos_cam.get("center"),
                    last_ts=ts_nuevo,
                )
                if datos_cam.get("auto_gen"):
                    disparar_gif_auto = True
        except Exception:
            pass

    cam_st = st.session_state["cam3d_state"]
    cam_azim = float(cam_st["azim"])
    cam_elev = float(cam_st["elev"])
    cam_dist = float(cam_st["dist"])
    cam_eye = cam_st.get("eye")
    cam_center = cam_st.get("center")

    # ── Controles principales de exageración y capas en el Modelo 3D superior ──
    c1, c2, c3, c4, c5 = st.columns(5)
    exag_z = c1.slider(
        "Exageración vertical del relieve (×)",
        min_value=0.5, max_value=25.0, value=3.0, step=0.5,
        key="mod3d_exag_z_slider",
        help="Factor multiplicador de la altitud topográfica (DEM). Se aplica tanto al Modelo 3D interactivo como a la proyección del GIF.",
    )
    exag_a = c2.slider(
        "Exageración de la lámina de agua",
        min_value=1, max_value=2000, value=150, step=10,
        key="mod3d_exag_a_slider",
        help="Factor visual aplicado al espesor de la lámina de agua superficial (mm -> m).",
    )
    vis = c3.slider(
        "Lámina mínima visible (mm)",
        min_value=0.1, max_value=20.0, value=float(max(r["umbral"] * 0.5, 0.5)), step=0.1,
        key="mod3d_vis_slider",
        help="Oculta láminas muy delgadas para destacar las cubetas y depresiones de acumulación.",
    )
    recortar = c4.checkbox(
        "Recortar al dominio", value=True,
        key="mod3d_recortar_chk",
        help="Recorta la malla 3D exactamente a los límites del AOI (o subcuenca activa).",
    )
    ver_red_3d = c5.checkbox(
        "🏞️ Red de drenaje 3D", value=True,
        key="mod3d_red_chk",
        help="Superpone los cauces de la red de drenaje sobre la superficie topográfica 3D.",
    )

    secuencia = r.get("timelapse", [])
    lamina_3d = r["arrays"]["lamina"]
    lam_ref_fija = None
    if secuencia:
        lam_ref_fija = max([float(s["lamina_max_mm"]) for s in secuencia] + [10.0])
        usar_tl_3d = st.checkbox(
            "⏱️ Recorrer secuencia temporal en 3D (Timelapse interactivo)",
            value=False,
            key="usar_tl_3d",
            help="Permite recorrer sin demoras los pasos cronológicos de la tormenta, acumulación, drenaje y secado sobre el modelo 3D.",
        )
        if usar_tl_3d:
            paso_3d = st.slider(
                "Paso temporal en 3D",
                min_value=1, max_value=len(secuencia),
                value=int(st.session_state.get("tl_paso_activo", 4)),
                key="tl_slider_3d",
            )
            info_3d = secuencia[paso_3d - 1]
            lamina_3d = info_3d["lamina"]
            est_txt, _ = plots._estado_proceso_timelapse(paso_3d)
            st.caption(
                f"⏱️ **{info_3d['etiqueta']}** — Estado: **{est_txt}** · "
                f"Lámina máx.: **{info_3d['lamina_max_mm']:.1f} mm** · "
                f"Área encharcada: **{info_3d['area_enc_ha']:.2f} ha** · "
                f"Humedad suelo: **{info_3d['humedad_media_pct']:.0f}% AWC**"
            )

    a = r["arrays"]
    dem_dom = r["dem"][r["mascara"]] if r["mascara"].any() else r["dem"]
    z_min_d, z_max_d = float(np.nanmin(dem_dom)), float(np.nanmax(dem_dom))
    pend_med = float(np.nanmean(a["pendiente"][r["mascara"]])) if r["mascara"].any() else float(np.nanmean(a["pendiente"]))
    _cols_tarjetas([
        ("Cota mínima", f"{z_min_d:,.1f}", "m s.n.m.", "DEM 3DEP en dominio", ""),
        ("Cota máxima", f"{z_max_d:,.1f}", "m s.n.m.", "DEM 3DEP en dominio", ""),
        ("Desnivel (ΔZ)", f"{z_max_d - z_min_d:,.1f}", "m", f"Malla: {r['dem'].shape[1]}×{r['dem'].shape[0]} celdas ({r['res_m']:.0f} m)", "suelo"),
        ("Pendiente media", f"{pend_med:.1f}", "%", f"Máx.: {float(np.nanmax(a['pendiente'][r['mascara']])):.1f}%", "alerta"),
    ])

    # ── Selector de base visual / textura sobre la superficie 3D ──
    modo_base_3d = st.radio(
        "Base visual / Textura sobre el relieve 3D",
        [
            "🛰️ Imagen satelital de la fecha del evento (Sentinel-2 sin nubes)",
            "🗻 Relieve / topografía actual (variable temática)",
            "🌐 Imagen satelital de alta resolución (Google Satellite)",
            "🌎 Imagen satelital de alta resolución (Esri World Imagery base)",
        ],
        horizontal=True,
        key="modo_base_textura_3d",
        help=(
            "Elija cómo vestir la superficie 3D: captura Sentinel-2 de la fecha del evento (coherencia temporal con el estado del lote), "
            "gradiente temático (Elevación/NDVI/NDWI/Pendiente/Napa), "
            "Google Satellite o Esri World Imagery para máximo detalle de caminos, bordes y depresiones."
        ),
    )

    opciones = {
        "Elevación (m)": (r["dem"], TERRENO),
        "NDVI": (r["ndvi"], VERDES),
        "NDWI": (r["ndwi"], HUMEDAD),
        "Pendiente (%)": (a["pendiente"], CALIDOS),
        "Profundidad de napa (m)": (a.get("prof_napa_m", r["dem"]), HUMEDAD),
    }
    nombre = "Elevación (m)"
    rgb_textura = None
    fecha_s2_activa = None
    malla_actual = st.session_state.get("grid", {}).get("malla")
    f_ev_str = pd.to_datetime(r["fecha_evento"]).strftime("%Y-%m-%d") if r.get("fecha_evento") is not None else None

    if modo_base_3d.startswith("🗻"):
        nombre = st.radio(
            "Variable temática del terreno",
            list(opciones),
            horizontal=True,
            help="Variable utilizada para colorear la superficie topográfica 3D debajo de la lámina de agua.",
        )
    elif modo_base_3d.startswith("🛰️") and malla_actual is not None:
        try:
            with st.spinner("Descargando textura satelital Sentinel-2 próxima al evento…"):
                rgb_textura, f_cap, nub_pct, dt_d, fte_s2 = obtener_textura_s2_evento(malla_actual, f_ev_str)
                fecha_s2_activa = f_cap
            ref_txt = f" (±{dt_d} días respecto al evento del {f_ev_str})" if f_ev_str else " (más reciente disponible)"
            st.info(
                f"📅 **Textura satelital temporal aplicada:** Captura del **`{f_cap}`**{ref_txt} · "
                f"Fuente: **{fte_s2}** · Nubosidad de escena: **{nub_pct:.1f}%**."
            )
        except Exception as e_s2:  # noqa: BLE001
            st.warning(f"No se pudo cargar la textura Sentinel-2 temporal ({e_s2}); se muestra el relieve base.")
            rgb_textura = None
    elif modo_base_3d.startswith("🌐") and malla_actual is not None:
        try:
            with st.spinner("Descargando textura satelital de alta resolución (Google Satellite)…"):
                rgb_textura, fte_goog = obtener_textura_google_malla(malla_actual)
            st.caption(f"🌐 **Textura base aplicada:** `{fte_goog}` — alta resolución para detalle de caminos, bordes y bajos.")
        except Exception as e_gg:  # noqa: BLE001
            st.warning(f"No se pudo descargar la textura de Google Satellite ({e_gg}); se muestra el relieve base.")
            rgb_textura = None
    elif modo_base_3d.startswith("🌎") and malla_actual is not None:
        try:
            with st.spinner("Descargando textura satelital de alta resolución (Esri World Imagery)…"):
                rgb_textura, fte_esri = obtener_textura_esri_malla(malla_actual)
            st.caption(f"🌎 **Textura base aplicada:** `{fte_esri}` — alta resolución para detalle de caminos, bordes y bajos.")
        except Exception as e_es:  # noqa: BLE001
            st.warning(f"No se pudo descargar la textura satelital base ({e_es}); se muestra el relieve base.")
            rgb_textura = None

    campo, anclas = opciones[nombre]
    escala = [[p, f"rgb{c}"] for p, c in anclas]
    fig = plots.figura_3d(
        r["dem"], lamina_3d, r["mascara"], campo, nombre, escala, r["res_m"],
        exag_z, exag_a, vis, recortar,
        red_drenaje=red_dren if ver_red_3d else None,
        bounds=r.get("bounds"),
        rgb_textura=rgb_textura,
        lamina_ref_fija=lam_ref_fija,
        cam_elev=cam_elev,
        cam_azim=cam_azim,
        cam_dist=cam_dist,
        cam_eye=cam_eye,
        cam_center=cam_center,
    )
    st.plotly_chart(fig, use_container_width=True, key="plt_modelo_3d_main")

    # Barra interactiva conectada al visor Plotly 3D: lee en vivo la orientación que el usuario acomoda con el mouse
    # y permite congelarla y generar el GIF con 1 clic
    _puente_js_camara_3d()

    # ── Exportación bajo demanda de GIF del Timelapse 3D ──
    if secuencia:
        st.markdown("---")
        with st.expander("🎬 Exportar animación GIF 3D del Timelapse (Con la orientación del visor 3D)", expanded=True):
            st.caption(
                "Mueva libremente el **Modelo 3D de arriba con el mouse** (rote hacia arriba/abajo/izquierda/derecha y acerque o aleje con la rueda) "
                "y pulse **📸 Congelar esta vista 3D del mouse y Generar GIF** (justo debajo del modelo 3D) o configure opciones adicionales aquí."
            )
            cg_ex, cg_tex, cg_res, cg_vel = st.columns([1.3, 1.6, 1.4, 1.1])
            exag_z_gif = cg_ex.slider(
                "Exageración del relieve en el GIF (×)",
                min_value=0.5, max_value=25.0, value=float(exag_z), step=0.5,
                key="gif_exag_z_slider",
                help="Nivel de exageración vertical del relieve en el GIF (por defecto toma el del Modelo 3D superior).",
            )
            tex_gif_sel = cg_tex.selectbox(
                "Textura 3D en el GIF",
                [
                    "🛰️ Sentinel-2 de la fecha disponible",
                    "🔄 Igual al visor 3D superior",
                    "🌐 Google Satellite (alta res.)",
                    "🌎 Esri World Imagery (alta res.)",
                    "🗻 Variable temática seleccionada",
                ],
                index=0,
                key="gif_textura_sel",
                help="Por defecto viste el relieve 3D del GIF con la imagen Sentinel-2 sin nubes de la fecha disponible.",
            )
            calidad_gif = cg_res.selectbox(
                "Calidad / Resolución del GIF",
                ["Alta definición HD (1120×680 px — muy nítido)", "Estándar (920×560 px — rápido)"],
                index=0,
                key="gif_calidad_sel",
                help="Renderiza la superficie 3D continua con ejes reales, barra de color y paleta fotográfica.",
            )
            dur_gif_ms = cg_vel.slider(
                "Duración por cuadro (ms)",
                min_value=350, max_value=1400, value=750, step=50,
                key="gif_dur_ms_slider",
                help="Velocidad de reproducción de la animación GIF (menor valor = más rápido).",
            )

            c_g1, c_g2 = st.columns([1.4, 2.6])
            click_manual_gif = c_g1.button("🎬 Generar GIF 3D", type="primary", use_container_width=True, key="btn_gen_gif_3d")
            if disparar_gif_auto or click_manual_gif:
                try:
                    with st.spinner(
                        f"Renderizando GIF 3D con la orientación congelada (Azimut {cam_azim:.0f}° · Inclinación {cam_elev:.0f}° · Zoom {cam_dist:.2f} · Exag. ×{exag_z_gif:g})…"
                    ):
                        rgb_gif = rgb_textura
                        f_s2_gif = fecha_s2_activa
                        if tex_gif_sel.startswith("🛰️") and malla_actual is not None:
                            if modo_base_3d.startswith("🛰️") and rgb_textura is not None:
                                rgb_gif = rgb_textura
                                f_s2_gif = fecha_s2_activa
                            else:
                                rgb_gif, f_s2_gif, _, _, _ = obtener_textura_s2_evento(malla_actual, f_ev_str)
                        elif tex_gif_sel.startswith("🌐") and malla_actual is not None:
                            rgb_gif, _ = obtener_textura_google_malla(malla_actual)
                            f_s2_gif = None
                        elif tex_gif_sel.startswith("🌎") and malla_actual is not None:
                            rgb_gif, _ = obtener_textura_esri_malla(malla_actual)
                            f_s2_gif = None
                        elif tex_gif_sel.startswith("🗻"):
                            rgb_gif = None
                            f_s2_gif = None

                        gif_bytes = plots.generar_gif_timelapse_3d(
                            r["dem"], r["mascara"], campo, anclas, secuencia, r["res_m"],
                            exag_z_gif, exag_a, vis, recortar=recortar,
                            rgb_textura=rgb_gif,
                            red_drenaje=red_dren if ver_red_3d else None,
                            bounds=r.get("bounds"),
                            duracion_ms=dur_gif_ms,
                            alta_definicion=calidad_gif.startswith("Alta"),
                            fecha_s2_txt=f_s2_gif,
                            cam_elev=cam_elev,
                            cam_azim=cam_azim,
                            cam_dist=cam_dist,
                            cam_center=cam_center,
                        )
                        st.session_state["gif_3d_bytes"] = gif_bytes
                        st.session_state["gif_3d_meta"] = f"Vista congelada: Azimut {cam_azim:.0f}° · Inclinación {cam_elev:.0f}° · Dist. {cam_dist:.2f} · Exageración ×{exag_z_gif:g}"
                except Exception as e_gif:  # noqa: BLE001
                    st.error(f"No se pudo generar el GIF 3D: {e_gif}")

            gif_guardado = st.session_state.get("gif_3d_bytes")
            if gif_guardado:
                c_g2.download_button(
                    "⬇️ Descargar GIF 3D (timelapse_3d.gif)",
                    data=gif_guardado,
                    file_name="timelapse_hidrologico_3d.gif",
                    mime="image/gif",
                    use_container_width=True,
                    key="btn_dl_gif_3d",
                )
                meta_txt = st.session_state.get("gif_3d_meta", f"Exageración relieve ×{exag_z_gif:g}")
                st.image(gif_guardado, caption=f"Vista previa del GIF 3D del Timelapse ({meta_txt})", use_container_width=True)
