"""AOI reading and validation (file, GeoJSON, point+radius). Not restricted to the US: only flags `en_eeuu`."""
import io, os, json, hashlib, tempfile
import geopandas as gpd
import shapely
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union

BBOX_EEUU = (-180.0, 15.0, -64.0, 72.0)
MAX_HA = 20000.0


def gdf_desde_geojson(obj):
    """GeoJSON (text/dict; Feature, FeatureCollection or geometry) -> WGS84 GeoDataFrame."""
    if isinstance(obj, str):
        obj = json.loads(obj)
    t = obj.get("type")
    if t == "FeatureCollection":
        return gpd.GeoDataFrame.from_features(obj["features"], crs="EPSG:4326")
    if t == "Feature":
        return gpd.GeoDataFrame.from_features([obj], crs="EPSG:4326")
    return gpd.GeoDataFrame(geometry=[shape(obj)], crs="EPSG:4326")


def gdf_desde_archivo(archivo):
    """.zip (Shapefile) or .geojson/.json uploaded with st.file_uploader."""
    nombre, datos = archivo.name.lower(), archivo.getvalue()
    if nombre.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "aoi.zip")
            with open(ruta, "wb") as f:
                f.write(datos)
            return gpd.read_file(f"zip://{ruta}")
    if nombre.endswith((".geojson", ".json")):
        return gpd.read_file(io.BytesIO(datos))
    raise ValueError("Unsupported format: use .zip (Shapefile) or .geojson")


def gdf_desde_punto(lat, lon, radio_m):
    """Circle of `radio_m` meters around a point (buffer in UTM)."""
    epsg = 32600 + int((lon + 180) // 6) + 1 if lat >= 0 else 32700 + int((lon + 180) // 6) + 1
    p = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(f"EPSG:{epsg}").buffer(radio_m)
    return gpd.GeoDataFrame(geometry=p.to_crs("EPSG:4326").values, crs="EPSG:4326")


def normalizar_aoi(gdf, max_ha=MAX_HA):
    """Validates and merges the AOI into a WGS84 geometry; returns a serializable dict with area, centroid and flags."""
    if gdf is None or gdf.empty:
        raise ValueError("No geometries in the input.")
    gdf = (gdf.set_crs("EPSG:4326") if gdf.crs is None else gdf).to_crs("EPSG:4326")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    geom = unary_union([shapely.make_valid(g) for g in gdf.geometry])
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("The AOI must be a polygon.")
    lon, lat = geom.centroid.x, geom.centroid.y
    area_ha = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:6933").area.iloc[0] / 1e4  # equivalent
    if area_ha > max_ha:
        raise ValueError(f"AOI too large ({area_ha:,.0f} ha). Maximum: {max_ha:,.0f} ha.")
    x0, y0, x1, y1 = BBOX_EEUU
    gj = mapping(geom)
    return {"geom": json.loads(json.dumps(gj)), "area_ha": float(area_ha), "lon": float(lon), "lat": float(lat),
            "bounds": tuple(float(b) for b in geom.bounds), "en_eeuu": bool(x0 <= lon <= x1 and y0 <= lat <= y1),
            "id": hashlib.md5(json.dumps(gj, sort_keys=True).encode()).hexdigest()[:10]}
