"""
Tab 0 — AOI Definition
Allows the user to define their field boundary by:
  A) uploading a .geojson or .zip (shapefile)
  B) entering coordinates manually
"""
import io
import json
import zipfile
import tempfile
import os

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union
from streamlit_folium import st_folium

from utils.export import gdf_to_shapefile_zip, gdf_to_geojson_bytes


def render(state: dict):
    st.header("📍 Area of Interest (AOI) Definition")
    st.markdown(
        "Upload a field boundary file (**GeoJSON** or **Shapefile ZIP**) "
        "or paste GeoJSON coordinates below. After loading, the field outline "
        "will appear on the map."
    )

    # ── Upload ────────────────────────────────────────────────────────────────
    st.subheader("Option A — Upload File")
    uploaded = st.file_uploader(
        "Upload field boundary (.geojson or .zip with shapefile)",
        type=["geojson", "zip"],
        key="aoi_upload",
    )

    if uploaded is not None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                if uploaded.name.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(uploaded.read())) as zf:
                        zf.extractall(tmp)
                    shp_files = [f for f in os.listdir(tmp) if f.endswith(".shp")]
                    if not shp_files:
                        st.error("No .shp file found inside the ZIP.")
                        return
                    gdf = gpd.read_file(os.path.join(tmp, shp_files[0])).to_crs("EPSG:4326")
                else:
                    content = uploaded.read()
                    gdf = gpd.read_file(io.BytesIO(content)).to_crs("EPSG:4326")

            geom = unary_union(gdf.geometry)
            area_ha = geom.area * 111320**2 / 10000
            area_ac = area_ha * 2.47105
            state["field_geom_shp"] = geom
            state["gdf_field"] = gpd.GeoDataFrame(
                index=[0], crs="epsg:4326", geometry=[geom]
            )
            st.success(
                f"✅ Field loaded — {area_ha:.2f} ha / {area_ac:.2f} ac"
            )
        except Exception as e:
            st.error(f"Error reading file: {e}")
            return

    # ── Manual GeoJSON paste ───────────────────────────────────────────────
    st.subheader("Option B — Paste GeoJSON Polygon")
    geojson_text = st.text_area(
        "Paste a GeoJSON Feature or FeatureCollection (EPSG:4326)",
        height=140,
        placeholder='{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[...]]]},"properties":{}}',
        key="aoi_geojson_text",
    )
    if st.button("Load GeoJSON", key="btn_load_geojson"):
        try:
            gj = json.loads(geojson_text)
            gdf = gpd.GeoDataFrame.from_features(
                gj["features"] if gj["type"] == "FeatureCollection" else [gj],
                crs="EPSG:4326",
            )
            geom = unary_union(gdf.geometry)
            area_ha = geom.area * 111320**2 / 10000
            state["field_geom_shp"] = geom
            state["gdf_field"] = gpd.GeoDataFrame(
                index=[0], crs="epsg:4326", geometry=[geom]
            )
            st.success(f"✅ GeoJSON loaded — {area_ha:.2f} ha")
        except Exception as e:
            st.error(f"Invalid GeoJSON: {e}")

    # ── Map preview ───────────────────────────────────────────────────────
    st.subheader("Field Preview")
    geom_shp = state.get("field_geom_shp")

    if geom_shp is not None:
        centroid = geom_shp.centroid
        m = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=13,
            tiles="Esri.WorldImagery",
            attr="Esri",
        )
        folium.GeoJson(
            mapping(geom_shp),
            style_function=lambda _: {
                "color": "#00ff88",
                "weight": 2.5,
                "fillOpacity": 0.1,
                "fillColor": "#00ff88",
            },
            tooltip="Field boundary",
        ).add_to(m)
        st_folium(m, width=800, height=450, returned_objects=[])

        # Download options
        st.markdown("#### ⬇️ Download Field Boundary")
        col1, col2 = st.columns(2)
        gdf_dl = state["gdf_field"]
        with col1:
            st.download_button(
                "📥 Download as GeoJSON",
                data=gdf_to_geojson_bytes(gdf_dl),
                file_name="field_boundary.geojson",
                mime="application/json",
            )
        with col2:
            st.download_button(
                "📥 Download as Shapefile (.zip)",
                data=gdf_to_shapefile_zip(gdf_dl, "field_boundary"),
                file_name="field_boundary.zip",
                mime="application/zip",
            )
    else:
        # Default map centered on Texas (USDA example region)
        m = folium.Map(location=[33.584, -101.845], zoom_start=10)
        st_folium(m, width=800, height=400, returned_objects=[])
        st.info("⬆️ Upload a file or paste GeoJSON to define your field.")
