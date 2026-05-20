# ============================================================
# metrics.py — Métricas agronómicas sobre series temporales
# ============================================================

import pandas as pd
import numpy as np
import math


def calcular_hr(df: pd.DataFrame) -> pd.Series:
    """Humedad relativa estimada a partir del punto de rocío (%)."""
    es_t   = 0.6108 * np.exp(17.27 * df["t_med"] / (df["t_med"] + 237.3))
    es_dew = 0.6108 * np.exp(17.27 * df["t_dew"] / (df["t_dew"] + 237.3))
    return (es_dew / es_t * 100).clip(0, 100)


def calcular_eto_pm(df: pd.DataFrame, latitud: float) -> pd.Series:
    """
    ETo Penman-Monteith FAO-56 (mm/día).
    Allen et al. 1998, FAO Irrigation and Drainage Paper 56.
    """
    T    = df["t_med"]
    Tmax = df["t_max"]
    Tmin = df["t_min"]
    Rs   = df["rad"]
    u2   = df["viento"] * (4.87 / math.log(67.8 * 10 - 5.42))  # 10m → 2m
    Td   = df["t_dew"]

    es = 0.5 * (0.6108 * np.exp(17.27 * Tmax / (Tmax + 237.3)) +
                0.6108 * np.exp(17.27 * Tmin / (Tmin + 237.3)))
    ea = 0.6108 * np.exp(17.27 * Td / (Td + 237.3))

    doy     = df.index.dayofyear
    lat_rad = math.radians(abs(latitud))
    dr      = 1 + 0.033 * np.cos(2 * math.pi / 365 * doy)
    dec     = 0.409 * np.sin(2 * math.pi / 365 * doy - 1.39)
    ws      = np.arccos(-np.tan(lat_rad) * np.tan(dec))
    Ra      = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * np.sin(lat_rad) * np.sin(dec) +
        np.cos(lat_rad) * np.cos(dec) * np.sin(ws)
    )

    Rso = (0.75 + 2e-5 * 0) * Ra
    Rns = (1 - 0.23) * Rs
    Rnl = (4.903e-9 * ((Tmax + 273.16) ** 4 + (Tmin + 273.16) ** 4) / 2 *
           (0.34 - 0.14 * np.sqrt(ea)) *
           (1.35 * (Rs / np.maximum(Rso, 0.1)) - 0.35))
    Rn    = Rns - Rnl
    delta = 4098 * (0.6108 * np.exp(17.27 * T / (T + 237.3))) / (T + 237.3) ** 2
    gamma = 0.0665

    eto = (0.408 * delta * Rn + gamma * (900 / (T + 273)) * u2 * (es - ea)) / (
        delta + gamma * (1 + 0.34 * u2)
    )
    return eto.clip(lower=0)


def agregar_mensual(df: pd.DataFrame, t_base: float = 10.0) -> pd.DataFrame:
    """Agrega la serie diaria ERA5 a nivel mensual con métricas agronómicas."""
    df = df.copy()
    df["eto"] = calcular_eto_pm(df, df.attrs.get("latitud", -30))
    df["hr"]  = calcular_hr(df)
    df["gda"] = (df["t_med"] - t_base).clip(lower=0)

    mensual = df.resample("MS").agg(
        precip   = ("precip",  "sum"),
        t_max    = ("t_max",   "mean"),
        t_min    = ("t_min",   "mean"),
        t_med    = ("t_med",   "mean"),
        hr       = ("hr",      "mean"),
        rad      = ("rad",     "sum"),
        viento   = ("viento",  "mean"),
        et_era   = ("et_era",  "sum"),
        eto      = ("eto",     "sum"),
        gda      = ("gda",     "sum"),
    ).dropna(subset=["precip"])

    mensual["balance_hidro"] = mensual["precip"] - mensual["eto"]
    mensual["mes_año"]       = mensual.index
    return mensual


def procesar_diario(df: pd.DataFrame, inicio: str, fin: str,
                    t_base: float = 10.0) -> pd.DataFrame:
    """Retorna el detalle diario del período solicitado con métricas acumuladas."""
    df = df.copy()
    df["eto"] = calcular_eto_pm(df, df.attrs.get("latitud", -30))
    df["hr"]  = calcular_hr(df)
    df["gda"] = (df["t_med"] - t_base).clip(lower=0)

    sub = df.loc[inicio:fin].copy()
    sub["precip_acum"]  = sub["precip"].cumsum()
    sub["eto_acum"]     = sub["eto"].cumsum()
    sub["balance_acum"] = sub["precip_acum"] - sub["eto_acum"]
    sub["gda_acum"]     = sub["gda"].cumsum()
    return sub


def resumen_comparativo(lotes_data: dict, t_base: float = 10.0) -> pd.DataFrame:
    """
    Genera tabla comparativa de métricas agregadas para N lotes.
    lotes_data: {nombre_lote: datos_json_str}
    """
    import io
    filas = []
    for nombre, datos_json in lotes_data.items():
        df = pd.read_json(io.StringIO(datos_json))
        df.index = pd.to_datetime(df.index, unit="ms")
        df.attrs["latitud"] = -30  # fallback
        men = agregar_mensual(df, t_base)
        filas.append({
            "Lote":       nombre,
            "Lluvia mm":  men["precip"].sum(),
            "ETo mm":     men["eto"].sum(),
            "Balance mm": men["balance_hidro"].sum(),
            "T°C media":  men["t_med"].mean(),
            "HR% media":  men["hr"].mean(),
            "GDA total":  men["gda"].sum(),
            "Rad MJ/m²":  men["rad"].sum(),
        })
    return pd.DataFrame(filas).set_index("Lote")
