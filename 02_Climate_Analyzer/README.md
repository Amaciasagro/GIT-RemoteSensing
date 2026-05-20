# 🌦️ Climate Analyzer — ERA5 + CHIRPS

**Análisis climático agrónomico espacial con Google Earth Engine y Streamlit**  
*Autor: Ariel Macías — Ingeniero Agrónomo & Analista SIG*

---

## ¿Qué hace esta app?

Climate Analyzer es una herramienta profesional de análisis climático que combina dos de las fuentes de datos satelitales más robustas del mundo:

- **ERA5-Land (ECMWF)** — temperatura, viento, radiación, evaporación, ~11 km/día
- **CHIRPS (UCSB-CHG)** — precipitación, ~5 km/día, desde 1981 a la actualidad

El flujo de trabajo es simple: **definís uno o más polígonos** (lotes, parcelas, áreas de monitoreo) y la app extrae, procesa y visualiza los datos para ese ámbito geográfico exacto.

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

## Instalación

```bash
git clone <repo>
cd climate_analyzer
pip install -r requirements.txt
```

### Configurar credenciales GEE

Creá el archivo `.streamlit/secrets.toml`:

```toml
EARTHENGINE_PROJECT = "tu-proyecto-gee"

[google_auth]
client_id     = "xxxx.apps.googleusercontent.com"
client_secret = "xxxx"
refresh_token = "xxxx"
```

Para obtener el `refresh_token` usá el flujo OAuth2 de GEE:

```bash
earthengine authenticate
```

El token queda en `~/.config/earthengine/credentials`.

---

## Ejecución

```bash
streamlit run app.py
```

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
