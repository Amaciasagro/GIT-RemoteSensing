"""Mapas Folium: mapa base, dibujo de AOI y capas temáticas raster con gradientes."""
import numpy as np
import folium
from folium import plugins
import branca.colormap as bcm

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_DARK = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
GOOGLE_SAT = "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
GOOGLE_HYB = "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"

AZULES = [(0, (190, 230, 255)), (0.3, (60, 160, 255)), (0.65, (20, 70, 200)), (1, (90, 20, 140))]
CALIDOS = [(0, (255, 255, 178)), (0.4, (253, 141, 60)), (0.7, (227, 26, 28)), (1, (128, 0, 38))]
VERDES = [(0, (247, 252, 185)), (0.5, (120, 198, 121)), (1, (0, 90, 50))]
TERRENO = [(0, (40, 90, 60)), (0.35, (180, 200, 110)), (0.7, (190, 150, 100)), (1, (245, 245, 245))]
HUMEDAD = [(0, (180, 110, 40)), (0.5, (230, 230, 160)), (1, (30, 100, 200))]
CLASES = {1: (120, 200, 255), 2: (30, 110, 255), 3: (150, 30, 200)}
CLASES_TXT = {1: "Leve", 2: "Moderado", 3: "Severo"}

# nombre -> (clave en resultados, anclas, unidad, vmin, vmax ('auto' = percentil 98), ocultar valores <=)
CAPAS = {
    "💧 Lámina de agua acumulada (mm)": ("lamina", AZULES, "mm", 0, "auto", 0.05),
    "🚨 Zonas de encharcamiento (clases)": ("categoria", None, "", 0, 3, None),
    "🌊 Escorrentía generada (mm)": ("escorrentia", CALIDOS, "mm", 0, "auto", None),
    "⬇️ Infiltración (mm)": ("infiltracion", AZULES, "mm", 0, "auto", None),
    "🔄 Flujo subsuperficial / Interflow (mm)": ("interflow", AZULES, "mm", 0, "auto", 0.02),
    "⚓ Profundidad estimada de napa (m)": ("prof_napa_m", HUMEDAD, "m", 0.3, 4.0, None),
    "🌱 Humedad final del suelo (% AWC)": ("humedad1_pct", HUMEDAD, "%", 0, 100, None),
    "📈 Número de curva (CN)": ("cn", CALIDOS, "", 30, 98, None),
    "⛰️ Pendiente (%)": ("pendiente", CALIDOS, "%", 0, "auto", None),
    "🗻 Elevación (m)": ("dem", TERRENO, "m", "auto0", "auto", None),
    "🌿 NDVI": ("ndvi", VERDES, "", 0, 0.9, None),
    "💦 NDWI": ("ndwi", HUMEDAD, "", -0.6, 0.3, None),
}


def mapa_base(centro, zoom=14, dibujo=False, satelite_primero=False):
    """Mapa Folium con bases Google Satellite, Esri Satélite y Oscuro y, opcionalmente, herramientas de dibujo."""
    m = folium.Map(location=centro, zoom_start=zoom, tiles=None, control_scale=True)
    oscuro = dict(tiles=ESRI_DARK, attr="Esri", name="Oscuro", show=not satelite_primero)
    gsat = dict(tiles=GOOGLE_SAT, attr="Google Satellite", name="Google Satélite", show=False)
    ghyb = dict(tiles=GOOGLE_HYB, attr="Google Hybrid", name="Google Híbrido", show=False)
    sat = dict(tiles=ESRI, attr="Esri World Imagery", name="Esri Satélite", show=satelite_primero)
    for cfg in ([oscuro, gsat, ghyb, sat] if satelite_primero else [sat, gsat, ghyb, oscuro]):
        folium.TileLayer(**cfg).add_to(m)
    if dibujo:
        plugins.Draw(export=False, draw_options={
            "polygon": True, "rectangle": True, "polyline": False,
            "circle": False, "marker": False, "circlemarker": False}).add_to(m)
    return m


def _color_y_grosor_subcuenca(val, vmin, vmax):
    """Devuelve (color_hex, grosor_borde_px) proporcional a la magnitud hidrológica de la subcuenca."""
    t = float(np.clip((val - vmin) / (vmax - vmin + 1e-6), 0.0, 1.0)) if vmax > vmin else 0.55
    pos = [a[0] for a in CALIDOS]
    rgb = [int(np.interp(t, pos, [a[1][k] for a in CALIDOS])) for k in range(3)]
    grosor = round(2.2 + 3.8 * t, 2)  # 2.2 px a 6.0 px según magnitud
    return _hex(rgb), grosor


def agregar_red_drenaje(m, red_drenaje, criterio_grosor="grosor_px"):
    """Superpone la red de drenaje (HydroSHEDS / NHD / DEM D8 / Local) con grosor variable según jerarquía/descarga/acumulación."""
    if not red_drenaje or not red_drenaje.get("features_geojson"):
        return
    feats = red_drenaje["features_geojson"].get("features", [])
    if not feats:
        return
    folium.GeoJson(
        red_drenaje["features_geojson"],
        name=f"Red de drenaje ({red_drenaje.get('fuente', 'HydroSHEDS')})",
        style_function=lambda f, cg=criterio_grosor: {
            "color": f.get("properties", {}).get("color", "#00b4d8"),
            "weight": float(f.get("properties", {}).get(cg, f.get("properties", {}).get("grosor_px", 2.5))),
            "opacity": 0.92,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["nombre", "orden", "descarga_cms", "acumulacion", "longitud_km", "fuente"],
            aliases=["Cauce:", "Jerarquía / Orden:", "Descarga media (m³/s):", "Área drenada / Acum. (km²):", "Longitud (km):", "Fuente:"],
        ),
    ).add_to(m)


def agregar_aoi(m, geom, cuenca_geom=None, cuenca_meta=None, campo_metrica=None, etiqueta_metrica=None):
    """
    Contorno del AOI y, opcionalmente, de las subcuencas hidrológicas.
    Si se especifica `campo_metrica` (ej. 'lamina_mean_mm' o 'lamina_max_mm'), aplica color y grosor de borde
    proporcionales a la magnitud hidrológica de cada subcuenca.
    """
    if cuenca_meta and isinstance(cuenca_meta, dict) and cuenca_meta.get("features_geojson"):
        feats = cuenca_meta["features_geojson"].get("features", [])
        usar_mag = campo_metrica and feats and (campo_metrica in feats[0].get("properties", {}))
        if usar_mag:
            vals = [float(f["properties"].get(campo_metrica, 0.0)) for f in feats]
            vmin, vmax = min(vals), max(vals)
            for f in feats:
                v = float(f["properties"].get(campo_metrica, 0.0))
                c_hex, w_px = _color_y_grosor_subcuenca(v, vmin, vmax)
                f["properties"]["_color_mag"] = c_hex
                f["properties"]["_weight_mag"] = w_px
                f["properties"]["_val_activo"] = round(v, 2)

            campos_tt = ["huc", "nombre", "area_ha", "_val_activo", "lamina_mean_mm", "lamina_max_mm", "escorrentia_mean_mm"]
            alias_tt = [
                "Código HUC:", "Subcuenca:", "Área (ha):",
                f"{etiqueta_metrica or campo_metrica}:",
                "Lámina media (mm):", "Lámina máx. (mm):", "Escorrentía media (mm):",
            ]
            folium.GeoJson(
                cuenca_meta["features_geojson"],
                name=f"Subcuencas por magnitud ({etiqueta_metrica or campo_metrica})",
                style_function=lambda f: {
                    "color": f["properties"].get("_color_mag", "#ff9f43"),
                    "weight": float(f["properties"].get("_weight_mag", 3.5)),
                    "fillColor": f["properties"].get("_color_mag", "#ff9f43"),
                    "fillOpacity": 0.14,
                },
                tooltip=folium.GeoJsonTooltip(fields=campos_tt, aliases=alias_tt),
            ).add_to(m)
        else:
            folium.GeoJson(
                cuenca_meta["features_geojson"],
                name=f"Subcuenca ({cuenca_meta.get('nivel', 'WBD')}: {cuenca_meta.get('huc_codigo', '')})",
                style_function=lambda _: {
                    "color": "#2f9bff", "weight": 2.4, "dashArray": "6, 4",
                    "fillColor": "#2f9bff", "fillOpacity": 0.07,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["huc", "nombre", "area_ha", "states"],
                    aliases=["Código HUC:", "Subcuenca:", "Área (ha):", "Estado(s):"],
                ),
            ).add_to(m)
    elif cuenca_geom:
        try:
            from shapely.geometry import mapping, shape
            borde_cuenca = mapping(shape(cuenca_geom).boundary)
        except Exception:
            borde_cuenca = cuenca_geom
        folium.GeoJson(
            {"type": "Feature", "properties": {}, "geometry": borde_cuenca},
            name="Cuenca zonal aportante",
            interactive=False,
            style_function=lambda _: {
                "color": "#2f9bff", "weight": 2.4, "dashArray": "6, 4",
                "fill": False, "fillOpacity": 0, "interactive": False,
            },
        ).add_to(m)

    # Dibujar el límite del AOI únicamente como línea perimetral (LineString/MultiLineString) con doble trazo
    # de alto contraste e interactive=False: así los límites del AOI se ven nítidos por encima de cualquier
    # capa temática (como Unidades Cartográficas de suelo) sin interceptar jamás el cursor dentro del lote.
    try:
        from shapely.geometry import mapping, shape
        borde_aoi = mapping(shape(geom).boundary)
    except Exception:
        borde_aoi = geom

    folium.GeoJson(
        {"type": "Feature", "properties": {}, "geometry": borde_aoi},
        name="AOI (halo)",
        control=False,
        interactive=False,
        style_function=lambda _: {
            "color": "#0b1320", "weight": 6.0, "opacity": 0.85,
            "fill": False, "fillOpacity": 0, "interactive": False,
        },
    ).add_to(m)
    folium.GeoJson(
        {"type": "Feature", "properties": {}, "geometry": borde_aoi},
        name="AOI (Lote principal)",
        interactive=False,
        style_function=lambda _: {
            "color": "#00ff9d", "weight": 3.4, "opacity": 1.0, "dashArray": "7, 4",
            "fill": False, "fillOpacity": 0, "interactive": False,
        },
    ).add_to(m)


def colorear(arr, vmin, vmax, anclas, alpha, oculta_menor=None):
    """Convierte un arreglo en imagen RGBA con gradiente continuo."""
    t = np.nan_to_num(np.clip((arr - vmin) / (vmax - vmin + 1e-9), 0, 1))
    pos = [a[0] for a in anclas]
    rgb = np.stack([np.interp(t, pos, [a[1][k] for a in anclas]) for k in range(3)], -1)
    rgba = np.dstack([rgb, np.full(arr.shape, 255.0 * alpha)])
    inval = ~np.isfinite(arr)
    if oculta_menor is not None:
        inval |= arr <= oculta_menor
    rgba[inval, 3] = 0
    return rgba.astype(np.uint8)


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c)


def _preparar_rgba_capa(res, nombre_capa, opacidad, recortar_aoi=True, arr_override=None):
    """Prepara la matriz RGBA y los metadatos de escala para una variable temática de `CAPAS`."""
    clave, anclas, unidad, vmin, vmax, oculta = CAPAS[nombre_capa]
    a = res["arrays"]
    campos = {**a, "dem": res["dem"], "ndvi": res["ndvi"], "ndwi": res["ndwi"],
              "humedad1_pct": a["humedad1"] * 100.0}
    arr = (arr_override if arr_override is not None else campos[clave]).astype(float).copy()
    mask = res["mascara"] if recortar_aoi else res.get("mascara_dominio", res["mascara"])
    arr[~mask] = np.nan
    if vmax == "auto":
        v = arr[np.isfinite(arr)]
        vmax = max(float(np.percentile(v, 98)) if v.size else 1.0, 1e-3)
    if vmin == "auto0":
        v = arr[np.isfinite(arr)]
        vmin = float(v.min()) if v.size else 0.0
        vmax = float(v.max()) if v.size else 1.0

    if clave == "categoria":
        rgba = np.zeros(arr.shape + (4,), np.uint8)
        for k, col in CLASES.items():
            sel = (arr == k)
            rgba[sel] = [*col, int(255 * opacidad)]
    else:
        rgba = colorear(arr, vmin, vmax, anclas, opacidad, oculta)
    return dict(clave=clave, anclas=anclas, unidad=unidad, vmin=vmin, vmax=vmax, rgba=rgba, arr=arr)


def _html_leyenda_compacta(nombre_capa, info_capa, umbral, lado="left", etiqueta_panel=None):
    """Construye una leyenda flotante HTML para una capa temática (izquierda o derecha)."""
    pos_css = "left:12px;" if lado == "left" else "right:12px;"
    titulo_base = nombre_capa.split(" ", 1)[1] if " " in nombre_capa else nombre_capa
    encabezado = f"<div style='color:#00f5d4;font-weight:700;font-size:11px;margin-bottom:2px'>{etiqueta_panel}</div>" if etiqueta_panel else ""
    if info_capa["clave"] == "categoria":
        filas = "".join(
            f"<div><span style='background:{_hex(c)};display:inline-block;width:13px;height:13px;"
            f"margin-right:6px;border-radius:3px;vertical-align:middle'></span>{CLASES_TXT[k]}</div>"
            for k, c in CLASES.items()
        )
        return (
            f"<div style='position:fixed;bottom:28px;{pos_css}z-index:9999;background:rgba(13,23,39,.92);"
            f"color:#dce6f2;padding:8px 12px;border-radius:8px;font-size:12px;border:1px solid #1f3350;"
            f"box-shadow:0 2px 8px rgba(0,0,0,.45)'>"
            f"{encabezado}<b>{titulo_base}</b> (umbral {umbral:g} mm)<br>{filas}</div>"
        )
    anclas = info_capa["anclas"]
    vmin, vmax = float(info_capa["vmin"]), float(info_capa["vmax"])
    stops = ", ".join(f"{_hex(c)} {int(round(p * 100))}%" for p, c in anclas)
    v_med = 0.5 * (vmin + vmax)
    fmt = ".2f" if (vmax - vmin) < 2.0 else (".1f" if (vmax - vmin) < 25.0 else ".0f")
    return (
        f"<div style='position:fixed;bottom:28px;{pos_css}z-index:9999;background:rgba(13,23,39,.92);"
        f"color:#dce6f2;padding:8px 12px;border-radius:8px;font-size:11.5px;border:1px solid #1f3350;"
        f"min-width:190px;box-shadow:0 2px 8px rgba(0,0,0,.45)'>"
        f"{encabezado}<b>{titulo_base}</b>"
        f"<div style='height:10px;border-radius:4px;margin:5px 0 3px 0;background:linear-gradient(90deg, {stops});"
        f"border:1px solid rgba(255,255,255,.2)'></div>"
        f"<div style='display:flex;justify-content:space-between;font-size:10.5px;color:#b8c7dc'>"
        f"<span>{vmin:{fmt}}</span><span>{v_med:{fmt}}</span><span>{vmax:{fmt}}</span></div></div>"
    )


def mapa_resultado(res, nombre_capa, opacidad, aoi_geom, umbral, cuenca_geom=None, cuenca_meta=None,
                   recortar_aoi=True, arr_override=None, campo_metrica_sub=None, etiqueta_metrica_sub=None,
                   red_drenaje=None, criterio_grosor_red="grosor_px", s2_rgb=None, s2_fecha=None):
    """Mapa temático 2D de una variable del resultado, imagen Sentinel-2 de la fecha disponible, subcuencas y red de drenaje."""
    info = _preparar_rgba_capa(res, nombre_capa, opacidad, recortar_aoi=recortar_aoi, arr_override=arr_override)
    clave, anclas, vmin, vmax, rgba = info["clave"], info["anclas"], info["vmin"], info["vmax"], info["rgba"]

    (s, w), (n, e) = res["bounds"]
    m = mapa_base([(s + n) / 2, (w + e) / 2], zoom=14 if cuenca_geom else 15, satelite_primero=True)
    if s2_rgb is not None and s2_rgb.ndim == 3:
        etq_s2 = f"🛰️ Sentinel-2 ({s2_fecha})" if s2_fecha else "🛰️ Sentinel-2 (fecha evento)"
        folium.raster_layers.ImageOverlay(
            image=s2_rgb, bounds=res["bounds"], name=etq_s2,
            opacity=1.0, origin="upper", interactive=False, show=True,
        ).add_to(m)
    folium.raster_layers.ImageOverlay(image=rgba, bounds=res["bounds"], name=nombre_capa,
                                      opacity=1.0, origin="upper", interactive=False).add_to(m)
    agregar_aoi(
        m, aoi_geom,
        cuenca_geom=cuenca_geom,
        cuenca_meta=cuenca_meta,
        campo_metrica=campo_metrica_sub,
        etiqueta_metrica=etiqueta_metrica_sub,
    )
    if red_drenaje is not None:
        agregar_red_drenaje(m, red_drenaje, criterio_grosor=criterio_grosor_red)
    if clave == "categoria":
        m.get_root().html.add_child(folium.Element(_html_leyenda_compacta(nombre_capa, info, umbral, lado="left")))
    else:
        idx = [vmin + p * (vmax - vmin) for p, _ in anclas]
        cmap = bcm.LinearColormap([_hex(c) for _, c in anclas], index=idx, vmin=vmin, vmax=vmax,
                                  caption=f"{nombre_capa.split(' ', 1)[1]}")
        cmap.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def mapa_comparativo_2d(res, capa_izq, capa_der, opacidad, aoi_geom, umbral, cuenca_geom=None, cuenca_meta=None,
                        recortar_aoi=True, arr_override_izq=None, arr_override_der=None,
                        campo_metrica_sub=None, etiqueta_metrica_sub=None,
                        red_drenaje=None, criterio_grosor_red="grosor_px", s2_rgb=None, s2_fecha=None,
                        subtitulo_izq=None, subtitulo_der=None):
    """Mapa comparativo sincronizado (`DualMap`) para contrastar dos mapas temáticos de `CAPAS` con zoom y desplazamiento vinculados."""
    info_izq = _preparar_rgba_capa(res, capa_izq, opacidad, recortar_aoi=recortar_aoi, arr_override=arr_override_izq)
    info_der = _preparar_rgba_capa(res, capa_der, opacidad, recortar_aoi=recortar_aoi, arr_override=arr_override_der)

    (s, w), (n, e) = res["bounds"]
    centro = [(s + n) / 2, (w + e) / 2]
    zoom = 14 if cuenca_geom else 15
    dm = plugins.DualMap(location=centro, zoom_start=zoom, tiles=None, control_scale=True)

    for sub_m, nom_capa, info_c in ((dm.m1, capa_izq, info_izq), (dm.m2, capa_der, info_der)):
        oscuro = dict(tiles=ESRI_DARK, attr="Esri", name="Oscuro", show=False)
        gsat = dict(tiles=GOOGLE_SAT, attr="Google Satellite", name="Google Satélite", show=False)
        ghyb = dict(tiles=GOOGLE_HYB, attr="Google Hybrid", name="Google Híbrido", show=False)
        sat = dict(tiles=ESRI, attr="Esri World Imagery", name="Esri Satélite", show=True)
        for cfg in (oscuro, gsat, ghyb, sat):
            folium.TileLayer(**cfg).add_to(sub_m)
        if s2_rgb is not None and s2_rgb.ndim == 3:
            etq_s2 = f"🛰️ Sentinel-2 ({s2_fecha})" if s2_fecha else "🛰️ Sentinel-2 (fecha evento)"
            folium.raster_layers.ImageOverlay(
                image=s2_rgb, bounds=res["bounds"], name=etq_s2,
                opacity=1.0, origin="upper", interactive=False, show=True,
            ).add_to(sub_m)
        folium.raster_layers.ImageOverlay(
            image=info_c["rgba"], bounds=res["bounds"], name=nom_capa,
            opacity=1.0, origin="upper", interactive=False,
        ).add_to(sub_m)
        agregar_aoi(
            sub_m, aoi_geom,
            cuenca_geom=cuenca_geom,
            cuenca_meta=cuenca_meta,
            campo_metrica=campo_metrica_sub,
            etiqueta_metrica=etiqueta_metrica_sub,
        )
        if red_drenaje is not None:
            agregar_red_drenaje(sub_m, red_drenaje, criterio_grosor=criterio_grosor_red)
        folium.LayerControl(collapsed=True).add_to(sub_m)

    etq_i = f"Mapa 1 · {subtitulo_izq}" if subtitulo_izq else "Mapa 1"
    etq_d = f"Mapa 2 · {subtitulo_der}" if subtitulo_der else "Mapa 2"
    dm.get_root().html.add_child(folium.Element(_html_leyenda_compacta(capa_izq, info_izq, umbral, lado="left", etiqueta_panel=etq_i)))
    dm.get_root().html.add_child(folium.Element(_html_leyenda_compacta(capa_der, info_der, umbral, lado="right", etiqueta_panel=etq_d)))
    return dm
