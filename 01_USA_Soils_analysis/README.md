# 🌱 Soil Analyzer: Advanced USA Soil & Topographic Mapping

**Autor:** Ariel Macías | Ingeniero Agrónomo · GIS & Remote Sensing Data Scientist

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Amaciasagro/GIT-RemoteSensing/blob/master/01_USA_Soils_analysis/01_USA_Soils_analysis.ipynb)
[![Streamlit App](https://img.shields.io/badge/-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://git-remotesensing-abuk6upwubrppkqjc7gwmf.streamlit.app)

Esta aplicación es una herramienta profesional de **Agricultura de Precisión** diseñada para diagnosticar lotes agrícolas en Estados Unidos. Integra datos oficiales de la **USDA-NRCS (Soil Data Mart)** con modelos de elevación global para generar reportes agronómicos y visualizaciones 3D fotorrealistas.

---


![Captura de Pantalla Principal](https://via.placeholder.com/800x400?text=Captura+de+la+App+Funcionando)

---

## 🚀 Guía Didáctica de Uso

La app está dividida en 4 módulos lógicos que siguen el flujo de trabajo de un consultor agronómico:

### 1. 📍 Definición del Lote (AOI)
El primer paso es delimitar el área de estudio. 
- **Cómo usarlo:** Puedes subir un archivo `.zip` (Shapefile) o `.geojson`. También permite pegar directamente las coordenadas en formato GeoJSON.
- **Visualización:** Verás el contorno sobre una capa de satélite para verificar que la ubicación sea correcta.

https://github.com/user-attachments/assets/d52144c0-92d2-4974-91e8-53a950058296


### 2. 🌱 Información de Suelos
Aquí ocurre la "magia" de la integración con la USDA.
- **Mapas:** Genera mapas automáticos de **Clase Textural** y **MUKey** (Unidades Cartográficas).
- **Reporte:** Al hacer clic, obtendrás una tabla detallada con pH, Materia Orgánica, CEC y más.
- **Gráficos de Perfil:** Visualiza cómo cambian las propiedades del suelo (arena, limo, arcilla) a medida que profundizas en el perfil (0-200 cm).

> 💡 **Espacio para Captura:** *Inserta aquí una imagen del mapa de texturas y el gráfico de barras apiladas.*

### 3. 🏔️ Modelos Topográficos
Análisis del relieve para entender el movimiento del agua y la erosión.
- **Curvas de Nivel:** Un mapa interactivo (Leaflet) donde puedes ver la elevación exacta pasando el mouse.
- **Hillshade:** Un mapa de sombras que resalta las micro-pendientes del terreno.

### 4. 🌐 Proyección 3D fotorrealista
La joya de la corona para presentaciones con clientes.
- **Superficie 3D:** Una maqueta rápida para ver la volumetría del campo.
- **Malla Satelital:** Proyecta imágenes de **Esri World Imagery** sobre el relieve.
- **Novedad:** El límite de tu lote se dibuja automáticamente sobre la montaña para no perder la referencia espacial.

---

## 📂 Estructura del Proyecto
El código está organizado de forma modular para facilitar su mantenimiento:

* `app.py`: El punto de entrada principal.
* `tabs/`: Contiene la lógica de interfaz de cada sección (AOI, Suelos, Topo, 3D).
* `utils/`: Motores de cálculo (Descarga de DEM, API de USDA, Exportación de archivos).
* `assets/`: Archivos estáticos, logos y mapas HTML base.
* `notebooks/`: Mi laboratorio de pruebas en Jupyter.

---

## 🛠️ Instalación y Configuración Local

Si eres desarrollador y quieres replicar este entorno:

1. **Clonar el repositorio:**
   ```bash
   git clone [https://github.com/tu-usuario/tu-repo.git](https://github.com/tu-usuario/tu-repo.git)
