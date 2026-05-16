"""
Tab 3 — 3D Topographic Projection
  • Plotly Surface with earth colorscale (fast)
  • Plotly Mesh3d draped with Esri World Imagery satellite texture
  • Field boundary perimeter drawn on both 3D figures
  • Vertical exaggeration slider with help tooltip
  • Downloads: interactive HTML, PNG
"""
import io
import warnings

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from utils.dem import download_dem, download_satellite_texture
from utils.export import fig_to_html_bytes

warnings.filterwarnings("ignore")


# ── Perimeter helper ───────────────────────────────────────────────────────

def _perimeter_trace(geom_shp, elevation, x_coords, y_coords, exag, label="Field boundary"):
    """
    Returns a Plotly Scatter3d trace that draws the field boundary
    draped on the DEM surface at the correct elevation.
    """
    from shapely.geometry import mapping
    import json

    def _interp_elev(lon, lat):
        """Bilinear elevation lookup for a (lon, lat) point."""
        H, W = elevation.shape
        xi = np.interp(lon, x_coords, np.arange(W))
        yi = np.interp(lat, y_coords[::-1], np.arange(H))
        xi_c, yi_c = int(np.clip(xi, 0, W - 1)), int(np.clip(yi, 0, H - 1))
        return float(elevation[yi_c, xi_c]) * exag

    geojson = mapping(geom_shp)
    coords_list = []
    if geojson["type"] == "Polygon":
        rings = [geojson["coordinates"][0]]
    elif geojson["type"] == "MultiPolygon":
        rings = [poly[0] for poly in geojson["coordinates"]]
    else:
        return None

    xs, ys, zs = [], [], []
    for ring in rings:
        for lon, lat in ring:
            xs.append(lon)
            ys.append(lat)
            zs.append(_interp_elev(lon, lat) + 2)  # small offset so it's visible
        xs.append(None); ys.append(None); zs.append(None)

    return go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(color="#00ff88", width=5),
        name=label,
        hoverinfo="skip",
    )


# ── Surface figure ─────────────────────────────────────────────────────────

def _fig_surface(elevation, x_coords, y_coords, exag, geom_shp=None):
    traces = [go.Surface(
        z=elevation * exag,
        x=x_coords,
        y=y_coords[::-1],
        colorscale="earth",
        colorbar=dict(title="Elevation (m)", thickness=20),
        hovertemplate="Lon: %{x:.4f}<br>Lat: %{y:.4f}<br>Alt: %{customdata:.1f} m<extra></extra>",
        customdata=elevation,
    )]

    if geom_shp is not None:
        perim = _perimeter_trace(geom_shp, elevation, x_coords, y_coords, exag)
        if perim is not None:
            traces.append(perim)

    fig = go.Figure(data=traces)
    fig.update_layout(
        title="3D Topographic Surface",
        scene=dict(
            xaxis_title="Longitude",
            yaxis_title="Latitude",
            zaxis_title="Elevation (m)",
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=0.3),
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.2)),
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        template="plotly_dark",
        height=620,
    )
    return fig


# ── Satellite mesh figure ──────────────────────────────────────────────────

def _fig_satellite_3d(elevation, x_coords, y_coords, texture_img, exag, geom_shp=None):
    from PIL import Image

    tex_h, tex_w = texture_img.shape[:2]
    el_h, el_w   = elevation.shape
    if tex_h != el_h or tex_w != el_w:
        pil_img     = Image.fromarray(texture_img)
        pil_img     = pil_img.resize((el_w, el_h), Image.LANCZOS)
        texture_img = np.array(pil_img)

    X, Y   = np.meshgrid(x_coords, y_coords[::-1])
    x_f    = X.flatten()
    y_f    = Y.flatten()
    z_f    = (elevation * exag).flatten()
    colors = [f"rgb({r},{g},{b})" for r, g, b in texture_img.reshape(-1, 3)]

    rows, cols = elevation.shape
    i_idx, j_idx, k_idx = [], [], []
    for r in range(rows - 1):
        for c in range(cols - 1):
            v1 = r * cols + c;  v2 = r * cols + (c + 1)
            v3 = (r + 1) * cols + c;  v4 = (r + 1) * cols + (c + 1)
            i_idx.extend([v1, v2]); j_idx.extend([v2, v4]); k_idx.extend([v3, v3])

    traces = [go.Mesh3d(
        x=x_f, y=y_f, z=z_f,
        i=i_idx, j=j_idx, k=k_idx,
        customdata=elevation.flatten(),
        vertexcolor=colors,
        lighting=dict(ambient=0.6, diffuse=0.8, roughness=0.9, specular=0.1),
        hovertemplate="<b>Elevation:</b> %{customdata:.2f} m<extra></extra>",
    )]

    if geom_shp is not None:
        perim = _perimeter_trace(geom_shp, elevation, x_coords, y_coords, exag)
        if perim is not None:
            traces.append(perim)

    fig = go.Figure(data=traces)
    fig.update_layout(
        title="3D Digital Model — Esri World Imagery Texture",
        scene=dict(
            xaxis_visible=True, yaxis_visible=True,
            zaxis=dict(title="Elevation (m)", backgroundcolor="rgb(20,20,30)"),
            aspectratio=dict(x=1, y=1, z=0.15),
            bgcolor="rgb(10,10,15)",
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        template="plotly_dark",
        height=640,
    )
    return fig


# ── Main render ────────────────────────────────────────────────────────────

def render(state: dict):
    st.header("🌐 3D Topographic Projection")

    # Support multiple AOIs
    field_geoms = state.get("field_geoms")
    if field_geoms:
        from shapely.ops import unary_union
        import geopandas as gpd
        if len(field_geoms) > 1:
            sel = st.selectbox(
                "Field to visualise",
                [f[0] for f in field_geoms] + ["— All combined —"],
                key="3d_field_sel",
            )
            if sel == "— All combined —":
                geom_shp  = unary_union([f[1] for f in field_geoms])
                gdf_field = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[geom_shp])
            else:
                f = next(x for x in field_geoms if x[0] == sel)
                geom_shp, gdf_field = f[1], f[2]
        else:
            geom_shp, gdf_field = field_geoms[0][1], field_geoms[0][2]
    else:
        geom_shp  = state.get("field_geom_shp")
        gdf_field = state.get("gdf_field")

    if geom_shp is None:
        st.warning("⚠️ Please define your AOI in the **AOI** tab first.")
        return

    # ── Controls ───────────────────────────────────────────────────────────
    col_ctrl, col_view = st.columns([1, 3])

    with col_ctrl:
        zoom_level = st.slider(
            "Tile zoom level", 12, 16, 14, key="3d_zoom",
            help=(
                "Resolution of the elevation (DEM) tiles from AWS Terrarium.\n\n"
                "**12** = ~38 m/px, very fast.\n"
                "**14** = ~9 m/px, recommended balance.\n"
                "**16** = ~2 m/px, very detailed but slow — many tiles to download."
            ),
        )
        exag = st.slider(
            "Vertical exaggeration", 1.0, 10.0, 1.5, step=0.25, key="3d_exag",
            help=(
                "Multiplier applied to the Z (elevation) axis.\n\n"
                "**1.0** = true-to-scale (flat terrain looks flat).\n"
                "**3–5** = recommended for gentle agricultural slopes.\n"
                "**8–10** = useful to highlight very subtle micro-relief.\n\n"
                "Note: this does not change real elevations, only the visual appearance."
            ),
        )
        mode = st.radio(
            "3D mode",
            ["🌍 Surface (fast)", "🛰️ Satellite texture (slow)"],
            key="3d_mode",
        )
        btn_render = st.button("🚀 Render 3D Model", key="btn_render_3d", type="primary")

    dem_key = f"{geom_shp.bounds}_{zoom_level}"

    if btn_render:
        progress = st.progress(0, text="Downloading elevation tiles…")
        try:
            elevation, x_coords, y_coords, tile_info = download_dem(
                geom_shp, zoom=zoom_level,
                progress_cb=lambda p: progress.progress(p, text=f"DEM tiles: {int(p*100)}%"),
            )
            state.update(elevation_3d=elevation, x_coords_3d=x_coords,
                         y_coords_3d=y_coords, tile_info_3d=tile_info, dem_key_3d=dem_key)
            state.pop("texture_img", None)
            progress.empty()
        except Exception as e:
            st.error(f"DEM download error: {e}")
            return

    if "elevation_3d" not in state:
        with col_view:
            st.info("👈 Configure settings and click **Render 3D Model** to start.")
        return

    elevation = state["elevation_3d"]
    x_coords  = state["x_coords_3d"]
    y_coords  = state["y_coords_3d"]
    tile_info = state["tile_info_3d"]

    with col_ctrl:
        st.metric("Grid size",       f"{elevation.shape[1]} × {elevation.shape[0]} px")
        st.metric("Elevation range", f"{elevation.min():.1f} – {elevation.max():.1f} m")
        st.caption("🟩 Green line = field boundary")

    with col_view:
        if "Surface" in mode:
            st.subheader("🌍 Surface — Earth Colorscale")
            with st.spinner("Rendering surface…"):
                fig = _fig_surface(elevation, x_coords, y_coords, exag, geom_shp=geom_shp)
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### ⬇️ Download")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥 Interactive HTML", fig_to_html_bytes(fig),
                                   "surface_3d.html", "text/html")
            with c2:
                try:
                    img_bytes = fig.to_image(format="png", width=1400, height=700)
                    st.download_button("📥 PNG", img_bytes, "surface_3d.png", "image/png")
                except Exception:
                    st.info("Install kaleido for PNG export: `pip install kaleido`")

        else:
            st.subheader("🛰️ 3D Model — Satellite Imagery Texture")

            if "texture_img" not in state or state.get("dem_key_3d") != dem_key:
                if st.button("📥 Download Satellite Texture", key="btn_texture"):
                    progress2 = st.progress(0, text="Downloading satellite tiles…")
                    try:
                        texture_img = download_satellite_texture(
                            tile_info,
                            progress_cb=lambda p: progress2.progress(
                                p, text=f"Satellite tiles: {int(p*100)}%"
                            ),
                        )
                        state["texture_img"] = texture_img
                        progress2.empty()
                        st.success("✅ Satellite texture loaded!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Texture download error: {e}")
                        return
                else:
                    st.info("Click **Download Satellite Texture** to fetch Esri World Imagery tiles.")
                    return

            texture_img = state["texture_img"]
            with st.spinner("Building 3D mesh with satellite texture…"):
                el_h, el_w = elevation.shape
                if el_h * el_w > 150_000:
                    factor      = max(1, int(np.sqrt(el_h * el_w / 100_000)))
                    elevation_ds = elevation[::factor, ::factor]
                    x_ds        = x_coords[::factor]
                    y_ds        = y_coords[::factor]
                    from PIL import Image as PILImage
                    pil = PILImage.fromarray(texture_img)
                    pil = pil.resize((elevation_ds.shape[1], elevation_ds.shape[0]), PILImage.LANCZOS)
                    texture_ds = np.array(pil)
                    st.caption(
                        f"ℹ️ Grid downsampled {factor}× for performance "
                        f"({elevation_ds.shape[1]}×{elevation_ds.shape[0]} pts)"
                    )
                else:
                    elevation_ds = elevation; x_ds = x_coords; y_ds = y_coords; texture_ds = texture_img

                fig_sat = _fig_satellite_3d(
                    elevation_ds, x_ds, y_ds, texture_ds, exag, geom_shp=geom_shp
                )

            st.plotly_chart(fig_sat, use_container_width=True)

            st.markdown("#### ⬇️ Download")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥 Interactive HTML", fig_to_html_bytes(fig_sat),
                                   "satellite_3d.html", "text/html")
            with c2:
                try:
                    img_bytes = fig_sat.to_image(format="png", width=1400, height=700)
                    st.download_button("📥 PNG", img_bytes, "satellite_3d.png", "image/png")
                except Exception:
                    st.info("Install kaleido for PNG export.")
