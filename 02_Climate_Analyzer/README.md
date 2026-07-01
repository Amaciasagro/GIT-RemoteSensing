[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/02_Climate_Analyzer/notebooks/02_Climatic_Analysis.ipynb)
[![Streamlit App](https://img.shields.io/badge/-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://git-remotesensing-9wvgyb6zyebxouaujadipk.streamlit.app/)

# 🌦️ Climate Analyzer — Dashboard Climático Interactivo

**Análisis climático agrónomico espacial con Google Earth Engine y Streamlit**  
*Autor: Ariel Macías — Ingeniero Agrónomo & Analista SIG*

---

## ¿Qué hace esta app?

https://github.com/user-attachments/assets/b5878891-908d-4510-8057-24a1d89127c2

---

## Funcionalidades

### 📈 Tab 1 — Series Temporales (ERA5)
- Precipitación, ETo Penman-Monteith FAO-56, temperatura mensual
- Balance hídrico mensual (P − ETo)
- Detalle diario del mes en curso con acumulados
- Humedad relativa y velocidad de viento
- Descarga de datos diarios en `.csv`

### 🌧️ Tab 2 — Anomalías CHIRPS
- Compara la precipitación del período contra el promedio histórico de los últimos 20 años
- Mapa temático: tonos rojos = déficit / azules = exceso
- Anomalía absoluta (mm) y porcentual (%)
- Estadísticas zonales por lote: media, mínimo, máximo

### 💧 Tab 3 — Balance Hídrico Espacial
- Combina CHIRPS y ERA5 píxel a píxel para calcular P − ETo
- ETo estimada con Hargreaves-Samani (raster)
- Tres capas visualizables: balance, precipitación, ETo
- Ideal para zonificar necesidad de riego y heterogeneidad intra-lote

### 🌡️ Tab 4 — Riesgo Térmico
- Conteo de días con **helada** (Tmin < umbral ajustable) por píxel
- Conteo de días con **calor extremo** (Tmax > umbral ajustable) por píxel
- Umbrales configurables desde la barra lateral
- Niveles de alerta automáticos (bajo / moderado / alto)

### 🔀 Tab 5 — Comparación de Lotes
- Tabla comparativa con todas las métricas agronómicas
- Gráficos de precipitación, balance y temperatura superpuestos
- Gráfico de radar normalizado multi-lote
- Conclusiones automáticas (lote con más lluvia, mejor balance, mayor GDA, etc.)
- Descarga de tabla comparativa en `.csv`

---

## 🛠️ Tecnologías

| Tecnología | Rol |
| :--- | :--- |
| **Streamlit** | Interfaz de usuario y despliegue web |
| **Google Earth Engine** | Acceso a ERA5-Land y cómputo espacial en la nube |
| **ERA5-Land (ECMWF)** | Reanálisis climático global a ~11 km de resolución |
| **Folium / Streamlit-Folium** | Mapa interactivo para definir el lote |
| **Plotly** | Gráficos dinámicos de series temporales |
| **GeoPandas / Shapely** | Procesamiento de geometrías vectoriales |
| **google-auth** | Autenticación OAuth2 con Google Earth Engine |

---

## 📦 Variables y métricas

| Variable / Métrica | Fuente | Unidad |
| :--- | :--- | :--- |
| Precipitación | ERA5-Land | mm/día |
| T. máxima / mínima / media | ERA5-Land | °C |
| Humedad Relativa | Calculada (punto de rocío) | % |
| Radiación solar descendente | ERA5-Land | MJ/m²/día |
| Velocidad de viento | ERA5-Land (u, v a 10 m) | m/s |
| Evapotranspiración real | ERA5-Land | mm/día |
| **ETo Penman-Monteith** | FAO-56 calculada | mm/día |
| **Balance hídrico** | Lluvia − ETo acum. | mm |
| **Grados Día Acumulados** | (T_med − T_base) · días | °C·día |

---

## 🛠️ Inicio Rápido

Tienes dos opciones para usar esta herramienta:

### Opción A: Usar la App en Línea (No requiere instalación) 🌐

Accede a la aplicación directamente en tu navegador — ideal para análisis rápidos y demostraciones:

**👉[Iniciar Climate_Analyzer_App](https://git-remotesensing-9wvgyb6zyebxouaujadipk.streamlit.app/) No requiere configuración. Simplemente sube el límite de tu lote y comienza a analizar.**

### Opción B: Ejecución Local (Para Desarrolladores) 💻

Clona el repositorio y ejecútalo en tu propia computadora — ideal para personalización y uso sin conexión:

1. **Clona el repositorio:**
```Bash 
    git clone https://github.com/Amaciasagro/GIT-RemoteSensing.git
    cd GIT-RemoteSensing/02_Climate_Analyzer
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

## Estructura del proyecto

```
climate_analyzer/
├── app.py                  # Entry point + orquestación de tabs
├── config.py               # Constantes, colecciones GEE, paletas, CSS
├── gee_client.py           # Queries GEE: ERA5, CHIRPS, mapas temáticos
├── metrics.py              # ETo PM, HR, GDA, balance (series temporales)
├── charts.py               # Todos los gráficos Plotly
├── map_utils.py            # Folium, mapas temáticos, carga de AOI
├── ui/
│   ├── sidebar.py          # Multi-lote, parámetros, carga de archivos
│   ├── tab_series.py       # Tab 1: Series temporales ERA5
│   ├── tab_anomalias.py    # Tab 2: Anomalías CHIRPS
│   ├── tab_balance.py      # Tab 3: Balance hídrico espacial
│   ├── tab_riesgos.py      # Tab 4: Riesgo térmico (heladas/calor)
│   └── tab_comparar.py     # Tab 5: Comparación multi-lote
├── requirements.txt
└── README.md
```

---

## Flujo de uso

1. **Abrís la app** → aparece un mapa limpio
2. **Dibujás un polígono** en el mapa o subís un `.shp`/`.geojson`
3. **Confirmás el lote** en la barra lateral (se guarda con nombre y color)
4. **Repetís** para agregar más lotes (sin límite)
5. **Presionás "Analizar lotes"** → descarga ERA5 para cada lote
6. **Navegás los tabs** para explorar series, anomalías, balance, riesgos y comparativas
7. **Descargás** los datos o tablas según necesites

---

## Notas metodológicas

### ETo Penman-Monteith FAO-56
Implementación según Allen et al. (1998). Se usa para las series temporales (Tab 1 y Tab 5). Requiere: Tmax, Tmin, Tdew, radiación solar, viento a 2m.

### ETo Hargreaves-Samani
Versión simplificada para el cálculo raster píxel a píxel (Tab 3). Solo requiere Tmax, Tmin y Ra (radiación extraterrestre). Apropiada para comparaciones espaciales relativas.

### Anomalía CHIRPS
El baseline histórico usa el mismo rango de días del año (DOY) sobre los `N` años anteriores al período analizado. Esto elimina el efecto estacional y hace comparables períodos cortos.

### Resolución espacial
| Fuente   | Resolución | Cobertura temporal |
|----------|------------|-------------------|
| ERA5-Land | ~11 km    | 1950–presente     |
| CHIRPS    | ~5 km     | 1981–presente     |

---

## Dependencias principales

| Librería | Uso |
|---------|-----|
| `earthengine-api` | Queries y procesamiento GEE |
| `streamlit` | Interfaz web |
| `streamlit-folium` | Renderizado de mapas interactivos |
| `folium` | Construcción de mapas Leaflet |
| `plotly` | Gráficos interactivos |
| `geopandas` / `shapely` | Carga y procesamiento de geometrías |
| `pandas` / `numpy` | Manipulación de series temporales |

---

## Roadmap futuro

- [ ] Exportar mapas temáticos como GeoTIFF (via `ee.batch`)
- [ ] Timelapse animado (GIF/MP4) por semana o década
- [ ] Integración con datos de pronóstico (GFS/ECMWF open)
- [ ] Índices de sequía (SPI, NDVI desde Sentinel/Landsat)
- [ ] Reporte PDF automático por lote

---

*Desarrollado con Google Earth Engine, Streamlit y datos abiertos de ECMWF y UCSB-CHG.*
