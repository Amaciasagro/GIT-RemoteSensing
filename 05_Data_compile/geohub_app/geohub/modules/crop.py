"""Crop module (Crop_monitor): Sentinel-2 SR (10 m) — multi-select series, direct viewer on clicking a date in the chart and 2-layer comparator."""
import json

import folium
import numpy as np
import pandas as pd
import streamlit as st
import branca.colormap as bcm
from streamlit_folium import st_folium

from ..config import tarjeta, INDICES, CAPAS_VISUALES_CROP
from ..core import state, export, charts
from ..core.maps import mapa_base, agregar_aoi, mapa_dual_comparativo
from ..services import gee


def estadisticas(df, cols):
    """Summary table per index: n, mean, std dev, min/max with date (YYYY-MM-DD), latest value and change."""
    filas = []
    for c in cols:
        if c not in df.columns:
            continue
        s = df[["fecha", c]].dropna()
        if s.empty:
            continue
        filas.append(dict(
            indice=c,
            descripcion=INDICES.get(c, ("",))[0],
            n=len(s),
            media=s[c].mean(),
            desvio=s[c].std(),
            minimo=s[c].min(),
            fecha_min=pd.to_datetime(s.loc[s[c].idxmin(), "fecha"]).strftime("%Y-%m-%d"),
            maximo=s[c].max(),
            fecha_max=pd.to_datetime(s.loc[s[c].idxmax(), "fecha"]).strftime("%Y-%m-%d"),
            ultimo=s[c].iloc[-1],
            delta_ultimo=s[c].iloc[-1] - s[c].iloc[-2] if len(s) > 1 else np.nan,
        ))
    return pd.DataFrame(filas).round(3)


def tabla_comparativa_fechas(df, fecha_a_str, fecha_b_str, indices_cols):
    """
    Builds the numeric comparison table between Date A and Date B for the selected indices,
    including value at A, value at B, absolute difference (Δ = B - A), percentage change (Δ %) and trend.
    """
    df_f = df.copy()
    df_f["fecha_str"] = pd.to_datetime(df_f["fecha"]).dt.strftime("%Y-%m-%d")
    fila_a = df_f[df_f["fecha_str"] == str(fecha_a_str)]
    fila_b = df_f[df_f["fecha_str"] == str(fecha_b_str)]
    if fila_a.empty or fila_b.empty:
        return pd.DataFrame()

    ra = fila_a.iloc[0]
    rb = fila_b.iloc[0]
    filas = []
    for idx_nom in indices_cols:
        if idx_nom not in df_f.columns:
            continue
        va = float(ra[idx_nom]) if pd.notna(ra[idx_nom]) else np.nan
        vb = float(rb[idx_nom]) if pd.notna(rb[idx_nom]) else np.nan
        delta = (vb - va) if (pd.notna(va) and pd.notna(vb)) else np.nan
        delta_pct = (100.0 * delta / abs(va)) if (pd.notna(delta) and abs(va) > 1e-6) else np.nan
        if pd.isna(delta):
            tend = "—"
        elif abs(delta) < 0.005:
            tend = "➖ Stable"
        elif delta > 0:
            tend = "📈 Increase"
        else:
            tend = "📉 Decrease"
        filas.append({
            "Index": idx_nom,
            "Description": INDICES.get(idx_nom, ("",))[0],
            f"Date A ({fecha_a_str})": round(va, 3) if pd.notna(va) else np.nan,
            f"Date B ({fecha_b_str})": round(vb, 3) if pd.notna(vb) else np.nan,
            "Difference (Δ = B − A)": round(delta, 3) if pd.notna(delta) else np.nan,
            "Change (Δ %)": round(delta_pct, 1) if pd.notna(delta_pct) else np.nan,
            "Trend": tend,
        })
    return pd.DataFrame(filas)


def _cards(items):
    for c, it in zip(st.columns(len(items)), items):
        c.markdown(tarjeta(*it), unsafe_allow_html=True)


def render(ctx):
    st.subheader("🛰️ Crop · Sentinel-2 SR Monitoring (10 m)")
    aoi, rango = ctx["aoi"], ctx["rango"]
    if aoi is None or rango is None:
        st.info("Define an AOI and a valid date range in the sidebar.")
        return
    if not ctx["gee_ok"]:
        st.error("Google Earth Engine is not connected: this module is not available.")
        return
    f_ini, f_fin = rango
    gj = json.dumps(aoi["geom"])

    # Sensor fixed to Sentinel-2 SR (10 m), a single maximum-cloudiness control and automatic query
    sensor = "S2"
    sensor_nom = "Sentinel-2 SR (10 m)"
    c_top1, c_top2 = st.columns([2.2, 1.6])
    c_top1.markdown(
        "<div style='padding-top:8px;color:#9bb3cc;font-size:13px;'>"
        "🛰️ <b>Active sensor:</b> <code>Sentinel-2 SR Harmonized (10 m)</code> · Automatic query</div>",
        unsafe_allow_html=True,
    )
    nubes = c_top2.slider(
        "Max. allowed cloudiness (%)",
        min_value=5, max_value=80, value=30, step=5,
        key="crop_nubes",
        help="Single cloudiness threshold: automatically filters Sentinel-2 scenes in both the time series and the maps.",
    )
    firma = state.firma(aoi["id"], f_ini, f_fin, sensor, nubes)
    df, vigente = state.obtener("cultivo", firma)
    if df is None or not vigente:
        with st.spinner("Automatically computing Sentinel-2 indices in Google Earth Engine…"):
            try:
                df = gee.serie_vegetacion(gj, f_ini, f_fin, sensor, nubes)
                state.guardar("cultivo", df, firma)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not query the vegetation: {e}")
                return
    if df.empty:
        st.error("No usable Sentinel-2 images in the range at that cloud %. Widen the window or raise the cloud %.")
        return

    # ── 1. Index selector in time series (multi-select, no second coverage filter) ──
    c_s1, c_s2 = st.columns([3.0, 1.0])
    sel = c_s1.multiselect(
        "🌱 Indices to plot in the time series",
        list(INDICES),
        default=["NDVI", "LAI", "SAVI", "NDWI"],
        format_func=lambda k: f"{k} · {INDICES[k][0]}",
        key="crop_multiselect_indices",
    )
    suav = c_s2.checkbox("Smooth curve (3-obs. moving average)", key="crop_suavizar_chk")
    if not sel:
        st.info("Select at least one index to plot.")
        return

    d = df.dropna(subset=["NDVI"]).copy().sort_values("fecha").reset_index(drop=True)
    if d.empty:
        st.error("No valid observations were obtained in the period.")
        return
    cols_disp = [c for c in INDICES if c in d.columns]
    if suav:
        d[cols_disp] = d[cols_disp].rolling(3, min_periods=1, center=True).mean()

    fechas_str_lista = pd.to_datetime(d["fecha"]).dt.strftime("%Y-%m-%d").tolist()
    if "crop_fecha_activa" not in st.session_state or st.session_state["crop_fecha_activa"] not in fechas_str_lista:
        st.session_state["crop_fecha_activa"] = fechas_str_lista[-1]

    # Interactive time-series chart: clicking any point directly updates the map and the dropdown below
    fig_ts = charts.fig_indices(d, sel, fecha_seleccionada=st.session_state["crop_fecha_activa"])
    try:
        ev_ts = st.plotly_chart(
            fig_ts,
            use_container_width=True,
            on_select="rerun",
            selection_mode="points",
            key="plt_crop_ts_interactivo",
        )
        pts = ev_ts.get("selection", {}).get("points", []) if isinstance(ev_ts, dict) else getattr(getattr(ev_ts, "selection", None), "points", [])
        if pts:
            p0 = pts[0] if isinstance(pts[0], dict) else {}
            f_clic = str(p0.get("x") or p0.get("customdata") or "")[:10]
            if f_clic not in fechas_str_lista:
                p_idx = p0.get("point_index", p0.get("point_number"))
                if isinstance(p_idx, int) and 0 <= p_idx < len(fechas_str_lista):
                    f_clic = fechas_str_lista[p_idx]
            if f_clic in fechas_str_lista and f_clic != st.session_state["crop_fecha_activa"]:
                st.session_state["crop_fecha_activa"] = f_clic
                st.session_state["crop_sel_fecha_visor"] = f_clic
                st.rerun()
    except TypeError:
        st.plotly_chart(fig_ts, use_container_width=True, key="plt_crop_ts_fallback")

    if st.session_state.get("crop_sel_fecha_visor") not in fechas_str_lista:
        st.session_state["crop_sel_fecha_visor"] = st.session_state["crop_fecha_activa"]

    # ── Analysis tabs and spatial visualization ──
    t_visor, t_comp_num, t_comp_vis, t_est, t_datos = st.tabs([
        f"🖼️ Map by Date ({st.session_state['crop_fecha_activa']})",
        "⚖️ Numeric Comparison",
        "🔀 Compare 2 Layers (Side by Side)",
        "📊 Period Statistics",
        "📋 Data Table",
    ])

    # ── 2. Image viewer with date dropdown above the map and synchronized with the chart ──
    with t_visor:
        def _al_cambiar_fecha_dropdown():
            st.session_state["crop_fecha_activa"] = st.session_state["crop_sel_fecha_visor"]

        cv0, cv1, cv2, cv3 = st.columns([1.4, 1.6, 1.6, 0.9])
        fecha_visor = cv0.selectbox(
            "📅 Available date",
            fechas_str_lista,
            key="crop_sel_fecha_visor",
            on_change=_al_cambiar_fecha_dropdown,
            help="Choose an available date in this dropdown or click directly on any point of the chart above.",
        )
        st.session_state["crop_fecha_activa"] = fecha_visor

        capa_visor = cv1.selectbox(
            "Layer / Index to display on the map",
            list(CAPAS_VISUALES_CROP.keys()),
            format_func=lambda k: CAPAS_VISUALES_CROP[k],
            index=list(CAPAS_VISUALES_CROP.keys()).index(sel[0]) if sel[0] in CAPAS_VISUALES_CROP else 0,
            key="crop_capa_visor_sel",
        )
        fuente_base_visor = cv2.selectbox(
            "Base image source",
            [
                f"🛰️ Sentinel-2 RGB of the date (≤ {nubes}% clouds)",
                "🌐 Google Satellite (high resolution)",
                "🌎 Esri World Imagery (high resolution)",
                "🗺️ Google Hybrid",
            ],
            index=0,
            key="crop_fuente_base_visor",
        )
        op_visor = cv3.slider("Layer opacity", 0.2, 1.0, 0.85, 0.05, key="crop_op_visor")

        try:
            with st.spinner(f"Loading Sentinel-2 map for {fecha_visor} (≤ {nubes}% clouds)…"):
                info_tile = gee.url_mapa_fecha_cercana(
                    gj, fecha_visor, f_ini, f_fin, sensor, nubes, capa=capa_visor, recortar_aoi=True
                )
            base_pref = "Google Satellite" if "Google Satellite" in fuente_base_visor else (
                "Google Hybrid" if "Hybrid" in fuente_base_visor else "Esri World Imagery"
            )
            m_vis = mapa_base([aoi["lat"], aoi["lon"]], 14, base_preferida=base_pref)

            mostrar_rgb_s2 = fuente_base_visor.startswith("🛰️")
            folium.TileLayer(
                tiles=info_tile["url_rgb"],
                attr=f"Sentinel-2 RGB ({info_tile['fecha_escena']})",
                name=f"🛰️ Sentinel-2 RGB ({info_tile['fecha_escena']} · {info_tile['nubes_pct']:.1f}% clouds)",
                overlay=True,
                show=mostrar_rgb_s2,
                opacity=1.0,
            ).add_to(m_vis)

            if capa_visor != "TrueColor" or not mostrar_rgb_s2:
                folium.TileLayer(
                    tiles=info_tile["url_capa"],
                    attr="Google Earth Engine",
                    name=f"{capa_visor} ({info_tile['fecha_escena']})",
                    overlay=True,
                    show=True,
                    opacity=op_visor,
                ).add_to(m_vis)

            agregar_aoi(m_vis, aoi["geom"])
            if capa_visor in INDICES:
                _, vmin, vmax, pal = INDICES[capa_visor]
                bcm.LinearColormap(pal, vmin=vmin, vmax=vmax, caption=f"{capa_visor} ({info_tile['fecha_escena']})").add_to(m_vis)
            folium.LayerControl(collapsed=False).add_to(m_vis)

            # 1) Map first
            st_folium(
                m_vis,
                height=500,
                use_container_width=True,
                returned_objects=[],
                key=f"mapa_crop_f_{fecha_visor}_{capa_visor}_{base_pref}_{op_visor}",
            )

            # 2) Below the map: the "Applied satellite scene" text and the Vegetation Index cards
            st.info(
                f"🛰️ **Applied satellite scene:** **`{info_tile['fecha_escena']}`** "
                f"(Δ = {info_tile['delta_dias']} days relative to {fecha_visor}) · "
                f"Sensor: **{sensor_nom}** · Scene cloudiness: **{info_tile['nubes_pct']:.1f}%** (limit ≤ {nubes}%) · "
                f"Base map: **{base_pref}**."
            )

            fila_f = d[pd.to_datetime(d["fecha"]).dt.strftime("%Y-%m-%d") == fecha_visor].iloc[0]
            tarjetas_debajo = [
                (
                    f"{c_i} ({fecha_visor})",
                    f"{fila_f[c_i]:.3f}" if pd.notna(fila_f[c_i]) else "—",
                    "m²/m²" if c_i == "LAI" else "",
                    f"Period max.: {d[c_i].max():.3f} ({pd.to_datetime(d.loc[d[c_i].idxmax(), 'fecha']):%Y-%m-%d})",
                    "agua" if c_i in ("NDWI", "NDMI") else "",
                )
                for c_i in sel[:5]
            ]
            if tarjetas_debajo:
                _cards(tarjetas_debajo)

            # 3) Download the spatial index layer as GeoTIFF, Shapefile (.zip) or GeoJSON
            with st.expander("📥 Download vegetation index spatial layer (GeoTIFF / Shapefile / GeoJSON)", expanded=True):
                st.caption(
                    "Export the spatial layer of the selected index and date clipped to the AOI in "
                    "**GeoTIFF (`.tif`, 10 m raster)**, **Shapefile (`.zip`, vector grid `.shp`)** or **GeoJSON (`.geojson`)** format."
                )
                cd_l, cd_f, cd_fmt, cd_btn = st.columns([1.5, 1.3, 1.4, 1.3])
                capa_dl = cd_l.selectbox(
                    "Index / Layer to download",
                    list(CAPAS_VISUALES_CROP.keys()),
                    index=list(CAPAS_VISUALES_CROP.keys()).index(capa_visor),
                    format_func=lambda k: CAPAS_VISUALES_CROP[k],
                    key="crop_dl_capa_sel",
                )
                fecha_dl = cd_f.selectbox(
                    "Layer date",
                    fechas_str_lista,
                    index=fechas_str_lista.index(fecha_visor),
                    key="crop_dl_fecha_sel",
                )
                fmt_dl = cd_fmt.selectbox(
                    "File format",
                    ["GeoTIFF (.tif — 10 m raster)", "Shapefile (.zip / .shp — Vector)", "GeoJSON (.geojson — Vector)"],
                    key="crop_dl_fmt_sel",
                )
                if cd_btn.button("🚀 Prepare download", type="primary", use_container_width=True, key="btn_crop_prep_dl"):
                    try:
                        if fmt_dl.startswith("GeoTIFF"):
                            with st.spinner(f"Generating 10 m GeoTIFF of {capa_dl} ({fecha_dl}) in Earth Engine…"):
                                data_b, ext_f, f_esc_dl = gee.exportar_geotiff_indice(gj, fecha_dl, f_ini, f_fin, nubes, capa=capa_dl)
                            st.session_state["crop_dl_ready"] = dict(
                                data=data_b,
                                fname=f"{capa_dl}_{f_esc_dl}{ext_f}",
                                mime="application/zip" if ext_f == ".zip" else "image/tiff",
                                label=f"⬇️ Download {capa_dl}_{f_esc_dl}{ext_f} (GeoTIFF)",
                            )
                        else:
                            with st.spinner(f"Sampling spatial grid of {capa_dl} ({fecha_dl}) and generating vector file…"):
                                gj_b, shp_b, f_esc_dl, n_cel = gee.exportar_vector_indice(gj, fecha_dl, f_ini, f_fin, nubes, capa=capa_dl)
                            if fmt_dl.startswith("Shapefile"):
                                st.session_state["crop_dl_ready"] = dict(
                                    data=shp_b,
                                    fname=f"{capa_dl}_{f_esc_dl}_shp.zip",
                                    mime="application/zip",
                                    label=f"⬇️ Download {capa_dl}_{f_esc_dl}_shp.zip ({n_cel} .shp cells)",
                                )
                            else:
                                st.session_state["crop_dl_ready"] = dict(
                                    data=gj_b,
                                    fname=f"{capa_dl}_{f_esc_dl}.geojson",
                                    mime="application/geo+json",
                                    label=f"⬇️ Download {capa_dl}_{f_esc_dl}.geojson ({n_cel} cells)",
                                )
                    except Exception as e_dl:  # noqa: BLE001
                        st.error(f"Could not prepare the spatial download: {e_dl}")

                dl_info = st.session_state.get("crop_dl_ready")
                if dl_info:
                    st.download_button(
                        dl_info["label"],
                        data=dl_info["data"],
                        file_name=dl_info["fname"],
                        mime=dl_info["mime"],
                        use_container_width=True,
                        key="btn_crop_exec_dl",
                    )

        except Exception as e_vis:  # noqa: BLE001
            st.error(f"Could not load the viewer for date {fecha_visor}: {e_vis}")

    # ── 3. Numeric comparison (table) between two dates ──
    with t_comp_num:
        st.markdown("#### ⚖️ Numeric Comparison of Indices")
        st.caption("Select two dates from the time series to contrast the values of the selected indices, their absolute difference ($\\Delta$) and their percentage change.")
        cn1, cn2, cn3 = st.columns([1.3, 1.3, 1.4])
        idx_a_def = 0
        idx_b_def = len(fechas_str_lista) - 1
        fecha_a_num = cn1.selectbox("📅 Date A (Reference / Initial)", fechas_str_lista, index=idx_a_def, key="crop_num_fecha_a")
        fecha_b_num = cn2.selectbox("📅 Date B (Comparison / Final)", fechas_str_lista, index=idx_b_def, key="crop_num_fecha_b")
        alcance_num = cn3.radio(
            "Indices to include in the table",
            ["Indices selected above", "All available indices"],
            horizontal=True,
            key="crop_num_alcance",
        )
        cols_comparar = sel if alcance_num == "Indices selected above" else [c for c in INDICES if c in d.columns]
        df_comp_ab = tabla_comparativa_fechas(d, fecha_a_num, fecha_b_num, cols_comparar)
        if df_comp_ab.empty:
            st.warning("Select two valid dates to compare.")
        else:
            tarjetas_ab = []
            for r_ab in df_comp_ab.head(4).itertuples():
                idx_n = r_ab[1]
                v_a = r_ab[3]
                v_b = r_ab[4]
                d_ab = r_ab[5]
                d_pct = r_ab[6]
                signo = "+" if (pd.notna(d_ab) and d_ab > 0) else ""
                sub_pct = f" ({signo}{d_pct:.1f}%)" if pd.notna(d_pct) else ""
                tarjetas_ab.append((
                    f"Δ {idx_n} (B − A)",
                    f"{signo}{d_ab:.3f}" if pd.notna(d_ab) else "—",
                    sub_pct,
                    f"A: {v_a:.3f} → B: {v_b:.3f}",
                    "suelo" if (pd.notna(d_ab) and d_ab >= 0) else "alerta",
                ))
            if tarjetas_ab:
                _cards(tarjetas_ab)
            st.dataframe(df_comp_ab, use_container_width=True, hide_index=True)
            export.boton_csv(df_comp_ab, f"comparacion_{fecha_a_num}_vs_{fecha_b_num}", "dl_crop_comp_ab")
            export.registrar("cultivo_comparacion_fechas", df_comp_ab)

    # ── 4. Side-by-side visual comparison between two dates ("Compare 2 layers") ──
    with t_comp_vis:
        st.markdown("#### 🔀 Compare 2 Sentinel-2 Layers Side by Side (Synchronized)")
        st.caption(
            "Visually compare **two different dates with the same index** (e.g. NDVI evolution between two dates) "
            "or **two different indices/layers** (e.g. True Color RGB vs. NDVI or NDVI vs. NDWI), respecting the maximum cloudiness threshold."
        )
        ct_b1, ct_b2 = st.columns([2.2, 1.8])
        base_dual = ct_b1.radio(
            "Background base map in both viewers",
            ["Google Satellite", "Esri World Imagery"],
            horizontal=True,
            key="crop_dual_base_sel",
        )
        op_dual = ct_b2.slider("Opacity of the thematic layers", 0.25, 1.0, 0.85, 0.05, key="crop_dual_op_slider")

        col_izq, col_der = st.columns(2)
        with col_izq:
            st.markdown("##### ⬅️ Left Viewer (Date A / Layer 1)")
            f_izq = st.selectbox("Left Date / Observation", fechas_str_lista, index=0, key="crop_dual_f_izq")
            capa_izq = st.selectbox(
                "Left Layer / Index",
                list(CAPAS_VISUALES_CROP.keys()),
                format_func=lambda k: CAPAS_VISUALES_CROP[k],
                index=list(CAPAS_VISUALES_CROP.keys()).index(sel[0]) if sel[0] in CAPAS_VISUALES_CROP else 0,
                key="crop_dual_capa_izq",
            )
        with col_der:
            st.markdown("##### ➡️ Right Viewer (Date B / Layer 2)")
            f_der = st.selectbox("Right Date / Observation", fechas_str_lista, index=len(fechas_str_lista) - 1, key="crop_dual_f_der")
            idx_der_def = list(CAPAS_VISUALES_CROP.keys()).index(sel[1]) if (len(sel) > 1 and sel[1] in CAPAS_VISUALES_CROP) else (
                list(CAPAS_VISUALES_CROP.keys()).index(sel[0]) if sel[0] in CAPAS_VISUALES_CROP else 0
            )
            capa_der = st.selectbox(
                "Right Layer / Index",
                list(CAPAS_VISUALES_CROP.keys()),
                format_func=lambda k: CAPAS_VISUALES_CROP[k],
                index=idx_der_def,
                key="crop_dual_capa_der",
            )

        try:
            with st.spinner("Loading synchronized Sentinel-2 viewers from Google Earth Engine…"):
                t_izq = gee.url_mapa_fecha_cercana(gj, f_izq, f_ini, f_fin, sensor, nubes, capa=capa_izq, recortar_aoi=True)
                t_der = gee.url_mapa_fecha_cercana(gj, f_der, f_ini, f_fin, sensor, nubes, capa=capa_der, recortar_aoi=True)

            m_dual = mapa_dual_comparativo(
                [aoi["lat"], aoi["lon"]],
                14,
                aoi["geom"],
                cfg_izq=dict(
                    url_capa=t_izq["url_capa"],
                    nombre_capa=f"{capa_izq} ({t_izq['fecha_escena']})",
                    url_rgb=t_izq["url_rgb"],
                    nombre_rgb=f"RGB ({t_izq['fecha_escena']})",
                    opacidad=op_dual,
                ),
                cfg_der=dict(
                    url_capa=t_der["url_capa"],
                    nombre_capa=f"{capa_der} ({t_der['fecha_escena']})",
                    url_rgb=t_der["url_rgb"],
                    nombre_rgb=f"RGB ({t_der['fecha_escena']})",
                    opacidad=op_dual,
                ),
                base_preferida=base_dual,
            )
            st_folium(
                m_dual,
                height=500,
                use_container_width=True,
                returned_objects=[],
                key=f"mapa_dual_crop_{f_izq}_{capa_izq}_{f_der}_{capa_der}_{base_dual}_{op_dual}",
            )

            ci_info, cd_info = st.columns(2)
            ci_info.info(
                f"⬅️ **Applied satellite scene (Left):** `{capa_izq}` · **`{t_izq['fecha_escena']}`** "
                f"(Clouds: **{t_izq['nubes_pct']:.1f}%**)"
            )
            cd_info.info(
                f"➡️ **Applied satellite scene (Right):** `{capa_der}` · **`{t_der['fecha_escena']}`** "
                f"(Clouds: **{t_der['nubes_pct']:.1f}%**)"
            )

            df_res_dual = tabla_comparativa_fechas(d, f_izq, f_der, list(dict.fromkeys([*sel, *[c for c in (capa_izq, capa_der) if c in INDICES]])))
            if not df_res_dual.empty:
                with st.expander(f"📊 View numeric table of differences between {f_izq} (Left) and {f_der} (Right)", expanded=True):
                    st.dataframe(df_res_dual, use_container_width=True, hide_index=True)
        except Exception as e_dual:  # noqa: BLE001
            st.error(f"Could not load the 2-layer comparator: {e_dual}")

    with t_est:
        est = estadisticas(d, sel)
        st.dataframe(est, use_container_width=True, hide_index=True)
        export.boton_csv(est, "cultivo_estadisticas", "dl_crop_e")
        export.registrar("cultivo_estadisticas", est)

    with t_datos:
        out = d[["fecha", *sel, "valid"]].copy()
        out["fecha"] = pd.to_datetime(out["fecha"]).dt.strftime("%Y-%m-%d")
        out = out.rename(columns={"valid": "cobertura_valida_pct"}).round(3)
        st.dataframe(out, use_container_width=True, hide_index=True)
        export.boton_csv(out, "cultivo_serie", "dl_crop_d")
        export.registrar("cultivo_serie", out)
