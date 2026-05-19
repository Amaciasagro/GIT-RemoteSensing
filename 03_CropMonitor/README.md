# 🌿 Crop Monitor — Dashboard Interactivo (LAI & NDVI)

Este Dashboard es una herramienta profesional de monitoreo fenológico diseñada para agrónomos y especialistas en Teledetección. Permite analizar la evolución de cultivos utilizando imágenes **Sentinel-2 SR Harmonized** procesadas en tiempo real mediante **Google Earth Engine**.

## 🎬 Demo en video


https://github.com/user-attachments/assets/5f16e574-2a01-425e-8ccd-44a193ce77e4


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

## 🛠️ Inicio Rápido

Tienes dos opciones para usar esta herramienta:

### Opción A: Usar la App en Línea (No requiere instalación) 🌐

Accede a la aplicación directamente en tu navegador — ideal para análisis rápidos y demostraciones:

**👉[Iniciar CropMonitor_App](https://git-remotesensing-fgftb8kssxadprrx57anvp.streamlit.app/) No requiere configuración. Simplemente sube el límite de tu lote y comienza a analizar.**

### Opción B: Ejecución Local (Para Desarrolladores) 💻

Clona el repositorio y ejecútalo en tu propia computadora — ideal para personalización y uso sin conexión:

1. **Clona el repositorio:**
```Bash 
    git clone https://github.com/Amaciasagro/GIT-RemoteSensing.git
    cd GIT-RemoteSensing/03_CropMonitor
```

2. **Crea un entorno virtual:**
```Bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

3. **Instala las dependencias:**
```Bash
pip install -r requirements.txt
```

4. **Ejecuta la aplicación:**
```Bash
streamlit run app.py
```
Abre tu navegador en: http://localhost:8501

---

## 🔑 Configuración de credenciales GEE

Creá el archivo `.streamlit/secrets.toml` con la siguiente estructura:

```toml
EARTHENGINE_PROJECT = "tu-proyecto-gee-123456"

[google_auth]
refresh_token = "tu-refresh-token"
client_id     = "tu-client-id.apps.googleusercontent.com"
client_secret = "tu-client-secret"
```

> ⚠️ **Nunca subas este archivo a GitHub.** Incluí `.streamlit/secrets.toml` en tu `.gitignore`.

Para obtener estas credenciales seguí la [guía oficial de autenticación de Earth Engine](https://developers.google.com/earth-engine/guides/auth).

---

## ☁️ Despliegue en Streamlit Cloud

1. Subí el código a un repositorio de GitHub (sin el archivo de secrets).
2. En [share.streamlit.io](https://share.streamlit.io) conectá tu repo.
3. En **Advanced Settings → Secrets** pegá el contenido de tu `secrets.toml`.
4. Desplegá — la conexión con GEE se establece automáticamente.

---
Autor: Ariel Macías | Ingeniero Agrónomo · GIS & Remote Sensing

