"""
🌱 USA Soil Spatial Analysis — Streamlit App
Author: Ariel Macías | Agronomist · GIS & Remote Sensing Data Scientist

Tabs:
  0 — AOI Definition          (upload / paste GeoJSON field boundary)
  1 — Soil Information        (choropleth texture & MUKey maps, agronomic report, depth profiles)
  2 — Topographic Models      (contour map, hillshade)
  3 — 3D Projection           (surface + satellite-textured mesh)

Data sources:
  • USDA-NRCS Soil Data Mart WFS  (soil polygons)
  • USDA Soil Data Access API      (tabular horizon data)
  • Terrarium tiles (AWS)          (elevation / DEM)
  • Esri World Imagery             (satellite texture)

Note: USDA-NRCS data is restricted to United States territory.
"""

import streamlit as st

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="USA Soil Analysis",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Inject minimal CSS ───────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        /* Tab bar styling */
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 8px 20px;
            border-radius: 6px 6px 0 0;
            font-weight: 600;
        }
        /* Metric cards */
        [data-testid="metric-container"] {
            background: #1a1a2e;
            border: 1px solid #2d2d44;
            border-radius: 8px;
            padding: 10px 14px;
        }
        /* Download buttons */
        .stDownloadButton button {
            width: 100%;
        }
        /* Header */
        h1 { color: #4CAF50 !important; }
        h2 { color: #81C784 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Header ───────────────────────────────────────────────────────────────────
st.title("🌱 USA Soil Spatial Analysis")
st.caption(
    "USDA-NRCS Soil Data Mart · Terrarium DEM · Esri World Imagery  |  "
    "**US territory only**  |  Author: Ariel Macías"
)
st.divider()

# ── Session state (shared across tabs) ───────────────────────────────────────
if "app_state" not in st.session_state:
    st.session_state["app_state"] = {}

state = st.session_state["app_state"]

# ── Tab routing ──────────────────────────────────────────────────────────────
tab_aoi_ui, tab_soils_ui, tab_topo_ui, tab_3d_ui = st.tabs([
    "📍 AOI Definition",
    "🌱 Soil Information",
    "🏔️ Topographic Models",
    "🌐 3D Projection",
])

# Lazy imports inside each tab to keep startup fast
with tab_aoi_ui:
    from tabs.tab_aoi import render as render_aoi
    render_aoi(state)

with tab_soils_ui:
    from tabs.tab_soils import render as render_soils
    render_soils(state)

with tab_topo_ui:
    from tabs.tab_topo import render as render_topo
    render_topo(state)

with tab_3d_ui:
    from tabs.tab_3d import render as render_3d
    render_3d(state)

# ── Footer ───────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "Data: USDA-NRCS SDA · AWS Terrarium · Esri World Imagery  |  "
    "Built with Streamlit · GeoPandas · Plotly · Folium"
)
