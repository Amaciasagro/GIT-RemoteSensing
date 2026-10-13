[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/02_Climate_Analyzer/notebooks/02_Climatic_Analysis.ipynb)
[![Streamlit App](https://img.shields.io/badge/-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://git-remotesensing-9wvgyb6zyebxouaujadipk.streamlit.app/)

# 🌦️ Climate Analyzer — Interactive Climate Dashboard

**Spatial agronomic climate analysis with Google Earth Engine and Streamlit**  
*Author: Ariel Macías — Agronomist (Agricultural Engineer) & GIS Analyst*

---

## What does this app do?

https://github.com/user-attachments/assets/b5878891-908d-4510-8057-24a1d89127c2

---

## Features

### 📈 Tab 1 — Time Series (ERA5)
- Precipitation, FAO-56 Penman-Monteith ETo, monthly temperature
- Monthly water balance (P − ETo)
- Daily detail of the current month with accumulated values
- Relative humidity and wind speed
- Download of daily data as `.csv`

### 🌧️ Tab 2 — CHIRPS Anomalies
- Compares the period's precipitation against the historical average of the last 20 years
- Thematic map: red tones = deficit / blue tones = excess
- Absolute (mm) and percentage (%) anomaly
- Zonal statistics per field: mean, minimum, maximum

### 💧 Tab 3 — Spatial Water Balance
- Combines CHIRPS and ERA5 pixel by pixel to calculate P − ETo
- ETo estimated with Hargreaves-Samani (raster)
- Three viewable layers: balance, precipitation, ETo
- Ideal for zoning irrigation needs and within-field heterogeneity

### 🌡️ Tab 4 — Thermal Risk
- Count of **frost** days (Tmin < adjustable threshold) per pixel
- Count of **extreme heat** days (Tmax > adjustable threshold) per pixel
- Thresholds configurable from the sidebar
- Automatic alert levels (low / moderate / high)

### 🔀 Tab 5 — Field Comparison
- Comparison table with all agronomic metrics
- Overlaid charts of precipitation, balance and temperature
- Normalized multi-field radar chart
- Automatic conclusions (field with the most rainfall, best balance, highest GDD, etc.)
- Download of the comparison table as `.csv`

---

## 🛠️ Technologies

| Technology | Role |
| :--- | :--- |
| **Streamlit** | User interface and web deployment |
| **Google Earth Engine** | Access to ERA5-Land and cloud-based spatial computing |
| **ERA5-Land (ECMWF)** | Global climate reanalysis at ~11 km resolution |
| **Folium / Streamlit-Folium** | Interactive map for defining the field |
| **Plotly** | Dynamic time series charts |
| **GeoPandas / Shapely** | Vector geometry processing |
| **google-auth** | OAuth2 authentication with Google Earth Engine |

---

## 📦 Variables and Metrics

| Variable / Metric | Source | Unit |
| :--- | :--- | :--- |
| Precipitation | ERA5-Land | mm/day |
| Max / min / mean temperature | ERA5-Land | °C |
| Relative humidity | Calculated (dew point) | % |
| Downward solar radiation | ERA5-Land | MJ/m²/day |
| Wind speed | ERA5-Land (u, v at 10 m) | m/s |
| Actual evapotranspiration | ERA5-Land | mm/day |
| **Penman-Monteith ETo** | FAO-56 calculated | mm/day |
| **Water balance** | Rainfall − accumulated ETo | mm |
| **Growing Degree Days** | (T_mean − T_base) · days | °C·day |

---

## 🛠️ Quick Start

You have two options for using this tool:

### Option A: Use the Online App (No installation required) 🌐

Access the application directly in your browser — ideal for quick analyses and demos:

**👉[Launch Climate_Analyzer_App](https://git-remotesensing-9wvgyb6zyebxouaujadipk.streamlit.app/) No setup required. Simply upload your field boundary and start analyzing.**

### Option B: Run Locally (For Developers) 💻

Clone the repository and run it on your own computer — ideal for customization and offline use:

1. **Clone the repository:**
```Bash 
    git clone https://github.com/Amaciasagro/GIT-RemoteSensing.git
    cd GIT-RemoteSensing/02_Climate_Analyzer
```

2. **Create a virtual environment:**
```Bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install the dependencies:**
```Bash
pip install -r requirements.txt
```

4. **Run the application:**
```Bash
streamlit run app.py
```
Open your browser at: http://localhost:8501

---

## Project Structure

```
climate_analyzer/
├── app.py                  # Entry point + tab orchestration
├── config.py               # Constants, GEE collections, palettes, CSS
├── gee_client.py           # GEE queries: ERA5, CHIRPS, thematic maps
├── metrics.py              # PM ETo, RH, GDD, balance (time series)
├── charts.py               # All Plotly charts
├── map_utils.py            # Folium, thematic maps, AOI loading
├── ui/
│   ├── sidebar.py          # Multi-field, parameters, file upload
│   ├── tab_series.py       # Tab 1: ERA5 time series
│   ├── tab_anomalias.py    # Tab 2: CHIRPS anomalies
│   ├── tab_balance.py      # Tab 3: Spatial water balance
│   ├── tab_riesgos.py      # Tab 4: Thermal risk (frost/heat)
│   └── tab_comparar.py     # Tab 5: Multi-field comparison
├── requirements.txt
└── README.md
```

---

## Workflow

1. **Open the app** → a clean map appears
2. **Draw a polygon** on the map or upload a `.shp`/`.geojson`
3. **Confirm the field** in the sidebar (it is saved with a name and color)
4. **Repeat** to add more fields (no limit)
5. **Click "Analyze fields"** → downloads ERA5 data for each field
6. **Browse the tabs** to explore series, anomalies, balance, risks and comparisons
7. **Download** the data or tables as needed

---

## Methodological Notes

### FAO-56 Penman-Monteith ETo
Implemented according to Allen et al. (1998). Used for the time series (Tab 1 and Tab 5). Requires: Tmax, Tmin, Tdew, solar radiation, wind at 2 m.

### Hargreaves-Samani ETo
Simplified version for pixel-by-pixel raster calculation (Tab 3). Requires only Tmax, Tmin and Ra (extraterrestrial radiation). Suitable for relative spatial comparisons.

### CHIRPS Anomaly
The historical baseline uses the same range of days of the year (DOY) over the `N` years preceding the analyzed period. This removes the seasonal effect and makes short periods comparable.

### Spatial Resolution
| Source   | Resolution | Temporal coverage |
|----------|------------|-------------------|
| ERA5-Land | ~11 km    | 1950–present      |
| CHIRPS    | ~5 km     | 1981–present      |

---

## Main Dependencies

| Library | Use |
|---------|-----|
| `earthengine-api` | GEE queries and processing |
| `streamlit` | Web interface |
| `streamlit-folium` | Rendering of interactive maps |
| `folium` | Building Leaflet maps |
| `plotly` | Interactive charts |
| `geopandas` / `shapely` | Loading and processing geometries |
| `pandas` / `numpy` | Time series manipulation |

---

## Future Roadmap

- [ ] Export thematic maps as GeoTIFF (via `ee.batch`)
- [ ] Animated timelapse (GIF/MP4) by week or decade
- [ ] Integration with forecast data (GFS/ECMWF open)
- [ ] Drought indices (SPI, NDVI from Sentinel/Landsat)
- [ ] Automatic PDF report per field

---

*Developed with Google Earth Engine, Streamlit and open data from ECMWF and UCSB-CHG.*
