"""
Soil Data Access (SDA) & WFS utilities for USDA-NRCS data.
"""
import io
import warnings
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

WFS_URL = "https://sdmdataaccess.nrcs.usda.gov/Spatial/SDMNAD83Geographic.wfs"
SDA_URL = "https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest"

MAX_DEPTH_CM = 80
N_FACTOR = 0.05

TEXTURE_PALETTE = {
    "Clay": "#8B0000",
    "Silty Clay": "#B22222",
    "Sandy Clay": "#CD5C5C",
    "Clay Loam": "#D2691E",
    "Sandy Clay Loam": "#A0522D",
    "Silty Clay Loam": "#C68642",
    "Silt Loam": "#DEB887",
    "Silt": "#F5DEB3",
    "Loam": "#8FBC8F",
    "Loamy Sand": "#F4A460",
    "Sand": "#EDC9Af",
    "No Data": "#AAAAAA",
}

HORIZON_COLS = [
    "mukey", "cokey", "compname", "comppct_r", "majcompflag",
    "chkey", "hzname", "hzdept_r", "hzdepb_r",
    "sandtotal_r", "silttotal_r", "claytotal_r",
    "dbovendry_r",
    "wtenthbar_r", "wthirdbar_r", "wfifteenbar_r",
    "om_r", "ph1to1h2o_r",
    "ec_r", "ecec_r", "esp_r", "sar_r", "cec7_r",
]

NUMERIC_COLS = HORIZON_COLS[3:4] + HORIZON_COLS[7:]

MAP_VARIABLES = {
    "Clay / Arcilla (%)": "claytotal_r",
    "Sand / Arena (%)": "sandtotal_r",
    "Silt / Limo (%)": "silttotal_r",
    "Bulk Density / Dens. ap. (g/cm³)": "dbovendry_r",
    "Water 10 kPa (%)": "wtenthbar_r",
    "Water 33 kPa (%)": "wthirdbar_r",
    "Water 1500 kPa (%)": "wfifteenbar_r",
    "Organic Matter / MO (%)": "om_r",
    "pH (H₂O 1:1)": "ph1to1h2o_r",
    "EC / CE (dS/m)": "ec_r",
    "ECEC (cmol/kg)": "ecec_r",
    "ESP / PSI (%)": "esp_r",
    "SAR": "sar_r",
    "CEC / CIC (cmol/kg)": "cec7_r",
}


def get_texture_class(sand, silt, clay):
    if any(pd.isna([sand, silt, clay])):
        return "No Data"
    s, si, c = float(sand), float(silt), float(clay)
    if c >= 40 and s <= 45 and si <= 40:
        return "Clay"
    if c >= 40 and si >= 40:
        return "Silty Clay"
    if c >= 35 and s >= 45:
        return "Sandy Clay"
    if c >= 27 and s <= 45 and si >= 28:
        return "Clay Loam"
    if c >= 27 and s >= 45:
        return "Sandy Clay Loam"
    if c >= 27 and si >= 60:
        return "Silty Clay Loam"
    if si >= 50 and c < 27:
        return "Silt Loam"
    if si >= 80 and c < 12:
        return "Silt"
    if s >= 85 and c < 10:
        return "Sand"
    if s >= 70 and c < 15:
        return "Loamy Sand"
    return "Loam"


def fetch_wfs_soils(field_geom_shp):
    """Download soil polygons from USDA WFS for a given Shapely geometry."""
    minx, miny, maxx, maxy = field_geom_shp.bounds
    bbox_str = f"{minx},{miny},{maxx},{maxy}"
    params = {
        "SERVICE": "WFS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeature",
        "TYPENAME": "MapunitPoly",
        "BBOX": bbox_str,
        "SRSNAME": "EPSG:4326",
        "OUTPUTFORMAT": "GML3",
    }
    response = requests.get(WFS_URL, params=params, verify=False, timeout=45)
    if response.status_code != 200:
        raise ConnectionError(f"USDA WFS Connection failed (HTTP {response.status_code}).")
    gdf_soils = gpd.read_file(io.BytesIO(response.content))
    if gdf_soils.empty:
        raise ValueError("No soil data found in this area. USDA data is limited to US territory.")
    gdf_field = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[field_geom_shp])
    gdf_clipped = gpd.overlay(gdf_soils, gdf_field, how="intersection")
    return gdf_clipped


def fetch_texture_data(mukeys_str):
    """Query dominant texture for each map unit."""
    sql = f"""
SELECT c.mukey, c.comppct_r, ch.sandtotal_r, ch.silttotal_r, ch.claytotal_r
FROM component AS c
LEFT JOIN chorizon AS ch ON c.cokey = ch.cokey
WHERE c.mukey IN {mukeys_str} AND c.majcompflag = 'Yes'
AND ch.hzdept_r = (SELECT MIN(hzdept_r) FROM chorizon WHERE chorizon.cokey = c.cokey)
"""
    df = pd.DataFrame()
    res = requests.post(SDA_URL, data={"query": sql, "format": "JSON"}, verify=False, timeout=60)
    if res.status_code == 200 and "Table" in res.json():
        df = pd.DataFrame(
            res.json()["Table"], columns=["mukey", "pct", "sand", "silt", "clay"]
        )
        df["texture"] = df.apply(
            lambda row: get_texture_class(row["sand"], row["silt"], row["clay"]), axis=1
        )
    return df


def fetch_horizon_data(mukeys_str):
    """Full horizon query with all agronomic properties."""
    sql = (
        "SELECT\n"
        "    c.mukey, c.cokey, c.compname, c.comppct_r, c.majcompflag,\n"
        "    ch.chkey, ch.hzname, ch.hzdept_r, ch.hzdepb_r,\n"
        "    ch.sandtotal_r, ch.silttotal_r, ch.claytotal_r,\n"
        "    ch.dbovendry_r,\n"
        "    ch.wtenthbar_r, ch.wthirdbar_r, ch.wfifteenbar_r,\n"
        "    ch.om_r,\n"
        "    ch.ph1to1h2o_r,\n"
        "    ch.ec_r, ch.ecec_r,\n"
        "    ch.esp_r, ch.sar_r,\n"
        "    ch.cec7_r\n"
        "FROM component AS c\n"
        "LEFT JOIN chorizon AS ch ON c.cokey = ch.cokey\n"
        f"WHERE c.mukey IN {mukeys_str}\n"
        "  AND ch.hzdept_r IS NOT NULL\n"
        "  AND ch.hzdepb_r IS NOT NULL\n"
        "ORDER BY c.mukey, c.comppct_r DESC, ch.hzdept_r ASC"
    )
    df = pd.DataFrame()
    r = requests.post(SDA_URL, data={"query": sql, "format": "JSON"}, verify=False, timeout=60)
    if r.status_code == 200 and "Table" in r.json():
        df = pd.DataFrame(r.json()["Table"], columns=HORIZON_COLS)
        for col in NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["n_estimado_r"] = df["om_r"] * N_FACTOR
        df["thickness_cm"] = df["hzdepb_r"] - df["hzdept_r"]
    return df


def build_mukeys_str(mukeys_series):
    mukeys = tuple(int(k) for k in mukeys_series.unique())
    return f"({mukeys[0]})" if len(mukeys) == 1 else str(mukeys).replace(",)", ")")


def calc_weighted_average(df_comp, variable, max_depth=MAX_DEPTH_CM):
    import numpy as np
    df = df_comp.copy()
    df["top_eff"] = df["hzdept_r"].clip(lower=0, upper=max_depth)
    df["bot_eff"] = df["hzdepb_r"].clip(lower=0, upper=max_depth)
    df["esp_eff"] = df["bot_eff"] - df["top_eff"]
    df = df[(df["esp_eff"] > 0) & df[variable].notna()].copy()
    if df.empty:
        return np.nan
    total_esp = df["esp_eff"].sum()
    return (df[variable] * df["esp_eff"]).sum() / total_esp if total_esp > 0 else np.nan
