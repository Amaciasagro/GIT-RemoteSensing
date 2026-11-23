"""Google Earth Engine client: DEM, Sentinel-2 indices (NDVI, NDWI, SAVI, LAI), CHIRPS, and ERA5-Land."""
import json
import os
import sys
import numpy as np
import pandas as pd
import streamlit as st

def _cargar_ee():
    """Imports earthengine-api ('ee') without shadowing compiled packages (shapely/numpy) in the active interpreter."""
    try:
        import ee as _ee
        if hasattr(_ee, "Initialize"):
            return _ee
    except Exception:
        pass

    import importlib.util
    for _mod in [k for k in list(sys.modules) if k == "ee" or k.startswith("ee.")]:
        sys.modules.pop(_mod, None)
    _candidatos_sp = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".venv", "Lib", "site-packages")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".venv", "Lib", "site-packages")),
    ]
    for _sp in _candidatos_sp:
        _ee_init = os.path.join(_sp, "ee", "__init__.py")
        if os.path.isfile(_ee_init):
            # Append to the END of sys.path so compiled shapely/numpy/pyproj in active Python are not shadowed
            if _sp not in sys.path:
                sys.path.append(_sp)
            _spec = importlib.util.spec_from_file_location(
                "ee", _ee_init, submodule_search_locations=[os.path.join(_sp, "ee")]
            )
            _mod_ee = importlib.util.module_from_spec(_spec)
            sys.modules["ee"] = _mod_ee
            _spec.loader.exec_module(_mod_ee)
            return _mod_ee
    import ee as _ee
    return _ee


ee = _cargar_ee()


def init_gee():
    """Initializes GEE with Service Account (secrets) or default credentials. Returns (ok, method, error)."""
    try:
        proyecto = None
        try:
            proyecto = st.secrets.get("gee_project")
            if "gee_service_account" in st.secrets:
                sa = dict(st.secrets["gee_service_account"])
                cred = ee.ServiceAccountCredentials(sa["client_email"], key_data=json.dumps(sa))
                ee.Initialize(cred, project=sa.get("project_id"))
                return True, "service_account", ""
        except FileNotFoundError:
            pass  # no secrets.toml found: fall back to ADC
        ee.Initialize(project=proyecto) if proyecto else ee.Initialize()
        return True, "ADC", ""
    except Exception as e:  # noqa: BLE001
        return False, "—", str(e)


# ── Sentinel-2 ───────────────────────────────────────────────────────────────
def _coleccion_s2(region, f_ini, f_fin, nubes=60):
    return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(region).filterDate(f_ini, f_fin)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", nubes)))


def _mascara_s2(img):
    """Masks clouds/shadows with SCL and scales reflectance to 0–1."""
    scl = img.select("SCL")
    ok = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
    return (img.select(["B2", "B3", "B4", "B8", "B11"]).updateMask(ok).divide(10000)
            .set("system:time_start", img.get("system:time_start")))


def _indices(img):
    """NDVI, NDWI (McFeeters), SAVI, and LAI (empirical from EVI)."""
    b2, b3, b4, b8 = [img.select(b) for b in ("B2", "B3", "B4", "B8")]
    ndvi = b8.subtract(b4).divide(b8.add(b4)).rename("NDVI")
    ndwi = b3.subtract(b8).divide(b3.add(b8)).rename("NDWI")
    savi = b8.subtract(b4).multiply(1.5).divide(b8.add(b4).add(0.5)).rename("SAVI")
    evi = b8.subtract(b4).multiply(2.5).divide(
        b8.add(b4.multiply(6)).subtract(b2.multiply(7.5)).add(1))
    lai = evi.multiply(3.618).subtract(0.118).clamp(0, 7).rename("LAI")
    return ee.Image.cat([ndvi, ndwi, savi, lai]).toFloat()


# ── Grid (DEM + indices) ─────────────────────────────────────────────────────
def _dem_terrarium_malla(malla):
    """
    Direct elevation fallback (AWS Terrarium DEM tiles) resampled to the UTM cells of `malla`
    if the GEE 'elevation' band returns empty pixels (-9999).
    """
    import io
    import requests
    import geopandas as gpd
    from PIL import Image
    from .geo_utils import coordenadas_celdas

    ny, nx = int(malla["ny"]), int(malla["nx"])
    X, Y = coordenadas_celdas(malla, (ny, nx))
    pts = gpd.GeoSeries(gpd.points_from_xy(X.ravel(), Y.ravel()), crs=malla["crs"]).to_crs("EPSG:4326")
    lons = np.array([p.x for p in pts], dtype=float).reshape(ny, nx)
    lats = np.array([p.y for p in pts], dtype=float).reshape(ny, nx)

    lon_min, lon_max = float(lons.min()), float(lons.max())
    lat_min, lat_max = float(lats.min()), float(lats.max())
    zoom = 13 if max(lon_max - lon_min, lat_max - lat_min) < 0.08 else 11
    n = 2 ** zoom

    def _ll2tile(lat, lon):
        xt = int((lon + 180.0) / 360.0 * n)
        lat_r = np.radians(np.clip(lat, -85.0, 85.0))
        yt = int((1.0 - np.log(np.tan(lat_r) + 1.0 / np.cos(lat_r)) / np.pi) / 2.0 * n)
        return xt, yt

    tx0, ty0 = _ll2tile(lat_max, lon_min)
    tx1, ty1 = _ll2tile(lat_min, lon_max)
    tc, tr = tx1 - tx0 + 1, ty1 - ty0 + 1
    mos = np.zeros((tr * 256, tc * 256, 3), dtype=np.float32)

    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{tx}/{ty}.png"
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                im = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.float32)
                ro, co = (ty - ty0) * 256, (tx - tx0) * 256
                mos[ro:ro + 256, co:co + 256] = im

    elev_mos = (mos[:, :, 0] * 256.0 + mos[:, :, 1] + mos[:, :, 2] / 256.0) - 32768.0
    # Continuous pixel coordinates inside the mosaic for each cell (lons, lats)
    px_global = (lons + 180.0) / 360.0 * n * 256.0 - tx0 * 256.0
    lat_r_arr = np.radians(np.clip(lats, -85.0, 85.0))
    py_global = (1.0 - np.log(np.tan(lat_r_arr) + 1.0 / np.cos(lat_r_arr)) / np.pi) / 2.0 * n * 256.0 - ty0 * 256.0

    ci = np.clip(np.round(px_global).astype(int), 0, elev_mos.shape[1] - 1)
    ri = np.clip(np.round(py_global).astype(int), 0, elev_mos.shape[0] - 1)
    return elev_mos[ri, ci].astype(float)


@st.cache_data(show_spinner=False, ttl=3600)
def descargar_malla(geom_json, malla, f_ini, f_fin, _v="v3"):
    """Downloads DEM (3DEP 10 m / SRTM / NASADEM + Terrarium fallback) and Sentinel-2 composite resampled to the grid."""
    crs, res = malla["crs"], malla["res"]
    x0, y1, nx, ny = malla["x0"], malla["y1"], malla["nx"], malla["ny"]
    transform = [res, 0, x0, 0, -res, y1]
    rect = ee.Geometry.Rectangle([x0, y1 - ny * res, x0 + nx * res, y1], proj=crs, geodesic=False)

    col = _coleccion_s2(rect, f_ini, f_fin).map(_mascara_s2)
    n_s2 = int(col.size().getInfo())
    if n_s2 == 0:
        raise RuntimeError("No Sentinel-2 images found in the specified window: please expand the search days.")
    proj = ee.Image(col.first()).select("B8").projection()
    ind = _indices(col.median()).setDefaultProjection(proj)
    ind_reproj = (
        ind.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=4096, bestEffort=True)
        .reproject(crs=crs, crsTransform=transform)
        .unmask(ind.reproject(crs=crs, crsTransform=transform))
    )

    # IMPORTANT: Do not use reduceResolution or .toFloat().resample() on 3DEP/SRTM because they lose their native
    # projection in GEE and return -9999; reproject elevation assets directly with bilinear on the raw asset.
    dep = ee.Image("USGS/3DEP/10m").select("elevation").resample("bilinear")
    srtm = ee.Image("USGS/SRTMGL1_003").select("elevation").resample("bilinear")
    nasadem = ee.Image("NASA/NASADEM_HGT/001").select("elevation").resample("bilinear")
    dem = dep.unmask(srtm).unmask(nasadem).rename("elevation").toFloat().reproject(crs=crs, crsTransform=transform)

    pila = dem.addBands(ind_reproj.toFloat()).unmask(-9999).toFloat().reproject(crs=crs, crsTransform=transform)

    props = pila.sampleRectangle(region=rect, defaultValue=-9999).getInfo()["properties"]
    bandas = ["elevation", "NDVI", "NDWI", "SAVI", "LAI"]
    arrs = {}
    for b in bandas:
        a = np.array(props[b], dtype=float)
        a[a <= -9998] = np.nan
        arrs[b] = a

    # Automatic fallback with AWS Terrarium tiles if GEE returned empty or constant elevation
    el = arrs["elevation"]
    if not np.isfinite(el).any() or (float(np.nanmax(el) - np.nanmin(el)) < 1e-3 and float(np.nanmax(np.abs(el))) < 1e-3):
        el_terr = _dem_terrarium_malla(malla)
        # Match exact shape in case sampleRectangle returned +1 pixel on the edge
        th, tw = el.shape
        arrs["elevation"] = el_terr[:th, :tw] if (el_terr.shape[0] >= th and el_terr.shape[1] >= tw) else np.resize(el_terr, (th, tw))

    return {"arrays": arrs, "n_s2": n_s2}


@st.cache_data(show_spinner=False, ttl=3600)
def serie_indices(geom_json, f_ini, f_fin):
    """Time series of mean indices over the AOI (one row per date)."""
    geom = ee.Geometry(json.loads(geom_json))
    col = _coleccion_s2(geom, f_ini, f_fin, nubes=40).map(
        lambda im: _indices(_mascara_s2(im)).set("system:time_start", im.get("system:time_start")))

    def f(img):
        v = img.reduceRegion(ee.Reducer.mean(), geom, 20, maxPixels=1e9, bestEffort=True)
        return ee.Feature(None, v).set("fecha", img.date().format("YYYY-MM-dd"))

    feats = col.map(f).filter(ee.Filter.notNull(["NDVI"])).getInfo()["features"]
    if not feats:
        return pd.DataFrame(columns=["fecha", "NDVI", "NDWI", "SAVI", "LAI"])
    df = pd.DataFrame([x["properties"] for x in feats])
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df.groupby("fecha", as_index=False).mean().sort_values("fecha")


# ── Climate ──────────────────────────────────────────────────────────────────
def _extraer(col, punto, escala):
    def f(img):
        v = img.reduceRegion(ee.Reducer.first(), punto, escala)
        return ee.Feature(None, v).set("fecha", img.date().format("YYYY-MM-dd"))
    return [x["properties"] for x in col.map(f).getInfo()["features"]]


@st.cache_data(show_spinner=False, ttl=3600)
def serie_clima(lon, lat, f_ini, f_fin, _v="v2"):
    """Daily series at centroid: CHIRPS P, ERA5-Land P/mean-min-max T/PET/surface and deep soil moisture."""
    pt = ee.Geometry.Point([lon, lat])
    chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate(f_ini, f_fin).select("precipitation")
    era = (ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").filterDate(f_ini, f_fin)
           .select(["temperature_2m", "temperature_2m_min", "temperature_2m_max",
                    "total_precipitation_sum", "potential_evaporation_sum",
                    "volumetric_soil_water_layer_1", "volumetric_soil_water_layer_3",
                    "volumetric_soil_water_layer_4"]))
    dc = pd.DataFrame(_extraer(chirps, pt, 5566))
    de = pd.DataFrame(_extraer(era, pt, 11132))
    if dc.empty and de.empty:
        raise RuntimeError("No CHIRPS/ERA5 data available for the period.")
    out = pd.DataFrame({"fecha": pd.to_datetime(pd.concat([dc.get("fecha", pd.Series(dtype=str)),
                                                           de.get("fecha", pd.Series(dtype=str))]).unique())})
    if not dc.empty:
        dc["fecha"] = pd.to_datetime(dc["fecha"])
        out = out.merge(dc.rename(columns={"precipitation": "p_chirps"}), on="fecha", how="left")
    else:
        out["p_chirps"] = np.nan
    if not de.empty:
        de["fecha"] = pd.to_datetime(de["fecha"])
        de["t2m"] = de["temperature_2m"] - 273.15
        de["t_min"] = de["temperature_2m_min"] - 273.15 if "temperature_2m_min" in de else np.nan
        de["t_max"] = de["temperature_2m_max"] - 273.15 if "temperature_2m_max" in de else np.nan
        de["p_era5"] = de["total_precipitation_sum"] * 1000.0
        de["pet"] = -de["potential_evaporation_sum"] * 1000.0   # ERA5 reports PET as negative
        de["swvl1"] = de["volumetric_soil_water_layer_1"]
        de["swvl3"] = de.get("volumetric_soil_water_layer_3", np.nan)
        de["swvl4"] = de.get("volumetric_soil_water_layer_4", np.nan)
        out = out.merge(de[["fecha", "t2m", "t_min", "t_max", "p_era5", "pet", "swvl1", "swvl3", "swvl4"]], on="fecha", how="left")
    for c in ("t2m", "t_min", "t_max", "p_era5", "pet", "swvl1", "swvl3", "swvl4"):
        if c not in out:
            out[c] = np.nan
    return out.sort_values("fecha").reset_index(drop=True)


@st.cache_data(show_spinner=False, ttl=3600)
def hietograma_era5_horario(lon, lat, f_ini_str, f_fin_str, p_total_objetivo_mm=None):
    """
    Extracts the real hourly hyetograph from ECMWF/ERA5_LAND/HOURLY ('total_precipitation_hourly')
    between f_ini_str and f_fin_str (inclusive), calibrating total volume with CHIRPS (p_total_objetivo_mm).
    Returns dict with:
      - 'df': hourly DataFrame ['fecha_hora', 'p_mm_h', 'p_acum_mm']
      - 'duracion_real_h': effective hours with rainfall >= 0.15 mm/h
      - 'intensidad_max_mmh': hourly peak (mm/h)
      - 'intensidad_media_mmh': mean intensity during active hours (mm/h)
      - 'fuente_horaria': str
    """
    t0 = pd.to_datetime(f_ini_str)
    t1 = pd.to_datetime(f_fin_str) + pd.Timedelta(days=1)
    fuente_h = "ERA5-Land Hourly + CHIRPS"
    df_h = pd.DataFrame()

    try:
        pt = ee.Geometry.Point([float(lon), float(lat)])
        col_h = (
            ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
            .filterDate(t0.strftime("%Y-%m-%d"), t1.strftime("%Y-%m-%d"))
            .select(["total_precipitation_hourly"])
        )

        def _f_hr(img):
            v = img.reduceRegion(ee.Reducer.first(), pt, 11132)
            return ee.Feature(None, v).set("fh", img.date().format("YYYY-MM-dd HH:mm"))

        feats = col_h.map(_f_hr).getInfo().get("features", [])
        if feats:
            rows = []
            for x in feats:
                pr = x.get("properties", {})
                val_m = pr.get("total_precipitation_hourly")
                p_mm = max(float(val_m) * 1000.0, 0.0) if val_m is not None else 0.0
                rows.append({"fecha_hora": pd.to_datetime(pr["fh"]), "p_mm_h": p_mm})
            df_h = pd.DataFrame(rows).sort_values("fecha_hora").reset_index(drop=True)
    except Exception:  # noqa: BLE001
        df_h = pd.DataFrame()

    # If ERA5 hourly returned no significant rain while CHIRPS recorded a storm,
    # or if the hourly query failed, build a physical SCS-II hourly profile
    p_obj = float(p_total_objetivo_mm) if (p_total_objetivo_mm is not None and p_total_objetivo_mm > 0) else None
    if df_h.empty or df_h["p_mm_h"].sum() < 0.2:
        fuente_h = "SCS-II hourly profile calibrated with CHIRPS"
        n_horas = max(int((t1 - t0).total_seconds() // 3600), 24)
        fechas_h = pd.date_range(t0, periods=n_horas, freq="h")
        # Asymmetric bell curve concentrated in the storm core
        x_norm = np.linspace(-2.5, 3.0, n_horas)
        pesos = np.exp(-0.5 * (x_norm ** 2)) * (x_norm > -1.8)
        pesos = np.where(pesos > 0.12 * pesos.max(), pesos, 0.0)
        suma_p = pesos.sum() or 1.0
        vol = p_obj if p_obj is not None else 25.0
        df_h = pd.DataFrame({"fecha_hora": fechas_h, "p_mm_h": vol * (pesos / suma_p)})
    elif p_obj is not None and df_h["p_mm_h"].sum() > 0:
        # Scale ERA5-Land hourly series to preserve the exact CHIRPS total rainfall depth
        factor = p_obj / float(df_h["p_mm_h"].sum())
        df_h["p_mm_h"] = df_h["p_mm_h"] * factor

    df_h["p_mm_h"] = df_h["p_mm_h"].clip(lower=0.0)
    df_h["p_acum_mm"] = df_h["p_mm_h"].cumsum()

    horas_activas = df_h[df_h["p_mm_h"] >= 0.15]
    dur_real = int(max(len(horas_activas), 1))
    i_max = float(df_h["p_mm_h"].max()) if not df_h.empty else 0.0
    p_tot = float(df_h["p_mm_h"].sum()) if not df_h.empty else (p_obj or 0.0)
    i_med = float(p_tot / dur_real) if dur_real > 0 else 0.0

    return dict(
        df=df_h,
        duracion_real_h=int(np.clip(dur_real, 1, 72)),
        horas_totales_evento=int(dur_real),
        intensidad_max_mmh=round(i_max, 2),
        intensidad_media_mmh=round(i_med, 2),
        p_total_mm=round(p_tot, 2),
        fuente_horaria=fuente_h,
    )


# ── USGS WBD Hydrological Watersheds (HUC12 / HUC10) ─────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def consultar_cuenca_wbd(geom_json, nivel="HUC12"):
    """
    Queries the USGS Watershed Boundary Dataset vector collection in Google Earth Engine:
      - USGS/WBD/2017/HUC12 (Subwatershed, default)
      - USGS/WBD/2017/HUC10 (Watershed, optional)
    spatially filtered with .filterBounds(aoi).
    Returns a GeoJSON FeatureCollection dict with the subwatersheds intersecting the AOI.
    """
    nivel_u = "HUC10" if "10" in str(nivel).upper() else "HUC12"
    col_id = f"USGS/WBD/2017/{nivel_u}"
    aoi_ee = ee.Geometry(json.loads(geom_json))
    fc = ee.FeatureCollection(col_id).filterBounds(aoi_ee)

    def _simplificar(feat):
        return feat.simplify(maxError=15)

    info = fc.map(_simplificar).getInfo()
    return info, col_id, nivel_u


# ── Drainage Network (HydroSHEDS FreeFlowingRivers -> NHD Flowline fallback) ─
@st.cache_data(show_spinner=False, ttl=3600)
def consultar_red_drenaje_gee(geom_json, preferir="HydroSHEDS"):
    """
    Queries the vector drainage network in Google Earth Engine filtered by .filterBounds(aoi):
      1) Primary (default): WWF/HydroSHEDS/v1/FreeFlowingRivers
      2) GEE fallback: projects/sat-io/open-datasets/NHD/NHD_FLOWLINE
    Returns (geojson_dict, source_str, warnings_list).
    """
    avisos = []
    aoi_ee = ee.Geometry(json.loads(geom_json))
    reg = aoi_ee.buffer(1500)

    hydrosheds_cfg = ("WWF/HydroSHEDS/v1/FreeFlowingRivers", "WWF/HydroSHEDS/v1/FreeFlowingRivers")
    nhd_cfg = ("projects/sat-io/open-datasets/NHD/NHD_FLOWLINE", "NHD Flowline (projects/sat-io/open-datasets/NHD/NHD_FLOWLINE)")
    colecciones = [nhd_cfg, hydrosheds_cfg] if "NHD" in str(preferir).upper() else [hydrosheds_cfg, nhd_cfg]

    for col_id, etiqueta in colecciones:
        try:
            fc = ee.FeatureCollection(col_id).filterBounds(reg).limit(400)
            info = fc.map(lambda f: f.simplify(maxError=12)).getInfo()
            feats = info.get("features", []) if isinstance(info, dict) else []
            if feats:
                return info, etiqueta, avisos
            avisos.append(f"ℹ️ `{col_id}` (.filterBounds) returned no channels within the queried area.")
        except Exception as e:  # noqa: BLE001
            avisos.append(f"⚠️ Could not query `{col_id}` ({e}). Trying fallback collection…")

    return {"type": "FeatureCollection", "features": []}, "No GEE reaches", avisos


# ── 3D Satellite Textures (Sentinel-2, Google Satellite, and Esri High-Res) ──
@st.cache_data(show_spinner=False, ttl=3600)
def obtener_textura_xyz_malla(malla, proveedor="esri"):
    """
    Downloads high-resolution satellite tiles (Esri World Imagery or Google Satellite) for the UTM grid
    and returns a uint8 RGB array (ny, nx, 3) perfectly aligned with the DEM.
    """
    import io
    import requests
    import geopandas as gpd
    from PIL import Image
    from .geo_utils import coordenadas_celdas

    ny, nx = int(malla["ny"]), int(malla["nx"])
    X, Y = coordenadas_celdas(malla, (ny, nx))
    pts = gpd.GeoSeries(gpd.points_from_xy(X.ravel(), Y.ravel()), crs=malla["crs"]).to_crs("EPSG:4326")
    lons = np.array([p.x for p in pts], dtype=float).reshape(ny, nx)
    lats = np.array([p.y for p in pts], dtype=float).reshape(ny, nx)

    lon_min, lon_max = float(lons.min()), float(lons.max())
    lat_min, lat_max = float(lats.min()), float(lats.max())
    span = max(lon_max - lon_min, lat_max - lat_min)
    zoom = 17 if span < 0.015 else (16 if span < 0.03 else (15 if span < 0.07 else (14 if span < 0.16 else 13)))
    n = 2 ** zoom

    def _ll2tile(lat, lon):
        xt = int((lon + 180.0) / 360.0 * n)
        lat_r = np.radians(np.clip(lat, -85.0, 85.0))
        yt = int((1.0 - np.log(np.tan(lat_r) + 1.0 / np.cos(lat_r)) / np.pi) / 2.0 * n)
        return xt, yt

    tx0, ty0 = _ll2tile(lat_max, lon_min)
    tx1, ty1 = _ll2tile(lat_min, lon_max)
    # Cap maximum tile count to keep downloads fast (<= 25 tiles)
    while (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 25 and zoom > 11:
        zoom -= 1
        n = 2 ** zoom
        tx0, ty0 = _ll2tile(lat_max, lon_min)
        tx1, ty1 = _ll2tile(lat_min, lon_max)

    es_google = "google" in str(proveedor).lower()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    tc, tr = tx1 - tx0 + 1, ty1 - ty0 + 1
    mos = np.zeros((tr * 256, tc * 256, 3), dtype=np.uint8)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            if es_google:
                url = f"https://mt1.google.com/vt/lyrs=s&x={tx}&y={ty}&z={zoom}"
            else:
                url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ty}/{tx}"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                im = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.uint8)
                ro, co = (ty - ty0) * 256, (tx - tx0) * 256
                mos[ro:ro + 256, co:co + 256] = im

    px_g = (lons + 180.0) / 360.0 * n * 256.0 - tx0 * 256.0
    lat_r_arr = np.radians(np.clip(lats, -85.0, 85.0))
    py_g = (1.0 - np.log(np.tan(lat_r_arr) + 1.0 / np.cos(lat_r_arr)) / np.pi) / 2.0 * n * 256.0 - ty0 * 256.0
    ci = np.clip(np.round(px_g).astype(int), 0, mos.shape[1] - 1)
    ri = np.clip(np.round(py_g).astype(int), 0, mos.shape[0] - 1)
    nom_fte = f"Google Satellite (Zoom {zoom})" if es_google else f"Esri World Imagery (Zoom {zoom})"
    return mos[ri, ci], nom_fte


def obtener_textura_esri_malla(malla):
    return obtener_textura_xyz_malla(malla, proveedor="esri")


def obtener_textura_google_malla(malla):
    return obtener_textura_xyz_malla(malla, proveedor="google")


@st.cache_data(show_spinner=False, ttl=3600)
def obtener_textura_s2_evento(malla, fecha_ref_str=None):
    """
    Finds the cloud-free Sentinel-2 SR (RGB: B4, B3, B2) scene closest to the event date
    (or today if manual event), resamples it to the UTM grid, and returns:
      (rgb_uint8_array, capture_date_str, cloud_pct, delta_days, source_str).
    Falls back to Esri World Imagery if no clean scene is available in GEE.
    """
    crs, res = malla["crs"], malla["res"]
    x0, y1, nx, ny = malla["x0"], malla["y1"], int(malla["nx"]), int(malla["ny"])
    transform = [res, 0, x0, 0, -res, y1]
    rect = ee.Geometry.Rectangle([x0, y1 - ny * res, x0 + nx * res, y1], proj=crs, geodesic=False)

    f_ref = pd.to_datetime(fecha_ref_str).normalize() if fecha_ref_str else pd.Timestamp.today().normalize()
    for ventana_d, max_nubes in ((20, 35), (45, 55), (90, 75)):
        f_ini = (f_ref - pd.Timedelta(days=ventana_d)).strftime("%Y-%m-%d")
        f_fin = (f_ref + pd.Timedelta(days=ventana_d + 1)).strftime("%Y-%m-%d")
        try:
            col = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(rect)
                .filterDate(f_ini, f_fin)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_nubes))
            )
            # Record millisecond difference relative to f_ref to prioritize closest & least cloudy scene
            t_ref_ms = int(f_ref.timestamp() * 1000)

            def _puntuar(im):
                dt_dias = ee.Number(im.get("system:time_start")).subtract(t_ref_ms).abs().divide(86400000.0)
                nubes = ee.Number(im.get("CLOUDY_PIXEL_PERCENTAGE"))
                score = dt_dias.add(nubes.multiply(0.35))
                return im.set("score_proximidad", score, "dt_dias", dt_dias)

            col_ord = col.map(_puntuar).sort("score_proximidad")
            if int(col_ord.size().getInfo()) == 0:
                continue

            mejor = ee.Image(col_ord.first())
            meta = mejor.toDictionary(["CLOUDY_PIXEL_PERCENTAGE", "dt_dias"]).combine(
                ee.Dictionary({"fecha_str": mejor.date().format("YYYY-MM-dd")})
            ).getInfo()

            # RGB composite backed by window median to fill any local clouds
            med_rgb = col_ord.limit(5).map(_mascara_s2).median().select(["B4", "B3", "B2"])
            rgb_im = (
                _mascara_s2(mejor).select(["B4", "B3", "B2"])
                .unmask(med_rgb)
                .unmask(0.12)
                .toFloat()
                .reproject(crs=crs, crsTransform=transform)
            )
            props = rgb_im.sampleRectangle(region=rect, defaultValue=0.12).getInfo()["properties"]
            r_b = np.array(props["B4"], dtype=float)[:ny, :nx]
            g_b = np.array(props["B3"], dtype=float)[:ny, :nx]
            b_b = np.array(props["B2"], dtype=float)[:ny, :nx]
            rgb = np.dstack([r_b, g_b, b_b])
            # Surface reflectance contrast stretch (0.015 - 0.26) + gamma correction
            rgb_norm = np.clip((rgb - 0.015) / 0.245, 0.0, 1.0) ** 0.82
            rgb_u8 = (rgb_norm * 255.0).astype(np.uint8)
            if rgb_u8.shape[0] != ny or rgb_u8.shape[1] != nx:
                from PIL import Image
                rgb_u8 = np.array(Image.fromarray(rgb_u8).resize((nx, ny), Image.BILINEAR))

            f_cap = str(meta.get("fecha_str", f_ref.strftime("%Y-%m-%d")))
            nub = round(float(meta.get("CLOUDY_PIXEL_PERCENTAGE", 0.0)), 1)
            dt_d = int(round(float(meta.get("dt_dias", 0.0))))
            return rgb_u8, f_cap, nub, dt_d, "Sentinel-2 SR Harmonized (GEE)"
        except Exception:  # noqa: BLE001
            continue

    # Automatic fallback to Esri World Imagery if no cloud-free S2 capture was found
    rgb_esri, fte_esri = obtener_textura_esri_malla(malla)
    return rgb_esri, f_ref.strftime("%Y-%m-%d"), 0.0, 0, f"{fte_esri} (fallback due to S2 cloud cover)"
