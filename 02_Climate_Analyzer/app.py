# ============================================================
# 🌦️ Climate Analyzer — Streamlit App
# Autor: Ariel Macías | Agrónomo · GIS & Remote Sensing
# Fuente de datos: ERA5-Land (ECMWF) via Google Earth Engine
# ============================================================

import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import geopandas as gpd
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import unary_union
import json, io, zipfile, tempfile, os, warnings, math
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from google.oauth2.credentials import Credentials

warnings.filterwarnings("ignore")

# ── Colección ERA5 y parámetros agronómicos ──────────────────
ERA5_COLLECTION = "ECMWF/ERA5_LAND/DAILY_AGGR"
T_BASE          = 10.0   # Grados día: temperatura base (°C)

# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE PÁGINA
# ════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Climate Analyzer · ERA5",
    page_icon="🌦️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stSidebar"] { background: #0d1520; }
  .block-container { padding-top: 1.2rem; padding-bottom: 1rem; }
  div[data-testid="metric-container"] {
    background: #111c2a;
    border: 1px solid #1a2d42;
    border-radius: 10px;
    padding: 12px 16px;
  }
  div[data-testid="metric-container"] label { color: #7a99b8 !important; font-size:12px; }
  .stAlert { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# Marca de agua
st.markdown("""
    <style>
    .watermark {
        position: fixed; bottom: 15px; right: 15px;
        opacity: 0.5; font-size: 13px; color: #7a99b8;
        z-index: 9999; pointer-events: none;
        background-color: rgba(13,21,32,0.7);
        padding: 5px 10px; border-radius: 5px;
    }
    </style>
    <div class="watermark">© 2026 Ariel Macías | Ingeniero Agrónomo & Analista SIG</div>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════
# GEE — INICIALIZACIÓN
# ════════════════════════════════════════════════════════════
@st.cache_resource
def init_gee():
    """Inicializa GEE con credenciales OAuth2 desde secrets.toml."""
    try:
        project_id = st.secrets.get("EARTHENGINE_PROJECT", "")
        auth_info  = st.secrets["google_auth"]
        creds = Credentials(
            token=None,
            refresh_token  = auth_info["refresh_token"],
            client_id      = auth_info["client_id"],
            client_secret  = auth_info["client_secret"],
            token_uri      = "https://oauth2.googleapis.com/token",
        )
        ee.Initialize(creds, project=project_id)
        return True, None
    except Exception as e:
        return False, str(e)


# ════════════════════════════════════════════════════════════
# GEE — DESCARGA ERA5
# ════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def descargar_era5(aoi_json: str, fecha_inicio: str, fecha_fin: str) -> str:
    """
    Descarga serie diaria ERA5-Land para el lote.
    Retorna JSON del DataFrame (cacheado por parámetros).
    """
    lote_geom = ee.Geometry(json.loads(aoi_json))

    bandas = [
        "total_precipitation_sum",       # mm/día
        "temperature_2m_max",            # K
        "temperature_2m_min",            # K
        "dewpoint_temperature_2m",       # K  → HR
        "surface_solar_radiation_downwards_sum",  # J/m²/día → MJ/m²/día
        "u_component_of_wind_10m",       # m/s
        "v_component_of_wind_10m",       # m/s
        "total_evaporation_sum",  # m/día → mm/día
    ]

    col = (ee.ImageCollection(ERA5_COLLECTION)
           .filterBounds(lote_geom)
           .filterDate(fecha_inicio, fecha_fin)
           .select(bandas))

    def extract(img):
        stats = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=lote_geom,
            scale=11132,     # ~0.1° resolución ERA5
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
        # Conversiones
        t_max  = p["temperature_2m_max"]  - 273.15
        t_min  = p["temperature_2m_min"]  - 273.15
        t_dew  = p["dewpoint_temperature_2m"] - 273.15
        precip = p["total_precipitation_sum"] * 1000          # m → mm
        rad    = p["surface_solar_radiation_downwards_sum"] / 1e6  # J → MJ
        et_era = abs(p.get("total_evaporation_sum", 0) or 0) * 1000  # m → mm
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
# MÉTRICAS AGRONÓMICAS
# ════════════════════════════════════════════════════════════
def calcular_hr(df: pd.DataFrame) -> pd.Series:
    """Humedad relativa estimada a partir del punto de rocío (%)."""
    es_t   = 0.6108 * np.exp(17.27 * df["t_med"]  / (df["t_med"]  + 237.3))
    es_dew = 0.6108 * np.exp(17.27 * df["t_dew"]  / (df["t_dew"]  + 237.3))
    hr = (es_dew / es_t * 100).clip(0, 100)
    return hr


def calcular_eto_pm(df: pd.DataFrame, latitud: float) -> pd.Series:
    """
    ETo Penman-Monteith FAO-56 (mm/día).
    Referencia: Allen et al. 1998, FAO Irrigation and Drainage Paper 56.
    """
    T    = df["t_med"]
    Tmax = df["t_max"]
    Tmin = df["t_min"]
    Rs   = df["rad"]        # MJ/m²/día
    u2   = df["viento"]     # m/s a 10 m → ajuste a 2 m
    Td   = df["t_dew"]

    # Viento a 2 m
    u2 = u2 * (4.87 / math.log(67.8 * 10 - 5.42))

    # Presión de vapor de saturación y real
    es = 0.5 * (0.6108 * np.exp(17.27 * Tmax / (Tmax + 237.3)) +
                0.6108 * np.exp(17.27 * Tmin / (Tmin + 237.3)))
    ea = 0.6108 * np.exp(17.27 * Td / (Td + 237.3))

    # DOY y Ra (MJ/m²/día)
    doy = df.index.dayofyear
    lat_rad = math.radians(abs(latitud))
    dr  = 1 + 0.033 * np.cos(2 * math.pi / 365 * doy)
    dec = 0.409 * np.sin(2 * math.pi / 365 * doy - 1.39)
    ws  = np.arccos(-np.tan(lat_rad) * np.tan(dec))
    Ra  = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * np.sin(lat_rad) * np.sin(dec) +
        np.cos(lat_rad) * np.cos(dec) * np.sin(ws)
    )

    # Radiación neta
    Rso = (0.75 + 2e-5 * 0) * Ra   # altitud ≈ 0 para simplificar
    Rns = (1 - 0.23) * Rs
    Rnl = (4.903e-9 * ((Tmax + 273.16)**4 + (Tmin + 273.16)**4) / 2 *
           (0.34 - 0.14 * np.sqrt(ea)) *
           (1.35 * (Rs / np.maximum(Rso, 0.1)) - 0.35))
    Rn  = Rns - Rnl

    # Pendiente de la curva de presión de vapor
    delta = 4098 * (0.6108 * np.exp(17.27 * T / (T + 237.3))) / (T + 237.3) ** 2

    # Constante psicrométrica (kPa/°C) a nivel del mar
    gamma = 0.0665

    # ETo
    eto = (0.408 * delta * Rn + gamma * (900 / (T + 273)) * u2 * (es - ea)) / (
        delta + gamma * (1 + 0.34 * u2)
    )
    return eto.clip(lower=0)


def agregar_mensual(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega la serie diaria a nivel mensual con las métricas agronómicas."""
    df = df.copy()
    df["eto"]  = calcular_eto_pm(df, df.attrs.get("latitud", -30))
    df["hr"]   = calcular_hr(df)
    df["gda"]  = (df["t_med"] - T_BASE).clip(lower=0)

    mensual = df.resample("MS").agg(
        precip      = ("precip",  "sum"),
        t_max       = ("t_max",   "mean"),
        t_min       = ("t_min",   "mean"),
        t_med       = ("t_med",   "mean"),
        hr          = ("hr",      "mean"),
        rad         = ("rad",     "sum"),
        viento      = ("viento",  "mean"),
        et_era      = ("et_era",  "sum"),
        eto         = ("eto",     "sum"),
        gda         = ("gda",     "sum"),
    ).dropna(subset=["precip"])

    mensual["balance_hidro"] = mensual["precip"] - mensual["eto"]
    mensual["mes_año"]       = mensual.index
    return mensual


def procesar_diario(df: pd.DataFrame, inicio: str, fin: str) -> pd.DataFrame:
    """Retorna el detalle diario del período solicitado con métricas acumuladas."""
    df = df.copy()
    df["eto"] = calcular_eto_pm(df, df.attrs.get("latitud", -30))
    df["hr"]  = calcular_hr(df)
    df["gda"] = (df["t_med"] - T_BASE).clip(lower=0)

    sub = df.loc[inicio:fin].copy()
    sub["precip_acum"] = sub["precip"].cumsum()
    sub["eto_acum"]    = sub["eto"].cumsum()
    sub["balance_acum"]= sub["precip_acum"] - sub["eto_acum"]
    sub["gda_acum"]    = sub["gda"].cumsum()
    return sub


# ════════════════════════════════════════════════════════════
# GRÁFICOS
# ════════════════════════════════════════════════════════════
def grafico_climatico(df_m: pd.DataFrame) -> go.Figure:
    """Panel superior: barras de lluvia + líneas de temperatura."""
    labels = df_m["mes_año"].dt.strftime("%b %Y")
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Barras de precipitación
    fig.add_trace(go.Bar(
        x=labels, y=df_m["precip"],
        name="Precipitación (mm)", marker_color="#4da6ff", opacity=0.8,
    ), secondary_y=False)

    # ETo
    fig.add_trace(go.Scatter(
        x=labels, y=df_m["eto"],
        name="ETo PM (mm)", mode="lines+markers",
        line=dict(color="#ff9f43", width=2),
        marker=dict(size=5),
    ), secondary_y=False)

    # Temperatura media
    fig.add_trace(go.Scatter(
        x=labels, y=df_m["t_med"],
        name="T. media (°C)", mode="lines",
        line=dict(color="#ee5a24", width=1.5, dash="dot"),
    ), secondary_y=True)

    fig.update_layout(
        title=dict(text="Precipitación · ETo · Temperatura mensual", font_size=13, x=0.01),
        height=280, margin=dict(l=10, r=10, t=35, b=10),
        paper_bgcolor="#0d1520", plot_bgcolor="#0d1520",
        font_color="#d4e2f0", legend=dict(orientation="h", y=-0.25, font_size=11),
        barmode="overlay",
        xaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8"),
        yaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8",
                   title="mm", title_font_size=11),
        yaxis2=dict(gridcolor="#1a2d42", tickfont_size=10, color="#ee5a24",
                    title="°C", title_font_size=11, showgrid=False),
    )
    return fig


def grafico_balance(df_m: pd.DataFrame) -> go.Figure:
    """Balance hídrico mensual (barras verdes/rojas)."""
    labels  = df_m["mes_año"].dt.strftime("%b %Y")
    balance = df_m["balance_hidro"]
    colores = ["#2ecc71" if v >= 0 else "#e74c3c" for v in balance]

    fig = go.Figure(go.Bar(
        x=labels, y=balance,
        marker_color=colores, opacity=0.85,
        name="Balance hídrico (mm)",
        hovertemplate="<b>%{x}</b><br>Balance: %{y:.1f} mm<extra></extra>",
    ))
    fig.add_hline(y=0, line_color="#ffffff", line_width=1, opacity=0.3)
    fig.update_layout(
        title=dict(text="Balance Hídrico mensual · Lluvia − ETo", font_size=13, x=0.01),
        height=240, margin=dict(l=10, r=10, t=35, b=10),
        paper_bgcolor="#0d1520", plot_bgcolor="#0d1520",
        font_color="#d4e2f0",
        xaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8"),
        yaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8", title="mm"),
    )
    return fig


def grafico_diario(df_d: pd.DataFrame) -> go.Figure:
    """Detalle diario del mes actual: acumulados y GDA."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=df_d.index, y=df_d["precip_acum"],
        name="Lluvia acum. (mm)", mode="lines",
        line=dict(color="#4da6ff", width=2),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df_d.index, y=df_d["eto_acum"],
        name="ETo acum. (mm)", mode="lines",
        line=dict(color="#ff9f43", width=2, dash="dash"),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df_d.index, y=df_d["balance_acum"],
        name="Balance acum. (mm)", mode="lines",
        fill="tozeroy",
        fillcolor="rgba(46,204,113,0.15)",
        line=dict(color="#2ecc71", width=1.5),
    ), secondary_y=False)

    fig.add_trace(go.Bar(
        x=df_d.index, y=df_d["gda_acum"],
        name=f"GDA acum. (base {T_BASE:.0f}°C)", opacity=0.4,
        marker_color="#f39c12",
    ), secondary_y=True)

    fig.update_layout(
        title=dict(text="Detalle diario — mes en curso · Acumulados", font_size=13, x=0.01),
        height=280, margin=dict(l=10, r=10, t=35, b=10),
        paper_bgcolor="#0d1520", plot_bgcolor="#0d1520",
        font_color="#d4e2f0", legend=dict(orientation="h", y=-0.3, font_size=10),
        xaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8"),
        yaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8", title="mm"),
        yaxis2=dict(tickfont_size=10, color="#f39c12",
                    title=f"GDA (base {T_BASE:.0f}°C)", showgrid=False),
    )
    return fig


def grafico_hr_viento(df_m: pd.DataFrame) -> go.Figure:
    """HR media y velocidad de viento mensual."""
    labels = df_m["mes_año"].dt.strftime("%b %Y")
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=labels, y=df_m["hr"],
        name="HR media (%)", marker_color="#a29bfe", opacity=0.75,
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=labels, y=df_m["viento"],
        name="Viento (m/s)", mode="lines+markers",
        line=dict(color="#fd79a8", width=2),
        marker=dict(size=5),
    ), secondary_y=True)

    fig.update_layout(
        title=dict(text="Humedad Relativa media · Velocidad de viento", font_size=13, x=0.01),
        height=240, margin=dict(l=10, r=10, t=35, b=10),
        paper_bgcolor="#0d1520", plot_bgcolor="#0d1520",
        font_color="#d4e2f0", legend=dict(orientation="h", y=-0.3, font_size=11),
        xaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8"),
        yaxis=dict(gridcolor="#1a2d42", tickfont_size=10, color="#7a99b8", title="%"),
        yaxis2=dict(tickfont_size=10, color="#fd79a8", title="m/s", showgrid=False),
    )
    return fig


# ════════════════════════════════════════════════════════════
# MAPA FOLIUM
# ════════════════════════════════════════════════════════════
def build_mapa(center, zoom, aoi_geojson=None, allow_draw=False) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satélite (Esri)", show=True,
    ).add_to(m)

    if aoi_geojson:
        folium.GeoJson(
            {"type": "Feature", "geometry": aoi_geojson},
            style_function=lambda _: {
                "color": "#f1c40f", "weight": 2,
                "dashArray": "6,4", "fillOpacity": 0.1,
            },
            name="Límite del lote",
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    if allow_draw:
        Draw(
            draw_options={
                "polygon": True, "rectangle": True,
                "polyline": False, "circle": False,
                "marker": False, "circlemarker": False,
            },
            edit_options={"edit": False},
        ).add_to(m)
    return m


# ════════════════════════════════════════════════════════════
# CARGA ARCHIVO AOI
# ════════════════════════════════════════════════════════════
def cargar_aoi_desde_archivo(archivos) -> dict | None:
    tmp = tempfile.mkdtemp()
    for f in archivos:
        with open(os.path.join(tmp, f.name), "wb") as fp:
            fp.write(f.read())
    for fname in os.listdir(tmp):
        if fname.endswith(".zip"):
            with zipfile.ZipFile(os.path.join(tmp, fname), "r") as z:
                z.extractall(tmp)
    validos = [f for f in os.listdir(tmp) if f.endswith((".shp", ".geojson"))]
    if not validos:
        return None
    gdf  = gpd.read_file(os.path.join(tmp, validos[0])).to_crs(epsg=4326)
    geom = unary_union(gdf.geometry)
    return mapping(geom)


# ════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════
def render_sidebar():
    with st.sidebar:
        st.markdown("## 🌦️ Climate Analyzer")
        st.caption("ERA5-Land · ECMWF · Google Earth Engine")
        st.divider()

        # ── Parámetros ──
        st.markdown("### ⚙️ Parámetros")
        col1, col2 = st.columns(2)
        with col1:
            anios = st.number_input("Años atrás", 1, 10, 5)
        with col2:
            t_base_ui = st.number_input("T base GDA (°C)", 0.0, 15.0, float(T_BASE), 1.0,
                                        help="Temperatura base para el cálculo de Grados Día Acumulados")

        st.divider()

        # ── AOI ──
        st.markdown("### 📍 Área de Interés")
        tab_dibujo, tab_archivo = st.tabs(["✏️ Dibujar", "📂 Subir archivo"])

        with tab_dibujo:
            st.caption("Dibujá un polígono en el mapa y presioná **Confirmar**.")
            if st.button("✅ Confirmar polígono dibujado", use_container_width=True,
                         type="primary", key="btn_confirm"):
                dibujado = st.session_state.get("ultimo_dibujo")
                if dibujado:
                    geom = dibujado.get("geometry") or dibujado
                    st.session_state["aoi"] = geom
                    st.session_state["datos_json"] = None
                    st.success("Lote confirmado.")
                else:
                    st.warning("Dibujá un polígono primero.")

        with tab_archivo:
            subidos = st.file_uploader(
                "Subir .shp (zip) o .geojson",
                type=["zip", "geojson", "shp"],
                accept_multiple_files=True,
            )
            if st.button("📌 Cargar al mapa", use_container_width=True, key="btn_upload"):
                if subidos:
                    geom = cargar_aoi_desde_archivo(subidos)
                    if geom:
                        st.session_state["aoi"] = geom
                        st.session_state["datos_json"] = None
                        st.success("Archivo cargado.")
                    else:
                        st.error("No se encontró geometría válida.")
                else:
                    st.warning("Seleccioná un archivo primero.")

        # Estado del lote
        if st.session_state.get("aoi"):
            try:
                shp     = shape(st.session_state["aoi"])
                area_ha = shp.area * 111320 ** 2 / 10000
                st.success(f"✅ Lote definido — {area_ha:.1f} ha")
            except Exception:
                st.success("✅ Lote definido")

        st.divider()

        # ── Botón analizar ──
        run_btn = st.button(
            "🛰️ Analizar clima del lote",
            use_container_width=True,
            type="primary",
            disabled=not st.session_state.get("aoi"),
        )

    return anios, t_base_ui, run_btn


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════
def main():
    global T_BASE
    # ── Session state defaults ──
    for key, val in {
        "aoi": None, "datos_json": None, "gee_ok": False,
        "ultimo_dibujo": None, "latitud": -30.0,
        "map_center": [-32.0, -63.0], "map_zoom": 5,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # ── GEE init ──
    if not st.session_state["gee_ok"]:
        ok, err = init_gee()
        st.session_state["gee_ok"] = ok
        if not ok:
            st.error(f"❌ Error al conectar con GEE: {err}")
            st.stop()

    # ── Sidebar ──
    anios, t_base_ui, run_btn = render_sidebar()

    # ── Análisis ──
    if run_btn and st.session_state["aoi"]:
        aoi_json  = json.dumps(st.session_state["aoi"])
        fecha_fin = pd.Timestamp.today().normalize()
        fecha_ini = fecha_fin - pd.DateOffset(years=anios)

        # Calcular latitud del centroide para ETo
        shp     = shape(st.session_state["aoi"])
        latitud = shp.centroid.y
        st.session_state["latitud"] = latitud
        st.session_state["map_center"] = [shp.centroid.y, shp.centroid.x]
        st.session_state["map_zoom"]   = 13

        with st.spinner("⏳ Descargando ERA5-Land desde Google Earth Engine (puede tardar 1–2 min)..."):
            try:
                datos_json = descargar_era5(
                    aoi_json,
                    fecha_ini.strftime("%Y-%m-%d"),
                    fecha_fin.strftime("%Y-%m-%d"),
                )
                st.session_state["datos_json"] = datos_json
                st.session_state["t_base"]     = t_base_ui
            except Exception as e:
                st.error(f"Error al descargar ERA5: {e}")

    # ════════════════════════════════════════════════════════
    # PANTALLA PRINCIPAL
    # ════════════════════════════════════════════════════════
    if st.session_state["datos_json"] is None:
        # Sin datos: mapa de dibujo
        st.markdown("### 📍 Definí el área de interés")
        st.caption("Dibujá un polígono en el mapa, confirmá en la barra lateral y presioná **Analizar clima del lote**.")

        mapa_inicial = build_mapa(
            center=st.session_state["map_center"],
            zoom=st.session_state["map_zoom"],
            aoi_geojson=st.session_state.get("aoi"),
            allow_draw=True,
        )
        resultado = st_folium(mapa_inicial, height=500, use_container_width=True,
                              returned_objects=["last_active_drawing"])
        if resultado and resultado.get("last_active_drawing"):
            st.session_state["ultimo_dibujo"] = resultado["last_active_drawing"]

        if not st.session_state["gee_ok"]:
            st.warning("Verificá las credenciales GEE en secrets.toml.")
        elif not st.session_state.get("aoi"):
            st.info("👈 Dibujá o subí un lote en la barra lateral para empezar.")
        return

    # ════════════════════════════════════════════════════════
    # DASHBOARD CON DATOS
    # ════════════════════════════════════════════════════════
    df_raw = pd.read_json(io.StringIO(st.session_state["datos_json"]))
    df_raw.index = pd.to_datetime(df_raw.index, unit="ms")
    df_raw.attrs["latitud"] = st.session_state.get("latitud", -30.0)

    # Actualizar T_BASE si el usuario la cambió en el sidebar
    t_base_actual = st.session_state.get("t_base", T_BASE)
    T_BASE = t_base_actual

    # Agregación mensual
    df_mensual = agregar_mensual(df_raw)

    # Mes actual (último mes completo disponible)
    fecha_max    = df_raw.index.max()
    daily_inicio = fecha_max.replace(day=1).strftime("%Y-%m-%d")
    daily_fin    = fecha_max.strftime("%Y-%m-%d")
    df_diario    = procesar_diario(df_raw, daily_inicio, daily_fin)

    # ── Métricas del último mes ──
    ultimo = df_mensual.iloc[-1]
    st.markdown(f"### 📊 Resumen — {ultimo['mes_año'].strftime('%B %Y').capitalize()}")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("🌧️ Lluvia",      f"{ultimo['precip']:.1f} mm")
    m2.metric("💧 ETo PM",      f"{ultimo['eto']:.1f} mm")
    m3.metric("⚖️ Balance",     f"{ultimo['balance_hidro']:+.1f} mm")
    m4.metric("🌡️ T. media",    f"{ultimo['t_med']:.1f} °C")
    m5.metric("💨 HR media",    f"{ultimo['hr']:.0f} %")
    m6.metric("☀️ Radiación",   f"{ultimo['rad']:.0f} MJ/m²")

    st.divider()

    # ── Gráficos ──
    col_izq, col_der = st.columns([3, 1])

    with col_izq:
        st.plotly_chart(grafico_climatico(df_mensual), use_container_width=True)
        st.plotly_chart(grafico_balance(df_mensual),   use_container_width=True)
        st.plotly_chart(grafico_diario(df_diario),     use_container_width=True)
        st.plotly_chart(grafico_hr_viento(df_mensual), use_container_width=True)

    with col_der:
        st.markdown("#### 🗺️ Lote analizado")
        mapa_resultado = build_mapa(
            center=st.session_state["map_center"],
            zoom=st.session_state["map_zoom"],
            aoi_geojson=st.session_state["aoi"],
        )
        st_folium(mapa_resultado, height=320, use_container_width=True,
                  returned_objects=[], key="mapa_resultado")

        st.divider()
        st.markdown("#### 📋 Resumen histórico")
        resumen = df_mensual[["mes_año", "precip", "eto", "balance_hidro", "t_med", "gda"]].copy()
        resumen["mes_año"] = resumen["mes_año"].dt.strftime("%b %Y")
        resumen.columns    = ["Mes", "Lluvia mm", "ETo mm", "Balance mm", "T°C", "GDA"]
        st.dataframe(
            resumen.style.format({
                "Lluvia mm": "{:.1f}", "ETo mm": "{:.1f}",
                "Balance mm": "{:+.1f}", "T°C": "{:.1f}", "GDA": "{:.0f}",
            }),
            use_container_width=True,
            height=280,
        )

        # ── Descarga CSV ──
        csv = df_raw.reset_index().rename(columns={"fecha": "Fecha"}).to_csv(index=False)
        st.download_button(
            "⬇️ Descargar datos diarios (.csv)",
            data=csv,
            file_name="era5_diario.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # ── Footer ──
    st.divider()
    st.caption(
        f"🛰️ ERA5-Land (ECMWF) · COPERNICUS/ERA5_LAND/DAILY_AGGR · "
        f"Período: {df_mensual['mes_año'].iloc[0].strftime('%b %Y')} → "
        f"{df_mensual['mes_año'].iloc[-1].strftime('%b %Y')} · "
        f"{len(df_mensual)} meses · T base GDA: {T_BASE:.0f} °C"
    )


if __name__ == "__main__":
    main()
