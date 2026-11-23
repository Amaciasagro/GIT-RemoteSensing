"""USDA-NRCS soil client: polygons (WFS), tabular data (Soil Data Access), and Google Earth Engine fallback."""
import io
import time
import numpy as np
import pandas as pd
import requests
import geopandas as gpd
from shapely.geometry import box, shape
from shapely import wkt as sh_wkt
from shapely.ops import transform as sh_transform, unary_union

from .config import TEXTURA_DEFECTO
from .geo_utils import coordenadas_celdas

SDA_URLS = [
    "https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest",
    "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
]
WFS_CONFIGS = [
    ("https://sdmdataaccess.nrcs.usda.gov/Spatial/SDMNAD83Geographic.wfs", "MapunitPoly", "GML3"),
    ("https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDMWGS84Geographic.wfs", "mapunitpoly", "GML3"),
    ("https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDMWGS84Geographic.wfs", "mapunitpoly", None),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WaterModel/1.0"}

COLS_NUM = ["comppct_r", "hzdept_r", "hzdepb_r", "sandtotal_r", "silttotal_r", "claytotal_r",
            "dbthirdbar_r", "ksat_r", "wthirdbar_r", "wfifteenbar_r", "awc_r"]


def clase_textural(sand, silt, clay):
    """USDA soil textural class from % sand, silt, and clay."""
    if clay is None or np.isnan(clay) or np.isnan(sand) or np.isnan(silt):
        return None
    if silt + 1.5 * clay < 15: return "Sand"
    if silt + 1.5 * clay >= 15 and silt + 2 * clay < 30: return "Loamy sand"
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "Sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52: return "Loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12): return "Silt loam"
    if silt >= 80 and clay < 12: return "Silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45: return "Sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45: return "Clay loam"
    if 27 <= clay < 40 and sand <= 20: return "Silty clay loam"
    if clay >= 35 and sand > 45: return "Sandy clay"
    if clay >= 40 and silt >= 40: return "Silty clay"
    if clay >= 40 and sand <= 45 and silt < 40: return "Clay"
    return "Loam"


def _sda_query(sql):
    """Executes a SQL query on Soil Data Access with retries and USDA mirrors."""
    ult_err = None
    payload = {"query": sql, "format": "JSON+COLUMNNAME"}
    for intento in range(2):
        for url in SDA_URLS:
            for use_form in (True, False):
                try:
                    kwargs = {"data": payload} if use_form else {"json": payload}
                    r = requests.post(url, headers=HEADERS, timeout=45, **kwargs)
                    if r.status_code >= 500:
                        ult_err = RuntimeError(f"HTTP {r.status_code} at {url}")
                        continue
                    r.raise_for_status()
                    if not r.text.strip():
                        return pd.DataFrame()
                    tabla = r.json().get("Table", [])
                    if len(tabla) < 2:
                        return pd.DataFrame(columns=tabla[0] if tabla else [])
                    return pd.DataFrame(tabla[1:], columns=tabla[0])
                except Exception as e:  # noqa: BLE001
                    ult_err = e
        if intento == 0:
            time.sleep(0.8)
    raise RuntimeError(f"USDA Soil Data Access unavailable ({ult_err})")


def descargar_poligonos(bounds, buffer_deg=0.002):
    """Map unit polygons (mapunitpoly) via WFS or SQL geometry fallback."""
    x0, y0, x1, y1 = bounds
    bbox_str = f"{x0-buffer_deg:.6f},{y0-buffer_deg:.6f},{x1+buffer_deg:.6f},{y1+buffer_deg:.6f}"
    ult_err = None

    for wfs_url, typename, out_fmt in WFS_CONFIGS:
        try:
            params = dict(
                SERVICE="WFS", VERSION="1.0.0", REQUEST="GetFeature",
                TYPENAME=typename, SRSNAME="EPSG:4326", BBOX=bbox_str,
            )
            if out_fmt:
                params["OUTPUTFORMAT"] = out_fmt
            r = requests.get(wfs_url, params=params, headers=HEADERS, timeout=45)
            if r.status_code >= 500:
                ult_err = RuntimeError(f"HTTP {r.status_code} on WFS")
                continue
            r.raise_for_status()
            if b"ExceptionReport" in r.content[:600] or b"ServiceException" in r.content[:600]:
                ult_err = RuntimeError("The WFS service returned an exception.")
                continue
            gdf = gpd.read_file(io.BytesIO(r.content))
            gdf.columns = [c.lower() for c in gdf.columns]
            if "mukey" not in gdf.columns or gdf.empty:
                ult_err = RuntimeError("WFS returned no polygons with 'mukey'.")
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            xmin, ymin, _, _ = gdf.total_bounds
            if xmin > 0 and ymin < 0:  # swapped axis order (lat, lon)
                gdf["geometry"] = gdf.geometry.apply(lambda g: sh_transform(lambda x, y, z=None: (y, x), g))
            gdf["mukey"] = gdf["mukey"].astype(str)
            return gdf[["mukey", "geometry"]]
        except Exception as e:  # noqa: BLE001
            ult_err = e

    # Fallback: fetch WKT geometries directly from SDA Tabular if WFS failed
    try:
        bbox_wkt = box(x0 - buffer_deg, y0 - buffer_deg, x1 + buffer_deg, y1 + buffer_deg).wkt
        sql = f"""
        SELECT mukey, mupolygongeo.STAsText() AS wkt
        FROM mupolygon
        WHERE mupolygonkey IN (
            SELECT DISTINCT mupolygonkey
            FROM SDA_Get_Mupolygonkey_from_intersection_with_WktWgs84('{bbox_wkt}')
        )"""
        df_wkt = _sda_query(sql)
        if not df_wkt.empty and "wkt" in df_wkt.columns:
            geoms = [sh_wkt.loads(w) for w in df_wkt["wkt"]]
            gdf = gpd.GeoDataFrame({"mukey": df_wkt["mukey"].astype(str)}, geometry=geoms, crs="EPSG:4326")
            return gdf[["mukey", "geometry"]]
    except Exception:  # noqa: BLE001
        pass

    raise RuntimeError(f"USDA WFS unavailable ({ult_err})")


def mukeys_por_interseccion(wkt):
    """Polygon-free fallback: list of mukeys intersecting the AOI."""
    df = _sda_query(f"SELECT DISTINCT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')")
    return df["mukey"].astype(str).tolist() if not df.empty else []


def consultar_horizontes(mukeys):
    """Components and horizons of the map units (major components)."""
    mukeys = [m for m in dict.fromkeys(map(str, mukeys)) if m.isdigit()]
    partes = []
    for i in range(0, len(mukeys), 150):
        lista = ",".join(f"'{m}'" for m in mukeys[i:i + 150])
        sql = f"""
        SELECT mu.mukey, mu.muname, co.cokey, co.compname, co.comppct_r, co.hydgrp,
               ch.hzname, ch.hzdept_r, ch.hzdepb_r, ch.sandtotal_r, ch.silttotal_r, ch.claytotal_r,
               ch.dbthirdbar_r, ch.ksat_r, ch.wthirdbar_r, ch.wfifteenbar_r, ch.awc_r
        FROM mapunit mu
        INNER JOIN component co ON co.mukey = mu.mukey AND co.majcompflag = 'Yes'
        LEFT JOIN chorizon ch ON ch.cokey = co.cokey
        WHERE mu.mukey IN ({lista})
        ORDER BY mu.mukey, co.comppct_r DESC, ch.hzdept_r"""
        d = _sda_query(sql)
        if not d.empty:
            partes.append(d)
    if not partes:
        raise RuntimeError("Soil Data Access returned no components/horizons.")
    df = pd.concat(partes, ignore_index=True)
    for c in COLS_NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["mukey"] = df["mukey"].astype(str)
    return df


def _hsg(txt, textura):
    """Hydrological Soil Group: for dual classes (A/D), takes the undrained condition (the second letter)."""
    if isinstance(txt, str) and txt.strip():
        g = txt.strip().upper().split("/")[-1][:1]
        if g in "ABCD":
            return g
    return TEXTURA_DEFECTO.get(textura, TEXTURA_DEFECTO["Loam"])["hsg"]


def _coherencia_hidrofisica_horizonte(sand, silt, clay, fc_pct, wp_pct, awc_frac, db_gcm3, ksat_ums, tex_fallback="Loam"):
    """
    Ensures strict physical consistency in every horizon between:
      - Bulk density `db` (g/cm3) and total porosity `por` (m3/m3),
      - Field capacity `fc_vol` (m3/m3) and permanent wilting point `wp_vol` (m3/m3),
      - Available water capacity `awc_vol = fc_vol - wp_vol` (m3/m3),
      - Drainable porosity / macropores `gs_vol = por - fc_vol >= 0.035` (m3/m3),
      - Saturated hydraulic conductivity `ksat_mmh` (mm/h) and capillary suction `psi_m` (m).
    """
    tex = clase_textural(sand, silt, clay) or tex_fallback
    d = TEXTURA_DEFECTO.get(tex, TEXTURA_DEFECTO["Loam"])

    if pd.notna(db_gcm3) and 0.85 <= float(db_gcm3) <= 2.05:
        db = float(db_gcm3)
        por = float(np.clip(1.0 - db / 2.65, 0.30, 0.62))
    else:
        por = float(np.clip(d["por"], 0.30, 0.62))
        db = round((1.0 - por) * 2.65, 2)

    # Always reserve minimum drainable porosity (macropores >= 3.5% vol or >= 8% of total porosity)
    gs_min_vol = max(0.035, 0.08 * por)
    fc_max_vol = max(por - gs_min_vol, 0.12)

    fc_raw = (float(fc_pct) / 100.0) if (pd.notna(fc_pct) and float(fc_pct) > 0) else (float(d["fc"]) / 100.0)
    wp_raw = (float(wp_pct) / 100.0) if (pd.notna(wp_pct) and float(wp_pct) > 0) else (float(d["wp"]) / 100.0)

    fc_vol = float(np.clip(fc_raw, 0.07, fc_max_vol))
    wp_vol = float(np.clip(wp_raw, 0.02, max(fc_vol - 0.03, 0.03)))

    if pd.notna(awc_frac) and float(awc_frac) > 0:
        awc_vol = float(np.clip(float(awc_frac), 0.02, max(fc_max_vol - 0.02, 0.04)))
        if wp_vol + awc_vol <= fc_max_vol:
            fc_vol = max(fc_vol, wp_vol + awc_vol)
            wp_vol = fc_vol - awc_vol
        else:
            fc_vol = fc_max_vol
            wp_vol = max(fc_vol - awc_vol, 0.02)
            awc_vol = fc_vol - wp_vol
    else:
        awc_vol = max(fc_vol - wp_vol, 0.03)
        wp_vol = fc_vol - awc_vol

    gs_vol = max(por - fc_vol, gs_min_vol)

    # Saxton & Rawls (2006) pedotransfer function for fallback Ksat when ksat_r is missing or <= 0
    lam = float(np.clip((np.log(max(fc_vol * 100.0, 2.0)) - np.log(max(wp_vol * 100.0, 1.0))) / 3.8167, 0.08, 0.75))
    ksat_sr = float(np.clip(1930.0 * (gs_vol ** (3.0 - lam)), 0.3, 250.0))
    ksat_mmh = (float(ksat_ums) * 3.6) if (pd.notna(ksat_ums) and float(ksat_ums) > 0) else ksat_sr

    c_val = float(clay) if pd.notna(clay) else 20.0
    s_val = float(sand) if pd.notna(sand) else 40.0
    psi_m = float(np.clip(d.get("psi_m", 0.32) * (0.75 + 0.012 * c_val - 0.003 * s_val), 0.05, 0.95))

    return dict(
        tex=tex, db=db, por=por,
        fc_vol=fc_vol, wp_vol=wp_vol, awc_vol=awc_vol, gs_vol=gs_vol,
        ksat_mmh=ksat_mmh, psi_m=psi_m,
    )


def _profundidad_edafica_ssurgo(h):
    """
    Determines actual edaphic effective depth of the SSURGO profile (cm),
    stopping at lithic/paralithic/dense restrictive layers (R, Cr, Cd, Qm, or near-zero Ksat without texture).
    """
    h_ord = h.dropna(subset=["hzdept_r", "hzdepb_r"]).sort_values("hzdept_r")
    if h_ord.empty:
        return 100.0
    prof_max = 0.0
    for _, r in h_ord.iterrows():
        hz = str(r.get("hzname") or "").strip().upper()
        es_roca = any(hz.startswith(pref) for pref in ("R", "CR", "CD", "QM", "2R", "3R"))
        sin_suelo = pd.isna(r.get("sandtotal_r")) and pd.isna(r.get("claytotal_r")) and (
            pd.notna(r.get("ksat_r")) and float(r["ksat_r"]) < 0.05
        )
        if es_roca or sin_suelo:
            if prof_max > 0:
                break
        prof_max = max(prof_max, float(r["hzdepb_r"]))
    return float(np.clip(prof_max if prof_max > 0 else h_ord["hzdepb_r"].max(), 20.0, 200.0))


def _agregar_horizontes(h, prof_cm, modo_prof="restrictivo"):
    """
    Integrates horizons according to the effective depth criterion:
      - 'restrictivo': min(agronomic_depth, ssurgo_edaphic_depth)
      - 'agronomica':  prof_cm set by user/crop
      - 'edafica':     actual effective profile depth from SSURGO
    Computes FC, PWP, AWC (mm), surface Ksat (basic infiltration), harmonic effective Ksat,
    restrictive minimum Ksat (deep percolation / interflow), bulk density, porosity, and suction.
    """
    h = h.dropna(subset=["hzdept_r", "hzdepb_r"]).copy()
    if h.empty:
        return None

    prof_ssurgo = _profundidad_edafica_ssurgo(h)
    prof_agro = float(prof_cm)
    if modo_prof == "edafica":
        prof_obj = prof_ssurgo
    elif modo_prof == "agronomica":
        prof_obj = prof_agro
    else:  # 'restrictivo': smaller (more restrictive) between agronomic and actual edaphic depth
        prof_obj = min(prof_agro, prof_ssurgo)

    h["esp"] = (np.minimum(h["hzdepb_r"], prof_obj) - np.maximum(h["hzdept_r"], 0)).clip(lower=0)
    h_act = h[h["esp"] > 0].copy()
    if h_act.empty:
        h["esp"] = (np.minimum(h["hzdepb_r"], max(prof_agro, prof_ssurgo)) - np.maximum(h["hzdept_r"], 0)).clip(lower=0)
        h_act = h[h["esp"] > 0].copy()
        if h_act.empty:
            return None

    # Profile average texture (thickness-weighted) to fill gaps
    w = h_act["esp"]
    med = {k: float(np.average(h_act[c][h_act[c].notna()], weights=w[h_act[c].notna()])) if h_act[c].notna().any() else np.nan
           for k, c in (("sand", "sandtotal_r"), ("silt", "silttotal_r"), ("clay", "claytotal_r"))}
    tex_perfil = clase_textural(med["sand"], med["silt"], med["clay"]) or "Loam"

    fc_mm = wp_mm = awc_mm = sat_mm = gs_mm = 0.0
    inv_k = 0.0
    da_pond = por_pond = psi_pond = 0.0
    ksat_lista = []
    ksat_sup = None

    for _, r in h_act.iterrows():
        t = float(r["esp"])
        props = _coherencia_hidrofisica_horizonte(
            r.get("sandtotal_r"), r.get("silttotal_r"), r.get("claytotal_r"),
            r.get("wthirdbar_r"), r.get("wfifteenbar_r"), r.get("awc_r"),
            r.get("dbthirdbar_r"), r.get("ksat_r"), tex_fallback=tex_perfil,
        )
        ks = props["ksat_mmh"]
        if ksat_sup is None or float(r["hzdept_r"]) <= 15.0:
            ksat_sup = ks if ksat_sup is None else 0.6 * ksat_sup + 0.4 * ks
        ksat_lista.append(ks)

        fc_mm += props["fc_vol"] * 10.0 * t
        wp_mm += props["wp_vol"] * 10.0 * t
        awc_mm += props["awc_vol"] * 10.0 * t
        sat_mm += props["por"] * 10.0 * t
        gs_mm += props["gs_vol"] * 10.0 * t
        inv_k += t / max(ks, 0.05)
        da_pond += props["db"] * t
        por_pond += props["por"] * t
        psi_pond += props["psi_m"] * t

    prof_ef = float(h_act["esp"].sum())
    ksat_arm = prof_ef / max(inv_k, 1e-6)
    ksat_min = float(min(ksat_lista)) if ksat_lista else ksat_arm
    ksat_sup = float(ksat_sup) if ksat_sup is not None else ksat_arm

    return dict(
        depth_cm=prof_ef,
        prof_agro_cm=prof_agro,
        prof_ssurgo_cm=prof_ssurgo,
        sand=med["sand"],
        silt=med["silt"],
        clay=med["clay"],
        textura=tex_perfil,
        da_gcm3=da_pond / max(prof_ef, 1.0),
        porosidad=por_pond / max(prof_ef, 1.0),
        psi_m=psi_pond / max(prof_ef, 1.0),
        fc_mm=fc_mm,
        awc_mm=awc_mm,
        wp_mm=wp_mm,
        ksat_mmh=ksat_arm,
        ksat_sup_mmh=ksat_sup,
        ksat_min_mmh=ksat_min,
        gs_mm=gs_mm,
    )


def resumir_suelo(df, prof_cm=100, modo_prof="restrictivo"):
    """Summary table per mukey (dominant component). Returns (mukey_table, dominant_horizons)."""
    filas, hors = [], []
    for mukey, g in df.groupby("mukey"):
        cok = g.sort_values("comppct_r", ascending=False)["cokey"].iloc[0]
        h = g[g["cokey"] == cok].sort_values("hzdept_r").copy()
        agg = _agregar_horizontes(h, prof_cm, modo_prof=modo_prof)
        if agg is None:
            continue
        # Enrich each horizon using the same hydrophysical consistency function
        ks_col, por_col, fc_col, wp_col = [], [], [], []
        for _, r_hz in h.iterrows():
            pr_hz = _coherencia_hidrofisica_horizonte(
                r_hz.get("sandtotal_r"), r_hz.get("silttotal_r"), r_hz.get("claytotal_r"),
                r_hz.get("wthirdbar_r"), r_hz.get("wfifteenbar_r"), r_hz.get("awc_r"),
                r_hz.get("dbthirdbar_r"), r_hz.get("ksat_r"), tex_fallback=agg["textura"],
            )
            ks_col.append(round(pr_hz["ksat_mmh"], 2))
            por_col.append(round(pr_hz["por"] * 100.0, 1))
            fc_col.append(round(pr_hz["fc_vol"] * 100.0, 1))
            wp_col.append(round(pr_hz["wp_vol"] * 100.0, 1))
        h["ksat_mmh"] = ks_col
        h["porosidad_pct"] = por_col
        h["wthirdbar_r"] = fc_col
        h["wfifteenbar_r"] = wp_col
        agg.update(mukey=mukey, muname=h["muname"].iloc[0], compname=h["compname"].iloc[0],
                   hsg=_hsg(h["hydgrp"].iloc[0], agg["textura"]))
        filas.append(agg)
        hors.append(h)
    if not filas:
        raise RuntimeError("No mukey has valid horizons.")
    return pd.DataFrame(filas), pd.concat(hors, ignore_index=True)


def suelo_desde_gee(aoi, prof_cm=100, modo_prof="restrictivo"):
    """
    Spatial and horizon fallback via Google Earth Engine (OpenLandMap USDA 250 m)
    when USDA-NRCS servers (WFS/SDA) return 502/503 errors.
    Returns (gdf, table, horizons, source).
    """
    import ee

    geom_shp = shape(aoi["geom"])
    minx, miny, maxx, maxy = aoi["bounds"]

    sand_img = ee.Image("OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02")
    clay_img = ee.Image("OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02")
    bd_img = ee.Image("OpenLandMap/SOL/SOL_BULKDENS-FINEEARTH_USDA-4A1H_M/v02")
    fc_img = ee.Image("OpenLandMap/SOL/SOL_WATERCONTENT-33KPA_USDA-4B1C_M/v01")

    bands_depths = [
        ("b0", "Ap", 0, 10),
        ("b10", "A", 10, 30),
        ("b30", "Bt1", 30, 60),
        ("b60", "Bt2", 60, 100),
        ("b100", "BC", 100, 200),
    ]

    pila = ee.Image.cat([
        sand_img.select([b for b, _, _, _ in bands_depths], [f"sand_{b}" for b, _, _, _ in bands_depths]),
        clay_img.select([b for b, _, _, _ in bands_depths], [f"clay_{b}" for b, _, _, _ in bands_depths]),
        bd_img.select([b for b, _, _, _ in bands_depths], [f"bd_{b}" for b, _, _, _ in bands_depths]),
        fc_img.select([b for b, _, _, _ in bands_depths], [f"fc_{b}" for b, _, _, _ in bands_depths]),
    ])

    # Subdivide the AOI into a 2x2 grid to capture spatial variability if present
    xs = np.linspace(minx, maxx, 3)
    ys = np.linspace(miny, maxy, 3)
    celdas = []
    feats_ee = []
    idx = 0
    for i in range(2):
        for j in range(2):
            sub = geom_shp.intersection(box(xs[j], ys[i], xs[j + 1], ys[i + 1]))
            if not sub.is_empty and sub.geom_type in ("Polygon", "MultiPolygon"):
                celdas.append((str(idx), sub))
                feats_ee.append(ee.Feature(ee.Geometry(sub.__geo_interface__), {"zid": str(idx)}))
                idx += 1

    if not celdas:
        celdas = [("0", geom_shp)]
        feats_ee = [ee.Feature(ee.Geometry(aoi["geom"]), {"zid": "0"})]

    fc_zones = ee.FeatureCollection(feats_ee)
    red = pila.reduceRegions(collection=fc_zones, reducer=ee.Reducer.mean(), scale=250).getInfo()["features"]
    props_by_zid = {f["properties"]["zid"]: f["properties"] for f in red}

    # Group subzones by surface textural class to form map units (mukey)
    zonas_por_tex = {}
    for zid, sub_geom in celdas:
        p = props_by_zid.get(zid, {})
        s0 = float(p.get("sand_b0") or 40.0)
        c0 = float(p.get("clay_b0") or 20.0)
        si0 = max(0.0, 100.0 - s0 - c0)
        tex0 = clase_textural(s0, si0, c0) or "Loam"
        zonas_por_tex.setdefault(tex0, []).append((p, sub_geom))

    rows_df = []
    poly_records = []
    for k_idx, (tex_dom, items) in enumerate(zonas_por_tex.items(), start=1):
        mukey = f"GEE_{k_idx}"
        merged_geom = unary_union([g for _, g in items])
        poly_records.append({"mukey": mukey, "geometry": merged_geom})
        d_def = TEXTURA_DEFECTO.get(tex_dom, TEXTURA_DEFECTO["Loam"])

        for b_code, hz_name, z_top, z_bot in bands_depths:
            vals_s = [float(p[f"sand_{b_code}"]) for p, _ in items if p.get(f"sand_{b_code}") is not None]
            vals_c = [float(p[f"clay_{b_code}"]) for p, _ in items if p.get(f"clay_{b_code}") is not None]
            vals_bd = [float(p[f"bd_{b_code}"]) / 100.0 for p, _ in items if p.get(f"bd_{b_code}") is not None]
            vals_fc = [float(p[f"fc_{b_code}"]) for p, _ in items if p.get(f"fc_{b_code}") is not None]

            sand = float(np.mean(vals_s)) if vals_s else 40.0
            clay = float(np.mean(vals_c)) if vals_c else 20.0
            silt = max(0.0, 100.0 - sand - clay)
            if sand + silt + clay > 0:
                escala = 100.0 / (sand + silt + clay)
                sand, silt, clay = sand * escala, silt * escala, clay * escala

            tex_hz = clase_textural(sand, silt, clay) or tex_dom
            d_hz = TEXTURA_DEFECTO.get(tex_hz, d_def)
            bd = float(np.clip(np.mean(vals_bd), 1.05, 1.85)) if vals_bd else (1.0 - d_hz["por"]) * 2.65
            fc = float(np.clip(np.mean(vals_fc), 8.0, 52.0)) if vals_fc else float(d_hz["fc"])
            # Estimate PWP from clay/texture ensuring consistency with FC
            wp_est = 0.48 * clay + 2.5
            wp = float(np.clip(wp_est, 4.0, max(fc - 5.0, 5.0)))
            awc = max(fc - wp, 4.0) / 100.0
            ksat_ums = float(d_hz["ksat"]) / 3.6  # mm/h -> um/s

            rows_df.append({
                "mukey": mukey,
                "muname": f"OpenLandMap USDA ({tex_dom})",
                "cokey": f"{mukey}_c1",
                "compname": tex_dom,
                "comppct_r": 100.0,
                "hydgrp": d_def["hsg"],
                "hzname": hz_name,
                "hzdept_r": float(z_top),
                "hzdepb_r": float(z_bot),
                "sandtotal_r": round(sand, 1),
                "silttotal_r": round(silt, 1),
                "claytotal_r": round(clay, 1),
                "dbthirdbar_r": round(bd, 2),
                "ksat_r": round(ksat_ums, 2),
                "wthirdbar_r": round(fc, 1),
                "wfifteenbar_r": round(wp, 1),
                "awc_r": round(awc, 3),
            })

    df_gee = pd.DataFrame(rows_df)
    tabla, hors = resumir_suelo(df_gee, prof_cm=prof_cm, modo_prof=modo_prof)
    gdf_gee = gpd.GeoDataFrame(poly_records, crs="EPSG:4326")
    return gdf_gee, tabla, hors, "Google Earth Engine (OpenLandMap / USDA 250 m — fallback due to SSURGO 502 outage)"


def tabla_defecto(textura="Loam", prof_cm=100):
    """Fallback soil (by textural class) when USDA services fail."""
    d = TEXTURA_DEFECTO.get(textura, TEXTURA_DEFECTO["Loam"])
    pr = _coherencia_hidrofisica_horizonte(
        40.0, 40.0, 20.0, d["fc"], d["wp"], (d["fc"] - d["wp"]) / 100.0,
        (1.0 - d["por"]) * 2.65, d["ksat"] / 3.6, tex_fallback=textura,
    )
    fc_mm = pr["fc_vol"] * 10.0 * prof_cm
    wp_mm = pr["wp_vol"] * 10.0 * prof_cm
    awc_mm = pr["awc_vol"] * 10.0 * prof_cm
    gs_mm = pr["gs_vol"] * 10.0 * prof_cm
    return pd.DataFrame([dict(
        mukey="DEFAULT", muname=f"Default soil ({textura})", compname="—",
        depth_cm=float(prof_cm), prof_agro_cm=float(prof_cm), prof_ssurgo_cm=float(prof_cm),
        sand=40.0, silt=40.0, clay=20.0, textura=textura,
        da_gcm3=pr["db"], porosidad=pr["por"], psi_m=pr["psi_m"],
        fc_mm=fc_mm, awc_mm=awc_mm, wp_mm=wp_mm,
        ksat_mmh=pr["ksat_mmh"], ksat_sup_mmh=pr["ksat_mmh"], ksat_min_mmh=pr["ksat_mmh"] * 0.6,
        gs_mm=gs_mm, hsg=d["hsg"],
    )])


def rasterizar_suelo(gdf_poly, tabla, malla, shape_):
    """Assigns each cell the properties of the mukey containing it. Returns dict of arrays + mukey."""
    ny, nx = shape_
    X, Y = coordenadas_celdas(malla, shape_)
    mk = np.full(ny * nx, None, dtype=object)
    if gdf_poly is not None and len(gdf_poly):
        pts = gpd.GeoDataFrame({"i": np.arange(ny * nx)},
                               geometry=gpd.points_from_xy(X.ravel(), Y.ravel()), crs=malla["crs"])
        j = gpd.sjoin(pts, gdf_poly.to_crs(malla["crs"])[["mukey", "geometry"]], how="inner", predicate="within")
        j = j[~j.index.duplicated()]
        mk[j.index.values] = j["mukey"].values
    validos = set(tabla["mukey"])
    ok = np.array([m in validos for m in mk])
    if ok.any():
        dominante = pd.Series(mk[ok]).mode().iloc[0]
    else:
        dominante = tabla["mukey"].iloc[0]
    mk[~ok] = dominante   # cells without data (water, urban, gaps) inherit the dominant mukey
    t = tabla.set_index("mukey")
    s = pd.Series(mk)
    cols_num_grid = (
        "fc_mm", "awc_mm", "wp_mm", "ksat_mmh", "ksat_sup_mmh", "ksat_min_mmh",
        "gs_mm", "depth_cm", "prof_agro_cm", "prof_ssurgo_cm", "da_gcm3", "porosidad", "psi_m",
    )
    out = {}
    for c in cols_num_grid:
        if c in t.columns:
            out[c] = s.map(t[c]).to_numpy(dtype=float).reshape(ny, nx)
    out["depth_mm"] = out["depth_cm"] * 10.0
    out["hsg"] = s.map(t["hsg"]).to_numpy(dtype=object).reshape(ny, nx)
    out["textura"] = s.map(t["textura"]).to_numpy(dtype=object).reshape(ny, nx)
    out["mukey"] = mk.reshape(ny, nx)
    return out
