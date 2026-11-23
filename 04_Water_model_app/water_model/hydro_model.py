"""
Advanced hydrological model:
  1) Physical infiltration (SCS-CN + Green-Ampt / surface Ksat limit) and layered percolation (restrictive Ksat).
  2) Water table dynamics (deep ERA5-Land + topography), capillary rise, and available storage reduction.
  3) Subsurface lateral flow (interflow) over restrictive horizons and exfiltration in low-lying areas.
  4) 2D surface routing with support for external contributing zonal watersheds.
  5) Chronological time-step simulation (storm & post-rain drainage timelapse).
"""
import numpy as np
import pandas as pd

from .config import CN_DESNUDO, CN_VEGETADO


# ── Terrain utilities ────────────────────────────────────────────────────────
def pendiente(dem, res):
    """Dimensionless slope (m/m)."""
    gy, gx = np.gradient(dem, res)
    return np.hypot(gx, gy)


def suavizar(a, n=1):
    """3x3 moving average (reduces high-frequency DEM noise)."""
    for _ in range(int(n)):
        p = np.pad(a, 1, mode="edge")
        ny, nx = a.shape
        a = sum(p[i:i + ny, j:j + nx] for i in range(3) for j in range(3)) / 9.0
    return a


def cn_por_grupo(hsg):
    """Base CN (bare and vegetated) from the hydrological soil groups array."""
    des = np.full(hsg.shape, CN_DESNUDO["C"])
    veg = np.full(hsg.shape, CN_VEGETADO["C"])
    for g in "ABCD":
        des[hsg == g] = CN_DESNUDO[g]
        veg[hsg == g] = CN_VEGETADO[g]
    return des, veg


def lai_desde_ndvi(ndvi):
    """Empirical LAI (Baret & Guyot, 1991)."""
    x = np.clip((0.69 - ndvi) / 0.59, 1e-3, 1.0)
    return np.clip(-np.log(x) / 0.91, 0, 6)


# ── Antecedent moisture, water table dynamics & runoff ───────────────────────
def humedad_antecedente(swvl1, fc_mm, awc_mm, depth_mm, ndwi, peso_ndwi=0.3):
    """Relative moisture 0–1 (0 = PWP, 1 = FC): blend of ERA5-Land (layer 1) and Sentinel-2 NDWI."""
    if swvl1 is None or not np.isfinite(swvl1):
        w_era = np.full(fc_mm.shape, 0.5)
    else:
        fc_f = fc_mm / np.maximum(depth_mm, 10.0)
        wp_f = (fc_mm - awc_mm) / np.maximum(depth_mm, 10.0)
        w_era = np.clip((swvl1 - wp_f) / np.maximum(fc_f - wp_f, 1e-3), 0, 1)
    w_ndwi = np.clip((ndwi + 0.5) / 0.7, 0, 1)
    return (1.0 - peso_ndwi) * w_era + peso_ndwi * w_ndwi


def estimar_napa_y_ascenso(dem, suelo, swvl3=None, swvl4=None, duracion_h=24.0):
    """
    Estimates spatial water table depth (m), capillary rise (mm),
    and available 'bucket' storage reduction factor (0.20 to 1.0)
    using deep ERA5-Land moisture (layers 3 & 4: 28–289 cm), porosity,
    soil capillary suction, and relative topographic position from the DEM.
    """
    por = suelo.get("porosidad", np.full(dem.shape, 0.46))
    psi_m = suelo.get("psi_m", np.full(dem.shape, 0.35))
    ksat_min = suelo.get("ksat_min_mmh", suelo["ksat_mmh"] * 0.6)
    depth_m = np.maximum(suelo["depth_cm"] / 100.0, 0.25)

    # Deep saturation degree in ERA5-Land (100–289 cm and 28–100 cm)
    s_deep = None
    if swvl4 is not None and np.isfinite(swvl4):
        s_deep = float(swvl4)
        if swvl3 is not None and np.isfinite(swvl3):
            s_deep = 0.65 * float(swvl4) + 0.35 * float(swvl3)
    elif swvl3 is not None and np.isfinite(swvl3):
        s_deep = float(swvl3)

    if s_deep is None:
        sat_prof = np.full(dem.shape, 0.62)
    else:
        sat_prof = np.clip(s_deep / np.maximum(por, 0.32), 0.20, 0.99)

    # Regional baseline water table depth from deep moisture (0.7 m if very saturated -> 3.8 m if dry)
    z_base_m = 3.8 - 3.0 * ((sat_prof - 0.20) / 0.79) ** 1.25
    # Local topographic modulation: in depressions (dem < median) the water table nears the surface
    dem_med = float(np.nanmedian(dem))
    rel_z = dem - dem_med
    prof_napa_m = np.clip(z_base_m + 0.55 * rel_z, 0.25, 6.0)

    # Capillary fringe and available storage reduction when the water table invades or borders the profile
    z_influencia = depth_m + 1.2 * psi_m
    invasion = np.clip((z_influencia - prof_napa_m) / np.maximum(z_influencia, 0.3), 0.0, 0.85)
    factor_almacen = np.clip(1.0 - 0.75 * invasion, 0.20, 1.0)

    # Capillary rise flux (Gardner / Anat et al. approx.) from water table into the root zone
    dist_napa = np.maximum(prof_napa_m - 0.6 * depth_m, 0.12)
    tasa_cap_mmh = ksat_min * np.exp(-dist_napa / np.maximum(psi_m, 0.08)) * (sat_prof ** 1.5)
    ascenso_capilar_mm = np.clip(tasa_cap_mmh * duracion_h * 0.25, 0.0, 0.35 * suelo["awc_mm"])

    return dict(
        prof_napa_m=prof_napa_m,
        factor_almacen=factor_almacen,
        ascenso_capilar_mm=ascenso_capilar_mm,
        sat_prof=sat_prof,
    )


def ajustar_cn(cn_des, cn_veg, ndvi, pend, w0):
    """Final CN: cover (NDVI) -> slope (Williams) -> antecedent moisture condition (continuous AMC I–III)."""
    fv = np.clip((ndvi - 0.2) / 0.6, 0, 1)
    cn2 = cn_des - fv * (cn_des - cn_veg)
    cn3 = 23 * cn2 / (10 + 0.13 * cn2)
    cn2 = np.clip((cn3 - cn2) / 3 * (1 - 2 * np.exp(-13.86 * pend)) + cn2, 30, 98)
    cn1 = 4.2 * cn2 / (10 - 0.058 * cn2)
    cn3 = 23 * cn2 / (10 + 0.13 * cn2)
    cn = np.where(w0 < 0.5, cn1 + (cn2 - cn1) * w0 / 0.5, cn2 + (cn3 - cn2) * (w0 - 0.5) / 0.5)
    return np.clip(cn, 30, 98)


def escorrentia_scs(pn, cn):
    """Direct SCS-CN runoff (mm)."""
    S = 25.4 * (1000.0 / cn - 10.0)
    ia = 0.2 * S
    return np.where(pn > ia, (pn - ia) ** 2 / (pn - ia + S), 0.0)


# ── Subsurface lateral flow (interflow) ──────────────────────────────────────
def rutear_interflow(dem, agua_grav_mm, gs_cap_mm, ksat_lat_mmh, ksat_min_mmh, res, duracion_h=24.0, n_pasos=25):
    """
    Models lateral subsurface flow (interflow) over the restrictive horizon:
    gravitational water perched above the lowest-Ksat layer moves laterally according to
    topographic slope (kinematic Darcy approximation) and exfiltrates to the surface
    in low-lying or concave areas when exceeding macropore capacity (gs_cap_mm).
    Returns (final_grav_water_mm, net_lateral_flow_mm, surface_exfiltration_mm).
    """
    ny, nx = dem.shape
    g = np.nan_to_num(agua_grav_mm).copy()
    desp = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    dist = np.array([np.hypot(res, res) if (di and dj) else res for di, dj in desp])[:, None, None]

    # Slope toward the 8 neighbors based on the top elevation of the restrictive horizon (~DEM)
    zp = np.pad(dem, 1, mode="edge")
    caidas = np.stack([np.clip(dem - zp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx], 0, None) for di, dj in desp])
    grad = caidas / dist
    suma_grad = grad.sum(0)
    pesos = np.divide(grad, suma_grad, out=np.zeros_like(grad), where=suma_grad > 0)
    tan_beta = np.maximum(grad.max(0), 1e-4)

    # Anisotropy / impedance contrast between upper and restrictive horizons
    contraste = np.clip(ksat_lat_mmh / np.maximum(ksat_min_mmh, 0.05), 1.0, 12.0)
    # Movable fraction per step via kinematic Darcy's law
    v_lat_mh = (ksat_lat_mmh / 1000.0) * contraste * tan_beta
    dt_h = max(float(duracion_h) / max(n_pasos, 1), 0.25)
    frac_paso = np.clip((v_lat_mh * dt_h) / max(res, 5.0) * 18.0, 0.0, 0.35)

    flujo_acum = np.zeros_like(g)
    for _ in range(int(n_pasos)):
        salida = g * frac_paso
        if salida.max() < 1e-4:
            break
        flujo = pesos * salida
        rec = np.zeros((ny + 2, nx + 2))
        for idx, (di, dj) in enumerate(desp):
            rec[1 + di:1 + di + ny, 1 + dj:1 + dj + nx] += flujo[idx]
        entrada = rec[1:-1, 1:-1]
        g = g - salida + entrada
        flujo_acum += entrada

    # When gravitational water exceeds macropore capacity at footslopes, it exfiltrates
    exfiltracion = np.maximum(g - gs_cap_mm, 0.0)
    g_final = g - exfiltracion
    return g_final, flujo_acum, exfiltracion


# ── Surface routing ──────────────────────────────────────────────────────────
def rutear_agua(dem, h0_mm, res, n_iter=500, k=0.25, caida_borde=0.02, mascara_aoi=None):
    """
    Cellular automaton routing (8 neighbors): water flows toward neighbors with lower free-surface elevation
    (DEM + water depth), naturally filling depressions.
    If `mascara_aoi` is provided, also quantifies net surface inflow entering from external
    subwatersheds into the main field (aporte_externo_mm normalized to AOI area).
    """
    ny, nx = dem.shape
    h = np.nan_to_num(h0_mm) / 1000.0
    desp = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    dist = np.array([np.hypot(res, res) if (di and dj) else res for di, dj in desp])[:, None, None]
    perdida = 0.0
    ingreso_aoi_m = 0.0

    for _ in range(int(n_iter)):
        H = dem + h
        Hp = np.pad(H, 1, mode="edge")
        Hp[0, :] -= caida_borde; Hp[-1, :] -= caida_borde
        Hp[:, 0] -= caida_borde; Hp[:, -1] -= caida_borde
        caidas = np.stack([np.clip(H - Hp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx], 0, None) for di, dj in desp])
        grad = caidas / dist
        suma = grad.sum(0)
        salida = np.minimum(h, k * caidas.max(0))
        if salida.max() < 1e-7:
            break
        w = np.divide(grad, suma, out=np.zeros_like(grad), where=suma > 0)
        flujo = w * salida
        rec = np.zeros((ny + 2, nx + 2))
        for idx, (di, dj) in enumerate(desp):
            rec[1 + di:1 + di + ny, 1 + dj:1 + dj + nx] += flujo[idx]
        entrada_int = rec[1:-1, 1:-1]
        if mascara_aoi is not None:
            # Net variation inside AOI from lateral transport outside the AOI
            ingreso_aoi_m += float((entrada_int[mascara_aoi] - salida[mascara_aoi]).sum())
        h = h - salida + entrada_int
        perdida += rec.sum() - entrada_int.sum()

    n_aoi = max(int(mascara_aoi.sum()), 1) if mascara_aoi is not None else (ny * nx)
    aporte_ext_mm = max(ingreso_aoi_m * 1000.0 / n_aoi, 0.0)

    # Physically consistent lateral expansion of the water surface in depressions:
    # Within a basin/depression (where elevation difference between contiguous cells is <=
    # the sub-cell microtopographic tolerance `tol_cuenca_m`), coalescing water levels its free surface
    # into a continuous 2D pond without fragmenting into 1-pixel lines, while strictly blocking
    # any uphill climbing onto true slopes (`dem_nb > H + tol_cuenca_m`).
    vol_inicial_m = float(h.sum())
    if vol_inicial_m > 0:
        tol_cuenca_m = max(0.45, 0.022 * float(res))
        for _ in range(5):
            H = dem + h
            Hp = np.pad(H, 1, mode="edge")
            demp = np.pad(dem, 1, mode="edge")
            hp = np.pad(h, 1, mode="edge")
            caidas_pond = []
            vec_h_validos = []
            mascara_vec_cuenca = []
            for di, dj in desp:
                H_nb = Hp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx]
                dem_nb = demp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx]
                h_nb = hp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx]
                en_cuenca = dem_nb <= (H + tol_cuenca_m)
                dif_nivel = np.where(en_cuenca, np.maximum(H + tol_cuenca_m * 0.45 - np.maximum(H_nb, dem_nb), 0.0), 0.0)
                caidas_pond.append(dif_nivel)
                puede_recibir = (dem <= (H_nb + tol_cuenca_m)) & (h_nb > 1e-6)
                vec_h_validos.append(np.where(puede_recibir, h_nb, 0.0))
                mascara_vec_cuenca.append(puede_recibir.astype(float))

            caidas_arr = np.stack(caidas_pond)
            grad_p = caidas_arr / dist
            suma_p = grad_p.sum(0)
            salida_p = np.minimum(h, 0.35 * caidas_arr.max(0))
            w_p = np.divide(grad_p, suma_p, out=np.zeros_like(grad_p), where=suma_p > 0)
            flujo_p = w_p * salida_p
            rec_p = np.zeros((ny + 2, nx + 2))
            for idx, (di, dj) in enumerate(desp):
                rec_p[1 + di:1 + di + ny, 1 + dj:1 + dj + nx] += flujo_p[idx]
            h = np.maximum(h - salida_p + rec_p[1:-1, 1:-1], 0.0)

            n_vec_ok = sum(mascara_vec_cuenca)
            media_vec_cuenca = np.divide(sum(vec_h_validos), np.maximum(n_vec_ok, 1.0))
            h = np.where(n_vec_ok >= 1, 0.62 * h + 0.38 * media_vec_cuenca, h)

        suma_post_m = float(h.sum())
        if suma_post_m > 0:
            h *= (vol_inicial_m / suma_post_m)

    h_mm = h * 1000.0
    return h_mm, perdida * 1000.0 / (ny * nx), aporte_ext_mm


# ── Precipitation event ──────────────────────────────────────────────────────
def simular_evento(dem, ndvi, ndwi, mascara, suelo, res, precip_mm, duracion_h=24.0,
                   swvl1=None, peso_ndwi=0.3, n_iter=500, swvl3=None, swvl4=None,
                   mascara_dominio=None, hietograma_df=None):
    """
    Cell-by-cell hydro-pedological balance + water table dynamics + subsurface flow + 2D routing.
    If `hietograma_df` (from ERA5-Land Hourly + CHIRPS) is provided, integrates hourly rainfall
    intensity step-by-step against Green-Ampt instantaneous infiltration capacity (Ksat_sup).
    """
    dom = mascara_dominio if mascara_dominio is not None else np.ones(dem.shape, dtype=bool)
    pend = pendiente(dem, res)
    lai = lai_desde_ndvi(ndvi)
    interc = np.where(dom, np.minimum(np.minimum(0.3 * lai, 2.5), precip_mm), 0.0)
    pn = np.where(dom, np.maximum(precip_mm - interc, 0.0), 0.0)

    # 1) Water table dynamics and capillary rise
    napa = estimar_napa_y_ascenso(dem, suelo, swvl3=swvl3, swvl4=swvl4, duracion_h=duracion_h)
    prof_napa_m = napa["prof_napa_m"]
    factor_almacen = napa["factor_almacen"]
    ascenso_cap = np.where(dom, napa["ascenso_capilar_mm"], 0.0)

    # 2) Effective available storage (reduced when water table/capillary fringe invades or nears profile)
    # and antecedent moisture w0 without double-counting ascenso_cap in initial state
    awc_efectivo = suelo["awc_mm"] * factor_almacen
    gs_efectivo = suelo["gs_mm"] * factor_almacen
    w0 = np.clip(
        humedad_antecedente(swvl1, suelo["fc_mm"], suelo["awc_mm"], suelo["depth_mm"], ndwi, peso_ndwi),
        0.0, 1.0,
    )
    # For runoff antecedent condition (AMC), account for saturation induced by capillary rise
    w_amc = np.clip(w0 + ascenso_cap / np.maximum(awc_efectivo, 1.0), 0.0, 1.0)

    # 3) SCS-CN runoff combined with hourly physical infiltration integration (Green-Ampt / Ksat_sup)
    cn_des, cn_veg = cn_por_grupo(suelo["hsg"])
    cn = ajustar_cn(cn_des, cn_veg, ndvi, pend, w_amc)
    q_scs = np.where(dom, escorrentia_scs(pn, cn), 0.0)

    ksat_sup = suelo.get("ksat_sup_mmh", suelo["ksat_mmh"])
    ksat_min = suelo.get("ksat_min_mmh", suelo["ksat_mmh"] * 0.6)
    psi_mm = suelo.get("psi_m", np.full(dem.shape, 0.32)) * 1000.0
    deficit_poros = np.clip((1.0 - w_amc) * (awc_efectivo / np.maximum(suelo["depth_mm"], 10.0)), 0.01, 0.35)

    if hietograma_df is not None and not hietograma_df.empty and "p_mm_h" in hietograma_df:
        # Real hourly integration over the event hyetograph (hour-by-hour Green-Ampt)
        p_horas = hietograma_df["p_mm_h"].to_numpy(dtype=float)
        p_tot_h = max(float(p_horas.sum()), 1e-6)
        f_acum = np.zeros_like(dem, dtype=float)
        q_horton = np.zeros_like(dem, dtype=float)
        for ph in p_horas:
            if ph <= 0.01:
                continue
            pn_h = pn * (float(ph) / p_tot_h)
            f_cap_h = ksat_sup * (1.0 + (psi_mm * deficit_poros) / np.maximum(f_acum + 2.0, 2.0))
            inf_h = np.minimum(pn_h, f_cap_h)
            q_horton += np.maximum(pn_h - inf_h, 0.0)
            f_acum += inf_h
        q_horton = np.where(dom, q_horton, 0.0)
    else:
        f_max_fisica = ksat_sup * duracion_h + np.sqrt(2.0 * ksat_sup * duracion_h * psi_mm * deficit_poros)
        q_horton = np.where(dom, np.maximum(pn - f_max_fisica, 0.0), 0.0)

    q = np.maximum(q_scs, q_horton)
    F = np.maximum(pn - q, 0.0)  # net surface infiltration (P - Interc - Q)

    # 4) Explicit profile mass-balance closure: profile inputs = F (infiltration) + ascenso_cap
    d_fc = np.maximum(awc_efectivo * (1.0 - w0), 0.0)
    entrada_perfil = F + ascenso_cap
    d_theta = np.minimum(entrada_perfil, d_fc)
    fx = np.maximum(entrada_perfil - d_theta, 0.0)

    # Deep percolation rate to aquifer is governed by the Ksat of the most restrictive horizon
    drena = np.minimum(fx, ksat_min * duracion_h)
    resto = fx - drena
    g_store0 = np.minimum(resto, gs_efectivo)
    sat_x0 = resto - g_store0

    # 5) Subsurface lateral flow (interflow) and exfiltration in depressions
    g_store, interflow_mm, exfiltracion_mm = rutear_interflow(
        dem, g_store0, gs_efectivo, ksat_sup, ksat_min, res, duracion_h=duracion_h
    )
    sat_x = sat_x0 + exfiltracion_mm
    agua_sup0 = np.where(dom, q + sat_x, 0.0)

    # 6) 2D surface routing (including runoff contributed by external watersheds into AOI)
    lamina, perdida, aporte_cuenca_mm = rutear_agua(
        dem, agua_sup0, res, n_iter=n_iter, mascara_aoi=mascara
    )
    cap_left = np.maximum(d_fc - d_theta, 0.0) + np.maximum(gs_efectivo - g_store, 0.0)
    reinf = np.minimum(lamina, np.minimum(cap_left, np.maximum(ksat_min * duracion_h - drena, 0.0)))
    lamina = lamina - reinf
    humedad_final = np.clip(w0 + (d_theta + reinf) / np.maximum(awc_efectivo, 1e-3), 0.0, 1.0)

    m = lambda a: float(np.nanmean(a[mascara]))
    # Total AOI inputs = P + Capillary rise + External watershed inflow
    # Outputs & storages = Interception + Soil recharge (d_theta) + Deep drainage + Grav. storage (g_store)
    #                    + Reinfiltration + Final ponded depth + Net surface/subsurface outflow
    entradas_tot = float(precip_mm) + m(ascenso_cap) + float(aporte_cuenca_mm)
    almac_y_perd_internas = m(interc) + m(d_theta) + m(drena) + m(g_store) + m(reinf) + m(lamina)
    salida_neta_balance = max(entradas_tot - almac_y_perd_internas, 0.0)

    balance = dict(
        precipitacion=float(precip_mm),
        interceptacion=m(interc),
        escorrentia=m(q),
        humedad_suelo=m(d_theta),
        drenaje_profundo=m(drena),
        almac_gravitacional=m(g_store),
        exceso_saturacion=m(sat_x),
        flujo_subsuperficial=m(interflow_mm),
        ascenso_capilar=m(ascenso_cap),
        prof_napa_m=m(prof_napa_m),
        aporte_cuenca_mm=float(aporte_cuenca_mm),
        reinfiltracion=m(reinf),
        lamina_final=m(lamina),
        salida_neta=salida_neta_balance,
        entradas_totales_mm=entradas_tot,
        cierre_balance_error_mm=abs(entradas_tot - (almac_y_perd_internas + salida_neta_balance)),
        cn_medio=m(cn),
        w0_medio=m(w0),
        pendiente_media_pct=m(pend) * 100.0,
    )
    return dict(
        lamina=lamina,
        escorrentia=q,
        infiltracion=F,
        drenaje=drena,
        interflow=interflow_mm,
        prof_napa_m=prof_napa_m,
        ascenso_capilar=ascenso_cap,
        humedad0=w0,
        humedad1=humedad_final,
        cn=cn,
        pendiente=pend * 100.0,
        interceptacion=interc,
        awc=suelo["awc_mm"],
        balance=balance,
    )


def clases_encharcamiento(lamina, umbral):
    """0 = no ponding, 1 = mild, 2 = moderate, 3 = severe (multiples of threshold)."""
    return np.digitize(lamina, [umbral, 2 * umbral, 5 * umbral])


# ── Temporal sequence (Event & post-rain drainage timelapse) ─────────────────
def simular_secuencia_temporal(dem, ndvi, ndwi, mascara, suelo, res, r_evento, clima=None, fecha_ev=None, umbral=5.0):
    """
    Builds a chronological sequence (timelapse) of time steps illustrating:
      1) Initial state (pre-storm),
      2) Rainfall onset and profile infiltration,
      3) Storm peak and pore saturation,
      4) Runoff and maximum depression ponding (end of event),
      5) Gravitational drainage, deep percolation, and evaporation at +1d, +2d, +4d, and +7d.
    Returns a list of dicts with spatial arrays ('lamina', 'humedad_pct') and metrics per step.
    """
    w0 = r_evento["humedad0"]
    w1 = r_evento["humedad1"]
    lam_pico = r_evento["lamina"]
    inf_tot = r_evento["infiltracion"]
    dren_tot = r_evento["drenaje"]
    ksat_min = suelo.get("ksat_min_mmh", suelo["ksat_mmh"] * 0.6)
    awc = np.maximum(suelo["awc_mm"], 10.0)
    ha_celda = (res ** 2) / 1e4

    # Mean post-rain evapotranspiration rate (mm/day) from ERA5 or estimated
    et_dia = 4.2
    if clima is not None and not clima.empty and "pet" in clima:
        pet_val = float(clima["pet"].dropna().tail(14).mean()) if clima["pet"].dropna().empty else 4.2
        et_dia = float(np.clip(pet_val * 0.85, 2.0, 7.5))

    f_base = pd.to_datetime(fecha_ev) if fecha_ev is not None else pd.Timestamp.today().normalize()

    definicion_pasos = [
        ("Step 1 · Pre-rain (t = 0 h)", -0.2, 0.00, 0.00, 0.0),
        ("Step 2 · Rain onset & infiltration (25% P)", 0.0, 0.22, 0.35, 0.0),
        ("Step 3 · Saturation & runoff (65% P)", 0.3, 0.68, 0.78, 0.0),
        ("Step 4 · Peak ponding in lows (100% P)", 1.0, 1.00, 1.00, 0.0),
        ("Step 5 · Post-rain drainage (+24 h / Day +1)", 2.0, 1.00, 1.00, 1.0),
        ("Step 6 · Redistribution & ET (+48 h / Day +2)", 3.0, 1.00, 1.00, 2.0),
        ("Step 7 · Depression dissipation (+96 h / Day +4)", 5.0, 1.00, 1.00, 4.0),
        ("Step 8 · Post-event state (+7 days)", 8.0, 1.00, 1.00, 7.0),
    ]

    secuencia = []
    lam_prev = np.zeros_like(lam_pico)
    hum_prev = w0.copy()
    dias_prev = 0.0
    inf_acum_arr = np.zeros_like(inf_tot)
    evap_acum_arr = np.zeros_like(inf_tot)
    dren_acum_arr = np.zeros_like(dren_tot)

    for idx, (etiqueta, offset_d, f_lam, f_hum, dias_dren) in enumerate(definicion_pasos):
        if idx == 0:
            lam_t = np.zeros_like(lam_pico)
            hum_t = w0.copy()
            inf_acum_arr = np.zeros_like(inf_tot)
            evap_acum_arr = np.zeros_like(inf_tot)
            dren_acum_arr = np.zeros_like(dren_tot)
        elif dias_dren <= 0.0:
            # During accumulation (Steps 2, 3, 4), water fills the deepest center of each depression first
            # and expands toward pond edges as f_lam increases, without overflowing the basin
            q_umbral = float(np.clip(1.0 - f_lam * 0.92, 0.0, 0.85))
            pos_vals = lam_pico[lam_pico > 0.2]
            corte_lat = float(np.quantile(pos_vals, q_umbral)) if pos_vals.size else 0.0
            lam_t = np.maximum(lam_pico - corte_lat * (1.0 - f_lam), 0.0)
            vol_obj = float(lam_pico.sum()) * f_lam
            if lam_t.sum() > 0:
                lam_t = lam_t * (vol_obj / float(lam_t.sum()))
            hum_t = w0 + (w1 - w0) * f_hum
            inf_acum_arr = inf_tot * f_hum
            dren_acum_arr = dren_tot * f_lam
            evap_acum_arr = np.zeros_like(inf_tot)
            lam_prev = lam_t.copy()
            hum_prev = hum_t.copy()
            dias_prev = 0.0
        else:
            # During post-rain drainage and drying (Steps 5 to 8), separate surface depth loss
            # (lam_prev - lam_t) step-by-step between residual infiltration/percolation and direct evaporation
            dt_dias = max(float(dias_dren - dias_prev), 0.0)
            pot_infil_paso = ksat_min * 24.0 * dt_dias * 0.35
            pot_evap_paso = np.full_like(lam_prev, et_dia * dt_dias)
            pot_total_paso = np.maximum(pot_infil_paso + pot_evap_paso, 1e-9)

            perdida_lam = np.minimum(lam_prev, pot_total_paso)
            lam_t = np.maximum(lam_prev - perdida_lam, 0.0)

            frac_infil = np.divide(pot_infil_paso, pot_total_paso, out=np.zeros_like(pot_total_paso), where=pot_total_paso > 0)
            infil_lam_paso = perdida_lam * frac_infil
            evap_lam_paso = perdida_lam - infil_lam_paso

            # Soil evapotranspiration in cells where atmospheric demand exceeds pond evaporation
            demanda_et_rest = np.maximum(et_dia * dt_dias - evap_lam_paso, 0.0)
            et_suelo_paso = demanda_et_rest * np.clip(hum_prev, 0.15, 1.0) * 0.65

            # Part of pond infiltration recharges available soil moisture and the rest percolates deeply
            espacio_awc = np.maximum((1.0 - hum_prev) * awc, 0.0)
            recarga_charco = np.minimum(infil_lam_paso * 0.45, espacio_awc)
            percol_charco = np.maximum(infil_lam_paso - recarga_charco, 0.0)

            hum_t = np.clip(hum_prev + (recarga_charco - et_suelo_paso) / awc, 0.12, 1.0)
            inf_acum_arr = inf_acum_arr + infil_lam_paso
            evap_acum_arr = evap_acum_arr + evap_lam_paso + et_suelo_paso
            dren_acum_arr = dren_acum_arr + percol_charco

            lam_prev = lam_t.copy()
            hum_prev = hum_t.copy()
            dias_prev = float(dias_dren)

        inf_t = float(np.nanmean(inf_acum_arr[mascara]))
        evap_t = float(np.nanmean(evap_acum_arr[mascara]))
        dren_t = float(np.nanmean(dren_acum_arr[mascara]))
        dren_evap_t = dren_t + evap_t

        lam_aoi = lam_t[mascara]
        hum_aoi = hum_t[mascara] * 100.0
        area_enc_ha = float(((lam_t >= umbral) & mascara).sum() * ha_celda)
        fecha_txt = (f_base + pd.Timedelta(days=max(offset_d, 0))).strftime("%Y-%m-%d")

        secuencia.append(dict(
            paso=idx + 1,
            etiqueta=etiqueta,
            fecha_txt=fecha_txt,
            lamina=lam_t,
            humedad_pct=hum_t * 100.0,
            lamina_media_mm=float(np.nanmean(lam_aoi)),
            lamina_max_mm=float(np.nanmax(lam_aoi)) if lam_aoi.size else 0.0,
            humedad_media_pct=float(np.nanmean(hum_aoi)),
            area_enc_ha=area_enc_ha,
            infiltracion_acum_mm=inf_t,
            evap_acum_mm=evap_t,
            drenaje_acum_mm=dren_t,
            drenaje_evap_acum_mm=dren_evap_t,
        ))
    return secuencia


# ── Daily balance (bucket with lateral flow and capillary rise) ──────────────
def balance_diario(clima, awc_mm, ksat_mmh, cn_des, cn_veg, ndvi, pend, s0_frac=0.5, psi_m=0.35):
    """Day-by-day soil water balance using AOI mean values (P, PET, capillary rise, interflow, and drainage)."""
    S = s0_frac * awc_mm
    kc = float(np.clip(1.2 * ndvi + 0.1, 0.15, 1.15))
    filas = []
    for _, r in clima.iterrows():
        p = r["p_chirps"] if np.isfinite(r["p_chirps"]) else (r["p_era5"] if np.isfinite(r["p_era5"]) else 0.0)
        pet = r["pet"] if np.isfinite(r["pet"]) else 0.0
        sw4 = r.get("swvl4", np.nan)
        # Daily capillary contribution estimated when deep ERA5 moisture is high and topsoil dries out
        sat_d = float(np.clip(sw4 / 0.45, 0.2, 0.98)) if pd.notna(sw4) and np.isfinite(sw4) else 0.55
        deficit_rel = max(1.0 - S / max(awc_mm, 1.0), 0.0)
        cap_dia = float(np.clip(0.8 * (sat_d ** 2) * deficit_rel * (psi_m / 0.35), 0.0, 1.8))

        cn = float(ajustar_cn(cn_des, cn_veg, ndvi, pend, np.clip(S / awc_mm, 0, 1)))
        q = float(escorrentia_scs(p, cn))
        S += (p - q) + cap_dia
        etc = kc * pet
        eta = etc * min(1.0, S / (0.5 * awc_mm))
        S = max(S - eta, 0.0)
        exceso = max(S - awc_mm, 0.0)
        interflow_d = exceso * float(np.clip(pend * 2.5, 0.05, 0.45))
        drena = exceso - interflow_d
        S = min(S, awc_mm)
        filas.append(dict(
            fecha=r["fecha"], precip=p, etc=etc, eta=eta, escorrentia=q,
            ascenso_capilar=cap_dia, interflow=interflow_d, drenaje=drena,
            almacen_mm=S, almacen_pct=100 * S / awc_mm,
        ))
    return pd.DataFrame(filas)
