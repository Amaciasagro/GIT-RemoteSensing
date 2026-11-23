"""Google Earth Engine services: climate (CHIRPS, ERA5-Land) and vegetation (Sentinel-2, Landsat 8/9)."""
import json
import numpy as np
import pandas as pd
import streamlit as st
import ee

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
    evi = n.subtract(r).multiply(2.5).divide(n.add(r.multiply(6)).subtract(b.multiply(7.5)).add(1)).clamp(-1, 1.5)
    return ee.Image.cat([
        nd(n, r).rename("NDVI"), evi.rename("EVI"),
        n.subtract(r).multiply(1.5).divide(n.add(r).add(0.5)).rename("SAVI"),
        nd(g, n).rename("NDWI"), nd(n, s).rename("NDMI"),
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
    return df[cols].reset_index(drop=True)


@st.cache_data(show_spinner=False, ttl=3000)
def url_mapa_indice(geom_json, f_ini, f_fin, sensor, nubes, indice):
    """GEE tile URL of the (median) composite of an index clipped to the AOI."""
    geom = ee.Geometry(json.loads(geom_json))
    col, _ = _coleccion(sensor, geom, f_ini, f_fin, nubes)
    if int(col.size().getInfo()) == 0:
        raise RuntimeError("No images in the chosen range/cloud threshold.")
    img = _indices(col.median()).select(indice).clip(geom)
    _, vmin, vmax, paleta = INDICES[indice]
    return img.getMapId({"min": vmin, "max": vmax, "palette": paleta})["tile_fetcher"].url_format
