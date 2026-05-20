# ============================================================
# 🌿 Crop Monitor — Streamlit App
# Autor: Ariel Macías | Agrónomo · GIS & Remote Sensing
# ============================================================

import streamlit as st
import ee
import folium
from folium.plugins import Draw, DualMap
from streamlit_folium import st_folium
import geopandas as gpd
import pandas as pd
import plotly.graph_objects as go
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
import json, io, zipfile, tempfile, os, warnings
from google.oauth2.credentials import Credentials
warnings.filterwarnings("ignore")

# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="Crop Monitor · LAI & NDVI",
    page_icon="🌿",
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

# ── Marca de Agua ──
st.markdown("""
    <style>
    .watermark {
        position: fixed;
        bottom: 15px;
        right: 15px;
        opacity: 0.5;
        font-size: 14px;
        color: #7a99b8;
        z-index: 9999;
        pointer-events: none;
        background-color: rgba(13, 21, 32, 0.7);
        padding: 5px 10px;
        border-radius: 5px;
    }
    </style>
    <div class="watermark">© 2026 Ariel Macías | Ingeniero agrónomo & Analista SIG</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# CONSTANTES DE VISUALIZACIÓN
# ════════════════════════════════════════════════════════════
VIS = {
    "NDVI":       {"min": 0.1, "max": 0.8,  "palette": ["red", "yellow", "green"]},
    "LAI":        {"min": 0,   "max": 6,    "palette": ["#f7fbff","#c6dbef","#6baed6","#2171b5","#08306b"]},
    "EVI":        {"min": 0,   "max": 0.8,  "palette": ["#ffffe5","#78c679","#004529"]},
    "SAVI":       {"min": 0,   "max": 0.7,  "palette": ["#fff7bc","#d9f0a3","#238443"]},
    "NDWI":       {"min": -0.5,"max": 0.5,  "palette": ["#d7191c","#ffffbf","#2c7bb6"]},
    "TrueColor":  {"min": 0,   "max": 3000, "bands": ["B4","B3","B2"]},
    "FalseColor": {"min": 0,   "max": 5000, "bands": ["B8","B4","B3"]},
}
LAYER_LABELS = {
    "NDVI": "NDVI", "LAI": "LAI", "EVI": "EVI",
    "SAVI": "SAVI", "NDWI": "NDWI",
    "TrueColor": "True Color", "FalseColor": "Falso Color NIR",
}

# ════════════════════════════════════════════════════════════
# GEE — INICIALIZACIÓN
# ════════════════════════════════════════════════════════════
def init_gee(project_name=None):
    try:
        if "EARTHENGINE_TOKEN" in st.secrets:
            token_data = json.loads(st.secrets["EARTHENGINE_TOKEN"])
            credenciales = Credentials(
                token=None,
                refresh_token=token_data.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=token_data.get("scopes")
            )
            if project_name:
                ee.Initialize(credentials=credenciales, project=project_name)
            else:
                ee.Initialize(credentials=credenciales)
            return True, None
        else:
            if project_name:
                ee.Initialize(project=project_name)
            else:
                ee.Initialize()
            return True, None
    except json.JSONDecodeError as e:
        return False, f"Formato inválido en secrets.toml. Revisá las comillas: {e}"
    except Exception as e:
        return False, str(e)


# ════════════════════════════════════════════════════════════
# GEE — CÁLCULO DE ÍNDICES
# ════════════════════════════════════════════════════════════
def make_add_indices(k: float, L: float):
    def add_indices(image):
        # NDVI
        ndvi   = image.normalizedDifference(["B8","B4"]).rename("NDVI")
        # LAI  (Beer-Lambert)
        ndvi_c = ndvi.max(ee.Image(0)).min(ee.Image(0.95))
        lai    = (ee.Image(1)
                  .subtract(ndvi_c.divide(0.95))
                  .log().multiply(-1.0 / k)
                  .max(0).rename("LAI"))
        # EVI
        nir, red, blue = (image.select(b).divide(10000) for b in ["B8","B4","B2"])
        evi = (nir.subtract(red).multiply(2.5)
               .divide(nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1))
               .rename("EVI"))
        # SAVI
        savi = (nir.subtract(red)
                .divide(nir.add(red).add(L))
                .multiply(1 + L).rename("SAVI"))
        # NDWI
        ndwi = image.normalizedDifference(["B3","B8"]).rename("NDWI")
        return (image.addBands([ndvi, lai, evi, savi, ndwi])
                .copyProperties(image, ["system:time_start"]))
    return add_indices


# ════════════════════════════════════════════════════════════
# GEE — EXTRACCIÓN DE ESTADÍSTICAS MENSUALES
# ════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def get_monthly_data(aoi_json: str, start: str, end: str,
                     max_clouds: int, k: float, L: float) -> str:
    """Devuelve JSON del DataFrame mensual (cacheado por parámetros)."""
    lote_geom = ee.Geometry(json.loads(aoi_json))
    s2_col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
              .filterBounds(lote_geom)
              .filterDate(start, end)
              .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_clouds))
              .map(make_add_indices(k, L)))

    def extract_stats(image):
        stats = image.select(["NDVI","LAI","EVI","SAVI","NDWI"]).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=lote_geom, scale=10, maxPixels=1e9)
        return ee.Feature(None, {
            "date": ee.Date(image.get("system:time_start")).format("YYYY-MM-dd"),
            **{idx: stats.get(idx) for idx in ["NDVI","LAI","EVI","SAVI","NDWI"]}
        })

    features = ee.FeatureCollection(s2_col.map(extract_stats)).getInfo()["features"]
    datos = [
        {"Fecha": pd.to_datetime(f["properties"]["date"]),
         **{k: f["properties"].get(k) for k in ["NDVI","LAI","EVI","SAVI","NDWI"]}}
        for f in features if f["properties"].get("NDVI") is not None
    ]
    df = pd.DataFrame(datos).set_index("Fecha")
    return df.resample("MS").mean().dropna().to_json()


# ════════════════════════════════════════════════════════════
# GEE — URL DE TILES PARA FOLIUM
# ════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def get_tile_url(aoi_json, start_date, end_date, layer, max_clouds, k, L):
    roi = ee.Geometry(json.loads(aoi_json))
    
    # Filtramos la colección exactamente como pediste: primera imagen que cumpla filtros
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterBounds(roi)
          .filterDate(start_date, end_date)
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', max_clouds))
          .median() # O .first() si prefieres la primera cronológica
          .clip(roi))

    if layer == 'NDVI':
        img = s2.normalizedDifference(['B8', 'B4'])
        vis_params = {'min': 0.1, 'max': 0.8, 'palette': ['red', 'yellow', 'green']}
    elif layer == 'LAI':
        ndvi = s2.normalizedDifference(['B8', 'B4']).max(ee.Image(0)).min(ee.Image(0.95))
        img  = (ee.Image(1).subtract(ndvi.divide(0.95))
                .log().multiply(-1.0 / k).max(0))
        vis_params = {'min': 0, 'max': 6,
                      'palette': ['#f7fbff','#c6dbef','#6baed6','#2171b5','#08306b']}
    elif layer == 'EVI':
        nir  = s2.select('B8').divide(10000)
        red  = s2.select('B4').divide(10000)
        blue = s2.select('B2').divide(10000)
        img  = (nir.subtract(red).multiply(2.5)
                .divide(nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1)))
        vis_params = {'min': 0, 'max': 0.8, 'palette': ['#ffffe5','#78c679','#004529']}
    elif layer == 'SAVI':
        nir = s2.select('B8').divide(10000)
        red = s2.select('B4').divide(10000)
        img = nir.subtract(red).divide(nir.add(red).add(L)).multiply(1 + L)
        vis_params = {'min': 0, 'max': 0.7, 'palette': ['#fff7bc','#d9f0a3','#238443']}
    elif layer == 'NDWI':
        img = s2.normalizedDifference(['B3', 'B8'])
        vis_params = {'min': -0.5, 'max': 0.5, 'palette': ['#d7191c','#ffffbf','#2c7bb6']}
    elif layer == 'TrueColor':
        img = s2.select(['B4', 'B3', 'B2'])
        vis_params = {'min': 0, 'max': 3000, 'gamma': 1.4}
    elif layer in ('FalseColor', 'RGB'):
        img = s2.select(['B8', 'B4', 'B3'])
        vis_params = {'min': 0, 'max': 5000}
    else:
        raise ValueError(f"Capa desconocida: {layer}")

    map_id = img.getMapId(vis_params)
    return map_id['tile_fetcher'].url_format


# ════════════════════════════════════════════════════════════
# MAPA FOLIUM
# ════════════════════════════════════════════════════════════
def build_folium_map(center, zoom, aoi_geojson=None,
                     tile_url=None, layer_name="Capa",
                     rgb_url=None, rgb_label="Satélite dinámico",
                     allow_draw=False) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom, tiles=None)

    # Basemap satelital estático (Esri)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satélite (Esri)", show=True
    ).add_to(m)

    # Satélite dinámico Sentinel-2 RGB del mes (opcional)
    if rgb_url:
        folium.TileLayer(
            tiles=rgb_url, attr="Sentinel-2 RGB",
            name=rgb_label, overlay=True, show=False
        ).add_to(m)

    # Capa de índice
    if tile_url:
        folium.TileLayer(
            tiles=tile_url, attr="Google Earth Engine",
            name=layer_name, overlay=True, show=True, opacity=0.75
        ).add_to(m)

    # Polígono del lote
    if aoi_geojson:
        folium.GeoJson(
            {"type": "Feature", "geometry": aoi_geojson},
            style_function=lambda _: {
                "color": "#ffffff", "weight": 2,
                "dashArray": "6,4", "fillOpacity": 0
            },
            name="Límite del lote"
        ).add_to(m)

    # Control de capas
    folium.LayerControl(collapsed=False).add_to(m)

    # Herramienta de dibujo (solo en modo AOI)
    if allow_draw:
        Draw(
            draw_options={
                "polygon": True, "rectangle": True,
                "polyline": False, "circle": False,
                "marker": False, "circlemarker": False
            },
            edit_options={"edit": False}
        ).add_to(m)

    return m

# ════════════════════════════════════════════════════════════
# MAPA DUAL (ESPEJO) PARA COMPARAR
# ════════════════════════════════════════════════════════════
def build_dual_folium_map(center, zoom, aoi_geojson, url1, url2, name1, name2, url_rgb1=None, url_rgb2=None) -> folium.plugins.DualMap:
    m = DualMap(location=center, zoom_start=zoom, tiles=None)

    # Base satelital estática para ambos mapas
    base_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    folium.TileLayer(tiles=base_url, attr="Esri", name="Satélite estático").add_to(m.m1)
    folium.TileLayer(tiles=base_url, attr="Esri", name="Satélite estático").add_to(m.m2)

    # Satélite dinámico RGB (Oculto por defecto, se activa desde el control de capas)
    if url_rgb1:
        folium.TileLayer(tiles=url_rgb1, attr="Sentinel-2", name="Satélite dinámico Izq", overlay=True, show=False).add_to(m.m1)
    if url_rgb2:
        folium.TileLayer(tiles=url_rgb2, attr="Sentinel-2", name="Satélite dinámico Der", overlay=True, show=False).add_to(m.m2)

    # Capas de GEE (Índices)
    folium.TileLayer(tiles=url1, attr="Google Earth Engine", name=name1, overlay=True, opacity=0.75).add_to(m.m1)
    folium.TileLayer(tiles=url2, attr="Google Earth Engine", name=name2, overlay=True, opacity=0.75).add_to(m.m2)

    # Polígono en ambos
    if aoi_geojson:
        style = lambda _: {"color": "#ffffff", "weight": 2, "dashArray": "6,4", "fillOpacity": 0}
        folium.GeoJson({"type": "Feature", "geometry": aoi_geojson}, style_function=style, name="Límite").add_to(m.m1)
        folium.GeoJson({"type": "Feature", "geometry": aoi_geojson}, style_function=style, name="Límite").add_to(m.m2)

    folium.LayerControl(collapsed=False).add_to(m)
    return m

# ════════════════════════════════════════════════════════════
# GRÁFICO FENOLÓGICO
# ════════════════════════════════════════════════════════════
def build_ndvi_chart(df: pd.DataFrame, selected_idx: int) -> go.Figure:
    colors = ["#3ddc84" if i != selected_idx else "#ffffff"
              for i in range(len(df))]
    sizes  = [5 if i != selected_idx else 10 for i in range(len(df))]
    labels = df.index.strftime("%Y-%m")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=df["NDVI"],
        mode="lines+markers",
        line=dict(color="#3ddc84", width=2),
        marker=dict(size=sizes, color=colors,
                    line=dict(color="#0d1520", width=1)),
        hovertemplate="<b>%{x}</b><br>NDVI: %{y:.3f}<extra></extra>",
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="#0d1520",
        plot_bgcolor="#0d1520",
        font_color="#d4e2f0",
        title=dict(text="Curva Fenológica · NDVI mensual · Sentinel-2",
                   font=dict(size=13), x=0.01),
        xaxis=dict(gridcolor="#1a2d42", showline=False,
                   tickfont=dict(size=10, color="#7a99b8")),
        yaxis=dict(gridcolor="#1a2d42", showline=False, range=[0, 1],
                   tickfont=dict(size=10, color="#7a99b8")),
        hovermode="x unified",
    )
    return fig


# ════════════════════════════════════════════════════════════
# AOI — CARGA DESDE ARCHIVO
# ════════════════════════════════════════════════════════════
def load_aoi_from_file(uploaded_files) -> dict | None:
    tmp = tempfile.mkdtemp()
    for f in uploaded_files:
        with open(os.path.join(tmp, f.name), "wb") as fp:
            fp.write(f.read())

    # Extraer ZIP si viene comprimido
    for fname in os.listdir(tmp):
        if fname.endswith(".zip"):
            with zipfile.ZipFile(os.path.join(tmp, fname), "r") as z:
                z.extractall(tmp)

    valid = [f for f in os.listdir(tmp) if f.endswith((".shp", ".geojson"))]
    if not valid:
        return None

    gdf = gpd.read_file(os.path.join(tmp, valid[0])).to_crs(epsg=4326)
    geom = unary_union(gdf.geometry)
    return mapping(geom)


# ════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════
def render_sidebar():
    with st.sidebar:
        st.markdown("# 🌿 Crop Monitor")
        st.caption("IAF & NDVI · Sentinel-2 · GEE")
        st.divider()
        
        with st.expander("🛠️ Parámetros Agronómicos Avanzados"):
            savi_l = st.slider(
                "Coeficiente Suelo (SAVI L)", 
                min_value=0.0, max_value=1.0, value=0.5, step=0.1,
                help="Diseñado para mitigar el efecto del suelo desnudo (ej: Baja cobertura 0.8; Alta cobertura 0.2. Por defecto 0.5)"
            )
            
            k_ext = st.slider(
                "Coeficiente Extinción (Beer-Lambert k)", 
                min_value=0.1, max_value=1.0, value=0.5, step=0.05,
                help="Cuantifica como la radiación PAR disminuye con la arquitectura de la planta (ej: Maíz 0.4; Soja 0.7)"
            )

            # Acá guardamos los valores para que el resto del programa los use
            st.session_state["savi_l"] = savi_l
            st.session_state["k_ext"] = k_ext
            
        # ── Configuración GEE ──
        st.markdown("### ⚙️ Configuración")
        gee_project = st.secrets.get("EARTHENGINE_PROJECT")
        
        col1, col2 = st.columns(2)
        with col1:
            anios = st.number_input("Años atrás", 1, 5, 3)
            
        with col2:
            max_nubes = st.number_input("Nubes máx (%)", 5, 80, 30, 5)
            
        st.divider()

        # ── AOI ──
        st.markdown("### 📍 Área de Interés")
        aoi_tab_draw, aoi_tab_file = st.tabs(["✏️ Dibujar", "📂 Subir archivo"])

        with aoi_tab_draw:
            st.caption("Dibujá un polígono o rectángulo en el mapa principal y presioná **Confirmar**.")
            if st.button("✅ Confirmar polígono dibujado", use_container_width=True,
                         type="primary", key="btn_confirm"):
                drawn = st.session_state.get("last_drawn")
                if drawn:
                    geom = drawn.get("geometry") or drawn
                    st.session_state["aoi"] = geom
                    st.session_state["data_json"] = None  # resetear datos
                    st.success("Lote confirmado.")
                else:
                    st.warning("Dibujá un polígono primero.")

        with aoi_tab_file:
            uploaded = st.file_uploader(
                "Subir .shp (zip) o .geojson",
                type=["zip", "geojson", "shp"],
                accept_multiple_files=True,
            )
            if st.button("📌 Cargar al mapa", use_container_width=True, key="btn_upload"):
                if uploaded:
                    geom = load_aoi_from_file(uploaded)
                    if geom:
                        st.session_state["aoi"] = geom
                        st.session_state["data_json"] = None
                        st.success("Archivo cargado.")
                    else:
                        st.error("No se encontró geometría válida.")
                else:
                    st.warning("Seleccioná un archivo primero.")

        # Estado del lote
        if st.session_state.get("aoi"):
            try:
                shp = shape(st.session_state["aoi"])
                area_ha = shp.area * 111320**2 / 10000
                st.success(f"✅ Lote definido — {area_ha:.1f} ha")
            except Exception:
                st.success("✅ Lote definido")

        st.divider()
        # ── Botón analizar ──
        run_btn = st.button(
            "🛰️ Analizar lote",
            use_container_width=True,
            type="primary",
            disabled=not (gee_project and st.session_state.get("aoi")),
        )

    return gee_project, anios, max_nubes, k_ext, savi_l, run_btn


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════
def main():
    # ── Session state defaults ──
    for key, val in {
        "aoi": None, "data_json": None, "gee_ok": False,
        "selected_month_idx": 0, "last_drawn": None,
        "map_center": [33.57, -101.85], "map_zoom": 10,
        "mode": "single", "layer1": "NDVI", "layer2": "LAI",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # ── Sidebar ──
    gee_project, anios, max_nubes, k_ext, savi_l, run_btn = render_sidebar()

    # ── GEE Init ──
    if not st.session_state.get("gee_ok", False):
        with st.spinner("Conectando con Earth Engine..."):
            ok, err = init_gee(gee_project)
            st.session_state["gee_ok"] = ok
            if not ok:
                st.error(f"Error GEE: {err}")
                return

    # ── Análisis ──
    if run_btn and st.session_state["gee_ok"] and st.session_state["aoi"]:
        aoi_json = json.dumps(st.session_state["aoi"])
        fecha_fin   = pd.Timestamp.today()
        fecha_ini   = fecha_fin - pd.DateOffset(years=anios)
        with st.spinner("⏳ Procesando imágenes satelitales (puede tardar 1–2 min)..."):
            try:
                data_json = get_monthly_data(
                    aoi_json,
                    fecha_ini.strftime("%Y-%m-%d"),
                    fecha_fin.strftime("%Y-%m-%d"),
                    max_nubes, k_ext, savi_l
                )
                st.session_state["data_json"]          = data_json
                st.session_state["selected_month_idx"] = 0
                st.session_state["analysis_params"]    = dict(
                    max_clouds=max_nubes, k=k_ext, L=savi_l
                )
                # Centrar mapa en el lote
                shp = shape(st.session_state["aoi"])
                cx, cy = shp.centroid.x, shp.centroid.y
                st.session_state["map_center"] = [cy, cx]
                st.session_state["map_zoom"]   = 14
            except Exception as e:
                st.error(f"Error al procesar: {e}")
    
    # ════════════════════════════════════════════════════════
    # PANTALLA PRINCIPAL
    # ════════════════════════════════════════════════════════

    if st.session_state["data_json"] is None:
        # ── Sin datos: mostrar mapa de dibujo ──
        st.markdown("### 📍 Definí el área de interés")
        st.caption("Dibujá un polígono en el mapa, confirmá en la barra lateral y presioná **Analizar lote**.")

        init_map = build_folium_map(
            center=st.session_state["map_center"],
            zoom=st.session_state["map_zoom"],
            aoi_geojson=st.session_state.get("aoi"),
            allow_draw=True
        )
        result = st_folium(init_map, height=500, use_container_width=True,
                           returned_objects=["last_active_drawing"])
        if result and result.get("last_active_drawing"):
            st.session_state["last_drawn"] = result["last_active_drawing"]

        if not gee_project:
            st.info("👈 Ingresá tu **Proyecto GEE** en la barra lateral para empezar.")
        elif not st.session_state["gee_ok"]:
            st.warning("Verificá que tu proyecto GEE sea correcto y que tengas credenciales.")
        return

    # ════════════════════════════════════════════════════════
    # DASHBOARD — con datos
    # ════════════════════════════════════════════════════════
    df = pd.read_json(io.StringIO(st.session_state["data_json"]))
    df.index = pd.to_datetime(df.index, unit="ms")
    params = st.session_state.get("analysis_params", {"max_clouds": 30, "k": 0.5, "L": 0.5})

    # ── Selector de mes ──
    month_labels = df.index.strftime("%Y-%m").tolist()
    sel_idx = st.session_state["selected_month_idx"]
    sel_idx = min(sel_idx, len(month_labels) - 1)

    # ── Gráfico ──
    fig = build_ndvi_chart(df, sel_idx)
    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key="ndvi_chart")
    if event and event.get("selection", {}).get("points"):
        clicked = event["selection"]["points"][0].get("point_index")
        if clicked is not None and clicked != sel_idx:
            st.session_state["selected_month_idx"] = clicked
            st.rerun()

    # Selectbox como alternativa / respaldo
    c1, c2 = st.columns([3, 1])
    with c1:
        new_sel = st.select_slider(
            "Mes seleccionado",
            options=month_labels,
            value=month_labels[sel_idx],
            label_visibility="collapsed",
        )
        new_idx = month_labels.index(new_sel)
        if new_idx != sel_idx:
            st.session_state["selected_month_idx"] = new_idx
            st.rerun()
    with c2:
        st.caption(f"📅 {new_sel}")

    # ── Métricas del mes ──
    row = df.iloc[sel_idx]
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("🟢 NDVI",  f"{row['NDVI']:.3f}")
    mc2.metric("🔵 LAI",   f"{row['LAI']:.2f} m²/m²")
    mc3.metric("🟣 EVI",   f"{row['EVI']:.3f}")
    mc4.metric("🟡 SAVI",  f"{row['SAVI']:.3f}")
    mc5.metric("🩵 NDWI",  f"{row['NDWI']:.3f}")

    st.divider()

    # ── Modo: single / compare ──
    mode_col, _, layer_col = st.columns([2, 1, 4])
    with mode_col:
        mode = st.radio(
            "Modo", ["Capa única", "Comparar dos capas"],
            horizontal=True,
            label_visibility="collapsed",
            index=0 if st.session_state["mode"] == "single" else 1,
        )
        st.session_state["mode"] = "single" if mode == "Capa única" else "compare"

    # Parámetros del mes seleccionado
    sel_date    = df.index[sel_idx]
    month_start = sel_date.strftime("%Y-%m-01")
    month_end   = (sel_date + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")
    aoi_json    = json.dumps(st.session_state["aoi"])
    center      = st.session_state["map_center"]
    zoom        = st.session_state["map_zoom"]

    # ── CAPA ÚNICA ──
    if st.session_state["mode"] == "single":
        with layer_col:
            layer1 = st.selectbox(
                "Capa",
                list(LAYER_LABELS.keys()),
                format_func=lambda k: LAYER_LABELS[k],
                index=list(LAYER_LABELS.keys()).index(st.session_state["layer1"]),
            )
            st.session_state["layer1"] = layer1

        with st.spinner(f"Cargando {LAYER_LABELS[layer1]}..."):
            try:
                url1 = get_tile_url(
                    aoi_json, month_start, month_end, layer1,
                    params["max_clouds"], params["k"], params["L"]
                )
                url_rgb = get_tile_url(
                    aoi_json, month_start, month_end, "TrueColor",
                    params["max_clouds"], params["k"], params["L"]
                )
                
                # ¡FALTABA ESTO! Crear el mapa antes de mandarlo a st_folium
                m = build_folium_map(
                    center=center, 
                    zoom=zoom, 
                    aoi_geojson=st.session_state["aoi"],
                    tile_url=url1, 
                    layer_name=LAYER_LABELS[layer1],
                    rgb_url=url_rgb,
                    rgb_label=f"Satélite dinámico ({month_start[:7]})"
                )
                
                st_folium(m, height=480, use_container_width=True,
                          returned_objects=["center", "zoom"], 
                          key=f"map_single_{sel_idx}_{layer1}")
            except Exception as e:
                st.error(f"Error al cargar capa: {e}")
                
    # ── COMPARAR ──
    else:
        st.markdown("#### ⚙️ Configurar Mapas Independientes")
        col_izq, col_der = st.columns(2)
        
        with col_izq:
            st.markdown("##### ⬅️ Mapa Izquierdo")
            # Selector de fecha independiente (arranca en el mes seleccionado globalmente)
            fecha_izq = st.selectbox("Mes/Año Izq.", month_labels, index=sel_idx, key="fecha_izq")
            layer1 = st.selectbox(
                "Capa Izquierda",
                list(LAYER_LABELS.keys()),
                format_func=lambda k: LAYER_LABELS[k],
                index=list(LAYER_LABELS.keys()).index(st.session_state["layer1"]),
                key="sel_layer1",
            )
            st.session_state["layer1"] = layer1
            
        with col_der:
            st.markdown("##### ➡️ Mapa Derecho")
            # Selector de fecha independiente
            fecha_der = st.selectbox("Mes/Año Der.", month_labels, index=sel_idx, key="fecha_der")
            layer2 = st.selectbox(
                "Capa Derecha",
                list(LAYER_LABELS.keys()),
                format_func=lambda k: LAYER_LABELS[k],
                index=list(LAYER_LABELS.keys()).index(st.session_state["layer2"]),
                key="sel_layer2",
            )
            st.session_state["layer2"] = layer2

        with st.spinner("Cargando capas sincronizadas..."):
            try:
                # Calcular inicio y fin exacto para el mapa izquierdo
                fecha_izq_dt = pd.to_datetime(fecha_izq)
                month_start_izq = fecha_izq_dt.strftime("%Y-%m-01")
                month_end_izq = (fecha_izq_dt + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")

                # Calcular inicio y fin exacto para el mapa derecho
                fecha_der_dt = pd.to_datetime(fecha_der)
                month_start_der = fecha_der_dt.strftime("%Y-%m-01")
                month_end_der = (fecha_der_dt + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")

                # Pedir tiles de los índices
                url1 = get_tile_url(aoi_json, month_start_izq, month_end_izq, layer1, params["max_clouds"], params["k"], params["L"])
                url2 = get_tile_url(aoi_json, month_start_der, month_end_der, layer2, params["max_clouds"], params["k"], params["L"])

                # Pedir tiles RGB (Satélite) para cada lado
                url_rgb_izq = get_tile_url(aoi_json, month_start_izq, month_end_izq, "TrueColor", params["max_clouds"], params["k"], params["L"])
                url_rgb_der = get_tile_url(aoi_json, month_start_der, month_end_der, "TrueColor", params["max_clouds"], params["k"], params["L"])
                
                st.caption(f"Comparando **{LAYER_LABELS[layer1]} ({fecha_izq})** vs **{LAYER_LABELS[layer2]} ({fecha_der})**")
                
                # Creamos el DualMap pasándole las 4 URLs (2 índices y 2 satélites)
                m_dual = build_dual_folium_map(
                    center, zoom, st.session_state["aoi"], 
                    url1, url2, 
                    f"{LAYER_LABELS[layer1]} ({fecha_izq})", 
                    f"{LAYER_LABELS[layer2]} ({fecha_der})",
                    url_rgb_izq, url_rgb_der
                )
                
                # Renderizamos el mapa (la key única fuerza la actualización al cambiar fechas)
                r_dual = st_folium(m_dual, height=480, use_container_width=True, 
                                   key=f"map_dual_{fecha_izq}_{layer1}_{fecha_der}_{layer2}", 
                                   returned_objects=["center", "zoom"])
                
                # Guardamos el centro y el zoom
                if r_dual and r_dual.get("center"):
                    st.session_state["map_center"] = [r_dual["center"]["lat"], r_dual["center"]["lng"]]
                    st.session_state["map_zoom"] = r_dual.get("zoom", zoom)
                    
            except Exception as e:
                st.error(f"Error al cargar capas: {e}")

    # ── Footer ──
    st.divider()
    st.caption(
        f"🛰️ Sentinel-2 SR Harmonized · "
        f"Período: {month_labels[0]} → {month_labels[-1]} · "
        f"{len(df)} meses con datos · "
        f"Nubes ≤ {params['max_clouds']}% · k={params['k']} · L={params['L']}"
    )


if __name__ == "__main__":
    main()