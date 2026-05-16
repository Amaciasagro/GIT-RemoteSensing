"""
Tab 2 — Topographic Models
  • Interactive contour map (Leaflet): hover → live elevation readout in sidebar
  • Hillshade preview (matplotlib)
  • Help tooltips on all sliders
  • Field boundary drawn on every map
  • Downloads: GeoJSON, HTML, CSV
"""
import json
import io
import warnings

import folium
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from shapely.geometry import mapping

from utils.dem import download_dem, extract_contours
from utils.export import geojson_features_to_bytes, fig_to_html_bytes

warnings.filterwarnings("ignore")


def _elev_to_hex(val, elev_min, elev_max, cmap):
    norm = (val - elev_min) / (elev_max - elev_min + 1e-9)
    r, g, b, _ = cmap(norm)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def _build_contour_html(contour_features, field_geojson_str, centroid_lat, centroid_lon,
                        elev_min, elev_max):
    """
    Standalone Leaflet HTML map with:
      - Satellite basemap
      - Field boundary
      - Coloured contour lines
      - Live elevation readout (top bar updates on hover)
      - Gradient colour legend
    """
    cmap   = plt.cm.get_cmap("RdYlGn")
    n_stop = 8
    stops, tick_html = [], ""
    for i in range(n_stop + 1):
        t = i / n_stop
        r, g, b, _ = cmap(t)
        hex_c = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
        stops.append(f"{hex_c} {int(t * 100)}%")
        if i % 2 == 0:
            label = "{:.0f} m".format(elev_min + t * (elev_max - elev_min))
            tick_html += (
                f'<span style="position:absolute;left:{int(t*100)}%;transform:translateX(-50%);'
                f'font-size:10px;color:#aaa;top:16px;white-space:nowrap;">{label}</span>'
            )

    for feat in contour_features:
        feat["properties"]["color"] = _elev_to_hex(
            feat["properties"]["elevation_m"], elev_min, elev_max, cmap
        )

    contour_json = json.dumps({"type": "FeatureCollection", "features": contour_features})
    gradient_css = ", ".join(stops)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{{margin:0;padding:0;background:#0f0f1e;}}</style>
</head><body>
<div style="position:relative;width:100%;height:620px;border-radius:12px;overflow:hidden;
            font-family:Segoe UI,Arial,sans-serif;">

  <!-- Live elevation readout -->
  <div id="elev-badge" style="display:none;position:absolute;top:14px;left:50%;
       transform:translateX(-50%);background:rgba(0,0,0,0.82);color:#fff;
       padding:7px 22px;border-radius:20px;font-size:15px;font-weight:700;
       z-index:1000;pointer-events:none;border:1px solid rgba(255,255,255,0.2);
       letter-spacing:.5px;min-width:180px;text-align:center;">
    — m
  </div>

  <!-- Legend -->
  <div style="position:absolute;bottom:20px;left:50%;transform:translateX(-50%);
       background:rgba(15,15,30,0.88);border:1px solid rgba(255,255,255,0.12);
       padding:10px 18px 30px 18px;border-radius:10px;z-index:1000;min-width:300px;">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                color:#aaa;margin-bottom:6px;">Elevation</div>
    <div style="height:13px;border-radius:5px;
                background:linear-gradient(to right,{gradient_css});
                border:1px solid rgba(255,255,255,0.1);"></div>
    <div style="position:relative;height:28px;">{tick_html}</div>
  </div>

  <!-- Hint -->
  <div style="position:absolute;top:14px;right:14px;background:rgba(15,15,30,0.85);
       color:#aaa;font-size:11px;padding:8px 12px;border-radius:8px;z-index:1000;
       line-height:1.8;border:1px solid rgba(255,255,255,0.1);">
    Hover line = elevation | Scroll = zoom | Drag = pan
  </div>

  <div id="leafmap" style="width:100%;height:100%;"></div>
</div>

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function() {{
  var CONTOURS = {contour_json};
  var FIELD    = {field_geojson_str};

  var map = L.map("leafmap").setView([{centroid_lat}, {centroid_lon}], 15);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
    {{attribution:"Esri", maxZoom:19}}
  ).addTo(map);

  var badge = document.getElementById("elev-badge");

  // Field boundary
  L.geoJSON(FIELD, {{
    style: {{color:"#00ff88", weight:2.8, fillOpacity:0.08, fillColor:"#00ff88"}}
  }}).addTo(map);

  // Contour lines
  L.geoJSON(CONTOURS, {{
    style: function(feat) {{
      return {{color: feat.properties.color, weight: 2.8, opacity: 0.75}};
    }},
    onEachFeature: function(feat, layer) {{
      var elev = feat.properties.elevation_m;
      layer.on("mouseover", function() {{
        this.setStyle({{weight: 5, opacity: 1, color: "#ffffff"}});
        badge.textContent = "⛰  " + elev + " m";
        badge.style.display = "block";
      }});
      layer.on("mouseout", function() {{
        this.setStyle({{weight: 2.8, opacity: 0.75, color: feat.properties.color}});
        badge.style.display = "none";
      }});
      layer.bindTooltip(elev + " m", {{sticky: true, className: "leaflet-tooltip"}});
    }}
  }}).addTo(map);
}})();
</script>
</body></html>"""
    return html


def render(state: dict):
    st.header("🏔️ Topographic Models")

    # Support multiple AOIs — use first or combined
    field_geoms = state.get("field_geoms")
    if field_geoms:
        from shapely.ops import unary_union
        import geopandas as gpd
        if len(field_geoms) > 1:
            sel = st.selectbox(
                "Field to analyse",
                [f[0] for f in field_geoms] + ["— All combined —"],
                key="topo_field_sel",
            )
            if sel == "— All combined —":
                geom_shp = unary_union([f[1] for f in field_geoms])
                gdf_field = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[geom_shp])
            else:
                f = next(x for x in field_geoms if x[0] == sel)
                geom_shp, gdf_field = f[1], f[2]
        else:
            geom_shp, gdf_field = field_geoms[0][1], field_geoms[0][2]
    else:
        geom_shp  = state.get("field_geom_shp")
        gdf_field = state.get("gdf_field")

    if geom_shp is None:
        st.warning("⚠️ Please define your AOI in the **AOI** tab first.")
        return

    field_geojson_str = json.dumps(gdf_field.__geo_interface__)
    centroid = gdf_field.geometry.centroid.iloc[0]

    # ── Controls ───────────────────────────────────────────────────────────
    col_ctrl, col_map = st.columns([1, 3])

    with col_ctrl:
        zoom_level = st.slider(
            "Tile zoom level",
            12, 16, 14, key="topo_zoom",
            help=(
                "Controls the resolution of the elevation tiles downloaded from AWS Terrarium.\n\n"
                "**12** = coarser grid, fewer tiles, fast.\n"
                "**16** = fine detail (≈4 m/px), many tiles, slow.\n"
                "Recommended: **13–14** for fields 50–500 ha."
            ),
        )
        n_contours = st.slider(
            "Number of contour levels",
            5, 30, 15, key="topo_nlevels",
            help=(
                "How many elevation iso-lines to draw.\n\n"
                "Fewer lines → cleaner map; more lines → finer vertical detail.\n"
                "Recommended: **10–20** for typical agricultural fields."
            ),
        )
        btn_load = st.button("🗻 Load / Refresh DEM", key="btn_load_dem", type="primary")

    # ── Load DEM ──────────────────────────────────────────────────────────
    dem_key = f"{geom_shp.bounds}_{zoom_level}"
    if btn_load or state.get("dem_key") != dem_key:
        if btn_load:
            progress = st.progress(0, text="Downloading elevation tiles…")
            try:
                elev, x_c, y_c, tile_info = download_dem(
                    geom_shp, zoom=zoom_level,
                    progress_cb=lambda p: progress.progress(p * 0.5, text=f"Tiles: {int(p*100)}%"),
                )
                state.update(elevation=elev, x_coords=x_c, y_coords=y_c,
                             tile_info=tile_info, dem_key=dem_key)
                progress.progress(0.5, text="Extracting contours…")
                state["contour_features"] = extract_contours(elev, x_c, y_c, n_levels=n_contours)
                state["contour_n"] = n_contours
                progress.progress(1.0, text="Done!")
                progress.empty()
            except Exception as e:
                st.error(f"DEM download error: {e}")
                return

    # Re-extract contours if n_contours changed without re-downloading
    if ("elevation" in state and state.get("contour_n") != n_contours):
        state["contour_features"] = extract_contours(
            state["elevation"], state["x_coords"], state["y_coords"], n_levels=n_contours
        )
        state["contour_n"] = n_contours

    if "elevation" not in state:
        with col_map:
            st.info("👈 Click **Load / Refresh DEM** to download elevation data.")
        return

    elevation        = state["elevation"]
    x_coords         = state["x_coords"]
    y_coords         = state["y_coords"]
    contour_features = state.get("contour_features", [])

    elev_values = [f["properties"]["elevation_m"] for f in contour_features]
    elev_min    = min(elev_values) if elev_values else 0
    elev_max    = max(elev_values) if elev_values else 1

    with col_ctrl:
        st.divider()
        st.metric("Min elevation", f"{elevation.min():.1f} m")
        st.metric("Max elevation", f"{elevation.max():.1f} m")
        st.metric("Relief", f"{elevation.max() - elevation.min():.1f} m")
        st.metric("Contour segments", len(contour_features))
        st.divider()
        st.markdown(
            "**💡 Live elevation:** hover over any contour line on the map "
            "to see its exact elevation in the top bar of the map.",
            help="The white bar at the top of the interactive map updates dynamically when you hover over a line.",
        )

    # ── Contour map ────────────────────────────────────────────────────────
    with col_map:
        st.subheader("Interactive Contour Map")
        html_map = _build_contour_html(
            contour_features, field_geojson_str,
            centroid.y, centroid.x,
            elev_min, elev_max,
        )
        st.components.v1.html(html_map, height=640, scrolling=False)

    # ── Hillshade ──────────────────────────────────────────────────────────
    st.subheader("Hillshade Preview")
    with st.spinner("Rendering hillshade…"):
        fig_hs, ax = plt.subplots(figsize=(10, 5), facecolor="#0f0f1e")
        ax.set_facecolor("#0f0f1e")

        # The DEM array has row-0 = northernmost latitude (max lat).
        # y_coords runs south→north (y_coords[0] = lat_min, y_coords[-1] = lat_max).
        # We flip the elevation array vertically so that row-0 = south (lat_min),
        # which matches the geographic extent passed to imshow/contour (origin="lower").
        elev_geo  = np.flipud(elevation)   # row-0 now = southernmost = lat_min

        ls        = LightSource(azdeg=315, altdeg=35)
        hillshade = ls.hillshade(elev_geo, vert_exag=3, dx=30, dy=30)

        ax.imshow(
            hillshade, cmap="gray", origin="lower",
            extent=[x_coords[0], x_coords[-1], y_coords[0], y_coords[-1]],
            aspect="auto",
        )
        # contour also gets the geo-oriented (flipped) elevation + matching y coords
        cs = ax.contour(
            np.linspace(x_coords[0], x_coords[-1], elev_geo.shape[1]),
            np.linspace(y_coords[0], y_coords[-1], elev_geo.shape[0]),
            elev_geo, levels=n_contours, cmap="RdYlGn", linewidths=0.8,
        )
        ax.clabel(cs, inline=True, fontsize=7, fmt="%.0f m", colors="white")
        ax.set_xlabel("Longitude", color="#aaa")
        ax.set_ylabel("Latitude",  color="#aaa")
        ax.tick_params(colors="#aaa")
        for spine in ax.spines.values():
            spine.set_edgecolor("#333")
        plt.tight_layout()
        st.pyplot(fig_hs)
        plt.close(fig_hs)

    # ── Downloads ─────────────────────────────────────────────────────────
    st.markdown("#### ⬇️ Download")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "📥 Contours GeoJSON",
            data=geojson_features_to_bytes(contour_features),
            file_name="contours.geojson",
            mime="application/json",
        )
    with c2:
        st.download_button(
            "📥 Contour Map (HTML)",
            data=html_map.encode("utf-8"),
            file_name="contour_map.html",
            mime="text/html",
        )
    with c3:
        H, W = elevation.shape
        rows_data = []
        for r in range(0, H, max(1, H // 200)):
            for c in range(0, W, max(1, W // 200)):
                rows_data.append({
                    "longitude":   round(float(x_coords[c]), 6),
                    "latitude":    round(float(y_coords[r]), 6),
                    "elevation_m": round(float(elevation[r, c]), 2),
                })
        elev_df = pd.DataFrame(rows_data)
        st.download_button(
            "📥 Elevation Grid (CSV, sampled)",
            data=elev_df.to_csv(index=False).encode("utf-8"),
            file_name="elevation_grid.csv",
            mime="text/csv",
        )
