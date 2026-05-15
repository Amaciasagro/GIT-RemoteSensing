"""
DEM (Digital Elevation Model) utilities using Terrarium tiles.
Handles tile download, mosaic assembly, and contour extraction.
"""
import io
import numpy as np
import requests
import matplotlib.pyplot as plt
from PIL import Image
from shapely.geometry import LineString, mapping


def latlon_to_tile(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int(
        (1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / np.pi)
        / 2
        * n
    )
    return x, y


def tile_bounds(x, y, zoom):
    n = 2 ** zoom
    lon_min = x / n * 360 - 180
    lon_max = (x + 1) / n * 360 - 180
    lat_max = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))
    lat_min = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def terrarium_to_meters(r, g, b):
    return (r * 256 + g + b / 256) - 32768


def download_dem(field_geom_shp, zoom=14, progress_cb=None):
    """
    Download Terrarium elevation tiles for the field bounding box.
    Returns (elevation, x_coords, y_coords, tile_info dict).
    """
    minx, miny, maxx, maxy = field_geom_shp.bounds

    tile_min_x, tile_min_y = latlon_to_tile(maxy, minx, zoom)
    tile_max_x, tile_max_y = latlon_to_tile(miny, maxx, zoom)

    TILE_PX = 256
    tile_cols = tile_max_x - tile_min_x + 1
    tile_rows = tile_max_y - tile_min_y + 1
    total_tiles = tile_cols * tile_rows
    mosaic = np.zeros((tile_rows * TILE_PX, tile_cols * TILE_PX, 3), dtype=np.float32)

    count = 0
    for ty in range(tile_min_y, tile_max_y + 1):
        for tx in range(tile_min_x, tile_max_x + 1):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{tx}/{ty}.png"
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                tile_img = np.array(
                    Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.float32
                )
                row_off = (ty - tile_min_y) * TILE_PX
                col_off = (tx - tile_min_x) * TILE_PX
                mosaic[row_off : row_off + TILE_PX, col_off : col_off + TILE_PX] = tile_img
            count += 1
            if progress_cb:
                progress_cb(count / total_tiles)

    elevation = terrarium_to_meters(mosaic[:, :, 0], mosaic[:, :, 1], mosaic[:, :, 2])

    geo_lon_min = tile_bounds(tile_min_x, tile_min_y, zoom)[0]
    geo_lat_max = tile_bounds(tile_min_x, tile_min_y, zoom)[3]
    geo_lon_max = tile_bounds(tile_max_x, tile_max_y, zoom)[2]
    geo_lat_min = tile_bounds(tile_max_x, tile_max_y, zoom)[1]

    total_px_w = tile_cols * TILE_PX
    total_px_h = tile_rows * TILE_PX

    x_coords = np.linspace(geo_lon_min, geo_lon_max, elevation.shape[1])
    y_coords = np.linspace(geo_lat_min, geo_lat_max, elevation.shape[0])

    tile_info = {
        "tile_min_x": tile_min_x,
        "tile_max_x": tile_max_x,
        "tile_min_y": tile_min_y,
        "tile_max_y": tile_max_y,
        "zoom": zoom,
        "geo_lon_min": geo_lon_min,
        "geo_lat_max": geo_lat_max,
        "geo_lon_max": geo_lon_max,
        "geo_lat_min": geo_lat_min,
        "total_px_w": total_px_w,
        "total_px_h": total_px_h,
    }

    return elevation, x_coords, y_coords, tile_info


def extract_contours(elevation, x_coords, y_coords, n_levels=15):
    """Extract contour line features from elevation array."""
    total_px_h, total_px_w = elevation.shape
    geo_lon_min = x_coords[0]
    geo_lon_max = x_coords[-1]
    geo_lat_min = y_coords[0]
    geo_lat_max = y_coords[-1]

    def pixel_to_latlon(px, py):
        lon = geo_lon_min + (px / total_px_w) * (geo_lon_max - geo_lon_min)
        lat = geo_lat_max - (py / total_px_h) * (geo_lat_max - geo_lat_min)
        return lon, lat

    fig_tmp, ax_tmp = plt.subplots()
    cs = ax_tmp.contour(elevation, levels=n_levels)
    plt.close(fig_tmp)

    features = []
    for i, level_segs in enumerate(cs.allsegs):
        level_value = cs.levels[i]
        for seg in level_segs:
            if len(seg) < 2:
                continue
            coords_geo = [pixel_to_latlon(px, py) for px, py in seg]
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(LineString(coords_geo)),
                    "properties": {"elevation_m": round(float(level_value), 1)},
                }
            )
    return features


def download_satellite_texture(tile_info, progress_cb=None):
    """Download Esri World Imagery tiles for 3D texture draping."""
    ti = tile_info
    t_cols = ti["tile_max_x"] - ti["tile_min_x"] + 1
    t_rows = ti["tile_max_y"] - ti["tile_min_y"] + 1
    total_tiles = t_cols * t_rows
    texture = np.zeros((t_rows * 256, t_cols * 256, 3), dtype=np.uint8)

    count = 0
    for ty in range(ti["tile_min_y"], ti["tile_max_y"] + 1):
        for tx in range(ti["tile_min_x"], ti["tile_max_x"] + 1):
            url = (
                f"https://server.arcgisonline.com/ArcGIS/rest/services/"
                f"World_Imagery/MapServer/tile/{ti['zoom']}/{ty}/{tx}"
            )
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                tile_img = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"))
                r_off = (ty - ti["tile_min_y"]) * 256
                c_off = (tx - ti["tile_min_x"]) * 256
                texture[r_off : r_off + 256, c_off : c_off + 256] = tile_img
            count += 1
            if progress_cb:
                progress_cb(count / total_tiles)

    return texture
