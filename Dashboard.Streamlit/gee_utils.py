# ============================================================
# gee_utils.py — Utilidades para Google Earth Engine
# ============================================================
import ee
import pandas as pd
from config import ERA5_COLLECTION, ERA5_SCALE, ERA5_BANDS, HIST_YEARS


def inicializar_gee(project: str) -> None:
    """Inicializa GEE con manejo de autenticación automático."""
    try:
        ee.Initialize(project=project)
        print("✅ Earth Engine inicializado.")
    except Exception:
        print("🔑 Autenticando Earth Engine...")
        ee.Authenticate()
        ee.Initialize(project=project)
        print("✅ Earth Engine inicializado.")


def obtener_fecha_maxima(coleccion: ee.ImageCollection) -> str:
    """Retorna la fecha de la imagen más reciente disponible en el catálogo."""
    ultima = coleccion.sort("system:time_start", False).first()
    return ultima.date().format("YYYY-MM-dd").getInfo()


def calcular_periodos(fecha_max_str: str, hist_years: int = HIST_YEARS):
    """
    Calcula los periodos de análisis a partir de la fecha más reciente.

    Returns:
        hist_start (str), hist_end (str), daily_start (str), daily_end (str)
    """
    fecha_fin    = pd.to_datetime(fecha_max_str)
    hist_start   = (fecha_fin - pd.DateOffset(years=hist_years)).replace(day=1).strftime("%Y-%m-%d")
    hist_end     = fecha_max_str
    daily_start  = fecha_fin.replace(day=1).strftime("%Y-%m-%d")
    daily_end    = fecha_max_str
    return hist_start, hist_end, daily_start, daily_end


def _extraer_feature(img: ee.Image, geometry: ee.Geometry) -> ee.Feature:
    """
    Función mapeada sobre la colección ERA5.
    Extrae todas las bandas relevantes y aplica conversiones de unidades.
    """
    fecha   = img.date().format("YYYY-MM-dd")
    valores = img.select(ERA5_BANDS).reduceRegion(
        reducer    = ee.Reducer.mean(),   # Media sobre el área del lote (no centroide)
        geometry   = geometry,
        scale      = ERA5_SCALE,          # Resolución nativa ERA5-Land (~9 km)
        maxPixels  = 1e8,
        bestEffort = True,
    )

    def get(band):
        return ee.Number(valores.get(band))

    # Conversiones de unidades
    t_max    = get("temperature_2m_max").subtract(273.15)                  # K → °C
    t_min    = get("temperature_2m_min").subtract(273.15)                  # K → °C
    t_med    = get("temperature_2m").subtract(273.15)                      # K → °C
    t_dp     = get("dewpoint_temperature_2m").subtract(273.15)             # K → °C (punto de rocío)
    precip   = get("total_precipitation_sum").multiply(1000)               # m → mm
    rad      = get("surface_solar_radiation_downwards_sum").divide(1e6)    # J/m² → MJ/m²
    u_wind   = get("u_component_of_wind_10m")                              # m/s
    v_wind   = get("v_component_of_wind_10m")                              # m/s
    et_veg   = get("evaporation_from_vegetation_transpiration_sum").multiply(1000)  # m → mm

    return ee.Feature(None, {
        "fecha"  : fecha,
        "t_max"  : t_max,
        "t_min"  : t_min,
        "t_med"  : t_med,
        "t_dp"   : t_dp,
        "precip" : precip,
        "rad"    : rad,
        "u_wind" : u_wind,
        "v_wind" : v_wind,
        "et_veg" : et_veg,
    })


def descargar_serie(lote_geom: ee.Geometry, hist_start: str, hist_end: str) -> pd.DataFrame:
    """
    Descarga la serie temporal ERA5 para el área del lote.

    Args:
        lote_geom:  Geometría ee.Geometry del lote (se usa el área completa, no el centroide)
        hist_start: Fecha de inicio 'YYYY-MM-DD'
        hist_end:   Fecha de fin   'YYYY-MM-DD'

    Returns:
        DataFrame con columnas: fecha, t_max, t_min, t_med, t_dp,
                                precip, rad, u_wind, v_wind, et_veg
    """
    print("📡 Descargando serie temporal ERA5-Land (20-40 seg aprox.)...")

    era5 = (
        ee.ImageCollection(ERA5_COLLECTION)
        .filterBounds(lote_geom)
        .filterDate(hist_start, ee.Date(hist_end).advance(1, "day"))
        .select(ERA5_BANDS)
    )

    try:
        features = (
            era5
            .map(lambda img: _extraer_feature(img, lote_geom))
            .filter(ee.Filter.notNull(ERA5_BANDS))
            .getInfo()["features"]
        )
    except ee.EEException as e:
        raise RuntimeError(f"❌ Error al consultar GEE: {e}")

    df = pd.DataFrame([f["properties"] for f in features])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.sort_values("fecha").reset_index(drop=True)

    print(f"✅ {len(df)} días descargados ({hist_start} → {hist_end})")
    return df
