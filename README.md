# 🌱 Soil Analyzer: Advanced USA Soil & Topographic Mapping

**Author:** Ariel Macías | Agronomist Engineer · GIS & Remote Sensing Data Scientist

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/01_USA_Soils_analysis/01_USA_Soils_analysis.ipynb)
[![Streamlit App](https://img.shields.io/badge/-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://git-remotesensing-abuk6upwubrppkqjc7gwmf.streamlit.app)

This application is a professional **Precision Agriculture** tool designed for diagnosing agricultural fields in the United States. It integrates official **USDA-NRCS (Soil Data Mart)** data with global elevation models to generate agronomic reports and photorealistic 3D visualizations.

---

## 🚀 User Guide

The app is divided into 4 logical modules that follow an agronomic consultant's workflow:

### 1. 📍 Field Definition (AOI)
The first step is to delineate the study area.
- **How to use:** You can upload a `.zip` file (Shapefile) or `.geojson`. You can also paste coordinates directly in GeoJSON format.
- **Visualization:** You'll see the boundary overlaid on a satellite layer to verify the location is correct.

https://github.com/user-attachments/assets/e432f095-ed1e-4ccc-9c20-cdaa987ec408

### 2. 🌱 Soil Information
This is where the USDA integration "magic" happens.
- **Maps:** Automatically generates **Texture Class** and **MUKey** (Map Unit Key) maps.
- **Report:** Click to get a detailed table with pH, Organic Matter, CEC, and more.
- **Profile Charts:** Visualize how soil properties (sand, silt, clay) change as you go deeper into the profile (0-200 cm).

https://github.com/user-attachments/assets/055724de-b02f-4a6d-bfbb-f8ca62bfb4fb

### 3. 🏔️ Topographic Models
Relief analysis to understand water movement and erosion.
- **Contour Lines:** An interactive map (Leaflet) where you can see the exact elevation by hovering your mouse.
- **Hillshade:** A shaded relief map that highlights micro-slopes in the terrain.

<img width="1328" height="558" alt="Screenshot 2026-05-18 172835" src="https://github.com/user-attachments/assets/c7e89389-967b-4e8b-91cc-7a249099b129" />

### 4. 🌐 Photorealistic 3D Projection
The crown jewel for client presentations.
- **3D Surface:** A quick model to visualize field volumetry.
- **Satellite Mesh:** Projects **Esri World Imagery** over the relief.
- **New feature:** Your field boundary is automatically drawn over the terrain so you don't lose spatial reference.

<img width="1320" height="561" alt="Screenshot 2026-05-18 173025" src="https://github.com/user-attachments/assets/351c01aa-90d3-4921-a42a-b814d1266091" />

<img width="1306" height="547" alt="Screenshot 2026-05-18 173514" src="https://github.com/user-attachments/assets/c29b14d1-3e07-4576-9a6e-fc9471cb9889" />

---

## 📂 Project Structure
The code is organized in a modular way for easy maintenance:

* `app.py`: Main entry point.
* `tabs/`: Contains the interface logic for each section (AOI, Soils, Topo, 3D).
* `utils/`: Calculation engines (DEM download, USDA API, file export).
* `assets/`: Static files, logos, and base HTML maps.
* `notebooks/`: My Jupyter testing lab.

---

## 🛠️ Quick Start

You have two options to use this tool:

### Option A: Use the Live App (No Installation Required) 🌐
Access the application directly in your browser — perfect for quick analysis and demonstrations:

**👉 [Launch Soil Analyzer App](https://git-remotesensing-abuk6upwubrppkqjc7gwmf.streamlit.app)**

No setup needed. Just upload your field boundary and start analyzing.

---

### Option B: Run Locally (For Developers) 💻
Clone the repository and run on your own machine — ideal for customization and offline use:

1. **Clone the repository:**
```bash
   git clone https://github.com/Amaciasagro/GIT-RemoteSensing.git
   cd GIT-RemoteSensing/01_USA_Soils_analysis
```

2. **Create a virtual environment:**
```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
   pip install -r requirements.txt
```

4. **Run the app:**
```bash
   streamlit run app.py
```

5. **Open your browser at:** `http://localhost:8501`

---

## 🌍 Data Sources

| Source | Type | Coverage |
|--------|------|----------|
| [USDA-NRCS Soil Data Mart WFS](https://sdmdataaccess.nrcs.usda.gov/) | Soil polygons (MapunitPoly) | USA only |
| [USDA Soil Data Access (SDA)](https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest) | Tabular horizon properties | USA only |
| [AWS Terrarium tiles](https://s3.amazonaws.com/elevation-tiles-prod/terrarium/) | Elevation (DEM) | Global |
| [Esri World Imagery](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/) | Satellite imagery | Global |

---

## ⬇️ Download Formats

| Feature | Available Formats |
|---------|------------------|
| Field boundary | GeoJSON, Shapefile (.zip) |
| Soil polygons | GeoJSON, Shapefile (.zip) |
| Agronomic data | CSV, Excel (.xlsx), HTML report |
| Depth profiles | Interactive HTML, PNG |
| Contour lines | GeoJSON, HTML map |
| Elevation grid | CSV (sampled) |
| 3D models | Interactive HTML, PNG |

---

## 🎓 Educational Use Cases

This tool is ideal for:
- **Agricultural consultants:** Field diagnostics and precision farming plans
- **University students:** Learning soil science and GIS applications
- **Research projects:** Spatial soil analysis and terrain modeling
- **Farm management:** Data-driven decision making for crop planning

---

## ⚠️ Known Limitations

- **US Territory Only:** USDA-NRCS data is restricted to United States territory
- **Performance:** Very large fields at zoom level 16 may require downsampling
- **PNG Export:** Requires `kaleido` package (`pip install kaleido`)
- **Satellite Texture:** Download time depends on field size and internet speed

---

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 License

This project is licensed under the MIT License - see the LICENSE file for details.

USDA-NRCS data is public domain. Esri World Imagery and AWS Terrarium tiles are subject to their respective terms of service.

---

## 📧 Contact

**Ariel Macías**
- 🌐 [GitHub](https://github.com/Amaciasagro)
- 💼 [LinkedIn](https://linkedin.com/in/your-profile)
- 📧 Email: your.email@example.com

---

## 🙏 Acknowledgments

- **USDA-NRCS** for providing free access to soil data
- **AWS** for hosting Terrarium elevation tiles
- **Esri** for World Imagery satellite basemaps
- **Streamlit** team for the amazing framework

---

**Made with ❤️ for the agricultural community**