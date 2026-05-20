# ============================================================
# gee_client.py — Google Earth Engine: init + queries
# ============================================================

import ee
import streamlit as st
import json, math
import pandas as pd
import numpy as np
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from config import (
    ERA5_COLLECTION, CHIRPS_COLLECTION,
    CHIRPS_BASELINE_YEARS,
    PALETA_ANOMALIA, PALETA_BALANCE,
    PALETA_PRECIPITACION, PALETA_TEMPERATURA,
    PALETA_HELADAS, PALETA_CALOR,
)


# ════════════════════════════════════════════════════════════
# INICIALIZACIÓN
# ════════════════════════════════════════════════════════════
@st.cache_resource
def init_gee():
    """
    Intenta inicializar GEE usando Service Account primero;
    si no está configurada, usa Application Default Credentials (gcloud).
    Retorna (ok: bool, metodo: str, error: str | None).
    """
    project_id = st.secrets.get("EARTHENGINE_PROJECT", "")

    # ── Método 1: Service Account ────────────────────────────
    if "gee_service_account" in st.secrets:
        try:
            sa_info = dict(st.secrets["gee_service_account"])
            # private_key en TOML puede tener \\n literales → convertir
            if "private_key" in sa_info:
                sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")
            if not project_id:
                project_id = sa_info.get("project_id", "")
            scopes = [
                "https://www.googleapis.com/auth/earthengine",
                "https://www.googleapis.com/auth/cloud-platform",
            ]
            creds = service_account.Credentials.from_service_account_info(
                sa_info, scopes=scopes
            )
            ee.Initialize(creds, project=project_id)
            return True, "service_account", None
        except Exception as e:
            return False, "service_account", str(e)

    # ── Método 2: Application Default Credentials (gcloud) ──
    try:
        import google.auth
        creds, detected_project = google.auth.default(scopes=[
            "https://www.googleapis.com/auth/earthengine",
            "https://www.googleapis.com/auth/cloud-platform",
        ])
        if not project_id:
            project_id = detected_project or ""
        ee.Initialize(creds, project=project_id)
        return True, "adc", None
    except Exception as e:
        return False, "adc", str(e)


# ════════════════════════════════════════════════════════════
# ERA5 — SERIE DIARIA PARA UN LOTE
# ════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def descargar_era5(aoi_json: str, fecha_inicio: str, fecha_fin: str) -> str:
    """
    Descarga serie diaria ERA5-Land para un polígono.
    Retorna JSON del DataFrame (cacheado por parámetros).
    """
    lote_geom = ee.Geometry(json.loads(aoi_json))

    bandas = [
        "total_precipitation_sum",
        "temperature_2m_max",
        "temperature_2m_min",
        "dewpoint_temperature_2m",
        "surface_solar_radiation_downwards_sum",
        "u_component_of_wind_10m",
        "v_component_of_wind_10m",
        "total_evaporation_sum",
    ]

    col = (ee.ImageCollection(ERA5_COLLECTION)
           .filterBounds(lote_geom)
           .filterDate(fecha_inicio, fecha_fin)
           .select(bandas))

    def extract(img):
        stats = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=lote_geom,
            scale=11132,
            maxPixels=1e9,
        )
        return ee.Feature(None, {
            "fecha": ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"),
            **{b: stats.get(b) for b in bandas},
        })

    features = (ee.FeatureCollection(col.map(extract))
                .sort("fecha")
                .getInfo()["features"])

    registros = []
    for f in features:
        p = f["properties"]
        if p.get("temperature_2m_max") is None:
            continue
        t_max  = p["temperature_2m_max"]  - 273.15
        t_min  = p["temperature_2m_min"]  - 273.15
        t_dew  = p["dewpoint_temperature_2m"] - 273.15
        precip = p["total_precipitation_sum"] * 1000
        rad    = p["surface_solar_radiation_downwards_sum"] / 1e6
        et_era = abs(p.get("total_evaporation_sum", 0) or 0) * 1000
        viento = math.sqrt(
            (p.get("u_component_of_wind_10m") or 0) ** 2 +
            (p.get("v_component_of_wind_10m") or 0) ** 2
        )
        registros.append({
            "fecha":  pd.to_datetime(p["fecha"]),
            "t_max":  t_max,
            "t_min":  t_min,
            "t_med":  (t_max + t_min) / 2,
            "t_dew":  t_dew,
            "precip": max(precip, 0),
            "rad":    max(rad, 0),
            "viento": viento,
            "et_era": et_era,
        })

    df = pd.DataFrame(registros).set_index("fecha")
    return df.to_json()


# ════════════════════════════════════════════════════════════
# CHIRPS — SERIE DIARIA PARA UN LOTE
# ════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def descargar_chirps_serie(aoi_json: str, fecha_inicio: str, fecha_fin: str) -> str:
    """
    Descarga serie diaria de precipitación CHIRPS para un polígono.
    Retorna JSON del DataFrame.
    """
    geom = ee.Geometry(json.loads(aoi_json))

    col = (ee.ImageCollection(CHIRPS_COLLECTION)
           .filterBounds(geom)
           .filterDate(fecha_inicio, fecha_fin)
           .select("precipitation"))

    def extract(img):
        stats = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=5566,     # ~0.05° resolución CHIRPS
            maxPixels=1e9,
        )
        return ee.Feature(None, {
            "fecha":  ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"),
            "precip": stats.get("precipitation"),
        })

    features = (ee.FeatureCollection(col.map(extract))
                .sort("fecha")
                .getInfo()["features"])

    registros = [
        {"fecha": pd.to_datetime(f["properties"]["fecha"]),
         "precip_chirps": max(f["properties"].get("precip") or 0, 0)}
        for f in features
        if f["properties"].get("precip") is not None
    ]
    df = pd.DataFrame(registros).set_index("fecha")
    return df.to_json()


# ════════════════════════════════════════════════════════════
# MAPAS TEMÁTICOS — TILES URL para Folium
# ════════════════════════════════════════════════════════════

def _get_tile_url(image: ee.Image, vis_params: dict) -> str:
    """Genera URL de tiles de una ee.Image para usar en Folium."""
    map_id = image.getMapId(vis_params)
    return map_id["tile_fetcher"].url_format


@st.cache_data(show_spinner=False)
def mapa_anomalia_chirps(
    aoi_json: str,
    fecha_inicio: str,
    fecha_fin: str,
    anios_baseline: int = CHIRPS_BASELINE_YEARS,
) -> dict:
    """
    Calcula anomalía de precipitación CHIRPS respecto al promedio histórico.

    Lógica:
    - Recorta el período analizado a máximo 1 año (el más reciente).
    - Para cada uno de los N años del baseline, suma CHIRPS en el mismo
      rango de días del año (mismo mes/día inicio → mismo mes/día fin).
    - Anomalía = suma actual − promedio de las sumas históricas.

    Así siempre se comparan acumulados del mismo largo temporal.
    """
    geom     = ee.Geometry(json.loads(aoi_json))
    fin_dt   = pd.to_datetime(fecha_fin)
    inicio_dt = pd.to_datetime(fecha_inicio)

    # ── Acotar el período actual a máximo 365 días ──────────
    # Si el usuario eligió 5 años de análisis, para la anomalía
    # usamos solo el último año completo disponible en CHIRPS.
    delta_dias = (fin_dt - inicio_dt).days
    if delta_dias > 365:
        inicio_dt = fin_dt - pd.Timedelta(days=365)
        delta_dias = 365

    f_actual_ini = inicio_dt.strftime("%Y-%m-%d")
    f_actual_fin = fin_dt.strftime("%Y-%m-%d")

    # ── Precipitación del período actual ─────────────────────
    precip_actual = (ee.ImageCollection(CHIRPS_COLLECTION)
                     .filterBounds(geom)
                     .filterDate(f_actual_ini, f_actual_fin)
                     .select("precipitation")
                     .sum())

    # ── Baseline: mismo rango mes/día, en los N años anteriores ──
    # Año del que arranca el baseline (el año inmediatamente anterior al actual)
    anio_ref = inicio_dt.year - 1

    def suma_anio_equivalente(offset: int) -> ee.Image:
        """Suma CHIRPS para el mismo rango mes-día, desplazado `offset` años atrás."""
        anio   = anio_ref - offset
        f_ini  = f"{anio}-{inicio_dt.month:02d}-{inicio_dt.day:02d}"
        f_fin  = (pd.Timestamp(f_ini) + pd.Timedelta(days=delta_dias)).strftime("%Y-%m-%d")
        return (ee.ImageCollection(CHIRPS_COLLECTION)
                .filterBounds(geom)
                .filterDate(f_ini, f_fin)
                .select("precipitation")
                .sum()
                .set("anio", anio))

    imagenes_hist = [suma_anio_equivalente(i) for i in range(anios_baseline)]
    col_hist      = ee.ImageCollection(imagenes_hist)
    promedio_hist = col_hist.mean()

    # ── Anomalía absoluta (mm) ──
    anomalia = precip_actual.subtract(promedio_hist).rename("anomalia")

    # ── Anomalía porcentual ──
    anomalia_pct = (anomalia
                    .divide(promedio_hist.add(1e-6))
                    .multiply(100)
                    .rename("anomalia_pct"))

    # ── Vis params ──
    vis = {
        "min": -200, "max": 200,
        "palette": PALETA_ANOMALIA,
    }
    vis_pct = {
        "min": -100, "max": 100,
        "palette": PALETA_ANOMALIA,
    }

    # ── Estadísticas zonales ──
    stats = anomalia.reduceRegion(
        reducer=ee.Reducer.mean()
                           .combine(ee.Reducer.min(), sharedInputs=True)
                           .combine(ee.Reducer.max(), sharedInputs=True),
        geometry=geom,
        scale=5566,
        maxPixels=1e9,
    ).getInfo()

    stats_pct = anomalia_pct.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom,
        scale=5566,
        maxPixels=1e9,
    ).getInfo()

    return {
        "tile_url":     _get_tile_url(anomalia, vis),
        "tile_url_pct": _get_tile_url(anomalia_pct, vis_pct),
        "anomalia_mm":  stats.get("anomalia_mean", 0) or 0,
        "anomalia_min": stats.get("anomalia_min",  0) or 0,
        "anomalia_max": stats.get("anomalia_max",  0) or 0,
        "anomalia_pct": stats_pct.get("anomalia_pct_mean", 0) or 0,
        "precip_actual_mm": (precip_actual.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geom, scale=5566, maxPixels=1e9,
        ).getInfo().get("precipitation") or 0),
        "precip_hist_mm": (promedio_hist.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geom, scale=5566, maxPixels=1e9,
        ).getInfo().get("precipitation") or 0),
        "vis_min": -200, "vis_max": 200,
        "palette": PALETA_ANOMALIA,
    }


@st.cache_data(show_spinner=False)
def mapa_balance_hidrico(
    aoi_json: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> dict:
    """
    Balance hídrico espacial: CHIRPS precip - ETo estimada desde ERA5.
    ETo simplificada (Hargreaves-Samani) para cálculo raster píxel a píxel.
    """
    geom = ee.Geometry(json.loads(aoi_json))

    # ── CHIRPS: precipitación acumulada ──
    chirps = (ee.ImageCollection(CHIRPS_COLLECTION)
              .filterBounds(geom)
              .filterDate(fecha_inicio, fecha_fin)
              .select("precipitation")
              .sum())

    # ── ERA5: ETo Hargreaves-Samani (raster) ──
    era5 = (ee.ImageCollection(ERA5_COLLECTION)
            .filterBounds(geom)
            .filterDate(fecha_inicio, fecha_fin)
            .select(["temperature_2m_max", "temperature_2m_min",
                     "surface_solar_radiation_downwards_sum"]))

    def eto_hargreaves(img):
        tmax = img.select("temperature_2m_max").subtract(273.15)
        tmin = img.select("temperature_2m_min").subtract(273.15)
        tmed = tmax.add(tmin).divide(2)
        ra   = img.select("surface_solar_radiation_downwards_sum").divide(1e6)  # MJ/m²
        # Hargreaves-Samani: ETo = 0.0023 * (Tmed + 17.8) * (Tmax - Tmin)^0.5 * Ra * 0.408
        td   = tmax.subtract(tmin).max(ee.Image(0))
        eto  = (tmed.add(17.8)
                .multiply(td.sqrt())
                .multiply(ra)
                .multiply(0.0023 * 0.408)
                .max(ee.Image(0))
                .rename("eto"))
        return eto

    eto_col = era5.map(eto_hargreaves)
    eto_sum = eto_col.sum()

    # ── Balance = P - ETo ──
    # Reproyectar ETo a resolución CHIRPS (5km) para la resta
    eto_reproj = eto_sum.reproject(crs="EPSG:4326", scale=5566)
    balance = chirps.subtract(eto_reproj).rename("balance")

    vis_balance = {
        "min": -400, "max": 400,
        "palette": PALETA_BALANCE,
    }
    vis_chirps = {
        "min": 0, "max": 800,
        "palette": PALETA_PRECIPITACION,
    }
    vis_eto = {
        "min": 0, "max": 800,
        "palette": PALETA_TEMPERATURA[::-1],
    }

    stats = balance.reduceRegion(
        reducer=ee.Reducer.mean()
                           .combine(ee.Reducer.min(), sharedInputs=True)
                           .combine(ee.Reducer.max(), sharedInputs=True),
        geometry=geom, scale=5566, maxPixels=1e9,
    ).getInfo()

    chirps_stat = chirps.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=5566, maxPixels=1e9,
    ).getInfo()

    eto_stat = eto_sum.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=11132, maxPixels=1e9,
    ).getInfo()

    return {
        "tile_url_balance": _get_tile_url(balance,  vis_balance),
        "tile_url_chirps":  _get_tile_url(chirps,   vis_chirps),
        "tile_url_eto":     _get_tile_url(eto_sum,  vis_eto),
        "balance_mean": stats.get("balance_mean", 0) or 0,
        "balance_min":  stats.get("balance_min",  0) or 0,
        "balance_max":  stats.get("balance_max",  0) or 0,
        "precip_mean":  chirps_stat.get("precipitation", 0) or 0,
        "eto_mean":     eto_stat.get("eto", 0) or 0,
        "vis_min": -400, "vis_max": 400,
        "palette": PALETA_BALANCE,
    }


@st.cache_data(show_spinner=False)
def mapa_riesgo_termico(
    aoi_json: str,
    fecha_inicio: str,
    fecha_fin: str,
    t_helada: float = 3.0,
    t_calor: float  = 35.0,
) -> dict:
    """
    Conteo de días con riesgo de helada (Tmin < t_helada) y
    estrés térmico (Tmax > t_calor) por píxel ERA5.
    """
    geom = ee.Geometry(json.loads(aoi_json))

    era5 = (ee.ImageCollection(ERA5_COLLECTION)
            .filterBounds(geom)
            .filterDate(fecha_inicio, fecha_fin)
            .select(["temperature_2m_max", "temperature_2m_min"]))

    def flag_helada(img):
        tmin = img.select("temperature_2m_min").subtract(273.15)
        return tmin.lt(t_helada).rename("helada")

    def flag_calor(img):
        tmax = img.select("temperature_2m_max").subtract(273.15)
        return tmax.gt(t_calor).rename("calor")

    dias_helada = era5.map(flag_helada).sum().rename("dias_helada")
    dias_calor  = era5.map(flag_calor).sum().rename("dias_calor")

    # Total de días del período para normalizar
    n_dias = (ee.ImageCollection(ERA5_COLLECTION)
              .filterBounds(geom)
              .filterDate(fecha_inicio, fecha_fin)
              .size().getInfo()) or 1

    vis_helada = {"min": 0, "max": max(n_dias * 0.3, 10), "palette": PALETA_HELADAS}
    vis_calor  = {"min": 0, "max": max(n_dias * 0.3, 10), "palette": PALETA_CALOR}

    stats_h = dias_helada.reduceRegion(
        reducer=ee.Reducer.mean()
                           .combine(ee.Reducer.max(), sharedInputs=True),
        geometry=geom, scale=11132, maxPixels=1e9,
    ).getInfo()

    stats_c = dias_calor.reduceRegion(
        reducer=ee.Reducer.mean()
                           .combine(ee.Reducer.max(), sharedInputs=True),
        geometry=geom, scale=11132, maxPixels=1e9,
    ).getInfo()

    return {
        "tile_url_helada": _get_tile_url(dias_helada, vis_helada),
        "tile_url_calor":  _get_tile_url(dias_calor,  vis_calor),
        "helada_dias_mean": stats_h.get("dias_helada_mean", 0) or 0,
        "helada_dias_max":  stats_h.get("dias_helada_max",  0) or 0,
        "calor_dias_mean":  stats_c.get("dias_calor_mean",  0) or 0,
        "calor_dias_max":   stats_c.get("dias_calor_max",   0) or 0,
        "n_dias_total": n_dias,
        "t_helada": t_helada,
        "t_calor":  t_calor,
        "vis_helada": vis_helada,
        "vis_calor":  vis_calor,
        "palette_helada": PALETA_HELADAS,
        "palette_calor":  PALETA_CALOR,
    }
