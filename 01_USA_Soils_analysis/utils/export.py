"""
Export utilities: CSV, Excel, GeoJSON, Shapefile (zip), HTML.
"""
import io
import json
import zipfile
import tempfile
import os
import pandas as pd
import geopandas as gpd


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Data") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


def gdf_to_geojson_bytes(gdf: gpd.GeoDataFrame) -> bytes:
    return gdf.to_json().encode("utf-8")


def gdf_to_shapefile_zip(gdf: gpd.GeoDataFrame, name: str = "export") -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        shp_path = os.path.join(tmp_dir, f"{name}.shp")
        gdf.to_file(shp_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for ext in ["shp", "shx", "dbf", "prj", "cpg"]:
                fp = os.path.join(tmp_dir, f"{name}.{ext}")
                if os.path.exists(fp):
                    zf.write(fp, f"{name}.{ext}")
        return buf.getvalue()


def geojson_features_to_bytes(features: list) -> bytes:
    fc = {"type": "FeatureCollection", "features": features}
    return json.dumps(fc, ensure_ascii=False).encode("utf-8")


def fig_to_html_bytes(fig) -> bytes:
    """Serialize a Plotly figure to standalone HTML bytes."""
    html_str = fig.to_html(full_html=True, include_plotlyjs="cdn")
    return html_str.encode("utf-8")


def folium_to_html_bytes(folium_map) -> bytes:
    buf = io.BytesIO()
    folium_map.save(buf, close_file=False)
    return buf.getvalue()
