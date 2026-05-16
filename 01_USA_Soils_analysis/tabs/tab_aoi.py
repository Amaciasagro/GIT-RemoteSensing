"""
Tab 0 — AOI Definition
  A) Draw polygon(s) on the map using Leaflet-Draw (confirm each one)
  B) Upload .geojson or .zip shapefile (supports multiple features)
  C) Paste raw GeoJSON text
  Multiple polygons are stored and can be analysed individually or combined.
"""
import io
import json
import zipfile
import tempfile
import os

import folium
from folium.plugins import Draw
import geopandas as gpd
import streamlit as st
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from streamlit_folium import st_folium

from utils.export import gdf_to_shapefile_zip, gdf_to_geojson_bytes


# ── helpers ────────────────────────────────────────────────────────────────

def _gdf_from_geoms(geoms_list):
    """Build a GeoDataFrame from a list of (name, shapely_geom) tuples."""
    return gpd.GeoDataFrame(
        [{"name": name} for name, _ in geoms_list],
        geometry=[g for _, g in geoms_list],
        crs="epsg:4326",
    )


def _area_label(geom):
    ha = geom.area * 111320 ** 2 / 10_000
    ac = ha * 2.47105
    return f"{ha:.2f} ha / {ac:.2f} ac"


def _sync_state_compat(state, field_geoms):
    """Keep backward-compat keys (field_geom_shp / gdf_field) pointing to first / combined."""
    if not field_geoms:
        state.pop("field_geom_shp", None)
        state.pop("gdf_field", None)
        return
    combined = unary_union([g for _, g in field_geoms])
    state["field_geom_shp"] = combined
    state["gdf_field"] = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[combined])
    state["field_geoms"] = [
        (name, geom, gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[geom]))
        for name, geom in field_geoms
    ]


def render(state: dict):
    st.header("📍 Area of Interest (AOI) Definition")
    st.markdown(
        "Define one or **multiple** field boundaries. "
        "Each can be analysed separately or combined in the Soil tab."
    )

    # ── Session list of (name, shapely_geom) ──────────────────────────────
    if "_aoi_list" not in st.session_state:
        st.session_state["_aoi_list"] = []   # list of [name, geom]

    aoi_list = st.session_state["_aoi_list"]

    # ── Tabs for input methods ─────────────────────────────────────────────
    m_draw, m_upload, m_paste = st.tabs([
        "✏️ Draw on Map", "📂 Upload File", "📋 Paste GeoJSON"
    ])

    # ── A) Draw ────────────────────────────────────────────────────────────
    with m_draw:
        st.subheader("Draw Polygon(s) on Map")
        st.markdown(
            "Use the **polygon / rectangle tool** on the left of the map. "
            "Draw a shape, then click **Confirm drawn polygon** to save it. "
            "You can draw multiple polygons one at a time."
        )

        # Determine map centre
        if aoi_list:
            centroid = unary_union([g for _, g in aoi_list]).centroid
            map_center = [centroid.y, centroid.x]
            map_zoom   = 13
        else:
            map_center = [33.584, -101.845]
            map_zoom   = 10

        m = folium.Map(location=map_center, zoom_start=map_zoom)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri", name="Satellite", overlay=False,
        ).add_to(m)

        # Show existing polygons
        for name, geom in aoi_list:
            folium.GeoJson(
                mapping(geom),
                style_function=lambda _: {
                    "color": "#00ff88", "weight": 2.5,
                    "fillOpacity": 0.12, "fillColor": "#00ff88",
                },
                tooltip=name,
            ).add_to(m)

        # Draw plugin (polygon + rectangle only)
        Draw(
            export=False,
            draw_options={
                "polygon": True,
                "rectangle": True,
                "polyline": False,
                "circle": False,
                "circlemarker": False,
                "marker": False,
            },
            edit_options={"edit": True, "remove": True},
        ).add_to(m)
        folium.LayerControl().add_to(m)

        map_data = st_folium(m, width=820, height=500, key="draw_map")

        # Name field + confirm button
        col_name, col_btn = st.columns([2, 1])
        with col_name:
            draw_name = st.text_input(
                "Polygon name",
                value=f"Field {len(aoi_list) + 1}",
                key="draw_poly_name",
            )
        with col_btn:
            btn_confirm = st.button("✅ Confirm drawn polygon", type="primary", key="btn_confirm_draw")

        if btn_confirm:
            # streamlit-folium returns last_active_drawing
            drawn = map_data.get("last_active_drawing") if map_data else None
            if drawn and drawn.get("geometry"):
                try:
                    geom = shape(drawn["geometry"])
                    if not geom.is_valid:
                        geom = geom.buffer(0)
                    name = draw_name.strip() or f"Field {len(aoi_list) + 1}"
                    # avoid duplicate names
                    existing_names = [n for n, _ in aoi_list]
                    if name in existing_names:
                        name = f"{name} ({len(aoi_list)+1})"
                    aoi_list.append([name, geom])
                    st.session_state["_aoi_list"] = aoi_list
                    _sync_state_compat(state, aoi_list)
                    st.success(f"✅ **{name}** added — {_area_label(geom)}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not parse drawn geometry: {e}")
            else:
                st.warning("No polygon detected on the map. Please draw one first.")

    # ── B) Upload ──────────────────────────────────────────────────────────
    with m_upload:
        st.subheader("Upload Boundary File")
        st.markdown("Supports **.geojson** or **.zip** (shapefile). Multi-feature files load each feature as a separate polygon.")
        uploaded = st.file_uploader(
            "Upload .geojson or .zip",
            type=["geojson", "zip"],
            accept_multiple_files=True,
            key="aoi_upload",
        )
        upload_name_prefix = st.text_input("Name prefix for uploaded polygons", value="Upload", key="upload_prefix")
        btn_load_upload = st.button("📌 Load uploaded file(s)", key="btn_load_upload", type="primary")

        if btn_load_upload and uploaded:
            loaded_count = 0
            for up_file in uploaded:
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        if up_file.name.endswith(".zip"):
                            with zipfile.ZipFile(io.BytesIO(up_file.read())) as zf:
                                zf.extractall(tmp)
                            shp_files = [f for f in os.listdir(tmp) if f.endswith(".shp")]
                            if not shp_files:
                                st.error(f"No .shp inside {up_file.name}")
                                continue
                            gdf = gpd.read_file(os.path.join(tmp, shp_files[0])).to_crs("EPSG:4326")
                        else:
                            content = up_file.read()
                            gdf     = gpd.read_file(io.BytesIO(content)).to_crs("EPSG:4326")

                    for i, row in gdf.iterrows():
                        geom = row.geometry
                        if geom is None or geom.is_empty:
                            continue
                        # Use a name from attributes if available, else prefix+index
                        name_candidates = ["name", "Name", "NAME", "id", "ID", "label"]
                        feat_name = None
                        for nc in name_candidates:
                            if nc in row and row[nc]:
                                feat_name = str(row[nc])
                                break
                        feat_name = feat_name or f"{upload_name_prefix} {len(aoi_list) + 1}"
                        aoi_list.append([feat_name, geom])
                        loaded_count += 1

                except Exception as e:
                    st.error(f"Error reading {up_file.name}: {e}")

            if loaded_count:
                st.session_state["_aoi_list"] = aoi_list
                _sync_state_compat(state, aoi_list)
                st.success(f"✅ {loaded_count} polygon(s) loaded.")
                st.rerun()

    # ── C) Paste GeoJSON ───────────────────────────────────────────────────
    with m_paste:
        st.subheader("Paste GeoJSON")
        geojson_text = st.text_area(
            "Paste a GeoJSON Feature or FeatureCollection (EPSG:4326)",
            height=160,
            placeholder='{"type":"FeatureCollection","features":[...]}',
            key="aoi_geojson_text",
        )
        paste_name = st.text_input("Name prefix", value="Pasted", key="paste_prefix")
        if st.button("Load GeoJSON", key="btn_load_geojson", type="primary"):
            try:
                gj = json.loads(geojson_text)
                feats = gj["features"] if gj["type"] == "FeatureCollection" else [gj]
                loaded = 0
                for feat in feats:
                    geom = shape(feat["geometry"])
                    if not geom.is_valid:
                        geom = geom.buffer(0)
                    name = (
                        feat.get("properties", {}).get("name")
                        or f"{paste_name} {len(aoi_list) + 1}"
                    )
                    aoi_list.append([name, geom])
                    loaded += 1
                st.session_state["_aoi_list"] = aoi_list
                _sync_state_compat(state, aoi_list)
                st.success(f"✅ {loaded} polygon(s) loaded.")
                st.rerun()
            except Exception as e:
                st.error(f"Invalid GeoJSON: {e}")

    # ── Polygon manager ────────────────────────────────────────────────────
    st.divider()
    st.subheader(f"📋 Loaded Polygons ({len(aoi_list)})")

    if not aoi_list:
        st.info("No polygons loaded yet. Use one of the methods above.")
        return

    # Preview map
    combined = unary_union([g for _, g in aoi_list])
    centroid = combined.centroid
    m_prev = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=12,
        tiles="Esri.WorldImagery",
        attr="Esri",
    )
    colors = ["#00ff88", "#ff6b35", "#4ecdc4", "#ffe66d", "#a8e6cf", "#ff8b94"]
    for idx, (name, geom) in enumerate(aoi_list):
        color = colors[idx % len(colors)]
        folium.GeoJson(
            mapping(geom),
            style_function=lambda _, c=color: {
                "color": c, "weight": 2.5,
                "fillOpacity": 0.18, "fillColor": c,
            },
            tooltip=name,
        ).add_to(m_prev)
        # Label centroid
        c = geom.centroid
        folium.Marker(
            location=[c.y, c.x],
            icon=folium.DivIcon(
                html=f'<div style="background:rgba(0,0,0,0.6);color:{color};padding:2px 6px;'
                     f'border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap;">{name}</div>',
                icon_size=(120, 24),
                icon_anchor=(60, 12),
            ),
        ).add_to(m_prev)
    st_folium(m_prev, width=820, height=420, returned_objects=[])

    # Per-polygon table
    to_remove = []
    for idx, (name, geom) in enumerate(aoi_list):
        col_name, col_area, col_rm = st.columns([3, 2, 1])
        with col_name:
            st.markdown(f"**{idx+1}. {name}**")
        with col_area:
            st.caption(_area_label(geom))
        with col_rm:
            if st.button("🗑️", key=f"rm_{idx}", help="Remove this polygon"):
                to_remove.append(idx)

    if to_remove:
        for idx in sorted(to_remove, reverse=True):
            aoi_list.pop(idx)
        st.session_state["_aoi_list"] = aoi_list
        _sync_state_compat(state, aoi_list)
        # Invalidate soil cache so it reloads on next visit
        state.pop("soil_cache_key", None)
        st.rerun()

    if st.button("🗑️ Clear ALL polygons", key="btn_clear_all"):
        st.session_state["_aoi_list"] = []
        _sync_state_compat(state, [])
        state.pop("soil_cache_key", None)
        st.rerun()

    # Download
    st.markdown("#### ⬇️ Download All Polygons")
    gdf_all = _gdf_from_geoms(aoi_list)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "📥 GeoJSON (all polygons)",
            data=gdf_to_geojson_bytes(gdf_all),
            file_name="aoi_polygons.geojson",
            mime="application/json",
        )
    with c2:
        st.download_button(
            "📥 Shapefile (.zip)",
            data=gdf_to_shapefile_zip(gdf_all, "aoi_polygons"),
            file_name="aoi_polygons.zip",
            mime="application/zip",
        )
