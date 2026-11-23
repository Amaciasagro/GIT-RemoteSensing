"""Google Earth Engine services: climate (CHIRPS, ERA5-Land) and vegetation (Sentinel-2, Landsat 8/9)."""
import json
import os
import sys
import numpy as np
import pandas as pd
import streamlit as st

def _cargar_ee():
    """Imports earthengine-api ('ee') without shadowing compiled packages (shapely/numpy) of the active interpreter."""
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
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", ".venv", "Lib", "site-packages")),
    ]
    for _sp in _candidatos_sp:
        _ee_init = os.path.join(_sp, "ee", "__init__.py")
        if os.path.isfile(_ee_init):
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

from ..config import INDICES

SENSORES = {"Sentinel-2 SR (10 m)": "S2", "Landsat 8/9 SR (30 m)": "LS"}


def init_gee():
    """Initializes GEE (Service Account in secrets or local credentials). Returns (ok, method, error)."""
    try:
        proyecto = None
        try:
            proyecto = st.secrets.get("gee_project")
            if "gee_service_account" in st.secrets:
                sa = dict(st.secrets["gee_service_account"])
                ee.Initialize(ee.ServiceAccountCredentials(sa["client_email"], key_data=json.dumps(sa)),
                              project=sa.get("project_id"))
                return True, "service_account", ""
        except FileNotFoundError:
            pass
        ee.Initialize(project=proyecto) if proyecto else ee.Initialize()
        return True, "local credentials", ""
    except Exception as e:  # noqa: BLE001
        return False, "—", str(e)


# ── Climate ────────────────────────────────────────────────────────────────────
def _extraer(col, region, escala):
    def f(img):
        v = img.reduceRegion(ee.Reducer.mean(), region, escala, maxPixels=1e9)
        return ee.Feature(None, v).set("fecha", img.date().format("YYYY-MM-dd"))
    return [x["properties"] for x in col.map(f).getInfo()["features"]]


@st.cache_data(show_spinner=False, ttl=3600)
def serie_clima(geom_json, lon, lat, usar_poligono, f_ini, f_fin):
    """
    Daily CHIRPS + ERA5-Land series. For small AOIs (< 1 pixel) the centroid is used; for large AOIs,
    the mean over the polygon. `f_fin` is exclusive in GEE (one day is added).
    """
    fin = (pd.Timestamp(f_fin) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    region = ee.Geometry(json.loads(geom_json)) if usar_poligono else ee.Geometry.Point([lon, lat])
    chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate(f_ini, fin).select("precipitation")
    era = (ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").filterDate(f_ini, fin)
           .select(["temperature_2m", "temperature_2m_min", "temperature_2m_max", "total_precipitation_sum",
                    "potential_evaporation_sum", "volumetric_soil_water_layer_1"]))
    dc, de = pd.DataFrame(_extraer(chirps, region, 5566)), pd.DataFrame(_extraer(era, region, 11132))
    if dc.empty and de.empty:
        raise RuntimeError("CHIRPS and ERA5-Land returned no data for the range.")
    fechas = pd.date_range(f_ini, f_fin, freq="D")
    out = pd.DataFrame({"fecha": fechas})
    if not dc.empty:
        dc["fecha"] = pd.to_datetime(dc["fecha"])
        out = out.merge(dc.rename(columns={"precipitation": "p_chirps"})[["fecha", "p_chirps"]], on="fecha", how="left")
    else:
        out["p_chirps"] = np.nan
    if not de.empty:
        de["fecha"] = pd.to_datetime(de["fecha"])
        de = de.rename(columns={"temperature_2m": "t_media", "temperature_2m_min": "t_min", "temperature_2m_max": "t_max",
                                "volumetric_soil_water_layer_1": "swvl1"})
        for c in ("t_media", "t_min", "t_max"):
            de[c] = de[c] - 273.15
        de["p_era5"] = de["total_precipitation_sum"] * 1000.0
        de["pet"] = -de["potential_evaporation_sum"] * 1000.0     # ERA5 reports negative PET
        out = out.merge(de[["fecha", "t_media", "t_min", "t_max", "p_era5", "pet", "swvl1"]], on="fecha", how="left")
    for c in ("t_media", "t_min", "t_max", "p_era5", "pet", "swvl1"):
        if c not in out:
            out[c] = np.nan
    return out


# ── Vegetation ───────────────────────────────────────────────────────────────
def _coleccion(sensor, region, f_ini, f_fin, nubes):
    """Collection with harmonized bands (blue, green, red, nir, swir1) in 0–1 reflectance and clouds masked."""
    fin = (pd.Timestamp(f_fin) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    if sensor == "S2":
        col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region).filterDate(f_ini, fin)
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", nubes)))

        def prep(img):
            scl = img.select("SCL")
            ok = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
            r = img.select(["B2", "B3", "B4", "B8", "B11"], ["blue", "green", "red", "nir", "swir1"])
            return r.updateMask(ok).divide(10000).set("system:time_start", img.get("system:time_start"))
        return col.map(prep), 10
    cols = [ee.ImageCollection(c).filterBounds(region).filterDate(f_ini, fin).filter(ee.Filter.lt("CLOUD_COVER", nubes))
            for c in ("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2")]

    def prep_ls(img):
        ok = img.select("QA_PIXEL").bitwiseAnd(30).eq(0)    # bits 1–4: dilated cloud, cirrus, cloud, shadow
        r = (img.select(["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6"], ["blue", "green", "red", "nir", "swir1"])
             .multiply(0.0000275).add(-0.2))
        return r.updateMask(ok).set("system:time_start", img.get("system:time_start"))
    return cols[0].merge(cols[1]).map(prep_ls), 30


def _indices(img):
    b, g, r, n, s = [img.select(x) for x in ("blue", "green", "red", "nir", "swir1")]
    nd = lambda a, c: a.subtract(c).divide(a.add(c))
    ndvi = nd(n, r).rename("NDVI")
    ndvi_clamp = ndvi.max(ee.Image(0.0)).min(ee.Image(0.95))
    lai = ee.Image(1.0).subtract(ndvi_clamp).divide(0.95).log().multiply(-2.0).max(0.0).rename("LAI")
    evi = n.subtract(r).multiply(2.5).divide(n.add(r.multiply(6)).subtract(b.multiply(7.5)).add(1)).clamp(-1, 1.5).rename("EVI")
    evi2 = n.subtract(r).multiply(2.5).divide(n.add(r.multiply(2.4)).add(1)).clamp(-1, 1.5).rename("EVI2")
    savi = n.subtract(r).multiply(1.5).divide(n.add(r).add(0.5)).rename("SAVI")
    ndwi = nd(g, n).rename("NDWI")
    ndmi = nd(n, s).rename("NDMI")
    return ee.Image.cat([
        ndvi, lai, evi, evi2, savi, ndwi, ndmi,
        n.mask().rename("valid")])          # fraction of valid (cloud-free) pixels within the AOI


@st.cache_data(show_spinner=False, ttl=3600)
def serie_vegetacion(geom_json, f_ini, f_fin, sensor, nubes):
    """Time series of indices (mean over the AOI) per image; includes valid pixel fraction."""
    geom = ee.Geometry(json.loads(geom_json))
    col, escala = _coleccion(sensor, geom, f_ini, f_fin, nubes)

    def f(img):
        v = _indices(img).reduceRegion(ee.Reducer.mean(), geom, escala, maxPixels=1e9, bestEffort=True)
        return ee.Feature(None, v).set("fecha", img.date().format("YYYY-MM-dd"))

    feats = col.map(f).filter(ee.Filter.notNull(["NDVI"])).getInfo()["features"]
    cols = ["fecha", *INDICES, "valid"]
    if not feats:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame([x["properties"] for x in feats])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.groupby("fecha", as_index=False).mean(numeric_only=True).sort_values("fecha")
    df["valid"] = df["valid"] * 100.0
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df[cols].reset_index(drop=True)


@st.cache_data(show_spinner=False, ttl=3000)
def url_mapa_indice(geom_json, f_ini, f_fin, sensor, nubes, indice):
    """GEE tile URL of the (median) composite of an index or RGB clipped to the AOI."""
    geom = ee.Geometry(json.loads(geom_json))
    col, _ = _coleccion(sensor, geom, f_ini, f_fin, nubes)
    if int(col.size().getInfo()) == 0:
        raise RuntimeError("No images in the chosen range/cloud threshold.")
    med = col.median().clip(geom)
    if indice == "TrueColor":
        return med.select(["red", "green", "blue"]).getMapId({"min": 0.01, "max": 0.28, "gamma": 1.25})["tile_fetcher"].url_format
    if indice == "FalseColor":
        return med.select(["nir", "red", "green"]).getMapId({"min": 0.02, "max": 0.48, "gamma": 1.2})["tile_fetcher"].url_format
    img = _indices(med).select(indice).clip(geom)
    _, vmin, vmax, paleta = INDICES[indice]
    return img.getMapId({"min": vmin, "max": vmax, "palette": paleta})["tile_fetcher"].url_format


@st.cache_data(show_spinner=False, ttl=3000)
def listar_fechas_satelitales(geom_json, f_ini, f_fin, max_nubes=30, sensor="S2"):
    """
    Lists all dates with satellite imagery available over the AOI that meet
    the maximum cloudiness % threshold (`max_nubes`).
    Returns a list of dicts [{'fecha': 'YYYY-MM-DD', 'nubes_pct': float, 'etiqueta': str}, ...].
    """
    geom = ee.Geometry(json.loads(geom_json))
    fin = (pd.Timestamp(f_fin) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    prop_nube = "CLOUDY_PIXEL_PERCENTAGE" if sensor == "S2" else "CLOUD_COVER"
    if sensor == "S2":
        col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geom)
            .filterDate(f_ini, fin)
            .filter(ee.Filter.lte(prop_nube, float(max_nubes)))
        )
    else:
        c8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(geom).filterDate(f_ini, fin).filter(ee.Filter.lte(prop_nube, float(max_nubes)))
        c9 = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2").filterBounds(geom).filterDate(f_ini, fin).filter(ee.Filter.lte(prop_nube, float(max_nubes)))
        col = c8.merge(c9)

    def _meta(im):
        return ee.Feature(None, {
            "fecha": im.date().format("YYYY-MM-dd"),
            "nubes": im.get(prop_nube),
        })

    feats = col.map(_meta).getInfo().get("features", [])
    if not feats:
        return []
    rows = []
    for f in feats:
        pr = f.get("properties", {})
        f_s = pr.get("fecha")
        nub = pr.get("nubes")
        if f_s:
            rows.append({"fecha": str(f_s), "nubes_pct": float(nub) if nub is not None else 0.0})
    if not rows:
        return []
    df_f = pd.DataFrame(rows).groupby("fecha", as_index=False)["nubes_pct"].min().sort_values("fecha", ascending=False)
    salida = []
    for r in df_f.itertuples():
        salida.append({
            "fecha": r.fecha,
            "nubes_pct": round(float(r.nubes_pct), 1),
            "etiqueta": f"{r.fecha} · Cloudiness: {r.nubes_pct:.1f}%",
        })
    return salida


@st.cache_data(show_spinner=False, ttl=3000)
def url_mapa_fecha_cercana(geom_json, fecha_obj_str, f_ini, f_fin, sensor, max_nubes, capa="NDVI", recortar_aoi=True):
    """
    Finds the Sentinel-2 / Landsat image closest to `fecha_obj_str` that respects `max_nubes` (%)
    and generates the tile URLs for both the requested `capa` (index, TrueColor or FalseColor) and the true RGB.
    Returns a dict with ('url_capa', 'url_rgb', 'fecha_escena', 'nubes_pct', 'delta_dias').
    """
    geom = ee.Geometry(json.loads(geom_json))
    f_obj = pd.to_datetime(fecha_obj_str).normalize()
    t_obj_ms = int(f_obj.timestamp() * 1000)
    prop_nube = "CLOUDY_PIXEL_PERCENTAGE" if sensor == "S2" else "CLOUD_COVER"

    # Search first within ±45 days around the target date, and as a fallback over the whole range [f_ini, f_fin]
    ventanas = [
        ((f_obj - pd.Timedelta(days=45)).strftime("%Y-%m-%d"), (f_obj + pd.Timedelta(days=46)).strftime("%Y-%m-%d")),
        (str(f_ini), (pd.Timestamp(f_fin) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")),
    ]

    mejor_raw = None
    meta_info = None
    for w_ini, w_fin in ventanas:
        if sensor == "S2":
            col_raw = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(geom)
                .filterDate(w_ini, w_fin)
                .filter(ee.Filter.lte(prop_nube, float(max_nubes)))
            )
        else:
            c8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(geom).filterDate(w_ini, w_fin).filter(ee.Filter.lte(prop_nube, float(max_nubes)))
            c9 = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2").filterBounds(geom).filterDate(w_ini, w_fin).filter(ee.Filter.lte(prop_nube, float(max_nubes)))
            col_raw = c8.merge(c9)

        def _puntuar(im):
            dt_d = ee.Number(im.get("system:time_start")).subtract(t_obj_ms).abs().divide(86400000.0)
            return im.set("dt_dias", dt_d)

        col_ord = col_raw.map(_puntuar).sort("dt_dias")
        if int(col_ord.size().getInfo()) > 0:
            mejor_raw = ee.Image(col_ord.first())
            meta_info = mejor_raw.toDictionary([prop_nube, "dt_dias"]).combine(
                ee.Dictionary({"fecha_escena": mejor_raw.date().format("YYYY-MM-dd")})
            ).getInfo()
            break

    if mejor_raw is None or meta_info is None:
        raise RuntimeError(f"No image found with cloudiness ≤ {max_nubes}% near {fecha_obj_str}.")

    fecha_esc = str(meta_info.get("fecha_escena", fecha_obj_str))
    nubes_esc = round(float(meta_info.get(prop_nube, 0.0)), 1)
    delta_d = int(round(float(meta_info.get("dt_dias", 0.0))))

    # Build a mosaic of the passes of that same day (±1 day) to cover the whole AOI if it falls on a swath edge
    f_esc_dt = pd.to_datetime(fecha_esc)
    d0 = (f_esc_dt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    d1 = (f_esc_dt + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    col_dia, _ = _coleccion(sensor, geom, d0, d1, max(float(max_nubes), nubes_esc + 1.0))
    # Fallback with ±15-day median to fill any pixel masked by isolated clouds
    col_respaldo, _ = _coleccion(
        sensor, geom,
        (f_esc_dt - pd.Timedelta(days=15)).strftime("%Y-%m-%d"),
        (f_esc_dt + pd.Timedelta(days=16)).strftime("%Y-%m-%d"),
        max(float(max_nubes) + 15.0, 60.0),
    )
    img_prep = col_dia.median().unmask(col_respaldo.median())
    if recortar_aoi:
        img_prep = img_prep.clip(geom)

    url_rgb = img_prep.select(["red", "green", "blue"]).getMapId({"min": 0.01, "max": 0.28, "gamma": 1.25})["tile_fetcher"].url_format

    if capa == "TrueColor":
        url_capa = url_rgb
    elif capa == "FalseColor":
        url_capa = img_prep.select(["nir", "red", "green"]).getMapId({"min": 0.02, "max": 0.48, "gamma": 1.2})["tile_fetcher"].url_format
    else:
        img_ind = _indices(img_prep).select(capa)
        if recortar_aoi:
            img_ind = img_ind.clip(geom)
        _, vmin, vmax, paleta = INDICES[capa]
        url_capa = img_ind.getMapId({"min": vmin, "max": vmax, "palette": paleta})["tile_fetcher"].url_format

    return dict(
        url_capa=url_capa,
        url_rgb=url_rgb,
        fecha_escena=fecha_esc,
        nubes_pct=nubes_esc,
        delta_dias=delta_d,
    )


@st.cache_data(show_spinner=False, ttl=3000)
def descargar_textura_s2_fecha_3d(bbox_crop, fecha_escena_str, max_nubes=40, shape_hw=(160, 160)):
    """
    Downloads the Sentinel-2 SR RGB image (`B4, B3, B2`) of `fecha_escena_str` (or the closest one ≤ max_nubes)
    over `bbox_crop = (lon_min, lat_min, lon_max, lat_max)` and returns a uint8 array (H, W, 3)
    to project it onto the 3D topographic model.
    """
    from PIL import Image

    lon_min, lat_min, lon_max, lat_max = [float(v) for v in bbox_crop]
    H, W = int(shape_hw[0]), int(shape_hw[1])
    rect = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max], proj="EPSG:4326", geodesic=False)

    f_dt = pd.to_datetime(fecha_escena_str)
    d0 = (f_dt - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    d1 = (f_dt + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    col_dia = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(rect)
        .filterDate(d0, d1)
    )
    col_mes = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(rect)
        .filterDate((f_dt - pd.Timedelta(days=35)).strftime("%Y-%m-%d"), (f_dt + pd.Timedelta(days=35)).strftime("%Y-%m-%d"))
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max(float(max_nubes) + 15.0, 50.0)))
    )

    def _prep_rgb(im):
        scl = im.select("SCL")
        ok = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
        return im.select(["B4", "B3", "B2"]).updateMask(ok).divide(10000.0)

    rgb_im = col_dia.map(_prep_rgb).median().unmask(col_mes.map(_prep_rgb).median()).unmask(0.12).toFloat()

    # Scale so that sampleRectangle returns ~(H, W) pixels without exceeding GEE limits
    span_lon = max(lon_max - lon_min, 1e-4)
    span_lat = max(lat_max - lat_min, 1e-4)
    res_x = span_lon / max(min(W, 180), 32)
    res_y = span_lat / max(min(H, 180), 32)
    transform = [res_x, 0.0, lon_min, 0.0, -res_y, lat_max]
    rgb_reproj = rgb_im.reproject(crs="EPSG:4326", crsTransform=transform)
    props = rgb_reproj.sampleRectangle(region=rect, defaultValue=0.12).getInfo()["properties"]

    r_b = np.array(props["B4"], dtype=float)
    g_b = np.array(props["B3"], dtype=float)
    b_b = np.array(props["B2"], dtype=float)
    rgb = np.dstack([r_b, g_b, b_b])
    rgb_norm = np.clip((rgb - 0.015) / 0.25, 0.0, 1.0) ** 0.82
    rgb_u8 = (rgb_norm * 255.0).astype(np.uint8)
    im_pil = Image.fromarray(rgb_u8, mode="RGB").resize((W, H), Image.BICUBIC)
    return np.array(im_pil, dtype=np.uint8)


def _construir_imagen_fecha_indice(geom, fecha_obj_str, f_ini, f_fin, sensor, max_nubes, capa="NDVI"):
    """
    Builds the GEE image clipped to the AOI for the date closest to `fecha_obj_str`
    with cloudiness <= max_nubes and returns (ee_image_capa, fecha_escena_str).
    """
    f_obj = pd.to_datetime(fecha_obj_str).normalize()
    t_obj_ms = int(f_obj.timestamp() * 1000)
    prop_nube = "CLOUDY_PIXEL_PERCENTAGE" if sensor == "S2" else "CLOUD_COVER"
    ventanas = [
        ((f_obj - pd.Timedelta(days=45)).strftime("%Y-%m-%d"), (f_obj + pd.Timedelta(days=46)).strftime("%Y-%m-%d")),
        (str(f_ini), (pd.Timestamp(f_fin) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")),
    ]
    fecha_esc = str(fecha_obj_str)
    nubes_esc = float(max_nubes)
    for w_ini, w_fin in ventanas:
        col_raw = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geom)
            .filterDate(w_ini, w_fin)
            .filter(ee.Filter.lte(prop_nube, float(max_nubes)))
        )
        col_ord = col_raw.map(
            lambda im: im.set("dt_dias", ee.Number(im.get("system:time_start")).subtract(t_obj_ms).abs().divide(86400000.0))
        ).sort("dt_dias")
        if int(col_ord.size().getInfo()) > 0:
            mejor = ee.Image(col_ord.first())
            meta = mejor.toDictionary([prop_nube]).combine(ee.Dictionary({"fecha_esc": mejor.date().format("YYYY-MM-dd")})).getInfo()
            fecha_esc = str(meta.get("fecha_esc", fecha_obj_str))
            nubes_esc = float(meta.get(prop_nube, max_nubes))
            break

    f_esc_dt = pd.to_datetime(fecha_esc)
    d0 = (f_esc_dt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    d1 = (f_esc_dt + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    col_dia, _ = _coleccion(sensor, geom, d0, d1, max(float(max_nubes), nubes_esc + 1.0))
    col_respaldo, _ = _coleccion(
        sensor, geom,
        (f_esc_dt - pd.Timedelta(days=15)).strftime("%Y-%m-%d"),
        (f_esc_dt + pd.Timedelta(days=16)).strftime("%Y-%m-%d"),
        max(float(max_nubes) + 15.0, 60.0),
    )
    img_prep = col_dia.median().unmask(col_respaldo.median()).clip(geom)
    if capa == "TrueColor":
        return img_prep.select(["red", "green", "blue"]).toFloat(), fecha_esc
    if capa == "FalseColor":
        return img_prep.select(["nir", "red", "green"]).toFloat(), fecha_esc
    return _indices(img_prep).select(capa).toFloat().clip(geom), fecha_esc


@st.cache_data(show_spinner=False, ttl=3000)
def exportar_geotiff_indice(geom_json, fecha_obj_str, f_ini, f_fin, max_nubes, capa="NDVI", escala=10):
    """
    Downloads from GEE the GeoTIFF file (.tif or .zip) at 10 m of the vegetation layer/index
    for the chosen date clipped to the AOI. Returns (bytes_archivo, extension_str, fecha_escena_str).
    """
    import requests
    from shapely.geometry import shape

    geom_dict = json.loads(geom_json)
    geom = ee.Geometry(geom_dict)
    shp = shape(geom_dict)
    area_ha = shp.area * (111320.0 ** 2) / 10000.0
    esc_uso = max(int(escala), 20 if area_ha > 2500 else 10)

    img_exp, f_esc = _construir_imagen_fecha_indice(geom, fecha_obj_str, f_ini, f_fin, "S2", max_nubes, capa=capa)
    url = img_exp.getDownloadURL({
        "name": f"{capa}_{f_esc}",
        "scale": esc_uso,
        "crs": "EPSG:4326",
        "region": geom,
        "format": "GEO_TIFF",
    })
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    ct = r.headers.get("content-type", "").lower()
    ext = ".zip" if "zip" in ct else ".tif"
    return r.content, ext, f_esc


@st.cache_data(show_spinner=False, ttl=3000)
def exportar_vector_indice(geom_json, fecha_obj_str, f_ini, f_fin, max_nubes, capa="NDVI", n_grid=55):
    """
    Samples the vegetation index raster layer over the AOI in GEE and builds a vector grid
    of polygonal cells clipped to the AOI with the index value in each cell.
    Returns (geojson_bytes, shapefile_zip_bytes, fecha_escena_str, n_celdas).
    """
    import io
    import tempfile
    import zipfile
    import geopandas as gpd
    from shapely.geometry import box, shape

    geom_dict = json.loads(geom_json)
    shp = shape(geom_dict)
    minx, miny, maxx, maxy = shp.bounds
    rect = ee.Geometry.Rectangle([minx, miny, maxx, maxy], proj="EPSG:4326", geodesic=False)

    nom_banda = "red" if capa == "TrueColor" else ("nir" if capa == "FalseColor" else capa)
    img_exp, f_esc = _construir_imagen_fecha_indice(rect, fecha_obj_str, f_ini, f_fin, "S2", max_nubes, capa=capa)
    banda_im = img_exp.select(nom_banda).unmask(-9999).toFloat()

    span_x = max(maxx - minx, 1e-4)
    span_y = max(maxy - miny, 1e-4)
    res_x = span_x / int(n_grid)
    res_y = span_y / int(n_grid)
    transform = [res_x, 0.0, minx, 0.0, -res_y, maxy]
    props = banda_im.reproject(crs="EPSG:4326", crsTransform=transform).sampleRectangle(
        region=rect, defaultValue=-9999
    ).getInfo()["properties"]

    arr = np.array(props[nom_banda], dtype=float)
    arr[arr <= -9998] = np.nan
    ny, nx = arr.shape
    xs = np.linspace(minx, maxx, nx + 1)
    ys = np.linspace(maxy, miny, ny + 1)  # row 0 is North (maxy)

    registros = []
    geoms = []
    for r in range(ny):
        y_top, y_bot = float(ys[r]), float(ys[r + 1])
        for c in range(nx):
            val = float(arr[r, c])
            if not np.isfinite(val):
                continue
            x_left, x_right = float(xs[c]), float(xs[c + 1])
            celda = box(x_left, min(y_top, y_bot), x_right, max(y_top, y_bot))
            if not shp.intersects(celda):
                continue
            geom_clip = shp.intersection(celda)
            if geom_clip.is_empty or geom_clip.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            registros.append({
                "indice": str(nom_banda),
                "fecha": str(f_esc),
                "valor": round(val, 4),
            })
            geoms.append(geom_clip)

    if not geoms:
        gdf = gpd.GeoDataFrame([{"indice": str(nom_banda), "fecha": str(f_esc), "valor": 0.0}], geometry=[shp], crs="EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame(registros, geometry=geoms, crs="EPSG:4326")

    geojson_bytes = gdf.to_json().encode("utf-8")

    buf_zip = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = os.path.join(tmpdir, f"{nom_banda}_{f_esc}.shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")
        with zipfile.ZipFile(buf_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for fn in os.listdir(tmpdir):
                zf.write(os.path.join(tmpdir, fn), arcname=fn)

    return geojson_bytes, buf_zip.getvalue(), f_esc, len(gdf)
