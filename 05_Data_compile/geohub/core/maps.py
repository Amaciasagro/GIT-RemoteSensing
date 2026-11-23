"""Shared Folium maps (with support for Google Satellite, Google Hybrid, Esri World Imagery and DualMap)."""
import folium
from folium import plugins

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
OSCURO = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
GOOGLE_SAT = "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
GOOGLE_HYB = "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"


def mapa_base(centro, zoom=14, dibujo=False, base_preferida="Esri World Imagery"):
    """
    Satellite base (Google Satellite, Google Hybrid, Esri World Imagery) + dark;
    with optional drawing tools.
    """
    m = folium.Map(location=centro, zoom_start=zoom, tiles=None, control_scale=True)
    pref = str(base_preferida).lower()
    show_google = "google" in pref and "hyb" not in pref and "híb" not in pref
    show_hyb = "hyb" in pref or "híb" in pref
    show_oscuro = "oscur" in pref or "dark" in pref
    show_esri = not (show_google or show_hyb or show_oscuro)

    folium.TileLayer(tiles=OSCURO, attr="Esri", name="Dark", show=show_oscuro).add_to(m)
    folium.TileLayer(tiles=GOOGLE_HYB, attr="Google Hybrid", name="Google Hybrid", show=show_hyb).add_to(m)
    folium.TileLayer(tiles=GOOGLE_SAT, attr="Google Satellite", name="Google Satellite", show=show_google).add_to(m)
    folium.TileLayer(tiles=ESRI, attr="Esri World Imagery", name="Esri World Imagery", show=show_esri).add_to(m)
    if dibujo:
        plugins.Draw(export=False, draw_options={"polygon": True, "rectangle": True, "polyline": False,
                                                 "circle": False, "marker": False, "circlemarker": False}).add_to(m)
    return m


def agregar_aoi(m, geom, nombre="AOI boundary"):
    """
    Draws the AOI outline only as a perimeter line (LineString/MultiLineString) with a double high-contrast
    stroke and `interactive=False`, so it is clearly visible above the soil polygons
    without ever intercepting mouse hover or click events inside the field.
    """
    from shapely.geometry import mapping, shape

    try:
        borde_geom = mapping(shape(geom).boundary)
    except Exception:
        borde_geom = geom

    # Dark outer halo for contrast over any texture color or satellite
    folium.GeoJson(
        {"type": "Feature", "properties": {}, "geometry": borde_geom},
        name=f"{nombre} (halo)",
        control=False,
        interactive=False,
        style_function=lambda _: {
            "color": "#0b1320",
            "weight": 6.0,
            "opacity": 0.85,
            "fill": False,
            "fillOpacity": 0,
            "interactive": False,
        },
    ).add_to(m)
    # Bright main line on top of the thematic layers
    folium.GeoJson(
        {"type": "Feature", "properties": {}, "geometry": borde_geom},
        name=nombre,
        interactive=False,
        style_function=lambda _: {
            "color": "#00ff9d",
            "weight": 3.4,
            "opacity": 1.0,
            "dashArray": "7, 4",
            "fill": False,
            "fillOpacity": 0,
            "interactive": False,
        },
    ).add_to(m)


def mapa_dual_comparativo(centro, zoom, aoi_geom, cfg_izq, cfg_der, base_preferida="Google Satellite"):
    """
    Builds a synchronized side-by-side DualMap viewer to compare two dates and/or two satellite layers.
    Each cfg_* is a dict with:
      - 'url_capa': str | None (tile URL of the index or RGB)
      - 'nombre_capa': str
      - 'url_rgb': str | None (Sentinel-2/Landsat RGB tile URL for the date)
      - 'nombre_rgb': str
      - 'opacidad': float
    """
    m = plugins.DualMap(location=centro, zoom_start=zoom, tiles=None)
    pref = str(base_preferida).lower()
    usar_google = "google" in pref

    for sub_m in (m.m1, m.m2):
        folium.TileLayer(tiles=OSCURO, attr="Esri", name="Dark", show=False).add_to(sub_m)
        folium.TileLayer(tiles=ESRI, attr="Esri World Imagery", name="Esri World Imagery", show=not usar_google).add_to(sub_m)
        folium.TileLayer(tiles=GOOGLE_SAT, attr="Google Satellite", name="Google Satellite", show=usar_google).add_to(sub_m)

    for sub_m, cfg in ((m.m1, cfg_izq), (m.m2, cfg_der)):
        if cfg.get("url_rgb") and cfg.get("url_rgb") != cfg.get("url_capa"):
            folium.TileLayer(
                tiles=cfg["url_rgb"],
                attr="Sentinel-2 / Landsat RGB",
                name=cfg.get("nombre_rgb", "RGB Date"),
                overlay=True,
                show=False,
                opacity=1.0,
            ).add_to(sub_m)
        if cfg.get("url_capa"):
            folium.TileLayer(
                tiles=cfg["url_capa"],
                attr="Google Earth Engine",
                name=cfg.get("nombre_capa", "Layer"),
                overlay=True,
                show=True,
                opacity=float(cfg.get("opacidad", 0.85)),
            ).add_to(sub_m)
        if aoi_geom:
            folium.GeoJson(
                {"type": "Feature", "properties": {}, "geometry": aoi_geom},
                name="AOI",
                style_function=lambda _: {"color": "#2fd4a7", "weight": 2.5, "dashArray": "6,4", "fillOpacity": 0},
            ).add_to(sub_m)

    folium.LayerControl(collapsed=True).add_to(m)
    return m
