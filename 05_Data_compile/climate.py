"""Climate module (Climate_analyzer): CHIRPS + ERA5-Land — metrics, events and time ranges."""
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
    gdd = (((w["t_max"] + w["t_min"]) / 2 - t_base).clip(lower=0)).sum(min_count=1)
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
    d["mes"] = d["fecha"].dt.strftime("%Y-%m")
    return (d.groupby("mes").agg(p_chirps=("p_chirps", lambda s: s.sum(min_count=1)),
                                 p_era5=("p_era5", lambda s: s.sum(min_count=1)),
                                 t_media=("t_media", "mean"), pet=("pet", lambda s: s.sum(min_count=1)))
            .reset_index().round(2))


def calidad(df, f_fin):
    """Per-variable availability summary and latency notices."""
    filas, avisos = [], []
    for col, nom in (("p_chirps", "P CHIRPS"), ("p_era5", "P ERA5-Land"), ("t_media", "Mean T ERA5-Land"),
                     ("pet", "PET ERA5-Land"), ("swvl1", "ERA5-Land soil moisture")):
        v = df[col].dropna()
        filas.append(dict(variable=nom, dias_con_dato=len(v), faltantes_pct=round(100 * (1 - len(v) / len(df)), 1),
                          ultima_fecha=df.loc[v.index[-1], "fecha"].date() if len(v) else None))
        if len(v) and df.loc[v.index[-1], "fecha"] < pd.Timestamp(f_fin) - pd.Timedelta(days=2):
            avisos.append(f"{nom}: last data on {df.loc[v.index[-1], 'fecha'].date()} (product latency).")
        if not len(v):
            avisos.append(f"{nom}: no data in the range.")
    return pd.DataFrame(filas), avisos


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
    if st.button("🔎 Query climate", type="primary", key="clima_btn"):
        with st.spinner("Downloading daily CHIRPS and ERA5-Land series…"):
            try:
                df = gee.serie_clima(json.dumps(aoi["geom"]), aoi["lon"], aoi["lat"], aoi["area_ha"] > 3000, f_ini, f_fin)
                state.guardar("clima", df, firma)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not query the climate: {e}")
                return
    df, vigente = state.obtener("clima", firma)
    if df is None:
        st.info("Press **Query climate** to download the data for the AOI and the chosen range.")
        return
    if not vigente:
        st.warning("The AOI or range changed since the last query: query again.")

    with st.expander("⚙️ Analysis parameters", expanded=False):
        c = st.columns(4)
        fuente = c[0].selectbox("P source", ["CHIRPS (ERA5 gap-fill)", "CHIRPS", "ERA5-Land"])
        umbral = c[1].number_input("Rainy day ≥ (mm)", 0.1, 20.0, 1.0, 0.5)
        t_base = c[2].number_input("T base GDD (°C)", 0.0, 20.0, 10.0, 0.5)
        hueco = c[3].number_input("Gap between events (days)", 0, 7, 1)
        min_total = st.slider("Event: minimum total (mm)", 1, 100, 10)
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
            etiquetas = [f"{r.inicio:%d-%b-%Y} → {r.fin:%d-%b-%Y} · {r.total_mm:.0f} mm ({r.dias} d)" for r in eventos.itertuples()]
            k = st.selectbox("Event (sorted by total)", range(len(etiquetas)), format_func=lambda i: etiquetas[i])
            v_ini, v_fin = eventos.loc[k, "inicio"], eventos.loc[k, "fin"]
    elif modo == "Sub-range":
        r = st.date_input("Sub-range", value=(v_ini.date(), v_fin.date()), min_value=v_ini.date(), max_value=v_fin.date())
        if isinstance(r, (tuple, list)) and len(r) == 2:
            v_ini, v_fin = pd.Timestamp(r[0]), pd.Timestamp(r[1])
    w = df[(df["fecha"] >= v_ini) & (df["fecha"] <= v_fin)]
    m = metricas(w, umbral, t_base)
    st.caption(f"Window: {v_ini:%d-%b-%Y} → {v_fin:%d-%b-%Y} ({len(w)} days) · P: {fuente}")
    _cards([("Total precipitation", _f(m["p_total"]), "mm", f"{m['dias_lluvia']} days ≥ {umbral:g} mm", "agua"),
            ("Max. daily", _f(m["p_max"]), "mm", f"{m['fecha_pmax']:%d-%b}" if m["fecha_pmax"] is not None else "", "alerta"),
            ("Max. 3 days", _f(m["p3_max"]), "mm", "rolling total", "agua"),
            ("Dry spell", f"{m['racha']}", "days", f"P < {umbral:g} mm", ""),
            ("P − PET balance", _f(m["balance"]), "mm", f"PET {_f(m['pet'])} mm", "suelo")])
    _cards([("Mean T", _f(m["t_media"], "{:.1f}"), "°C", "ERA5-Land", ""),
            ("Abs. min T", _f(m["t_min"], "{:.1f}"), "°C", "", ""),
            ("Abs. max T", _f(m["t_max"], "{:.1f}"), "°C", "", "alerta"),
            ("Growing degree days (GDD)", _f(m["gdd"]), "°C·d", f"base {t_base:g} °C", "suelo")])

    zoom = None
    plot = df
    if modo != "Entire range":
        plot = df[(df["fecha"] >= v_ini - pd.Timedelta(days=5)) & (df["fecha"] <= v_fin + pd.Timedelta(days=5))]
        zoom = (v_ini, v_fin)
    st.plotly_chart(charts.fig_clima(plot, zoom), use_container_width=True)

    t1, t2, t3, t4 = st.tabs(["📅 Daily", "🗓️ Monthly", "⛈️ Events", "🩺 Data quality"])
    with t1:
        out = w.drop(columns=["swvl1"]).round(2).assign(swvl1=w["swvl1"].round(3))
        st.dataframe(out, use_container_width=True, hide_index=True)
        export.boton_csv(out, "clima_diario", "dl_clima_d")
        export.registrar("clima_diario", out)
    with t2:
        mm = resumen_mensual(w)
        st.plotly_chart(charts.fig_mensual(mm), use_container_width=True)
        st.dataframe(mm, use_container_width=True, hide_index=True)
        export.boton_csv(mm, "clima_mensual", "dl_clima_m")
        export.registrar("clima_mensual", mm)
    with t3:
        if eventos.empty:
            st.info("No events with the current criteria.")
        else:
            ev = eventos.round(1)
            st.dataframe(ev, use_container_width=True, hide_index=True)
            export.boton_csv(ev, "clima_eventos", "dl_clima_e")
            export.registrar("clima_eventos", ev)
    with t4:
        st.dataframe(q, use_container_width=True, hide_index=True)
        both = df[["p_chirps", "p_era5"]].dropna()
        if len(both) > 5:
            st.caption(f"CHIRPS vs ERA5-Land correlation (daily P): r = {both.corr().iloc[0, 1]:.2f} · n = {len(both)}")
