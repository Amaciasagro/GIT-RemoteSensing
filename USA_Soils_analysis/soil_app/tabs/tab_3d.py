"""
Tab 3 — 3D Topographic Model
Actualizado: Incluye dibujo del contorno del lote sobre el relieve 3D.
"""
import io
import warnings
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from utils.dem import download_dem, download_satellite_texture
from utils.export import fig_to_html_bytes
from shapely.geometry import shape

warnings.filterwarnings("ignore")

def _add_aoi_boundary(fig, state, elevation, x_coords, y_coords, exag):
    """Calcula y agrega el contorno del lote sobre la superficie 3D."""
    try:
        geom = shape(state['field_geom_shp'])
        if geom.geom_type == 'Polygon':
            x_line, y_line = geom.exterior.xy
        else:
            x_line, y_line = max(geom.geoms, key=lambda p: p.area).exterior.xy
        
        # Proyectar el contorno sobre la matriz de elevación
        z_line = []
        for lon, lat in zip(x_line, y_line):
            # Encontrar el índice más cercano en la matriz de elevación
            ix = np.abs(x_coords - lon).argmin()
            iy = np.abs(y_coords - lat).argmin()
            # Le sumamos un pequeño offset para que la línea no se hunda
            z_val = elevation[iy, ix] * exag + 0.8
            z_line.append(z_val)
            
        fig.add_trace(go.Scatter3d(
            x=list(x_line), y=list(y_line), z=z_line,
            mode='lines',
            line=dict(color='yellow', width=8),
            name='Límite del Lote',
            hoverinfo='name'
        ))
    except Exception as e:
        st.sidebar.error(f"Error al dibujar contorno: {e}")
    return fig

def _fig_surface(elevation, x_coords, y_coords, exag=1.5):
    fig = go.Figure(data=[go.Surface(
        z=elevation * exag,
        x=x_coords,
        y=y_coords[::-1],
        colorscale="earth",
        colorbar=dict(title="Elevation (m)", thickness=20),
        hovertemplate="Lon: %{x:.4f}<br>Lat: %{y:.4f}<br>Alt: %{z:.1f} m<extra></extra>",
    )])
    fig.update_layout(
        scene=dict(
            xaxis_title="Longitude", yaxis_title="Latitude", zaxis_title="Elevation (m)",
            aspectmode="manual", aspectratio=dict(x=1, y=1, z=0.3),
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.2)),
        ),
        margin=dict(l=0, r=0, b=0, t=40), template="plotly_dark", height=600,
    )
    return fig

def _fig_satellite_3d(elevation, x_coords, y_coords, texture_img, exag=1.5):
    from PIL import Image
    tex_h, tex_w = texture_img.shape[:2]
    el_h, el_w = elevation.shape
    if tex_h != el_h or tex_w != el_w:
        pil_img = Image.fromarray(texture_img)
        pil_img = pil_img.resize((el_w, el_h), Image.LANCZOS)
        texture_img = np.array(pil_img)

    X, Y = np.meshgrid(x_coords, y_coords[::-1])
    x_f, y_f = X.flatten(), Y.flatten()
    z_f = (elevation * exag).flatten()
    color_strings = [f"rgb({r},{g},{b})" for r, g, b in texture_img.reshape(-1, 3)]

    rows, cols = elevation.shape
    i_idx, j_idx, k_idx = [], [], []
    for r in range(rows - 1):
        for c in range(cols - 1):
            v1, v2 = r * cols + c, r * cols + (c + 1)
            v3, v4 = (r + 1) * cols + c, (r + 1) * cols + (c + 1)
            i_idx.extend([v1, v2]); j_idx.extend([v2, v4]); k_idx.extend([v3, v3])

    fig = go.Figure(data=[go.Mesh3d(
        x=x_f, y=y_f, z=z_f, i=i_idx, j=j_idx, k=k_idx,
        customdata=elevation.flatten(), vertexcolor=color_strings,
        lighting=dict(ambient=0.6, diffuse=0.8, roughness=0.9, specular=0.1),
        hovertemplate="<b>Elevation:</b> %{customdata:.2f} m<extra></extra>",
    )])
    fig.update_layout(
        scene=dict(
            zaxis=dict(title="Elevation (m)", backgroundcolor="rgb(20,20,30)"),
            aspectratio=dict(x=1, y=1, z=0.15), bgcolor="rgb(10,10,15)",
        ),
        margin=dict(l=0, r=0, b=0, t=40), template="plotly_dark", height=620,
    )
    return fig

def render(state: dict):
    st.header("🌐 3D Topographic Projection")
    geom_shp = state.get("field_geom_shp")
    if geom_shp is None:
        st.warning("⚠️ Please define your AOI in the **AOI** tab first.")
        return

    col_ctrl, col_view = st.columns([1, 3])
    with col_ctrl:
        zoom_level = st.slider("Tile zoom level", 12, 16, 14, key="3d_zoom")
        exag = st.slider("Vertical exaggeration", 1.0, 5.0, 1.5, step=0.25, key="3d_exag")
        mode = st.radio("3D mode", ["🌍 Surface (fast)", "🛰️ Satellite texture (slow)"], key="3d_mode")
        btn_render = st.button("🚀 Render 3D Model", key="btn_render_3d", type="primary")

    dem_key = f"{geom_shp.bounds}_{zoom_level}"
    if btn_render:
        with st.spinner("📥 Downloading elevation tiles..."):
            progress = st.progress(0)
            elevation, x_coords, y_coords, tile_info = download_dem(
                geom_shp, zoom=zoom_level,
                progress_cb=lambda p: progress.progress(p, text=f"DEM tiles: {int(p*100)}%"),
            )
            state.update({"elevation_3d": elevation, "x_coords_3d": x_coords, 
                          "y_coords_3d": y_coords, "tile_info_3d": tile_info, "dem_key_3d": dem_key})
            state.pop("texture_img", None)
            progress.empty()

    if "elevation_3d" not in state:
        with col_view: st.info("👈 Click **Render 3D Model** to start.")
        return

    el, xc, yc = state["elevation_3d"], state["x_coords_3d"], state["y_coords_3d"]

    with col_view:
        if "Surface" in mode:
            fig = _fig_surface(el, xc, yc, exag=exag)
            fig = _add_aoi_boundary(fig, state, el, xc, yc, exag)
            st.plotly_chart(fig, use_container_width=True)
        else:
            if "texture_img" not in state or state.get("dem_key_3d") != dem_key:
                if st.button("📥 Download Satellite Texture"):
                    prog = st.progress(0)
                    texture_img = download_satellite_texture(state["tile_info_3d"], 
                                   progress_cb=lambda p: prog.progress(p, text="Texture..."))
                    state["texture_img"] = texture_img
                    prog.empty(); st.rerun()
                return
            
            fig = _fig_satellite_3d(el, xc, yc, state["texture_img"], exag=exag)
            fig = _add_aoi_boundary(fig, state, el, xc, yc, exag)
            st.plotly_chart(fig, use_container_width=True)