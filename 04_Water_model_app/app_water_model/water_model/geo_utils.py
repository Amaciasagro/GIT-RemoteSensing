"""Utilidades geoespaciales: lectura del AOI, validación (EE. UU.) y definición de la malla de trabajo."""
import io
import os
import json
import hashlib
import tempfile

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import shape, mapping, LineString
from shapely.ops import unary_union, linemerge

# Caja aproximada de EE. UU. (incluye Alaska y Hawái): lon_min, lat_min, lon_max, lat_max
BBOX_EEUU = (-180.0, 15.0, -64.0, 72.0)
MAX_HA = 5000.0
MAX_HA_CUENCA = 120000.0  # HUC12 (~4,000-16,000 ha) y HUC10 (~16,000-100,000 ha)


def gdf_desde_geojson(obj):
    """Convierte un GeoJSON (Feature, FeatureCollection o geometría) en GeoDataFrame WGS84."""
    if isinstance(obj, str):
        obj = json.loads(obj)
    tipo = obj.get("type")
    if tipo == "FeatureCollection":
        feats = obj.get("features", [])
        if not feats:
            return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
        return gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    if tipo == "Feature":
        return gpd.GeoDataFrame.from_features([obj], crs="EPSG:4326")
    return gpd.GeoDataFrame(geometry=[shape(obj)], crs="EPSG:4326")


def gdf_desde_archivo(archivo):
    """Lee un .zip (Shapefile), .gpkg (GeoPackage), .shp o .geojson/.json subido con st.file_uploader."""
    nombre = archivo.name.lower()
    datos = archivo.getvalue()
    if nombre.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "aoi.zip")
            with open(ruta, "wb") as f:
                f.write(datos)
            return gpd.read_file(f"zip://{ruta}")
    if nombre.endswith((".gpkg", ".shp")):
        ext = os.path.splitext(nombre)[1]
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, f"layer{ext}")
            with open(ruta, "wb") as f:
                f.write(datos)
            return gpd.read_file(ruta)
    if nombre.endswith((".geojson", ".json")):
        return gpd.read_file(io.BytesIO(datos))
    raise ValueError("Formato no soportado: use .zip (Shapefile), .gpkg (GeoPackage) o .geojson")


def normalizar_aoi(gdf):
    """Valida el AOI, lo une en una sola geometría WGS84 y calcula área/centroide."""
    if gdf is None or gdf.empty:
        raise ValueError("El archivo no contiene geometrías.")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    geom = unary_union([shapely.make_valid(g) for g in gdf.geometry])
    # Conservar solo polígonos
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("El AOI debe ser un polígono.")
    lon, lat = geom.centroid.x, geom.centroid.y
    x0, y0, x1, y1 = BBOX_EEUU
    if not (x0 <= lon <= x1 and y0 <= lat <= y1):
        raise ValueError("El AOI está fuera de EE. UU.: los datos USDA-NRCS solo cubren ese territorio.")
    area_ha = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:5070").area.iloc[0] / 1e4
    if area_ha > MAX_HA:
        raise ValueError(f"AOI demasiado grande ({area_ha:,.0f} ha). Máximo permitido: {MAX_HA:,.0f} ha.")
    geojson = mapping(geom)
    return {
        "geom": json.loads(json.dumps(geojson)),  # tuplas -> listas (serializable)
        "area_ha": float(area_ha),
        "lon": float(lon), "lat": float(lat),
        "bounds": tuple(float(b) for b in geom.bounds),
        "id": hashlib.md5(json.dumps(geojson, sort_keys=True).encode()).hexdigest()[:10],
    }


def normalizar_cuenca(gdf, aoi=None, fuente="USGS/WBD/2017/HUC12", nivel="HUC12"):
    """
    Valida y normaliza un GeoDataFrame de cuencas/subcuencas (desde USGS WBD en GEE o archivo local .shp/.gpkg/.geojson).
    Extrae y conserva metadatos: código HUC (huc12/huc10), nombre, área (ha), estados y geometrías individuales.
    Si no hay intersección con el AOI, lanza LookupError para que se registre en st.session_state['avisos'].
    """
    if gdf is None or gdf.empty:
        raise LookupError(f"No se encontraron subcuencas en {fuente} que intersecten el AOI.")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326").copy()
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        raise LookupError(f"La consulta a {fuente} no devolvió geometrías válidas.")

    gdf["geometry"] = [shapely.make_valid(g) for g in gdf.geometry]
    if aoi is not None:
        aoi_geom = shape(aoi["geom"])
        mask_inter = gdf.geometry.intersects(aoi_geom)
        gdf = gdf[mask_inter].copy()
        if gdf.empty:
            raise LookupError(
                f"Ninguna subcuenca de {fuente} intersecta el polígono del AOI ({aoi['lat']:.4f}, {aoi['lon']:.4f})."
            )

    geom = unary_union(list(gdf.geometry))
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("La cuenca debe contener polígonos válidos.")

    area_ha = float(gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:5070").area.iloc[0] / 1e4)
    if area_ha > MAX_HA_CUENCA:
        raise ValueError(f"Cuenca demasiado extensa ({area_ha:,.0f} ha). Máximo soportado: {MAX_HA_CUENCA:,.0f} ha.")

    # Extraer metadatos por polígono (código HUC, nombre, área en ha, estado, hacia qué HUC drena)
    cols_lower = {c.lower(): c for c in gdf.columns}
    c_huc = next((cols_lower[k] for k in ("huc12", "huc10", "huc_12", "huc_10", "huc8", "huc_code", "huc", "id", "fid") if k in cols_lower), None)
    c_nom = next((cols_lower[k] for k in ("name", "nombre", "gnis_name", "subbasin", "watershed", "hu_12_name", "hu_10_name") if k in cols_lower), None)
    c_st = next((cols_lower[k] for k in ("states", "state", "estado") if k in cols_lower), None)
    c_to = next((cols_lower[k] for k in ("tohuc", "to_huc", "downstream") if k in cols_lower), None)

    areas_ind_ha = gpd.GeoSeries(list(gdf.geometry), crs="EPSG:4326").to_crs("EPSG:5070").area.to_numpy() / 1e4
    subcuencas_meta = []
    codigos_huc = []
    nombres_huc = []
    estados_set = []
    feats_geojson = []

    for idx, ((_, row), a_ha) in enumerate(zip(gdf.iterrows(), areas_ind_ha), start=1):
        huc_val = str(row[c_huc]).strip() if (c_huc and pd.notna(row[c_huc]) and str(row[c_huc]).strip()) else f"{nivel}-{idx:02d}"
        nom_val = str(row[c_nom]).strip() if (c_nom and pd.notna(row[c_nom]) and str(row[c_nom]).strip()) else f"Subcuenca {huc_val}"
        st_val = str(row[c_st]).strip() if (c_st and pd.notna(row[c_st])) else "—"
        to_val = str(row[c_to]).strip() if (c_to and pd.notna(row[c_to])) else "—"

        if huc_val not in codigos_huc:
            codigos_huc.append(huc_val)
        if nom_val not in nombres_huc:
            nombres_huc.append(nom_val)
        if st_val != "—" and st_val not in estados_set:
            estados_set.append(st_val)

        meta_item = dict(
            huc=huc_val,
            nombre=nom_val,
            area_ha=round(float(a_ha), 1),
            states=st_val,
            tohuc=to_val,
            fuente=fuente,
        )
        subcuencas_meta.append(meta_item)
        feats_geojson.append(dict(
            type="Feature",
            properties=meta_item,
            geometry=json.loads(json.dumps(mapping(row.geometry))),
        ))

    ext_ha = area_ha
    if aoi is not None:
        aoi_geom = shape(aoi["geom"])
        diff = geom.difference(aoi_geom)
        ext_ha = float(gpd.GeoSeries([diff], crs="EPSG:4326").to_crs("EPSG:5070").area.iloc[0] / 1e4) if not diff.is_empty else 0.0

    lon_c, lat_c = float(geom.centroid.x), float(geom.centroid.y)
    geojson = mapping(geom)
    return {
        "geom": json.loads(json.dumps(geojson)),
        "features_geojson": {"type": "FeatureCollection", "features": feats_geojson},
        "huc_codigo": ", ".join(codigos_huc),
        "nombre": " · ".join(nombres_huc),
        "states": ", ".join(estados_set) if estados_set else "US",
        "fuente": fuente,
        "nivel": nivel,
        "subcuencas": subcuencas_meta,
        "area_ha": round(area_ha, 1),
        "area_externa_ha": round(ext_ha, 1),
        "n_subcuencas": int(len(subcuencas_meta)),
        "lon": lon_c,
        "lat": lat_c,
        "bounds": tuple(float(b) for b in geom.bounds),
        "id": hashlib.md5(json.dumps(geojson, sort_keys=True).encode()).hexdigest()[:10],
    }


def definir_malla(aoi, res_m=None, max_lado=160, margen=0.10, cuenca=None):
    """Define una malla regular en UTM (metros) que cubre el AOI (y la cuenca aportante si existe) más margen."""
    geom = shape(aoi["geom"])
    if cuenca is not None and cuenca.get("geom"):
        geom = unary_union([geom, shape(cuenca["geom"])])
    epsg = 32600 + int((aoi["lon"] + 180) // 6) + 1
    crs = f"EPSG:{epsg}"
    gu = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(crs)
    minx, miny, maxx, maxy = gu.total_bounds
    w, h = maxx - minx, maxy - miny
    pad = (0.04 if cuenca else margen) * max(w, h) + 30.0
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    if not res_m:
        res_m = max(10.0, float(np.ceil(max(maxx - minx, maxy - miny) / max_lado / 2.0) * 2.0))
    res = float(res_m)
    x0 = float(np.floor(minx / res) * res)
    y1 = float(np.ceil(maxy / res) * res)
    nx = int(np.ceil((maxx - x0) / res))
    ny = int(np.ceil((y1 - miny) / res))
    # Salvaguarda de tamaño máximo de grilla para evitar límites de sampleRectangle en GEE (<= 220x220)
    if max(nx, ny) > 220:
        res = float(np.ceil(max(maxx - minx, maxy - miny) / 200.0 / 2.0) * 2.0)
        x0 = float(np.floor(minx / res) * res)
        y1 = float(np.ceil(maxy / res) * res)
        nx = int(np.ceil((maxx - x0) / res))
        ny = int(np.ceil((y1 - miny) / res))
    return {"crs": crs, "res": res, "x0": x0, "y1": y1, "nx": nx, "ny": ny}


def coordenadas_celdas(malla, shape_):
    """Coordenadas UTM del centro de cada celda para un arreglo (ny, nx)."""
    ny, nx = shape_
    xs = malla["x0"] + (np.arange(nx) + 0.5) * malla["res"]
    ys = malla["y1"] - (np.arange(ny) + 0.5) * malla["res"]
    return np.meshgrid(xs, ys)


def mascara_aoi(aoi, malla, shape_):
    """Máscara booleana (True = celda dentro del AOI)."""
    gu = gpd.GeoSeries([shape(aoi["geom"])], crs="EPSG:4326").to_crs(malla["crs"]).iloc[0]
    X, Y = coordenadas_celdas(malla, shape_)
    m = shapely.contains_xy(gu, X, Y)
    if not m.any():  # AOI menor que una celda: forzar la celda del centroide
        c = gu.centroid
        j = int((c.x - malla["x0"]) // malla["res"])
        i = int((malla["y1"] - c.y) // malla["res"])
        m[min(max(i, 0), shape_[0] - 1), min(max(j, 0), shape_[1] - 1)] = True
    return m


def mascara_dominio(aoi, cuenca, malla, shape_):
    """Máscara booleana del dominio hidrológico activo (unión de AOI y cuenca zonal aportante)."""
    if cuenca is None or not cuenca.get("geom"):
        return np.ones(shape_, dtype=bool)
    geom_u = unary_union([shape(aoi["geom"]), shape(cuenca["geom"])])
    gu = gpd.GeoSeries([geom_u], crs="EPSG:4326").to_crs(malla["crs"]).iloc[0]
    X, Y = coordenadas_celdas(malla, shape_)
    m = shapely.contains_xy(gu, X, Y)
    return m | mascara_aoi(aoi, malla, shape_)


def limites_wgs84(malla, shape_):
    """Límites [[sur, oeste], [norte, este]] de la malla en WGS84 (para ImageOverlay de Folium)."""
    ny, nx = shape_
    x1 = malla["x0"] + nx * malla["res"]
    y0 = malla["y1"] - ny * malla["res"]
    pts = gpd.GeoSeries(gpd.points_from_xy([malla["x0"], x1], [y0, malla["y1"]]), crs=malla["crs"]).to_crs("EPSG:4326")
    (w, s), (e, n) = [(p.x, p.y) for p in pts]
    return [[s, w], [n, e]]


def normalizar_red_drenaje(gdf, aoi=None, cuenca=None, fuente="WWF/HydroSHEDS/v1/FreeFlowingRivers"):
    """
    Valida y normaliza una red de drenaje vectorial (LineString/MultiLineString) desde HydroSHEDS
    (WWF/HydroSHEDS/v1/FreeFlowingRivers), NHD Flowline o archivo local (.shp/.gpkg/.geojson).
    Extrae atributos de jerarquía (RIV_ORD / streamorde), descarga media (DIS_AV_CMS, m3/s) y
    acumulación/área drenada aguas arriba (UPLAND_SKM / TotDASqKM, km2) para asignar orden (1..5)
    y grosor de línea variable (1.8..6.0 px).
    """
    if gdf is None or gdf.empty:
        raise LookupError(f"La capa de red de drenaje ({fuente}) no contiene tramos.")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326").copy()
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        raise LookupError(f"La red de drenaje ({fuente}) no tiene geometrías válidas.")

    # Filtrar o recortar al entorno del dominio (subcuenca o AOI con buffer)
    ref_geom = None
    if cuenca is not None and cuenca.get("geom"):
        ref_geom = shape(cuenca["geom"]).buffer(0.012)
    elif aoi is not None and aoi.get("geom"):
        ref_geom = shape(aoi["geom"]).buffer(0.018)

    if ref_geom is not None:
        gdf = gdf[gdf.geometry.intersects(ref_geom)].copy()
        if gdf.empty:
            raise LookupError(f"Ningún tramo de {fuente} intersecta el área de estudio.")
        gdf["geometry"] = [g.intersection(ref_geom) for g in gdf.geometry]
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    # Conservar solo líneas
    lineas_ok = [g.geom_type in ("LineString", "MultiLineString") for g in gdf.geometry]
    gdf = gdf[lineas_ok].copy()
    if gdf.empty:
        raise ValueError("El archivo de red de drenaje debe contener geometrías de tipo línea (LineString).")

    cols_l = {c.lower(): c for c in gdf.columns}
    c_ord = next((cols_l[k] for k in ("riv_ord", "bb_ord", "streamorde", "streamcalc", "order", "orden", "strahler", "jerarquia") if k in cols_l), None)
    c_dis = next((cols_l[k] for k in ("dis_av_cms", "q_mean", "discharge", "caudal", "q_cms") if k in cols_l), None)
    c_acc = next((cols_l[k] for k in ("upland_skm", "totdasqkm", "arbolatesu", "acumulacion", "flow_acc", "length_km", "lengthkm") if k in cols_l), None)
    c_nom = next((cols_l[k] for k in ("bb_name", "riv_name", "gnis_name", "name", "nombre", "fcode_desc", "ftype") if k in cols_l), None)

    long_m = gpd.GeoSeries(list(gdf.geometry), crs="EPSG:4326").to_crs("EPSG:5070").length.to_numpy()

    # Vectores de descarga (m3/s), área drenada/acumulación (km2) y orden jerárquico
    dis_arr = (
        np.maximum(pd.to_numeric(gdf[c_dis], errors="coerce").fillna(0.0).to_numpy(dtype=float), 0.0)
        if c_dis else np.zeros(len(gdf), dtype=float)
    )
    acc_arr = (
        np.maximum(pd.to_numeric(gdf[c_acc], errors="coerce").fillna(0.0).to_numpy(dtype=float), 0.0)
        if c_acc else np.round(long_m / 1000.0, 2)
    )
    if c_ord and pd.to_numeric(gdf[c_ord], errors="coerce").notna().any():
        ord_raw = pd.to_numeric(gdf[c_ord], errors="coerce").fillna(5.0).to_numpy(dtype=float)
        # En HydroSHEDS RIV_ORD=1 es el cauce de mayor caudal y 10 el menor: convertir a escala creciente 1..10
        if "riv_ord" in c_ord.lower() or "bb_ord" in c_ord.lower():
            val_jer = np.clip(11.0 - ord_raw, 1.0, 10.0)
        else:
            val_jer = ord_raw
    elif dis_arr.max() > 0:
        val_jer = np.log10(dis_arr + 1.0)
    elif acc_arr.max() > 0:
        val_jer = np.log10(acc_arr + 1.0)
    else:
        val_jer = np.log10(np.maximum(long_m, 10.0))

    # Combinar jerarquía, descarga y acumulación para calcular grosor de cauce (1.8 a 6.0 px)
    def _norm_vec(v):
        lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
        return (v - lo) / (hi - lo + 1e-9) if hi > lo else np.full_like(v, 0.5, dtype=float)

    n_jer = _norm_vec(val_jer)
    n_dis = _norm_vec(np.log10(dis_arr + 1.0)) if dis_arr.max() > 0 else n_jer
    n_acc = _norm_vec(np.log10(acc_arr + 1.0)) if acc_arr.max() > 0 else n_jer
    norm_comb = 0.45 * n_jer + 0.30 * n_dis + 0.25 * n_acc

    ordenes = np.clip(np.round(1.0 + norm_comb * 4.0), 1, 5).astype(int)
    grosores_jer = np.round(1.8 + n_jer * 4.2, 2)
    grosores_dis = np.round(1.8 + n_dis * 4.2, 2)
    grosores_acc = np.round(1.8 + n_acc * 4.2, 2)
    grosores = np.round(1.8 + norm_comb * 4.2, 2)

    paleta_rios = {1: "#90e0ef", 2: "#48cae4", 3: "#00b4d8", 4: "#0096c7", 5: "#00f5d4"}
    feats = []
    tramos_meta = []
    for idx, ((_, row), ord_v, g_comb, g_j, g_d, g_a, d_v, a_v, l_m) in enumerate(
        zip(gdf.iterrows(), ordenes, grosores, grosores_jer, grosores_dis, grosores_acc, dis_arr, acc_arr, long_m), start=1
    ):
        nom_v = str(row[c_nom]).strip() if (c_nom and pd.notna(row[c_nom]) and str(row[c_nom]).strip()) else f"Cauce HydroSHEDS #{idx}"
        prop = dict(
            id=idx,
            nombre=nom_v,
            orden=int(ord_v),
            descarga_cms=round(float(d_v), 3),
            acumulacion=round(float(a_v), 2),
            longitud_km=round(float(l_m) / 1000.0, 2),
            grosor_px=float(g_comb),
            grosor_jerarquia_px=float(g_j),
            grosor_descarga_px=float(g_d),
            grosor_acumulacion_px=float(g_a),
            color=paleta_rios.get(int(ord_v), "#00b4d8"),
            fuente=fuente,
        )
        tramos_meta.append(prop)
        feats.append(dict(
            type="Feature",
            properties=prop,
            geometry=json.loads(json.dumps(mapping(row.geometry))),
        ))

    return {
        "features_geojson": {"type": "FeatureCollection", "features": feats},
        "tramos": tramos_meta,
        "n_tramos": len(feats),
        "longitud_total_km": round(float(long_m.sum()) / 1000.0, 2),
        "fuente": fuente,
    }


def extraer_red_drenaje_dem(dem, malla, mascara_dom=None):
    """
    Extrae una red de drenaje jerárquica D8 directamente desde el DEM 3DEP cuando NHD/HydroSHEDS
    no tienen cobertura vectorial a escala intra-lote. Calcula acumulación de flujo, asigna orden
    (1..5) y grosor variable (1.8..5.5 px), y devuelve la estructura normalizada en EPSG:4326.
    """
    ny, nx = dem.shape
    dom = mascara_dom if mascara_dom is not None else np.ones((ny, nx), dtype=bool)
    res = float(malla["res"])
    X, Y = coordenadas_celdas(malla, (ny, nx))

    # Dirección de flujo D8 hacia el vecino de mayor pendiente descendente
    desp = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    dist = [np.hypot(res, res) if (di and dj) else res for di, dj in desp]
    zp = np.pad(dem, 1, mode="edge")
    caidas = np.stack([(dem - zp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx]) / d for (di, dj), d in zip(desp, dist)])
    mejor_dir = np.argmax(caidas, axis=0)
    max_pend = np.max(caidas, axis=0)

    # Ordenar celdas de mayor a menor cota para acumular área drenada (D8 flow accumulation)
    acum = np.ones((ny, nx), dtype=float)
    orden_idx = np.argsort(dem.ravel())[::-1]
    for flat_i in orden_idx:
        r, c = divmod(int(flat_i), nx)
        if max_pend[r, c] <= 0:
            continue
        di, dj = desp[int(mejor_dir[r, c])]
        nr, nc = r + di, c + dj
        if 0 <= nr < ny and 0 <= nc < nx:
            acum[nr, nc] += acum[r, c]

    # Umbral adaptativo (percentil 90 de acumulación dentro del dominio)
    vals_dom = acum[dom]
    umbral = max(float(np.percentile(vals_dom, 91)) if vals_dom.size else 12.0, 8.0)
    es_cauce = (acum >= umbral) & dom

    # Construir segmentos entre centros de celdas conectadas con acumulación >= umbral
    registros = []
    for r in range(ny):
        for c in range(nx):
            if not es_cauce[r, c] or max_pend[r, c] <= 0:
                continue
            di, dj = desp[int(mejor_dir[r, c])]
            nr, nc = r + di, c + dj
            if 0 <= nr < ny and 0 <= nc < nx and dom[nr, nc]:
                linea_utm = LineString([(X[r, c], Y[r, c]), (X[nr, nc], Y[nr, nc])])
                registros.append({"acumulacion": float(acum[r, c]) * (res ** 2) / 1e4, "geometry": linea_utm})

    if not registros:
        raise LookupError("No se pudieron extraer líneas de drenaje desde el DEM.")

    gdf_utm = gpd.GeoDataFrame(registros, crs=malla["crs"])
    # Clasificar en 5 niveles de acumulación y fusionar segmentos contiguos por nivel
    q_bins = np.quantile(gdf_utm["acumulacion"], [0.0, 0.45, 0.72, 0.88, 0.96, 1.0])
    q_bins = np.unique(q_bins)
    gdf_utm["orden"] = np.clip(np.digitize(gdf_utm["acumulacion"], q_bins[1:-1]) + 1, 1, 5)

    filas_fusion = []
    for ord_v, grp in gdf_utm.groupby("orden"):
        merged = linemerge(list(grp.geometry))
        geoms = [merged] if merged.geom_type == "LineString" else list(getattr(merged, "geoms", [merged]))
        acc_med = float(grp["acumulacion"].mean())
        for idx_g, g in enumerate(geoms, start=1):
            if g.length >= res * 0.9:
                filas_fusion.append({
                    "gnis_name": f"Línea de drenaje D8 (Orden {ord_v})",
                    "orden": int(ord_v),
                    "acumulacion": round(acc_med, 2),
                    "geometry": g,
                })

    gdf_wgs = gpd.GeoDataFrame(filas_fusion, crs=malla["crs"]).to_crs("EPSG:4326")
    return normalizar_red_drenaje(gdf_wgs, fuente="Derivada del DEM 3DEP (Acumulación de flujo D8)")


def calcular_metricas_subcuencas(cuenca, malla, r_evento, p_mm, umbral):
    """
    Calcula para cada subcuenca de `cuenca['features_geojson']` métricas hidrológicas derivadas de
    ejecutar_pipeline(...): promedio y máximo de lámina de encharcamiento (mm), escorrentía (mm),
    infiltración/retención en el balance hídrico (mm), humedad (% AWC) y área encharcada (ha).
    Actualiza `cuenca['features_geojson']` y `cuenca['subcuencas']` in-place y los devuelve.
    """
    if cuenca is None or not cuenca.get("features_geojson"):
        return cuenca

    lam = r_evento["lamina"]
    esc = r_evento["escorrentia"]
    inf = r_evento["infiltracion"]
    hum = r_evento["humedad1"] * 100.0
    ny, nx = lam.shape
    X, Y = coordenadas_celdas(malla, (ny, nx))
    ha_celda = (float(malla["res"]) ** 2) / 1e4

    feats = cuenca["features_geojson"].get("features", [])
    sub_lista = []

    for feat in feats:
        geom_wgs = shape(feat["geometry"])
        gu = gpd.GeoSeries([geom_wgs], crs="EPSG:4326").to_crs(malla["crs"]).iloc[0]
        m_sub = shapely.contains_xy(gu, X, Y)
        if not m_sub.any():
            c = gu.centroid
            j = int(np.clip((c.x - malla["x0"]) // malla["res"], 0, nx - 1))
            i = int(np.clip((malla["y1"] - c.y) // malla["res"], 0, ny - 1))
            m_sub[i, j] = True

        lam_s = lam[m_sub]
        esc_s = esc[m_sub]
        inf_s = inf[m_sub]
        hum_s = hum[m_sub]
        bal_s = inf_s - esc_s  # Balance neto retenido vs escurrido (mm)

        pr = feat.setdefault("properties", {})
        pr.update(
            lamina_mean_mm=round(float(np.nanmean(lam_s)), 2),
            lamina_max_mm=round(float(np.nanmax(lam_s)), 2),
            escorrentia_mean_mm=round(float(np.nanmean(esc_s)), 2),
            escorrentia_max_mm=round(float(np.nanmax(esc_s)), 2),
            infiltracion_mean_mm=round(float(np.nanmean(inf_s)), 2),
            infiltracion_max_mm=round(float(np.nanmax(inf_s)), 2),
            balance_mean_mm=round(float(np.nanmean(bal_s)), 2),
            balance_max_mm=round(float(np.nanmax(bal_s)), 2),
            humedad_mean_pct=round(float(np.nanmean(hum_s)), 1),
            humedad_max_pct=round(float(np.nanmax(hum_s)), 1),
            area_enc_ha=round(float((lam_s >= umbral).sum() * ha_celda), 2),
            pct_enc=round(float((lam_s >= umbral).mean() * 100.0), 1),
        )
        sub_lista.append(dict(pr))

    cuenca["subcuencas"] = sub_lista
    return cuenca
