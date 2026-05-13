# 🌿 Crop Monitor (IAF & Vegetation indices)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/LAI_v3.ipynb)

**Autor:** Ariel Macías | Agrónomo · GIS & Remote Sensing

Monitor fenológico interactivo para lotes agrícolas usando **Sentinel-2 SR Harmonized** vía **Google Earth Engine**. Calcula y visualiza 5 índices espectrales (NDVI, LAI, EVI, SAVI, NDWI) sobre una ventana de hasta 3 años, con un dashboard donde al hacer clic en la curva NDVI se cargan automáticamente todas las capas del mes seleccionado en el mapa.

---

## 🔄 Flujo de trabajo

| Paso | Celda | Descripción |
|------|-------|-------------|
| 0 | Configuración | Proyecto GEE, coordenadas, ventana temporal y parámetros de índices |
| 1 | Inicialización | Autenticación GEE · Dibujo del lote o carga de Shapefile/GeoJSON |
| 2 | Índices + gráfico | Descarga S2, cálculo de los 5 índices, gráfico multipanel mensual |
| 3 | Dashboard | Curva NDVI interactiva → clic en un mes → carga todas las capas en el mapa |

---

## 📐 Índices calculados

| Índice | Fórmula | Utilidad agronómica |
|--------|---------|---------------------|
| **NDVI** | (B8−B4) / (B8+B4) | Vigor vegetativo general |
| **LAI** | −ln(1 − NDVI/0.95) / k | Área foliar (m²/m²), modelo Beer-Lambert |
| **EVI** | 2.5·(B8−B4) / (B8+6·B4−7.5·B2+1) | Vigor corregido por aerosoles y suelo, no satura |
| **SAVI** | (B8−B4) / (B8+B4+L)·(1+L), L=0.5 | NDVI ajustado por suelo expuesto |
| **NDWI** | (B3−B8) / (B3+B8) | Contenido de agua en canopeo/suelo |

---

## 🗺️ Capas de visualización del dashboard

| Capa | Bandas | Para qué sirve |
|------|--------|----------------|
| True Color | B4·B3·B2 | Vista natural, detecta nubes y cosecha |
| Falso Color NIR | B8·B4·B3 | Vegetación sana → rojo intenso |
| NDVI | — | Paleta rojo→amarillo→verde |
| LAI | — | Paleta de azules (0–6 m²/m²) |
| EVI | — | Paleta verde claro→verde oscuro |
| SAVI | — | Paleta amarillo→verde |
| NDWI | — | Paleta rojo (seco) → azul (húmedo) |

> **Nota sobre la imagen base:** El dashboard carga la imagen Sentinel-2 **menos nubosa** del mes (escena real, no composite mediana) para True Color y Falso Color. Los índices se calculan sobre la mediana del mes para mayor robustez ante nubes residuales.

---

## ⚙️ Parámetros configurables (Celda 0)

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| `GEE_PROJECT` | `'your-project'` | Project ID de Google Earth Engine |
| `CENTRO_LAT / CENTRO_LON` | 33.584 / -101.845 | Centro del mapa inicial |
| `ANIOS_ATRAS` | 3 | Ventana temporal del análisis |
| `MAX_NUBES` | 30 % | Umbral de cobertura nubosa para filtrar imágenes |
| `K_EXTINCTION` | 0.5 | Coeficiente extinción Beer-Lambert para LAI (0.4–0.6 para cultivos) |
| `SAVI_L` | 0.5 | Factor de corrección de suelo (0 = suelo desnudo, 1 = canopeo cerrado) |

---

## 🗄️ Fuente de datos

| Fuente | Descripción |
|--------|-------------|
| [Sentinel-2 SR Harmonized](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED) | Reflectancia superficial · 10 m resolución |
| Google Earth Engine | Procesamiento y extracción de estadísticas espaciales |

Las estadísticas se extraen como media espacial sobre todo el polígono del lote a escala de 10 m.

---

## 🛠️ Requisitos

```bash
pip install earthengine-api geemap geopandas shapely
pip install pandas matplotlib plotly ipywidgets
```

O con conda:

```bash
conda install -c conda-forge earthengine-api geemap geopandas matplotlib
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
cd GIT-RemoteSensing
```

2. Abrir el notebook:

```bash
jupyter notebook LAI_v3.ipynb
```

3. En la **Celda 0**, configurar el proyecto GEE y los parámetros de análisis.

4. Ejecutar las celdas en orden. En la **Celda 3**, hacer clic en cualquier punto de la curva NDVI para cargar todas las capas del mes seleccionado en el mapa interactivo.

---

## 🗺️ Definición del lote — dos opciones

**Opción A — Dibujar en el mapa**
Usar la herramienta de polígono del panel izquierdo y presionar *"✅ Confirmar polígono dibujado"*. Se exporta automáticamente `lote_exportado.geojson`.

**Opción B — Subir un archivo vectorial**
Subir un `.shp` (en `.zip` con todos los componentes) o `.geojson` mediante el widget de carga. Se reproyecta automáticamente a EPSG:4326.

---

## 📊 Outputs generados

- **Gráfico multipanel** (matplotlib) con evolución mensual de los 5 índices durante la ventana temporal configurada
- **Dashboard interactivo** (Plotly + geemap) con:
  - Curva fenológica NDVI clickeable por mes
  - Mapa con 7 capas alternables: True Color, Falso Color NIR, NDVI, LAI, EVI, SAVI, NDWI
  - Resumen de valores medios del mes seleccionado en consola
- **Archivo `lote_exportado.geojson`** con el polígono del lote

---

## 📁 Estructura del directorio

```
GIT-RemoteSensing/
├── LAI_v3.ipynb    # Notebook principal (self-contained)
└── README.md
```

---

## 🔗 Recursos relacionados

- [Sentinel-2 en Google Earth Engine](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)
- [FAO — Índice de Área Foliar](https://www.fao.org/land-water/land/land-governance/land-resources-planning-toolbox/category/details/es/c/1236449/)
- [geemap documentation](https://geemap.org/)
- [Google Earth Engine](https://earthengine.google.com/)

---

## 📄 Licencia

Repositorio de uso personal. Imágenes Sentinel-2 provistas por la ESA / Copernicus bajo licencia abierta.
