"""Plotly charts (dark theme) shared by the modules."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_L = dict(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,28,46,.6)",
          margin=dict(l=40, r=20, t=50, b=40), font=dict(color="#dce6f2"))
COLORES = {
    "NDVI": "#2fd4a7",
    "LAI": "#1b7837",   # Dark green to clearly distinguish it from the NDVI emerald green (#2fd4a7)
    "EVI": "#7bd88f",
    "EVI2": "#ff9f43",
    "SAVI": "#d9a441",
    "NDWI": "#2f9bff",
    "NDMI": "#8f7bff",
}


def fig_clima(df, ventana=None, p_col="p_precip", t_base=None):
    """
    Daily P (CHIRPS/ERA5) + cumulative, and temperatures with:
      - Left Y axis in °C and right Y axis in °F perfectly synchronized.
      - Fixed horizontal dotted line at the Growing-Degree-Day threshold (GDD / t_base).
      - Dynamic horizontal guide line (spikeline) on the temperature axis when moving the cursor.
    """
    fechas_str = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m-%d")
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.52, 0.48], vertical_spacing=0.07,
        specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
        subplot_titles=("Daily and cumulative precipitation (mm)", "Daily temperature (°C / °F) and Growing-Degree-Day threshold (GDD)"),
    )
    fig.add_trace(
        go.Bar(
            x=fechas_str, y=df["p_chirps"], name="CHIRPS (mm)", marker_color="#2f9bff",
            hovertemplate="<b>%{x}</b><br>P CHIRPS: %{y:.1f} mm<extra></extra>",
        ),
        1, 1, secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df["p_era5"], name="ERA5-Land (mm)", line=dict(color="#ffb703", width=1.2),
            hovertemplate="<b>%{x}</b><br>P ERA5-Land: %{y:.1f} mm<extra></extra>",
        ),
        1, 1, secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df[p_col].fillna(0).cumsum(), name="Cumulative P",
            line=dict(color="#2fd4a7", dash="dot", width=2),
            hovertemplate="<b>%{x}</b><br>Cumulative P: %{y:.1f} mm<extra></extra>",
        ),
        1, 1, secondary_y=True,
    )

    t_max_f = df["t_max"] * 1.8 + 32.0
    t_med_f = df["t_media"] * 1.8 + 32.0
    t_min_f = df["t_min"] * 1.8 + 32.0

    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df["t_max"], name="T max (°C)",
            customdata=t_max_f,
            line=dict(color="#ff6b6b", width=1.4),
            hovertemplate="<b>%{x}</b><br>T max: <b>%{y:.1f} °C</b> (%{customdata:.1f} °F)<extra></extra>",
        ),
        2, 1, secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df["t_media"], name="Mean T (°C)",
            customdata=t_med_f,
            line=dict(color="#ffb703", width=2.2),
            hovertemplate="<b>%{x}</b><br>Mean T: <b>%{y:.1f} °C</b> (%{customdata:.1f} °F)<extra></extra>",
        ),
        2, 1, secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df["t_min"], name="T min (°C)",
            customdata=t_min_f,
            line=dict(color="#5aa9ff", width=1.4),
            hovertemplate="<b>%{x}</b><br>T min: <b>%{y:.1f} °C</b> (%{customdata:.1f} °F)<extra></extra>",
        ),
        2, 1, secondary_y=False,
    )
    # Invisible auxiliary trace in °F to activate and synchronize the right secondary Y axis (°F)
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=t_med_f, name="T (°F)",
            mode="lines", line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        ),
        2, 1, secondary_y=True,
    )

    # Compute a consistent temperature range to align °C (left) and °F (right) exactly
    vals_t = pd.concat([df["t_min"], df["t_media"], df["t_max"]]).dropna()
    if t_base is not None:
        vals_t = pd.concat([vals_t, pd.Series([float(t_base)])])
    c_min = float(np.floor(vals_t.min() - 2.0)) if not vals_t.empty else 0.0
    c_max = float(np.ceil(vals_t.max() + 2.0)) if not vals_t.empty else 35.0
    f_min = c_min * 1.8 + 32.0
    f_max = c_max * 1.8 + 32.0

    # Fixed horizontal dotted line at the Growing-Degree-Day (GDD) threshold
    if t_base is not None:
        tb_c = int(round(float(t_base)))
        tb_f = tb_c * 1.8 + 32.0
        fig.add_hline(
            y=float(tb_c), row=2, col=1,
            line_dash="dot", line_color="#00f5d4", line_width=2.2,
            annotation_text=f"GDD threshold: {tb_c} °C ({tb_f:.1f} °F)",
            annotation_position="top left",
            annotation_font=dict(color="#00f5d4", size=11),
            annotation_bgcolor="rgba(11,19,32,0.82)",
            secondary_y=False,
        )

    if ventana:
        v0 = pd.to_datetime(ventana[0]).strftime("%Y-%m-%d")
        v1 = pd.to_datetime(ventana[1]).strftime("%Y-%m-%d")
        fig.add_vrect(x0=v0, x1=v1, fillcolor="#2fd4a7", opacity=0.12, line_width=0)

    fig.update_layout(
        **_L,
        height=620,
        hovermode="x",
        spikedistance=-1,
        hoverdistance=100,
        legend=dict(orientation="h", y=-0.11),
        title="Daily precipitation and temperature",
    )
    fig.update_xaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikedash="dot", spikecolor="#7a99b8", spikethickness=1,
    )
    fig.update_yaxes(title_text="mm/day", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Cum. (mm)", row=1, col=1, secondary_y=True, showgrid=False)
    fig.update_yaxes(
        title_text="Temperature (°C)",
        range=[c_min, c_max],
        row=2, col=1,
        secondary_y=False,
        showspikes=True,
        spikemode="across+toaxis+marker",
        spikesnap="cursor",
        spikedash="dash",
        spikecolor="#00f5d4",
        spikethickness=1.6,
    )
    fig.update_yaxes(
        title_text="Temperature (°F)",
        range=[f_min, f_max],
        row=2, col=1,
        secondary_y=True,
        showgrid=False,
        showspikes=True,
        spikemode="across+toaxis",
        spikesnap="cursor",
        spikedash="dash",
        spikecolor="#00f5d4",
        spikethickness=1.2,
    )
    return fig


def fig_temperatura_gdd(df, t_base=10.0, ventana=None):
    """
    Dedicated daily Temperature (°C) chart with fixed Growing-Degree-Day (GDD) threshold
    and dynamic horizontal guide line (spikeline) that follows the cursor's °C value.
    """
    fechas_str = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m-%d")
    t_med_gdd = ((df["t_max"] + df["t_min"]) / 2.0).fillna(df["t_media"])
    gdd_diario = (t_med_gdd - float(t_base)).clip(lower=0.0)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=fechas_str, y=gdd_diario,
            name=f"Daily GDD (base {t_base:g} °C)",
            marker_color="rgba(47, 212, 167, 0.28)",
            hovertemplate="<b>%{x}</b><br>GDD: <b>%{y:.1f} °C·d</b><extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df["t_max"], name="T max (°C)",
            mode="lines", line=dict(color="#ff6b6b", width=1.6),
            hovertemplate="<b>%{x}</b><br>T max: <b>%{y:.1f} °C</b><extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df["t_media"], name="Mean T (°C)",
            mode="lines", line=dict(color="#ffb703", width=2.4),
            hovertemplate="<b>%{x}</b><br>Mean T: <b>%{y:.1f} °C</b><extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=fechas_str, y=df["t_min"], name="T min (°C)",
            mode="lines", line=dict(color="#5aa9ff", width=1.6),
            hovertemplate="<b>%{x}</b><br>T min: <b>%{y:.1f} °C</b><extra></extra>",
        ),
        secondary_y=False,
    )

    # Fixed horizontal dotted line at the Growing-Degree-Day (GDD) threshold
    fig.add_hline(
        y=float(t_base),
        line_dash="dot", line_color="#00f5d4", line_width=2.4,
        annotation_text=f"GDD threshold: {float(t_base):g} °C",
        annotation_position="top left",
        annotation_font=dict(color="#00f5d4", size=12),
        annotation_bgcolor="rgba(11,19,32,0.88)",
        secondary_y=False,
    )

    if ventana:
        v0 = pd.to_datetime(ventana[0]).strftime("%Y-%m-%d")
        v1 = pd.to_datetime(ventana[1]).strftime("%Y-%m-%d")
        fig.add_vrect(x0=v0, x1=v1, fillcolor="#2fd4a7", opacity=0.10, line_width=0)

    fig.update_layout(
        **_L,
        height=390,
        hovermode="closest",
        spikedistance=-1,
        hoverdistance=100,
        title=f"🌡️ Thermal Regime and Growing-Degree-Day Threshold (GDD = {float(t_base):g} °C) — Move the cursor to compare °C",
        legend=dict(orientation="h", y=-0.18),
    )
    fig.update_xaxes(
        showspikes=True, spikemode="across+toaxis", spikesnap="cursor",
        spikedash="dot", spikecolor="#7a99b8", spikethickness=1.2,
    )
    fig.update_yaxes(
        title_text="Temperature (°C)",
        showspikes=True,
        spikemode="across+toaxis+marker",
        spikesnap="cursor",
        spikedash="dash",
        spikecolor="#00f5d4",
        spikethickness=1.8,
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text="Daily GDD (°C·d)",
        showgrid=False,
        secondary_y=True,
    )
    return fig


def fig_mensual(m):
    """Monthly precipitation (bars) by source."""
    fig = go.Figure()
    for col, nom, c in (("p_chirps", "CHIRPS", "#2f9bff"), ("p_era5", "ERA5-Land", "#ffb703")):
        fig.add_trace(go.Bar(x=m["mes"], y=m[col], name=nom, marker_color=c))
    fig.update_layout(**_L, height=320, barmode="group", title="Monthly precipitation (mm)")
    return fig


def fig_indices(df, cols, fecha_seleccionada=None):
    """
    Time series of the indices selected by the user (with secondary axis for LAI)
    and vertical line marking the selected date.
    Configured with hovermode='closest' and clickmode='event+select' so that a click on
    any point directly selects that date and updates the map below.
    """
    tiene_lai = "LAI" in cols and len(cols) > 1
    fig = make_subplots(specs=[[{"secondary_y": True}]]) if tiene_lai else go.Figure()
    fechas_str = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m-%d").tolist()

    for c in cols:
        if c not in df.columns:
            continue
        es_sec = tiene_lai and (c == "LAI")
        tr = go.Scatter(
            x=fechas_str,
            y=df[c],
            name=f"{c} (m²/m²)" if c == "LAI" else c,
            mode="lines+markers",
            customdata=fechas_str,
            line=dict(color=COLORES.get(c, "#2fd4a7"), width=2.5),
            marker=dict(size=9, line=dict(width=1.2, color="#0b1320")),
            selected=dict(marker=dict(size=12)),
            unselected=dict(marker=dict(opacity=0.85)),
            hovertemplate=f"<b>Date: %{{x}}</b><br>{c}: <b>%{{y:.3f}}</b><br><i>Click the point to see this date on the map</i><extra></extra>",
        )
        if tiene_lai:
            fig.add_trace(tr, secondary_y=es_sec)
        else:
            fig.add_trace(tr)

    if fecha_seleccionada is not None:
        f_sel_str = pd.to_datetime(fecha_seleccionada).strftime("%Y-%m-%d")
        fig.add_vline(x=f_sel_str, line_width=2, line_dash="dash", line_color="#ffb703")
        fig.add_annotation(
            x=f_sel_str, y=1.02, yref="paper",
            text=f"📅 Date on map: {f_sel_str}",
            showarrow=False, font=dict(color="#ffb703", size=11),
            bgcolor="rgba(11,19,32,0.88)", bordercolor="#ffb703",
        )

    fig.update_layout(
        **_L,
        height=400,
        clickmode="event+select",
        hovermode="closest",
        title="Sentinel-2 index time series (AOI mean) — Click any point to view that date on the map",
        legend=dict(orientation="h", y=-0.16),
    )
    if tiene_lai:
        fig.update_yaxes(title_text="Index value", secondary_y=False)
        fig.update_yaxes(title_text="LAI (m²/m²)", showgrid=False, secondary_y=True)
    else:
        fig.update_yaxes(title_text="LAI (m²/m²)" if cols == ["LAI"] else "Index value")
    return fig


def fig_perfil(h):
    """Horizon profile (sand/silt/clay) of the dominant component."""
    h = h.dropna(subset=["hzdept_r", "hzdepb_r"]).sort_values("hzdept_r")
    etq = [f"{int(a)}–{int(b)} cm" for a, b in zip(h["hzdept_r"], h["hzdepb_r"])]
    fig = go.Figure()
    for col, nom, c in (("sandtotal_r", "Sand", "#e9c46a"), ("silttotal_r", "Silt", "#8ab17d"), ("claytotal_r", "Clay", "#e76f51")):
        fig.add_trace(go.Bar(y=etq, x=h[col], name=nom, orientation="h", marker_color=c))
    fig.update_layout(**_L, barmode="stack", height=340, title="Textural profile", xaxis_title="%",
                      yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=-0.2))
    return fig


def fig_ternario(h):
    """Horizons on the textural triangle (sand-silt-clay)."""
    d = h.dropna(subset=["sandtotal_r", "silttotal_r", "claytotal_r"])
    fig = go.Figure(go.Scatterternary(a=d["claytotal_r"], b=d["sandtotal_r"], c=d["silttotal_r"], mode="markers",
                                      text=d["muname"].str.slice(0, 30) + " · " + d["hzname"].astype(str),
                                      marker=dict(size=9, color="#2fd4a7", line=dict(width=1, color="#0b1320"))))
    fig.update_layout(**_L, height=420, title="Textural triangle (horizons)",
                      ternary=dict(sum=100, aaxis=dict(title="Clay %"), baxis=dict(title="Sand %"), caxis=dict(title="Silt %"),
                                   bgcolor="rgba(17,28,46,.6)"))
    return fig
