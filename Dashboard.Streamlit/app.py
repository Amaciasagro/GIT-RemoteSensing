import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ariel Macías | GIS & Remote Sensing",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

  html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
  }

  /* Sidebar */
  section[data-testid="stSidebar"] {
    background: #0a1628;
    border-right: 1px solid #1e3a5f;
  }
  section[data-testid="stSidebar"] * { color: #c8d8e8 !important; }
  section[data-testid="stSidebar"] .stRadio label { color: #c8d8e8 !important; }

  /* Main background */
  .main { background: #f0f4f8; }

  /* Hero card */
  .hero-card {
    background: linear-gradient(135deg, #0a1628 0%, #1a3a6c 50%, #0d2444 100%);
    border-radius: 20px;
    padding: 3rem 2.5rem;
    color: white;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
  }
  .hero-card::before {
    content: "";
    position: absolute;
    top: -60px; right: -60px;
    width: 250px; height: 250px;
    background: radial-gradient(circle, rgba(56,189,248,0.15) 0%, transparent 70%);
    border-radius: 50%;
  }
  .hero-name {
    font-family: 'Space Mono', monospace;
    font-size: 2.8rem;
    font-weight: 700;
    letter-spacing: -1px;
    margin: 0;
    line-height: 1.1;
  }
  .hero-title {
    font-size: 1.1rem;
    font-weight: 300;
    color: #93c5fd;
    margin: 0.4rem 0 1.2rem;
    letter-spacing: 2px;
    text-transform: uppercase;
  }
  .hero-bio {
    font-size: 1rem;
    color: #cbd5e1;
    line-height: 1.7;
    max-width: 640px;
  }
  .badge {
    display: inline-block;
    background: rgba(56,189,248,0.2);
    border: 1px solid rgba(56,189,248,0.4);
    color: #7dd3fc;
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    padding: 4px 12px;
    border-radius: 20px;
    margin: 4px 4px 4px 0;
  }

  /* Section headers */
  .section-header {
    font-family: 'Space Mono', monospace;
    font-size: 1.3rem;
    font-weight: 700;
    color: #0a1628;
    border-left: 4px solid #3b82f6;
    padding-left: 12px;
    margin: 2rem 0 1rem;
  }

  /* Metric cards */
  .metric-card {
    background: white;
    border-radius: 14px;
    padding: 1.5rem;
    box-shadow: 0 2px 12px rgba(10,22,40,0.07);
    text-align: center;
  }
  .metric-value {
    font-family: 'Space Mono', monospace;
    font-size: 2.2rem;
    font-weight: 700;
    color: #0a1628;
    line-height: 1;
  }
  .metric-label {
    font-size: 0.82rem;
    color: #64748b;
    margin-top: 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }

  /* Workflow step */
  .workflow-step {
    background: white;
    border-radius: 14px;
    padding: 1.4rem 1.6rem;
    box-shadow: 0 2px 12px rgba(10,22,40,0.07);
    border-left: 4px solid #3b82f6;
    margin-bottom: 1rem;
  }
  .step-number {
    font-family: 'Space Mono', monospace;
    font-size: 0.78rem;
    color: #3b82f6;
    font-weight: 700;
    letter-spacing: 2px;
  }
  .step-title {
    font-size: 1.05rem;
    font-weight: 600;
    color: #0a1628;
    margin: 4px 0;
  }
  .step-desc {
    font-size: 0.9rem;
    color: #64748b;
    line-height: 1.6;
  }

  /* Contact row */
  .contact-link {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: #0a1628;
    color: #93c5fd !important;
    border-radius: 30px;
    padding: 8px 20px;
    font-size: 0.9rem;
    font-family: 'Space Mono', monospace;
    text-decoration: none;
    margin: 4px 4px 4px 0;
    transition: background 0.2s;
  }
  .contact-link:hover { background: #1e3a6c; }

  /* Tool chip */
  .tool-chip {
    display: inline-block;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #1d4ed8;
    font-size: 0.82rem;
    font-weight: 500;
    padding: 5px 14px;
    border-radius: 20px;
    margin: 4px;
  }
</style>
""", unsafe_allow_html=True)

# ── Sidebar navigation ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛰️ **Navigation**")
    st.markdown("---")
    section = st.radio(
        "Go to section:",
        ["🏠 About", "🔬 LAI Workflow", "🌱 Soil Analysis", "📊 Sample Data", "📬 Contact"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.78rem; color:#64748b; line-height:1.8;'>
    <b style='color:#93c5fd;'>Repository</b><br>
    github.com/Amaciasagro/<br>GIT-RemoteSensing<br><br>
    <b style='color:#93c5fd;'>Specialization</b><br>
    GIS · Remote Sensing<br>Precision Agriculture<br>Vegetation Indices<br>Soil Analysis
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════
# SECTION: About
# ═══════════════════════════════════════════════════════════════════
if section == "🏠 About":
    st.markdown("""
    <div class="hero-card">
      <p class="hero-name">Ariel Macías</p>
      <p class="hero-title">Agronomist · GIS & Remote Sensing Analyst</p>
      <p class="hero-bio">
        I bridge field agronomy and geospatial technology — analyzing crop health,
        soil properties, and land use dynamics through satellite imagery, Python scripting,
        and cloud-based geospatial platforms. My work transforms raw spectral data into
        actionable insights for precision agriculture.
      </p>
      <br>
      <span class="badge">🐍 Python</span>
      <span class="badge">🌍 Google Earth Engine</span>
      <span class="badge">🗺️ QGIS</span>
      <span class="badge">📡 Sentinel-2</span>
      <span class="badge">🌿 Vegetation Indices</span>
      <span class="badge">🔬 Soil Science</span>
    </div>
    """, unsafe_allow_html=True)

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    metrics = [
        ("2+", "Years in GIS & RS"),
        ("2", "Published Notebooks"),
        ("10+", "Spectral Indices Used"),
        ("3", "Tools Mastered"),
    ]
    for col, (val, label) in zip([col1, col2, col3, col4], metrics):
        with col:
            st.markdown(f"""
            <div class="metric-card">
              <div class="metric-value">{val}</div>
              <div class="metric-label">{label}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-header">🛠 Tech Stack</div>', unsafe_allow_html=True)
    tools = {
        "Languages & Frameworks": ["Python", "JavaScript (GEE)", "Jupyter Notebook", "Streamlit"],
        "Geospatial Platforms": ["Google Earth Engine", "QGIS", "GDAL", "Rasterio"],
        "Data & Analysis": ["NumPy", "Pandas", "Matplotlib", "Plotly"],
        "Remote Sensing": ["Sentinel-2", "Landsat", "NDVI", "LAI", "EVI", "SAVI"],
    }
    for category, items in tools.items():
        st.markdown(f"**{category}**")
        chips = " ".join(f'<span class="tool-chip">{t}</span>' for t in items)
        st.markdown(chips, unsafe_allow_html=True)
        st.write("")

# ═══════════════════════════════════════════════════════════════════
# SECTION: LAI Workflow
# ═══════════════════════════════════════════════════════════════════
elif section == "🔬 LAI Workflow":
    st.markdown('<div class="section-header">🔬 Leaf Area Index (LAI) Analysis</div>', unsafe_allow_html=True)
    st.markdown("""
    The **LAI notebook** (`LAI.ipynb`) implements a full remote sensing pipeline to estimate
    the Leaf Area Index — a critical biophysical variable that relates to crop canopy cover,
    photosynthesis potential, and biomass estimation.
    """)

    # Workflow steps
    steps = [
        ("STEP 01", "Data Acquisition via Google Earth Engine",
         "Query and filter Sentinel-2 surface reflectance imagery for the area of interest. Apply cloud masking using the SCL band to ensure clean spectral data."),
        ("STEP 02", "Spectral Band Extraction",
         "Extract relevant spectral bands — primarily NIR (Band 8) and Red (Band 4) — for vegetation index computation. Export as GeoTIFF or process directly in GEE."),
        ("STEP 03", "Vegetation Index Computation",
         "Calculate NDVI, EVI, and SAVI indices. These intermediate products feed into the LAI estimation model using empirical or semi-physical relationships."),
        ("STEP 04", "LAI Estimation",
         "Apply the LAI estimation equation derived from spectral indices. Validated against field measurements and literature values for agricultural crops."),
        ("STEP 05", "Spatial Analysis & Visualization",
         "Visualize LAI maps using QGIS and Python (Matplotlib/Plotly). Generate zonal statistics per field parcel and temporal trend charts."),
        ("STEP 06", "Agronomic Interpretation",
         "Translate LAI values into actionable insights: identify under-performing areas, estimate biomass, support irrigation and fertilization decisions."),
    ]
    for num, title, desc in steps:
        st.markdown(f"""
        <div class="workflow-step">
          <div class="step-number">{num}</div>
          <div class="step-title">{title}</div>
          <div class="step-desc">{desc}</div>
        </div>""", unsafe_allow_html=True)

    # Interactive LAI chart
    st.markdown('<div class="section-header">📈 Simulated LAI Temporal Profile</div>', unsafe_allow_html=True)
    st.caption("Representative LAI curve for a soybean crop cycle — illustrates the kind of temporal analysis in the notebook.")

    doy = np.arange(1, 365, 8)
    # Simulate a double crop season
    lai_sim = (
        2.8 * np.exp(-((doy - 120) ** 2) / (2 * 35 ** 2)) +
        3.2 * np.exp(-((doy - 280) ** 2) / (2 * 30 ** 2)) +
        np.random.normal(0, 0.08, len(doy))
    ).clip(0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=doy, y=lai_sim,
        mode="lines+markers",
        line=dict(color="#3b82f6", width=2.5),
        marker=dict(size=5, color="#1d4ed8"),
        fill="tozeroy",
        fillcolor="rgba(59,130,246,0.12)",
        name="LAI",
        hovertemplate="DOY %{x}<br>LAI = %{y:.2f} m²/m²<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="Day of Year (DOY)",
        yaxis_title="LAI (m² / m²)",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="DM Sans", size=13),
        height=320,
        margin=dict(l=50, r=20, t=20, b=50),
        xaxis=dict(showgrid=True, gridcolor="#e2e8f0"),
        yaxis=dict(showgrid=True, gridcolor="#e2e8f0", range=[0, 4.5]),
    )
    st.plotly_chart(fig, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════
# SECTION: Soil Analysis
# ═══════════════════════════════════════════════════════════════════
elif section == "🌱 Soil Analysis":
    st.markdown('<div class="section-header">🌱 Soil Spectral Analysis</div>', unsafe_allow_html=True)
    st.markdown("""
    The **soils_w notebook** (`soils_w.ipynb`) applies remote sensing to characterize
    soil properties through spectral analysis. Bare soil composites from Sentinel-2 and
    Landsat enable mapping of organic matter content, moisture, and textural classes.
    """)

    # Workflow steps for soil
    soil_steps = [
        ("STEP 01", "Bare Soil Composite Generation",
         "Using GEE, filter time series imagery to extract bare soil pixels (NDVI < 0.2). Create a seasonal or annual composite minimizing vegetation contamination."),
        ("STEP 02", "Soil Index Computation",
         "Calculate BSI (Bare Soil Index), MNDWI, and Clay Mineral Ratio from shortwave infrared (SWIR) and visible bands."),
        ("STEP 03", "Spectral Signature Analysis",
         "Extract spectral signatures per soil class. Analyze reflectance curves across bands B2–B12 to differentiate soil types and moisture conditions."),
        ("STEP 04", "Soil Property Mapping",
         "Correlate spectral indices with measured soil organic carbon (SOC), clay content, and moisture from field samples. Generate predictive maps."),
    ]
    for num, title, desc in soil_steps:
        color = "#10b981"
        st.markdown(f"""
        <div class="workflow-step" style="border-left-color: {color};">
          <div class="step-number" style="color:{color};">{num}</div>
          <div class="step-title">{title}</div>
          <div class="step-desc">{desc}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-header">📊 Simulated Soil Spectral Signatures</div>', unsafe_allow_html=True)
    st.caption("Typical Sentinel-2 spectral response curves for different soil classes.")

    bands = ["B2\n490nm", "B3\n560nm", "B4\n665nm", "B5\n705nm", "B6\n740nm",
             "B7\n783nm", "B8\n842nm", "B8A\n865nm", "B11\n1610nm", "B12\n2190nm"]
    band_x = list(range(len(bands)))

    soils = {
        "Sandy loam (dry)": ([0.12, 0.16, 0.21, 0.23, 0.25, 0.26, 0.27, 0.28, 0.35, 0.30], "#f59e0b"),
        "Clay (moist)": ([0.05, 0.07, 0.09, 0.10, 0.11, 0.12, 0.12, 0.13, 0.18, 0.14], "#6366f1"),
        "Organic-rich (dark)": ([0.03, 0.04, 0.05, 0.055, 0.06, 0.065, 0.07, 0.072, 0.10, 0.08], "#374151"),
        "Silty loam": ([0.09, 0.12, 0.15, 0.165, 0.18, 0.19, 0.20, 0.205, 0.26, 0.22], "#10b981"),
    }

    fig2 = go.Figure()
    for name, (vals, color) in soils.items():
        fig2.add_trace(go.Scatter(
            x=band_x, y=vals,
            mode="lines+markers",
            name=name,
            line=dict(color=color, width=2),
            marker=dict(size=7),
            hovertemplate=f"<b>{name}</b><br>Reflectance = %{{y:.3f}}<extra></extra>",
        ))

    fig2.update_layout(
        xaxis=dict(tickvals=band_x, ticktext=bands, showgrid=True, gridcolor="#e2e8f0"),
        yaxis=dict(title="Reflectance", showgrid=True, gridcolor="#e2e8f0"),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="DM Sans", size=12),
        height=360, margin=dict(l=50, r=20, t=20, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig2, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════
# SECTION: Sample Data Explorer
# ═══════════════════════════════════════════════════════════════════
elif section == "📊 Sample Data":
    st.markdown('<div class="section-header">📊 Sample Field Data Explorer</div>', unsafe_allow_html=True)
    st.markdown("Interactive demo of the kind of data analysis done in the repository notebooks.")

    # Generate sample field data
    np.random.seed(42)
    n = 60
    df = pd.DataFrame({
        "Field_ID": [f"P{i:03d}" for i in range(n)],
        "Date": pd.date_range("2024-01-15", periods=n, freq="5D"),
        "NDVI": np.clip(np.random.normal(0.62, 0.14, n), 0.1, 0.95),
        "LAI": np.clip(np.random.normal(2.8, 0.8, n), 0.2, 5.5),
        "EVI": np.clip(np.random.normal(0.48, 0.10, n), 0.05, 0.80),
        "BSI": np.clip(np.random.normal(0.15, 0.08, n), -0.1, 0.5),
        "Clay_%": np.clip(np.random.normal(28, 8, n), 8, 55),
        "SOC_%": np.clip(np.random.normal(1.8, 0.6, n), 0.5, 4.0),
        "Moisture_%": np.clip(np.random.normal(32, 10, n), 10, 60),
    })

    # Filters
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        ndvi_range = st.slider("Filter by NDVI range", 0.0, 1.0, (0.2, 0.95), step=0.01)
    with col_f2:
        lai_range = st.slider("Filter by LAI range", 0.0, 6.0, (0.0, 6.0), step=0.1)

    mask = (
        df["NDVI"].between(*ndvi_range) &
        df["LAI"].between(*lai_range)
    )
    df_f = df[mask].copy()
    st.caption(f"Showing **{len(df_f)}** of {n} field records")

    # Scatter: NDVI vs LAI
    st.markdown("**NDVI vs LAI — Scatter Analysis**")
    fig3 = px.scatter(
        df_f, x="NDVI", y="LAI",
        color="Clay_%", color_continuous_scale="Blues",
        size="SOC_%", size_max=18,
        hover_data=["Field_ID", "EVI", "Moisture_%"],
        labels={"Clay_%": "Clay (%)"},
    )
    fig3.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        height=360, margin=dict(l=40, r=20, t=20, b=40),
        font=dict(family="DM Sans", size=12),
        xaxis=dict(showgrid=True, gridcolor="#e2e8f0"),
        yaxis=dict(showgrid=True, gridcolor="#e2e8f0"),
    )
    st.plotly_chart(fig3, use_container_width=True)

    # Dual chart: index distributions
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Index Distribution**")
        fig4 = go.Figure()
        for idx, color in [("NDVI", "#3b82f6"), ("EVI", "#10b981"), ("BSI", "#f59e0b")]:
            fig4.add_trace(go.Violin(
                y=df_f[idx], name=idx,
                box_visible=True, meanline_visible=True,
                fillcolor=color, opacity=0.6,
                line_color=color,
            ))
        fig4.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            height=280, margin=dict(l=30, r=10, t=10, b=30),
            font=dict(family="DM Sans", size=12),
            showlegend=False,
            yaxis=dict(showgrid=True, gridcolor="#e2e8f0"),
        )
        st.plotly_chart(fig4, use_container_width=True)

    with col_b:
        st.markdown("**Soil Property Correlation**")
        soil_cols = ["Clay_%", "SOC_%", "Moisture_%"]
        corr = df_f[soil_cols].corr()
        fig5 = px.imshow(
            corr, text_auto=".2f",
            color_continuous_scale="Blues",
            zmin=-1, zmax=1,
        )
        fig5.update_layout(
            height=280, margin=dict(l=30, r=10, t=10, b=30),
            font=dict(family="DM Sans", size=12),
            paper_bgcolor="white",
        )
        st.plotly_chart(fig5, use_container_width=True)

    # Table
    st.markdown("**Filtered Data Table**")
    st.dataframe(
        df_f[["Field_ID", "Date", "NDVI", "LAI", "EVI", "BSI", "Clay_%", "SOC_%", "Moisture_%"]]
        .round(3)
        .reset_index(drop=True),
        use_container_width=True,
        height=260,
    )

# ═══════════════════════════════════════════════════════════════════
# SECTION: Contact
# ═══════════════════════════════════════════════════════════════════
elif section == "📬 Contact":
    st.markdown("""
    <div class="hero-card">
      <p class="hero-name">Let's connect</p>
      <p class="hero-title">Open to collaborations & opportunities</p>
      <p class="hero-bio">
        I'm available for freelance GIS/remote sensing projects, research collaborations,
        and full-time roles in precision agriculture, environmental monitoring,
        or geospatial data science.
      </p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="section-header">📌 Reach out</div>', unsafe_allow_html=True)
        st.markdown("""
        <a class="contact-link" href="mailto:amacias.agro@gmail.com">✉ amacias.agro@gmail.com</a><br><br>
        <a class="contact-link" href="https://github.com/Amaciasagro" target="_blank">⌥ github.com/Amaciasagro</a><br><br>
        <a class="contact-link" href="https://www.linkedin.com/in/ariel-macías-509b0718a/" target="_blank">▸ LinkedIn Profile</a>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="section-header">🎯 What I bring</div>', unsafe_allow_html=True)
        offerings = [
            ("🌿", "Crop monitoring", "NDVI, LAI, EVI time series from Sentinel-2 / Landsat"),
            ("🌍", "GEE automation", "Cloud-based processing pipelines in JavaScript & Python"),
            ("🔬", "Soil mapping", "Spectral soil analysis and property estimation"),
            ("🗺️", "QGIS workflows", "Spatial analysis, cartography, and field data integration"),
        ]
        for icon, title, desc in offerings:
            st.markdown(f"""
            <div style="display:flex;gap:12px;align-items:flex-start;margin-bottom:14px;">
              <span style="font-size:1.4rem;">{icon}</span>
              <div>
                <div style="font-weight:600;color:#0a1628;font-size:0.95rem;">{title}</div>
                <div style="font-size:0.84rem;color:#64748b;">{desc}</div>
              </div>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(
        '<p style="text-align:center; color:#94a3b8; font-size:0.82rem; font-family:Space Mono, monospace;">'
        'Built with Streamlit · Data from GIT-RemoteSensing repository · © 2024 Ariel Macías</p>',
        unsafe_allow_html=True,
    )
