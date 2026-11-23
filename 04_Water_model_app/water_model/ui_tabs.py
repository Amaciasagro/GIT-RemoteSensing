"""Interface tabs: AOI + Zonal Watershed, Soil (Ksat/Porosity/Effective Depth), Climate, Balance + Timelapse, 2D Map, and 3D Model."""
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
    """Displays a row of KPI cards: items = [(title, value, unit, subtitle, card_type), ...]."""
    cols = st.columns(len(items))
    for c, it in zip(cols, items):
        c.markdown(tarjeta(*it), unsafe_allow_html=True)


def _fijar_aoi(fn):
    try:
        st.session_state["aoi"] = normalizar_aoi(fn())
    except Exception as e:  # noqa: BLE001
        st.error(f"Invalid AOI: {e}")
        return False
    limpiar_resultados()
    return True


def _fijar_cuenca(fn, fuente="Local file", nivel="Local"):
    try:
        aoi = st.session_state.get("aoi")
        st.session_state["cuenca"] = normalizar_cuenca(fn(), aoi=aoi, fuente=fuente, nivel=nivel)
    except LookupError as e_lk:
        avisos = st.session_state.setdefault("avisos", [])
        msg = f"⚠️ No intersection between watershed and AOI: {e_lk}"
        if msg not in avisos:
            avisos.append(msg)
        st.warning(msg)
        return False
    except Exception as e:  # noqa: BLE001
        st.error(f"Invalid watershed: {e}")
        return False
    limpiar_resultados()
    return True


# ── Visual Historical Event Selection Panel (CHIRPS + Hourly ERA5) ───────────
def render_panel_selector_historico(solo_dia_pico=False):
    """
    Displays the interactive historical rainfall bar chart (Climate Analyzer style),
    allows selecting a storm by clicking a bar or via the dropdown selector,
    and automatically extracts cumulative millimeters, start/end dates, actual duration (ERA5-Land Hourly),
    and the hourly intensity hyetograph that feeds the hydrological model.
    """
    aoi = st.session_state.get("aoi")
    clima = st.session_state.get("clima")
    if aoi is None or clima is None or clima.empty:
        return None

    with st.expander("🌧️ Visual Historical Event Selection (CHIRPS + ERA5-Land Hourly Hyetograph)", expanded=True):
        c_per, c_ev, c_opt = st.columns([1.2, 2.2, 1.1])
        periodo = c_per.selectbox(
            "Chart time window",
            ["Last year (365 days)", "Last 6 months", "Last 3 months", "Custom range"],
            key="chirps_ventana_grafico",
            help="Filter the visible period in the bar chart to identify storms more clearly.",
        )

        df_c = clima.copy().sort_values("fecha").reset_index(drop=True)
        f_max_d = df_c["fecha"].max()
        if periodo == "Last 6 months":
            df_c = df_c[df_c["fecha"] >= (f_max_d - pd.Timedelta(days=180))]
        elif periodo == "Last 3 months":
            df_c = df_c[df_c["fecha"] >= (f_max_d - pd.Timedelta(days=90))]
        elif periodo == "Custom range":
            r_ini, r_fin = st.date_input(
                "Select start and end dates",
                value=(df_c["fecha"].min().date(), f_max_d.date()),
                min_value=df_c["fecha"].min().date(),
                max_value=f_max_d.date(),
                key="chirps_rango_fechas",
            )
            df_c = df_c[(df_c["fecha"].dt.date >= r_ini) & (df_c["fecha"].dt.date <= r_fin)]

        eventos = listar_eventos_chirps(df_c, min_mm=2.0)
        if not eventos:
            st.warning("No rainfall ≥ 2 mm was recorded in the selected window.")
            return None

        fechas_disp = [e["fecha_str"] for e in eventos]
        f_guardada = st.session_state.get("evento_chirps_fecha_str")
        idx_def = fechas_disp.index(f_guardada) if f_guardada in fechas_disp else 0

        ev_elegido = c_ev.selectbox(
            "Selected storm (sorted from largest to smallest magnitude)",
            eventos,
            index=idx_def,
            format_func=lambda x: f"🏆 {x['label']}" if x == eventos[0] else x["label"],
            key="sel_evento_chirps_main",
            help="Storms are sorted from highest to lowest daily rainfall depth to immediately spot extreme events.",
        )
        ventana_completa = c_opt.checkbox(
            "Integrate contiguous storm days",
            value=not solo_dia_pico,
            key="chk_ventana_tormenta",
            help="If enabled, automatically sums consecutive rainy days of the same storm (front start to end).",
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

        det = _obtener_detalle_cacheado(fecha_activa_str)

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
            st.plotly_chart(fig_barras, use_container_width=True)

        st.session_state["evento_chirps_fecha_str"] = fecha_activa_str
        st.session_state["detalle_evento_activo"] = det

        if det is not None:
            _cols_tarjetas([
                ("Total event rainfall", f"{det['p_total_mm']:.1f}", "mm", f"Peak day ({det['fecha_pico_str']}): {det['p_pico_mm']:.1f} mm", "agua"),
                ("Start → End", det["fecha_inicio"], "", f"Through {det['fecha_fin']} ({det['n_dias']} day(s))", ""),
                ("Actual duration (ERA5)", f"{det['duracion_real_h']}", "h", f"Effective rain hours ({det['fuente_horaria']})", "suelo"),
                ("Peak / mean intensity", f"{det['intensidad_max_mmh']:.1f}", "mm/h", f"Mean intensity: {det['intensidad_media_mmh']:.2f} mm/h", "alerta"),
            ])
            st.plotly_chart(plots.fig_hietograma_evento(det), use_container_width=True, key="plt_hieto_selector_top")
            st.caption(
                "✅ **Integrated with the hydrological engine:** When clicking **▶️ Run model**, the SCS-CN balance, "
                "Green-Ampt hourly infiltration ($K_{sat}$), and 2D routing will automatically use "
                f"**P = {det['p_total_mm']:.1f} mm**, **Duration = {det['duracion_real_h']} h**, and this **hourly hyetograph**."
            )
        return det


# ── 1. AOI and Zonal Watershed ───────────────────────────────────────────────
def render_tab_aoi():
    st.subheader("📍 Area of Interest (USA) and Contributing Zonal Watershed")
    metodo = st.radio(
        "Main field (AOI) boundary method",
        ["✏️ Draw on map", "📁 Upload Shapefile (.zip) / GeoJSON", "📋 Paste GeoJSON"],
        horizontal=True,
        key="aoi_metodo",
        help="Choose how to define the main agricultural field polygon to evaluate.",
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
        if dib and st.button("✅ Use drawn polygon", type="primary"):
            ok = _fijar_aoi(lambda: gdf_desde_geojson(dib))
    elif metodo.startswith("📁"):
        f = st.file_uploader(
            "Zipped Shapefile (.zip), GeoPackage (.gpkg), or GeoJSON of the field",
            type=["zip", "gpkg", "shp", "geojson", "json"],
            key="up_aoi_file",
            help="Upload your field boundary as a .zip (Shapefile), .gpkg (GeoPackage), or .geojson.",
        )
        if f and st.button("✅ Load AOI", type="primary"):
            ok = _fijar_aoi(lambda: gdf_desde_archivo(f))
    else:
        txt = st.text_area(
            "GeoJSON (Feature, FeatureCollection, or geometry)",
            height=180,
            help="Paste the raw JSON text of a GeoJSON polygon in EPSG:4326.",
        )
        if txt.strip() and st.button("✅ Load AOI", type="primary"):
            ok = _fijar_aoi(lambda: gdf_desde_geojson(txt))
    if ok:
        st.rerun()

    aoi = st.session_state.get("aoi")
    if aoi:
        with st.expander("🌊 USGS WBD Hydrological Subwatershed (HUC12 / HUC10 in GEE) or Local File (.shp / .gpkg)", expanded=True):
            st.caption(
                "Automatically retrieve the official subwatershed from the **Watershed Boundary Dataset (`USGS/WBD/2017/HUC12` or `HUC10`)** "
                "in Google Earth Engine filtered by `.filterBounds(aoi)`, or upload your own local vector file (`.zip`, `.gpkg`, `.shp`, `.geojson`)."
            )
            c_orig, c_act, c_del = st.columns([2.6, 1.3, 1.0])
            origen_cuenca = c_orig.radio(
                "Subwatershed source",
                [
                    "🛰️ GEE: USGS/WBD/2017/HUC12 (Subwatershed)",
                    "🛰️ GEE: USGS/WBD/2017/HUC10 (Watershed)",
                    "📂 Local file (.zip Shapefile, .gpkg, .shp, .geojson)",
                ],
                horizontal=True,
                key="origen_cuenca_sel",
                help="HUC12 corresponds to local subwatersheds (~4,000–16,000 ha); HUC10 to larger watersheds; or load your own file.",
            )

            if origen_cuenca.startswith("🛰️"):
                nivel_wbd = "HUC10" if "HUC10" in origen_cuenca else "HUC12"
                if c_act.button(f"🔍 Query {nivel_wbd} in GEE", type="primary", use_container_width=True):
                    with st.spinner(f"Querying USGS/WBD/2017/{nivel_wbd} with .filterBounds(aoi)…"):
                        limpiar_resultados()
                        c_res = obtener_cuenca_wbd_gee(aoi, nivel=nivel_wbd)
                    if c_res is not None:
                        st.success(f"{nivel_wbd} subwatershed loaded: **{c_res['huc_codigo']} — {c_res['nombre']}** ({c_res['area_ha']:,.1f} ha)")
                    st.rerun()
            else:
                f_cuenca = st.file_uploader(
                    "Zonal watershed file (.zip Shapefile, .gpkg GeoPackage, .shp, or .geojson)",
                    type=["zip", "gpkg", "shp", "geojson", "json"],
                    key="up_cuenca_file",
                    help="Polygon(s) of the watershed or subwatersheds intersecting or surrounding the main field.",
                )
                if c_act.button("📌 Load local file", disabled=f_cuenca is None, type="primary", use_container_width=True):
                    if _fijar_cuenca(lambda: gdf_desde_archivo(f_cuenca), fuente=f"Local ({f_cuenca.name})", nivel="Local"):
                        st.rerun()

            if cuenca and c_del.button("🗑️ Remove subwatershed", use_container_width=True):
                st.session_state.pop("cuenca", None)
                limpiar_resultados()
                st.rerun()

            cuenca = st.session_state.get("cuenca")
            if cuenca:
                _cols_tarjetas([
                    (f"{cuenca.get('nivel', 'HUC')} Code", cuenca.get("huc_codigo", "—"), "", f"Source: {cuenca.get('fuente', 'WBD')}", "agua"),
                    ("Subwatershed name", cuenca.get("nombre", "—"), "", f"State(s): {cuenca.get('states', 'US')}", "agua"),
                    ("Total subwatershed area", f"{cuenca['area_ha']:,.1f}", "ha", f"{cuenca['n_subcuencas']} polygon(s)", "agua"),
                    ("External contributing area", f"{cuenca['area_externa_ha']:,.1f}", "ha", f"Watershed/AOI ratio: {cuenca['area_ha']/max(aoi['area_ha'], 0.1):.1f}×", "suelo"),
                ])
                if cuenca.get("subcuencas"):
                    df_sub = pd.DataFrame(cuenca["subcuencas"]).rename(columns={
                        "huc": "HUC Code", "nombre": "Subwatershed Name",
                        "area_ha": "Area (ha)", "states": "State(s)",
                        "tohuc": "Drains to HUC", "fuente": "Collection / Source",
                    })
                    st.dataframe(df_sub, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("**🏞️ Drainage Network (`WWF/HydroSHEDS/v1/FreeFlowingRivers` in GEE, `NHD_FLOWLINE` fallback, or Local File `.shp`/`.gpkg`)**")
            c_rd0, c_rd1, c_rd2, c_rd3 = st.columns([1.6, 2.0, 1.3, 0.9])
            pref_gee_red = c_rd0.selectbox(
                "Preferred GEE collection",
                ["HydroSHEDS (WWF/FreeFlowingRivers)", "NHD (NHD_FLOWLINE)"],
                key="pref_gee_red_sel",
                help="Prioritizes WWF/HydroSHEDS/v1/FreeFlowingRivers (with NHD_FLOWLINE fallback) or vice versa when querying with .filterBounds(aoi).",
            )
            f_red = c_rd1.file_uploader(
                "Optional local drainage network (.zip Shapefile, .gpkg, .shp, .geojson)",
                type=["zip", "gpkg", "shp", "geojson", "json"],
                key="up_red_drenaje_file",
                help="If no file is uploaded, WWF/HydroSHEDS/v1/FreeFlowingRivers will be queried automatically (with NHD_FLOWLINE / DEM D8 fallback).",
            )
            if c_rd2.button("🛰️ Query HydroSHEDS / NHD", use_container_width=True):
                st.session_state.pop("red_drenaje", None)
                pref_k = "NHD" if "NHD" in pref_gee_red else "HydroSHEDS"
                with st.spinner(f"Querying {pref_gee_red} with .filterBounds(aoi)…"):
                    red_g = obtener_red_drenaje(aoi, cuenca=cuenca, grid=st.session_state.get("grid"), preferir=pref_k)
                if red_g:
                    st.success(f"Network loaded ({red_g['fuente']}): {red_g['n_tramos']} reaches ({red_g['longitud_total_km']} km)")
                st.rerun()
            if f_red is not None and c_rd2.button("📌 Load local network", type="primary", use_container_width=True):
                try:
                    red_l = normalizar_red_drenaje(
                        gdf_desde_archivo(f_red), aoi=aoi, cuenca=cuenca, fuente=f"Local ({f_red.name})"
                    )
                    st.session_state["red_drenaje"] = red_l
                    st.rerun()
                except Exception as e_rl:  # noqa: BLE001
                    st.error(f"Could not load local drainage network: {e_rl}")
            if st.session_state.get("red_drenaje") and c_rd3.button("🗑️ Remove network", use_container_width=True):
                st.session_state.pop("red_drenaje", None)
                st.rerun()

            red_act = st.session_state.get("red_drenaje")
            if red_act:
                st.caption(
                    f"🏞️ **Active drainage network:** `{red_act['fuente']}` · "
                    f"**{red_act['n_tramos']} reaches** · Total length: **{red_act['longitud_total_km']} km**."
                )

        cuenca = st.session_state.get("cuenca")
        red_act = st.session_state.get("red_drenaje")
        tarjetas_aoi = [
            ("Field area (AOI)", f"{aoi['area_ha']:,.1f}", "ha", "Main field", ""),
            ("Latitude", f"{aoi['lat']:.4f}", "°", "AOI centroid", ""),
            ("Longitude", f"{aoi['lon']:.4f}", "°", "AOI centroid", ""),
        ]
        if cuenca:
            tarjetas_aoi.append((
                f"{cuenca.get('nivel', 'HUC')} Subwatershed", f"{cuenca['area_ha']:,.1f}", "ha",
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
        st.success("AOI ready. Choose in the sidebar whether to model over the **AOI** or the **Subwatershed**, then click **▶️ Run model**.")
    else:
        st.info("Draw or upload a polygon within the United States to begin.")


# ── 2. Soil ──────────────────────────────────────────────────────────────────
def render_tab_suelo():
    st.subheader("🧱 Soil Hydrophysical Properties (SSURGO / USDA-NRCS)")
    s = st.session_state.get("suelo")
    if not s:
        st.info("Run the model to query soil properties.")
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
    limitante = "SSURGO Edaphic" if prof_edaf < prof_agro else "Agronomic / Rooting"

    _cols_tarjetas([
        ("Dominant texture", str(tex_dom), "", f"Hydrological Soil Group HSG {hsg_dom}", "suelo"),
        ("Effective depth", f"{prof_ef:.0f}", "cm", f"Agron.: {prof_agro:.0f} cm · SSURGO: {prof_edaf:.0f} cm ({limitante})", "suelo"),
        ("Available water (AWC)", f"{mean('awc_mm'):.0f}", "mm", f"FC: {mean('fc_mm'):.0f} mm · PWP: {mean('wp_mm'):.0f} mm", "agua"),
        ("Ksat inf. / perc.", f"{mean('ksat_sup_mmh'):.1f} / {mean('ksat_min_mmh'):.1f}", "mm/h", f"Harmonic mean: {mean('ksat_mmh'):.1f} mm/h", "agua"),
        ("Porosity / Bulk dens.", f"{mean('porosidad')*100:.1f}%", "", f"BD: {mean('da_gcm3'):.2f} g/cm³ · Macropores: {mean('gs_mm'):.0f} mm", "suelo"),
    ])
    st.caption(
        f"**Source:** {s['fuente']} · **Depth criterion:** `{s.get('modo_prof', 'restrictivo')}`. "
        "Maximum basic infiltration rate is governed by surface $K_{sat}$ and capillary suction ($\\psi$), "
        "whereas deep percolation and interflow rates are controlled by the $K_{sat}$ of the most restrictive horizon."
    )

    if s["gdf"] is not None:
        t = tabla.set_index("mukey")
        gdf = s["gdf"].copy()
        gdf["textura"] = gdf["mukey"].map(t["textura"])
        gdf["textura_en"] = gdf["textura"].astype(str)
        gdf["muname"] = gdf["mukey"].map(t["muname"])
        gdf["compname"] = gdf["mukey"].map(t["compname"]) if "compname" in t.columns else gdf["muname"]
        gdf["awc_mm"] = gdf["mukey"].map(t["awc_mm"]).round(1)
        gdf["ksat_mmh"] = gdf["mukey"].map(t["ksat_mmh"]).round(1)
        paleta = ["#e9c46a", "#f4a261", "#e76f51", "#8ab17d", "#2a9d8f", "#264653", "#b5838d", "#6d6875",
                  "#90be6d", "#43aa8b", "#577590", "#f9c74f"]
        col = {k: paleta[i % 12] for i, k in enumerate(sorted(gdf["textura"].dropna().unique()))}
        mp = mapa_base([st.session_state["aoi"]["lat"], st.session_state["aoi"]["lon"]], 15, satelite_primero=True)
        folium.GeoJson(
            gdf[["mukey", "muname", "compname", "textura", "textura_en", "awc_mm", "ksat_mmh", "geometry"]].to_json(),
            name="Soil Map Units (SSURGO)",
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
                fields=["mukey", "muname", "compname", "textura_en", "awc_mm", "ksat_mmh"],
                aliases=["🔑 MUKey:", "📍 Map Unit:", "🌱 Dom. series:", "🎨 Texture:", "💧 AWC (mm):", "⏬ Harm. Ksat (mm/h):"],
                sticky=True,
            ),
        ).add_to(mp)
        cuenca = st.session_state.get("cuenca")
        agregar_aoi(mp, st.session_state["aoi"]["geom"], cuenca_geom=cuenca["geom"] if cuenca else None)
        folium.LayerControl().add_to(mp)
        st_folium(mp, height=420, use_container_width=True, returned_objects=[], key="mapa_suelos")

    tb = tabla.copy()
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
            "Detailed profile by horizon (mukey)",
            list(tabla["mukey"]),
            help="Select a map unit to inspect its granulometry, Ksat, and porosity by soil layer.",
        )
        h = s["horizontes"]
        st.plotly_chart(plots.fig_perfil(h[h["mukey"] == mk]), use_container_width=True, key="plt_perfil_suelo")


# ── 3. Climate and Vegetation ────────────────────────────────────────────────
def render_tab_clima():
    st.subheader("🌦️ Climate (CHIRPS + ERA5-Land) and Vegetation (Sentinel-2)")
    clima, ind = st.session_state.get("clima"), st.session_state.get("indices")
    if clima is None and ind is None:
        st.info("No data yet (run the model) or services did not respond.")
        return
    if clima is not None and not clima.empty:
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
        t_min_txt = f"Min: {clima['t_min'].min():.1f}°C · Max: {clima['t_max'].max():.1f}°C" if ("t_min" in clima and clima["t_min"].notna().any()) else "ERA5-Land"
        sub_sw = f"{t_min_txt} · Deep moist.: {sw4_med:.2f} m³/m³" if np.isfinite(sw4_med) else t_min_txt
        _cols_tarjetas([
            ("P last 30 d", f"{p.tail(30).sum():.0f}", "mm", "CHIRPS/ERA5", "agua"),
            ("P last 365 d", f"{p.sum():.0f}", "mm", "annual cumulative", "agua"),
            ("Daily max", f"{p.max():.0f}", "mm", str(clima['fecha'].iloc[int(p.idxmax())].date()), "alerta"),
            ("Mean T (range)", f"{clima['t2m'].mean():.1f}", "°C", sub_sw, ""),
        ])
        st.plotly_chart(plots.fig_clima(clima), use_container_width=True, key="plt_clima_serie")
    if ind is not None and not ind.empty:
        u = ind.iloc[-1]
        _cols_tarjetas([("NDVI", f"{u['NDVI']:.2f}", "", str(u["fecha"].date()), ""),
                        ("NDWI", f"{u['NDWI']:.2f}", "", "latest record", "agua"),
                        ("SAVI", f"{u['SAVI']:.2f}", "", "latest record", ""),
                        ("LAI", f"{u['LAI']:.2f}", "m²/m²", "latest record", "")])
        st.plotly_chart(plots.fig_indices(ind), use_container_width=True, key="plt_indices_s2")


# ── 4. Water Balance and Timelapse ───────────────────────────────────────────
def render_tab_balance():
    st.subheader("💧 Event Water Balance, Water Table Dynamics, and Temporal Sequence")
    r = st.session_state.get("resultado")
    if not r:
        st.info("Run the model from the sidebar.")
        return
    b = r["balance"]
    ev = f" ({pd.to_datetime(r['fecha_evento']).strftime('%Y-%m-%d')})" if r.get("fecha_evento") is not None else " (Manual)"
    pct_enc = 100 * r["area_enc_ha"] / max(r["area_aoi_ha"], 1e-9)

    _cols_tarjetas([
        ("Precipitation", f"{r['p_mm']:.1f}", "mm", f"Event{ev}", "agua"),
        ("Runoff / Watershed", f"{b['escorrentia']:.1f}", "mm", f"CN {b['cn_medio']:.0f} · Ext. inflow: +{b.get('aporte_cuenca_mm', 0.0):.1f} mm", "alerta"),
        ("Recharge / Interflow", f"{b['humedad_suelo']:.1f}", "mm", f"Lat. interflow: {b.get('flujo_subsuperficial', 0.0):.1f} mm", ""),
        ("Water table / Cap. rise", f"{b.get('prof_napa_m', 2.2):.2f}", "m", f"Capillary rise: +{b.get('ascenso_capilar', 0.0):.1f} mm", "suelo"),
        ("Ponded area", f"{r['area_enc_ha']:.2f}", "ha", f"{pct_enc:.1f}% of AOI (max {r['lamina_max']:.0f} mm)", "alerta"),
    ])

    c1, c2 = st.columns([1.25, 1])
    c1.plotly_chart(plots.fig_balance_evento(b), use_container_width=True, key="plt_balance_evento")
    with c2:
        st.markdown("**Surface and Subsurface Physical Components (mm, AOI mean)**")
        st.dataframe(pd.DataFrame({
            "Hydrological component": [
                "Final accumulated surface depth",
                "Lateral subsurface flow (Interflow)",
                "Deep percolation (controlled by Ksat_min)",
                "Capillary rise from water table",
                "External watershed surface inflow to AOI",
                "Re-infiltration from depressions",
                "Net export outside AOI",
                "Estimated mean water table depth (m)",
            ],
            "Value": [
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
            f"Grid resolution: {r['res_m']:.0f} m · Effective duration: {r.get('duracion_h', 24):.0f} h · S2 scenes: {r['n_s2']}"
            + (f" · ERA5 surf.: {r['swvl1']:.3f} m³/m³" if r.get("swvl1") is not None else "")
            + (f" · ERA5 deep (layer 4): {r['swvl4']:.3f} m³/m³" if r.get("swvl4") is not None and np.isfinite(r["swvl4"]) else "")
        )

    det_ev = r.get("detalle_evento")
    if det_ev is not None and "df" in det_ev:
        with st.expander(
            f"⏱️ Real Hourly Hyetograph applied in simulation ({det_ev['fecha_inicio']} → {det_ev['fecha_fin']} · "
            f"{det_ev['p_total_mm']:.1f} mm in {det_ev['duracion_real_h']} h · Imax {det_ev['intensidad_max_mmh']:.1f} mm/h)",
            expanded=True,
        ):
            st.plotly_chart(plots.fig_hietograma_evento(det_ev), use_container_width=True, key="plt_hieto_tab_balance")

    secuencia = r.get("timelapse", [])
    if secuencia:
        st.markdown("---")
        st.markdown("### ⏱️ Time-Step Simulation (*Event Timelapse*)")
        st.caption(
            "Slide the chronological control to inspect how water enters the profile, saturates pores, "
            "accumulates ponded depth in topographic depressions, and then drains or evapotranspires in subsequent days."
        )
        paso_idx = st.slider(
            "Chronological simulation step",
            min_value=1, max_value=len(secuencia), value=4, step=1,
            format="Step %d",
            key="tl_slider_balance",
            help="Step forward or backward in time from rainfall onset up to +7 days post-rain.",
        )
        st.session_state["tl_paso_activo"] = paso_idx
        actual = secuencia[paso_idx - 1]
        _cols_tarjetas([
            ("Active phase", actual["etiqueta"].split("·")[-1].strip(), "", f"Ref. date: {actual['fecha_txt']}", "agua"),
            ("Mean depth", f"{actual['lamina_media_mm']:.1f}", "mm", f"Max in lows: {actual['lamina_max_mm']:.1f} mm", "agua"),
            ("Ponded area", f"{actual['area_enc_ha']:.2f}", "ha", f"Threshold ≥ {r['umbral']:g} mm", "alerta"),
            ("Profile moisture", f"{actual['humedad_media_pct']:.1f}", "% AWC", f"Cum. infiltration: {actual['infiltracion_acum_mm']:.1f} mm", "suelo"),
        ])
        st.plotly_chart(plots.fig_timelapse(secuencia, paso_actual=paso_idx), use_container_width=True, key="plt_timelapse_balance")

    bd = st.session_state.get("balance_diario")
    if bd is not None:
        st.plotly_chart(plots.fig_balance_diario(bd), use_container_width=True, key="plt_balance_diario_anual")
        with st.expander("Daily water balance table (last year)"):
            st.dataframe(bd.round(2), use_container_width=True, hide_index=True)


# ── 5. 2D Map ────────────────────────────────────────────────────────────────
def render_tab_mapa():
    st.subheader("🗺️ 2D Thematic Map, Subwatersheds by Magnitude, and Hierarchical Drainage Network")
    r = st.session_state.get("resultado")
    if not r:
        st.info("Run the model from the sidebar.")
        return
    cuenca = st.session_state.get("cuenca")
    red_dren = st.session_state.get("red_drenaje") or r.get("red_drenaje")
    secuencia = r.get("timelapse", [])
    lista_capas = list(CAPAS)

    c_modo, c_tl, c_s2, c_op = st.columns([1.8, 1.15, 1.35, 0.9])
    modo_comp = c_modo.radio(
        "Display mode",
        ["🗺️ Single map", "🔀 Compare two thematic maps"],
        horizontal=True,
        key="mapa2d_modo_vis",
        help="View a single thematic map or simultaneously compare two thematic layers with synchronized zoom and pan.",
    )
    es_comparacion = modo_comp.startswith("🔀")
    modo_tl = c_tl.checkbox(
        "⏱️ Use Timelapse step",
        value=False,
        help="If enabled, the map shows the spatial evolution of water depth or soil moisture at the chosen time step.",
    )
    usar_s2_2d = c_s2.checkbox(
        "🛰️ Sentinel-2 base (event date)",
        value=False,
        help="Overlays the cloud-free Sentinel-2 capture closest to the event date as a base image (same as in the 3D Model).",
    )
    op = c_op.slider("Opacity", 0.2, 1.0, 0.8, 0.05, help="Transparency of the raster layer over the satellite imagery.")

    if not es_comparacion:
        capa = st.selectbox(
            "Raster thematic variable",
            lista_capas,
            index=0,
            key="mapa2d_capa_unica",
            help="Select the spatial layer to display over the satellite/dark base map.",
        )
        capa_der = None
    else:
        col_m1, col_m2 = st.columns(2)
        capa = col_m1.selectbox(
            "Thematic variable 1 (Left map)",
            lista_capas,
            index=0,
            key="mapa2d_capa_izq",
            help="First thematic variable to compare (left panel).",
        )
        idx_def_der = 7 if len(lista_capas) > 7 else min(2, len(lista_capas) - 1)
        capa_der = col_m2.selectbox(
            "Thematic variable 2 (Right map)",
            lista_capas,
            index=idx_def_der,
            key="mapa2d_capa_der",
            help="Second thematic variable to compare (right panel).",
        )

    s2_rgb_2d, s2_fecha_2d = None, None
    malla_2d = st.session_state.get("grid", {}).get("malla")
    if usar_s2_2d and malla_2d is not None:
        f_ev_2d = pd.to_datetime(r["fecha_evento"]).strftime("%Y-%m-%d") if r.get("fecha_evento") is not None else None
        try:
            with st.spinner("Loading Sentinel-2 image for available date…"):
                s2_rgb_2d, s2_fecha_2d, nub_2d, dt_2d, fte_2d = obtener_textura_s2_evento(malla_2d, f_ev_2d)
            st.caption(f"🛰️ **Active Sentinel-2 image in 2D map:** Capture from **`{s2_fecha_2d}`** (±{dt_2d} d · cloud cover {nub_2d:.1f}% · {fte_2d}).")
        except Exception as e_s2m:  # noqa: BLE001
            st.warning(f"Could not load Sentinel-2 capture ({e_s2m}).")

    c_sub1, c_sub2, c_sub3, c_sub4, c_sub5 = st.columns([1.5, 1.1, 1.4, 1.1, 1.1])
    metricas_opciones = {
        "Water depth / Ponding (mm)": "lamina",
        "Surface runoff (mm)": "escorrentia",
        "Cumulative infiltration (mm)": "infiltracion",
        "Net retained balance (mm)": "balance",
        "Soil moisture (% AWC)": "humedad",
    }
    nom_met_sub = c_sub1.selectbox(
        "Subwatershed metric (color & border)",
        list(metricas_opciones.keys()),
        disabled=cuenca is None,
        help="Variable derived from ejecutar_pipeline(...) governing the fill color and border stroke weight of each subwatershed.",
    )
    est_sub = c_sub2.radio(
        "Subwatershed statistic",
        ["Mean", "Maximum"],
        horizontal=True,
        disabled=cuenca is None,
        help="Choose between the mean or maximum value within each HUC12/HUC10/Local subwatershed.",
    )
    criterios_red = {
        "Combined (Order + Discharge + Accum.)": "grosor_px",
        "Hierarchy / Order (RIV_ORD / Strahler)": "grosor_jerarquia_px",
        "Mean discharge (DIS_AV_CMS m³/s)": "grosor_descarga_px",
        "Accumulation / Area (UPLAND_SKM km²)": "grosor_acumulacion_px",
    }
    crit_red_etq = c_sub3.selectbox(
        "Channel stroke width (HydroSHEDS/NHD)",
        list(criterios_red.keys()),
        help="Defines which HydroSHEDS/NHD attribute controls variable line thickness for drainage channels.",
    )
    criterio_grosor_red = criterios_red[crit_red_etq]
    mostrar_red_2d = c_sub4.checkbox(
        "🏞️ Drainage network",
        value=True,
        help="Displays channels (WWF/HydroSHEDS/v1/FreeFlowingRivers / NHD_FLOWLINE / DEM D8) with variable stroke width.",
    )
    recortar_aoi = True
    if cuenca is not None:
        recortar_aoi = c_sub5.checkbox(
            "Clip to AOI only",
            value=False,
            key="mapa2d_recortar_aoi",
            help="Uncheck to display the raster across the entire modeled subwatershed.",
        )

    campo_met_sub = None
    etq_met_sub = None
    if cuenca is not None:
        base_m = metricas_opciones[nom_met_sub]
        suf_m = "mean_pct" if (base_m == "humedad" and est_sub == "Mean") else (
            "max_pct" if base_m == "humedad" else ("mean_mm" if est_sub == "Mean" else "max_mm")
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
                "Time step to display on 2D map",
                min_value=1, max_value=len(secuencia),
                value=int(st.session_state.get("tl_paso_activo", 4)),
                key="tl_slider_mapa2d",
                help="Explore spatially how ponding builds up and dissipates step by step.",
            )
            paso_info = secuencia[paso_m - 1]
            st.info(
                f"⏱️ **{paso_info['etiqueta']}** ({paso_info['fecha_txt']}) — "
                f"Mean depth: **{paso_info['lamina_media_mm']:.1f} mm** · "
                f"Ponded area: **{paso_info['area_enc_ha']:.2f} ha** · "
                f"Soil moisture: **{paso_info['humedad_media_pct']:.1f}% AWC**"
            )
            arr_override = _extraer_arr_timelapse(capa, paso_info)
            sufijo_key = f"tl_{paso_m}_{campo_met_sub}_{mostrar_red_2d}_{criterio_grosor_red}"
        else:
            ct1, ct2 = st.columns(2)
            paso_m1 = ct1.slider(
                "Time step Map 1 (Left)",
                min_value=1, max_value=len(secuencia),
                value=int(st.session_state.get("tl_paso_activo", 4)),
                key="tl_slider_mapa2d_izq",
            )
            paso_m2 = ct2.slider(
                "Time step Map 2 (Right)",
                min_value=1, max_value=len(secuencia),
                value=min(len(secuencia), int(st.session_state.get("tl_paso_activo", 4)) + 2),
                key="tl_slider_mapa2d_der",
            )
            p_info1 = secuencia[paso_m1 - 1]
            p_info2 = secuencia[paso_m2 - 1]
            ct1.caption(
                f"⏱️ **{p_info1['etiqueta']}** ({p_info1['fecha_txt']}) · "
                f"Depth: **{p_info1['lamina_media_mm']:.1f} mm** · Moisture: **{p_info1['humedad_media_pct']:.1f}%**"
            )
            ct2.caption(
                f"⏱️ **{p_info2['etiqueta']}** ({p_info2['fecha_txt']}) · "
                f"Depth: **{p_info2['lamina_media_mm']:.1f} mm** · Moisture: **{p_info2['humedad_media_pct']:.1f}%**"
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
        with st.expander(f"📊 Hydrological Metrics by Subwatershed — Active: {etq_met_sub}", expanded=True):
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
            f"🏞️ **Overlaid drainage network:** `{red_dren.get('fuente', 'NHD')}` · "
            f"**{red_dren.get('n_tramos', 0)} reaches** ({red_dren.get('longitud_total_km', 0)} km) scaled by stream order/accumulation."
        )

    cat = r["arrays"]["categoria"][r["mascara"]]
    ha = r["res_m"] ** 2 / 1e4
    _cols_tarjetas([(n, f"{(cat == k).sum() * ha:.2f}", "ha", f"{100 * (cat == k).mean():.1f}% of evaluated domain", t)
                    for k, n, t in ((1, "Mild ponding", ""), (2, "Moderate", "agua"), (3, "Severe", "alerta"))])


# ── 6. 3D Model ──────────────────────────────────────────────────────────────
def _puente_js_camara_3d():
    """
    Injects a lightweight JavaScript bridge that reads the 3D camera in real time (`getCamera()`:
    eye, center, up) while the user rotates, pans, or zooms with the mouse in the Plotly 3D chart.
    When clicking 'Freeze this mouse 3D view & Generate GIF', freezes that exact mouse orientation,
    sends it to Streamlit, and triggers GIF generation from that viewpoint.
    """
    import streamlit.components.v1 as components

    html_code = """
    <div id="bar_cam3d" style="font-family:'Segoe UI',sans-serif;background:#111c2e;border:1px solid #1f3350;
         border-left:4px solid #00f5d4;border-radius:9px;padding:10px 14px;display:flex;flex-wrap:wrap;
         align-items:center;justify-content:space-between;gap:10px;color:#dce6f2;box-sizing:border-box;">
      <div style="font-size:12.5px;line-height:1.4;">
        <span style="color:#00f5d4;font-weight:700;">🎥 Live 3D Orientation (drag/zoom the 3D model above with your mouse):</span>
        <span id="lbl_cam3d" style="color:#e8f1fb;margin-left:6px;font-family:monospace;font-size:12.5px;">
          Azimuth: 45°  |  Tilt: 27°  |  Zoom/Dist.: 2.05
        </span>
      </div>
      <button id="btn_freeze_gif" style="background:linear-gradient(135deg,#00b4d8,#0077b6);color:#ffffff;
              border:none;border-radius:7px;padding:8px 16px;font-weight:700;font-size:12.5px;cursor:pointer;
              box-shadow:0 2px 6px rgba(0,180,216,0.35);white-space:nowrap;">
        📸 Freeze this mouse 3D view & Generate GIF
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
            lbl.textContent = 'Azimuth: ' + azim + '°  |  Tilt: ' + elev + '°  |  Zoom/Dist.: ' + dist.toFixed(2);
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
          btn.textContent = '⏳ Freezing orientation & generating 3D GIF...';
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

    st.subheader("🧊 3D Model: Relief + Water Depth + Drainage Network & Temporal Evolution")
    r = st.session_state.get("resultado")
    if not r:
        st.info("Run the model from the sidebar.")
        return
    red_dren = st.session_state.get("red_drenaje") or r.get("red_drenaje")

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

    c1, c2, c3, c4, c5 = st.columns(5)
    exag_z = c1.slider(
        "Vertical relief exaggeration (×)",
        min_value=0.5, max_value=25.0, value=3.0, step=0.5,
        key="mod3d_exag_z_slider",
        help="Multiplier applied to topographic altitude (DEM). Applies to both the interactive 3D Model and the GIF export.",
    )
    exag_a = c2.slider(
        "Water depth exaggeration",
        min_value=1, max_value=2000, value=150, step=10,
        key="mod3d_exag_a_slider",
        help="Visual scaling factor applied to surface water thickness (mm -> m).",
    )
    vis = c3.slider(
        "Minimum visible depth (mm)",
        min_value=0.1, max_value=20.0, value=float(max(r["umbral"] * 0.5, 0.5)), step=0.1,
        key="mod3d_vis_slider",
        help="Hides very thin water films to highlight ponding basins and depressions.",
    )
    recortar = c4.checkbox(
        "Clip to domain", value=True,
        key="mod3d_recortar_chk",
        help="Clips the 3D mesh strictly to the boundaries of the active AOI (or subwatershed).",
    )
    ver_red_3d = c5.checkbox(
        "🏞️ 3D Drainage network", value=True,
        key="mod3d_red_chk",
        help="Overlays drainage network channels onto the 3D topographic surface.",
    )

    secuencia = r.get("timelapse", [])
    lamina_3d = r["arrays"]["lamina"]
    lam_ref_fija = None
    if secuencia:
        lam_ref_fija = max([float(s["lamina_max_mm"]) for s in secuencia] + [10.0])
        usar_tl_3d = st.checkbox(
            "⏱️ Scrub temporal sequence in 3D (Interactive Timelapse)",
            value=False,
            key="usar_tl_3d",
            help="Allows smooth scrubbing through storm, ponding, drainage, and drying time steps on the 3D model.",
        )
        if usar_tl_3d:
            paso_3d = st.slider(
                "3D time step",
                min_value=1, max_value=len(secuencia),
                value=int(st.session_state.get("tl_paso_activo", 4)),
                key="tl_slider_3d",
            )
            info_3d = secuencia[paso_3d - 1]
            lamina_3d = info_3d["lamina"]
            est_txt, _ = plots._estado_proceso_timelapse(paso_3d)
            st.caption(
                f"⏱️ **{info_3d['etiqueta']}** — State: **{est_txt}** · "
                f"Max depth: **{info_3d['lamina_max_mm']:.1f} mm** · "
                f"Ponded area: **{info_3d['area_enc_ha']:.2f} ha** · "
                f"Soil moisture: **{info_3d['humedad_media_pct']:.0f}% AWC**"
            )

    a = r["arrays"]
    dem_dom = r["dem"][r["mascara"]] if r["mascara"].any() else r["dem"]
    z_min_d, z_max_d = float(np.nanmin(dem_dom)), float(np.nanmax(dem_dom))
    pend_med = float(np.nanmean(a["pendiente"][r["mascara"]])) if r["mascara"].any() else float(np.nanmean(a["pendiente"]))
    _cols_tarjetas([
        ("Min elevation", f"{z_min_d:,.1f}", "m a.s.l.", "3DEP DEM in domain", ""),
        ("Max elevation", f"{z_max_d:,.1f}", "m a.s.l.", "3DEP DEM in domain", ""),
        ("Relief (ΔZ)", f"{z_max_d - z_min_d:,.1f}", "m", f"Grid: {r['dem'].shape[1]}×{r['dem'].shape[0]} cells ({r['res_m']:.0f} m)", "suelo"),
        ("Mean slope", f"{pend_med:.1f}", "%", f"Max: {float(np.nanmax(a['pendiente'][r['mascara']])):.1f}%", "alerta"),
    ])

    modo_base_3d = st.radio(
        "Visual Base / Texture over 3D Relief",
        [
            "🛰️ Event-date satellite image (cloud-free Sentinel-2)",
            "🗻 Current relief / topography (thematic variable)",
            "🌐 High-resolution satellite image (Google Satellite)",
            "🌎 High-resolution satellite image (Esri World Imagery base)",
        ],
        horizontal=True,
        key="modo_base_textura_3d",
        help=(
            "Choose how to drape the 3D surface: event-date Sentinel-2 capture (temporal consistency with field state), "
            "thematic gradient (Elevation/NDVI/NDWI/Slope/Water table), "
            "Google Satellite, or Esri World Imagery for fine detail of roads, boundaries, and depressions."
        ),
    )

    opciones = {
        "Elevation (m)": (r["dem"], TERRENO),
        "NDVI": (r["ndvi"], VERDES),
        "NDWI": (r["ndwi"], HUMEDAD),
        "Slope (%)": (a["pendiente"], CALIDOS),
        "Water table depth (m)": (a.get("prof_napa_m", r["dem"]), HUMEDAD),
    }
    nombre = "Elevation (m)"
    rgb_textura = None
    fecha_s2_activa = None
    malla_actual = st.session_state.get("grid", {}).get("malla")
    f_ev_str = pd.to_datetime(r["fecha_evento"]).strftime("%Y-%m-%d") if r.get("fecha_evento") is not None else None

    if modo_base_3d.startswith("🗻"):
        nombre = st.radio(
            "Terrain thematic variable",
            list(opciones),
            horizontal=True,
            help="Variable used to color the 3D topographic surface beneath the water layer.",
        )
    elif modo_base_3d.startswith("🛰️") and malla_actual is not None:
        try:
            with st.spinner("Downloading Sentinel-2 satellite texture closest to event…"):
                rgb_textura, f_cap, nub_pct, dt_d, fte_s2 = obtener_textura_s2_evento(malla_actual, f_ev_str)
                fecha_s2_activa = f_cap
            ref_txt = f" (±{dt_d} days relative to {f_ev_str} event)" if f_ev_str else " (latest available)"
            st.info(
                f"📅 **Temporal satellite texture applied:** Capture from **`{f_cap}`**{ref_txt} · "
                f"Source: **{fte_s2}** · Scene cloud cover: **{nub_pct:.1f}%**."
            )
        except Exception as e_s2:  # noqa: BLE001
            st.warning(f"Could not load temporal Sentinel-2 texture ({e_s2}); displaying base relief.")
            rgb_textura = None
    elif modo_base_3d.startswith("🌐") and malla_actual is not None:
        try:
            with st.spinner("Downloading high-resolution satellite texture (Google Satellite)…"):
                rgb_textura, fte_goog = obtener_textura_google_malla(malla_actual)
            st.caption(f"🌐 **Base texture applied:** `{fte_goog}` — high resolution for fine detail of roads, borders, and lows.")
        except Exception as e_gg:  # noqa: BLE001
            st.warning(f"Could not download Google Satellite texture ({e_gg}); displaying base relief.")
            rgb_textura = None
    elif modo_base_3d.startswith("🌎") and malla_actual is not None:
        try:
            with st.spinner("Downloading high-resolution satellite texture (Esri World Imagery)…"):
                rgb_textura, fte_esri = obtener_textura_esri_malla(malla_actual)
            st.caption(f"🌎 **Base texture applied:** `{fte_esri}` — high resolution for fine detail of roads, borders, and lows.")
        except Exception as e_es:  # noqa: BLE001
            st.warning(f"Could not download base satellite texture ({e_es}); displaying base relief.")
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

    _puente_js_camara_3d()

    if secuencia:
        st.markdown("---")
        with st.expander("🎬 Export 3D Timelapse GIF Animation (Using 3D Viewer Orientation)", expanded=True):
            st.caption(
                "Freely orbit, pan, and zoom the **3D Model above with your mouse** "
                "and click **📸 Freeze this mouse 3D view & Generate GIF** (right below the 3D model) or adjust additional options below."
            )
            cg_ex, cg_tex, cg_res, cg_vel = st.columns([1.3, 1.6, 1.4, 1.1])
            exag_z_gif = cg_ex.slider(
                "GIF relief exaggeration (×)",
                min_value=0.5, max_value=25.0, value=float(exag_z), step=0.5,
                key="gif_exag_z_slider",
                help="Vertical relief exaggeration level in the GIF (defaults to the upper 3D Model setting).",
            )
            tex_gif_sel = cg_tex.selectbox(
                "3D texture in GIF",
                [
                    "🛰️ Sentinel-2 from available date",
                    "🔄 Same as upper 3D viewer",
                    "🌐 Google Satellite (high-res)",
                    "🌎 Esri World Imagery (high-res)",
                    "🗻 Selected thematic variable",
                ],
                index=0,
                key="gif_textura_sel",
                help="By default drapes the 3D relief in the GIF with the cloud-free Sentinel-2 image from the available date.",
            )
            calidad_gif = cg_res.selectbox(
                "GIF Quality / Resolution",
                ["High Definition HD (1120×680 px — sharp)", "Standard (920×560 px — fast)"],
                index=0,
                key="gif_calidad_sel",
                help="Renders the continuous 3D surface with true axes, colorbar, and photographic palette.",
            )
            dur_gif_ms = cg_vel.slider(
                "Frame duration (ms)",
                min_value=350, max_value=1400, value=750, step=50,
                key="gif_dur_ms_slider",
                help="Playback speed of the GIF animation (lower value = faster).",
            )

            c_g1, c_g2 = st.columns([1.4, 2.6])
            click_manual_gif = c_g1.button("🎬 Generate 3D GIF", type="primary", use_container_width=True, key="btn_gen_gif_3d")
            if disparar_gif_auto or click_manual_gif:
                try:
                    with st.spinner(
                        f"Rendering 3D GIF with frozen orientation (Azimuth {cam_azim:.0f}° · Tilt {cam_elev:.0f}° · Zoom {cam_dist:.2f} · Exag. ×{exag_z_gif:g})…"
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
                            alta_definicion=calidad_gif.startswith("High"),
                            fecha_s2_txt=f_s2_gif,
                            cam_elev=cam_elev,
                            cam_azim=cam_azim,
                            cam_dist=cam_dist,
                            cam_center=cam_center,
                        )
                        st.session_state["gif_3d_bytes"] = gif_bytes
                        st.session_state["gif_3d_meta"] = f"Frozen view: Azimuth {cam_azim:.0f}° · Tilt {cam_elev:.0f}° · Dist. {cam_dist:.2f} · Exaggeration ×{exag_z_gif:g}"
                except Exception as e_gif:  # noqa: BLE001
                    st.error(f"Could not generate 3D GIF: {e_gif}")

            gif_guardado = st.session_state.get("gif_3d_bytes")
            if gif_guardado:
                c_g2.download_button(
                    "⬇️ Download 3D GIF (timelapse_3d.gif)",
                    data=gif_guardado,
                    file_name="timelapse_hydrological_3d.gif",
                    mime="image/gif",
                    use_container_width=True,
                    key="btn_dl_gif_3d",
                )
                meta_txt = st.session_state.get("gif_3d_meta", f"Relief exaggeration ×{exag_z_gif:g}")
                st.image(gif_guardado, caption=f"3D Timelapse GIF Preview ({meta_txt})", use_container_width=True)