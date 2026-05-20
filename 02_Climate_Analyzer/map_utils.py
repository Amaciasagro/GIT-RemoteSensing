# ============================================================
# map_utils.py — Mapas Folium + utilidades espaciales
# ============================================================

import folium
from folium.plugins import Draw
import json, io, zipfile, tempfile, os
import geopandas as gpd
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from config import COLORES_LOTES, DARK_BG


# ════════════════════════════════════════════════════════════
# MAPA BASE
# ════════════════════════════════════════════════════════════
def build_mapa(
    center: list,
    zoom: int,
    lotes: list | None = None,   # [{"nombre": str, "geom": dict, "color": str}]
    allow_draw: bool = False,
) -> folium.Map:
    """
    Construye un mapa Folium con imagen satelital.
    lotes: lista de lotes a renderizar con su color individual.
    """
    m = folium.Map(location=center, zoom_start=zoom, tiles=None)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri", name="Satélite (Esri)", show=True,
    ).add_to(m)

    if lotes:
        for lote in lotes:
            geom  = lote.get("geom")
            color = lote.get("color", "#f1c40f")
            nombre = lote.get("nombre", "Lote")
            if geom:
                folium.GeoJson(
                    {"type": "Feature", "geometry": geom,
                     "properties": {"nombre": nombre}},
                    style_function=lambda _, c=color: {
                        "color": c, "weight": 2.5,
                        "dashArray": "6,4", "fillOpacity": 0.12,
                        "fillColor": c,
                    },
                    tooltip=folium.GeoJsonTooltip(fields=["nombre"]),
                    name=nombre,
                ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    if allow_draw:
        Draw(
            draw_options={
                "polygon": True, "rectangle": True,
                "polyline": False, "circle": False,
                "marker": False, "circlemarker": False,
            },
            edit_options={"edit": False},
        ).add_to(m)
    return m


# ════════════════════════════════════════════════════════════
# MAPA TEMÁTICO (tiles GEE sobre Folium)
# ════════════════════════════════════════════════════════════
def agregar_tile_gee(
    mapa: folium.Map,
    tile_url: str,
    nombre_capa: str,
    show: bool = True,
) -> None:
    """Agrega un tile layer de GEE al mapa Folium."""
    folium.TileLayer(
        tiles=tile_url,
        attr="Google Earth Engine",
        name=nombre_capa,
        overlay=True,
        show=show,
        opacity=0.85,
    ).add_to(mapa)


def agregar_lotes_overlay(mapa: folium.Map, lotes: list) -> None:
    """Agrega los contornos de los lotes sobre el raster temático."""
    for lote in lotes:
        geom  = lote.get("geom")
        color = lote.get("color", "#ffffff")
        nombre = lote.get("nombre", "Lote")
        if geom:
            folium.GeoJson(
                {"type": "Feature", "geometry": geom,
                 "properties": {"nombre": nombre}},
                style_function=lambda _, c=color: {
                    "color": c, "weight": 2.5,
                    "fillOpacity": 0.0,
                },
                tooltip=folium.GeoJsonTooltip(fields=["nombre"]),
            ).add_to(mapa)


def leyenda_gradiente_html(
    titulo: str,
    palette: list,
    val_min: float,
    val_max: float,
    unidad: str = "",
) -> str:
    """
    Genera HTML de leyenda de gradiente de color para incrustar en Folium.
    """
    gradient = ", ".join(palette)
    mid = (val_min + val_max) / 2
    return f"""
    <div style="
        position: fixed; bottom: 40px; left: 40px; z-index: 9999;
        background: rgba(13,21,32,0.88); border-radius: 8px;
        padding: 10px 16px; font-family: sans-serif; min-width: 180px;
        border: 1px solid #1a2d42;
    ">
      <div style="color:#d4e2f0; font-size:12px; font-weight:600; margin-bottom:6px;">
        {titulo}
      </div>
      <div style="
        height: 14px; border-radius: 4px; width: 100%;
        background: linear-gradient(to right, {gradient});
        margin-bottom: 4px;
      "></div>
      <div style="display:flex; justify-content:space-between;
                  color:#7a99b8; font-size:10px;">
        <span>{val_min:+.0f} {unidad}</span>
        <span>{mid:+.0f} {unidad}</span>
        <span>{val_max:+.0f} {unidad}</span>
      </div>
    </div>
    """


def build_mapa_tematico(
    center: list,
    zoom: int,
    tile_url: str,
    nombre_capa: str,
    lotes: list,
    palette: list,
    val_min: float,
    val_max: float,
    titulo_leyenda: str,
    unidad: str = "",
    capas_extra: list | None = None,  # [{"tile_url": str, "nombre": str}]
) -> folium.Map:
    """
    Construye un mapa Folium con raster temático GEE + contornos + leyenda.
    capas_extra: capas adicionales que el usuario puede activar/desactivar.
    """
    m = folium.Map(location=center, zoom_start=zoom, tiles=None)

    # Satélite base
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri", name="Satélite (Esri)", show=True,
    ).add_to(m)

    # Capa temática principal
    agregar_tile_gee(m, tile_url, nombre_capa)

    # Capas adicionales opcionales
    if capas_extra:
        for capa in capas_extra:
            agregar_tile_gee(m, capa["tile_url"], capa["nombre"], show=False)

    # Contornos de lotes
    agregar_lotes_overlay(m, lotes)

    # Leyenda
    leyenda_html = leyenda_gradiente_html(
        titulo_leyenda, palette, val_min, val_max, unidad
    )
    m.get_root().html.add_child(folium.Element(leyenda_html))

    folium.LayerControl(collapsed=False).add_to(m)
    return m


# ════════════════════════════════════════════════════════════
# CARGA DE ARCHIVOS AOI
# ════════════════════════════════════════════════════════════
def cargar_aoi_desde_archivo(archivos) -> dict | None:
    """Lee .shp (zip) o .geojson y retorna geometría GeoJSON dict."""
    tmp = tempfile.mkdtemp()
    for f in archivos:
        with open(os.path.join(tmp, f.name), "wb") as fp:
            fp.write(f.read())
    for fname in os.listdir(tmp):
        if fname.endswith(".zip"):
            with zipfile.ZipFile(os.path.join(tmp, fname), "r") as z:
                z.extractall(tmp)
    validos = [f for f in os.listdir(tmp) if f.endswith((".shp", ".geojson"))]
    if not validos:
        return None
    gdf  = gpd.read_file(os.path.join(tmp, validos[0])).to_crs(epsg=4326)
    geom = unary_union(gdf.geometry)
    return mapping(geom)


# ════════════════════════════════════════════════════════════
# CENTROIDE Y ÁREA
# ════════════════════════════════════════════════════════════
def centroide_y_area(geom_dict: dict) -> tuple[float, float, float]:
    """Retorna (lat, lon, area_ha) del polígono."""
    shp = shape(geom_dict)
    lat = shp.centroid.y
    lon = shp.centroid.x
    area_ha = shp.area * 111320 ** 2 / 10000
    return lat, lon, area_ha


def bbox_lotes(lotes: list) -> list:
    """Calcula el centro [lat, lon] del bounding box de todos los lotes."""
    geoms = [shape(l["geom"]) for l in lotes if l.get("geom")]
    if not geoms:
        return [-32.0, -63.0]
    union  = unary_union(geoms)
    bounds = union.bounds  # (minx, miny, maxx, maxy)
    return [
        (bounds[1] + bounds[3]) / 2,
        (bounds[0] + bounds[2]) / 2,
    ]
    
    
# ════════════════════════════════════════════════════════════
# DESCARGA DE CAPAS
# ════════════════════════════════════════════════════════════

def exportar_mapa_html(mapa: folium.Map) -> bytes:
    """Exporta un mapa Folium como bytes HTML para st.download_button."""
    from io import BytesIO
    buffer = BytesIO()
    mapa.save(buffer, close_file=False)
    return buffer.getvalue()

