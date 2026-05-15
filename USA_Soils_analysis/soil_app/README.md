# 🌱 USA Soil Spatial Analysis — Streamlit App

**Author:** Ariel Macías | Agronomist · GIS & Remote Sensing Data Scientist

An interactive multi-tab web application for advanced agricultural field analysis using official USDA-NRCS data and open elevation sources.

> ⚠️ **USDA-NRCS data is restricted to United States territory.**

---

## 📋 Features

| Tab | Description |
|-----|-------------|
| **📍 AOI Definition** | Upload a shapefile (ZIP) or GeoJSON, or paste GeoJSON directly. Field preview on satellite basemap. Download boundary as GeoJSON or Shapefile. |
| **🌱 Soil Information** | Choropleth maps (by texture class and by MUKey), full agronomic tabular report, depth-profile charts for any soil property. Download maps, data tables (CSV/Excel), and charts (HTML/PNG). |
| **🏔️ Topographic Models** | Contour line map with elevation hover (Leaflet), hillshade preview (matplotlib), configurable zoom and contour levels. Download contours as GeoJSON, HTML, or elevation CSV. |
| **🌐 3D Projection** | Plotly 3D surface with earth colorscale (fast) and Plotly Mesh3d draped with Esri World Imagery satellite texture (full photorealistic). Download as interactive HTML or PNG. |

---

## 🛠️ Installation

### 1. Clone / copy the project

```bash
git clone <your-repo>
cd soil_app
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `kaleido` is optional but required for PNG exports from Plotly:
> ```bash
> pip install kaleido
> ```

### 4. Google Earth Engine (optional)

The original notebook used GEE for the interactive drawing widget. This Streamlit app **does not require GEE** — field boundaries are loaded via file upload or GeoJSON paste. If you want to integrate GEE in the future, authenticate with:

```bash
earthengine authenticate
```

---

## 🚀 Running the App

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

---

## 📁 Project Structure

```
soil_app/
├── app.py                  # Main entry point — tab routing
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── tabs/
│   ├── __init__.py
│   ├── tab_aoi.py          # Tab 0 — AOI Definition
│   ├── tab_soils.py        # Tab 1 — Soil Information
│   ├── tab_topo.py         # Tab 2 — Topographic Models
│   └── tab_3d.py           # Tab 3 — 3D Projection
└── utils/
    ├── __init__.py
    ├── soil_data.py         # USDA WFS + SDA query helpers
    ├── dem.py               # DEM tile download + contour extraction
    └── export.py            # CSV, Excel, GeoJSON, SHP, HTML export helpers
```

---

## 📊 Data Sources

| Source | Type | Coverage |
|--------|------|----------|
| [USDA-NRCS Soil Data Mart WFS](https://sdmdataaccess.nrcs.usda.gov/) | Soil polygons (MapunitPoly) | USA only |
| [USDA Soil Data Access (SDA)](https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest) | Tabular horizon properties | USA only |
| [AWS Terrarium tiles](https://s3.amazonaws.com/elevation-tiles-prod/terrarium/) | Elevation (DEM) | Global |
| [Esri World Imagery](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/) | Satellite imagery | Global |

---

## ⬇️ Download Formats by Feature

| Feature | Formats |
|---------|---------|
| Field boundary | GeoJSON, Shapefile (.zip) |
| Soil polygons (texture / MUKey) | GeoJSON, Shapefile (.zip) |
| Agronomic horizon data | CSV, Excel (.xlsx) |
| Depth profile charts | Interactive HTML, PNG |
| Contour lines | GeoJSON |
| Contour map | HTML (standalone Leaflet) |
| Elevation grid | CSV (sampled) |
| 3D surface / mesh | Interactive HTML, PNG |

---

## ⚙️ Configuration

Key parameters are in `utils/soil_data.py`:

```python
MAX_DEPTH_CM = 80   # Root zone depth for weighted averages
N_FACTOR     = 0.05 # Estimated N = OM × N_FACTOR (Bremner 1965)
```

Tile zoom level (12–16) and contour count (5–30) are adjustable via UI sliders.

---

## 🐛 Known Limitations

- **US only**: USDA-NRCS WFS and SDA only cover US territory.
- **Satellite 3D mesh**: very large fields at zoom 16 may produce slow renders; the app auto-downsamples grids > 150,000 points.
- **PNG export** requires `kaleido` (`pip install kaleido`).
- **No GEE drawing widget**: replaced by file upload / GeoJSON paste for broader compatibility.

---

## 📜 License

For educational and research use. USDA data is public domain. Esri World Imagery and AWS Terrarium tiles are subject to their respective terms of service.
