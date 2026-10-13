[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/03_CropMonitor/notebooks/03_Crop_Monitor.ipynb)
[![Streamlit App](https://img.shields.io/badge/-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://git-remotesensing-fgftb8kssxadprrx57anvp.streamlit.app/)

# 🌿 Crop Monitor — Interactive Dashboard (LAI & NDVI)

This dashboard is a professional phenological monitoring tool designed for agronomists and Remote Sensing specialists. It allows you to analyze crop development using **Sentinel-2 SR Harmonized** imagery processed in real time with **Google Earth Engine**.

## 🎬 Video Demo


https://github.com/user-attachments/assets/5f16e574-2a01-425e-8ccd-44a193ce77e4


## 🚀 Main Features
- **Interactive Phenological Curve:** Visualization of the monthly evolution of indices (NDVI, LAI, SAVI, EVI, NDWI) through Plotly charts.
- **Temporal Synchronization:** As you navigate the time curve, the map automatically updates both the selected index and the base satellite image of the field.
- **Dynamic Monthly Satellite View:** True Color (RGB) display of the best image of the selected month (filtered by cloud cover), allowing you to visually validate the index data.
- **Comparative Maps (DualMap):** Ability to compare two different indices (e.g. NDVI vs LAI) in a synchronized split screen.
- **Field Management:** Manual polygon drawing directly on the map or upload of local files (.shp in .zip or .geojson).

## 🛠️ Technologies Used
| Technology | Use in the Project |
| :--- | :--- |
| **Streamlit** | User interface and web deployment. |
| **Google Earth Engine (GEE)** | Cloud-based geospatial processing and access to Sentinel-2. |
| **Folium / Streamlit-Folium** | Interactive map visualization and raster layers. |
| **Plotly** | Dynamic charts and time series analysis. |
| **Geopandas / Shapely** | Management and manipulation of vector data. |

## 🛠️ Quick Start

You have two options for using this tool:

### Option A: Use the Online App (No installation required) 🌐

Access the application directly in your browser — ideal for quick analyses and demos:

**👉[Launch CropMonitor_App](https://git-remotesensing-fgftb8kssxadprrx57anvp.streamlit.app/) No setup required. Simply upload your field boundary and start analyzing.**

### Option B: Run Locally (For Developers) 💻

Clone the repository and run it on your own computer — ideal for customization and offline use:

1. **Clone the repository:**
```Bash 
    git clone https://github.com/Amaciasagro/GIT-RemoteSensing.git
    cd GIT-RemoteSensing/03_CropMonitor
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

## 🔑 GEE Credentials Setup

Create the file `.streamlit/secrets.toml` with the following structure:

```toml
EARTHENGINE_PROJECT = "your-gee-project-123456"

[google_auth]
refresh_token = "your-refresh-token"
client_id     = "your-client-id.apps.googleusercontent.com"
client_secret = "your-client-secret"
```

> ⚠️ **Never upload this file to GitHub.** Add `.streamlit/secrets.toml` to your `.gitignore`.

To obtain these credentials, follow the [official Earth Engine authentication guide](https://developers.google.com/earth-engine/guides/auth).

---

## ☁️ Deployment on Streamlit Cloud

1. Upload the code to a GitHub repository (without the secrets file).
2. On [share.streamlit.io](https://share.streamlit.io), connect your repo.
3. In **Advanced Settings → Secrets**, paste the contents of your `secrets.toml`.
4. Deploy — the connection to GEE is established automatically.

---
Author: Ariel Macías | Agronomist (Agricultural Engineer) · GIS & Remote Sensing
