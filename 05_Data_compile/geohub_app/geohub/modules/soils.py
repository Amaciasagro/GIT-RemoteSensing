"""Soils module (USA_Soils_Analisis): SSURGO via USDA-NRCS — interactive map with MUKEY, agronomic report per map unit, CASO/SoilWeb links and 3D model."""
import datetime as dt
import json
import math
import re
import urllib.parse

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from shapely.geometry import Point, mapping, shape
from streamlit_folium import st_folium

from ..config import tarjeta, TEXTURA_ES
from ..core import state, export, charts
from ..core.maps import mapa_base, agregar_aoi
from ..services import usda, gee

# Consistent color palette by USDA textural class
PALETA_TEXTURAS = {
    "Clay": "#8B0000",
    "Silty clay": "#B22222",
    "Sandy clay": "#CD5C5C",
    "Clay loam": "#D2691E",
    "Sandy clay loam": "#A0522D",
    "Silty clay loam": "#C68642",
    "Silt loam": "#DEB887",
    "Silt": "#F5DEB3",
    "Loam": "#8FBC8F",
    "Sandy loam": "#90be6d",
    "Loamy sand": "#F4A460",
    "Sand": "#e9c46a",
}

COLS_REPORTE_AGRO = [
    ("Hz", "hzname", "", 0),
    ("Depth (cm)", "__depth__", "", 0),
    ("Sand %", "sandtotal_r", "", 1),
    ("Silt %", "silttotal_r", "", 1),
    ("Clay %", "claytotal_r", "🏔️", 1),
    ("Texture", "__texture__", "", 0),
    ("Bulk dens. (g/cm³)", "dbthirdbar_r", "", 2),
    ("Ksat (mm/h)", "__ksat_mmh__", "💧", 1),
    ("H₂O 10kPa %", "wtenthbar_r", "", 1),
    ("H₂O 33kPa (FC) %", "wthirdbar_r", "", 1),
    ("H₂O 1500kPa (PWP) %", "wfifteenbar_r", "", 1),
    ("AWC (cm/cm)", "awc_r", "", 2),
    ("MO (%)", "om_r", "🌿", 2),
    ("pH (1:1)", "ph1to1h2o_r", "⚗️", 2),
    ("CE (dS/m)", "ec_r", "💧", 2),
    ("ECEC", "ecec_r", "", 1),
    ("ESP (%)", "esp_r", "🧂", 1),
    ("SAR", "sar_r", "🧂", 1),
    ("CEC", "cec7_r", "", 1),
    ("Est. N (%)", "n_estimado_r", "", 3),
]

LEYENDA_ALERTAS_HTML = (
    '<div style="font-family:sans-serif;font-size:11px;margin:8px 0 14px;padding:9px 14px;'
    'background:#111c2e;border:1px solid #1f3350;border-radius:8px;display:flex;flex-wrap:wrap;'
    'gap:8px;align-items:center;color:#dce6f2;">'
    '<b style="color:#e8f1fb;margin-right:4px;">🔔 Agronomic Traffic Light:</b>'
    '<span style="background:#ffe4e1;color:#8b0000;padding:2px 8px;border-radius:10px;font-weight:700;font-size:10px;">🔴 CRITICAL</span>'
    '<span style="background:#fff9e6;color:#b8860b;padding:2px 8px;border-radius:10px;font-weight:700;font-size:10px;">🟡 WARNING</span>'
    '<span style="background:#e6f9f0;color:#1b6e44;padding:2px 8px;border-radius:10px;font-weight:700;font-size:10px;">🟢 OPTIMAL</span>'
    '<span style="color:#8da6c2;font-size:10px;">'
    '&nbsp;EC ≥2 Warning / ≥4 Crit. · ESP ≥6 Warning / ≥15 Crit. · SAR ≥9 Warning / ≥13 Crit. · '
    'pH &lt;5.5 or &gt;8.5 Warning · Clay ≥40% Warning · OM &lt;1% Warning / &lt;0.5% Crit. · Bulk dens. ≥1.6 Warning / ≥1.75 Crit.'
    '</span></div>'
)


def _cards(items):
    for c, it in zip(st.columns(len(items)), items):
        c.markdown(tarjeta(*it), unsafe_allow_html=True)


def _estilo_alerta(col, val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "color:#6c849e;text-align:center;"
    CRIT = "background:#ffe4e1;color:#8b0000;font-weight:700;text-align:center;border-radius:3px;"
    WARN = "background:#fff9e6;color:#9c6d00;font-weight:700;text-align:center;border-radius:3px;"
    GOOD = "background:#e6f9f0;color:#1b6e44;font-weight:600;text-align:center;"
    NORM = "text-align:center;color:#dce6f2;"
    v = float(val)
    if col == "ec_r":
        return CRIT if v >= 4 else (WARN if v >= 2 else NORM)
    if col == "esp_r":
        return CRIT if v >= 15 else (WARN if v >= 6 else NORM)
    if col == "sar_r":
        return CRIT if v >= 13 else (WARN if v >= 9 else NORM)
    if col == "ph1to1h2o_r":
        if v <= 4.5 or v >= 9.0:
            return CRIT
        if v <= 5.5 or v >= 8.5:
            return WARN
    if col == "claytotal_r":
        return CRIT if v >= 50 else (WARN if v >= 40 else NORM)
    if col == "om_r":
        if v < 0.5:
            return CRIT
        if v < 1.0:
            return WARN
        if v >= 3.0:
            return GOOD
    if col in ("cec7_r", "ecec_r"):
        return CRIT if v < 6 else (WARN if v < 10 else NORM)
    if col in ("dbthirdbar_r", "dbovendry_r"):
        return CRIT if v >= 1.75 else (WARN if v >= 1.6 else NORM)
    return NORM


def _fmt_val(val, decs=1):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return '<span style="color:#5f7c9b;">—</span>'
    return f"{float(val):.{decs}f}"


def _construir_tabla_componente_html(df_comp, prof_cm=100):
    """Generates the horizons HTML table + weighted-average row (0–prof_cm) for one component."""
    ths = "".join(
        f'<th style="padding:6px 8px;background:#16243a;color:#9bb3cc;border:1px solid #233854;'
        f'white-space:nowrap;font-size:11px;font-weight:600;text-align:center;">{badge} {label}</th>'
        for label, _, badge, _ in COLS_REPORTE_AGRO
    )
    filas_html = []
    df_hz = df_comp.dropna(subset=["hzdept_r", "hzdepb_r"]).sort_values("hzdept_r").reset_index(drop=True)
    if df_hz.empty:
        return '<div style="padding:8px;color:#8da6c2;font-size:12px;">This component has no detailed horizons recorded in SSURGO.</div>'

    for i, (_, hz) in enumerate(df_hz.iterrows()):
        bg = "#0f1928" if i % 2 == 0 else "#132033"
        tex = usda.clase_textural(hz.get("sandtotal_r"), hz.get("silttotal_r"), hz.get("claytotal_r")) or "Loam"
        tex_es = TEXTURA_ES.get(tex, tex)
        col_tex = PALETA_TEXTURAS.get(tex, "#8da6c2")
        tds = []
        for _, col, _, decs in COLS_REPORTE_AGRO:
            if col == "__depth__":
                t0 = int(hz["hzdept_r"]) if pd.notna(hz.get("hzdept_r")) else 0
                t1 = int(hz["hzdepb_r"]) if pd.notna(hz.get("hzdepb_r")) else 0
                tds.append(f'<td style="text-align:center;border:1px solid #1f3350;padding:5px 7px;white-space:nowrap;color:#9bb3cc;font-size:11px;">{t0}–{t1}</td>')
            elif col == "__texture__":
                tds.append(
                    f'<td style="text-align:center;border:1px solid #1f3350;padding:5px 7px;">'
                    f'<span style="background:{col_tex}33;color:#e8f1fb;border:1px solid {col_tex};'
                    f'padding:2px 7px;border-radius:8px;font-size:10px;white-space:nowrap;">{tex_es}</span></td>'
                )
            elif col == "__ksat_mmh__":
                ks = float(hz["ksat_r"]) * 3.6 if pd.notna(hz.get("ksat_r")) else np.nan
                tds.append(f'<td style="padding:5px 7px;border:1px solid #1f3350;font-size:11px;text-align:center;color:#dce6f2;">{_fmt_val(ks, 1)}</td>')
            elif col == "hzname":
                tds.append(f'<td style="padding:5px 8px;border:1px solid #1f3350;font-weight:700;color:#e8f1fb;font-size:12px;">{hz.get("hzname", "—")}</td>')
            else:
                val = hz.get(col)
                st_al = _estilo_alerta(col, val)
                tds.append(f'<td style="padding:5px 7px;border:1px solid #1f3350;font-size:11px;{st_al}">{_fmt_val(val, decs)}</td>')
        filas_html.append(f'<tr style="background:{bg};">' + "".join(tds) + "</tr>")

    # Bottom row: Weighted average (0 - prof_cm)
    wp_sand = usda.promedio_ponderado_componente(df_hz, "sandtotal_r", prof_cm)
    wp_silt = usda.promedio_ponderado_componente(df_hz, "silttotal_r", prof_cm)
    wp_clay = usda.promedio_ponderado_componente(df_hz, "claytotal_r", prof_cm)
    tex_w = usda.clase_textural(wp_sand, wp_silt, wp_clay) or "Loam"
    tex_w_es = TEXTURA_ES.get(tex_w, tex_w)
    col_tw = PALETA_TEXTURAS.get(tex_w, "#8da6c2")
    tds_w = []
    for _, col, _, decs in COLS_REPORTE_AGRO:
        if col == "hzname":
            tds_w.append(f'<td style="padding:6px 8px;border:1px solid #2b476e;font-weight:700;color:#2fd4a7;font-size:11px;white-space:nowrap;">⚖️ Avg. (0–{prof_cm} cm)</td>')
        elif col == "__depth__":
            tds_w.append(f'<td style="text-align:center;border:1px solid #2b476e;padding:6px 7px;font-size:10px;color:#9bb3cc;font-style:italic;">0–{prof_cm} cm</td>')
        elif col == "__texture__":
            tds_w.append(
                f'<td style="text-align:center;border:1px solid #2b476e;padding:6px 7px;">'
                f'<span style="background:{col_tw}33;color:#e8f1fb;border:1px solid {col_tw};'
                f'padding:2px 7px;border-radius:8px;font-size:10px;white-space:nowrap;">{tex_w_es}</span></td>'
            )
        elif col == "__ksat_mmh__":
            ks_w = usda.promedio_ponderado_componente(df_hz, "ksat_r", prof_cm)
            ks_mmh = ks_w * 3.6 if pd.notna(ks_w) else np.nan
            tds_w.append(f'<td style="padding:6px 7px;border:1px solid #2b476e;font-size:11px;text-align:center;color:#dce6f2;font-weight:600;">{_fmt_val(ks_mmh, 1)}</td>')
        else:
            val_w = usda.promedio_ponderado_componente(df_hz, col, prof_cm)
            st_al = _estilo_alerta(col, val_w)
            tds_w.append(f'<td style="padding:6px 7px;border:1px solid #2b476e;font-size:11px;{st_al}">{_fmt_val(val_w, decs)}</td>')
    filas_html.append('<tr style="background:#172a45;border-top:2px solid #2fd4a7;">' + "".join(tds_w) + "</tr>")

    return (
        '<div style="overflow-x:auto;border-radius:8px;border:1px solid #1f3350;">'
        f'<table style="width:100%;border-collapse:collapse;font-size:12px;">'
        f'<thead><tr>{ths}</tr></thead><tbody>{"".join(filas_html)}</tbody></table></div>'
    )


def _preparar_df_csv_uc(hors, tabla, mukeys_filtro=None):
    """Prepares a clean, complete DataFrame with the series, horizons and agronomic properties for CSV download."""
    df_h = hors.copy()
    df_h["mukey"] = df_h["mukey"].astype(str)
    if mukeys_filtro:
        set_mk = {str(m) for m in mukeys_filtro}
        df_h = df_h[df_h["mukey"].isin(set_mk)].copy()
    if "pct_aoi" in tabla.columns:
        mapa_pct = tabla.set_index(tabla["mukey"].astype(str))["pct_aoi"].to_dict()
        mapa_area = tabla.set_index(tabla["mukey"].astype(str))["area_ha"].to_dict()
        df_h["pct_aoi"] = df_h["mukey"].map(mapa_pct).round(2)
        df_h["area_uc_ha"] = df_h["mukey"].map(mapa_area).round(2)
    if "ksat_r" in df_h.columns:
        df_h["ksat_mmh"] = (pd.to_numeric(df_h["ksat_r"], errors="coerce") * 3.6).round(2)
    df_h["textura_hz"] = [
        TEXTURA_ES.get(usda.clase_textural(s, si, c), usda.clase_textural(s, si, c) or "")
        for s, si, c in zip(df_h.get("sandtotal_r", []), df_h.get("silttotal_r", []), df_h.get("claytotal_r", []))
    ]
    cols_orden = [
        c for c in (
            "mukey", "musym", "muname", "pct_aoi", "area_uc_ha",
            "compname", "comppct_r", "majcompflag", "hydgrp", "drainagecl", "slope_r", "taxclname",
            "hzname", "hzdept_r", "hzdepb_r", "textura_hz",
            "sandtotal_r", "silttotal_r", "claytotal_r",
            "dbthirdbar_r", "ksat_mmh", "wtenthbar_r", "wthirdbar_r", "wfifteenbar_r", "awc_r",
            "om_r", "n_estimado_r", "ph1to1h2o_r", "ec_r", "ecec_r", "esp_r", "sar_r", "cec7_r",
        ) if c in df_h.columns
    ]
    return df_h[cols_orden].sort_values(["mukey", "comppct_r", "hzdept_r"], ascending=[True, False, True]).round(3)


def _render_panel_detalle_mukey(mk_sel, tabla, hors, gdf, aoi, prof_cm):
    """
    Shows the detailed panel of a Map Unit (MUKEY) selected or clicked on the map:
      - List and summary table of all series/components of the MUKEY sorted from highest to lowest % share.
      - Full agronomic report (horizons, physical/chemical properties, alerts and SoilWeb SDE link) per component.
      - CSV download of the chosen map unit or of all map units in the AOI.
    """
    fila_mu = tabla[tabla["mukey"] == str(mk_sel)]
    muname = fila_mu["muname"].iloc[0] if not fila_mu.empty else f"MUKEY {mk_sel}"
    musym = fila_mu["musym"].iloc[0] if (not fila_mu.empty and "musym" in fila_mu.columns) else str(mk_sel)
    pct_aoi = float(fila_mu["pct_aoi"].iloc[0]) if (not fila_mu.empty and pd.notna(fila_mu["pct_aoi"].iloc[0])) else np.nan
    area_ha = float(fila_mu["area_ha"].iloc[0]) if (not fila_mu.empty and pd.notna(fila_mu["area_ha"].iloc[0])) else np.nan

    hm = hors[hors["mukey"].astype(str) == str(mk_sel)].copy()
    if hm.empty:
        st.warning(f"No components found for MUKEY {mk_sel}.")
        return

    # Group components and sort strictly from highest to lowest % share (comppct_r DESC)
    resumen_comps = []
    orden_cokeys = []
    for cok, df_c in hm.groupby("cokey", sort=False):
        pct_c = float(df_c["comppct_r"].iloc[0]) if pd.notna(df_c["comppct_r"].iloc[0]) else 0.0
        nom_c = str(df_c["compname"].iloc[0]) if pd.notna(df_c["compname"].iloc[0]) else "Component"
        maj_c = "Yes (Major)" if str(df_c.get("majcompflag", pd.Series(["Yes"])).iloc[0]).lower().startswith("y") else "No (Minor)"
        hsg_c = str(df_c["hydgrp"].iloc[0]) if ("hydgrp" in df_c.columns and pd.notna(df_c["hydgrp"].iloc[0])) else "—"
        drn_c = str(df_c["drainagecl"].iloc[0]) if ("drainagecl" in df_c.columns and pd.notna(df_c["drainagecl"].iloc[0])) else "—"
        slp_c = f"{float(df_c['slope_r'].iloc[0]):.1f}%" if ("slope_r" in df_c.columns and pd.notna(df_c["slope_r"].iloc[0])) else "—"
        tax_c = str(df_c["taxclname"].iloc[0]) if ("taxclname" in df_c.columns and pd.notna(df_c["taxclname"].iloc[0])) else "—"
        n_hz = int(df_c["hzdept_r"].notna().sum())
        agg_c = usda._agregar_horizontes(df_c, prof_cm)
        tex_c = TEXTURA_ES.get(agg_c["textura"], agg_c["textura"]) if agg_c else "—"
        awc_c = round(agg_c["awc_mm"], 1) if agg_c else np.nan
        ksat_c = round(agg_c["ksat_mmh"], 1) if agg_c else np.nan
        resumen_comps.append({
            "cokey": cok,
            "Series / Component": nom_c,
            "% Share (map unit)": pct_c,
            "Type": maj_c,
            "Texture (0–depth)": tex_c,
            "Hydrologic Group": hsg_c,
            "Drainage Class": drn_c,
            "Rep. slope": slp_c,
            "AWC (mm)": awc_c,
            "Ksat (mm/h)": ksat_c,
            "Horizons": n_hz,
            "USDA Taxonomy": tax_c,
        })
    df_comps = pd.DataFrame(resumen_comps).sort_values("% Share (map unit)", ascending=False).reset_index(drop=True)
    orden_cokeys = df_comps["cokey"].tolist()

    sub_area = f"{area_ha:.2f} ha ({pct_aoi:.1f}% of AOI)" if pd.notna(area_ha) and pd.notna(pct_aoi) else "In AOI"
    st.markdown(
        f"#### 📌 Map Unit Detail · **MUKEY `{mk_sel}`** (Symbol `{musym}`) — *{muname}*\n"
        f"<span style='color:#8da6c2;font-size:13px;'>Area in the field: <b>{sub_area}</b> · "
        f"Series/components recorded in this MUKEY: <b>{len(df_comps)}</b> (sorted from highest to lowest % share)</span>",
        unsafe_allow_html=True,
    )

    st.markdown("**1️⃣ Soil Series / Components in this MUKEY (sorted from highest to lowest % share):**")
    st.dataframe(
        df_comps.drop(columns=["cokey"]),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("**2️⃣ Agronomic Report per Series / Component (Horizons, physical/edaphic properties and alert traffic light):**")
    st.markdown(LEYENDA_ALERTAS_HTML, unsafe_allow_html=True)

    for idx_c, cok in enumerate(orden_cokeys):
        info_c = df_comps[df_comps["cokey"] == cok].iloc[0]
        nom_c = info_c["Series / Component"]
        pct_c = info_c["% Share (map unit)"]
        url_sde = f"https://casoilresource.lawr.ucdavis.edu/sde/?series={urllib.parse.quote(nom_c.lower())}#osd"
        etiqueta_exp = (
            f"{'⭐ ' if idx_c == 0 else '🔹 '}Series: {nom_c} — {pct_c:.0f}% of the map unit "
            f"({info_c['Type']} · Texture: {info_c['Texture (0–depth)']} · Drainage: {info_c['Drainage Class']} · "
            f"HSG: {info_c['Hydrologic Group']})"
        )
        with st.expander(etiqueta_exp, expanded=(idx_c == 0)):
            st.markdown(
                f"🔗 **Official series sheet at UC Davis (CASO):** "
                f"[Open taxonomic and morphological description of **{nom_c}** in SoilWeb SDE]({url_sde}) · "
                f"**Taxonomy:** *{info_c['USDA Taxonomy']}* · **Rep. slope:** {info_c['Rep. slope']}",
            )
            df_c_hz = hm[hm["cokey"] == cok].copy()
            st.markdown(_construir_tabla_componente_html(df_c_hz, prof_cm=prof_cm), unsafe_allow_html=True)

    # ── CSV download of the chosen map unit or of all map units in the AOI ──
    st.markdown("##### 📥 Export agronomic data of Map Units (CSV)")
    cd1, cd2, cd3 = st.columns([1.8, 1.4, 1.4])
    todos_mks = [str(m) for m in tabla["mukey"].tolist()]
    mks_elegidos = cd1.multiselect(
        "Map Units (MUKEY) to include in the custom download",
        todos_mks,
        default=[str(mk_sel)],
        format_func=lambda k: f"MUKEY {k} ({tabla.loc[tabla['mukey'].astype(str) == k, 'muname'].iloc[0][:32]})",
        key=f"sel_csv_mks_{mk_sel}",
    )
    df_csv_sel = _preparar_df_csv_uc(hors, tabla, mukeys_filtro=mks_elegidos or [str(mk_sel)])
    df_csv_all = _preparar_df_csv_uc(hors, tabla, mukeys_filtro=None)
    with cd2:
        export.boton_csv(df_csv_sel, f"suelos_uc_seleccionadas_{mk_sel}", f"dl_csv_uc_sel_{mk_sel}")
    with cd3:
        export.boton_csv(df_csv_all, "suelos_todas_uc_aoi", f"dl_csv_uc_all_{mk_sel}")
    export.registrar("suelos_reporte_agronomico_aoi", df_csv_all)


# ── Helpers for 3D Modeling in Soils ───────────────────────────────────────
def _aspecto_escena_3d(elevation, x_coords, y_coords, exag):
    lat_mean = float(np.mean(y_coords))
    lon_span_m = max(abs(float(x_coords[-1] - x_coords[0])) * 111320.0 * np.cos(np.radians(lat_mean)), 1.0)
    lat_span_m = max(abs(float(y_coords[-1] - y_coords[0])) * 111320.0, 1.0)
    max_xy_m = max(lon_span_m, lat_span_m)
    dz_m = max(float(np.nanmax(elevation) - np.nanmin(elevation)), 0.5)
    ax_x = float(lon_span_m / max_xy_m)
    ax_y = float(lat_span_m / max_xy_m)
    ratio_base = max(dz_m / max_xy_m, 0.08)
    ax_z = float(np.clip(ratio_base * float(exag), 0.12, 1.25))
    return dict(x=ax_x, y=ax_y, z=ax_z)


def _traza_perimetro_3d(geom_shp, elevation, x_coords, y_coords):
    H, W = elevation.shape
    lat_min, lat_max = float(y_coords[0]), float(y_coords[-1])
    z_span = max(float(np.nanmax(elevation) - np.nanmin(elevation)), 1.0)
    offset_m = max(z_span * 0.018, 0.25)

    def _elev_pt(lon, lat):
        xi = int(np.clip(np.interp(lon, x_coords, np.arange(W)), 0, W - 1))
        yi = int(np.clip((1.0 - (lat - lat_min) / (lat_max - lat_min + 1e-9)) * (H - 1), 0, H - 1))
        r0, r1 = max(0, yi - 1), min(H, yi + 2)
        c0, c1 = max(0, xi - 1), min(W, xi + 2)
        return float(np.nanmax(elevation[r0:r1, c0:c1])) + offset_m

    gj = mapping(geom_shp)
    rings = [gj["coordinates"][0]] if gj["type"] == "Polygon" else (
        [p[0] for p in gj["coordinates"]] if gj["type"] == "MultiPolygon" else []
    )
    if not rings:
        return None
    step_deg = max(min(abs(float(x_coords[-1] - x_coords[0])) / 80.0, abs(float(y_coords[-1] - y_coords[0])) / 80.0), 1e-6)
    xs, ys, zs = [], [], []
    for ring in rings:
        for i in range(len(ring) - 1):
            lon0, lat0 = ring[i][0], ring[i][1]
            lon1, lat1 = ring[i + 1][0], ring[i + 1][1]
            n_pts = max(2, int(np.ceil(np.hypot(lon1 - lon0, lat1 - lat0) / step_deg)))
            for tv in np.linspace(0.0, 1.0, n_pts, endpoint=False):
                ln = lon0 + tv * (lon1 - lon0)
                lt = lat0 + tv * (lat1 - lat0)
                xs.append(ln); ys.append(lt); zs.append(_elev_pt(ln, lt))
        if ring:
            xs.append(ring[-1][0]); ys.append(ring[-1][1]); zs.append(_elev_pt(ring[-1][0], ring[-1][1]))
        xs.append(None); ys.append(None); zs.append(None)
    return go.Scatter3d(
        x=xs, y=ys, z=zs, mode="lines",
        line=dict(color="#2fd4a7", width=6),
        name="AOI boundary", hoverinfo="skip",
    )


def _rgb_a_paleta_ordenada(rgb_arr):
    """Quantizes an RGB texture to 256 colors ordered by luminance for Plotly Surface."""
    from PIL import Image

    im_pil = Image.fromarray(rgb_arr.astype(np.uint8), mode="RGB")
    im_q = im_pil.quantize(colors=256, method=Image.MEDIANCUT)
    pal_raw = im_q.getpalette()[:256 * 3]
    n_col = max(len(pal_raw) // 3, 1)
    cols = np.array(pal_raw[:n_col * 3], dtype=int).reshape(n_col, 3)
    lum = 0.299 * cols[:, 0] + 0.587 * cols[:, 1] + 0.114 * cols[:, 2]
    orden = np.argsort(lum)
    inv_orden = np.zeros(n_col, dtype=int)
    inv_orden[orden] = np.arange(n_col)
    idx_raw = np.clip(np.array(im_q, dtype=int), 0, n_col - 1)
    idx_arr = inv_orden[idx_raw].astype(float)
    cols_ord = cols[orden]
    escala_rgb = [[i / max(n_col - 1, 1), f"rgb({int(cols_ord[i,0])},{int(cols_ord[i,1])},{int(cols_ord[i,2])})"] for i in range(n_col)]
    return idx_arr, escala_rgb, float(max(n_col - 1, 1))


def _construir_figura_3d_suelos(elevation, x_coords, y_coords, exag, geom_shp=None, rgb_texture=None, titulo_tex="No texture (Topographic relief)"):
    from PIL import Image

    H, W = elevation.shape
    surf_kwargs = dict(
        z=elevation,
        x=x_coords,
        y=y_coords[::-1],
        lighting=dict(ambient=0.72 if rgb_texture is not None else 0.58, diffuse=0.86, specular=0.15),
        hovertemplate="Lon: %{x:.4f}°<br>Lat: %{y:.4f}°<br>Elevation: <b>%{z:.1f} m a.s.l.</b><extra></extra>",
    )
    if rgb_texture is not None and rgb_texture.ndim == 3:
        if rgb_texture.shape[0] != H or rgb_texture.shape[1] != W:
            rgb_texture = np.array(Image.fromarray(rgb_texture.astype(np.uint8)).resize((W, H), Image.BICUBIC))
        idx_c, esc_rgb, cmax_rgb = _rgb_a_paleta_ordenada(rgb_texture)
        surf_kwargs.update(surfacecolor=idx_c, colorscale=esc_rgb, cmin=0.0, cmax=cmax_rgb, showscale=False)
    else:
        surf_kwargs.update(colorscale="earth", colorbar=dict(title="Elevation (m)", thickness=18, len=0.65))

    traces = [go.Surface(**surf_kwargs)]
    if geom_shp is not None:
        tr_p = _traza_perimetro_3d(geom_shp, elevation, x_coords, y_coords)
        if tr_p is not None:
            traces.append(tr_p)

    aspect = _aspecto_escena_3d(elevation, x_coords, y_coords, exag)
    fig = go.Figure(data=traces)
    fig.update_layout(
        title=dict(text=f"🧊 3D Terrain Model · {titulo_tex} (Exaggeration ×{exag:g})", font=dict(size=13, color="#e8f1fb"), x=0.01),
        scene=dict(
            xaxis_title="Longitude (°)",
            yaxis_title="Latitude (°)",
            zaxis_title="Elevation (m a.s.l.)",
            aspectmode="manual",
            aspectratio=aspect,
            camera=dict(eye=dict(x=1.40, y=1.40, z=0.90)),
            xaxis=dict(backgroundcolor="rgba(0,0,0,0)"),
            yaxis=dict(backgroundcolor="rgba(0,0,0,0)"),
            zaxis=dict(backgroundcolor="rgba(0,0,0,0)"),
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        height=620,
    )
    return fig


def _render_subtab_3d_suelos(ctx, geom_shp):
    aoi = ctx["aoi"]
    rango = ctx.get("rango")
    gee_ok = ctx.get("gee_ok", False)
    hoy = dt.date.today()
    f_ini_def = rango[0] if rango else (hoy - dt.timedelta(days=365)).strftime("%Y-%m-%d")
    f_fin_def = rango[1] if rango else hoy.strftime("%Y-%m-%d")

    st.markdown("#### 🧊 3D Topographic Modeling (with and without satellite texture and cloudiness filter)")
    st.caption(
        "Generate the 3D elevation model of the field with pure relief or draped with **Sentinel-2** imagery "
        "(choosing among the available dates that meet your maximum `% cloudiness` threshold), "
        "**Google Satellite** or **Esri World Imagery**."
    )

    c_m1, c_m2, c_m3, c_m4 = st.columns([1.8, 1.2, 1.0, 1.0])
    modo_tex = c_m1.selectbox(
        "Display mode / 3D Texture",
        [
            "🛰️ With Sentinel-2 texture by available date (filtered by % clouds)",
            "🌐 With reference texture: Google Satellite",
            "🌎 With reference texture: Esri World Imagery",
            "🗻 No satellite texture (Topographic surface / Pure relief)",
        ],
        key="suelo_3d_modo_tex",
    )
    base_ref_2d = c_m2.selectbox(
        "Reference base map",
        ["Google Satellite", "Esri World Imagery", "Google Hybrid"],
        key="suelo_3d_base_ref",
        help="Reference base map and high-resolution fallback for the terrain.",
    )
    exag_3d = c_m3.slider("Vertical exaggeration", 1.0, 20.0, 3.0, 0.5, key="suelo_3d_exag")
    zoom_3d = c_m4.slider("DEM detail (Zoom)", 12, 16, 14, 1, key="suelo_3d_zoom",
                          help="Zoom 14 (~9 m/px) offers the best balance between speed and micro-topographic detail.")

    fecha_s2_elegida = None
    nubes_max_3d = 25
    if modo_tex.startswith("🛰️"):
        if not gee_ok:
            st.warning("⚠️ Google Earth Engine is not connected; the texture of the selected base map will be used.")
        else:
            cs1, cs2, cs3 = st.columns([1.2, 1.3, 2.0])
            nubes_max_3d = cs1.slider(
                "Max. cloudiness threshold (%)",
                min_value=0, max_value=80, value=25, step=5,
                key="suelo_3d_max_nubes",
                help="Filters the available Sentinel-2 scenes whose cloud percentage is less than or equal to this value.",
            )
            ventana_s2 = cs2.selectbox(
                "Date search period",
                ["Active time window", "Last year (365 days)", "Last 2 years"],
                key="suelo_3d_ventana_s2",
            )
            if ventana_s2 == "Last year (365 days)":
                b_ini, b_fin = (hoy - dt.timedelta(days=365)).strftime("%Y-%m-%d"), hoy.strftime("%Y-%m-%d")
            elif ventana_s2 == "Last 2 years":
                b_ini, b_fin = (hoy - dt.timedelta(days=730)).strftime("%Y-%m-%d"), hoy.strftime("%Y-%m-%d")
            else:
                b_ini, b_fin = f_ini_def, f_fin_def

            try:
                fechas_disp = gee.listar_fechas_satelitales(json.dumps(aoi["geom"]), b_ini, b_fin, max_nubes=nubes_max_3d, sensor="S2")
            except Exception as e_f:  # noqa: BLE001
                fechas_disp = []
                st.warning(f"Could not list Sentinel-2 dates ({e_f}).")

            if fechas_disp:
                sel_f_obj = cs3.selectbox(
                    f"Date with available Sentinel-2 image (≤ {nubes_max_3d}% clouds · {len(fechas_disp)} scenes)",
                    fechas_disp,
                    format_func=lambda x: f"📅 {x['etiqueta']}",
                    key="suelo_3d_fecha_s2_sel",
                )
                fecha_s2_elegida = sel_f_obj["fecha"]
            else:
                cs3.info(f"No Sentinel-2 scenes with ≤ {nubes_max_3d}% clouds in that range. Increase the cloudiness % or change the period.")

    smooth_3d = st.slider("DEM micro-noise smoothing (passes)", 0, 8, 2, 1, key="suelo_3d_smooth")

    dem_cache_key = f"{aoi['id']}_{zoom_3d}"
    if st.session_state.get("suelo_3d_dem_key") != dem_cache_key:
        with st.spinner("Downloading digital elevation model (DEM)…"):
            try:
                elev, xc, yc, tinfo = usda.descargar_dem_3d(geom_shp, zoom=zoom_3d, smooth_passes=0)
                st.session_state["suelo_3d_data"] = dict(raw_elev=tinfo["raw_elevation"], xc=xc, yc=yc, tinfo=tinfo)
                st.session_state["suelo_3d_dem_key"] = dem_cache_key
            except Exception as e_dem:  # noqa: BLE001
                st.error(f"Could not download the DEM for the 3D model: {e_dem}")
                return

    datos_3d = st.session_state.get("suelo_3d_data")
    if not datos_3d:
        return

    elev = usda.suavizar_dem(datos_3d["raw_elev"], pasadas=smooth_3d)
    xc, yc, tinfo = datos_3d["xc"], datos_3d["yc"], datos_3d["tinfo"]

    z_min, z_max = float(np.nanmin(elev)), float(np.nanmax(elev))
    _cards([
        ("Min. elevation", f"{z_min:,.1f}", "m s.n.m.", "DEM around AOI", ""),
        ("Max. elevation", f"{z_max:,.1f}", "m s.n.m.", "DEM around AOI", ""),
        ("Relief (ΔZ)", f"{z_max - z_min:,.1f}", "m", f"Mesh {elev.shape[1]}×{elev.shape[0]} px (Zoom {tinfo['zoom']})", "suelo"),
        ("Z exaggeration", f"×{exag_3d:g}", "", base_ref_2d if not fecha_s2_elegida else f"Sentinel-2 ({fecha_s2_elegida})", "agua"),
    ])

    rgb_tex = None
    titulo_tex = "No texture (Topographic relief)"
    if modo_tex.startswith("🗻"):
        rgb_tex = None
        titulo_tex = "No texture (Hypsometric-topographic relief)"
    elif modo_tex.startswith("🛰️") and fecha_s2_elegida and gee_ok:
        with st.spinner(f"Downloading Sentinel-2 texture of {fecha_s2_elegida} (≤ {nubes_max_3d}% clouds)…"):
            try:
                rgb_tex = gee.descargar_textura_s2_fecha_3d(
                    tinfo["bbox_crop"], fecha_s2_elegida, max_nubes=nubes_max_3d, shape_hw=elev.shape
                )
                titulo_tex = f"Sentinel-2 texture ({fecha_s2_elegida} · ≤ {nubes_max_3d}% clouds)"
            except Exception as e_t:  # noqa: BLE001
                st.warning(f"Could not load the Sentinel-2 texture ({e_t}); using {base_ref_2d}.")
                rgb_tex = usda.descargar_textura_xyz_3d(tinfo, proveedor=base_ref_2d)
                titulo_tex = f"Texture {base_ref_2d}"
    elif modo_tex.startswith("🌐"):
        with st.spinner("Downloading high-resolution Google Satellite texture…"):
            rgb_tex = usda.descargar_textura_xyz_3d(tinfo, proveedor="Google Satellite")
            titulo_tex = "Google Satellite texture"
    else:
        prov_uso = base_ref_2d if modo_tex.startswith("🛰️") else "Esri World Imagery"
        with st.spinner(f"Downloading satellite texture ({prov_uso})…"):
            rgb_tex = usda.descargar_textura_xyz_3d(tinfo, proveedor=prov_uso)
            titulo_tex = f"Texture {prov_uso}"

    fig_3d = _construir_figura_3d_suelos(elev, xc, yc, exag_3d, geom_shp=geom_shp, rgb_texture=rgb_tex, titulo_tex=titulo_tex)
    st.plotly_chart(fig_3d, use_container_width=True, key="plt_suelos_3d_main")
    html_3d = fig_3d.to_html(include_plotlyjs="cdn", full_html=True).encode("utf-8")
    st.download_button(
        "⬇️ Download Interactive 3D Model (.html)",
        data=html_3d,
        file_name=f"modelo_3d_suelos_{fecha_s2_elegida or 'terreno'}.html",
        mime="text/html",
        key="dl_suelos_3d_html",
    )


def render(ctx):
    st.subheader("🧱 Soils · USDA-NRCS SSURGO & 3D Modeling")
    aoi = ctx["aoi"]
    if aoi is None:
        st.info("Define an AOI in the sidebar.")
        return
    if not aoi["en_eeuu"]:
        st.warning("The AOI is outside the U.S.: SSURGO/USDA-NRCS only covers that territory.")
        return

    geom_shp = shape(aoi["geom"])
    c1, c2 = st.columns([2.4, 1.4])
    prof = c1.slider("Depth to integrate (cm)", 30, 200, 100, 10, key="suelo_prof")
    base_mapa_suelo = c2.selectbox(
        "Satellite base map",
        ["Google Satellite", "Esri World Imagery", "Google Hybrid", "Dark"],
        index=0,
        key="suelo_base_mapa_sel",
    )
    firma = state.firma(aoi["id"], prof)
    d, vigente = state.obtener("suelos", firma)
    if d is None or not vigente:
        with st.spinner("Automatically querying USDA SSURGO polygons, series and horizons…"):
            try:
                gdf, tabla, hors, avisos = usda.consultar_suelos(geom_shp, aoi["bounds"], prof)
                tabla, prom = usda.ponderar_por_area(gdf, tabla, geom_shp)
                state.guardar("suelos", dict(gdf=gdf, tabla=tabla, hors=hors, prom=prom, avisos=avisos), firma)
                d, vigente = state.obtener("suelos", firma)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not obtain soil information: {e}. It may be a temporary service failure "
                         "from USDA or an AOI without soil mapping (water, urban, unsurveyed area).")
                return
    for a in d["avisos"]:
        st.warning(a)

    t, p, hors = d["tabla"], d["prom"], d["hors"]
    ponderado = t["pct_aoi"].notna().any()
    _cards([
        ("Dominant texture", TEXTURA_ES.get(p["textura_dom"], p["textura_dom"]), "", f"HSG {p['hsg_dom']}", "suelo"),
        ("Field cap.", f"{p['fc_mm']:.0f}", "mm", f"0–{p['depth_cm']:.0f} cm", "suelo"),
        ("Wilting point", f"{p['wp_mm']:.0f}", "mm", "PMP", "suelo"),
        ("Available water", f"{p['awc_mm']:.0f}", "mm", "FC − PWP", "agua"),
        ("Ksat", f"{p['ksat_mmh']:.1f}", "mm/h", "harmonic mean per profile", "agua"),
    ])

    url_gmap_aoi = f"https://casoilresource.lawr.ucdavis.edu/gmap/?loc={aoi['lat']:.5f},{aoi['lon']:.5f},z15"
    st.caption(
        ("Area-weighted averages within the AOI. " if ponderado else "No polygons: units are averaged without area weighting. ")
        + f"🔗 **[Explore field in California Soil Resource Lab (SoilWeb GMap)]({url_gmap_aoi})**"
    )

    tab_mapa, tab_tabla, tab_perfil, tab_3d = st.tabs([
        "🗺️ Texture Map and Detail by Map Unit",
        "📋 Map Units",
        "📉 Profiles and Textural Triangle",
        "🧊 3D Terrain Model",
    ])

    with tab_mapa:
        mukeys_lista = [str(m) for m in t["mukey"].tolist()]
        if "suelo_uc_activa" not in st.session_state or st.session_state["suelo_uc_activa"] not in mukeys_lista:
            st.session_state["suelo_uc_activa"] = mukeys_lista[0]

        if d["gdf"] is None:
            st.info("The polygon service was not available; select a Map Unit below to inspect its components.")
        else:
            idx = t.set_index("mukey")
            g = d["gdf"].copy()
            g["mukey"] = g["mukey"].astype(str)
            for col in ("musym", "muname", "compname", "textura", "awc_mm", "ksat_mmh", "pct_aoi"):
                if col in idx.columns:
                    g[col] = g["mukey"].map(idx[col])
            if "musym" not in g.columns:
                g["musym"] = g["mukey"]
            g["textura_es"] = g["textura"].map(lambda x: TEXTURA_ES.get(x, str(x)))
            g["awc_mm"] = pd.to_numeric(g["awc_mm"], errors="coerce").round(1)
            g["ksat_mmh"] = pd.to_numeric(g["ksat_mmh"], errors="coerce").round(1)
            g["pct_aoi"] = pd.to_numeric(g["pct_aoi"], errors="coerce").round(1)

            paleta_fallback = ["#e9c46a", "#f4a261", "#e76f51", "#8ab17d", "#2a9d8f", "#264653", "#b5838d", "#6d6875",
                               "#90be6d", "#43aa8b", "#577590", "#f9c74f"]
            col_map = {
                k: PALETA_TEXTURAS.get(k, paleta_fallback[i % len(paleta_fallback)])
                for i, k in enumerate(sorted(g["textura"].dropna().unique()))
            }

            m = mapa_base([aoi["lat"], aoi["lon"]], 15, base_preferida=base_mapa_suelo)
            cols_gj = [c for c in ("mukey", "musym", "muname", "compname", "textura", "textura_es", "pct_aoi", "awc_mm", "ksat_mmh", "geometry") if c in g.columns]
            # IMPORTANT: The style_function must NOT depend on `suelo_uc_activa` so that st_folium
            # keeps exactly the same map instance and does NOT reload the iframe on the first click.
            folium.GeoJson(
                g[cols_gj].to_json(),
                name="Map Units (SSURGO)",
                style_function=lambda f: {
                    "fillColor": col_map.get(f["properties"].get("textura"), "#888888"),
                    "color": "#0b1320",
                    "weight": 1.5,
                    "fillOpacity": 0.58,
                },
                highlight_function=lambda _: {
                    "weight": 3.5,
                    "color": "#00ff9d",
                    "fillOpacity": 0.82,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["mukey", "musym", "muname", "compname", "textura_es", "pct_aoi", "awc_mm", "ksat_mmh"],
                    aliases=[
                        "🔑 MUKEY:",
                        "🏷️ Symbol (MUSYM):",
                        "📍 Map Unit:",
                        "🌱 Dominant series:",
                        "🎨 Textural Class:",
                        "📐 AOI Share (%):",
                        "💧 Avail. water AWC (mm):",
                        "⏬ Harmonic Ksat (mm/h):",
                    ],
                    sticky=True,
                ),
            ).add_to(m)
            # Draw the AOI boundary ABOVE the soil polygons as a non-interactive perimeter line
            # so it stands out clearly without blocking hover or click on the map units
            agregar_aoi(m, aoi["geom"])
            folium.LayerControl(collapsed=True).add_to(m)

            st.caption("💡 **Move the cursor** over any polygon inside or outside the AOI to see its **`MUKEY`** and texture, or **click a Map Unit** to automatically update its information below.")
            sal_mapa = st_folium(
                m,
                height=460,
                use_container_width=True,
                returned_objects=["last_active_drawing", "last_object_clicked", "last_object_clicked_tooltip"],
                key="mapa_suelos_interactivo",
            )

            # Detect a click on a map polygon (by active GeoJSON feature, by lat/lng coordinates or by tooltip)
            mk_clic = None
            firma_clic = None
            if sal_mapa:
                lad = sal_mapa.get("last_active_drawing")
                if isinstance(lad, dict):
                    prop_mk = str(lad.get("properties", {}).get("mukey", "")).strip()
                    if prop_mk in mukeys_lista:
                        mk_clic = prop_mk
                loc_pt = sal_mapa.get("last_object_clicked")
                if isinstance(loc_pt, dict) and loc_pt.get("lat") is not None and loc_pt.get("lng") is not None:
                    pt_shp = Point(float(loc_pt["lng"]), float(loc_pt["lat"]))
                    hits = g[g.geometry.contains(pt_shp)]
                    if hits.empty:
                        hits = g[g.geometry.intersects(pt_shp.buffer(1e-4))]
                    if not hits.empty:
                        cand = str(hits["mukey"].iloc[0]).strip()
                        if cand in mukeys_lista:
                            mk_clic = cand
                    firma_clic = f"{loc_pt['lat']:.6f}_{loc_pt['lng']:.6f}_{mk_clic}"
                tt_txt = sal_mapa.get("last_object_clicked_tooltip")
                if mk_clic is None and isinstance(tt_txt, str) and tt_txt.strip():
                    m_re = re.search(r"MUKEY:\s*([A-Za-z0-9_]+)", tt_txt)
                    if m_re and m_re.group(1) in mukeys_lista:
                        mk_clic = m_re.group(1)
                if firma_clic is None and mk_clic is not None:
                    firma_clic = f"feat_{mk_clic}_{tt_txt}"

            # If there was a new click on the map, directly update the dropdown and the active map unit without reloading the map
            if mk_clic and firma_clic and firma_clic != st.session_state.get("_ult_firma_clic_suelo"):
                st.session_state["_ult_firma_clic_suelo"] = firma_clic
                st.session_state["suelo_uc_activa"] = mk_clic
                st.session_state["sel_mukey_detalle_mapa"] = mk_clic

            st.caption(
                "Colors by textural class: "
                + " · ".join(f"<span style='color:{c}'>■</span> {TEXTURA_ES.get(k, k)}" for k, c in col_map.items()),
                unsafe_allow_html=True,
            )

        st.markdown("---")
        etiquetas_mk = {}
        for r_t in t.itertuples():
            mk_s = str(r_t.mukey)
            pct_s = f" · {r_t.pct_aoi:.1f}% of AOI ({r_t.area_ha:.1f} ha)" if pd.notna(r_t.pct_aoi) else ""
            etiquetas_mk[mk_s] = f"MUKEY {mk_s} — {r_t.muname} ({TEXTURA_ES.get(r_t.textura, r_t.textura)}{pct_s})"

        if st.session_state.get("sel_mukey_detalle_mapa") not in mukeys_lista:
            st.session_state["sel_mukey_detalle_mapa"] = st.session_state["suelo_uc_activa"]

        def _al_cambiar_uc_dropdown():
            st.session_state["suelo_uc_activa"] = st.session_state["sel_mukey_detalle_mapa"]

        mk_sel = st.selectbox(
            "🔎 Selected Map Unit (click a polygon on the map or choose from the list)",
            mukeys_lista,
            format_func=lambda k: etiquetas_mk.get(k, k),
            key="sel_mukey_detalle_mapa",
            on_change=_al_cambiar_uc_dropdown,
        )
        st.session_state["suelo_uc_activa"] = mk_sel
        _render_panel_detalle_mukey(mk_sel, t, hors, d["gdf"], aoi, prof)

    with tab_tabla:
        out = t.copy()
        out["textura"] = out["textura"].map(lambda x: TEXTURA_ES.get(x, x))
        cols = [c for c in ("mukey", "musym", "muname", "compname", "comppct_r", "n_componentes", "textura", "hsg",
                            "pct_aoi", "area_ha", "depth_cm", "fc_mm", "wp_mm", "awc_mm", "ksat_mmh", "sand", "silt", "clay")
                if c in out.columns]
        out = out[cols].round(2)
        st.dataframe(out, use_container_width=True, hide_index=True)
        export.boton_csv(out, "suelos_unidades", "dl_suelos_t")
        export.registrar("suelos_unidades", out)

    with tab_perfil:
        c_p1, c_p2 = st.columns([2, 2])
        mk_p = c_p1.selectbox("Map unit (MUKEY)", [str(m) for m in t["mukey"]], key="suelo_mk")
        hm_p = hors[hors["mukey"].astype(str) == str(mk_p)].copy()
        comps_p = hm_p[["cokey", "compname", "comppct_r"]].drop_duplicates().sort_values("comppct_r", ascending=False)
        cok_lista = comps_p["cokey"].tolist()
        cok_etq = {r.cokey: f"{r.compname} ({r.comppct_r:.0f}%)" if pd.notna(r.comppct_r) else str(r.compname) for r in comps_p.itertuples()}
        cok_sel = c_p2.selectbox("Series / Component (sorted by % share)", cok_lista, format_func=lambda k: cok_etq.get(k, str(k)), key="suelo_cok_perfil")
        hm_comp = hm_p[hm_p["cokey"] == cok_sel]

        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.fig_perfil(hm_comp), use_container_width=True, key="plt_suelo_perfil_hz")
        c2.plotly_chart(charts.fig_ternario(hors), use_container_width=True, key="plt_suelo_ternario")
        cols_h = [c for c in ("mukey", "musym", "compname", "comppct_r", "majcompflag", "hzname", "hzdept_r", "hzdepb_r",
                              "sandtotal_r", "silttotal_r", "claytotal_r", "dbthirdbar_r", "ksat_r",
                              "wtenthbar_r", "wthirdbar_r", "wfifteenbar_r", "awc_r", "om_r", "ph1to1h2o_r",
                              "ec_r", "ecec_r", "esp_r", "sar_r", "cec7_r", "n_estimado_r") if c in hm_p.columns]
        st.dataframe(hm_p[cols_h].round(2), use_container_width=True, hide_index=True)
        export.boton_csv(hors[cols_h].round(2), "suelos_horizontes", "dl_suelos_h")
        export.registrar("suelos_horizontes", hors[cols_h].round(2))

    with tab_3d:
        _render_subtab_3d_suelos(ctx, geom_shp)
