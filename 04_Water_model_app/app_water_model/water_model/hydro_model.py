"""
Modelo hidrológico avanzado:
  1) Infiltración física (SCS-CN + límite Green-Ampt / Ksat superficial) y percolación por estratos (Ksat restrictiva).
  2) Dinámica de napa freática (ERA5-Land profundo + topografía), ascenso capilar y reducción de almacenamiento útil.
  3) Flujo subsuperficial lateral (interflow) sobre horizontes restrictivos y exfiltración en bajos.
  4) Ruteo superficial 2D con soporte de cuencas zonales aportantes externas al lote.
  5) Simulación cronológica por pasos temporales (timelapse de tormenta y drenaje poslluvia).
"""
import numpy as np
import pandas as pd

from .config import CN_DESNUDO, CN_VEGETADO


# ── Utilidades de terreno ────────────────────────────────────────────────────
def pendiente(dem, res):
    """Pendiente adimensional (m/m)."""
    gy, gx = np.gradient(dem, res)
    return np.hypot(gx, gy)


def suavizar(a, n=1):
    """
    Filtro que preserva el microrelieve (bordes, lomas y depresiones locales):
    1) Despike robusto (3.5 MAD en ventana 5x5) para eliminar únicamente ruido puntual aislado.
    2) Si n > 0, aplica un kernel gaussiano separable ponderado al centro (peso central 0.36 vs 0.111
       de una media caja 3x3) que atenúa solo el escalonamiento sub-píxel conservando las ondulaciones
       y gradientes locales del DEM.
    """
    arr = a.astype(float).copy()
    if int(n) <= 0:
        return arr
    ny, nx = arr.shape
    if ny >= 5 and nx >= 5:
        pad5 = np.pad(arr, 2, mode="edge")
        local_sum = sum(pad5[r:r + ny, c:c + nx] for r in range(5) for c in range(5))
        local_mean = (local_sum - arr) / 24.0
        diff = arr - local_mean
        mad = float(np.nanmedian(np.abs(diff))) + 1e-6
        spikes = np.abs(diff) > (3.5 * 1.4826 * mad)
        arr[spikes] = local_mean[spikes]
    for _ in range(int(n)):
        ph = np.pad(arr, ((0, 0), (1, 1)), mode="edge")
        arr = 0.20 * ph[:, :-2] + 0.60 * ph[:, 1:-1] + 0.20 * ph[:, 2:]
        pv = np.pad(arr, ((1, 1), (0, 0)), mode="edge")
        arr = 0.20 * pv[:-2, :] + 0.60 * pv[1:-1, :] + 0.20 * pv[2:, :]
    return arr


def cn_por_grupo(hsg):
    """CN base (desnudo y vegetado) a partir del arreglo de grupos hidrológicos."""
    des = np.full(hsg.shape, CN_DESNUDO["C"])
    veg = np.full(hsg.shape, CN_VEGETADO["C"])
    for g in "ABCD":
        des[hsg == g] = CN_DESNUDO[g]
        veg[hsg == g] = CN_VEGETADO[g]
    return des, veg


def lai_desde_ndvi(ndvi):
    """LAI empírico (Baret & Guyot, 1991)."""
    x = np.clip((0.69 - ndvi) / 0.59, 1e-3, 1.0)
    return np.clip(-np.log(x) / 0.91, 0, 6)


# ── Humedad antecedente, dinámica de napa y escorrentía ──────────────────────
def humedad_antecedente(swvl1, fc_mm, awc_mm, depth_mm, ndwi, peso_ndwi=0.3):
    """Humedad relativa 0–1 (0 = PMP, 1 = CC): mezcla ERA5-Land (capa 1) y NDWI de Sentinel-2."""
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
    Estima la profundidad espacial del nivel freático (m), el ascenso capilar (mm)
    y el factor de reducción del almacenamiento útil del 'balde' (0.15 a 1.0)
    usando la humedad profunda de ERA5-Land (capas 3 y 4: 28–289 cm), la porosidad,
    la succión capilar del suelo y la posición topográfica relativa del DEM.
    """
    por = suelo.get("porosidad", np.full(dem.shape, 0.46))
    psi_m = suelo.get("psi_m", np.full(dem.shape, 0.35))
    ksat_min = suelo.get("ksat_min_mmh", suelo["ksat_mmh"] * 0.6)
    depth_m = np.maximum(suelo["depth_cm"] / 100.0, 0.25)

    # Grado de saturación profunda en ERA5-Land (100–289 cm y 28–100 cm)
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

    # Profundidad base regional de la napa según humedad profunda (0.7 m si muy saturado -> 3.8 m si seco)
    z_base_m = 3.8 - 3.0 * ((sat_prof - 0.20) / 0.79) ** 1.25
    # Modulación topográfica local: en bajos (dem < media) la napa se acerca a la superficie
    dem_med = float(np.nanmedian(dem))
    rel_z = dem - dem_med
    prof_napa_m = np.clip(z_base_m + 0.55 * rel_z, 0.25, 6.0)

    # Franja capilar y reducción del almacenamiento útil cuando la napa invade o bordea el perfil
    # Si prof_napa_m <= depth_m + psi_m, parte del perfil está ocupado por agua freática/capilar
    z_influencia = depth_m + 1.2 * psi_m
    invasion = np.clip((z_influencia - prof_napa_m) / np.maximum(z_influencia, 0.3), 0.0, 0.85)
    factor_almacen = np.clip(1.0 - 0.75 * invasion, 0.20, 1.0)

    # Flujo de ascenso capilar (aprox. tipo Gardner / Anat et al.) desde la napa hacia la zona radicular
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
    """CN final: cobertura (NDVI) -> pendiente (Williams) -> condición antecedente (AMC I–III continua)."""
    fv = np.clip((ndvi - 0.2) / 0.6, 0, 1)
    cn2 = cn_des - fv * (cn_des - cn_veg)
    cn3 = 23 * cn2 / (10 + 0.13 * cn2)
    cn2 = np.clip((cn3 - cn2) / 3 * (1 - 2 * np.exp(-13.86 * pend)) + cn2, 30, 98)
    cn1 = 4.2 * cn2 / (10 - 0.058 * cn2)
    cn3 = 23 * cn2 / (10 + 0.13 * cn2)
    cn = np.where(w0 < 0.5, cn1 + (cn2 - cn1) * w0 / 0.5, cn2 + (cn3 - cn2) * (w0 - 0.5) / 0.5)
    return np.clip(cn, 30, 98)


def escorrentia_scs(pn, cn):
    """Escorrentía directa SCS-CN (mm)."""
    S = 25.4 * (1000.0 / cn - 10.0)
    ia = 0.2 * S
    return np.where(pn > ia, (pn - ia) ** 2 / (pn - ia + S), 0.0)


# ── Flujo subsuperficial lateral (interflow) ─────────────────────────────────
def rutear_interflow(dem, agua_grav_mm, gs_cap_mm, ksat_lat_mmh, ksat_min_mmh, res, duracion_h=24.0, n_pasos=25):
    """
    Modela el flujo lateral subsuperficial (interflow) sobre el horizonte restrictivo:
    el agua gravitacional retenida sobre la capa de menor Ksat se desplaza lateralmente según
    la pendiente topográfica (aproximación cinemática de Darcy) y exfiltra a la superficie
    en zonas bajas o cóncavas cuando supera la capacidad de macroporos (gs_cap_mm).
    Devuelve (agua_grav_final_mm, flujo_lateral_neto_mm, exfiltracion_superficial_mm).
    """
    ny, nx = dem.shape
    g = np.nan_to_num(agua_grav_mm).copy()
    desp = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    dist = np.array([np.hypot(res, res) if (di and dj) else res for di, dj in desp])[:, None, None]

    # Pendiente hacia los 8 vecinos basada en la cota del techo del horizonte restrictivo (~DEM)
    zp = np.pad(dem, 1, mode="edge")
    caidas = np.stack([np.clip(dem - zp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx], 0, None) for di, dj in desp])
    grad = caidas / dist
    suma_grad = grad.sum(0)
    pesos = np.divide(grad, suma_grad, out=np.zeros_like(grad), where=suma_grad > 0)
    tan_beta = np.maximum(grad.max(0), 1e-4)

    # Anisotropía / contraste de impedancia entre horizonte superior y restrictivo
    contraste = np.clip(ksat_lat_mmh / np.maximum(ksat_min_mmh, 0.05), 1.0, 12.0)
    # Fracción desplazable por paso según ley de Darcy cinemática
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

    # Cuando el agua gravitacional supera la capacidad de macroporos en pie de pendiente, exfiltra
    exfiltracion = np.maximum(g - gs_cap_mm, 0.0)
    g_final = g - exfiltracion
    return g_final, flujo_acum, exfiltracion


# ── Ruteo superficial ────────────────────────────────────────────────────────
def rutear_agua(dem, h0_mm, res, n_iter=500, k=0.25, caida_borde=0.02, mascara_aoi=None):
    """
    Ruteo por autómata celular (8 vecinos): el agua fluye hacia vecinos de menor cota de superficie libre
    (DEM + lámina), llenando depresiones de forma natural.
    Si se provee `mascara_aoi`, cuantifica además el flujo neto superficial que ingresa desde
    las subcuencas externas hacia el lote principal (aporte_externo_mm referido al área del AOI).
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
            # Variación neta dentro del AOI por transporte lateral desde fuera del AOI
            ingreso_aoi_m += float((entrada_int[mascara_aoi] - salida[mascara_aoi]).sum())
        h = h - salida + entrada_int
        perdida += rec.sum() - entrada_int.sum()

    n_aoi = max(int(mascara_aoi.sum()), 1) if mascara_aoi is not None else (ny * nx)
    aporte_ext_mm = max(ingreso_aoi_m * 1000.0 / n_aoi, 0.0)

    # Expansión lateral físicamente consistente del espejo de agua en depresiones:
    # Dentro de una cubeta/depresión (donde el desnivel entre celdas contiguas es menor o igual
    # a la tolerancia microtopográfica de sub-celda `tol_cuenca_m`), el agua coalescente nivela su
    # superficie libre formando una mancha 2D continua sin fragmentarse en líneas de 1 píxel,
    # pero bloqueando estrictamente cualquier ascenso hacia laderas reales (`dem_nb > H + tol_cuenca_m`).
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


# ── Evento de precipitación ──────────────────────────────────────────────────
def simular_evento(dem, ndvi, ndwi, mascara, suelo, res, precip_mm, duracion_h=24.0,
                   swvl1=None, peso_ndwi=0.3, n_iter=500, swvl3=None, swvl4=None,
                   mascara_dominio=None, hietograma_df=None):
    """
    Balance hidro-pedológico celda a celda + dinámica de napa + flujo subsuperficial + ruteo 2D.
    Si se provee `hietograma_df` (extraído de ERA5-Land Hourly + CHIRPS), integra paso a paso
    la intensidad horaria contra la capacidad de infiltración instantánea de Green-Ampt (Ksat_sup).
    """
    dom = mascara_dominio if mascara_dominio is not None else np.ones(dem.shape, dtype=bool)
    pend = pendiente(dem, res)
    lai = lai_desde_ndvi(ndvi)
    interc = np.where(dom, np.minimum(np.minimum(0.3 * lai, 2.5), precip_mm), 0.0)
    pn = np.where(dom, np.maximum(precip_mm - interc, 0.0), 0.0)

    # 1) Dinámica de napa freática y ascenso capilar
    napa = estimar_napa_y_ascenso(dem, suelo, swvl3=swvl3, swvl4=swvl4, duracion_h=duracion_h)
    prof_napa_m = napa["prof_napa_m"]
    factor_almacen = napa["factor_almacen"]
    ascenso_cap = np.where(dom, napa["ascenso_capilar_mm"], 0.0)

    # 2) Almacenamiento útil efectivo (reducido cuando la napa/franja capilar invade o se acerca al perfil)
    # y humedad antecedente w0 sin duplicar ascenso_cap en el estado inicial
    awc_efectivo = suelo["awc_mm"] * factor_almacen
    gs_efectivo = suelo["gs_mm"] * factor_almacen
    w0 = np.clip(
        humedad_antecedente(swvl1, suelo["fc_mm"], suelo["awc_mm"], suelo["depth_mm"], ndwi, peso_ndwi),
        0.0, 1.0,
    )
    # Para la condición antecedente de escorrentía (AMC), considerar la saturación inducida por el ascenso capilar
    w_amc = np.clip(w0 + ascenso_cap / np.maximum(awc_efectivo, 1.0), 0.0, 1.0)

    # 3) Escorrentía SCS-CN combinada con integración horaria de infiltración física (Green-Ampt / Ksat_sup)
    cn_des, cn_veg = cn_por_grupo(suelo["hsg"])
    cn = ajustar_cn(cn_des, cn_veg, ndvi, pend, w_amc)
    q_scs = np.where(dom, escorrentia_scs(pn, cn), 0.0)

    ksat_sup = suelo.get("ksat_sup_mmh", suelo["ksat_mmh"])
    ksat_min = suelo.get("ksat_min_mmh", suelo["ksat_mmh"] * 0.6)
    psi_mm = suelo.get("psi_m", np.full(dem.shape, 0.32)) * 1000.0
    deficit_poros = np.clip((1.0 - w_amc) * (awc_efectivo / np.maximum(suelo["depth_mm"], 10.0)), 0.01, 0.35)

    if hietograma_df is not None and not hietograma_df.empty and "p_mm_h" in hietograma_df:
        # Integración horaria real sobre el hietograma del evento (Green-Ampt hora a hora)
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
    F = np.maximum(pn - q, 0.0)  # infiltración superficial neta (P - Interc - Q)

    # 4) Cierre explícito del balance en el perfil: entradas al perfil = F (infiltración) + ascenso_cap
    d_fc = np.maximum(awc_efectivo * (1.0 - w0), 0.0)
    entrada_perfil = F + ascenso_cap
    d_theta = np.minimum(entrada_perfil, d_fc)
    fx = np.maximum(entrada_perfil - d_theta, 0.0)

    # La velocidad de percolación profunda al acuífero está gobernada por la Ksat del horizonte más restrictivo
    drena = np.minimum(fx, ksat_min * duracion_h)
    resto = fx - drena
    g_store0 = np.minimum(resto, gs_efectivo)
    sat_x0 = resto - g_store0

    # 5) Flujo subsuperficial lateral (interflow) y exfiltración en bajos
    g_store, interflow_mm, exfiltracion_mm = rutear_interflow(
        dem, g_store0, gs_efectivo, ksat_sup, ksat_min, res, duracion_h=duracion_h
    )
    sat_x = sat_x0 + exfiltracion_mm
    agua_sup0 = np.where(dom, q + sat_x, 0.0)

    # 6) Ruteo superficial 2D (incluyendo escorrentía aportada por cuencas externas hacia el AOI)
    lamina, perdida, aporte_cuenca_mm = rutear_agua(
        dem, agua_sup0, res, n_iter=n_iter, mascara_aoi=mascara
    )
    cap_left = np.maximum(d_fc - d_theta, 0.0) + np.maximum(gs_efectivo - g_store, 0.0)
    reinf = np.minimum(lamina, np.minimum(cap_left, np.maximum(ksat_min * duracion_h - drena, 0.0)))
    lamina = lamina - reinf
    humedad_final = np.clip(w0 + (d_theta + reinf) / np.maximum(awc_efectivo, 1e-3), 0.0, 1.0)

    m = lambda a: float(np.nanmean(a[mascara]))
    # Entradas totales al AOI = P + Ascenso capilar + Aporte externo de cuenca
    # Salidas y almacenamientos = Interceptación + Recarga suelo (d_theta) + Drenaje profundo + Almac. grav. (g_store)
    #                             + Reinfiltración + Lámina final + Salida superficial/subsuperficial neta
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
    """0 = sin encharcamiento, 1 = leve, 2 = moderado, 3 = severo (múltiplos del umbral)."""
    return np.digitize(lamina, [umbral, 2 * umbral, 5 * umbral])


# ── Secuencia temporal (Timelapse del evento y drenaje poslluvia) ────────────
def simular_secuencia_temporal(dem, ndvi, ndwi, mascara, suelo, res, r_evento, clima=None, fecha_ev=None, umbral=5.0):
    """
    Construye una secuencia cronológica (timelapse) de pasos temporales que muestra:
      1) Estado inicial (pre-tormenta),
      2) Inicio de precipitación e infiltración en el perfil,
      3) Pico de tormenta y saturación de poros,
      4) Escorrentía y acumulación máxima en depresiones (fin del evento),
      5) Drenaje gravitacional, percolación profunda y evaporación a +1d, +2d, +4d y +7d.
    Devuelve una lista de dicts con los arreglos espaciales ('lamina', 'humedad_pct') y métricas por paso.
    """
    w0 = r_evento["humedad0"]
    w1 = r_evento["humedad1"]
    lam_pico = r_evento["lamina"]
    inf_tot = r_evento["infiltracion"]
    dren_tot = r_evento["drenaje"]
    ksat_min = suelo.get("ksat_min_mmh", suelo["ksat_mmh"] * 0.6)
    awc = np.maximum(suelo["awc_mm"], 10.0)
    ha_celda = (res ** 2) / 1e4

    # Tasa media de evapotranspiración poslluvia (mm/día) desde ERA5 o estimada
    et_dia = 4.2
    if clima is not None and not clima.empty and "pet" in clima:
        pet_val = float(clima["pet"].dropna().tail(14).mean()) if not clima["pet"].dropna().empty else 4.2
        et_dia = float(np.clip(pet_val * 0.85, 2.0, 7.5))

    f_base = pd.to_datetime(fecha_ev) if fecha_ev is not None else pd.Timestamp.today().normalize()

    definicion_pasos = [
        ("Paso 1 · Pre-lluvia (t = 0 h)", -0.2, 0.00, 0.00, 0.0),
        ("Paso 2 · Inicio lluvia e infiltración (25% P)", 0.0, 0.22, 0.35, 0.0),
        ("Paso 3 · Saturación y escurrimiento (65% P)", 0.3, 0.68, 0.78, 0.0),
        ("Paso 4 · Pico de acumulación en bajos (100% P)", 1.0, 1.00, 1.00, 0.0),
        ("Paso 5 · Drenaje poslluvia (+24 h / Día +1)", 2.0, 1.00, 1.00, 1.0),
        ("Paso 6 · Redistribución y ET (+48 h / Día +2)", 3.0, 1.00, 1.00, 2.0),
        ("Paso 7 · Disipación en depresiones (+96 h / Día +4)", 5.0, 1.00, 1.00, 4.0),
        ("Paso 8 · Estado post-evento (+7 días)", 8.0, 1.00, 1.00, 7.0),
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
            # Durante la acumulación (Pasos 2, 3, 4), el agua llena primero el centro más profundo de cada
            # depresión y se expande hacia las orillas del charco conforme crece f_lam, sin salir de la cubeta
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
            # Durante el drenaje y secado poslluvia (Pasos 5 a 8), separamos paso a paso la pérdida de lámina
            # superficial (lam_prev - lam_t) entre infiltración/percolación remanente y evaporación directa
            dt_dias = max(float(dias_dren - dias_prev), 0.0)
            pot_infil_paso = ksat_min * 24.0 * dt_dias * 0.35
            pot_evap_paso = np.full_like(lam_prev, et_dia * dt_dias)
            pot_total_paso = np.maximum(pot_infil_paso + pot_evap_paso, 1e-9)

            perdida_lam = np.minimum(lam_prev, pot_total_paso)
            lam_t = np.maximum(lam_prev - perdida_lam, 0.0)

            frac_infil = np.divide(pot_infil_paso, pot_total_paso, out=np.zeros_like(pot_total_paso), where=pot_total_paso > 0)
            infil_lam_paso = perdida_lam * frac_infil
            evap_lam_paso = perdida_lam - infil_lam_paso

            # Evapotranspiración del suelo en celdas donde la demanda atmosférica supera la evaporación de charco
            demanda_et_rest = np.maximum(et_dia * dt_dias - evap_lam_paso, 0.0)
            et_suelo_paso = demanda_et_rest * np.clip(hum_prev, 0.15, 1.0) * 0.65

            # Parte de la infiltración desde charcos recarga la humedad disponible y el resto percola en profundidad
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


# ── Balance diario (cubeta con flujo lateral y ascenso capilar) ──────────────
def balance_diario(clima, awc_mm, ksat_mmh, cn_des, cn_veg, ndvi, pend, s0_frac=0.5, psi_m=0.35):
    """Balance de agua del suelo día a día con valores medios del AOI (P, PET, ascenso capilar, interflow y drenaje)."""
    S = s0_frac * awc_mm
    kc = float(np.clip(1.2 * ndvi + 0.1, 0.15, 1.15))
    filas = []
    for _, r in clima.iterrows():
        p = r["p_chirps"] if np.isfinite(r["p_chirps"]) else (r["p_era5"] if np.isfinite(r["p_era5"]) else 0.0)
        pet = r["pet"] if np.isfinite(r["pet"]) else 0.0
        sw4 = r.get("swvl4", np.nan)
        # Aporte capilar diario estimado cuando la humedad profunda ERA5 es elevada y el suelo superior se seca
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
