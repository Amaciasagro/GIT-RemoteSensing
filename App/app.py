"""
╔══════════════════════════════════════════════════════════════╗
║   AgroSense Dashboard — Ariel Macías                        ║
║   GIS & Remote Sensing · Agronomist                         ║
║   Integrates: LAI/NDVI · Soils · Climate (ERA5)             ║
╚══════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import requests
import warnings
import math
warnings.filterwarnings("ignore")

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="AgroSense | Ariel Macías",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
section[data-testid="stSidebar"] { background: #0b1e3d; }
section[data-testid="stSidebar"] * { color: #b8cfe8 !important; }
.hero {
    background: linear-gradient(130deg, #0b1e3d 0%, #1a3f7a 55%, #0d2a55 100%);
    border-radius: 18px; padding: 2.5rem 2.2rem; color: white; margin-bottom: 1.8rem;
}
.hero h1 { font-family:'Space Mono',monospace; font-size:2.4rem; font-weight:700;
           letter-spacing:-1px; margin:0; line-height:1.1; }
.hero p  { color:#93c5fd; font-size:0.95rem; margin:0.3rem 0 0; letter-spacing:2px; text-transform:uppercase; }
.sec-title {
    font-family:'Space Mono',monospace; font-size:1.1rem; font-weight:700;
    color:#0b1e3d; border-left:4px solid #3b82f6; padding-left:10px; margin:1.8rem 0 1rem;
}
.kpi-card {
    background:white; border-radius:12px; padding:1.2rem 1rem;
    box-shadow:0 2px 10px rgba(11,30,61,.08); text-align:center;
}
.kpi-val { font-family:'Space Mono',monospace; font-size:2rem; font-weight:700; color:#0b1e3d; }
.kpi-lbl { font-size:0.78rem; color:#64748b; text-transform:uppercase; letter-spacing:1px; margin-top:4px; }
.info-box { background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:1rem 1.2rem; font-size:0.88rem; color:#1e40af; margin-bottom:1rem; }
.warn-box { background:#fffbeb; border:1px solid #fde68a; border-radius:10px; padding:1rem 1.2rem; font-size:0.88rem; color:#92400e; margin-bottom:1rem; }
</style>
""", unsafe_allow_html=True)

# ── GEE init ─────────────────────────────────────────────────
@st.cache_resource
def init_gee(project_id: str):
    import ee
    try:
        ee.Initialize(project=project_id)
        return ee, None
    except Exception:
        try:
            ee.Authenticate()
            ee.Initialize(project=project_id)
            return ee, None
        except Exception as e:
            return None, str(e)

# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛰️ AgroSense")
    st.markdown("---")
    page = st.radio("Módulo:", ["🏠 Inicio", "🌿 LAI & NDVI", "🌱 Suelos", "🌦️ Clima ERA5"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown("### ⚙️ Google Earth Engine")
    gee_project = st.text_input("Project ID", value="my-project-12126-484118")
    if st.button("🔗 Conectar GEE", use_container_width=True):
        with st.spinner("Conectando..."):
            ee_obj, err = init_gee(gee_project)
        if err:
            st.error(f"Error: {err}")
            st.session_state["gee_ok"] = False
        else:
            st.success("✅ GEE conectado")
            st.session_state["gee_ok"] = True
            st.session_state["ee"] = ee_obj

    gee_ok = st.session_state.get("gee_ok", False)
    st.markdown(
        f'<div style="font-size:0.82rem;">{"🟢 Earth Engine activo" if gee_ok else "🔴 GEE no conectado"}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.markdown('<div style="font-size:0.78rem;color:#64748b;line-height:1.9;">Ariel Macías<br>Agrónomo · GIS & RS<br>GEE · USDA-NRCS · ERA5</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════
# INICIO
# ════════════════════════════════════════════════════
if page == "🏠 Inicio":
    st.markdown('<div class="hero"><h1>🛰️ AgroSense</h1><p>Ariel Macías · Agrónomo · GIS & Remote Sensing</p></div>', unsafe_allow_html=True)
    st.markdown("Dashboard que integra tres flujos de análisis agronómico usando APIs satelitales y de suelos.")
    col1, col2, col3 = st.columns(3)
    for col, (icon, title, desc) in zip([col1, col2, col3], [
        ("🌿", "LAI & NDVI", "Sentinel-2 SR via GEE. NDVI, LAI, EVI, SAVI, NDWI sobre cualquier lote. Serie temporal mensual configurable."),
        ("🌱", "Suelos", "USDA-NRCS Soil Data Access. Textura, pH, CEC, AWC y MO. Cobertura en EE.UU."),
        ("🌦️", "Clima ERA5", "ERA5-Land via GEE. Precipitación, temperatura, ETo Penman-Monteith FAO-56, balance hídrico y grados-día."),
    ]):
        with col:
            st.markdown(f'<div class="kpi-card" style="text-align:left;padding:1.4rem;"><div style="font-size:1.8rem;margin-bottom:8px;">{icon}</div><div style="font-weight:600;font-size:1rem;color:#0b1e3d;margin-bottom:6px;">{title}</div><div style="font-size:0.85rem;color:#64748b;line-height:1.6;">{desc}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="sec-title">🚀 Cómo usar</div>', unsafe_allow_html=True)
    for num, title, desc in [
        ("1", "Conectar GEE", "Ingresá tu GEE Project ID en el panel izquierdo y hacé clic en 'Conectar GEE'."),
        ("2", "Elegir módulo", "Seleccioná LAI & NDVI, Suelos o Clima en el menú de la izquierda."),
        ("3", "Definir el lote", "Ingresá las coordenadas y parámetros del análisis."),
        ("4", "Ejecutar", "Hacé clic en el botón de análisis — los datos se descargan en tiempo real desde las APIs."),
    ]:
        st.markdown(f'<div style="display:flex;gap:14px;align-items:flex-start;margin-bottom:12px;"><div style="background:#0b1e3d;color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-family:Space Mono,monospace;font-size:0.8rem;flex-shrink:0;">{num}</div><div><div style="font-weight:600;color:#0b1e3d;">{title}</div><div style="font-size:0.86rem;color:#64748b;">{desc}</div></div></div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════
# LAI & NDVI
# ════════════════════════════════════════════════════
elif page == "🌿 LAI & NDVI":
    st.markdown('<div class="sec-title">🌿 LAI & NDVI Crop Monitor — Sentinel-2 SR</div>', unsafe_allow_html=True)
    if not gee_ok:
        st.markdown('<div class="warn-box">⚠️ Conectá GEE primero desde el panel izquierdo.</div>', unsafe_allow_html=True)

    with st.expander("⚙️ Parámetros", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            lat_c    = st.number_input("Latitud centro",  value=-27.48, format="%.5f")
            lon_c    = st.number_input("Longitud centro", value=-58.83, format="%.5f")
            anios    = st.slider("Años hacia atrás", 1, 5, 3)
        with c2:
            max_nubes = st.slider("Máx. cobertura nubosa (%)", 5, 80, 30)
            k_ext     = st.number_input("Coef. extinción k (Beer-Lambert)", 0.3, 0.8, 0.5, step=0.05)
            savi_l    = st.number_input("Factor L (SAVI)", 0.0, 1.0, 0.5, step=0.1)
            buffer_m  = st.number_input("Radio del lote (m)", 200, 5000, 500, step=100)

    if st.button("🚀 Calcular índices", type="primary", disabled=not gee_ok):
        ee = st.session_state["ee"]
        with st.spinner("Descargando Sentinel-2 de GEE... (1-2 min)"):
            try:
                import datetime
                lote_geom = ee.Geometry.Point([lon_c, lat_c]).buffer(buffer_m)
                fecha_fin    = datetime.date.today()
                fecha_inicio = fecha_fin - datetime.timedelta(days=anios * 365)

                s2_col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                          .filterBounds(lote_geom)
                          .filterDate(str(fecha_inicio), str(fecha_fin))
                          .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_nubes)))

                def add_indices(image):
                    ndvi   = image.normalizedDifference(["B8","B4"]).rename("NDVI")
                    ndvi_c = ndvi.max(ee.Image(0)).min(ee.Image(0.95))
                    lai    = (ee.Image(1).subtract(ndvi_c.divide(0.95))
                              .log().multiply(-1.0/k_ext).max(0).rename("LAI"))
                    nir    = image.select("B8").divide(10000)
                    red    = image.select("B4").divide(10000)
                    blue   = image.select("B2").divide(10000)
                    evi    = (nir.subtract(red).multiply(2.5)
                              .divide(nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1))
                              .rename("EVI"))
                    savi   = (nir.subtract(red).divide(nir.add(red).add(savi_l))
                              .multiply(1+savi_l).rename("SAVI"))
                    ndwi   = image.normalizedDifference(["B3","B8"]).rename("NDWI")
                    return image.addBands([ndvi, lai, evi, savi, ndwi])

                s2_idx = s2_col.map(add_indices)

                months = []
                cur = fecha_inicio.replace(day=1)
                while cur <= fecha_fin:
                    months.append(cur.year*100+cur.month)
                    cur = cur.replace(month=cur.month+1) if cur.month < 12 else cur.replace(year=cur.year+1, month=1)

                def monthly_mean(ym):
                    y = ee.Number(ym).int()
                    m = ee.Number(ym).subtract(y.multiply(100)).int()
                    start = ee.Date.fromYMD(y, m, 1)
                    end   = start.advance(1, "month")
                    img   = s2_idx.filterDate(start, end).median().clip(lote_geom)
                    vals  = img.select(["NDVI","LAI","EVI","SAVI","NDWI"]).reduceRegion(
                        reducer=ee.Reducer.mean(), geometry=lote_geom, scale=10, maxPixels=1e9)
                    return ee.Feature(None, vals.set("ym", ym))

                fc   = ee.FeatureCollection(ee.List(months).map(lambda ym: monthly_mean(ee.Number(ym))))
                rows = fc.getInfo()["features"]

                records = []
                for f in rows:
                    p  = f["properties"]
                    ym = int(p.get("ym", 0))
                    y, m = ym//100, ym%100
                    records.append({"fecha": pd.Timestamp(year=y, month=m, day=1),
                                    "NDVI": p.get("NDVI"), "LAI": p.get("LAI"),
                                    "EVI":  p.get("EVI"),  "SAVI": p.get("SAVI"),
                                    "NDWI": p.get("NDWI")})

                df = pd.DataFrame(records).dropna(subset=["NDVI"]).set_index("fecha")
                st.session_state["df_lai"] = df
                st.success(f"✅ {len(df)} meses descargados.")
            except Exception as e:
                st.error(f"❌ {e}")

    df = st.session_state.get("df_lai")
    if df is not None and not df.empty:
        last = df.iloc[-1]
        cols = st.columns(5)
        for col, (name, val, lbl) in zip(cols, [
            ("NDVI", f"{last['NDVI']:.3f}", "Vigor vegetativo"),
            ("LAI",  f"{last['LAI']:.2f} m²/m²", "Área foliar"),
            ("EVI",  f"{last['EVI']:.3f}", "Índice mejorado"),
            ("SAVI", f"{last['SAVI']:.3f}", "Ajustado suelo"),
            ("NDWI", f"{last['NDWI']:.3f}", "Agua canopeo"),
        ]):
            with col:
                st.markdown(f'<div class="kpi-card"><div class="kpi-val" style="font-size:1.5rem;">{val}</div><div class="kpi-lbl">{name}<br><span style="font-size:0.7rem;">{lbl}</span></div></div>', unsafe_allow_html=True)
        st.markdown("")

        idx_cfg = {"NDVI":("#22c55e","NDVI (0–1)"), "LAI":("#3b82f6","LAI (m²/m²)"),
                   "EVI":("#a855f7","EVI"), "SAVI":("#f59e0b","SAVI"), "NDWI":("#06b6d4","NDWI")}
        idx_sel = st.multiselect("Índices a graficar:", list(idx_cfg.keys()), default=["NDVI","LAI"])

        if idx_sel:
            fig = make_subplots(rows=len(idx_sel), cols=1, shared_xaxes=True, vertical_spacing=0.04)
            for i, idx in enumerate(idx_sel, 1):
                color, label = idx_cfg[idx]
                fig.add_trace(go.Scatter(x=df.index, y=df[idx], mode="lines+markers", name=idx,
                                         line=dict(color=color, width=2), marker=dict(size=5),
                                         hovertemplate=f"<b>{idx}</b>=%{{y:.3f}}<extra></extra>"), row=i, col=1)
                fig.update_yaxes(title_text=label, row=i, col=1, showgrid=True, gridcolor="#e2e8f0")
            fig.update_layout(height=180*len(idx_sel), plot_bgcolor="white", paper_bgcolor="white",
                               font=dict(family="DM Sans",size=12), margin=dict(l=60,r=20,t=20,b=40), showlegend=False)
            fig.update_xaxes(showgrid=True, gridcolor="#e2e8f0")
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("📋 Tabla de datos"):
            st.dataframe(df[idx_sel].round(4), use_container_width=True)
    else:
        st.markdown('<div class="info-box">ℹ️ Configurá el lote y hacé clic en "Calcular índices".</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════
# SUELOS
# ════════════════════════════════════════════════════
elif page == "🌱 Suelos":
    st.markdown('<div class="sec-title">🌱 Soil Analyzer — USDA-NRCS SDA</div>', unsafe_allow_html=True)
    st.markdown('<div class="warn-box">⚠️ Cobertura únicamente en <b>Estados Unidos</b>. Para Argentina u otros países el servicio no devuelve datos.</div>', unsafe_allow_html=True)

    with st.expander("⚙️ Bounding box del lote", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            lat_min = st.number_input("Latitud mínima (sur)",   value=33.578, format="%.5f")
            lon_min = st.number_input("Longitud mínima (oeste)", value=-101.852, format="%.5f")
        with c2:
            lat_max = st.number_input("Latitud máxima (norte)", value=33.590, format="%.5f")
            lon_max = st.number_input("Longitud máxima (este)", value=-101.838, format="%.5f")

    if st.button("🔍 Consultar USDA-NRCS SDA", type="primary"):
        wfs_url = "https://sdmdataaccess.nrcs.usda.gov/Spatial/SDM.wfs"
        params  = {"SERVICE":"WFS","VERSION":"1.1.0","REQUEST":"GetFeature",
                   "TYPENAME":"MapunitPolyExtended","BBOX":f"{lon_min},{lat_min},{lon_max},{lat_max}",
                   "SRSNAME":"EPSG:4326","OUTPUTFORMAT":"GeoJSON"}
        with st.spinner("Consultando USDA-NRCS..."):
            try:
                resp = requests.get(wfs_url, params=params, verify=False, timeout=30)
                gj   = resp.json()
                features = gj.get("features", [])
                if not features:
                    st.warning("No se encontraron unidades en ese bounding box.")
                else:
                    rows = [{"mukey":f["properties"].get("mukey",""), "musym":f["properties"].get("musym",""),
                             "muname":f["properties"].get("muname","—")} for f in features]
                    df_units = pd.DataFrame(rows).drop_duplicates("mukey")
                    mukeys   = "','".join(df_units["mukey"].astype(str).tolist())

                    sda_url = "https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest"
                    query   = f"""SELECT mu.mukey, mu.musym, c.compname AS serie, c.comppct_r AS pct,
                                ch.sandtotal_r AS arena, ch.silttotal_r AS limo, ch.claytotal_r AS arcilla,
                                ch.om_r AS mo, ch.ph1to1h2o_r AS ph, ch.cec7_r AS cec, ch.awc_r AS awc
                                FROM mapunit mu JOIN component c ON mu.mukey=c.mukey
                                JOIN chorizon ch ON c.cokey=ch.cokey
                                WHERE mu.mukey IN ('{mukeys}') AND ch.hzdept_r=0
                                ORDER BY mu.mukey, c.comppct_r DESC"""
                    r2 = requests.post(sda_url, data={"query":query,"format":"JSON"}, verify=False, timeout=30)
                    df_soil = pd.DataFrame()
                    if r2.status_code == 200:
                        data2 = r2.json()
                        if data2.get("Table"):
                            cols_s = ["mukey","musym","serie","pct","arena","limo","arcilla","mo","ph","cec","awc"]
                            df_soil = pd.DataFrame(data2["Table"], columns=cols_s)
                            for c in ["pct","arena","limo","arcilla","mo","ph","cec","awc"]:
                                df_soil[c] = pd.to_numeric(df_soil[c], errors="coerce")
                    st.session_state["df_soil"] = df_soil
                    st.session_state["df_units"] = df_units
                    st.success(f"✅ {len(df_units)} unidades cartográficas encontradas.")
            except Exception as e:
                st.error(f"❌ {e}")

    def classify_texture(sand, silt, clay):
        if any(pd.isna(v) for v in [sand, silt, clay]): return "Sin datos"
        if clay >= 40: return "Arcilla"
        if clay >= 27 and sand <= 20: return "Arcilla limosa"
        if clay >= 27: return "Arcillo arenosa"
        if silt >= 50 and clay < 27: return "Franco limoso"
        if sand >= 70 and clay < 15: return "Arenoso franco"
        if sand >= 85: return "Arena"
        return "Franco"

    PALETA = {"Arena":"#f59e0b","Arenoso franco":"#fbbf24","Franco":"#84cc16",
              "Franco limoso":"#22c55e","Arcillo arenosa":"#ef4444",
              "Arcilla limosa":"#dc2626","Arcilla":"#991b1b","Sin datos":"#94a3b8"}

    df_soil = st.session_state.get("df_soil")
    if df_soil is not None and not df_soil.empty:
        df_soil["textura"] = df_soil.apply(lambda r: classify_texture(r["arena"],r["limo"],r["arcilla"]), axis=1)
        pct_sum = df_soil["pct"].sum() or 1
        w = df_soil["pct"] / pct_sum

        kpis = [("Arena",f"{(df_soil['arena']*w).sum():.1f}%",""),
                ("Limo", f"{(df_soil['limo']*w).sum():.1f}%",""),
                ("Arcilla",f"{(df_soil['arcilla']*w).sum():.1f}%",""),
                ("MO",f"{(df_soil['mo']*w).sum():.2f}%","Materia orgánica"),
                ("pH",f"{(df_soil['ph']*w).sum():.1f}",""),
                ("CEC",f"{(df_soil['cec']*w).sum():.1f}","cmol/kg"),
                ("AWC",f"{(df_soil['awc']*w).sum():.3f}","cm/cm")]
        cols = st.columns(len(kpis))
        for col, (name, val, unit) in zip(cols, kpis):
            with col:
                st.markdown(f'<div class="kpi-card"><div class="kpi-val" style="font-size:1.4rem;">{val}</div><div class="kpi-lbl">{name}<br><span style="font-size:0.7rem;color:#94a3b8;">{unit}</span></div></div>', unsafe_allow_html=True)
        st.markdown("")

        fig_t = go.Figure()
        for _, row in df_soil.iterrows():
            color = PALETA.get(row["textura"], "#94a3b8")
            fig_t.add_trace(go.Bar(name=f"{row['serie']} ({row['pct']}%)",
                                   x=["Arena","Limo","Arcilla"],
                                   y=[row["arena"],row["limo"],row["arcilla"]],
                                   marker_color=color, opacity=0.85))
        fig_t.update_layout(barmode="group", plot_bgcolor="white", paper_bgcolor="white",
                            font=dict(family="DM Sans",size=12), height=340,
                            margin=dict(l=50,r=20,t=20,b=40),
                            xaxis=dict(showgrid=True,gridcolor="#e2e8f0"),
                            yaxis=dict(title="%",showgrid=True,gridcolor="#e2e8f0"),
                            legend=dict(orientation="h",yanchor="bottom",y=1.02))
        st.plotly_chart(fig_t, use_container_width=True)

        st.dataframe(df_soil[["musym","serie","pct","arena","limo","arcilla","textura","mo","ph","cec","awc"]]
                     .rename(columns={"musym":"Unidad","serie":"Serie","pct":"% comp.",
                                      "arena":"Arena%","limo":"Limo%","arcilla":"Arcilla%",
                                      "textura":"Textura","mo":"MO%","ph":"pH","cec":"CEC","awc":"AWC"})
                     .round(2), use_container_width=True)
    else:
        st.markdown('<div class="info-box">ℹ️ Ingresá el bounding box y ejecutá la consulta.</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════
# CLIMA ERA5
# ════════════════════════════════════════════════════
elif page == "🌦️ Clima ERA5":
    st.markdown('<div class="sec-title">🌦️ Climate Analyzer — ERA5-Land · ECMWF</div>', unsafe_allow_html=True)
    if not gee_ok:
        st.markdown('<div class="warn-box">⚠️ Conectá GEE primero desde el panel izquierdo.</div>', unsafe_allow_html=True)

    with st.expander("⚙️ Parámetros", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            lat_c2  = st.number_input("Latitud centro",  value=-27.48, format="%.5f", key="lat_clim")
            lon_c2  = st.number_input("Longitud centro", value=-58.83, format="%.5f", key="lon_clim")
            buf_clim= st.number_input("Radio (m)", 500, 10000, 2000, step=500)
        with c2:
            t_base  = st.number_input("T base GDA (°C)", value=10.0, step=0.5)
            anios_c = st.slider("Años de histórico", 1, 5, 2)

    if st.button("🚀 Descargar ERA5", type="primary", disabled=not gee_ok):
        ee = st.session_state["ee"]
        with st.spinner("Descargando ERA5-Land de GEE... (2-3 min)"):
            try:
                import datetime
                lote_geom    = ee.Geometry.Point([lon_c2, lat_c2]).buffer(buf_clim)
                fecha_fin    = datetime.date.today()
                fecha_inicio = fecha_fin - datetime.timedelta(days=anios_c*365)

                era5 = (ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
                        .filterBounds(lote_geom)
                        .filterDate(str(fecha_inicio), str(fecha_fin))
                        .select(["total_precipitation_sum","temperature_2m_max","temperature_2m_min",
                                 "dewpoint_temperature_2m","surface_solar_radiation_downwards_sum",
                                 "u_component_of_wind_10m","v_component_of_wind_10m"]))

                def reduce_img(img):
                    vals = img.reduceRegion(reducer=ee.Reducer.mean(), geometry=lote_geom,
                                           scale=11132, maxPixels=1e9)
                    return ee.Feature(None, vals.set("date", img.date().format("YYYY-MM-dd")))

                rows = era5.map(reduce_img).getInfo()["features"]

                records = []
                for f in rows:
                    p = f["properties"]
                    try:
                        tmax = p.get("temperature_2m_max")
                        tmin = p.get("temperature_2m_min")
                        td   = p.get("dewpoint_temperature_2m")
                        if tmax: tmax -= 273.15
                        if tmin: tmin -= 273.15
                        if td:   td   -= 273.15
                        prec = (p.get("total_precipitation_sum") or 0) * 1000
                        rad  = (p.get("surface_solar_radiation_downwards_sum") or 0) / 1e6
                        u    = p.get("u_component_of_wind_10m") or 0
                        v    = p.get("v_component_of_wind_10m") or 0
                        ws   = math.sqrt(u**2 + v**2)
                        tmed = ((tmax or 0) + (tmin or 0)) / 2 if tmax and tmin else None
                        hr   = (100 * math.exp((17.625*td)/(243.04+td)) /
                                math.exp((17.625*tmed)/(243.04+tmed))) if td and tmed else None
                        gda  = max(0, tmed - t_base) if tmed else 0

                        # ETo PM simplificado
                        eto = np.nan
                        if tmed and rad:
                            u2    = ws * 0.748
                            hr_v  = max(0, min(100, hr)) if hr else 50
                            es    = 0.6108 * math.exp(17.27*tmed/(tmed+237.3))
                            ea    = es * hr_v / 100
                            delta = 4098 * es / (tmed+237.3)**2
                            gamma = 0.0665
                            Rn    = 0.77 * rad - 0.5
                            eto   = max(0, (0.408*delta*Rn + gamma*(900/(tmed+273))*u2*(es-ea)) /
                                       (delta + gamma*(1+0.34*u2)))

                        records.append({"fecha": pd.Timestamp(p["date"]),
                                        "precip":prec,"tmax":tmax,"tmin":tmin,"tmed":tmed,
                                        "hr":hr,"rad":rad,"viento":ws,"gda":gda,"eto":eto})
                    except:
                        pass

                df_c = pd.DataFrame(records).set_index("fecha").dropna(subset=["tmed"])
                df_c["balance"]  = df_c["precip"] - df_c["eto"]
                df_c["gda_acum"] = df_c["gda"].cumsum()

                df_m = df_c.resample("ME").agg(
                    {"precip":"sum","eto":"sum","balance":"sum",
                     "tmax":"mean","tmin":"mean","tmed":"mean","hr":"mean","gda":"sum"}
                ).round(2)
                df_m["mes"] = df_m.index.strftime("%b %Y")

                st.session_state["df_clima_d"] = df_c
                st.session_state["df_clima_m"] = df_m
                st.success(f"✅ {len(df_c)} días descargados ({len(df_m)} meses).")
            except Exception as e:
                st.error(f"❌ {e}")

    df_m = st.session_state.get("df_clima_m")
    df_d = st.session_state.get("df_clima_d")

    if df_m is not None and not df_m.empty:
        last_m = df_m.iloc[-1]
        gda_total = df_d["gda_acum"].iloc[-1] if df_d is not None else 0

        kpis = [("Lluvia", f"{last_m['precip']:.1f} mm", "último mes"),
                ("ETo PM", f"{last_m['eto']:.1f} mm",   "Penman-Monteith"),
                ("Balance",f"{last_m['balance']:+.1f} mm","Lluvia − ETo"),
                ("T media",f"{last_m['tmed']:.1f} °C",  "último mes"),
                ("HR media",f"{last_m['hr']:.0f}%",     "último mes"),
                ("GDA acum.",f"{gda_total:.0f} °C·día", "período completo")]
        cols = st.columns(len(kpis))
        for col, (name, val, sub) in zip(cols, kpis):
            with col:
                st.markdown(f'<div class="kpi-card"><div class="kpi-val" style="font-size:1.3rem;">{val}</div><div class="kpi-lbl">{name}<br><span style="font-size:0.7rem;color:#94a3b8;">{sub}</span></div></div>', unsafe_allow_html=True)
        st.markdown("")

        tab1, tab2, tab3, tab4 = st.tabs(["🌧 Lluvia & ETo", "🌡 Temperatura", "💧 Balance hídrico", "🌱 Grados día"])

        with tab1:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_m["mes"], y=df_m["precip"], name="Precipitación (mm)", marker_color="#3b82f6", opacity=0.8))
            fig.add_trace(go.Scatter(x=df_m["mes"], y=df_m["eto"], name="ETo PM (mm)", mode="lines+markers", line=dict(color="#ef4444",width=2), marker=dict(size=6)))
            fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", font=dict(family="DM Sans"), height=340,
                              margin=dict(l=50,r=20,t=20,b=80), barmode="overlay",
                              xaxis=dict(tickangle=-45,showgrid=True,gridcolor="#e2e8f0"),
                              yaxis=dict(title="mm",showgrid=True,gridcolor="#e2e8f0"),
                              legend=dict(orientation="h",yanchor="bottom",y=1.02))
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=df_m["mes"], y=df_m["tmax"], name="T máx", line=dict(color="#ef4444",width=2)))
            fig2.add_trace(go.Scatter(x=df_m["mes"], y=df_m["tmed"], name="T media", line=dict(color="#f59e0b",width=2)))
            fig2.add_trace(go.Scatter(x=df_m["mes"], y=df_m["tmin"], name="T mín", line=dict(color="#3b82f6",width=2),
                                      fill="tonexty", fillcolor="rgba(59,130,246,0.08)"))
            fig2.update_layout(plot_bgcolor="white", paper_bgcolor="white", font=dict(family="DM Sans"), height=340,
                               margin=dict(l=50,r=20,t=20,b=80),
                               xaxis=dict(tickangle=-45,showgrid=True,gridcolor="#e2e8f0"),
                               yaxis=dict(title="°C",showgrid=True,gridcolor="#e2e8f0"),
                               legend=dict(orientation="h",yanchor="bottom",y=1.02))
            st.plotly_chart(fig2, use_container_width=True)

        with tab3:
            colors = ["#22c55e" if v >= 0 else "#ef4444" for v in df_m["balance"]]
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(x=df_m["mes"], y=df_m["balance"], marker_color=colors, name="Balance"))
            fig3.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
            fig3.update_layout(plot_bgcolor="white", paper_bgcolor="white", font=dict(family="DM Sans"), height=340,
                               margin=dict(l=50,r=20,t=20,b=80),
                               xaxis=dict(tickangle=-45,showgrid=True,gridcolor="#e2e8f0"),
                               yaxis=dict(title="mm (Lluvia − ETo)",showgrid=True,gridcolor="#e2e8f0"))
            st.plotly_chart(fig3, use_container_width=True)

        with tab4:
            fig4 = go.Figure()
            fig4.add_trace(go.Bar(x=df_m["mes"], y=df_m["gda"], name="GDA mensuales", marker_color="#a855f7", opacity=0.8))
            if df_d is not None:
                fig4.add_trace(go.Scatter(x=df_d.index, y=df_d["gda_acum"], name="GDA acumulados",
                                          mode="lines", line=dict(color="#7c3aed",width=2), yaxis="y2"))
            fig4.update_layout(plot_bgcolor="white", paper_bgcolor="white", font=dict(family="DM Sans"), height=340,
                               margin=dict(l=50,r=60,t=20,b=80),
                               xaxis=dict(tickangle=-45,showgrid=True,gridcolor="#e2e8f0"),
                               yaxis=dict(title="GDA mensuales",showgrid=True,gridcolor="#e2e8f0"),
                               yaxis2=dict(title="GDA acumulados",overlaying="y",side="right"),
                               legend=dict(orientation="h",yanchor="bottom",y=1.02))
            st.plotly_chart(fig4, use_container_width=True)

        with st.expander("📋 Tabla mensual"):
            st.dataframe(df_m.drop(columns=["mes"]).round(2), use_container_width=True)
    else:
        st.markdown('<div class="info-box">ℹ️ Configurá el lote y hacé clic en "Descargar ERA5".</div>', unsafe_allow_html=True)
