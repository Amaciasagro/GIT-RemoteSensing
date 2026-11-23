"""Climate module (Climate_analyzer): CHIRPS + ERA5-Land — metrics, events, clean YYYY-MM-DD dates and interactive GDD threshold."""
import json

import numpy as np
import pandas as pd
import streamlit as st

from ..config import tarjeta
from ..core import state, export, charts
from ..services import gee


# ── Pure calculations (no Streamlit) ───────────────────────────────────────────
def serie_precip(df, fuente):
    """Precipitation column according to the chosen source."""
    if fuente == "CHIRPS":
        return df["p_chirps"]
    if fuente == "ERA5-Land":
        return df["p_era5"]
    return df["p_chirps"].fillna(df["p_era5"])          # CHIRPS with ERA5 gap-fill


def racha_seca(p, umbral):
    """Longest run of consecutive days with P < threshold."""
    mejor = act = 0
    for v in (p < umbral).to_numpy():
        act = act + 1 if v else 0
        mejor = max(mejor, act)
    return mejor


def detectar_eventos(df, umbral_dia, hueco, min_total):
    """Groups rainy days (P ≥ threshold) separated by ≤ `hueco` (gap) dry days; filters by minimum total."""
    p = df["p_precip"]
    idx = np.flatnonzero((p >= umbral_dia).to_numpy())
    cols = ["inicio", "fin", "dias", "total_mm", "max_dia_mm", "fecha_max"]
    if idx.size == 0:
        return pd.DataFrame(columns=cols)
    filas = []
    for g in np.split(idx, np.where(np.diff(idx) > hueco + 1)[0] + 1):
        sub = df.iloc[g[0]:g[-1] + 1]
        ps = sub["p_precip"].fillna(0)
        filas.append(dict(inicio=sub["fecha"].iloc[0], fin=sub["fecha"].iloc[-1], dias=len(sub),
                          total_mm=ps.sum(), max_dia_mm=ps.max(), fecha_max=sub["fecha"].iloc[int(ps.to_numpy().argmax())]))
    ev = pd.DataFrame(filas, columns=cols)
    return ev[ev["total_mm"] >= min_total].sort_values("total_mm", ascending=False).reset_index(drop=True)


def metricas(w, umbral_dia, t_base):
    """Metrics for a window (DataFrame with p_precip, t_*, pet)."""
    p = w["p_precip"]
    t_med_gdd = ((w["t_max"] + w["t_min"]) / 2.0).fillna(w["t_media"])
    gdd = ((t_med_gdd - t_base).clip(lower=0)).sum(min_count=1)
    p3 = p.rolling(3, min_periods=3).sum()
    pet = w["pet"].sum(min_count=1)
    return dict(
        p_total=p.sum(min_count=1), dias_lluvia=int((p >= umbral_dia).sum()),
        p_max=p.max(), fecha_pmax=w["fecha"].loc[p.idxmax()] if p.notna().any() else None,
        p3_max=p3.max(), racha=racha_seca(p, umbral_dia),
        t_media=w["t_media"].mean(), t_min=w["t_min"].min(), t_max=w["t_max"].max(),
        gdd=gdd, pet=pet, balance=(p.sum(min_count=1) - pet) if pd.notna(pet) else np.nan)


def resumen_mensual(df):
    d = df.copy()
    d["mes"] = pd.to_datetime(d["fecha"]).dt.strftime("%Y-%m")
    return (d.groupby("mes").agg(p_chirps=("p_chirps", lambda s: s.sum(min_count=1)),
                                 p_era5=("p_era5", lambda s: s.sum(min_count=1)),
                                 t_media=("t_media", "mean"), pet=("pet", lambda s: s.sum(min_count=1)))
            .reset_index().round(2))


def calidad(df, f_fin):
    """Per-variable availability summary (with clean YYYY-MM-DD date, no latency notices)."""
    filas, avisos = [], []
    for col, nom in (("p_chirps", "P CHIRPS"), ("p_era5", "P ERA5-Land"), ("t_media", "Mean T ERA5-Land"),
                     ("pet", "PET ERA5-Land"), ("swvl1", "ERA5-Land soil moisture")):
        v = df[col].dropna()
        ult_f = pd.to_datetime(df.loc[v.index[-1], "fecha"]).strftime("%Y-%m-%d") if len(v) else "—"
        filas.append(dict(variable=nom, dias_con_dato=len(v), faltantes_pct=round(100 * (1 - len(v) / len(df)), 1),
                          ultima_fecha=ult_f))
        if not len(v):
            avisos.append(f"{nom}: no data in the range.")
    return pd.DataFrame(filas), avisos


def limpiar_fechas_tabla(df_in, cols_fecha=("fecha", "inicio", "fin", "fecha_max", "ultima_fecha")):
    """Formats all date columns to YYYY-MM-DD, removing any 00:00:00 time part."""
    out = df_in.copy()
    for c in cols_fecha:
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d").fillna("—")
    if isinstance(out.index, pd.DatetimeIndex):
        out.index = out.index.strftime("%Y-%m-%d")
    return out


# ── Interface ────────────────────────────────────────────────────────────────
def _cards(items):
    for c, it in zip(st.columns(len(items)), items):
        c.markdown(tarjeta(*it), unsafe_allow_html=True)


def _f(v, fmt="{:.0f}"):
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else fmt.format(v)


def render(ctx):
    st.subheader("🌦️ Climate · CHIRPS + ERA5-Land")
    aoi, rango = ctx["aoi"], ctx["rango"]
    if aoi is None or rango is None:
        st.info("Define an AOI and a valid date range in the sidebar.")
        return
    if not ctx["gee_ok"]:
        st.error("Google Earth Engine is not connected: this module is not available.")
        return
    f_ini, f_fin = rango
    firma = state.firma(aoi["id"], f_ini, f_fin)
    df, vigente = state.obtener("clima", firma)
    if df is None or not vigente:
        with st.spinner("Automatically downloading daily CHIRPS and ERA5-Land series…"):
            try:
                df = gee.serie_clima(json.dumps(aoi["geom"]), aoi["lon"], aoi["lat"], aoi["area_ha"] > 3000, f_ini, f_fin)
                state.guardar("clima", df, firma)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not query the climate: {e}")
                return

    # Clean main controls: Precipitation Source and integer text box for GDD Threshold
    c_p1, c_p2 = st.columns([1.6, 1.4])
    fuente = c_p1.selectbox("Precipitation source (PP)", ["CHIRPS (ERA5 gap-fill)", "CHIRPS", "ERA5-Land"], key="clim_fuente_p")
    t_base = int(c_p2.number_input(
        "🌡️ GDD threshold / T base (°C, integer value)",
        min_value=-10, max_value=40, value=10, step=1, format="%d",
        key="clim_t_base_gdd_int",
        help="Enter an integer base temperature (°C) for the Growing-Degree-Day (GDD) calculation and its threshold line in the chart.",
    ))
    umbral = 1.0
    hueco = 1
    min_total = 10

    df = df.copy()
    df["p_precip"] = serie_precip(df, "CHIRPS" if fuente == "CHIRPS" else "ERA5-Land" if fuente == "ERA5-Land" else "mix")
    q, avisos = calidad(df, f_fin)
    for a in avisos:
        st.warning(a)
    if df["p_precip"].notna().sum() == 0:
        st.error("No precipitation available with the chosen source in this range.")
        return

    eventos = detectar_eventos(df, umbral, hueco, min_total)
    modo = st.radio("Analysis window", ["Entire range", "Detected event", "Sub-range"], horizontal=True)
    v_ini, v_fin = df["fecha"].iloc[0], df["fecha"].iloc[-1]
    if modo == "Detected event":
        if eventos.empty:
            st.info("No events detected with these parameters; showing the entire range.")
        else:
            etiquetas = [f"{pd.to_datetime(r.inicio):%Y-%m-%d} → {pd.to_datetime(r.fin):%Y-%m-%d} · {r.total_mm:.0f} mm ({r.dias} d)" for r in eventos.itertuples()]
            k = st.selectbox("Event (sorted by total)", range(len(etiquetas)), format_func=lambda i: etiquetas[i])
            v_ini, v_fin = eventos.loc[k, "inicio"], eventos.loc[k, "fin"]
    elif modo == "Sub-range":
        r = st.date_input("Sub-range", value=(v_ini.date(), v_fin.date()), min_value=v_ini.date(), max_value=v_fin.date())
        if isinstance(r, (tuple, list)) and len(r) == 2:
            v_ini, v_fin = pd.Timestamp(r[0]), pd.Timestamp(r[1])
    w = df[(df["fecha"] >= v_ini) & (df["fecha"] <= v_fin)]
    m = metricas(w, umbral, t_base)
    st.caption(f"Window: {v_ini:%Y-%m-%d} → {v_fin:%Y-%m-%d} ({len(w)} days) · P: {fuente} · GDD threshold: {t_base:g} °C")
    _cards([("Total precipitation", _f(m["p_total"]), "mm", f"{m['dias_lluvia']} rainy days", "agua"),
            ("Max. daily", _f(m["p_max"]), "mm", f"{m['fecha_pmax']:%Y-%m-%d}" if m["fecha_pmax"] is not None else "", "alerta"),
            ("Max. 3 days", _f(m["p3_max"]), "mm", "rolling total", "agua"),
            ("Dry spell", f"{m['racha']}", "days", "consecutive days without rain", ""),
            ("P − PET balance", _f(m["balance"]), "mm", f"PET {_f(m['pet'])} mm", "suelo")])
    _cards([("Mean T", _f(m["t_media"], "{:.1f}"), "°C", "ERA5-Land", ""),
            ("Abs. min T", _f(m["t_min"], "{:.1f}"), "°C", "", ""),
            ("Abs. max T", _f(m["t_max"], "{:.1f}"), "°C", "", "alerta"),
            ("Growing degree days (GDD)", _f(m["gdd"]), "°C·d", f"Umbral base {t_base:g} °C", "suelo")])

    zoom = None
    plot = df
    if modo != "Entire range":
        plot = df[(df["fecha"] >= v_ini - pd.Timedelta(days=5)) & (df["fecha"] <= v_fin + pd.Timedelta(days=5))]
        zoom = (v_ini, v_fin)

    st.plotly_chart(charts.fig_clima(plot, zoom, t_base=t_base), use_container_width=True, key="plt_clima_combinado")

    t1, t2, t3, t4 = st.tabs(["📅 Daily (PP and Climate)", "🗓️ Monthly", "⛈️ PP events", "🩺 Data quality"])
    with t1:
        out = w.drop(columns=["swvl1"]).round(2).assign(swvl1=w["swvl1"].round(3))
        out = limpiar_fechas_tabla(out, cols_fecha=("fecha",))
        st.dataframe(out, use_container_width=True, hide_index=True)
        st.caption(
            "📖 **Glossary of variables:** "
            "**`p_chirps`**: daily CHIRPS precipitation (mm) · "
            "**`p_era5`**: daily ERA5-Land precipitation (mm) · "
            "**`p_precip`**: active daily precipitation according to the chosen source (mm) · "
            "**`t_media` / `t_min` / `t_max`**: daily mean, minimum and maximum temperature at 2 m (°C, ERA5-Land) · "
            "**`pet`**: daily potential evapotranspiration (*Potential Evapotranspiration*, mm/day, ERA5-Land) · "
            "**`swvl1`**: volumetric surface soil moisture 0–7 cm (*Soil Water Volumetric Layer 1*, m³ of water / m³ of soil)."
        )
        export.boton_csv(out, "clima_diario", "dl_clima_d")
        export.registrar("clima_diario", out)
    with t2:
        mm = resumen_mensual(w)
        st.plotly_chart(charts.fig_mensual(mm), use_container_width=True, key="plt_clima_mensual")
        st.dataframe(mm, use_container_width=True, hide_index=True)
        st.caption(
            "📖 **Glossary:** **`mes`**: year-month (`YYYY-MM`) · **`p_chirps` / `p_era5`**: monthly cumulative rainfall (mm) · "
            "**`t_media`**: monthly mean temperature (°C) · **`pet`**: monthly cumulative potential evapotranspiration (mm)."
        )
        export.boton_csv(mm, "clima_mensual", "dl_clima_m")
        export.registrar("clima_mensual", mm)
    with t3:
        if eventos.empty:
            st.info("No events with the current criteria.")
        else:
            ev = limpiar_fechas_tabla(eventos.round(1), cols_fecha=("inicio", "fin", "fecha_max"))
            st.dataframe(ev, use_container_width=True, hide_index=True)
            st.caption(
                "📖 **Glossary:** **`inicio` / `fin`**: storm start and end dates · "
                "**`dias`**: event duration in days · **`total_mm`**: cumulative rainfall of the event (mm) · "
                "**`max_dia_mm`**: precipitation of the rainiest day of the event (mm) · **`fecha_max`**: date of the daily peak."
            )
            export.boton_csv(ev, "clima_eventos", "dl_clima_e")
            export.registrar("clima_eventos", ev)
    with t4:
        q_clean = limpiar_fechas_tabla(q, cols_fecha=("ultima_fecha",))
        st.dataframe(q_clean, use_container_width=True, hide_index=True)
        st.caption(
            "📖 **Glossary:** **`variable`**: climate series evaluated · **`dias_con_dato`**: number of days with a valid record · "
            "**`faltantes_pct`**: percentage of days with no data available in the period (%) · **`ultima_fecha`**: date of the latest available record."
        )
        both = df[["p_chirps", "p_era5"]].dropna()
        if len(both) > 5:
            st.caption(f"CHIRPS vs ERA5-Land correlation (daily P): r = {both.corr().iloc[0, 1]:.2f} · n = {len(both)}")
