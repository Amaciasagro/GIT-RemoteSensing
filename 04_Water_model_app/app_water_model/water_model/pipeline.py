"""Orquestación del flujo: malla (DEM + Sentinel-2 + cuenca) -> suelo USDA/GEE -> clima -> modelo hidrológico + timelapse."""
import json
import numpy as np
import pandas as pd
import streamlit as st
from shapely.geometry import shape
from shapely.ops import unary_union

from .geo_utils import (
    definir_malla, mascara_aoi, mascara_dominio, limites_wgs84,
    gdf_desde_geojson, normalizar_cuenca, normalizar_red_drenaje,
    extraer_red_drenaje_dem, calcular_metricas_subcuencas,
)
from .gee_client import (
    descargar_malla, serie_clima, serie_indices,
    hietograma_era5_horario, consultar_cuenca_wbd, consultar_red_drenaje_gee,
)
from . import soil_client as sc
from . import hydro_model as hm

CLAVES_DERIVADAS = [
    "grid", "suelo", "suelo_grid", "clima", "indices", "resultado",
    "balance_diario", "avisos", "firmas", "detalle_evento", "cache_detalle_eventos",
]


def obtener_red_drenaje(aoi, cuenca=None, grid=None, preferir="HydroSHEDS"):
    """
    Obtiene y normaliza la red de drenaje para el dominio activo:
      1) Si el usuario ya cargó una red local en st.session_state['red_drenaje'] con origen local, la conserva.
      2) Consulta GEE: primario WWF/HydroSHEDS/v1/FreeFlowingRivers -> respaldo projects/sat-io/open-datasets/NHD/NHD_FLOWLINE.
      3) Si GEE no tiene tramos vectoriales dentro del lote/subcuenca, deriva la red jerárquica D8 desde el DEM 3DEP.
    Guarda el resultado en st.session_state['red_drenaje'] y registra advertencias en st.session_state['avisos'].
    """
    avisos = st.session_state.setdefault("avisos", [])
    red_actual = st.session_state.get("red_drenaje")
    if red_actual and str(red_actual.get("fuente", "")).startswith("Local"):
        return red_actual

    objetivo = cuenca if (cuenca is not None and cuenca.get("geom")) else aoi
    geom_json = json.dumps(objetivo["geom"])
    try:
        info, fuente_gee, av_gee = consultar_red_drenaje_gee(geom_json, preferir=preferir)
        for m in av_gee:
            if m not in avisos:
                avisos.append(m)
        feats = info.get("features", []) if isinstance(info, dict) else []
        if feats:
            gdf_r = gdf_desde_geojson(info)
            red = normalizar_red_drenaje(gdf_r, aoi=aoi, cuenca=cuenca, fuente=fuente_gee)
            st.session_state["red_drenaje"] = red
            return red
    except Exception as e_r:  # noqa: BLE001
        msg = f"⚠️ No se pudo normalizar red de drenaje vectorial de GEE ({e_r})."
        if msg not in avisos:
            avisos.append(msg)

    # Respaldo automático: red de drenaje jerárquica D8 extraída del DEM 3DEP de la malla
    if grid is not None and "dem" in grid:
        try:
            red_dem = extraer_red_drenaje_dem(grid["dem"], grid["malla"], mascara_dom=grid.get("mascara_dominio"))
            st.session_state["red_drenaje"] = red_dem
            msg_d8 = (
                "ℹ️ `WWF/HydroSHEDS/v1/FreeFlowingRivers` y `NHD_FLOWLINE` no presentan cauces cartografiados dentro del polígono; "
                "se generó la red de drenaje jerárquica D8 directamente desde el DEM 3DEP."
            )
            if msg_d8 not in avisos:
                avisos.append(msg_d8)
            return red_dem
        except Exception as e_d8:  # noqa: BLE001
            msg_err = f"⚠️ Tampoco fue posible derivar la red de drenaje del DEM: {e_d8}"
            if msg_err not in avisos:
                avisos.append(msg_err)
    return None


def obtener_cuenca_wbd_gee(aoi, nivel="HUC12"):
    """
    Consulta USGS/WBD/2017/HUC12 (o HUC10) en Google Earth Engine con .filterBounds(aoi),
    normaliza geometría y metadatos (código HUC, nombre, área, estados) y los guarda en st.session_state['cuenca'].
    Si no hay intersección, registra una advertencia en st.session_state['avisos'] y devuelve None.
    """
    avisos = st.session_state.setdefault("avisos", [])
    geom_json = json.dumps(aoi["geom"])
    try:
        info, col_id, nivel_u = consultar_cuenca_wbd(geom_json, nivel=nivel)
        feats = info.get("features", []) if isinstance(info, dict) else []
        if not feats:
            msg = f"⚠️ La consulta a `{col_id}` con `.filterBounds(aoi)` no encontró ninguna subcuenca que intersecte el AOI."
            if msg not in avisos:
                avisos.append(msg)
            return None
        gdf = gdf_desde_geojson(info)
        cuenca = normalizar_cuenca(gdf, aoi=aoi, fuente=col_id, nivel=nivel_u)
        st.session_state["cuenca"] = cuenca
        return cuenca
    except LookupError as e_lk:
        msg = f"⚠️ Sin intersección en USGS WBD ({nivel}): {e_lk}"
        if msg not in avisos:
            avisos.append(msg)
        return None
    except Exception as e:  # noqa: BLE001
        msg = f"⚠️ No se pudo consultar la cuenca USGS WBD ({nivel}) en GEE: {e}"
        if msg not in avisos:
            avisos.append(msg)
        return None


def limpiar_resultados():
    """Borra todo lo derivado del AOI (al cambiar de AOI o de cuenca)."""
    for k in CLAVES_DERIVADAS:
        st.session_state.pop(k, None)


def _rellenar(a, defecto):
    """Rellena NaN con la mediana (o un valor por defecto si todo es NaN)."""
    a = a.copy()
    v = np.nanmedian(a) if np.isfinite(a).any() else defecto
    a[~np.isfinite(a)] = v
    return a


def listar_eventos_chirps(clima, min_mm=3.0):
    """
    Extrae los eventos históricos reales de precipitación del período desde la serie CHIRPS/ERA5.
    Devuelve una lista de dicts ordenada de mayor a menor magnitud (y fecha):
      [{'label': str, 'fecha': Timestamp, 'fecha_str': str, 'p_1d': float, 'p_3d': float}, ...].
    """
    if clima is None or clima.empty:
        return []
    df = clima.copy().sort_values("fecha").reset_index(drop=True)
    p = df["p_chirps"].fillna(df["p_era5"]).fillna(0.0)
    p3 = p.rolling(3, min_periods=1).sum()
    eventos = []
    for i in range(len(df)):
        v1 = float(p.iloc[i])
        if v1 >= min_mm:
            f = pd.to_datetime(df["fecha"].iloc[i])
            v3 = float(p3.iloc[i])
            f_str = f.strftime("%Y-%m-%d")
            etq = f"{f_str} — {v1:.1f} mm/día (tormenta 3d: {v3:.1f} mm)"
            eventos.append(dict(label=etq, fecha=f, fecha_str=f_str, p_1d=v1, p_3d=v3))
    eventos.sort(key=lambda x: (x["p_1d"], x["p_3d"]), reverse=True)
    return eventos


def extraer_detalle_evento(clima, lon, lat, fecha_sel, solo_dia_pico=False):
    """
    Dado un evento/fecha seleccionado en el gráfico o selector:
      1) Identifica la ventana continua de tormenta (fecha_inicio a fecha_fin con lluvia contigua >= 1.0 mm),
      2) Calcula los milímetros totales acumulados del evento en CHIRPS,
      3) Cruza el rango con los datos horarios de ERA5-Land (hietograma_era5_horario) para extraer
         la duración real en horas activas, la intensidad máxima (mm/h) y el hietograma horario.
    """
    if clima is None or clima.empty:
        return None
    df = clima.copy().sort_values("fecha").reset_index(drop=True)
    p = df["p_chirps"].fillna(df["p_era5"]).fillna(0.0)
    df["p_mm"] = p

    if fecha_sel is not None:
        f_ts = pd.to_datetime(fecha_sel).normalize()
        m_f = df["fecha"].dt.normalize() == f_ts
        idx = int(df[m_f].index[0]) if m_f.any() else int(p.idxmax())
    else:
        idx = int(p.idxmax())

    i_ini = i_fin = idx
    if not solo_dia_pico:
        while i_ini > 0 and (idx - i_ini) < 3 and float(p.iloc[i_ini - 1]) >= 1.0:
            i_ini -= 1
        while i_fin < len(df) - 1 and (i_fin - idx) < 3 and float(p.iloc[i_fin + 1]) >= 1.0:
            i_fin += 1

    f_pico = pd.to_datetime(df["fecha"].iloc[idx])
    f_ini = pd.to_datetime(df["fecha"].iloc[i_ini])
    f_fin = pd.to_datetime(df["fecha"].iloc[i_fin])
    p_pico = float(p.iloc[idx])
    p_total = max(float(p.iloc[i_ini:i_fin + 1].sum()), p_pico, 0.5)
    n_dias = int(i_fin - i_ini + 1)

    hieto = hietograma_era5_horario(
        lon, lat,
        f_ini.strftime("%Y-%m-%d"),
        f_fin.strftime("%Y-%m-%d"),
        p_total_objetivo_mm=p_total,
    )
    return dict(
        fecha_pico=f_pico,
        fecha_pico_str=f_pico.strftime("%Y-%m-%d"),
        fecha_inicio=f_ini.strftime("%Y-%m-%d"),
        fecha_fin=f_fin.strftime("%Y-%m-%d"),
        n_dias=n_dias,
        p_pico_mm=round(p_pico, 1),
        p_total_mm=round(p_total, 1),
        duracion_real_h=hieto["duracion_real_h"],
        intensidad_max_mmh=hieto["intensidad_max_mmh"],
        intensidad_media_mmh=hieto["intensidad_media_mmh"],
        fuente_horaria=hieto["fuente_horaria"],
        df=hieto["df"],
    )


def _precipitacion(par, clima, aoi=None):
    """
    Devuelve (P mm, duracion_h, fecha_evento o None, detalle_evento o None).
    Cuando se selecciona un evento histórico, alimenta el modelo con el milimetraje total,
    la duración real (h) y el hietograma horario extraídos de CHIRPS + ERA5-Land Hourly.
    """
    modo = par["modo_p"]
    if modo.startswith("Manual") or clima is None or clima.empty:
        return float(par["p_manual"]), float(par["dur_h"]), None, None

    p = clima["p_chirps"].fillna(clima["p_era5"]).fillna(0.0)
    cache_ev = st.session_state.setdefault("cache_detalle_eventos", {})

    def _det_cache(f_ref, solo_pico):
        if aoi is None:
            return None
        f_key = pd.to_datetime(f_ref).strftime("%Y-%m-%d") if f_ref is not None else "max"
        k_ev = (aoi["id"], f_key, not bool(solo_pico))
        if k_ev not in cache_ev:
            cache_ev[k_ev] = extraer_detalle_evento(clima, aoi["lon"], aoi["lat"], f_ref, solo_dia_pico=solo_pico)
        return cache_ev[k_ev]

    if modo.startswith("Seleccionar evento"):
        ev_fecha = par.get("evento_hist_fecha")
        solo_1d = not par.get("evento_hist_ventana_completa", True)
        det = par.get("detalle_evento")
        if det is None and aoi is not None:
            det = _det_cache(ev_fecha, solo_1d)
        if det is not None:
            return float(det["p_total_mm"]), float(det["duracion_real_h"]), det["fecha_pico"], det

    if modo.startswith("Máximo diario"):
        i = int(p.idxmax())
        f_ev = clima["fecha"].iloc[i]
        det = _det_cache(f_ev, True)
        dur = float(det["duracion_real_h"]) if det else float(par["dur_h"])
        return float(p.iloc[i]), dur, f_ev, det

    if modo.startswith("Máximo 3 días"):
        r = p.rolling(3).sum()
        i = int(r.idxmax())
        f_ev = clima["fecha"].iloc[i]
        det = _det_cache(f_ev, False)
        dur = float(det["duracion_real_h"]) if det else float(par["dur_h"])
        return float(r.iloc[i]), dur, f_ev, det

    return float(p.tail(7).sum()), float(par["dur_h"]), None, None   # últimos 7 días


def _swvl_antecedente(clima, fecha, col="swvl1"):
    """Humedad volumétrica ERA5 (capa indicada) del día previo al evento, o el último dato disponible."""
    if clima is None or col not in clima or clima[col].dropna().empty:
        return None
    if fecha is not None:
        previo = clima[clima["fecha"] < fecha][col].dropna()
        if not previo.empty:
            return float(previo.iloc[-1])
    return float(clima[col].dropna().iloc[-3:].mean())


def ejecutar_pipeline(par):
    """Ejecuta (o reutiliza lo ya descargado) todo el flujo. Cada fallo no crítico se registra como aviso."""
    ss = st.session_state
    aoi = ss.get("aoi")
    if not aoi:
        st.error("Defina primero el AOI.")
        return
    avisos, firmas = [], ss.setdefault("firmas", {})
    limite_analisis = par.get("limite_analisis", "aoi")  # 'aoi', 'aoi_aporte_cuenca', 'subcuenca'
    nivel_wbd = par.get("nivel_wbd", "HUC12")

    with st.status("Ejecutando modelo hidrológico…", expanded=True) as estado:
        # 0) Cuenca hidrológica USGS WBD (HUC12/HUC10) o archivo local --------
        cuenca = ss.get("cuenca")
        if limite_analisis in ("aoi_aporte_cuenca", "subcuenca") and cuenca is None:
            st.write(f"🌊 Consultando subcuenca USGS/WBD/2017/{nivel_wbd} en Google Earth Engine (.filterBounds)…")
            cuenca = obtener_cuenca_wbd_gee(aoi, nivel=nivel_wbd)
            if cuenca is None:
                avisos.append(
                    f"⚠️ No se encontró intersección con `USGS/WBD/2017/{nivel_wbd}` para el AOI actual. "
                    "Se ejecuta el modelo utilizando únicamente el límite del AOI."
                )
                limite_analisis = "aoi"

        # Si el usuario eligió usar únicamente el AOI, no expandir la malla a la cuenca
        cuenca_activa = cuenca if (cuenca is not None and limite_analisis in ("aoi_aporte_cuenca", "subcuenca")) else None
        # Cuando se elige 'subcuenca', el límite principal de evaluación pasa a ser la subcuenca completa
        aoi_efectivo = cuenca_activa if (limite_analisis == "subcuenca" and cuenca_activa is not None) else aoi

        geom_json = json.dumps(aoi_efectivo["geom"])
        cuenca_id = f"{cuenca_activa['id']}_{limite_analisis}" if cuenca_activa else "only_aoi"
        modo_prof = par.get("modo_prof", "restrictivo")
        hoy = pd.Timestamp.today().normalize()
        f_fin = hoy.strftime("%Y-%m-%d")

        # 1) Malla: DEM + índices Sentinel-2 (cubre AOI o Subcuenca según selector)
        firma_grid = f"{aoi['id']}|{cuenca_id}|{par['res_m']}|{par['dias_s2']}|{par['suavizado']}|v4"
        dem_invalido = (
            "grid" in ss
            and (float(np.nanmax(ss["grid"]["dem"]) - np.nanmin(ss["grid"]["dem"])) < 1e-3)
        )
        if firmas.get("grid") != firma_grid or "grid" not in ss or dem_invalido:
            st.write("🛰️ Descargando DEM (3DEP) y compuesto Sentinel-2…")
            try:
                malla = definir_malla(aoi, par["res_m"] or None, cuenca=cuenca_activa)
                f_ini = (hoy - pd.Timedelta(days=int(par["dias_s2"]))).strftime("%Y-%m-%d")
                dat = descargar_malla(geom_json, malla, f_ini, f_fin)
                a = dat["arrays"]
                dem_raw = _rellenar(a["elevation"], 0.0)
                dem = hm.suavizar(dem_raw, int(par["suavizado"])) if par["suavizado"] else dem_raw.copy()
                shp = dem.shape
                m_aoi_orig = mascara_aoi(aoi, malla, shp)
                m_dom = mascara_dominio(aoi, cuenca_activa, malla, shp)
                # Si limite_analisis == 'subcuenca', la máscara evaluada es toda la subcuenca
                m_eval = m_dom if (limite_analisis == "subcuenca" and cuenca_activa is not None) else m_aoi_orig
                ss["grid"] = dict(
                    malla=malla, dem=dem, dem_raw=dem_raw,
                    ndvi=np.clip(_rellenar(a["NDVI"], 0.3), -1, 1),
                    ndwi=np.clip(_rellenar(a["NDWI"], -0.3), -1, 1),
                    lai=_rellenar(a["LAI"], 1.0),
                    mascara=m_eval,
                    mascara_aoi_lote=m_aoi_orig,
                    mascara_dominio=m_dom,
                    limite_analisis=limite_analisis,
                    bounds=limites_wgs84(malla, shp),
                    n_s2=dat["n_s2"], shape=shp,
                )
                firmas["grid"] = firma_grid
            except Exception as e:  # noqa: BLE001
                estado.update(label="❌ Error en GEE", state="error")
                st.error(f"No se pudo obtener DEM/Sentinel-2: {e}")
                return
        g = ss["grid"]

        # 2) Suelo USDA (con criterio de profundidad efectiva: agronómica vs. edáfica SSURGO)
        firma_suelo = f"{aoi['id']}|{cuenca_id}|{par['prof_cm']}|{modo_prof}"
        es_respaldo = "suelo" in ss and not str(ss["suelo"].get("fuente", "")).startswith("USDA-NRCS")
        if firmas.get("suelo") != firma_suelo or "suelo" not in ss or es_respaldo:
            st.write("🧱 Consultando SSURGO / USDA-NRCS (granulometría, Ksat, porosidad y profundidad efectiva)…")
            gdf, tabla, hors, fuente = None, None, None, "USDA-NRCS SSURGO (polígonos + horizontes)"
            bounds_consulta = aoi["bounds"]
            if cuenca_activa is not None and cuenca_activa.get("bounds"):
                b1, b2 = aoi["bounds"], cuenca_activa["bounds"]
                bounds_consulta = (min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3]))
            try:
                gdf = sc.descargar_poligonos(bounds_consulta)
                df = sc.consultar_horizontes(gdf["mukey"].unique())
                tabla, hors = sc.resumir_suelo(df, par["prof_cm"], modo_prof=modo_prof)
                gdf = gdf[gdf["mukey"].isin(tabla["mukey"])]
            except Exception as e1:  # noqa: BLE001
                try:
                    geom_u = unary_union([shape(aoi["geom"]), shape(cuenca_activa["geom"])]) if cuenca_activa else shape(aoi["geom"])
                    df = sc.consultar_horizontes(sc.mukeys_por_interseccion(geom_u.wkt))
                    tabla, hors = sc.resumir_suelo(df, par["prof_cm"], modo_prof=modo_prof)
                    gdf, fuente = None, "USDA-NRCS SSURGO (sin polígonos: mukey dominante uniforme)"
                    avisos.append(f"WFS espacial de SSURGO (USDA-NRCS) no disponible ({e1}). Se usó la consulta tabular de SSURGO.")
                except Exception as e2:  # noqa: BLE001
                    try:
                        st.write("🛰️ SSURGO (USDA-NRCS) caído (HTTP 502); consultando respaldo en Google Earth Engine (OpenLandMap USDA 250 m)…")
                        gdf, tabla, hors, fuente = sc.suelo_desde_gee(aoi_efectivo, par["prof_cm"], modo_prof=modo_prof)
                        avisos.append(
                            "⚠️ **El servidor de SSURGO (USDA-NRCS Soil Data Access) se encuentra caído o en mantenimiento** "
                            f"(`{e2}`). Mientras el servicio de USDA se restablece, se obtuvieron automáticamente los perfiles "
                            "y texturas del lote desde **Google Earth Engine (OpenLandMap USDA 250 m)**."
                        )
                    except Exception as e3:  # noqa: BLE001
                        avisos.append(f"SSURGO ({e2}) y respaldo GEE ({e3}) no disponibles. Se usa suelo por defecto (Loam).")
                        tabla, hors, gdf, fuente = sc.tabla_defecto("Loam", par["prof_cm"]), None, None, "Valor por defecto"
            ss["suelo"] = dict(tabla=tabla, horizontes=hors, gdf=gdf, fuente=fuente, modo_prof=modo_prof)
            firmas["suelo"] = firma_suelo
        s = ss["suelo"]
        ss["suelo_grid"] = sc.rasterizar_suelo(s["gdf"], s["tabla"], g["malla"], g["shape"])

        # 3) Clima (CHIRPS + ERA5-Land superficial y profundo) + serie de índices
        if firmas.get("clima") != aoi["id"] or "clima" not in ss:
            st.write("🌦️ Descargando CHIRPS / ERA5-Land (superficial + profundo) y serie Sentinel-2…")
            ini = (hoy - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
            try:
                ss["clima"] = serie_clima(aoi["lon"], aoi["lat"], ini, f_fin)
            except Exception as e:  # noqa: BLE001
                ss["clima"] = None
                avisos.append(f"Clima no disponible ({e}). Se usa la precipitación manual y humedad antecedente neutra.")
            try:
                ss["indices"] = serie_indices(geom_json, ini, f_fin)
            except Exception as e:  # noqa: BLE001
                ss["indices"] = None
                avisos.append(f"Serie temporal de índices no disponible ({e}).")
            firmas["clima"] = aoi["id"]
        clima = ss.get("clima")

        # 4) Modelo hidrológico + flujo subsuperficial + dinámica de napa + timelapse
        st.write("💧 Calculando infiltración física (hietograma horario), flujo subsuperficial, dinámica de napa y secuencia temporal…")
        try:
            p_mm, dur_real_h, f_ev, det_ev = _precipitacion(par, clima, aoi=aoi)
            ss["detalle_evento"] = det_ev
            swvl1 = _swvl_antecedente(clima, f_ev, "swvl1")
            swvl3 = _swvl_antecedente(clima, f_ev, "swvl3")
            swvl4 = _swvl_antecedente(clima, f_ev, "swvl4")
            sg = ss["suelo_grid"]
            hieto_df = det_ev["df"] if det_ev is not None else None
            r = hm.simular_evento(
                g["dem"], g["ndvi"], g["ndwi"], g["mascara"], sg, g["malla"]["res"],
                p_mm, dur_real_h, swvl1, par["peso_ndwi"], par["n_iter"],
                swvl3=swvl3, swvl4=swvl4, mascara_dominio=g["mascara_dominio"],
                hietograma_df=hieto_df,
            )
            r["categoria"] = hm.clases_encharcamiento(r["lamina"], par["umbral"])
            secuencia = hm.simular_secuencia_temporal(
                g["dem"], g["ndvi"], g["ndwi"], g["mascara"], sg, g["malla"]["res"],
                r, clima=clima, fecha_ev=f_ev, umbral=par["umbral"],
            )
            # Calcular métricas hidrológicas por subcuenca (promedio y máximo) y obtener red de drenaje
            if ss.get("cuenca") is not None:
                ss["cuenca"] = calcular_metricas_subcuencas(ss["cuenca"], g["malla"], r, p_mm, par["umbral"])
            red_dren = obtener_red_drenaje(aoi, cuenca=cuenca_activa or ss.get("cuenca"), grid=g)

            m = g["mascara"]
            ha_celda = g["malla"]["res"] ** 2 / 1e4
            area_enc = float(((r["lamina"] >= par["umbral"]) & m).sum() * ha_celda)
            ss["resultado"] = dict(
                arrays={k: v for k, v in r.items() if isinstance(v, np.ndarray)},
                balance=r["balance"],
                timelapse=secuencia,
                detalle_evento=det_ev,
                red_drenaje=red_dren,
                subcuencas_metricas=ss["cuenca"].get("subcuencas", []) if ss.get("cuenca") else [],
                duracion_h=dur_real_h,
                dem=g["dem"], dem_raw=g.get("dem_raw", g["dem"]), ndvi=g["ndvi"], ndwi=g["ndwi"],
                mascara=m, mascara_dominio=g["mascara_dominio"],
                bounds=g["bounds"], res_m=g["malla"]["res"], n_s2=g["n_s2"],
                p_mm=p_mm, fecha_evento=f_ev, swvl1=swvl1, swvl3=swvl3, swvl4=swvl4,
                umbral=par["umbral"], area_enc_ha=area_enc,
                area_aoi_ha=float(m.sum() * ha_celda),
                lamina_max=float(np.nanmax(r["lamina"][m])),
            )
            # Balance diario con medias del AOI
            if clima is not None and not clima.empty:
                sgm = {k: float(np.nanmean(sg[k][m])) for k in ("awc_mm", "ksat_mmh", "psi_m")}
                cd, cv = hm.cn_por_grupo(sg["hsg"])
                ss["balance_diario"] = hm.balance_diario(
                    clima, max(sgm["awc_mm"], 1.0), sgm["ksat_mmh"], float(np.nanmean(cd[m])),
                    float(np.nanmean(cv[m])), float(np.nanmean(g["ndvi"][m])),
                    float(np.nanmean(hm.pendiente(g["dem"], g["malla"]["res"])[m])),
                    psi_m=sgm["psi_m"],
                )
        except Exception as e:  # noqa: BLE001
            estado.update(label="❌ Error en el modelo", state="error")
            st.error(f"Fallo en el modelo hidrológico: {e}")
            return
        ss["avisos"] = avisos
        estado.update(label="✅ Modelo completado", state="complete", expanded=False)
