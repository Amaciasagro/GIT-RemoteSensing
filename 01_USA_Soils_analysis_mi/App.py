# ============================================================
# 🇺🇸 USA Soil & Topography Analyzer — Streamlit App
# ============================================================

import streamlit as st
import ee
import folium
import geopandas as gpd
import pandas as pd
import numpy as np
import requests
import io, json, zipfile, tempfile, os, math
from PIL import Image
from io import BytesIO
from folium.plugins import Draw
from streamlit_folium import st_folium
import plotly.graph_objects as go
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import unary_union
from google.oauth2.credentials import Credentials

# ── Configuración de Página ──
st.set_page_config(page_title="USA Soil Analyzer", page_icon="🌱", layout="wide")

# ── Constantes y Paletas ──
MAX_DEPTH_CM = 80
TEXTURE_PALETTE = {
    'Clay': '#8B0000', 'Silty clay': '#B22222', 'Sandy clay': '#CD5C5C',
    'Clay loam': '#D2691E', 'Sandy clay loam': '#A0522D', 'Silty clay loam': '#C68642',
    'Silt loam': '#DEB887', 'Silt': '#F5DEB3', 'Loam': '#8FBC8F',
    'Loamy sand': '#F4A460', 'Sand': '#EDC9Af', 'No Data': '#AAAAAA'
}

# ════════════════════════════════════════════════════════════
# 1. INICIALIZACIÓN Y HELPERS GEE/AOI
# ════════════════════════════════════════════════════════════
@st.cache_resource
def init_gee():
    try:
        project_id = st.secrets.get("EARTHENGINE_PROJECT")
        auth_info = st.secrets["google_auth"]
        creds = Credentials(
            token=None, refresh_token=auth_info["refresh_token"],
            client_id=auth_info["client_id"], client_secret=auth_info["client_secret"],
            token_uri="https://oauth2.googleapis.com/token"
        )
        ee.Initialize(creds, project=project_id)
        return True
    except Exception:
        return False

def load_aoi_from_file(uploaded_files):
    tmp = tempfile.mkdtemp()
    for f in uploaded_files:
        with open(os.path.join(tmp, f.name), "wb") as fp:
            fp.write(f.read())
    for fname in os.listdir(tmp):
        if fname.endswith(".zip"):
            with zipfile.ZipFile(os.path.join(tmp, fname), "r") as z:
                z.extractall(tmp)
    valid = [f for f in os.listdir(tmp) if f.endswith((".shp", ".geojson"))]
    if not valid: return None
    gdf = gpd.read_file(os.path.join(tmp, valid[0])).to_crs(epsg=4326)
    return mapping(unary_union(gdf.geometry))

# ════════════════════════════════════════════════════════════
# 2. FUNCIONES USDA (ESPACIAL + TABULAR)
# ════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def fetch_usda_soils(aoi_json):
    geom = shape(json.loads(aoi_json))
    minx, miny, maxx, maxy = geom.bounds
    
    wfs_url = "https://sdmdataaccess.nrcs.usda.gov/Spatial/SDMNAD83Geographic.wfs"
    params = {
        'SERVICE': 'WFS', 'VERSION': '1.0.0', 'REQUEST': 'GetFeature',
        'TYPENAME': 'MapunitPoly', 'BBOX': f"{minx},{miny},{maxx},{maxy}", 
        'SRSNAME': 'EPSG:4326', 'OUTPUTFORMAT': 'GML3'
    }
    
    # 3 reintentos para la descarga espacial
    max_intentos = 3
    for intento in range(max_intentos):
        try:
            res = requests.get(wfs_url, params=params, verify=False, timeout=60)
            if res.status_code == 200:
                gdf_soils = gpd.read_file(io.BytesIO(res.content))
                gdf_field = gpd.GeoDataFrame(index=[0], crs='epsg:4326', geometry=[geom])
                return gpd.overlay(gdf_soils, gdf_field, how='intersection')
        except requests.exceptions.Timeout:
            if intento == max_intentos - 1:
                st.error("El servidor WFS tardó demasiado. Probá de nuevo.")
                return None
            continue
        except Exception:
            return None
    return None


@st.cache_data(show_spinner=False)
def fetch_and_process_sda_data(mukeys):
    """Consulta la base tabular SDA por SQL y calcula promedios a 80cm."""
    mukey_str = ",".join([f"'{m}'" for m in mukeys])
    query = f"""
    SELECT c.mukey, c.compname, c.comppct_r, 
           h.hzdept_r, h.hzdepb_r, h.sandtotal_r, h.silttotal_r, h.claytotal_r,
           h.om_r, h.cec7_r, h.ph1to1h2o_r, h.ec_r, h.sar_r, t.texcl
    FROM component c
    LEFT JOIN chorizon h ON c.cokey = h.cokey
    LEFT JOIN chtexturegrp tg ON h.chkey = tg.chkey AND tg.rvindicator = 'Yes'
    LEFT JOIN chtexture t ON tg.chtgkey = t.chtgkey
    WHERE c.mukey IN ({mukey_str}) AND c.majcompflag = 'Yes'
    """
    
    url = "https://sdmdataaccess.nrcs.usda.gov/Tabular/post.rest"
    
    try:
        # AQUÍ ESTÁ LA CORRECCIÓN: Usamos POST, enviamos la 'query' y agregamos el timeout
        res = requests.post(url, data={'query': query, 'format': 'JSON'}, timeout=60)
        
        if res.status_code != 200 or 'Table' not in res.json():
            return pd.DataFrame()
            
        data = res.json()['Table']
        cols = ["mukey", "compname", "comppct", "top", "bottom", "sand", "silt", "clay", "om", "cec", "ph", "ec", "sar", "texture"]
        
        df = pd.DataFrame(data, columns=cols).dropna(subset=["top", "bottom"]).astype({c: float for c in cols[2:13]})
        
        # ── Lógica de Promedio Ponderado hasta 80cm (dejá la que ya tenías acá abajo) ──
        results = []
        for mukey, group in df.groupby('mukey'):
            dom_comp = group.loc[group['comppct'].idxmax()]
            comp_name = dom_comp['compname']
            
            hz_df = group[group['compname'] == comp_name].copy()
            hz_df = hz_df[hz_df['top'] < 80]
            hz_df['bottom_eff'] = hz_df['bottom'].clip(upper=80)
            hz_df['weight'] = hz_df['bottom_eff'] - hz_df['top']
            total_w = hz_df['weight'].sum()
            
            if total_w > 0:
                row_res = {'MUKey': mukey, 'Serie': comp_name}
                for col in ['sand', 'silt', 'clay', 'om', 'cec', 'ph', 'ec', 'sar']:
                    val = (hz_df[col] * hz_df['weight']).sum() / total_w
                    row_res[col.capitalize()] = round(val, 2)
                
                top_hz = hz_df.loc[hz_df['top'].idxmin()]
                row_res['Textura'] = top_hz['texture'] if pd.notnull(top_hz['texture']) else 'No Data'
                results.append(row_res)
                
        return pd.DataFrame(results)

    except requests.exceptions.Timeout:
        st.warning("El servidor tabular SDA tardó demasiado en responder.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error en consulta SDA: {e}")
        return pd.DataFrame()
        
    data = res.json()['Table']
    cols = ["mukey", "compname", "comppct", "top", "bottom", "sand", "silt", "clay", "om", "cec", "ph", "ec", "sar", "texture"]
    df = pd.DataFrame(data, columns=cols).dropna(subset=["top", "bottom"]).astype({c: float for c in cols[2:13]})
    
    # Lógica de Promedio Ponderado hasta MAX_DEPTH_CM
    results = []
    for mukey, group in df.groupby('mukey'):
        # Tomar el componente dominante
        dom_comp = group.loc[group['comppct'].idxmax()]
        comp_name = dom_comp['compname']
        
        # Filtrar horizontes del componente dominante dentro de los 80cm
        hz_df = group[group['compname'] == comp_name].copy()
        hz_df = hz_df[hz_df['top'] < MAX_DEPTH_CM]
        hz_df['bottom_eff'] = hz_df['bottom'].clip(upper=MAX_DEPTH_CM)
        hz_df['weight'] = hz_df['bottom_eff'] - hz_df['top']
        total_w = hz_df['weight'].sum()
        
        if total_w > 0:
            row_res = {'MUKey': mukey, 'Serie': comp_name}
            # Promedios numéricos
            for col in ['sand', 'silt', 'clay', 'om', 'cec', 'ph', 'ec', 'sar']:
                val = (hz_df[col] * hz_df['weight']).sum() / total_w
                row_res[col.capitalize()] = round(val, 2)
            
            # Textura superficial (del horizonte más alto)
            top_hz = hz_df.loc[hz_df['top'].idxmin()]
            row_res['Textura'] = top_hz['texture'] if pd.notnull(top_hz['texture']) else 'No Data'
            results.append(row_res)
            
    return pd.DataFrame(results)

def color_alerts(val, col_name):
    """Aplica colores de alerta a las celdas del DataFrame."""
    color = ''
    if pd.isna(val): return ''
    if col_name == 'Ph':
        if val > 8.0: color = 'background-color: #ffcccc; color: #800000' # Alcalino (Rojo)
        elif val < 5.5: color = 'background-color: #fff0b3; color: #806000' # Ácido (Amarillo)
    elif col_name == 'Ec':
        if val > 2.0: color = 'background-color: #ffcccc; color: #800000' # Salino (Rojo)
    elif col_name == 'Sar':
        if val > 13.0: color = 'background-color: #ffcccc; color: #800000' # Sódico (Rojo)
    elif col_name == 'Om':
        if val < 1.5: color = 'background-color: #e6f2ff; color: #004080' # Baja MO (Azul claro)
    return color

# ════════════════════════════════════════════════════════════
# 3. FUNCIONES DE TOPOGRAFÍA
# ════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def fetch_elevation_data(aoi_json):
    geom = shape(json.loads(aoi_json))
    minx, miny, maxx, maxy = geom.bounds
    zoom = 14
    
    def latlon_to_tile(lat, lon, z):
        n = 2 ** z
        x = int((lon + 180) / 360 * n)
        y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
        return x, y

    t_min_x, t_min_y = latlon_to_tile(maxy, minx, zoom)
    t_max_x, t_max_y = latlon_to_tile(miny, maxx, zoom)
    
    tile_cols = t_max_x - t_min_x + 1
    tile_rows = t_max_y - t_min_y + 1
    mosaic = np.zeros((tile_rows * 256, tile_cols * 256, 3), dtype=np.float32)

    for ty in range(t_min_y, t_max_y + 1):
        for tx in range(t_min_x, t_max_x + 1):
            url = f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{tx}/{ty}.png'
            r = requests.get(url)
            if r.status_code == 200:
                img = np.array(Image.open(BytesIO(r.content)).convert('RGB'), dtype=np.float32)
                mosaic[(ty - t_min_y)*256:(ty - t_min_y + 1)*256, (tx - t_min_x)*256:(tx - t_min_x + 1)*256] = img

    elevation = (mosaic[:,:,0] * 256 + mosaic[:,:,1] + mosaic[:,:,2] / 256) - 32768
    return elevation, (t_min_x, t_max_x, t_min_y, t_max_y, zoom)

# ════════════════════════════════════════════════════════════
# 4. INTERFAZ PRINCIPAL
# ════════════════════════════════════════════════════════════
def main():
    if "aoi" not in st.session_state: st.session_state["aoi"] = None
    init_gee()

    with st.sidebar:
        st.markdown("## 🇺🇸 USA Soil Analyzer")
        st.caption("USDA-NRCS SDA & Topography")
        st.divider()
        st.markdown("### 📍 Área de Interés")
        
        aoi_tab_draw, aoi_tab_file = st.tabs(["✏️ Dibujar", "📂 Subir archivo"])
        with aoi_tab_draw:
            if st.button("✅ Confirmar dibujo", use_container_width=True, type="primary"):
                if st.session_state.get("last_drawn"):
                    st.session_state["aoi"] = st.session_state["last_drawn"].get("geometry") or st.session_state["last_drawn"]
        with aoi_tab_file:
            uploaded = st.file_uploader("Subir .shp (zip) o .geojson", type=["zip", "geojson", "shp"])
            if st.button("📌 Cargar al mapa", use_container_width=True):
                if uploaded: st.session_state["aoi"] = load_aoi_from_file([uploaded])

        if st.session_state["aoi"]:
            area_ha = shape(st.session_state["aoi"]).area * 111320**2 / 10000
            st.success(f"✅ Lote: {area_ha:.1f} ha")
            st.download_button("⬇️ Descargar Polígono", json.dumps(st.session_state["aoi"]), "lote.geojson", "application/json", use_container_width=True)

    if not st.session_state["aoi"]:
        st.markdown("### 📍 Definí el área de interés (Solo EE.UU.)")
        m = folium.Map(location=[33.58, -101.84], zoom_start=12) # Centrado por defecto en Lubbock, TX
        Draw(draw_options={"polygon": True, "rectangle": True, "polyline": False, "circle": False, "marker": False}).add_to(m)
        res = st_folium(m, height=500, use_container_width=True, returned_objects=["last_active_drawing"])
        if res and res.get("last_active_drawing"): st.session_state["last_drawn"] = res["last_active_drawing"]
        return

    tab_suelos, tab_topo = st.tabs(["🌱 Análisis Edáfico (SDA)", "⛰️ Topografía y DEM 3D"])

    # --------------------------------------------------------
    # TAB 1: SUELOS (MAPA + TABLA CON ALERTAS)
    # --------------------------------------------------------
    with tab_suelos:
        aoi_json = json.dumps(st.session_state["aoi"])
        with st.spinner("Consultando bases de datos USDA (WFS y SDA)..."):
            gdf_espacial = fetch_usda_soils(aoi_json)
            
            if gdf_espacial is not None and not gdf_espacial.empty:
                mukeys = gdf_espacial['mukey'].unique().tolist()
                df_tabular = fetch_and_process_sda_data(mukeys)
                
                if not df_tabular.empty:
                    # Unir datos espaciales con tabulares para colorear el mapa
                    # Asegurarnos de que ambas columnas sean texto (string) antes de unirlas
                    gdf_espacial['mukey'] = gdf_espacial['mukey'].astype(str)
                    df_tabular['MUKey'] = df_tabular['MUKey'].astype(str)

                    # Unir datos espaciales con tabulares para colorear el mapa
                    gdf_final = gdf_espacial.merge(df_tabular, left_on='mukey', right_on='MUKey', how='left')
                    
                    st.markdown("### 🗺️ Mapa de Suelos por Textura")
                    m_soil = folium.Map(location=[shape(st.session_state["aoi"]).centroid.y, shape(st.session_state["aoi"]).centroid.x], zoom_start=14)
                    folium.TileLayer('CartoDB positron').add_to(m_soil)
                    
                    def get_color(feature):
                        tex = feature['properties'].get('Textura', 'No Data')
                        # Limpiar string para match seguro
                        tex_clean = str(tex).capitalize() if tex else 'No Data'
                        return TEXTURE_PALETTE.get(tex_clean, '#AAAAAA')

                    folium.GeoJson(
                        gdf_final.__geo_interface__,
                        style_function=lambda x: {'fillColor': get_color(x), 'color': '#333', 'weight': 1, 'fillOpacity': 0.7},
                        tooltip=folium.GeoJsonTooltip(fields=['Serie', 'Textura', 'MUKey'], aliases=['Serie:', 'Textura superficial:', 'MUKey:'])
                    ).add_to(m_soil)
                    folium.GeoJson(st.session_state["aoi"], style_function=lambda x: {'color': 'blue', 'fillOpacity': 0, 'weight': 2}).add_to(m_soil)
                    st_folium(m_soil, height=400, use_container_width=True)

                    # Mostrar Tabla Interactiva con alertas visuales
                    st.markdown(f"### 📊 Propiedades Físico-Químicas (0-{MAX_DEPTH_CM} cm)")
                    st.caption("Valores críticos resaltados: pH > 8.0 (Rojo) | pH < 5.5 (Amarillo) | CE > 2.0 (Rojo) | MO < 1.5% (Azul)")
                    
                    # Aplicar estilos
                    styled_df = df_tabular.style.apply(
                        lambda row: [color_alerts(val, col) for col, val in row.items()], axis=1
                    ).format(precision=2)
                    
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)
                    
                    # Botón de Descarga Excel
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                        df_tabular.to_excel(writer, index=False, sheet_name='Propiedades_Suelo')
                    st.download_button("⬇️ Descargar Tabla (Excel)", buffer.getvalue(), "usda_analisis_suelos.xlsx", "application/vnd.ms-excel")
                else:
                    st.warning("Se encontró el polígono, pero la USDA no tiene datos tabulares para este suelo.")
            else:
                st.error("No se encontraron datos de suelo. Verificá que el polígono esté dentro de Estados Unidos.")

    # --------------------------------------------------------
    # TAB 2: TOPOGRAFÍA
    # --------------------------------------------------------
    with tab_topo:
        st.markdown("### ⛰️ Modelo Digital de Elevación (DEM)")
        with st.spinner("Generando maqueta topográfica 3D..."):
            elevation, tile_bounds = fetch_elevation_data(aoi_json)
            geom = shape(st.session_state["aoi"])
            x_coords = np.linspace(geom.bounds[0], geom.bounds[2], elevation.shape[1])
            y_coords = np.linspace(geom.bounds[1], geom.bounds[3], elevation.shape[0])
            
            fig_3d = go.Figure(data=[go.Surface(z=elevation, x=x_coords, y=y_coords, colorscale='earth')])
            fig_3d.update_layout(
                scene=dict(xaxis_title='Longitud', yaxis_title='Latitud', zaxis_title='Elevación (m)', aspectratio=dict(x=1, y=1, z=0.2)),
                margin=dict(l=0, r=0, b=0, t=0), template="plotly_dark", height=500
            )
            st.plotly_chart(fig_3d, use_container_width=True)
            st.download_button("⬇️ Descargar Modelo 3D (HTML)", fig_3d.to_html(), "modelo_3d.html", "text/html")

if __name__ == "__main__":
    main()