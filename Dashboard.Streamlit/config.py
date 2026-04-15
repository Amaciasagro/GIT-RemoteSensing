# ============================================================
# config.py — Parámetros globales del Climate Analyzer
# Editá este archivo antes de correr el notebook.
# ============================================================
import os

# --- Google Earth Engine ---
GEE_PROJECT = os.environ.get("GEE_PROJECT", "tu-proyecto-gee")  # Nunca hardcodear el ID

# --- Mapa inicial ---
CENTRO_LAT   = -27.46   # Corrientes, Argentina (ejemplo)
CENTRO_LON   = -58.83
ZOOM_INICIAL = 14

# --- Agronomía ---
T_BASE = 10.0  # °C — temperatura base para cálculo de GDA (maíz=10, soja=10, trigo=0)

# --- ERA5-Land ---
ERA5_COLLECTION = "ECMWF/ERA5_LAND/DAILY_AGGR"
ERA5_SCALE      = 9000   # Resolución nativa ERA5-Land (~9 km)
HIST_YEARS      = 3      # Años hacia atrás para el histórico

# --- Bandas ERA5-Land a extraer ---
ERA5_BANDS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m",
    "dewpoint_temperature_2m",
    "total_precipitation_sum",
    "surface_solar_radiation_downwards_sum",
    "u_component_of_wind_10m",
    "v_component_of_wind_10m",
    "evaporation_from_vegetation_transpiration_sum",
]
