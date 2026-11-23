"""Plotly charts (dark theme): 3D model, balance, climate, indices and soil profile."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_LAYOUT = dict(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,28,46,.6)",
               margin=dict(l=40, r=20, t=50, b=40), font=dict(color="#dce6f2"))


def _rgb_a_surfacecolor(rgb_arr):
    """
    Quantizes an RGB uint8 array (ny, nx, 3) to a 256-colour indexed palette
    sorted by luminance to render real satellite texture on go.Surface
    without interpolation artifacts between neighbouring vertices.
    Returns (float_index_matrix, plotly_colorscale, float_cmax).
    """
    from PIL import Image

    im_pil = Image.fromarray(rgb_arr.astype(np.uint8), mode="RGB")
    im_q = im_pil.quantize(colors=256, method=Image.MEDIANCUT)
    pal_raw = im_q.getpalette()[:256 * 3]
    n_col = max(len(pal_raw) // 3, 1)
    cols = np.array(pal_raw[:n_col * 3], dtype=int).reshape(n_col, 3)

    # Sort the palette by perceptual luminance so that WebGL linear interpolation is smooth
    lum = 0.299 * cols[:, 0] + 0.587 * cols[:, 1] + 0.114 * cols[:, 2]
    orden = np.argsort(lum)
    inv_orden = np.zeros(n_col, dtype=int)
    inv_orden[orden] = np.arange(n_col)

    idx_raw = np.clip(np.array(im_q, dtype=int), 0, n_col - 1)
    idx_arr = inv_orden[idx_raw].astype(float)
    cols_ord = cols[orden]

    escala_rgb = []
    for i in range(n_col):
        r, g, b = int(cols_ord[i, 0]), int(cols_ord[i, 1]), int(cols_ord[i, 2])
        t_pos = i / max(n_col - 1, 1)
        escala_rgb.append([t_pos, f"rgb({r},{g},{b})"])
    return idx_arr, escala_rgb, float(max(n_col - 1, 1))


def _calcular_eye_camara(cam_elev=27.0, cam_azim=45.0, cam_dist=2.05, cam_eye_directo=None):
    """
    Converts the spherical camera angles (elevation in °, horizontal azimuth in ° and distance/zoom)
    or a `cam_eye_directo` vector captured from the 3D viewer into Plotly 3D's `eye = dict(x=..., y=..., z=...)` vector.
    """
    if isinstance(cam_eye_directo, dict) and all(k in cam_eye_directo for k in ("x", "y", "z")):
        return dict(
            x=float(cam_eye_directo["x"]),
            y=float(cam_eye_directo["y"]),
            z=float(cam_eye_directo["z"]),
        )
    rad_el = np.radians(float(np.clip(cam_elev, 5.0, 88.0)))
    rad_az = np.radians(float(cam_azim))
    d = float(np.clip(cam_dist, 0.6, 4.5))
    r_xy = d * np.cos(rad_el)
    return dict(
        x=float(r_xy * np.cos(rad_az)),
        y=float(r_xy * np.sin(rad_az)),
        z=float(d * np.sin(rad_el)),
    )


def figura_3d(dem, lamina, mascara, color, color_nombre, escala, res, exag_z, exag_agua, umbral_vis, recortar,
              red_drenaje=None, bounds=None, rgb_textura=None, lamina_ref_fija=None, titulo_extra=None,
              cam_elev=27.0, cam_azim=45.0, cam_dist=2.05, cam_eye=None, cam_center=None):
    """
    Terrain surface (with thematic colour or RGB satellite texture) + accumulated water depth
    without Z-fighting or bands/tiles + optional 3D drainage network over the relief (Plotly Surface).
    """
    d, l, mk = dem[::-1].copy(), lamina[::-1].copy(), mascara[::-1]
    usar_rgb = rgb_textura is not None and rgb_textura.ndim == 3
    if usar_rgb:
        c, escala_uso, cmax_rgb = _rgb_a_surfacecolor(rgb_textura[::-1].copy())
    else:
        c, escala_uso, cmax_rgb = color[::-1].astype(float).copy(), escala, None
    ny_full, nx_full = d.shape

    # If clipping to the active domain (AOI or sub-basin), also adjust the spatial window
    # so that the field does not look small inside a large sub-basin grid
    r0, r1, c0, c1 = 0, ny_full, 0, nx_full
    if recortar and mk.any():
        filas_ok = np.where(mk.any(axis=1))[0]
        cols_ok = np.where(mk.any(axis=0))[0]
        r0, r1 = max(int(filas_ok[0]) - 1, 0), min(int(filas_ok[-1]) + 2, ny_full)
        c0, c1 = max(int(cols_ok[0]) - 1, 0), min(int(cols_ok[-1]) + 2, nx_full)
        d = d[r0:r1, c0:c1].copy()
        l = l[r0:r1, c0:c1].copy()
        mk = mk[r0:r1, c0:c1].copy()
        c = c[r0:r1, c0:c1].copy()

    ny, nx = d.shape
    vals_validos = d[mk] if (recortar and mk.any()) else d[np.isfinite(d)]
    z_min_base = float(np.nanmin(vals_validos)) if vals_validos.size else float(np.nanmin(d))
    z_max_base = float(np.nanmax(vals_validos)) if vals_validos.size else float(np.nanmax(d))
    dz_terreno = max(z_max_base - z_min_base, 0.5)

    # Real elevation in metres (m a.s.l.) so that the Z axis shows true elevations
    zt = d.copy()
    zt_plot = zt.copy()
    if recortar:
        zt_plot[~mk] = np.nan
        c[~mk] = np.nan
    mostrar = l >= umbral_vis
    if recortar:
        mostrar &= mk

    # IMPORTANT: Represent water as a continuous cover without Z-fighting (no stripes or tiles).
    # 1) Dilate the wet edge by 1 cell (`mostrar_borde`) so that go.Surface in Plotly has the 4 vertices
    #    of every peripheral cell defined and does not discard triangles on pond shores.
    # 2) Subtly depress the terrain bed (`zt_plot`) under the interior of ponds and raise
    #    the water surface (`zw`) with ample separation in the WebGL depth buffer to completely eliminate
    #    interference bands/lines (Z-fighting) when viewed from above or at an oblique angle.
    l_pos = l[mostrar & np.isfinite(l)]
    if lamina_ref_fija is not None and lamina_ref_fija > 0:
        l_ref_mm = max(float(lamina_ref_fija), 8.0)
    else:
        l_ref_mm = max(float(np.percentile(l_pos, 95)) if l_pos.size else 20.0, 8.0)
    factor_evento = min(l_ref_mm / 25.0, 1.0)
    espesor_norm = np.clip(l / l_ref_mm, 0.0, 1.2) * (0.40 + 0.60 * factor_evento)

    espesor_agua_m = np.clip(espesor_norm * dz_terreno * 0.022 * (float(exag_agua) / 150.0), 0.0, 0.055 * dz_terreno)
    offset_base_m = max(0.016 * dz_terreno, 0.12)
    z_agua_cruda = zt + espesor_agua_m + offset_base_m
    zp_w = np.pad(z_agua_cruda, 1, mode="edge")
    z_agua_plana = 0.55 * z_agua_cruda + 0.45 * (
        sum(zp_w[i:i + ny, j:j + nx] for i in range(3) for j in range(3)) / 9.0
    )

    # 3x3 dilation of `mostrar` to close the shores of each pond in Plotly's triangle mesh
    mp_pad = np.pad(mostrar.astype(int), 1, mode="constant", constant_values=0)
    mostrar_dil = sum(mp_pad[i:i + ny, j:j + nx] for i in range(3) for j in range(3)) > 0
    if recortar:
        mostrar_dil &= mk
    es_orilla = mostrar_dil & (~mostrar)

    # Terrain bed slightly depressed under the pond interior to avoid Z-fighting with the water
    zt_plot = np.where(mostrar, zt_plot - max(0.018 * dz_terreno, 0.10), zt_plot)

    z_charco = np.maximum(z_agua_plana, zt + offset_base_m)
    z_orilla = zt + offset_base_m * 0.35
    zw = np.where(mostrar, z_charco, np.where(es_orilla, z_orilla, np.nan))
    lw = np.where(mostrar, l, np.where(es_orilla, float(umbral_vis), np.nan))

    x, y = np.arange(nx) * res, np.arange(ny) * res
    ancho_m = max(float(nx - 1) * res, 1.0)
    alto_m = max(float(ny - 1) * res, 1.0)
    max_xy = max(ancho_m, alto_m)
    ax_x = float(ancho_m / max_xy)
    ax_y = float(alto_m / max_xy)
    # Real physical vertical ratio (dz_terreno / max_xy) with a visual floor of 0.09 for flat terrain,
    # multiplied by exag_z over a wide range (up to 2.60) so that every exaggeration change (0.5x to 25x) is reflected
    ratio_base = max(dz_terreno / max_xy, 0.09)
    ax_z = float(np.clip(ratio_base * float(exag_z), 0.08, 2.60))

    z_rango_min = z_min_base - 0.02 * dz_terreno
    z_rango_max = z_max_base + 0.16 * dz_terreno

    fig = go.Figure()
    surf_kwargs = dict(
        x=x, y=y, z=zt_plot, surfacecolor=c, colorscale=escala_uso, name="Terrain",
        lighting=dict(ambient=0.72 if usar_rgb else 0.55, diffuse=0.88, specular=0.15),
    )
    if usar_rgb:
        surf_kwargs.update(showscale=False, cmin=0.0, cmax=cmax_rgb)
    else:
        surf_kwargs.update(colorbar=dict(title=color_nombre, x=-0.02, len=0.6))
    fig.add_trace(go.Surface(**surf_kwargs))
    if np.isfinite(lw).any():
        fig.add_trace(go.Surface(x=x, y=y, z=zw, surfacecolor=lw, name="Water", opacity=0.93,
                                 colorscale=[[0, "#a8dcff"], [0.5, "#2f8bff"], [1, "#1a3fb8"]],
                                 cmin=umbral_vis, cmax=max(float(np.nanmax(lw)), umbral_vis + 1e-3),
                                 colorbar=dict(title="Depth (mm)", x=1.02, len=0.6)))

    # Overlay 3D drainage network grouped by hierarchical order if provided
    if red_drenaje and red_drenaje.get("features_geojson") and bounds:
        (s, w), (n, e) = bounds
        por_orden = {}
        for feat in red_drenaje["features_geojson"].get("features", []):
            pr = feat.get("properties", {})
            ord_v = int(pr.get("orden", 2))
            gros_v = float(pr.get("grosor_px", 3.0))
            col_v = pr.get("color", "#00f5d4")
            geom = feat.get("geometry", {})
            lineas = [geom["coordinates"]] if geom.get("type") == "LineString" else geom.get("coordinates", [])
            xs_l, ys_l, zs_l = por_orden.setdefault((ord_v, gros_v, col_v), ([], [], []))
            for coords in lineas:
                for lon, lat in coords:
                    fx_full = (lon - w) / (e - w + 1e-9) * (nx_full - 1)
                    fy_full = (lat - s) / (n - s + 1e-9) * (ny_full - 1)
                    ci = int(round(fx_full)) - c0
                    ri = int(round(fy_full)) - r0
                    if 0 <= ci < nx and 0 <= ri < ny and (not recortar or mk[ri, ci]):
                        z_val = zt[ri, ci]
                        if np.isfinite(zw[ri, ci]):
                            z_val = max(z_val, zw[ri, ci])
                        xs_l.append((fx_full - c0) * res)
                        ys_l.append((fy_full - r0) * res)
                        zs_l.append(float(z_val) + max(0.025 * dz_terreno, 0.08))
                    else:
                        # Insert a None separator when a vertex leaves the grid or the active mask
                        # to avoid artificial straight lines between disconnected channel reaches
                        if xs_l and xs_l[-1] is not None:
                            xs_l.append(None); ys_l.append(None); zs_l.append(None)
                if xs_l and xs_l[-1] is not None:
                    xs_l.append(None); ys_l.append(None); zs_l.append(None)

        for (ord_v, gros_v, col_v), (xs_l, ys_l, zs_l) in sorted(por_orden.items()):
            if xs_l:
                fig.add_trace(go.Scatter3d(
                    x=xs_l, y=ys_l, z=zs_l, mode="lines",
                    name=f"Drainage Order {ord_v}",
                    line=dict(color=col_v, width=max(gros_v * 1.6, 3.0)),
                    hoverinfo="name",
                ))
    layout_3d = {**_LAYOUT, "margin": dict(l=0, r=0, t=36 if titulo_extra else 30, b=0)}
    if titulo_extra:
        layout_3d["title"] = dict(text=titulo_extra, font=dict(size=13, color="#e8f1fb"), x=0.02)
    eye_cam = _calcular_eye_camara(cam_elev=cam_elev, cam_azim=cam_azim, cam_dist=cam_dist, cam_eye_directo=cam_eye)
    cam_dict = dict(eye=eye_cam)
    if isinstance(cam_center, dict) and all(k in cam_center for k in ("x", "y", "z")):
        cam_dict["center"] = dict(x=float(cam_center["x"]), y=float(cam_center["y"]), z=float(cam_center["z"]))
    fig.update_layout(**layout_3d, height=680,
                      scene=dict(aspectmode="manual",
                                 aspectratio=dict(x=ax_x, y=ax_y, z=ax_z),
                                 camera=cam_dict,
                                 uirevision="cam_interactiva_3d",
                                 xaxis_title="Easting (m)", yaxis_title="Northing (m)",
                                 zaxis_title=f"Elevation (m a.s.l., exag. ×{exag_z:g})",
                                 xaxis=dict(backgroundcolor="rgba(0,0,0,0)"),
                                 yaxis=dict(backgroundcolor="rgba(0,0,0,0)"),
                                 zaxis=dict(range=[z_rango_min, z_rango_max], backgroundcolor="rgba(0,0,0,0)")))
    return fig


def _estado_proceso_timelapse(idx_paso):
    """Classifies the time step into its physical state (Accumulation, Peak, Drainage or Drying)."""
    if idx_paso == 1:
        return "Initial condition (Pre-rain)", (135, 165, 195)
    if idx_paso in (2, 3):
        return "Accumulation and active infiltration", (55, 165, 255)
    if idx_paso == 4:
        return "Peak accumulation in depressions", (255, 110, 110)
    if idx_paso in (5, 6):
        return "Gravitational drainage and redistribution", (56, 210, 210)
    return "Drying and evapotranspiration", (47, 212, 167)


def _cargar_fuentes_pil(escala=1.0):
    """
    Loads Windows TrueType fonts (Segoe UI / Arial / Calibri) with full support for accents
    and special characters. If none is found, returns the default font.
    """
    import os
    from PIL import ImageFont

    rutas_bold = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
    ]
    rutas_reg = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]
    f_titulo = f_sub = f_met = None
    for rb in rutas_bold:
        if os.path.isfile(rb):
            try:
                f_titulo = ImageFont.truetype(rb, int(round(18 * escala)))
                f_sub = ImageFont.truetype(rb, int(round(14 * escala)))
                break
            except Exception:
                pass
    for rr in rutas_reg:
        if os.path.isfile(rr):
            try:
                f_met = ImageFont.truetype(rr, int(round(14 * escala)))
                if f_sub is None:
                    f_sub = ImageFont.truetype(rr, int(round(14 * escala)))
                if f_titulo is None:
                    f_titulo = ImageFont.truetype(rr, int(round(18 * escala)))
                break
            except Exception:
                pass
    if f_titulo is None:
        f_default = ImageFont.load_default()
        return f_default, f_default, f_default, False
    return f_titulo, f_sub, f_met, True


def _limpiar_texto_pil(txt, soporta_unicode=True):
    """Normalizes special symbols to guarantee that corrupted characters never appear in PIL."""
    s = str(txt).replace("·", "|").replace("—", "-").replace("–", "-").replace("≥", ">=")
    if soporta_unicode:
        return s
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _remuestrear_2d_bicubico(arr, shape_yx):
    """Smoothly resamples a 2D (float) or 3D (RGB uint8) array to (ny_out, nx_out) with bicubic interpolation."""
    from PIL import Image

    if isinstance(shape_yx, int):
        ny_out = nx_out = int(shape_yx)
    else:
        ny_out, nx_out = int(shape_yx[0]), int(shape_yx[1])
    if arr.ndim == 3:
        im = Image.fromarray(arr.astype(np.uint8), mode="RGB").resize((nx_out, ny_out), Image.BICUBIC)
        return np.array(im, dtype=np.uint8)
    arr_f = np.nan_to_num(arr, nan=float(np.nanmedian(arr)) if np.isfinite(arr).any() else 0.0).astype(np.float32)
    im = Image.fromarray(arr_f, mode="F").resize((nx_out, ny_out), Image.BICUBIC)
    return np.array(im, dtype=float)


def _preparar_escena_3d_comun(dem, lamina, mascara, rgb_base, res, exag_z, exag_agua, umbral_vis,
                              lam_ref_seq, recortar=True, red_drenaje=None, bounds=None, ng_max=135):
    """
    Prepares the 3D geometry with exactly the same orientation ([::-1]), clipping, real elevations (m a.s.l.),
    aspect ratio (ax_x, ax_y, ax_z), levelled water surface and 3D drainage network as `figura_3d`.
    """
    d_full = dem[::-1].copy()
    l_full = lamina[::-1].copy()
    mk_full = mascara[::-1].copy()
    rgb_full = rgb_base[::-1].copy()
    ny_full, nx_full = d_full.shape

    r0, r1, c0, c1 = 0, ny_full, 0, nx_full
    if recortar and mk_full.any():
        f_ok = np.where(mk_full.any(axis=1))[0]
        c_ok = np.where(mk_full.any(axis=0))[0]
        r0, r1 = max(int(f_ok[0]) - 1, 0), min(int(f_ok[-1]) + 2, ny_full)
        c0, c1 = max(int(c_ok[0]) - 1, 0), min(int(c_ok[-1]) + 2, nx_full)

    d_crop = d_full[r0:r1, c0:c1].copy()
    l_crop = l_full[r0:r1, c0:c1].copy()
    mk_crop = mk_full[r0:r1, c0:c1].copy()
    rgb_crop = rgb_full[r0:r1, c0:c1].copy()
    ny_c, nx_c = d_crop.shape

    ancho_m = max(float(nx_c - 1) * res, 1.0)
    alto_m = max(float(ny_c - 1) * res, 1.0)
    max_xy = max(ancho_m, alto_m)
    ax_x = float(ancho_m / max_xy)
    ax_y = float(alto_m / max_xy)

    # Smoothly resample preserving the aspect ratio (nx_c, ny_c) for a continuous, sharp 3D mesh
    escala_g = min(float(ng_max) / max(ny_c, nx_c, 1), 2.2)
    if max(ny_c, nx_c) < int(ng_max * 0.75):
        escala_g = float(ng_max) / max(ny_c, nx_c, 1)
    ny_g = int(np.clip(round(ny_c * escala_g), 55, ng_max))
    nx_g = int(np.clip(round(nx_c * escala_g), 55, ng_max))

    d = _remuestrear_2d_bicubico(d_crop, (ny_g, nx_g))
    l = np.maximum(_remuestrear_2d_bicubico(l_crop, (ny_g, nx_g)), 0.0)
    mk = _remuestrear_2d_bicubico(mk_crop.astype(float), (ny_g, nx_g)) >= 0.45
    rgb_t = _remuestrear_2d_bicubico(rgb_crop, (ny_g, nx_g))

    vals_validos = d[mk] if (recortar and mk.any()) else d[np.isfinite(d)]
    z_min_base = float(np.nanmin(vals_validos)) if vals_validos.size else float(np.nanmin(d))
    z_max_base = float(np.nanmax(vals_validos)) if vals_validos.size else float(np.nanmax(d))
    dz_terreno = max(z_max_base - z_min_base, 0.5)

    ratio_base = max(dz_terreno / max_xy, 0.09)
    ax_z = float(np.clip(ratio_base * float(exag_z), 0.08, 2.60))
    z_rango_min = z_min_base - 0.02 * dz_terreno
    z_rango_max = z_max_base + 0.16 * dz_terreno

    mostrar = l >= umbral_vis
    if recortar:
        mostrar &= mk

    l_ref_mm = max(float(lam_ref_seq), 8.0)
    factor_evento = min(l_ref_mm / 25.0, 1.0)
    espesor_norm = np.clip(l / l_ref_mm, 0.0, 1.2) * (0.40 + 0.60 * factor_evento)
    espesor_agua_m = np.clip(espesor_norm * dz_terreno * 0.012 * (float(exag_agua) / 150.0), 0.0, 0.03 * dz_terreno)
    offset_base_m = max(0.004 * dz_terreno, 0.02)
    z_agua_cruda = d + espesor_agua_m + offset_base_m
    zp_w = np.pad(z_agua_cruda, 1, mode="edge")
    z_agua_plana = 0.5 * z_agua_cruda + 0.5 * (
        sum(zp_w[i:i + ny_g, j:j + nx_g] for i in range(3) for j in range(3)) / 9.0
    )
    zw = np.where(mostrar, np.maximum(z_agua_plana, d + offset_base_m * 0.6), d)

    # 3D shading identical to Plotly Surface lighting (ambient=0.72, diffuse=0.88) over the Sentinel-2 image
    zn = np.clip((d - z_min_base) / dz_terreno, 0.0, 1.0)
    intens_hs = 14.0 + 4.0 * float(exag_z)
    gy, gx = np.gradient(zn * intens_hs)
    pend = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    asp = np.arctan2(-gx, gy)
    az, alt = np.radians(315.0), np.radians(44.0)
    cos_inc = np.clip(np.sin(alt) * np.sin(pend) + np.cos(alt) * np.cos(pend) * np.cos(az - asp), 0.0, 1.0)
    iluminacion = np.clip(0.58 + 0.54 * cos_inc, 0.48, 1.14)
    rgb_shaded = np.clip(rgb_t.astype(float) * iluminacion[:, :, None], 0.0, 255.0)

    # Colour per face (ny_g - 1, nx_g - 1, 4) combining Sentinel-2 texture + water surface (#a8dcff -> #2f8bff -> #1a3fb8)
    rgb_caras = 0.25 * (
        rgb_shaded[:-1, :-1] + rgb_shaded[1:, :-1] + rgb_shaded[:-1, 1:] + rgb_shaded[1:, 1:]
    ) / 255.0
    l_caras = 0.25 * (l[:-1, :-1] + l[1:, :-1] + l[:-1, 1:] + l[1:, 1:])
    mk_caras = (mk[:-1, :-1] & mk[1:, :-1] & mk[:-1, 1:] & mk[1:, 1:]) if recortar else np.ones_like(l_caras, dtype=bool)
    agua_caras = (l_caras >= umbral_vis) & mk_caras

    # Water colour scale identical to figura_3d: [[0, "#a8dcff"], [0.5, "#2f8bff"], [1, "#1a3fb8"]]
    t_w = np.clip((l_caras - umbral_vis) / max(l_ref_mm - umbral_vis, 1e-3), 0.0, 1.0)
    c0_w = np.array([168.0, 220.0, 255.0]) / 255.0
    c1_w = np.array([47.0, 139.0, 255.0]) / 255.0
    c2_w = np.array([26.0, 63.0, 184.0]) / 255.0
    col_agua = np.where(
        (t_w < 0.5)[:, :, None],
        c0_w + (c1_w - c0_w) * (t_w * 2.0)[:, :, None],
        c1_w + (c2_w - c1_w) * ((t_w - 0.5) * 2.0)[:, :, None],
    )
    alpha_w = np.clip(0.84 + 0.12 * t_w, 0.84, 0.96)[:, :, None]
    rgb_final = np.where(
        agua_caras[:, :, None],
        rgb_caras * (1.0 - alpha_w) + col_agua * alpha_w,
        rgb_caras,
    )
    alpha_caras = np.where(mk_caras, 1.0, 0.0)
    facecolors = np.dstack([np.clip(rgb_final, 0.0, 1.0), alpha_caras])

    z_surf = np.where(mostrar, zw, d).copy()
    if recortar:
        z_surf[~mk] = np.nan

    x_vec = np.linspace(0.0, ancho_m, nx_g)
    y_vec = np.linspace(0.0, alto_m, ny_g)
    X_m, Y_m = np.meshgrid(x_vec, y_vec)

    # Extract 3D traces of the drainage network in the same system (Easting m, Northing m, Elevation m a.s.l.)
    segmentos_red = []
    if red_drenaje and red_drenaje.get("features_geojson") and bounds:
        (s, w), (n, e) = bounds
        for feat in red_drenaje["features_geojson"].get("features", []):
            pr = feat.get("properties", {})
            gros_v = float(pr.get("grosor_px", 2.5))
            col_v = pr.get("color", "#00f5d4")
            geom = feat.get("geometry", {})
            lineas = [geom["coordinates"]] if geom.get("type") == "LineString" else geom.get("coordinates", [])
            for coords in lineas:
                xs_l, ys_l, zs_l = [], [], []
                for lon, lat in coords:
                    fx_full = (lon - w) / (e - w + 1e-9) * (nx_full - 1)
                    fy_full = (lat - s) / (n - s + 1e-9) * (ny_full - 1)
                    ci = int(round(fx_full)) - c0
                    ri = int(round(fy_full)) - r0
                    if 0 <= ci < nx_c and 0 <= ri < ny_c:
                        if recortar and not mk_crop[ri, ci]:
                            if len(xs_l) >= 2:
                                segmentos_red.append((xs_l, ys_l, zs_l, col_v, gros_v))
                            xs_l, ys_l, zs_l = [], [], []
                            continue
                        gi_r = int(np.clip(round(ri / max(ny_c - 1, 1) * (ny_g - 1)), 0, ny_g - 1))
                        gi_c = int(np.clip(round(ci / max(nx_c - 1, 1) * (nx_g - 1)), 0, nx_g - 1))
                        zv = float(zw[gi_r, gi_c]) if np.isfinite(zw[gi_r, gi_c]) else float(d[gi_r, gi_c])
                        xs_l.append((fx_full - c0) * res)
                        ys_l.append((fy_full - r0) * res)
                        zs_l.append(zv + max(0.022 * dz_terreno, 0.08))
                    else:
                        if len(xs_l) >= 2:
                            segmentos_red.append((xs_l, ys_l, zs_l, col_v, gros_v))
                        xs_l, ys_l, zs_l = [], [], []
                if len(xs_l) >= 2:
                    segmentos_red.append((xs_l, ys_l, zs_l, col_v, gros_v))

    return dict(
        X=X_m, Y=Y_m, Z=z_surf, Z_raw= np.where(mostrar, zw, d),
        mk=mk, facecolors=facecolors,
        ancho_m=ancho_m, alto_m=alto_m,
        z_min_base=z_min_base, z_max_base=z_max_base, dz_terreno=dz_terreno,
        z_rango_min=z_rango_min, z_rango_max=z_rango_max,
        ax_x=ax_x, ax_y=ax_y, ax_z=ax_z,
        l_ref_mm=l_ref_mm, segmentos_red=segmentos_red,
    )


def _decorar_hud_pil(img, paso_info, total_pasos, exag_z, dz, fecha_s2_txt=None, cam_elev=27.0, cam_azim=45.0):
    """Draws the HUD header and footer with TrueType typography (full accent support)."""
    from PIL import ImageDraw

    W, H = img.size
    escala_ui = W / 960.0
    f_tit, f_sub, f_met, ok_utf = _cargar_fuentes_pil(escala=escala_ui)
    draw = ImageDraw.Draw(img, "RGBA")

    idx_p = int(paso_info["paso"])
    estado_txt, col_est = _estado_proceso_timelapse(idx_p)
    h_top = int(round(72 * escala_ui))
    draw.rectangle([(0, 0), (W, h_top)], fill=(13, 23, 39, 242))
    draw.rectangle([(0, h_top - 3), (W, h_top)], fill=(*col_est, 255))

    s2_tag = f"  |  S2: {fecha_s2_txt}" if fecha_s2_txt else ""
    t1 = _limpiar_texto_pil(
        f"{paso_info['etiqueta']}  |  Date: {paso_info['fecha_txt']}{s2_tag}  |  Exag.: x{exag_z:g}  |  Angle: {cam_azim:.0f}°/{cam_elev:.0f}°",
        ok_utf,
    )
    t2 = _limpiar_texto_pil(
        f"PROCESS STATE: {estado_txt.upper()}   (DEM relief: {dz:.1f} m)",
        ok_utf,
    )
    draw.text((int(18 * escala_ui), int(9 * escala_ui)), t1, fill=(235, 243, 252), font=f_tit)
    draw.text((int(18 * escala_ui), int(39 * escala_ui)), t2, fill=col_est, font=f_sub)

    h_bot = int(round(50 * escala_ui))
    draw.rectangle([(0, H - h_bot), (W, H)], fill=(13, 23, 39, 242))
    metricas_hud = _limpiar_texto_pil(
        f"Mean depth: {paso_info['lamina_media_mm']:.1f} mm   |   "
        f"Max. depth: {paso_info['lamina_max_mm']:.1f} mm   |   "
        f"Ponded area: {paso_info['area_enc_ha']:.2f} ha   |   "
        f"Profile moisture: {paso_info['humedad_media_pct']:.0f}% AWC",
        ok_utf,
    )
    draw.text((int(18 * escala_ui), int(H - h_bot + 7 * escala_ui)), metricas_hud, fill=(210, 226, 244), font=f_met)

    bx0, bx1 = int(18 * escala_ui), int(W - 18 * escala_ui)
    by0, by1 = int(H - 13 * escala_ui), int(H - 6 * escala_ui)
    draw.rectangle([(bx0, by0), (bx1, by1)], fill=(28, 45, 68, 255))
    prog_w = int((bx1 - bx0) * (idx_p / max(total_pasos, 1)))
    draw.rectangle([(bx0, by0), (bx0 + prog_w, by1)], fill=(*col_est, 255))
    return img


def _render_cuadro_3d_matplotlib(dem, lamina, mascara, rgb_base, paso_info, total_pasos, res, exag_z, exag_agua,
                                 umbral_vis, lam_ref_seq, recortar=True, red_drenaje=None, bounds=None,
                                 fecha_s2_txt=None, tamaño=(1120, 680), ng_max=135,
                                 cam_elev=27.0, cam_azim=45.0, cam_dist=2.05, cam_center=None):
    """
    Renders a 3D frame with Matplotlib (Axes3D.plot_surface) replicating the view, orientation,
    projection angle (cam_elev, cam_azim, cam_dist, cam_center), vertical exaggeration (exag_z),
    axes in metres (Easting, Northing, Elevation m a.s.l.), Sentinel-2 satellite texture,
    water surface with colour bar and 3D drainage network of the interactive model above (`figura_3d`).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize
    from PIL import Image

    esc = _preparar_escena_3d_comun(
        dem, lamina, mascara, rgb_base, res, exag_z, exag_agua, umbral_vis,
        lam_ref_seq, recortar=recortar, red_drenaje=red_drenaje, bounds=bounds, ng_max=ng_max,
    )

    W, H = tamaño
    dpi = 100
    fig = plt.figure(figsize=(W / dpi, H / dpi), dpi=dpi, facecolor="#0b1320")
    ax = fig.add_axes([0.03, 0.07, 0.83, 0.82], projection="3d", facecolor="#0b1320")

    # Continuous 3D surface without seams or black edges between cells (antialiased=False, linewidth=0)
    ax.plot_surface(
        esc["X"], esc["Y"], esc["Z"],
        facecolors=esc["facecolors"],
        rstride=1, cstride=1,
        antialiased=False, shade=False, linewidth=0, edgecolor="none",
    )

    # Overlay the 3D drainage network if active
    for xs_l, ys_l, zs_l, col_v, gros_v in esc["segmentos_red"]:
        ax.plot(xs_l, ys_l, zs_l, color=col_v, linewidth=max(gros_v * 0.75, 1.3), alpha=0.92, zorder=15)

    # Apply framing offset (pan / center) if the user panned the 3D model with the mouse
    dx_m = dy_m = dz_m = 0.0
    if isinstance(cam_center, dict):
        dx_m = float(cam_center.get("x", 0.0)) / max(esc["ax_x"], 0.1) * esc["ancho_m"] * 0.45
        dy_m = float(cam_center.get("y", 0.0)) / max(esc["ax_y"], 0.1) * esc["alto_m"] * 0.45
        dz_m = float(cam_center.get("z", 0.0)) / max(esc["ax_z"], 0.1) * esc["dz_terreno"] * 0.45

    ax.set_xlim(0.0 + dx_m, esc["ancho_m"] + dx_m)
    ax.set_ylim(0.0 + dy_m, esc["alto_m"] + dy_m)
    ax.set_zlim(esc["z_rango_min"] + dz_m, esc["z_rango_max"] + dz_m)
    zoom_mpl = float(np.clip(2.05 / max(float(cam_dist), 0.55), 0.55, 2.20))
    try:
        ax.set_box_aspect((esc["ax_x"], esc["ax_y"], esc["ax_z"]), zoom=zoom_mpl)
    except TypeError:
        ax.set_box_aspect((esc["ax_x"], esc["ax_y"], esc["ax_z"]))

    # Camera angle frozen from the upper 3D Model
    ax.view_init(elev=float(cam_elev), azim=float(cam_azim))

    # Dark style consistent with Plotly Dark
    pane_col = (0.067, 0.110, 0.180, 0.72)
    for axis_p in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis_p.set_pane_color(pane_col)
        axis_p._axinfo["grid"]["color"] = (0.14, 0.22, 0.33, 0.65)
        axis_p._axinfo["grid"]["linewidth"] = 0.6

    ax.tick_params(axis="x", colors="#9bb3cc", labelsize=8, pad=1)
    ax.tick_params(axis="y", colors="#9bb3cc", labelsize=8, pad=1)
    ax.tick_params(axis="z", colors="#9bb3cc", labelsize=8, pad=2)
    ax.set_xlabel("Easting (m)", color="#dce6f2", fontsize=9, labelpad=6)
    ax.set_ylabel("Northing (m)", color="#dce6f2", fontsize=9, labelpad=6)
    ax.set_zlabel(f"Elevation (m a.s.l., exag. ×{exag_z:g})", color="#dce6f2", fontsize=9, labelpad=7)

    # Side colour bar for the water depth (mm), identical to the one in figura_3d
    cmap_agua = LinearSegmentedColormap.from_list("agua_3d", ["#a8dcff", "#2f8bff", "#1a3fb8"])
    norm_agua = Normalize(vmin=float(umbral_vis), vmax=max(float(esc["l_ref_mm"]), float(umbral_vis) + 1.0))
    sm = ScalarMappable(norm=norm_agua, cmap=cmap_agua)
    sm.set_array([])
    cax = fig.add_axes([0.885, 0.22, 0.018, 0.54])
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label("Depth (mm)", color="#dce6f2", fontsize=9)
    cb.ax.yaxis.set_tick_params(color="#9bb3cc", labelcolor="#dce6f2", labelsize=8)
    cb.outline.set_edgecolor("#263b54")

    fig.canvas.draw()
    rgba_buf = np.asarray(fig.canvas.buffer_rgba())
    img = Image.fromarray(rgba_buf[:, :, :3], mode="RGB")
    plt.close(fig)

    img = _decorar_hud_pil(
        img, paso_info, total_pasos, exag_z, esc["dz_terreno"],
        fecha_s2_txt=fecha_s2_txt, cam_elev=cam_elev, cam_azim=cam_azim,
    )
    return img


def generar_gif_timelapse_3d(dem, mascara, campo_color, anclas_color, secuencia, res, exag_z, exag_agua,
                             umbral_vis, recortar=True, rgb_textura=None, red_drenaje=None, bounds=None,
                             duracion_ms=700, alta_definicion=True, fecha_s2_txt=None,
                             cam_elev=27.0, cam_azim=45.0, cam_dist=2.05, cam_center=None):
    """
    Builds on demand the animated GIF of the 3D timelapse replicating the interactive 3D model above
    with exactly the same camera angle (cam_elev, cam_azim, cam_dist, cam_center) and exaggeration level (exag_z).
    """
    import io
    from PIL import Image
    from .map_utils import colorear

    if not secuencia:
        raise ValueError("No timelapse steps are available to generate the GIF.")

    lam_ref_seq = max([float(s["lamina_max_mm"]) for s in secuencia] + [10.0])

    if rgb_textura is not None and rgb_textura.ndim == 3:
        rgb_base = rgb_textura
    else:
        v_ok = campo_color[np.isfinite(campo_color)]
        vmin = float(v_ok.min()) if v_ok.size else 0.0
        vmax = float(v_ok.max()) if v_ok.size else 1.0
        rgb_base = colorear(campo_color, vmin, vmax, anclas_color, 1.0)[:, :, :3]

    tam = (1120, 680) if alta_definicion else (920, 560)
    ng_max = 135 if alta_definicion else 105
    total_pasos = len(secuencia)

    cuadros_rgb = []
    for s_info in secuencia:
        im_rgb = _render_cuadro_3d_matplotlib(
            dem, s_info["lamina"], mascara, rgb_base, s_info, total_pasos, res,
            exag_z, exag_agua, umbral_vis, lam_ref_seq,
            recortar=recortar, red_drenaje=red_drenaje, bounds=bounds,
            fecha_s2_txt=fecha_s2_txt, tamaño=tam, ng_max=ng_max,
            cam_elev=cam_elev, cam_azim=cam_azim, cam_dist=cam_dist, cam_center=cam_center,
        )
        cuadros_rgb.append(im_rgb)

    # Build a master palette from the peak frame (Step 4) so that the Sentinel-2 texture
    # and the water scale keep uniform photographic colours without flicker between frames
    idx_ref = min(3, len(cuadros_rgb) - 1)
    paleta_maestra = cuadros_rgb[idx_ref].quantize(colors=256, method=Image.MEDIANCUT)
    cuadros_q = [
        im.quantize(colors=256, palette=paleta_maestra, dither=Image.Dither.FLOYDSTEINBERG)
        for im in cuadros_rgb
    ]

    buf = io.BytesIO()
    cuadros_q[0].save(
        buf, format="GIF", save_all=True, append_images=cuadros_q[1:],
        duration=int(duracion_ms), loop=0, optimize=False,
    )
    return buf.getvalue()


def fig_balance_evento(b):
    """Hydro-pedological split of the precipitation and event inputs."""
    etiquetas = [
        "Interception",
        "Direct runoff",
        "Soil recharge (up to FC)",
        "Deep percolation (Ksat_min)",
        "Subsurface flow (interflow)",
        "Grav. storage",
        "Saturation excess / Exfiltration",
        "Capillary rise (water table)",
    ]
    vals = [
        b["interceptacion"],
        b["escorrentia"],
        b["humedad_suelo"],
        b["drenaje_profundo"],
        b.get("flujo_subsuperficial", 0.0),
        b["almac_gravitacional"],
        b["exceso_saturacion"],
        b.get("ascenso_capilar", 0.0),
    ]
    colores = ["#7fc97f", "#ff9f43", "#2f9bff", "#7a5cff", "#00b4d8", "#38c6c6", "#ff6b6b", "#ffd166"]
    if b.get("aporte_cuenca_mm", 0.0) > 0.05:
        etiquetas.append("External basin inflow")
        vals.append(b["aporte_cuenca_mm"])
        colores.append("#4cc9f0")
    fig = go.Figure(go.Bar(x=vals, y=etiquetas, orientation="h",
                           marker_color=colores,
                           text=[f"{v:.1f}" for v in vals], textposition="auto"))
    fig.update_layout(**_LAYOUT, height=400, title=f"Event partition (P = {b['precipitacion']:.1f} mm)",
                      xaxis_title="mm (AOI mean)", yaxis=dict(autorange="reversed"))
    return fig


def fig_timelapse(secuencia, paso_actual=4):
    """Chronological evolution (timelapse) of surface depth, infiltration and soil moisture."""
    etq = [f"P{s['paso']}" for s in secuencia]
    textos = [s["etiqueta"] for s in secuencia]
    lam_max = [s["lamina_max_mm"] for s in secuencia]
    lam_med = [s["lamina_media_mm"] for s in secuencia]
    hum_pct = [s["humedad_media_pct"] for s in secuencia]
    inf_ac = [s["infiltracion_acum_mm"] for s in secuencia]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=etq, y=lam_max, name="Max. depth in low areas (mm)", marker_color="rgba(47,155,255,0.45)",
               customdata=textos, hovertemplate="%{customdata}<br>Max. depth: %{y:.1f} mm<extra></extra>"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=etq, y=lam_med, name="Mean depth (mm)", mode="lines+markers",
                   line=dict(color="#2f9bff", width=2.5)),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=etq, y=inf_ac, name="Cumulative infiltration (mm)", mode="lines+markers",
                   line=dict(color="#38c6c6", width=2, dash="dot")),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=etq, y=hum_pct, name="Soil moisture (% AWC)", mode="lines+markers",
                   line=dict(color="#2fd4a7", width=2.5)),
        secondary_y=True,
    )
    idx_sel = max(0, min(int(paso_actual) - 1, len(etq) - 1))
    fig.add_vline(x=idx_sel, line_width=2, line_dash="dash", line_color="#ffb703")
    fig.update_layout(
        **_LAYOUT, height=340,
        title=f"Time sequence (Timelapse) — Active: {secuencia[idx_sel]['etiqueta']}",
        legend=dict(orientation="h", y=-0.22),
    )
    fig.update_yaxes(title_text="Depth / Infiltration (mm)", secondary_y=False)
    fig.update_yaxes(title_text="Profile moisture (% AWC)", range=[0, 108], secondary_y=True)
    return fig


def fig_balance_diario(df):
    """Precipitation, ETc/ETa and soil storage (% of AWC)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=df["fecha"], y=df["precip"], name="Precipitation (mm)", marker_color="#2f9bff"))
    fig.add_trace(go.Scatter(x=df["fecha"], y=df["eta"], name="ETa (mm)", line=dict(color="#ffb703")))
    fig.add_trace(go.Scatter(x=df["fecha"], y=df["almacen_pct"], name="Available water (% AWC)",
                             line=dict(color="#2fd4a7", width=2)), secondary_y=True)
    fig.update_layout(**_LAYOUT, height=380, title="Daily soil water balance (bucket)",
                      legend=dict(orientation="h", y=-0.2))
    fig.update_yaxes(title_text="mm/day", secondary_y=False)
    fig.update_yaxes(title_text="% AWC", range=[0, 105], secondary_y=True)
    return fig


def fig_selector_eventos_chirps(df, fecha_sel=None, f_ini_ev=None, f_fin_ev=None):
    """
    Interactive bar chart of historical CHIRPS precipitation (02_Climatic_Analyzer style),
    visually highlighting storm peaks and the selected event.
    Allows clicking directly on any bar to select that storm.
    """
    df_p = df.copy().sort_values("fecha").reset_index(drop=True)
    p = df_p["p_chirps"].fillna(df_p["p_era5"]).fillna(0.0)
    df_p["p_mm"] = p
    fechas_str = df_p["fecha"].dt.strftime("%Y-%m-%d")

    # Identify the top-5 rainfall threshold to highlight them in orange (#ff9f43)
    p_pos = p[p > 1.0]
    umbral_top = float(p_pos.nlargest(5).min()) if len(p_pos) >= 5 else float(p.max())
    f_sel_str = pd.to_datetime(fecha_sel).strftime("%Y-%m-%d") if fecha_sel is not None else None
    t_ini = pd.to_datetime(f_ini_ev) if f_ini_ev is not None else None
    t_fin = pd.to_datetime(f_fin_ev) if f_fin_ev is not None else None

    colores = []
    for f_dt, f_s, val in zip(df_p["fecha"], fechas_str, p):
        if f_sel_str and f_s == f_sel_str:
            colores.append("#2fd4a7")  # Peak of the selected event
        elif t_ini is not None and t_fin is not None and (t_ini <= f_dt <= t_fin) and val > 0.5:
            colores.append("#00e5ff")  # Contiguous days of the same storm
        elif val >= umbral_top and val > 5.0:
            colores.append("#ff9f43")  # Top storms of the period
        else:
            colores.append("#4da6ff")  # Standard daily rain (Climate Analyzer style)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=fechas_str,
            y=df_p["p_mm"],
            name="CHIRPS precipitation (mm/day)",
            marker_color=colores,
            opacity=0.88,
            customdata=fechas_str,
            hovertemplate="<b>Date: %{x}</b><br>Precipitation: <b>%{y:.1f} mm</b><br><i>Click to select this event</i><extra></extra>",
        ),
        secondary_y=False,
    )

    if "t2m" in df_p and df_p["t2m"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=fechas_str,
                y=df_p["t2m"],
                name="Mean T (°C)",
                mode="lines",
                line=dict(color="#ee5a24", width=1.4, dash="dot"),
                hoverinfo="skip",
            ),
            secondary_y=True,
        )

    # Annotation on the selected event
    if f_sel_str and (fechas_str == f_sel_str).any():
        v_sel = float(df_p.loc[fechas_str == f_sel_str, "p_mm"].iloc[0])
        fig.add_annotation(
            x=f_sel_str, y=v_sel,
            text=f"🎯 {f_sel_str}<br><b>{v_sel:.1f} mm</b>",
            showarrow=True, arrowhead=2, arrowcolor="#2fd4a7",
            bgcolor="rgba(13,21,32,0.92)", bordercolor="#2fd4a7",
            font=dict(color="#e8f1fb", size=11), ax=0, ay=-36,
        )

    fig.update_layout(
        title=dict(
            text="🌧️ CHIRPS Daily Precipitation Historical Series — Click on a bar (or use the selector) to choose a storm",
            font_size=13, x=0.01, font_color="#e8f1fb",
        ),
        height=310,
        margin=dict(l=12, r=12, t=42, b=12),
        paper_bgcolor="#0d1520",
        plot_bgcolor="#0d1520",
        font_color="#e8f1fb",
        barmode="overlay",
        clickmode="event+select",
        dragmode="zoom",
        legend=dict(orientation="h", y=-0.24, font_size=11),
        xaxis=dict(gridcolor="#1e2d42", tickfont_size=10, color="#7a99b8"),
        yaxis=dict(gridcolor="#1e2d42", tickfont_size=10, color="#7a99b8", title="Precipitation (mm)"),
        yaxis2=dict(gridcolor="#1e2d42", tickfont_size=10, color="#ee5a24", title="°C", showgrid=False),
    )
    return fig


def fig_hietograma_evento(det):
    """
    Chart of the hourly intensity hyetograph (mm/h) and cumulative rainfall curve (mm)
    for the selected historical event (ERA5-Land Hourly + CHIRPS).
    """
    df_h = det["df"]
    etq_h = df_h["fecha_hora"].dt.strftime("%m-%d %H:%M")
    p_h = df_h["p_mm_h"]
    i_max = float(p_h.max()) if not p_h.empty else 0.0
    colores = ["#ff6b6b" if (v >= i_max and v > 0) else ("#4da6ff" if v >= 0.15 else "#263b54") for v in p_h]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=etq_h, y=p_h,
            name="Hourly intensity (mm/h)",
            marker_color=colores, opacity=0.88,
            hovertemplate="<b>%{x} UTC</b><br>Intensity: <b>%{y:.2f} mm/h</b><extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=etq_h, y=df_h["p_acum_mm"],
            name="Storm cumulative (mm)",
            mode="lines",
            fill="tozeroy", fillcolor="rgba(47,212,167,0.14)",
            line=dict(color="#2fd4a7", width=2.4),
            hovertemplate="<b>%{x} UTC</b><br>Cumulative: <b>%{y:.1f} mm</b><extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_layout(
        title=dict(
            text=(
                f"⏱️ Event Hourly Hyetograph ({det['fecha_inicio']} → {det['fecha_fin']}) · "
                f"Total: {det['p_total_mm']:.1f} mm · Effective duration: {det['duracion_real_h']} h · "
                f"Imax: {det['intensidad_max_mmh']:.1f} mm/h"
            ),
            font_size=12, x=0.01, font_color="#e8f1fb",
        ),
        height=265,
        margin=dict(l=12, r=12, t=38, b=12),
        paper_bgcolor="#0d1520",
        plot_bgcolor="#0d1520",
        font_color="#e8f1fb",
        legend=dict(orientation="h", y=-0.26, font_size=11),
        xaxis=dict(gridcolor="#1e2d42", tickfont_size=10, color="#7a99b8"),
        yaxis=dict(gridcolor="#1e2d42", tickfont_size=10, color="#4da6ff", title="Intensity (mm/h)"),
        yaxis2=dict(gridcolor="#1e2d42", tickfont_size=10, color="#2fd4a7", title="Cumulative (mm)", showgrid=False),
    )
    return fig


def fig_clima(df):
    """Daily P (CHIRPS/ERA5), cumulative P and temperatures (T max, T mean and T min) with dual °C (left) and °F (right) axes."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.56, 0.44], vertical_spacing=0.07,
        specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
        subplot_titles=("Daily and cumulative precipitation (mm)", "Daily temperature at 2 m (°C / °F)"),
    )
    fig.add_trace(go.Bar(x=df["fecha"], y=df["p_chirps"], name="CHIRPS (mm)", marker_color="#2f9bff"), 1, 1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df["fecha"], y=df["p_era5"], name="ERA5-Land (mm)",
                             line=dict(color="#ffb703", width=1)), 1, 1, secondary_y=False)
    acum = df["p_chirps"].fillna(df["p_era5"]).fillna(0).cumsum()
    fig.add_trace(go.Scatter(x=df["fecha"], y=acum, name="Cumulative P", line=dict(color="#2fd4a7", dash="dot")),
                  1, 1, secondary_y=True)

    t_med_c = df["t2m"]
    t_max_c = df["t_max"] if ("t_max" in df.columns and df["t_max"].notna().any()) else t_med_c
    t_min_c = df["t_min"] if ("t_min" in df.columns and df["t_min"].notna().any()) else t_med_c

    t_max_f = t_max_c * 1.8 + 32.0
    t_med_f = t_med_c * 1.8 + 32.0
    t_min_f = t_min_c * 1.8 + 32.0

    if "t_max" in df.columns and df["t_max"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df["fecha"], y=t_max_c, customdata=t_max_f,
                name="T max (°C)", line=dict(color="#ff6b6b", width=1.4),
                hovertemplate="<b>%{x|%Y-%m-%d}</b><br>T max: <b>%{y:.1f} °C</b> (%{customdata:.1f} °F)<extra></extra>",
            ),
            2, 1, secondary_y=False,
        )
    fig.add_trace(
        go.Scatter(
            x=df["fecha"], y=t_med_c, customdata=t_med_f,
            name="T mean (°C)", line=dict(color="#ffb703", width=2.1),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>T mean: <b>%{y:.1f} °C</b> (%{customdata:.1f} °F)<extra></extra>",
        ),
        2, 1, secondary_y=False,
    )
    if "t_min" in df.columns and df["t_min"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df["fecha"], y=t_min_c, customdata=t_min_f,
                name="T min (°C)", line=dict(color="#5aa9ff", width=1.4),
                hovertemplate="<b>%{x|%Y-%m-%d}</b><br>T min: <b>%{y:.1f} °C</b> (%{customdata:.1f} °F)<extra></extra>",
            ),
            2, 1, secondary_y=False,
        )
    # Invisible auxiliary trace in °F to activate and synchronize the right Y axis in °F
    fig.add_trace(
        go.Scatter(
            x=df["fecha"], y=t_med_f, name="T (°F)",
            mode="lines", line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        ),
        2, 1, secondary_y=True,
    )

    vals_t = pd.concat([t_min_c, t_med_c, t_max_c]).dropna()
    c_min = float(np.floor(vals_t.min() - 2.0)) if not vals_t.empty else -5.0
    c_max = float(np.ceil(vals_t.max() + 2.0)) if not vals_t.empty else 35.0
    f_min = c_min * 1.8 + 32.0
    f_max = c_max * 1.8 + 32.0

    fig.update_layout(**_LAYOUT, height=560, title="Daily climate forcing", legend=dict(orientation="h", y=-0.12))
    fig.update_yaxes(title_text="mm/day", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Cumul. (mm)", row=1, col=1, secondary_y=True, showgrid=False)
    fig.update_yaxes(title_text="Temperature (°C)", range=[c_min, c_max], row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Temperature (°F)", range=[f_min, f_max], row=2, col=1, secondary_y=True, showgrid=False)
    return fig


def fig_indices(df):
    """Time series of NDVI, NDWI, SAVI and LAI (secondary axis)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for col, color in (("NDVI", "#2fd4a7"), ("NDWI", "#2f9bff"), ("SAVI", "#d9a441")):
        fig.add_trace(go.Scatter(x=df["fecha"], y=df[col], name=col, mode="lines+markers",
                                 line=dict(color=color)))
    fig.add_trace(go.Scatter(x=df["fecha"], y=df["LAI"], name="LAI", mode="lines",
                             line=dict(color="#b388ff", dash="dot")), secondary_y=True)
    fig.update_layout(**_LAYOUT, height=380, title="Sentinel-2 indices (AOI mean)", legend=dict(orientation="h", y=-0.2))
    fig.update_yaxes(title_text="Index", secondary_y=False)
    fig.update_yaxes(title_text="LAI", secondary_y=True)
    return fig


def fig_perfil(h):
    """Horizon profile: texture (sand/silt/clay %) + Ksat (mm/h) and total porosity (%)."""
    h = h.dropna(subset=["hzdept_r", "hzdepb_r"]).sort_values("hzdept_r").copy()
    etq = [f"{r.get('hzname', 'Hz')} ({int(a)}–{int(b)} cm)" for (_, r), a, b in zip(h.iterrows(), h["hzdept_r"], h["hzdepb_r"])]
    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.08,
        column_widths=[0.58, 0.42],
        subplot_titles=("Texture (% by weight)", "Ksat conductivity (mm/h) and Porosity (%)"),
    )
    for col, nom, color in (("sandtotal_r", "Sand", "#e9c46a"), ("silttotal_r", "Silt", "#8ab17d"),
                            ("claytotal_r", "Clay", "#e76f51")):
        fig.add_trace(go.Bar(y=etq, x=h[col], name=nom, orientation="h", marker_color=color), row=1, col=1)

    ksat_vals = h["ksat_mmh"] if "ksat_mmh" in h.columns else (h["ksat_r"].fillna(3.0) * 3.6)
    por_vals = h["porosidad_pct"] if "porosidad_pct" in h.columns else ((1.0 - h["dbthirdbar_r"].fillna(1.4) / 2.65) * 100.0)
    fig.add_trace(
        go.Bar(y=etq, x=ksat_vals, name="Ksat (mm/h)", orientation="h", marker_color="#2f9bff",
               text=[f"{v:.1f} mm/h" for v in ksat_vals], textposition="auto"),
        row=1, col=2,
    )
    fig.add_trace(
        go.Scatter(y=etq, x=por_vals, name="Total porosity (%)", mode="lines+markers",
                   line=dict(color="#2fd4a7", width=2.5), marker=dict(size=8)),
        row=1, col=2,
    )
    fig.update_layout(**_LAYOUT, barmode="stack", height=390,
                      title="Soil profile by horizon (texture, Ksat and porosity)",
                      legend=dict(orientation="h", y=-0.22))
    fig.update_xaxes(title_text="% Texture", row=1, col=1)
    fig.update_xaxes(title_text="Ksat (mm/h) / Porosity (%)", row=1, col=2)
    fig.update_yaxes(autorange="reversed", row=1, col=1)
    return fig
