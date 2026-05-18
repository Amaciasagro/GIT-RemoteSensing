# 🌿 Crop Monitor — Dashboard Interactivo (LAI & NDVI)

Este Dashboard es una herramienta profesional de monitoreo fenológico diseñada para agrónomos y especialistas en Teledetección. Permite analizar la evolución de cultivos utilizando imágenes **Sentinel-2 SR Harmonized** procesadas en tiempo real mediante **Google Earth Engine**.

## 🚀 Funcionalidades Principales
- **Curva Fenológica Interactiva:** Visualización de la evolución mensual de índices (NDVI, LAI, SAVI, EVI, NDWI) mediante gráficos de Plotly.
- **Sincronización Temporal:** Al navegar por la curva de tiempo, el mapa actualiza automáticamente tanto el índice seleccionado como la imagen satelital base del lote.
- **Satélite Dinámico Mensual:** Visualización en Color Real (RGB) de la mejor imagen del mes seleccionado (filtrada por nubosidad), permitiendo validar visualmente los datos de los índices.
- **Mapas Comparativos (DualMap):** Capacidad de comparar dos índices diferentes (ej. NDVI vs LAI) de forma sincronizada en pantalla dividida.
- **Gestión de Lotes:** Dibujo manual de polígonos directamente en el mapa o carga de archivos locales (.shp en .zip o .geojson).

## 🛠️ Tecnologías Utilizadas
| Tecnología | Uso en el Proyecto |
| :--- | :--- |
| **Streamlit** | Interfaz de usuario y despliegue web. |
| **Google Earth Engine (GEE)** | Procesamiento geoespacial en la nube y acceso a Sentinel-2. |
| **Folium / Streamlit-Folium** | Visualización de mapas interactivos y capas ráster. |
| **Plotly** | Gráficos dinámicos y análisis de series temporales. |
| **Geopandas / Shapely** | Gestión y manipulación de datos vectoriales. |

## 💻 Instalación y Uso Local
1. Clona este repositorio.
2. Crea un entorno virtual e instala las dependencias:
   ```bash
   pip install -r requirements.txt
3. Configura tus credenciales de GEE en .streamlit/secrets.toml.
4. Ejecuta la aplicación:
   streamlit run app.py

🌐 DESPLIEGUE EN STREAMLIT CLOUD
Para desplegar esta app de forma segura, asegúrate de:
1. Tener un archivo .gitignore que incluya .streamlit/secrets.toml y cualquier archivo de credenciales locales.
2. Subir el código a GitHub.
3. En el panel de Advanced Settings de Streamlit Cloud, copiar y pegar el contenido de tus secretos para que la conexión con GEE funcione en la nube.

---
Autor: Ariel Macías | Agrónomo · GIS & Remote Sensing

