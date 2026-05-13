# 🌦️ Climate Analyzer 

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/Climate/Climate_td_v2.ipynb)

**Autor:** Ariel Macías | Agrónomo · GIS & Remote Sensing

Herramienta interactiva para análisis climático agronómico sobre un lote agrícola, usando datos **ERA5-Land** (ECMWF) vía **Google Earth Engine**. Calcula variables climáticas diarias y mensuales, ETo por Penman-Monteith FAO-56, balance hídrico y grados día acumulados, con visualizaciones interactivas.

---

## 🔄 Flujo de trabajo

| Paso | Celda | Descripción |
|------|-------|-------------|
| 0 | Configuración | Proyecto GEE y coordenadas del mapa inicial |
| 1 | Inicialización | Autenticación GEE · Dibujo del lote o carga de Shapefile |
| 2 | Análisis completo | Descarga ERA5 · Métricas agronómicas · Gráficos interactivos |

---

## 📋 Variables extraídas de ERA5-Land

| Variable | Descripción |
|----------|-------------|
| Precipitación | Suma diaria (mm) |
| T. máx / mín / media | Temperatura a 2 m (°C) |
| Punto de rocío | → Humedad relativa estimada (%) |
| Radiación solar | Descendente superficial (MJ/m²/día) |
| Viento (u, v) | Componentes a 10 m → velocidad escalar (m/s) |
| ET vegetación | Evapotranspiración real ERA5 (mm) |
| **ETo Penman-Monteith** | Calculada con FAO-56 a partir de las anteriores |
| **Balance hídrico** | Lluvia acum. − ETo acum. (mm) |
| **GDA** | Grados día acumulados sobre T_BASE (definida en `config.py`) |

---

## 🗄️ Fuente de datos

| Fuente | Descripción |
|--------|-------------|
| [ERA5-Land (ECMWF)](https://www.ecmwf.int/en/era5-land) | Reanálisis climático diario · ~9 km resolución |
| Google Earth Engine | Acceso y procesamiento de la colección ERA5-Land |

Los datos se extraen como media espacial sobre el área completa del lote (no sobre un centroide puntual).

---

## 📁 Estructura del proyecto

```
Climate/
├── Climate_td_v2.ipynb   # Notebook principal
├── config.py             # Parámetros: colección ERA5, T_BASE, etc.
├── gee_utils.py          # Funciones GEE: fechas, periodos, descarga de serie
├── agro_metrics.py       # Cálculo de ETo PM, HR, agregación mensual/diaria
├── plots.py              # Generación de gráficos interactivos (Plotly)
└── README.md             # Este archivo
```

---

## 🛠️ Requisitos

```bash
pip install earthengine-api geemap geopandas shapely
pip install pandas plotly ipywidgets
```

O con conda:

```bash
conda install -c conda-forge earthengine-api geemap geopandas
```

### Requisitos adicionales

- **Cuenta de Google Earth Engine** con un proyecto activo ([registrarse aquí](https://earthengine.google.com/))
- Python >= 3.8
- Jupyter Notebook o JupyterLab

---

## 🚀 Uso

1. Clonar el repositorio:

```bash
git clone https://github.com/Amaciasagro/GIT-RemoteSensing.git
cd GIT-RemoteSensing/Climate
```

2. Abrir el notebook:

```bash
jupyter notebook Climate_td_v2.ipynb
```

3. En la **Celda 0**, configurar el proyecto GEE y las coordenadas iniciales:

```python
GEE_PROJECT  = 'tu-proyecto-gee'   # Project ID de Google Earth Engine
CENTRO_LAT   = 33.584              # Latitud del centro del mapa
CENTRO_LON   = -101.845            # Longitud del centro del mapa
ZOOM_INICIAL = 14
```

4. Revisar `config.py` para ajustar la **temperatura base** (T_BASE) usada en el cálculo de grados día.

5. Ejecutar las celdas en orden.

---

## 🗺️ Definición del lote — dos opciones

**Opción A — Dibujar en el mapa**
Usar la herramienta de polígono del panel izquierdo del mapa interactivo y presionar *"✅ Confirmar polígono dibujado"*. El lote se exporta automáticamente como `lote_exportado.geojson`.

**Opción B — Subir un Shapefile**
Subir un archivo `.shp` (en `.zip` con todos los componentes: `.shp`, `.dbf`, `.shx`, `.prj`) mediante el widget de carga. El archivo se reproyecta automáticamente a EPSG:4326.

---

## 📊 Outputs generados

- **Resumen en consola** del último mes disponible: lluvia, ETo, balance hídrico, temperatura media, HR
- **Gráficos interactivos** (Plotly) con series mensuales y detalle diario del mes actual:
  - Precipitación y ETo mensual
  - Balance hídrico acumulado
  - Temperatura máx/mín/media
  - Humedad relativa
  - Grados día acumulados (GDA)
- **Archivo `lote_exportado.geojson`** con el polígono del lote

---

## 🔗 Recursos relacionados

- [ERA5-Land en Google Earth Engine](https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_DAILY_AGGR)
- [FAO-56 Penman-Monteith](https://www.fao.org/3/x0490e/x0490e00.htm)
- [geemap documentation](https://geemap.org/)
- [Google Earth Engine](https://earthengine.google.com/)

---

## 📄 Licencia

Repositorio de uso personal. Datos climáticos provistos por ECMWF (ERA5-Land) bajo licencia Copernicus.
