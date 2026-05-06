# 🌱 Soil Analyzer — USA Soils Analysis

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/01_USA_Soils_analysis/01_USA_Soils_analysis.ipynb)

**Autor:** Ariel Macías | Agronomist · GIS & Remote Sensing

Herramienta interactiva para analizar suelos de un lote agrícola en **Estados Unidos**, integrando datos oficiales de la **USDA-NRCS (Soil Data Mart)** con **Google Earth Engine**. Permite delimitar un lote, descargar unidades cartográficas de suelo y generar un reporte agronómico completo con visualizaciones.

> ⚠️ Los datos USDA-NRCS tienen cobertura exclusiva en **Estados Unidos**. Para lotes en Argentina u otros países, los servicios no devuelven datos.

---

## 🔄 Flujo de trabajo

| Paso | Celda | Descripción |
|------|-------|-------------|
| 0 | Configuración | Parámetros de proyecto GEE y coordenadas del mapa inicial |
| 1 | Inicialización | Autenticación GEE · Dibujo del lote o carga de Shapefile/GeoJSON |
| 2 | Descarga WFS | Consulta espacial a USDA Soil Data Mart · Mapa coloreado por clase textural |
| 3 | Reporte agronómico | Tablas detalladas con textura, MO, pH, CEC, AWC por serie de suelo |
| 4 | Gráficos | Barras apiladas de composición granulométrica por unidad cartográfica |

---

## 📋 Propiedades de suelo consultadas

| Propiedad | Descripción |
|-----------|-------------|
| Arena / Limo / Arcilla | Granulometría del horizonte superficial (0–20 cm) |
| Clase textural | Clasificada automáticamente desde granulometría (12 clases USDA) |
| Materia Orgánica (%) | Contenido de MO superficial |
| pH | Reacción del suelo (con código de color por rango) |
| CEC | Capacidad de intercambio catiónico (cmol/kg) |
| AWC | Agua disponible (cm/cm) |

---

## 🗄️ Fuentes de datos

| Fuente | Descripción |
|--------|-------------|
| [USDA-NRCS Soil Data Mart (WFS)](https://sdmdataaccess.nrcs.usda.gov/) | Polígonos de unidades cartográficas de suelo |
| [USDA SDA Tabular API](https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest) | Propiedades físico-químicas por componente y horizonte |
| [UC Davis SoilWeb](https://casoilresource.lawr.ucdavis.edu/soilweb-apps/) | Fichas de series de suelo (enlaces en el reporte) |
| Google Earth Engine | Mapa base satelital e inicialización del entorno geoespacial |

---

## 🛠️ Requisitos

```bash
pip install earthengine-api geemap geopandas requests shapely
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
cd GIT-RemoteSensing/01_USA_Soils_analysis
```

2. Abrir el notebook:

```bash
jupyter notebook 01_USA_Soils_analysis.ipynb
```

3. En la **Celda 0**, configurar el proyecto GEE y las coordenadas del mapa inicial:

```python
GEE_PROJECT  = 'tu-proyecto-gee'   # Project ID de Google Earth Engine
CENTRO_LAT   = 33.584              # Latitud del centro del mapa
CENTRO_LON   = -101.845            # Longitud del centro del mapa
ZOOM_INICIAL = 14
```

4. Ejecutar las celdas en orden.

---

## 🗺️ Definición del lote — dos opciones

**Opción A — Dibujar en el mapa**
Usar la herramienta de polígono del panel izquierdo del mapa interactivo y luego presionar el botón *"✅ Confirmar polígono dibujado"*. El lote se exporta automáticamente como GeoJSON descargable.

**Opción B — Subir un archivo vectorial**
Subir un archivo `.shp` (en `.zip` con todos los componentes) o `.geojson` mediante el widget de carga. El archivo se reproyecta automáticamente a EPSG:4326.

---

## 📊 Outputs generados

- **Mapa interactivo** con unidades de suelo coloreadas por clase textural (paleta de 12 clases USDA)
- **Tabla resumen** de superficies por unidad cartográfica (hectáreas y % del lote)
- **Reporte HTML expandible** con propiedades detalladas por serie de suelo, incluyendo:
  - Links directos a la ficha de cada serie en UC Davis SoilWeb
  - Color de pH según rango agronómico (muy ácido → neutro → alcalino)
  - Clase textural clasificada automáticamente
- **Gráficos de composición granulométrica** (barras apiladas arena/limo/arcilla)
- **Archivo `lote_exportado.geojson`** con el polígono del lote

---

## 📁 Estructura del directorio

```
01_USA_Soils_analysis/
├── 01_USA_Soils_analysis.ipynb   # Notebook principal
└── README.md                     # Este archivo
```

---

## 🔗 Recursos relacionados

- [USDA-NRCS Soil Data Access](https://sdmdataaccess.nrcs.usda.gov/)
- [UC Davis SoilWeb](https://casoilresource.lawr.ucdavis.edu/soilweb-apps/)
- [Google Earth Engine](https://earthengine.google.com/)
- [geemap documentation](https://geemap.org/)

---

## 📄 Licencia

Repositorio de uso personal. Datos de suelo provistos por USDA-NRCS bajo dominio público.
