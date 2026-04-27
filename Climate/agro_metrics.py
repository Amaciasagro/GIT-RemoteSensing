# ============================================================
# agro_metrics.py — Métricas agronómicas derivadas de ERA5
# ============================================================
"""
Módulo de cálculo de indicadores agronómicos:
  - ETo (Penman-Monteith FAO-56)
  - Grados Día Acumulados (GDA)
  - Balance Hídrico (lluvia acumulada - ETo acumulada)
  - Humedad Relativa estimada desde punto de rocío
"""

import numpy as np
import pandas as pd
from config import T_BASE


# ─────────────────────────────────────────────
# 1. ETo — Penman-Monteith FAO-56
# ─────────────────────────────────────────────

def calcular_eto_pm(df: pd.DataFrame, latitud_deg: float) -> pd.Series:
    """
    Calcula ETo diaria (mm/día) por Penman-Monteith FAO-56.

    Requiere columnas en df:
        t_max, t_min, t_med  (°C)
        t_dp                 (°C)  punto de rocío → HR
        rad                  (MJ/m²/día) radiación solar descendente
        u_wind, v_wind       (m/s) componentes del viento a 10 m

    Args:
        df:           DataFrame con datos diarios ERA5
        latitud_deg:  Latitud del lote en grados decimales

    Returns:
        Serie con ETo (mm/día)
    """
    T     = df["t_med"].values
    T_max = df["t_max"].values
    T_min = df["t_min"].values
    T_dp  = df["t_dp"].values
    Rs    = df["rad"].values                                   # MJ/m²/día

    # Velocidad del viento a 2 m (conversión desde 10 m, FAO-56 Ec. 47)
    u2 = np.sqrt(df["u_wind"].values**2 + df["v_wind"].values**2) * (4.87 / np.log(67.8 * 10 - 5.42))

    # Presión de vapor de saturación (kPa)
    e_sat = 0.6108 * np.exp(17.27 * T / (T + 237.3))
    e_max = 0.6108 * np.exp(17.27 * T_max / (T_max + 237.3))
    e_min = 0.6108 * np.exp(17.27 * T_min / (T_min + 237.3))
    es    = (e_max + e_min) / 2

    # Presión de vapor real desde punto de rocío
    ea = 0.6108 * np.exp(17.27 * T_dp / (T_dp + 237.3))

    # Déficit de presión de vapor (kPa)
    vpd = np.maximum(es - ea, 0)

    # Pendiente de la curva de saturación (kPa/°C)
    delta = 4098 * e_sat / (T + 237.3)**2

    # Presión atmosférica y constante psicrométrica (asume altitud = 0 m)
    P     = 101.3
    gamma = 0.000665 * P

    # Radiación neta estimada (Rn) — simplificada sin albedo dinámico
    # Radiación neta de onda corta
    alpha = 0.23   # albedo referencia pasto
    Rns   = (1 - alpha) * Rs

    # Radiación neta de onda larga (FAO-56 Ec. 39 simplificada)
    sigma  = 4.903e-9   # MJ/m²/día/K⁴
    T_K    = T + 273.16
    Rso    = (0.75 + 2e-5 * 0) * Rs   # Rso con altitud = 0
    Rso    = np.maximum(Rso, 0.1)
    Rs_Rso = np.clip(Rs / Rso, 0.3, 1.0)
    Rnl    = sigma * T_K**4 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * Rs_Rso - 0.35)
    Rn     = Rns - Rnl

    # Flujo de calor del suelo (G ≈ 0 para escala diaria)
    G = 0

    # ETo Penman-Monteith FAO-56
    num   = 0.408 * delta * (Rn - G) + gamma * (900 / (T + 273)) * u2 * vpd
    den   = delta + gamma * (1 + 0.34 * u2)
    eto   = num / den

    return pd.Series(np.maximum(eto, 0), index=df.index, name="eto")


# ─────────────────────────────────────────────
# 2. Grados Día Acumulados (GDA)
# ─────────────────────────────────────────────

def calcular_gda(df: pd.DataFrame, t_base: float = T_BASE) -> pd.Series:
    """
    Calcula grados día acumulados desde el inicio de la serie.

    GD_diario = max(((T_max + T_min) / 2) - T_base, 0)

    Args:
        df:     DataFrame con columnas t_max y t_min (°C)
        t_base: Temperatura base del cultivo (°C). Por defecto config.T_BASE

    Returns:
        Serie con GDA acumulados
    """
    gd = ((df["t_max"] + df["t_min"]) / 2 - t_base).clip(lower=0)
    return gd.cumsum().rename("gda")


# ─────────────────────────────────────────────
# 3. Humedad Relativa desde punto de rocío
# ─────────────────────────────────────────────

def calcular_hr(df: pd.DataFrame) -> pd.Series:
    """
    Estima HR (%) media diaria desde temperatura media y punto de rocío.

    HR = 100 × ea / es
    """
    ea = 0.6108 * np.exp(17.27 * df["t_dp"] / (df["t_dp"] + 237.3))
    es = 0.6108 * np.exp(17.27 * df["t_med"] / (df["t_med"] + 237.3))
    hr = (ea / es * 100).clip(0, 100)
    return hr.rename("hr")


# ─────────────────────────────────────────────
# 4. Agregación mensual completa
# ─────────────────────────────────────────────

def agregar_mensual(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega el DataFrame diario a resolución mensual.

    Incluye: precip, t_max, t_min, t_med, eto, hr, et_veg.

    Returns:
        DataFrame mensual con columna 'mes_año' como timestamp
    """
    df = df.copy()
    df["mes_año"] = df["fecha"].dt.to_period("M")

    agg = df.groupby("mes_año").agg(
        precip  = ("precip", "sum"),
        t_max   = ("t_max",  "mean"),
        t_min   = ("t_min",  "mean"),
        t_med   = ("t_med",  "mean"),
        eto     = ("eto",    "sum"),
        hr      = ("hr",     "mean"),
        et_veg  = ("et_veg", "sum"),
    ).reset_index()

    agg["mes_año"]       = agg["mes_año"].dt.to_timestamp()
    agg["balance_hidro"] = agg["precip"] - agg["eto"]   # Balance hídrico mensual
    return agg


# ─────────────────────────────────────────────
# 5. Procesamiento diario del mes actual
# ─────────────────────────────────────────────

def procesar_diario(df: pd.DataFrame, daily_start: str, daily_end: str) -> pd.DataFrame:
    """
    Filtra y enriquece el DataFrame para el análisis diario del mes actual.

    Agrega: precip_acum, eto_acum, balance_hidro_acum, gda.
    """
    mask = (df["fecha"] >= daily_start) & (df["fecha"] <= daily_end)
    dd   = df[mask].copy().sort_values("fecha").reset_index(drop=True)

    dd["precip_acum"]      = dd["precip"].cumsum()
    dd["eto_acum"]         = dd["eto"].cumsum()
    dd["balance_hidro_acum"] = dd["precip_acum"] - dd["eto_acum"]
    dd["gda"]              = ((dd["t_max"] + dd["t_min"]) / 2 - T_BASE).clip(lower=0).cumsum()
    return dd
