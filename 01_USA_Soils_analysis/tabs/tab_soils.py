"""
Tab 1 — Soil Information
  • Sub-tab 1: Unified choropleth map (Texture / MUKey / any agronomic variable)
  • Sub-tab 2: Agronomic Report — notebook-style HTML table with alerts & weighted averages
  • Sub-tab 3: Depth Profiles (granulometric + any variable)
"""
import io
import json
import math
import urllib.parse
import warnings

import folium
import geopandas as gpd
import matplotlib.cm as cm_mpl
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from shapely.ops import unary_union
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

# ── Constants ──────────────────────────────────────────────────────────────
TEXTURE_COLS   = ["claytotal_r", "silttotal_r", "sandtotal_r"]
TEXTURE_NAMES  = {"claytotal_r": "Clay", "silttotal_r": "Silt", "sandtotal_r": "Sand"}
TEXTURE_COLORS = {"claytotal_r": "#8B0000", "silttotal_r": "#C68642", "sandtotal_r": "#F4A460"}
N_FACTOR       = 0.05

ALL_MAP_LAYERS = {
    "🎨 Texture Class":               "__texture__",
    "🔑 MUKey":                       "__mukey__",
    **MAP_VARIABLES,
    "Est. N / N estimado (%) ⚠️":    "n_estimado_r",
}

TABLE_COL_DEFS = [
    ("Hz / Horiz",          "hzname",          "",    0),
    ("Depth / Prof (cm)",   "__depth__",        "",    0),
    ("Sand / Arena %",      "sandtotal_r",      "",    1),
    ("Silt / Limo %",       "silttotal_r",      "",    1),
    ("Clay / Arcilla %",    "claytotal_r",      "🏔️",  1),
    ("Texture / Textura",   "__texture__",      "",    0),
    ("Dens. (g/cm³)",       "dbovendry_r",      "",    2),
    ("H₂O 10kPa (%)",       "wtenthbar_r",      "",    1),
    ("H₂O 33kPa (%)",       "wthirdbar_r",      "",    1),
    ("H₂O 1500kPa (%)",     "wfifteenbar_r",    "",    1),
    ("OM / MO (%)",         "om_r",             "🌿",  2),
    ("pH (H₂O 1:1)",        "ph1to1h2o_r",      "⚗️",  2),
    ("EC / CE (dS/m)",      "ec_r",             "💧",  2),
    ("ECEC",                "ecec_r",           "",    1),
    ("ESP / PSI (%)",       "esp_r",            "🧂",  1),
    ("SAR",                 "sar_r",            "🧂",  1),
    ("CEC / CIC",           "cec7_r",           "",    1),
    ("Est. N (%)",          "n_estimado_r",     "",    3),
]

HTML_LEGEND = (
    '<div style="font-family:sans-serif;font-size:11px;margin:12px 0 18px;padding:10px 16px;'
    'background:#fafafa;border:1px solid #ddd;border-radius:6px;display:flex;flex-wrap:wrap;'
    'gap:8px;align-items:center;">'
    '<b style="color:#333;margin-right:5px;">🔔 Alerts / Alertas:</b>'
    '<span style="background:#ffe4e1;color:#8b0000;padding:2px 8px;border-radius:10px;font-weight:600;font-size:10px;">🔴 CRITICAL / CRÍTICO</span>'
    '<span style="background:#fff9e6;color:#b8860b;padding:2px 8px;border-radius:10px;font-weight:600;font-size:10px;">🟡 WARNING / ALERTA</span>'
    '<span style="background:#f0f9f0;color:#2d6a2d;padding:2px 8px;border-radius:10px;font-size:10px;">🟢 OPTIMAL / ÓPTIMO</span>'
    '<span style="color:#666;font-size:10px;">'
    '&nbsp;EC/CE ≥2 Warn / ≥4 Crit'
    '&nbsp;|&nbsp; ESP/PSI ≥6 Warn / ≥15 Crit'
    '&nbsp;|&nbsp; SAR ≥9 Warn / ≥13 Crit'
    '&nbsp;|&nbsp; pH &lt;5.5 or &gt;8.5 Warn'
    '&nbsp;|&nbsp; Clay/Arcilla ≥40% Warn'
    '&nbsp;|&nbsp; OM/MO &lt;1% Warn / &lt;0.5% Crit'
    '&nbsp;|&nbsp; Dens. ≥1.6 Warn / ≥1.75 Crit'
    '</span></div>'
)


# ── Alert / formatting helpers ─────────────────────────────────────────────

def get_alert_style(col, val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "color:#999;text-align:center;"
    CRITICAL = "background:#ffe4e1;color:#8b0000;font-weight:600;text-align:center;border-radius:3px;"
    WARNING  = "background:#fff9e6;color:#b8860b;font-weight:600;text-align:center;border-radius:3px;"
    GOOD     = "background:#f0f9f0;color:#2d6a2d;text-align:center;"
    NORMAL   = "text-align:center;color:#333;"
    v = float(val)
    if col == "ec_r":         return CRITICAL if v >= 4  else (WARNING if v >= 2  else NORMAL)
    if col == "esp_r":        return CRITICAL if v >= 15 else (WARNING if v >= 6  else NORMAL)
    if col == "sar_r":        return CRITICAL if v >= 13 else (WARNING if v >= 9  else NORMAL)
    if col in ("ph1to1h2o_r", "phsaturated_r"):
        if v <= 4.5 or v >= 9.0: return CRITICAL
        if v <= 5.5 or v >= 8.5: return WARNING
    if col == "claytotal_r":  return CRITICAL if v >= 50 else (WARNING if v >= 40 else NORMAL)
    if col == "om_r":
        if v < 0.5:  return CRITICAL
        if v < 1.0:  return WARNING
        if v >= 3.0: return GOOD
    if col in ("cec7_r", "ecec_r"): return CRITICAL if v < 6 else (WARNING if v < 10 else NORMAL)
    if col == "dbovendry_r":  return CRITICAL if v >= 1.75 else (WARNING if v >= 1.6 else NORMAL)
    return NORMAL


def fmt(val, decimals=1):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return '<span style="color:#ccc;">—</span>'
    return f"{val:.{decimals}f}"


# ── HTML table builders ────────────────────────────────────────────────────

def _build_header():
    ths = [
        f'<th style="padding:7px 9px;background:#f5f5f5;color:#444;border:1px solid #ddd;'
        f'white-space:nowrap;font-size:11px;font-weight:600;text-align:center;">'
        f'{badge} {label}</th>'
        for label, col, badge, _ in TABLE_COL_DEFS
    ]
    return "<tr>" + "".join(ths) + "</tr>"


def _build_data_row(hz, bg):
    tds = []
    tex = get_texture_class(hz.get("sandtotal_r"), hz.get("silttotal_r"), hz.get("claytotal_r"))
    for label, col, badge, decs in TABLE_COL_DEFS:
        if col == "__depth__":
            top, bot = hz.get("hzdept_r"), hz.get("hzdepb_r")
            ts = str(int(top)) if pd.notna(top) else "?"
            bs = str(int(bot)) if pd.notna(bot) else "?"
            tds.append(
                f'<td style="text-align:center;border:1px solid #e8e8e8;padding:5px 7px;'
                f'white-space:nowrap;color:#555;font-size:11px;">{ts}–{bs}</td>'
            )
        elif col == "__texture__":
            color = TEXTURE_PALETTE.get(tex, "#aaa")
            tds.append(
                f'<td style="text-align:center;border:1px solid #e8e8e8;padding:5px 7px;">'
                f'<span style="background:{color}18;color:{color};border:1px solid {color}50;'
                f'padding:2px 6px;border-radius:8px;font-size:10px;white-space:nowrap;">{tex}</span></td>'
            )
        elif col == "hzname":
            tds.append(
                f'<td style="padding:5px 9px;border:1px solid #e8e8e8;font-weight:600;'
                f'color:#333;font-size:12px;">{hz.get(col, "—")}</td>'
            )
        else:
            val   = hz.get(col)
            style = get_alert_style(col, val)
            tds.append(
                f'<td style="padding:5px 7px;border:1px solid #e8e8e8;font-size:11px;{style}">'
                f'{fmt(val, decs)}</td>'
            )
    return f'<tr style="background:{bg};">' + "".join(tds) + "</tr>"


def _build_wpavg_row(wp_dict):
    tds = []
    tex_w = get_texture_class(
        wp_dict.get("sandtotal_r_wpavg"),
        wp_dict.get("silttotal_r_wpavg"),
        wp_dict.get("claytotal_r_wpavg"),
    )
    for label, col, badge, decs in TABLE_COL_DEFS:
        if col == "__depth__":
            tds.append(
                f'<td style="text-align:center;border:1px solid #c8d9e8;padding:6px 7px;'
                f'font-size:10px;color:#567;font-style:italic;">0–{MAX_DEPTH_CM} cm</td>'
            )
        elif col == "__texture__":
            color = TEXTURE_PALETTE.get(tex_w, "#aaa")
            tds.append(
                f'<td style="text-align:center;border:1px solid #c8d9e8;padding:6px 7px;">'
                f'<span style="background:{color}18;color:{color};border:1px solid {color}50;'
                f'padding:2px 6px;border-radius:8px;font-size:10px;">{tex_w}</span></td>'
            )
        elif col == "hzname":
            tds.append(
                f'<td style="padding:6px 9px;border:1px solid #c8d9e8;font-weight:600;'
                f'color:#456;font-size:11px;white-space:nowrap;">'
                f'⚖️ Wt. Avg / Prom. (0–{MAX_DEPTH_CM}cm)</td>'
            )
        else:
            wp_col = f"{col}_wpavg" if col and not col.startswith("__") else None
            val    = wp_dict.get(wp_col) if wp_col else None
            style  = get_alert_style(col, val)
            tds.append(
                f'<td style="padding:6px 7px;border:1px solid #c8d9e8;font-size:11px;{style}">'
                f'{fmt(val, decs)}</td>'
            )
    return '<tr style="background:#e8f1f8;border-top:2px solid #567;">' + "".join(tds) + "</tr>"


def _build_html_report(df_horizons, gdf_clipped, df_wpavg):
    gdf_areas           = gdf_clipped.copy()
    gdf_areas["mukey"]  = gdf_areas["mukey"].astype(str)
    gdf_areas["area_ha"] = gdf_areas.geometry.to_crs(epsg=6933).area / 10_000
    musym_map = gdf_areas.groupby("mukey")["musym"].first().to_dict()
    area_map  = gdf_areas.groupby("mukey")["area_ha"].sum().to_dict()
    wpavg_lookup = (
        df_wpavg.set_index("mukey").to_dict("index")
        if df_wpavg is not None and not df_wpavg.empty else {}
    )

    html = (
        f'<div style="font-family:sans-serif;max-width:100%;overflow-x:auto;">'
        f'{HTML_LEGEND}'
        f'<p style="color:#555;font-size:12px;margin:0 0 12px;">📊 <b>'
        f'{df_horizons["mukey"].nunique()} Map Units (MUKeys)</b>. '
        f'Dominant component horizons + weighted average 0–{MAX_DEPTH_CM} cm.</p>'
    )

    for mukey, df_mu in df_horizons.groupby("mukey"):
        mukey_str = str(mukey)
        musym     = musym_map.get(mukey_str, mukey_str)
        area_ha   = area_map.get(mukey_str, 0)
        comp_dom  = df_mu.sort_values("comppct_r", ascending=False)["cokey"].iloc[0]
        df_dom    = df_mu[df_mu["cokey"] == comp_dom].sort_values("hzdept_r").reset_index(drop=True)
        compname  = df_dom["compname"].iloc[0]
        comppct   = df_dom["comppct_r"].iloc[0]
        n_hz      = len(df_dom)
        url_ficha = (
            "https://casoilresource.lawr.ucdavis.edu/sde/?series="
            f"{urllib.parse.quote(compname.lower())}#osd"
        )
        html += (
            f'<details open style="margin-bottom:16px;border:1px solid #d0d0d0;border-radius:8px;'
            f'overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.05);">'
            f'<summary style="background:linear-gradient(135deg,#f7f7f7,#e8e8e8);padding:11px 16px;'
            f'font-weight:600;cursor:pointer;color:#333;font-size:13px;list-style:none;display:flex;'
            f'flex-wrap:wrap;align-items:center;gap:10px;">'
            f'<span style="background:#fff;padding:3px 9px;border-radius:12px;font-size:12px;'
            f'border:1px solid #ccc;">MUKey {mukey_str}</span>'
            f'<span>Unit/Unidad: <b>{musym}</b></span>'
            f'<span style="opacity:0.5;">|</span>'
            f'<span><a href="{url_ficha}" target="_blank" style="color:#3498db;text-decoration:none;'
            f'border-bottom:1px dashed #3498db;">{compname}</a> 🔗'
            f'<span style="opacity:0.6;font-weight:normal;"> ({comppct:.0f}% dom.)</span></span>'
            f'<span style="opacity:0.5;">|</span>'
            f'<span style="opacity:0.8;">{area_ha:.1f} ha &nbsp;· {n_hz} horiz.</span>'
            f'</summary>'
            f'<div style="padding:12px;background:#fff;overflow-x:auto;">'
            f'<table style="width:100%;border-collapse:collapse;font-size:12px;">'
            f'<thead>{_build_header()}</thead><tbody>'
        )
        for i, (_, hz) in enumerate(df_dom.iterrows()):
            html += _build_data_row(hz.to_dict(), "#fdfdfd" if i % 2 == 0 else "#ffffff")
        html += _build_wpavg_row(wpavg_lookup.get(mukey_str, {}))
        html += "</tbody></table></div></details>"

    return html + "</div>"


# ── Weighted averages ──────────────────────────────────────────────────────

def _calc_wpavg_all(df_horizons):
    def _wpavg_by_mukey(variable):
        results = []
        for mukey, df_mu in df_horizons.groupby("mukey"):
            comp_dom = df_mu.sort_values("comppct_r", ascending=False)["cokey"].iloc[0]
            df_comp  = df_mu[df_mu["cokey"] == comp_dom]
            value    = calc_weighted_average(df_comp, variable)
            results.append({"mukey": str(mukey), f"{variable}_wpavg": value})
        return pd.DataFrame(results)

    all_vars = list(MAP_VARIABLES.values()) + ["n_estimado_r"]
    frames   = [_wpavg_by_mukey(col) for col in all_vars if col in df_horizons.columns]
    if not frames:
        return pd.DataFrame()
    df_out = frames[0].copy()
    for df_tmp in frames[1:]:
        df_out = df_out.merge(df_tmp, on="mukey", how="outer")
    return df_out


# ── Unified choropleth ─────────────────────────────────────────────────────

def _build_unified_map(layer_key, gdf_clipped, gdf_field, df_texture, gdf_wpavg):
    centroid = gdf_field.geometry.centroid.iloc[0]
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=13, tiles="Esri.WorldImagery", attr="Esri",
    )
    folium.GeoJson(
        gdf_field.__geo_interface__,
        style_function=lambda _: {"color": "white", "weight": 2.5, "fillOpacity": 0},
    ).add_to(m)

    layer_col = ALL_MAP_LAYERS[layer_key]

    if layer_col == "__texture__":
        gdf_render = gdf_clipped[["mukey", "musym", "geometry"]].copy()
        gdf_render["mukey"] = gdf_render["mukey"].astype(str)
        if not df_texture.empty:
            dom = (
                df_texture.sort_values("pct", ascending=False)
                .drop_duplicates("mukey")[["mukey", "texture"]]
            )
            dom["mukey"] = dom["mukey"].astype(str)
            gdf_render = gdf_render.merge(dom, on="mukey", how="left").fillna({"texture": "No Data"})
        else:
            gdf_render["texture"] = "No Data"
        for texture, group in gdf_render.groupby("texture"):
            color = TEXTURE_PALETTE.get(texture, "#AAAAAA")
            folium.GeoJson(
                group.__geo_interface__,
                style_function=lambda _, c=color: {
                    "color": "#555", "weight": 1, "fillColor": c, "fillOpacity": 0.65,
                },
                highlight_function=lambda _, c=color: {"fillColor": c, "fillOpacity": 0.9},
                tooltip=folium.GeoJsonTooltip(fields=["mukey", "musym", "texture"]),
                name=f"Texture: {texture}",
            ).add_to(m)

    elif layer_col == "__mukey__":
        gdf_render = gdf_clipped[["mukey", "musym", "geometry"]].copy()
        mukeys = gdf_render["mukey"].unique().tolist()
        cmap   = cm_mpl.get_cmap("tab20", len(mukeys))
        mukey_colors = {
            mk: "#{:02x}{:02x}{:02x}".format(*[int(v * 255) for v in cmap(i)[:3]])
            for i, mk in enumerate(mukeys)
        }
        for mukey, group in gdf_render.groupby("mukey"):
            color = mukey_colors.get(mukey, "#AAAAAA")
            folium.GeoJson(
                group.__geo_interface__,
                style_function=lambda _, c=color: {
                    "color": "#555", "weight": 1, "fillColor": c, "fillOpacity": 0.70,
                },
                highlight_function=lambda _, c=color: {"fillColor": c, "fillOpacity": 0.95},
                tooltip=folium.GeoJsonTooltip(fields=["mukey", "musym"]),
                name=f"MUKey: {mukey}",
            ).add_to(m)

    else:  # continuous numeric variable
        wpavg_col = f"{layer_col}_wpavg"
        if gdf_wpavg is None or wpavg_col not in gdf_wpavg.columns:
            return m
        gdf_num = gdf_clipped[["mukey", "musym", "geometry"]].copy()
        gdf_num["mukey"] = gdf_num["mukey"].astype(str)
        gdf_num = gdf_num.merge(
            gdf_wpavg[["mukey", wpavg_col]].rename(columns={wpavg_col: "value"}),
            on="mukey", how="left",
        )
        valid = gdf_num["value"].dropna()
        if valid.empty:
            return m
        vmin, vmax = valid.min(), valid.max()
        cmap = cm_mpl.get_cmap("RdYlGn_r")

        def _color(val):
            if pd.isna(val): return "#AAAAAA"
            norm = (val - vmin) / (vmax - vmin + 1e-9)
            r, g, b, _ = cmap(norm)
            return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

        gdf_num["color"]     = gdf_num["value"].apply(_color)
        gdf_num["value_str"] = gdf_num["value"].apply(
            lambda v: f"{v:.2f}" if pd.notna(v) else "—"
        )
        for _, row in gdf_num.iterrows():
            color = row["color"]
            folium.GeoJson(
                row["geometry"].__geo_interface__,
                style_function=lambda _, c=color: {
                    "color": "#444", "weight": 1, "fillColor": c, "fillOpacity": 0.72,
                },
                highlight_function=lambda _, c=color: {"fillColor": c, "fillOpacity": 0.95},
                tooltip=folium.Tooltip(
                    f"<b>MUKey {row['mukey']}</b> ({row['musym']})<br>"
                    f"{layer_key}: <b>{row['value_str']}</b>"
                ),
            ).add_to(m)

    folium.LayerControl().add_to(m)
    return m


# ── Depth profile chart ────────────────────────────────────────────────────

def _profile_chart(df_horizons, musym_map, selected_mukeys, variable_label, variable_col):
    n          = len(selected_mukeys)
    is_texture = variable_col == "texture"
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
        df_comp  = df_mu[df_mu["cokey"] == comp_dom].sort_values("hzdept_r")
        compname = df_comp["compname"].iloc[0]
        comppct  = df_comp["comppct_r"].iloc[0]
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
                    name=TEXTURE_NAMES[var_tex], marker_color=TEXTURE_COLORS[var_tex],
                    text=[f"{v:.0f}%" if v > 0 else "" for v in xs],
                    textposition="inside",
                    hovertemplate=f"<b>{TEXTURE_NAMES[var_tex]}</b><br>Val: %{{x:.1f}}%<br>Depth: %{{y}} cm<extra></extra>",
                    legendgroup=TEXTURE_NAMES[var_tex], showlegend=(col_idx == 1),
                    width=widths,
                ), row=1, col=col_idx)
        else:
            xs, ys = [], []
            for _, hz in df_comp.iterrows():
                val = hz[variable_col] if not pd.isna(hz[variable_col]) else None
                xs.extend([val, val]); ys.extend([hz["hzdept_r"], hz["hzdepb_r"]])
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines",
                fill="tozerox", fillcolor="rgba(41,128,185,0.15)",
                line=dict(color="#2980b9", width=2.5),
                name=compname, showlegend=(col_idx == 1),
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
        fig.update_layout(**{xax: dict(title="(%)" if is_texture else variable_label, gridcolor="#eee")})
    return fig


# ── Main render ────────────────────────────────────────────────────────────

def render(state: dict):
    st.header("🌱 Soil Information")

    # Support single or multiple AOIs
    field_geoms = state.get("field_geoms")
    if not field_geoms:
        geom_shp = state.get("field_geom_shp")
        if geom_shp is None:
            st.warning("⚠️ Please define your AOI in the **AOI** tab first.")
            return
        field_geoms = [("Field 1", geom_shp, state["gdf_field"])]

    if len(field_geoms) > 1:
        field_names   = [f[0] for f in field_geoms]
        selected_name = st.selectbox(
            "Analyse field:", field_names + ["— All fields combined —"],
            key="soil_field_selector",
        )
        if selected_name == "— All fields combined —":
            combined_geom = unary_union([f[1] for f in field_geoms])
            active_geom   = combined_geom
            active_gdf    = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[combined_geom])
            active_label  = "All fields"
        else:
            f = next(x for x in field_geoms if x[0] == selected_name)
            active_geom, active_gdf, active_label = f[1], f[2], f[0]
    else:
        active_geom, active_gdf, active_label = field_geoms[0][1], field_geoms[0][2], field_geoms[0][0]

    cache_key = str(active_geom.bounds)

    if state.get("soil_cache_key") != cache_key:
        with st.spinner("📡 Downloading soil polygons (USDA WFS)…"):
            try:
                gdf_clipped = fetch_wfs_soils(active_geom)
                state["gdf_clipped"]    = gdf_clipped
                state["soil_cache_key"] = cache_key
                for k in ("df_texture", "df_horizons", "df_wpavg"):
                    state.pop(k, None)
            except Exception as e:
                st.error(f"WFS Error: {e}")
                return

    gdf_clipped = state["gdf_clipped"]
    mukeys_str  = build_mukeys_str(gdf_clipped["mukey"])
    musym_map   = (
        gdf_clipped[["mukey", "musym"]].drop_duplicates()
        .set_index("mukey")["musym"].to_dict()
    )

    if "df_texture" not in state:
        with st.spinner("📡 Fetching texture data (SDA)…"):
            try:    state["df_texture"] = fetch_texture_data(mukeys_str)
            except: state["df_texture"] = pd.DataFrame()

    if "df_horizons" not in state:
        with st.spinner("📡 Fetching full horizon data (SDA)…"):
            try:
                df_hz = fetch_horizon_data(mukeys_str)
                df_hz["n_estimado_r"] = df_hz["om_r"] * N_FACTOR
                state["df_horizons"]  = df_hz
            except:
                state["df_horizons"] = pd.DataFrame()

    if "df_wpavg" not in state and not state["df_horizons"].empty:
        with st.spinner("⚖️ Computing weighted averages…"):
            state["df_wpavg"] = _calc_wpavg_all(state["df_horizons"])

    df_texture  = state["df_texture"]
    df_horizons = state["df_horizons"]
    df_wpavg    = state.get("df_wpavg")

    gdf_wpavg = None
    if df_wpavg is not None and not df_wpavg.empty:
        gdf_wpavg = gdf_clipped[["mukey"]].drop_duplicates().copy()
        gdf_wpavg["mukey"] = gdf_wpavg["mukey"].astype(str)
        gdf_wpavg = gdf_wpavg.merge(df_wpavg, on="mukey", how="left")

    st.success(
        f"✅ **{active_label}** — {len(gdf_clipped)} soil polygons "
        f"| {df_horizons['mukey'].nunique() if not df_horizons.empty else 0} MUKeys with horizon data"
    )

    sub_map, sub_report, sub_profiles = st.tabs([
        "🗺️ Choropleth Map",
        "📋 Agronomic Report",
        "📊 Depth Profiles",
    ])

    # ── Choropleth ─────────────────────────────────────────────────────────
    with sub_map:
        st.subheader("Soil Choropleth Map")
        col_ctrl, col_map = st.columns([1, 3])
        with col_ctrl:
            layer_key = st.selectbox(
                "🗂️ Layer / Variable", list(ALL_MAP_LAYERS.keys()), key="choropleth_layer",
            )
            layer_col = ALL_MAP_LAYERS[layer_key]
            if layer_col == "__texture__":
                st.markdown("**Texture palette**")
                present = (
                    df_texture.drop_duplicates("mukey")["texture"].unique().tolist()
                    if not df_texture.empty else list(TEXTURE_PALETTE.keys())
                )
                for tex in present:
                    c = TEXTURE_PALETTE.get(tex, "#aaa")
                    st.markdown(
                        f'<span style="background:{c};padding:2px 9px;border-radius:4px;'
                        f'color:white;font-size:11px;display:inline-block;margin:2px;">{tex}</span>',
                        unsafe_allow_html=True,
                    )
            elif layer_col == "__mukey__":
                st.markdown("**Each colour = one MUKey**")
            else:
                wpavg_col = f"{layer_col}_wpavg"
                if gdf_wpavg is not None and wpavg_col in gdf_wpavg.columns:
                    valid = gdf_wpavg[wpavg_col].dropna()
                    if not valid.empty:
                        st.metric("Min", f"{valid.min():.2f}")
                        st.metric("Max", f"{valid.max():.2f}")
                        st.metric("Mean", f"{valid.mean():.2f}")
                st.caption("Scale: 🟢 low → 🔴 high")

        with col_map:
            with st.spinner("Rendering map…"):
                m = _build_unified_map(layer_key, gdf_clipped, active_gdf, df_texture, gdf_wpavg)
            st_folium(m, width=820, height=520, returned_objects=[])

        st.markdown("#### ⬇️ Download")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("📥 Soil Polygons GeoJSON", gdf_to_geojson_bytes(gdf_clipped),
                               "soils.geojson", "application/json")
        with c2:
            st.download_button("📥 Shapefile (.zip)", gdf_to_shapefile_zip(gdf_clipped, "soils"),
                               "soils.zip", "application/zip")

    # ── Agronomic Report ───────────────────────────────────────────────────
    with sub_report:
        st.subheader("Agronomic Tabular Report")
        if df_horizons.empty:
            st.warning("No horizon data available. Check USDA SDA connection.")
        else:
            html_report = _build_html_report(df_horizons, gdf_clipped, df_wpavg)
            st.components.v1.html(html_report, height=700, scrolling=True)

            st.markdown("#### ⬇️ Download")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.download_button("📥 CSV (horizons)", df_to_csv_bytes(df_horizons),
                                   "horizons.csv", "text/csv")
            with c2:
                st.download_button("📥 Excel", df_to_excel_bytes(df_horizons, "Horizons"),
                                   "horizons.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with c3:
                if df_wpavg is not None and not df_wpavg.empty:
                    st.download_button("📥 CSV (weighted avg)", df_to_csv_bytes(df_wpavg),
                                       "wpavg.csv", "text/csv")
            st.download_button("📥 HTML Report",
                               data=html_report.encode("utf-8"),
                               file_name="agronomic_report.html", mime="text/html")

    # ── Depth Profiles ─────────────────────────────────────────────────────
    with sub_profiles:
        st.subheader("Depth Profile Charts")
        if df_horizons.empty:
            st.warning("No horizon data available.")
            return
        mukeys_disp = df_horizons["mukey"].unique().tolist()
        options     = [f"Unit {musym_map.get(str(mk), mk)} (mukey: {mk})" for mk in mukeys_disp]
        col_l, col_r = st.columns([1, 2])
        with col_l:
            var_options = ["Texture (Clay / Silt / Sand)"] + list(MAP_VARIABLES.keys())
            var_sel     = st.selectbox("Variable", var_options, key="profile_var")
            unit_sel    = st.multiselect("Map Units", options,
                                          default=options[:min(3, len(options))],
                                          key="profile_units")
            btn_gen = st.button("📊 Generate Profiles", key="btn_profiles")
        if btn_gen and unit_sel:
            selected_mukeys = [opt.split("mukey: ")[1].rstrip(")") for opt in unit_sel]
            variable_col    = "texture" if "Texture" in var_sel else MAP_VARIABLES.get(var_sel)
            with st.spinner("Generating profile chart…"):
                fig = _profile_chart(df_horizons, musym_map, selected_mukeys, var_sel, variable_col)
            with col_r:
                st.plotly_chart(fig, use_container_width=True)
            st.markdown("#### ⬇️ Download Chart")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥 Interactive HTML", fig_to_html_bytes(fig),
                                   "depth_profiles.html", "text/html")
            with c2:
                try:
                    img_bytes = fig.to_image(format="png", width=1200, height=600)
                    st.download_button("📥 PNG", img_bytes, "depth_profiles.png", "image/png")
                except Exception:
                    st.info("Install kaleido for PNG export.")
