



# 🌦️ Climate Analyzer — Dashboard Climático Interactivo

**Análisis climático profesional sobre lotes agrícolas** utilizando datos **ERA5-Land (ECMWF)** procesados en tiempo real vía **Google Earth Engine**. Diseñado para agrónomos y especialistas en Teledetección que necesitan caracterizar el clima de un lote sin escribir código.

---

## 🎬 Demo en video

<!-- Cuando tengas el video listo, reemplazá VIDEO_ID con tu ID de YouTube y descomentá estas líneas: -->
<!-- [![Demo Climate Analyzer](https://img.youtube.com/vi/VIDEO_ID/maxresdefault.jpg)](https://www.youtube.com/watch?v=VIDEO_ID) -->

https://github.com/user-attachments/assets/b5878891-908d-4510-8057-24a1d89127c2

---

## ✨ Funcionalidades

**Variables ERA5-Land extraídas**
Precipitación diaria, temperatura máx/mín/media, punto de rocío, radiación solar, componentes de viento y evapotranspiración real — todas promediadas sobre el área exacta del lote.

**Métricas agronómicas calculadas**
- **ETo Penman-Monteith FAO-56** — evapotranspiración de referencia diaria (mm)
- **Humedad Relativa** estimada a partir del punto de rocío (%)
- **Balance Hídrico** acumulado — Lluvia − ETo (mm)
- **Grados Día Acumulados (GDA)** sobre temperatura base configurable

**Gráficos interactivos (Plotly)**
- Barras de precipitación + ETo + temperatura mensual
- Balance hídrico mensual (verde/rojo según superávit o déficit)
- Acumulados diarios del mes en curso (lluvia, ETo, balance, GDA)
- Humedad relativa y velocidad de viento mensual

**Gestión de lotes**
Dibujá un polígono en el mapa o cargá un archivo `.shp` (en `.zip`) o `.geojson`. Muestra el área en hectáreas y centraliza el mapa automáticamente.

**Descarga de datos**
Exportá la serie diaria completa en formato `.csv` con un solo clic.

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

## 💻 Instalación local

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/climate-analyzer.git
cd climate-analyzer

# 2. Crear entorno virtual e instalar dependencias
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Configurar credenciales GEE
mkdir -p .streamlit
cp secrets.toml .streamlit/secrets.toml
# → Editá .streamlit/secrets.toml con tus credenciales reales

# 4. Ejecutar
streamlit run app.py
```

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

## 📁 Estructura del proyecto

```
climate-analyzer/
│
├── app.py                  # Aplicación principal
├── requirements.txt        # Dependencias Python
├── secrets.toml            # Plantilla de credenciales (NO subir con datos reales)
├── .gitignore
│
└── .streamlit/
    └── secrets.toml        # Credenciales reales (ignorado por git)
```

---

## 🗺️ Cómo usar la app

1. **Definir el lote** — dibujá un polígono en el mapa o cargá un `.shp`/`.geojson`.
2. **Configurar parámetros** — ajustá el período de análisis y la temperatura base para GDA.
3. **Analizar** — presioná *Analizar clima del lote*. ERA5 se descarga vía GEE (1–2 min la primera vez).
4. **Explorar** — revisá los gráficos mensuales y el detalle diario del mes en curso.
5. **Exportar** — descargá la serie diaria completa en `.csv`.

---

## 📄 Licencia

Este proyecto se distribuye bajo la licencia **MIT**.

---

**Autor:** Ariel Macías | Ingeniero Agrónomo · GIS & Remote Sensing · © 2026
