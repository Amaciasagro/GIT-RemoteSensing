"""USDA-NRCS service: polygons (WFS + SQL fallback for geometries in SDA), horizons and GEE fallback."""
import io
import time
import numpy as np
import pandas as pd
import requests
import geopandas as gpd
from shapely import wkt as sh_wkt
from shapely.geometry import box
from shapely.ops import transform as sh_transform, unary_union

from ..config import TEXTURA_DEFECTO

SDA_URLS = [
    "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
    "https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest",
]
WFS_CONFIGS = [
    ("https://sdmdataaccess.nrcs.usda.gov/Spatial/SDMNAD83Geographic.wfs", "MapunitPoly", "GML3"),
    ("https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDMWGS84Geographic.wfs", "mapunitpoly", "GML3"),
    ("https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDMWGS84Geographic.wfs", "mapunitpoly", None),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GeoHub/1.0"}

COLS_NUM = [
    "comppct_r", "slope_r", "hzdept_r", "hzdepb_r", "sandtotal_r", "silttotal_r", "claytotal_r",
    "dbthirdbar_r", "dbovendry_r", "ksat_r", "wtenthbar_r", "wthirdbar_r", "wfifteenbar_r", "awc_r",
    "om_r", "ph1to1h2o_r", "ec_r", "ecec_r", "esp_r", "sar_r", "cec7_r",
]


def clase_textural(sand, silt, clay):
    """USDA textural class from % sand, silt and clay."""
    if clay is None or np.isnan(clay) or np.isnan(sand) or np.isnan(silt):
        return None
    if silt + 1.5 * clay < 15: return "Sand"
    if silt + 1.5 * clay >= 15 and silt + 2 * clay < 30: return "Loamy sand"
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "Sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52: return "Loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12): return "Silt loam"
    if silt >= 80 and clay < 12: return "Silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45: return "Sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45: return "Clay loam"
    if 27 <= clay < 40 and sand <= 20: return "Silty clay loam"
    if clay >= 35 and sand > 45: return "Sandy clay"
    if clay >= 40 and silt >= 40: return "Silty clay"
    if clay >= 40 and sand <= 45 and silt < 40: return "Clay"
    return "Loam"


def _sda_query(sql):
    """Runs a SQL query on Soil Data Access with retries and USDA mirrors."""
    ult_err = None
    payload = {"query": sql, "format": "JSON+COLUMNNAME"}
    for intento in range(2):
        for url in SDA_URLS:
            for use_json in (True, False):
                try:
                    kwargs = {"json": payload} if use_json else {"data": payload}
                    r = requests.post(url, headers=HEADERS, timeout=60, **kwargs)
                    if r.status_code >= 500:
                        ult_err = RuntimeError(f"HTTP {r.status_code} at {url}")
                        continue
                    r.raise_for_status()
                    if not r.text.strip():
                        return pd.DataFrame()
                    tabla = r.json().get("Table", [])
                    if len(tabla) < 2:
                        return pd.DataFrame(columns=tabla[0] if tabla else [])
                    return pd.DataFrame(tabla[1:], columns=tabla[0])
                except Exception as e:  # noqa: BLE001
                    ult_err = e
        if intento == 0:
            time.sleep(0.6)
    raise RuntimeError(f"Soil Data Access not available ({ult_err})")


def _poligonos_via_sda_sql(wkt_geom):
    """
    Gets the real SSURGO polygons (mupolygongeo) directly from the Tabular SQL engine
    of Soil Data Access when the WFS server returns HTTP 500 / 502.
    """
    sql = f"""
    SELECT CAST(mukey AS VARCHAR(30)) AS mukey, mupolygongeo.STAsText() AS wkt
    FROM mupolygon
    WHERE mupolygonkey IN (
        SELECT DISTINCT mupolygonkey
        FROM SDA_Get_Mupolygonkey_from_intersection_with_WktWgs84('{wkt_geom}')
    )"""
    df_wkt = _sda_query(sql)
    if df_wkt.empty or "wkt" not in df_wkt.columns:
        raise RuntimeError("SDA SQL returned no geometries for the AOI.")
    geoms = [sh_wkt.loads(w) for w in df_wkt["wkt"] if isinstance(w, str) and w.strip()]
    if not geoms:
        raise RuntimeError("Could not decode WKT geometries from SDA.")
    gdf = gpd.GeoDataFrame({"mukey": df_wkt["mukey"].astype(str)}, geometry=geoms, crs="EPSG:4326")
    return gdf[["mukey", "geometry"]]


def descargar_poligonos(bounds, buffer_deg=0.002, aoi_geom=None):
    """
    Map unit polygons (mapunitpoly):
      1) Tries the USDA WFS services (with OUTPUTFORMAT=GML3 and rounded coordinates).
      2) If the WFS fails with HTTP 500/502, extracts the exact geometries from SDA Tabular SQL (mupolygon).
    """
    x0, y0, x1, y1 = bounds
    bbox_str = f"{x0-buffer_deg:.6f},{y0-buffer_deg:.6f},{x1+buffer_deg:.6f},{y1+buffer_deg:.6f}"
    ult_err = None

    for wfs_url, typename, out_fmt in WFS_CONFIGS:
        try:
            params = dict(
                SERVICE="WFS", VERSION="1.0.0", REQUEST="GetFeature",
                TYPENAME=typename, SRSNAME="EPSG:4326", BBOX=bbox_str,
            )
            if out_fmt:
                params["OUTPUTFORMAT"] = out_fmt
            r = requests.get(wfs_url, params=params, headers=HEADERS, timeout=45)
            if r.status_code >= 500:
                ult_err = RuntimeError(f"HTTP {r.status_code} at {wfs_url}")
                continue
            r.raise_for_status()
            if b"ExceptionReport" in r.content[:600] or b"ServiceException" in r.content[:600]:
                ult_err = RuntimeError("The WFS service returned an exception.")
                continue
            gdf = gpd.read_file(io.BytesIO(r.content))
            gdf.columns = [c.lower() for c in gdf.columns]
            if "mukey" not in gdf.columns or gdf.empty:
                ult_err = RuntimeError("The WFS returned no polygons with 'mukey'.")
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            xmin, ymin, _, _ = gdf.total_bounds
            if xmin > 0 and ymin < 0:  # axis order inverted (lat, lon)
                gdf["geometry"] = gdf.geometry.apply(lambda g: sh_transform(lambda x, y, z=None: (y, x), g))
            gdf["mukey"] = gdf["mukey"].astype(str)
            return gdf[["mukey", "geometry"]]
        except Exception as e:  # noqa: BLE001
            ult_err = e

    # Direct fallback via SDA SQL (mupolygon) when the WFS returns HTTP 500
    wkt_consulta = aoi_geom.wkt if aoi_geom is not None else box(x0 - buffer_deg, y0 - buffer_deg, x1 + buffer_deg, y1 + buffer_deg).wkt
    try:
        return _poligonos_via_sda_sql(wkt_consulta)
    except Exception:
        bbox_wkt = box(x0 - buffer_deg, y0 - buffer_deg, x1 + buffer_deg, y1 + buffer_deg).wkt
        return _poligonos_via_sda_sql(bbox_wkt)


def mukeys_por_interseccion(wkt):
    """Fallback without polygons: list of mukeys that intersect the AOI."""
    df = _sda_query(f"SELECT DISTINCT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')")
    return df["mukey"].astype(str).tolist() if not df.empty else []


def consultar_horizontes(mukeys):
    """
    Queries ALL components (major and minor, sorted by comppct_r DESC) and their horizons
    for the given map units, including complete physical, chemical and agronomic properties.
    """
    mukeys = [m for m in dict.fromkeys(map(str, mukeys)) if m.isdigit()]
    partes = []
    for i in range(0, len(mukeys), 150):
        lista = ",".join(f"'{m}'" for m in mukeys[i:i + 150])
        sql = f"""
        SELECT mu.mukey, mu.musym, mu.muname,
               co.cokey, co.compname, co.comppct_r, co.majcompflag, co.hydgrp,
               co.drainagecl, co.slope_r, co.taxclname, co.taxorder,
               ch.chkey, ch.hzname, ch.hzdept_r, ch.hzdepb_r,
               ch.sandtotal_r, ch.silttotal_r, ch.claytotal_r,
               ch.dbthirdbar_r, ch.dbovendry_r, ch.ksat_r,
               ch.wtenthbar_r, ch.wthirdbar_r, ch.wfifteenbar_r, ch.awc_r,
               ch.om_r, ch.ph1to1h2o_r, ch.ec_r, ch.ecec_r, ch.esp_r, ch.sar_r, ch.cec7_r
        FROM mapunit mu
        INNER JOIN component co ON co.mukey = mu.mukey
        LEFT JOIN chorizon ch ON ch.cokey = co.cokey
        WHERE mu.mukey IN ({lista})
        ORDER BY mu.mukey, co.comppct_r DESC, ch.hzdept_r ASC"""
        d = _sda_query(sql)
        if not d.empty:
            partes.append(d)
    if not partes:
        raise RuntimeError("Soil Data Access returned no components/horizons.")
    df = pd.concat(partes, ignore_index=True)
    for c in COLS_NUM:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "dbovendry_r" in df.columns and "dbthirdbar_r" in df.columns:
        df["dbovendry_r"] = df["dbovendry_r"].fillna(df["dbthirdbar_r"])
        df["dbthirdbar_r"] = df["dbthirdbar_r"].fillna(df["dbovendry_r"])
    if "om_r" in df.columns:
        df["n_estimado_r"] = df["om_r"] * 0.05
    else:
        df["n_estimado_r"] = np.nan
    df["mukey"] = df["mukey"].astype(str)
    if "musym" not in df.columns:
        df["musym"] = df["mukey"]
    df["musym"] = df["musym"].fillna(df["mukey"]).astype(str)
    return df


def _hsg(txt, textura):
    """Hydrologic group: for dual classes (A/D) the undrained condition (the second) is taken."""
    if isinstance(txt, str) and txt.strip():
        g = txt.strip().upper().split("/")[-1][:1]
        if g in "ABCD":
            return g
    return TEXTURA_DEFECTO.get(textura, TEXTURA_DEFECTO["Loam"])["hsg"]


def _agregar_horizontes(h, prof_cm):
    """Integrates the horizons down to prof_cm: FC, PWP, AWC (mm), effective Ksat and gravitational storage."""
    h = h.dropna(subset=["hzdept_r", "hzdepb_r"]).copy()
    h["esp"] = (np.minimum(h["hzdepb_r"], prof_cm) - np.maximum(h["hzdept_r"], 0)).clip(lower=0)
    h = h[h["esp"] > 0]
    if h.empty:
        return None
    w = h["esp"]
    med = {k: np.average(h[c][h[c].notna()], weights=w[h[c].notna()]) if h[c].notna().any() else np.nan
           for k, c in (("sand", "sandtotal_r"), ("silt", "silttotal_r"), ("clay", "claytotal_r"))}
    tex_perfil = clase_textural(med["sand"], med["silt"], med["clay"]) or "Loam"
    fc_mm = awc_mm = sat_mm = 0.0
    inv_k = 0.0
    for _, r in h.iterrows():
        t = r["esp"]
        tex = clase_textural(r["sandtotal_r"], r["silttotal_r"], r["claytotal_r"]) or tex_perfil
        d = TEXTURA_DEFECTO[tex]
        fc = r["wthirdbar_r"] if pd.notna(r["wthirdbar_r"]) else d["fc"]
        wp = r["wfifteenbar_r"] if pd.notna(r["wfifteenbar_r"]) else d["wp"]
        awc = r["awc_r"] * 10 * t if pd.notna(r["awc_r"]) else max(fc - wp, 0) / 100 * 10 * t
        ks = r["ksat_r"] * 3.6 if pd.notna(r["ksat_r"]) else d["ksat"]   # µm/s -> mm/h
        por = 1 - r["dbthirdbar_r"] / 2.65 if pd.notna(r["dbthirdbar_r"]) else d["por"]
        fc_mm += fc / 100 * 10 * t
        awc_mm += awc
        sat_mm += por * 10 * t
        inv_k += t / max(ks, 0.01)
    prof_ef = float(h["esp"].sum())
    fc_mm = max(fc_mm, awc_mm)
    return dict(depth_cm=prof_ef, sand=med["sand"], silt=med["silt"], clay=med["clay"], textura=tex_perfil,
                fc_mm=fc_mm, awc_mm=awc_mm, wp_mm=max(fc_mm - awc_mm, 0.0),
                ksat_mmh=prof_ef / inv_k, gs_mm=max(sat_mm - fc_mm, 0.0))


def resumir_suelo(df, prof_cm=100):
    """
    Table per mukey (using the component with valid horizons and the highest % share)
    and full DataFrame of all components and horizons sorted by comppct_r DESC.
    """
    filas, hors_all = [], []
    for mukey, g in df.groupby("mukey", sort=False):
        g_ord = g.sort_values(["comppct_r", "hzdept_r"], ascending=[False, True]).copy()
        # Find the component with the highest % share that has valid horizons
        cok_dom = None
        agg_dom = None
        h_dom = None
        for cok, hc in g_ord.groupby("cokey", sort=False):
            agg_try = _agregar_horizontes(hc.sort_values("hzdept_r"), prof_cm)
            if agg_try is not None:
                cok_dom = cok
                agg_dom = agg_try
                h_dom = hc.sort_values("hzdept_r")
                break
        if agg_dom is None or h_dom is None:
            continue
        musym_val = str(h_dom["musym"].iloc[0]) if "musym" in h_dom.columns and pd.notna(h_dom["musym"].iloc[0]) else str(mukey)
        comppct_val = float(h_dom["comppct_r"].iloc[0]) if pd.notna(h_dom["comppct_r"].iloc[0]) else np.nan
        n_comps = int(g_ord["cokey"].nunique())
        agg_dom.update(
            mukey=str(mukey),
            musym=musym_val,
            muname=h_dom["muname"].iloc[0],
            compname=h_dom["compname"].iloc[0],
            comppct_r=comppct_val,
            n_componentes=n_comps,
            hsg=_hsg(h_dom["hydgrp"].iloc[0], agg_dom["textura"]),
        )
        filas.append(agg_dom)
        g_ord["es_dominante"] = g_ord["cokey"] == cok_dom
        hors_all.append(g_ord)
    if not filas:
        raise RuntimeError("No mukey has valid horizons.")
    return pd.DataFrame(filas), pd.concat(hors_all, ignore_index=True)


def promedio_ponderado_componente(df_comp, col, prof_cm=100):
    """Computes the horizon-thickness-weighted average (0 to prof_cm) of a numeric variable."""
    if col not in df_comp.columns:
        return np.nan
    h = df_comp.dropna(subset=["hzdept_r", "hzdepb_r", col]).copy()
    if h.empty:
        return np.nan
    h["esp"] = (np.minimum(h["hzdepb_r"], prof_cm) - np.maximum(h["hzdept_r"], 0)).clip(lower=0)
    h = h[h["esp"] > 0]
    if h.empty or h["esp"].sum() <= 0:
        return np.nan
    return float((h[col].astype(float) * h["esp"]).sum() / h["esp"].sum())


# ── 3D DEM utilities (AWS Terrarium) and Satellite Textures (Google / Esri) ─
def _latlon_to_tile(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = np.radians(np.clip(lat, -85.0, 85.0))
    y = int((1.0 - np.log(np.tan(lat_r) + 1.0 / np.cos(lat_r)) / np.pi) / 2.0 * n)
    return x, y


def _tile_bounds(x, y, zoom):
    n = 2 ** zoom
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y / n))))
    lat_min = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def suavizar_dem(elevation, pasadas=2):
    """Removes isolated spikes (despike) and applies separable Gaussian smoothing in NumPy."""
    arr = elevation.astype(np.float32).copy()
    if pasadas <= 0:
        return arr
    pad = np.pad(arr, 2, mode="edge")
    H, W = arr.shape
    local_sum = sum(pad[r:r + H, c:c + W] for r in range(5) for c in range(5))
    local_mean = (local_sum - arr) / 24.0
    diff = arr - local_mean
    mad = float(np.nanmedian(np.abs(diff))) + 1e-6
    spike_mask = np.abs(diff) > (3.5 * 1.4826 * mad)
    arr[spike_mask] = local_mean[spike_mask]
    for _ in range(int(pasadas)):
        p_h = np.pad(arr, ((0, 0), (1, 1)), mode="edge")
        arr = 0.25 * p_h[:, :-2] + 0.50 * p_h[:, 1:-1] + 0.25 * p_h[:, 2:]
        p_v = np.pad(arr, ((1, 1), (0, 0)), mode="edge")
        arr = 0.25 * p_v[:-2, :] + 0.50 * p_v[1:-1, :] + 0.25 * p_v[2:, :]
    return arr


def descargar_dem_3d(aoi_geom, zoom=14, pad_ratio=0.12, smooth_passes=2):
    """
    Downloads AWS Terrarium elevation tiles clipped to the surroundings of the AOI.
    Returns (elevation, x_coords, y_coords, tile_info).
    """
    from PIL import Image

    minx, miny, maxx, maxy = aoi_geom.bounds
    dx = max(maxx - minx, 0.001)
    dy = max(maxy - miny, 0.001)
    c_minx, c_maxx = minx - dx * pad_ratio, maxx + dx * pad_ratio
    c_miny, c_maxy = miny - dy * pad_ratio, maxy + dy * pad_ratio

    tx0, ty0 = _latlon_to_tile(c_maxy, c_minx, zoom)
    tx1, ty1 = _latlon_to_tile(c_miny, c_maxx, zoom)
    while (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 25 and zoom > 11:
        zoom -= 1
        tx0, ty0 = _latlon_to_tile(c_maxy, c_minx, zoom)
        tx1, ty1 = _latlon_to_tile(c_miny, c_maxx, zoom)

    t_cols, t_rows = tx1 - tx0 + 1, ty1 - ty0 + 1
    mosaic = np.zeros((t_rows * 256, t_cols * 256, 3), dtype=np.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{tx}/{ty}.png"
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                im = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.float32)
                ro, co = (ty - ty0) * 256, (tx - tx0) * 256
                mosaic[ro:ro + 256, co:co + 256] = im

    elevation = (mosaic[:, :, 0] * 256.0 + mosaic[:, :, 1] + mosaic[:, :, 2] / 256.0) - 32768.0
    geo_lon_min = _tile_bounds(tx0, ty0, zoom)[0]
    geo_lat_max = _tile_bounds(tx0, ty0, zoom)[3]
    geo_lon_max = _tile_bounds(tx1, ty1, zoom)[2]
    geo_lat_min = _tile_bounds(tx1, ty1, zoom)[1]

    tw, th = t_cols * 256, t_rows * 256
    x_full = np.linspace(geo_lon_min, geo_lon_max, tw)
    y_n2s = np.linspace(geo_lat_max, geo_lat_min, th)

    c0 = max(0, int(np.searchsorted(x_full, c_minx)) - 1)
    c1 = min(tw, int(np.searchsorted(x_full, c_maxx)) + 1)
    r0 = max(0, int(np.searchsorted(-y_n2s, -c_maxy)) - 1)
    r1 = min(th, int(np.searchsorted(-y_n2s, -c_miny)) + 1)

    if (c1 - c0) >= 16 and (r1 - r0) >= 16:
        elevation = elevation[r0:r1, c0:c1]
        x_coords = x_full[c0:c1]
        y_coords = y_n2s[r0:r1][::-1]
        crop_slice = (r0, r1, c0, c1)
    else:
        x_coords = x_full
        y_coords = np.linspace(geo_lat_min, geo_lat_max, th)
        crop_slice = None

    raw_elev = elevation.copy()
    if smooth_passes and smooth_passes > 0:
        elevation = suavizar_dem(elevation, pasadas=smooth_passes)

    tile_info = dict(
        tx0=tx0, tx1=tx1, ty0=ty0, ty1=ty1, zoom=zoom,
        crop_slice=crop_slice, raw_elevation=raw_elev,
        bbox_crop=(float(x_coords[0]), float(y_coords[0]), float(x_coords[-1]), float(y_coords[-1])),
    )
    return elevation, x_coords, y_coords, tile_info


def descargar_textura_xyz_3d(tile_info, proveedor="Google Satellite"):
    """Downloads Google Satellite or Esri World Imagery RGB tiles aligned with the 3D DEM."""
    from PIL import Image

    tx0, tx1, ty0, ty1, zoom = tile_info["tx0"], tile_info["tx1"], tile_info["ty0"], tile_info["ty1"], tile_info["zoom"]
    t_cols, t_rows = tx1 - tx0 + 1, ty1 - ty0 + 1
    tex = np.zeros((t_rows * 256, t_cols * 256, 3), dtype=np.uint8)
    es_google = "google" in str(proveedor).lower()

    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            if es_google:
                url = f"https://mt1.google.com/vt/lyrs=s&x={tx}&y={ty}&z={zoom}"
            else:
                url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ty}/{tx}"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                im = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.uint8)
                ro, co = (ty - ty0) * 256, (tx - tx0) * 256
                tex[ro:ro + 256, co:co + 256] = im

    cs = tile_info.get("crop_slice")
    if cs is not None:
        r0, r1, c0, c1 = cs
        tex = tex[r0:r1, c0:c1]
    return tex


def _suelos_desde_gee(aoi_geom, bounds, prof_cm=100):
    """Fallback via Google Earth Engine (OpenLandMap USDA 250 m) when both WFS and SDA Tabular are down."""
    from .gee import ee
    minx, miny, maxx, maxy = bounds
    sand_img = ee.Image("OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02")
    clay_img = ee.Image("OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02")
    bd_img = ee.Image("OpenLandMap/SOL/SOL_BULKDENS-FINEEARTH_USDA-4A1H_M/v02")
    fc_img = ee.Image("OpenLandMap/SOL/SOL_WATERCONTENT-33KPA_USDA-4B1C_M/v01")
    bands_depths = [("b0", "Ap", 0, 10), ("b10", "A", 10, 30), ("b30", "Bt1", 30, 60), ("b60", "Bt2", 60, 100), ("b100", "BC", 100, 200)]
    pila = ee.Image.cat([
        sand_img.select([b for b, _, _, _ in bands_depths], [f"sand_{b}" for b, _, _, _ in bands_depths]),
        clay_img.select([b for b, _, _, _ in bands_depths], [f"clay_{b}" for b, _, _, _ in bands_depths]),
        bd_img.select([b for b, _, _, _ in bands_depths], [f"bd_{b}" for b, _, _, _ in bands_depths]),
        fc_img.select([b for b, _, _, _ in bands_depths], [f"fc_{b}" for b, _, _, _ in bands_depths]),
    ])
    xs, ys = np.linspace(minx, maxx, 3), np.linspace(miny, maxy, 3)
    celdas, feats_ee, idx = [], [], 0
    for i in range(2):
        for j in range(2):
            sub = aoi_geom.intersection(box(xs[j], ys[i], xs[j + 1], ys[i + 1]))
            if not sub.is_empty and sub.geom_type in ("Polygon", "MultiPolygon"):
                celdas.append((str(idx), sub))
                feats_ee.append(ee.Feature(ee.Geometry(sub.__geo_interface__), {"zid": str(idx)}))
                idx += 1
    if not celdas:
        celdas = [("0", aoi_geom)]
        feats_ee = [ee.Feature(ee.Geometry(aoi_geom.__geo_interface__), {"zid": "0"})]
    red = pila.reduceRegions(collection=ee.FeatureCollection(feats_ee), reducer=ee.Reducer.mean(), scale=250).getInfo()["features"]
    props_by_zid = {f["properties"]["zid"]: f["properties"] for f in red}
    zonas_por_tex = {}
    for zid, sub_geom in celdas:
        p = props_by_zid.get(zid, {})
        s0, c0 = float(p.get("sand_b0") or 40.0), float(p.get("clay_b0") or 20.0)
        tex0 = clase_textural(s0, max(0.0, 100.0 - s0 - c0), c0) or "Loam"
        zonas_por_tex.setdefault(tex0, []).append((p, sub_geom))
    rows_df, poly_records = [], []
    for k_idx, (tex_dom, items) in enumerate(zonas_por_tex.items(), start=1):
        mukey = f"GEE_{k_idx}"
        poly_records.append({"mukey": mukey, "geometry": unary_union([g for _, g in items])})
        d_def = TEXTURA_DEFECTO.get(tex_dom, TEXTURA_DEFECTO["Loam"])
        for b_code, hz_name, z_top, z_bot in bands_depths:
            vals_s = [float(p[f"sand_{b_code}"]) for p, _ in items if p.get(f"sand_{b_code}") is not None]
            vals_c = [float(p[f"clay_{b_code}"]) for p, _ in items if p.get(f"clay_{b_code}") is not None]
            vals_bd = [float(p[f"bd_{b_code}"]) / 100.0 for p, _ in items if p.get(f"bd_{b_code}") is not None]
            vals_fc = [float(p[f"fc_{b_code}"]) for p, _ in items if p.get(f"fc_{b_code}") is not None]
            sand = float(np.mean(vals_s)) if vals_s else 40.0
            clay = float(np.mean(vals_c)) if vals_c else 20.0
            silt = max(0.0, 100.0 - sand - clay)
            bd = float(np.clip(np.mean(vals_bd), 1.05, 1.85)) if vals_bd else (1.0 - d_def["por"]) * 2.65
            fc = float(np.clip(np.mean(vals_fc), 8.0, 52.0)) if vals_fc else float(d_def["fc"])
            wp = float(np.clip(0.48 * clay + 2.5, 4.0, max(fc - 5.0, 5.0)))
            rows_df.append({
                "mukey": mukey, "muname": f"OpenLandMap USDA ({tex_dom})", "cokey": f"{mukey}_c1",
                "compname": tex_dom, "comppct_r": 100.0, "hydgrp": d_def["hsg"], "hzname": hz_name,
                "hzdept_r": float(z_top), "hzdepb_r": float(z_bot), "sandtotal_r": round(sand, 1),
                "silttotal_r": round(silt, 1), "claytotal_r": round(clay, 1), "dbthirdbar_r": round(bd, 2),
                "ksat_r": round(float(d_def["ksat"]) / 3.6, 2), "wthirdbar_r": round(fc, 1),
                "wfifteenbar_r": round(wp, 1), "awc_r": round(max(fc - wp, 4.0) / 100.0, 3),
            })
    df_gee = pd.DataFrame(rows_df)
    tabla, hors = resumir_suelo(df_gee, prof_cm=prof_cm)
    return gpd.GeoDataFrame(poly_records, crs="EPSG:4326"), tabla, hors


def consultar_suelos(aoi_geom, bounds, prof_cm):
    """
    Full flow with multi-level fallback:
      1) Polygons via WFS or WKT geometries in SDA Tabular SQL (mupolygon) -> SSURGO horizons.
      2) If no geometries are obtained but SDA Tabular responds, uses the tabular mukey intersection.
      3) If the SSURGO (USDA) servers are down (HTTP 500/502), uses the Google Earth Engine fallback (OpenLandMap 250 m).
    Returns (gdf|None, table, horizons, warnings).
    """
    avisos, gdf = [], None
    try:
        gdf = descargar_poligonos(bounds, aoi_geom=aoi_geom)
        df = consultar_horizontes(gdf["mukey"].unique())
    except Exception as e1:  # noqa: BLE001
        gdf = None
        try:
            df = consultar_horizontes(mukeys_por_interseccion(aoi_geom.wkt))
            avisos.append(f"WFS polygons not available ({e1}); the SSURGO tabular intersection was used.")
        except Exception as e2:  # noqa: BLE001
            gdf, tabla, hors = _suelos_desde_gee(aoi_geom, bounds, prof_cm)
            avisos.append(
                "⚠️ **The SSURGO (USDA-NRCS) server returned error 500/502**. "
                "The field's profiles and textures were obtained from **Google Earth Engine (OpenLandMap USDA 250 m)**."
            )
            return gdf, tabla, hors, avisos

    tabla, hors = resumir_suelo(df, prof_cm)
    if gdf is not None:
        gdf = gdf[gdf["mukey"].isin(tabla["mukey"])]
        faltan = set(df["mukey"]) - set(tabla["mukey"])
        if faltan:
            avisos.append(f"{len(faltan)} unit(s) without valid horizons (e.g. water or rock) were left out.")
    return gdf, tabla, hors, avisos


def ponderar_por_area(gdf, tabla, aoi_geom):
    """Adds area (ha) and % within the AOI per mukey and returns (table, area-weighted average row)."""
    t = tabla.copy()
    if gdf is not None and len(gdf):
        gu = gpd.GeoSeries([aoi_geom], crs="EPSG:4326").to_crs("EPSG:5070").iloc[0]
        g = gdf.to_crs("EPSG:5070")
        g["area_ha"] = g.geometry.intersection(gu).area / 1e4
        t["area_ha"] = t["mukey"].map(g.groupby("mukey")["area_ha"].sum()).fillna(0.0)
    else:
        t["area_ha"] = np.nan
    tot = t["area_ha"].sum()
    if not tot or np.isnan(tot):
        t["pct_aoi"] = np.nan
        w = np.ones(len(t)) / len(t)
    else:
        t["pct_aoi"] = 100 * t["area_ha"] / tot
        w = (t["area_ha"] / tot).to_numpy()
    prom = {c: float(np.nansum(t[c].to_numpy(float) * w)) for c in ("fc_mm", "wp_mm", "awc_mm", "ksat_mmh", "depth_cm")}
    prom["textura_dom"] = t.loc[t["pct_aoi"].idxmax() if t["pct_aoi"].notna().any() else 0, "textura"]
    prom["hsg_dom"] = t.loc[t["pct_aoi"].idxmax() if t["pct_aoi"].notna().any() else 0, "hsg"]
    return t.sort_values("pct_aoi", ascending=False, na_position="last").reset_index(drop=True), prom
