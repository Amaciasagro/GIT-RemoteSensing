"""
Tab 1 — Soil Information
  • Choropleth map by texture
  • Choropleth map by MUKey
  • Agronomic tabular report
  • Depth-profile charts (granulometry + properties)
  • Download: GeoJSON, Shapefile, CSV, Excel
"""
import io
import json
import warnings

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from streamlit_folium import st_folium

from utils.soil_data import (
    HORIZON_COLS,
    MAP_VARIABLES,
    TEXTURE_PALETTE,
    build_mukeys_str,
    calc_weighted_average,
    fetch_horizon_data,
    fetch_texture_data,
    fetch_wfs_soils,
    get_texture_class,
    MAX_DEPTH_CM,
)
from utils.export import (
    df_to_csv_bytes,
    df_to_excel_bytes,
    gdf_to_geojson_bytes,
    gdf_to_shapefile_zip,
    fig_to_html_bytes,
)

warnings.filterwarnings("ignore")

TEXTURE_COLS = ["claytotal_r", "silttotal_r", "sandtotal_r"]
TEXTURE_NAMES = {"claytotal_r": "Clay", "silttotal_r": "Silt", "sandtotal_r": "Sand"}
TEXTURE_COLORS = {"claytotal_r": "#8B0000", "silttotal_r": "#C68642", "sandtotal_r": "#F4A460"}


# ── helpers ────────────────────────────────────────────────────────────────

def _mukeys_str(gdf_clipped):
    return build_mukeys_str(gdf_clipped["mukey"])


def _build_texture_render(gdf_clipped, df_texture):
    gdf_render = gdf_clipped[["mukey", "musym", "geometry"]].copy()
    gdf_render["mukey"] = gdf_render["mukey"].astype(str)
    if not df_texture.empty:
        dom = (
            df_texture.sort_values("pct", ascending=False)
            .drop_duplicates("mukey")[["mukey", "texture"]]
        )
        dom["mukey"] = dom["mukey"].astype(str)
        gdf_render = gdf_render.merge(dom, on="mukey", how="left").fillna(
            {"texture": "No Data"}
        )
    else:
        gdf_render["texture"] = "No Data"
    return gdf_render


def _choropleth_texture(gdf_render, gdf_field):
    centroid = gdf_field.geometry.centroid.iloc[0]
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=13,
        tiles="Esri.WorldImagery",
        attr="Esri",
    )
    # Field boundary
    folium.GeoJson(
        gdf_field.__geo_interface__,
        style_function=lambda _: {"color": "white", "weight": 2.5, "fillOpacity": 0},
    ).add_to(m)
    # Soil polygons by texture
    for texture, group in gdf_render.groupby("texture"):
        color = TEXTURE_PALETTE.get(texture, "#AAAAAA")
        folium.GeoJson(
            group.__geo_interface__,
            style_function=lambda _, c=color: {
                "color": "#555",
                "weight": 1,
                "fillColor": c,
                "fillOpacity": 0.65,
            },
            highlight_function=lambda _, c=color: {"fillColor": c, "fillOpacity": 0.9},
            tooltip=folium.GeoJsonTooltip(fields=["mukey", "musym", "texture"]),
            name=f"Texture: {texture}",
        ).add_to(m)
    folium.LayerControl().add_to(m)
    return m


def _choropleth_mukey(gdf_render, gdf_field):
    import matplotlib.cm as cm
    centroid = gdf_field.geometry.centroid.iloc[0]
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=13,
        tiles="Esri.WorldImagery",
        attr="Esri",
    )
    folium.GeoJson(
        gdf_field.__geo_interface__,
        style_function=lambda _: {"color": "white", "weight": 2.5, "fillOpacity": 0},
    ).add_to(m)
    mukeys = gdf_render["mukey"].unique().tolist()
    cmap = cm.get_cmap("tab20", len(mukeys))
    mukey_colors = {mk: "#{:02x}{:02x}{:02x}".format(*[int(v * 255) for v in cmap(i)[:3]])
                    for i, mk in enumerate(mukeys)}
    for mukey, group in gdf_render.groupby("mukey"):
        color = mukey_colors.get(str(mukey), "#AAAAAA")
        folium.GeoJson(
            group.__geo_interface__,
            style_function=lambda _, c=color: {
                "color": "#555", "weight": 1,
                "fillColor": c, "fillOpacity": 0.70,
            },
            highlight_function=lambda _, c=color: {"fillColor": c, "fillOpacity": 0.95},
            tooltip=folium.GeoJsonTooltip(fields=["mukey", "musym"]),
            name=f"MUKey: {mukey}",
        ).add_to(m)
    folium.LayerControl().add_to(m)
    return m


def _profile_chart(df_horizons, musym_map, selected_mukeys, variable_label, variable_col):
    n = len(selected_mukeys)
    is_texture = (variable_col == "texture")
    fig = make_subplots(
        rows=1, cols=n,
        subplot_titles=[f"Unit {musym_map.get(mk, mk)}" for mk in selected_mukeys],
        shared_yaxes=True,
    )
    for col_idx, mk in enumerate(selected_mukeys, start=1):
        df_mu = df_horizons[df_horizons["mukey"].astype(str) == str(mk)]
        if df_mu.empty:
            continue
        comp_dom = df_mu.sort_values("comppct_r", ascending=False)["cokey"].iloc[0]
        df_comp = df_mu[df_mu["cokey"] == comp_dom].sort_values("hzdept_r")
        compname = df_comp["compname"].iloc[0]
        comppct = df_comp["comppct_r"].iloc[0]

        if is_texture:
            for var_tex in TEXTURE_COLS:
                xs, ys, widths = [], [], []
                for _, hz in df_comp.iterrows():
                    val = hz[var_tex] if not pd.isna(hz[var_tex]) else 0
                    mid = (hz["hzdept_r"] + hz["hzdepb_r"]) / 2
                    xs.append(val); ys.append(mid)
                    widths.append(hz["hzdepb_r"] - hz["hzdept_r"])
                fig.add_trace(go.Bar(
                    x=xs, y=ys, orientation="h",
                    name=TEXTURE_NAMES[var_tex],
                    marker_color=TEXTURE_COLORS[var_tex],
                    text=[f"{v:.0f}%" if v > 0 else "" for v in xs],
                    textposition="inside",
                    hovertemplate=f"<b>{TEXTURE_NAMES[var_tex]}</b><br>Val: %{{x:.1f}}%<br>Depth: %{{y}} cm<extra></extra>",
                    legendgroup=TEXTURE_NAMES[var_tex],
                    showlegend=(col_idx == 1),
                    width=widths,
                ), row=1, col=col_idx)
        else:
            xs, ys = [], []
            for _, hz in df_comp.iterrows():
                val = hz[variable_col] if not pd.isna(hz[variable_col]) else None
                xs.extend([val, val])
                ys.extend([hz["hzdept_r"], hz["hzdepb_r"]])
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines",
                fill="tozerox", fillcolor="rgba(41,128,185,0.15)",
                line=dict(color="#2980b9", width=2.5),
                name=compname,
                showlegend=(col_idx == 1),
                hovertemplate=f"<b>{variable_label}</b><br>Val: %{{x:.2f}}<br>Depth: %{{y}} cm<extra></extra>",
            ), row=1, col=col_idx)
            fig.add_hline(y=MAX_DEPTH_CM, line_dash="dash", line_color="#27ae60",
                          annotation_text=f"{MAX_DEPTH_CM} cm root zone",
                          annotation_position="bottom right", row=1, col=col_idx)

        fig.layout.annotations[col_idx - 1]["text"] = (
            f"<b>Unit {musym_map.get(mk, mk)}</b><br>"
            f"<span style='font-size:11px;color:#555;'>{compname} ({comppct:.0f}%)</span>"
        )

    prof_max = df_horizons["hzdepb_r"].max() if not df_horizons.empty else 200
    fig.update_layout(
        title=f"📊 Depth Profile — {variable_label}",
        barmode="stack" if is_texture else None,
        height=560, template="plotly_white",
        legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center"),
        margin=dict(t=100, b=80),
    )
    for i in range(1, n + 1):
        yax = f"yaxis{i}" if i > 1 else "yaxis"
        fig.update_layout(**{yax: dict(autorange="reversed",
                                       title="Depth (cm)" if i == 1 else "",
                                       range=[prof_max + 5, 0], gridcolor="#eee")})
        xax = f"xaxis{i}" if i > 1 else "xaxis"
        fig.update_layout(**{xax: dict(title="(%)" if is_texture else variable_label,
                                       gridcolor="#eee")})
    return fig


# ── Main render ────────────────────────────────────────────────────────────

def render(state: dict):
    st.header("🌱 Soil Information")

    geom_shp = state.get("field_geom_shp")
    if geom_shp is None:
        st.warning("⚠️ Please define your AOI in the **AOI** tab first.")
        return

    gdf_field = state["gdf_field"]

    # ── Fetch data (cached in state) ───────────────────────────────────────
    if "gdf_clipped" not in state or state.get("soil_geom_key") != str(geom_shp.bounds):
        with st.spinner("📡 Downloading soil data from USDA WFS…"):
            try:
                gdf_clipped = fetch_wfs_soils(geom_shp)
                state["gdf_clipped"] = gdf_clipped
                state["soil_geom_key"] = str(geom_shp.bounds)
            except Exception as e:
                st.error(f"WFS Error: {e}")
                return

    gdf_clipped = state["gdf_clipped"]
    mukeys_str = _mukeys_str(gdf_clipped)
    musym_map = (
        gdf_clipped[["mukey", "musym"]].drop_duplicates()
        .set_index("mukey")["musym"].to_dict()
    )

    if "df_texture" not in state or state.get("soil_geom_key") != state.get("tex_geom_key"):
        with st.spinner("📡 Fetching texture data from SDA…"):
            try:
                df_texture = fetch_texture_data(mukeys_str)
                state["df_texture"] = df_texture
                state["tex_geom_key"] = state["soil_geom_key"]
            except Exception as e:
                st.warning(f"Texture query failed: {e}")
                state["df_texture"] = pd.DataFrame()

    if "df_horizons" not in state or state.get("soil_geom_key") != state.get("hz_geom_key"):
        with st.spinner("📡 Fetching full horizon data from SDA…"):
            try:
                df_horizons = fetch_horizon_data(mukeys_str)
                state["df_horizons"] = df_horizons
                state["hz_geom_key"] = state["soil_geom_key"]
            except Exception as e:
                st.warning(f"Horizon query failed: {e}")
                state["df_horizons"] = pd.DataFrame()

    df_texture = state["df_texture"]
    df_horizons = state["df_horizons"]
    gdf_render = _build_texture_render(gdf_clipped, df_texture)

    st.success(f"✅ {len(gdf_clipped)} soil map units loaded.")

    # ── Tabs within this tab ───────────────────────────────────────────────
    sub1, sub2, sub3, sub4 = st.tabs([
        "🗺️ Texture Map", "🔑 MUKey Map", "📋 Agronomic Report", "📊 Depth Profiles"
    ])

    # ── Sub-tab 1: Texture choropleth ─────────────────────────────────────
    with sub1:
        st.subheader("Soil Texture Choropleth Map")
        with st.spinner("Rendering map…"):
            m_tex = _choropleth_texture(gdf_render, gdf_field)
        st_folium(m_tex, width=800, height=500, returned_objects=[])

        # Legend
        st.markdown("**Texture Legend**")
        present = gdf_render["texture"].unique().tolist()
        cols = st.columns(min(len(present), 6))
        for i, tex in enumerate(present):
            cols[i % 6].markdown(
                f'<span style="background:{TEXTURE_PALETTE.get(tex,"#aaa")};'
                f'padding:3px 10px;border-radius:4px;color:white;font-size:12px;">{tex}</span>',
                unsafe_allow_html=True,
            )

        st.markdown("#### ⬇️ Download")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("📥 GeoJSON (Clipped Soils)", gdf_to_geojson_bytes(gdf_render),
                               "soils_texture.geojson", "application/json")
        with c2:
            st.download_button("📥 Shapefile (.zip)", gdf_to_shapefile_zip(gdf_render, "soils_texture"),
                               "soils_texture.zip", "application/zip")

    # ── Sub-tab 2: MUKey choropleth ────────────────────────────────────────
    with sub2:
        st.subheader("Soil Map Units (MUKey) Map")
        with st.spinner("Rendering map…"):
            m_mk = _choropleth_mukey(gdf_render, gdf_field)
        st_folium(m_mk, width=800, height=500, returned_objects=[])

        st.markdown("#### ⬇️ Download")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("📥 GeoJSON", gdf_to_geojson_bytes(gdf_clipped),
                               "soils_mukey.geojson", "application/json")
        with c2:
            st.download_button("📥 Shapefile (.zip)", gdf_to_shapefile_zip(gdf_clipped, "soils_mukey"),
                               "soils_mukey.zip", "application/zip")

    # ── Sub-tab 3: Agronomic report ────────────────────────────────────────
    with sub3:
        st.subheader("Agronomic Tabular Report")
        if df_horizons.empty:
            st.warning("No horizon data available.")
        else:
            display_cols = [
                "mukey", "compname", "comppct_r", "hzname", "hzdept_r", "hzdepb_r",
                "sandtotal_r", "silttotal_r", "claytotal_r",
                "dbovendry_r", "om_r", "ph1to1h2o_r",
                "cec7_r", "ec_r", "esp_r", "sar_r",
                "wthirdbar_r", "wfifteenbar_r",
            ]
            show_df = df_horizons[[c for c in display_cols if c in df_horizons.columns]].copy()
            show_df.columns = [c.replace("_r", "").replace("total", "") for c in show_df.columns]
            st.dataframe(show_df, use_container_width=True, height=400)

            st.markdown("#### ⬇️ Download")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥 CSV", df_to_csv_bytes(df_horizons),
                                   "horizons.csv", "text/csv")
            with c2:
                st.download_button("📥 Excel", df_to_excel_bytes(df_horizons, "Horizons"),
                                   "horizons.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ── Sub-tab 4: Depth profiles ──────────────────────────────────────────
    with sub4:
        st.subheader("Depth Profile Charts")
        if df_horizons.empty:
            st.warning("No horizon data available.")
            return

        mukeys_disp = df_horizons["mukey"].unique().tolist()
        options = [f"Unit {musym_map.get(str(mk), mk)} (mukey: {mk})" for mk in mukeys_disp]

        col_l, col_r = st.columns([1, 2])
        with col_l:
            var_options = ["Texture (Clay / Silt / Sand)"] + list(MAP_VARIABLES.keys())
            var_sel = st.selectbox("Variable", var_options, key="profile_var")
            unit_sel = st.multiselect("Map Units", options, default=options[:min(3, len(options))],
                                       key="profile_units")
            btn_gen = st.button("📊 Generate Profiles", key="btn_profiles")

        if btn_gen and unit_sel:
            selected_mukeys = [opt.split("mukey: ")[1].rstrip(")") for opt in unit_sel]
            variable_col = "texture" if "Texture" in var_sel else MAP_VARIABLES.get(var_sel)

            with st.spinner("Generating profile chart…"):
                fig = _profile_chart(df_horizons, musym_map, selected_mukeys, var_sel, variable_col)

            with col_r:
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### ⬇️ Download Chart")
            c1, c2 = st.columns(2)
            with c1:
                html_bytes = fig_to_html_bytes(fig)
                st.download_button("📥 Interactive HTML", html_bytes,
                                   "depth_profiles.html", "text/html")
            with c2:
                img_bytes = fig.to_image(format="png", width=1200, height=600)
                st.download_button("📥 PNG Image", img_bytes,
                                   "depth_profiles.png", "image/png")
