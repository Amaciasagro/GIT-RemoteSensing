# 🌿 Crop Monitor — LAI & NDVI

Dashboard interactivo de monitoreo de cultivos con Sentinel-2 y Google Earth Engine.

## Instalación local

```bash
pip install -r requirements.txt
streamlit run app.py
```

La primera vez que corras la app, GEE va a pedir autenticación.
Si ya autenticaste con `earthengine authenticate`, no hace falta hacer nada extra.

## Deploy en Streamlit Cloud

1. Subí el repositorio a GitHub
2. Creá la app en [share.streamlit.io](https://share.streamlit.io)
3. Configurá los secrets en el panel de Streamlit Cloud:

```toml
# .streamlit/secrets.toml
[gee]
project = "tu-proyecto-gee"

# Opcional: cuenta de servicio (recomendado para producción)
key_json = '''
{
  "type": "service_account",
  "project_id": "...",
  "client_email": "...",
  ...
}
'''
```

## Flujo de uso

1. Ingresá el **Proyecto GEE** en la barra lateral
2. Configurá los parámetros (años, nubes, k, L)
3. Dibujá el lote en el mapa o subí un `.shp`/`.geojson`
4. Presioná **Analizar lote**
5. Explorá la curva fenológica y los mapas por mes

## Índices calculados

| Índice | Descripción |
|--------|-------------|
| NDVI   | Vigor vegetativo general |
| LAI    | Área foliar (Beer-Lambert) |
| EVI    | Vigor corregido por aerosoles y suelo |
| SAVI   | NDVI ajustado por suelo expuesto |
| NDWI   | Contenido de agua en canopeo/suelo |
