# ============================================================
# charts.py — Gráficos Plotly para Climate Analyzer
# ============================================================

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from config import DARK_BG, TEXT_PRIMARY, TEXT_SECONDARY, DARK_BORDER, COLORES_LOTES

# ── Layout base reutilizable ─────────────────────────────────
def _layout_base(title: str, height: int, **kwargs) -> dict:
    return dict(
        title=dict(text=title, font_size=13, x=0.01, font_color=TEXT_PRIMARY),
        height=height,
        margin=dict(l=10, r=10, t=38, b=10),
        paper_bgcolor=DARK_BG,
        plot_bgcolor=DARK_BG,
        font_color=TEXT_PRIMARY,
        xaxis=dict(gridcolor=DARK_BORDER, tickfont_size=10, color=TEXT_SECONDARY),
        yaxis=dict(gridcolor=DARK_BORDER, tickfont_size=10, color=TEXT_SECONDARY),
        **kwargs,
    )


# ════════════════════════════════════════════════════════════
# GRÁFICOS SERIES TEMPORALES (un lote)
# ════════════════════════════════════════════════════════════

def grafico_climatico(df_m: pd.DataFrame, nombre_lote: str = "") -> go.Figure:
    labels = df_m["mes_año"].dt.strftime("%b %Y")
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=labels, y=df_m["precip"],
        name="Precipitación (mm)", marker_color="#4da6ff", opacity=0.8,
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=labels, y=df_m["eto"],
        name="ETo PM (mm)", mode="lines+markers",
        line=dict(color="#ff9f43", width=2), marker=dict(size=5),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=labels, y=df_m["t_med"],
        name="T. media (°C)", mode="lines",
        line=dict(color="#ee5a24", width=1.5, dash="dot"),
    ), secondary_y=True)

    titulo = f"Precipitación · ETo · Temperatura mensual{' — ' + nombre_lote if nombre_lote else ''}"
    fig.update_layout(
        **_layout_base(titulo, 280),
        legend=dict(orientation="h", y=-0.25, font_size=11),
        barmode="overlay",
        yaxis2=dict(gridcolor=DARK_BORDER, tickfont_size=10, color="#ee5a24",
                    title="°C", title_font_size=11, showgrid=False),
    )
    fig.update_yaxes(title_text="mm", secondary_y=False)
    return fig


def grafico_balance(df_m: pd.DataFrame, nombre_lote: str = "") -> go.Figure:
    labels  = df_m["mes_año"].dt.strftime("%b %Y")
    balance = df_m["balance_hidro"]
    colores = ["#2ecc71" if v >= 0 else "#e74c3c" for v in balance]

    fig = go.Figure(go.Bar(
        x=labels, y=balance, marker_color=colores, opacity=0.85,
        name="Balance hídrico (mm)",
        hovertemplate="<b>%{x}</b><br>Balance: %{y:.1f} mm<extra></extra>",
    ))
    fig.add_hline(y=0, line_color="#ffffff", line_width=1, opacity=0.3)
    titulo = f"Balance Hídrico mensual · Lluvia − ETo{' — ' + nombre_lote if nombre_lote else ''}"
    fig.update_layout(**_layout_base(titulo, 240))
    return fig


def grafico_diario(df_d: pd.DataFrame, t_base: float = 10.0,
                   nombre_lote: str = "") -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=df_d.index, y=df_d["precip_acum"],
        name="Lluvia acum. (mm)", mode="lines",
        line=dict(color="#4da6ff", width=2),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df_d.index, y=df_d["eto_acum"],
        name="ETo acum. (mm)", mode="lines",
        line=dict(color="#ff9f43", width=2, dash="dash"),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df_d.index, y=df_d["balance_acum"],
        name="Balance acum. (mm)", mode="lines",
        fill="tozeroy", fillcolor="rgba(46,204,113,0.15)",
        line=dict(color="#2ecc71", width=1.5),
    ), secondary_y=False)

    fig.add_trace(go.Bar(
        x=df_d.index, y=df_d["gda_acum"],
        name=f"GDA acum. (base {t_base:.0f}°C)", opacity=0.4,
        marker_color="#f39c12",
    ), secondary_y=True)

    titulo = f"Detalle diario — mes en curso{' — ' + nombre_lote if nombre_lote else ''}"
    fig.update_layout(
        **_layout_base(titulo, 280),
        legend=dict(orientation="h", y=-0.3, font_size=10),
        yaxis2=dict(tickfont_size=10, color="#f39c12",
                    title=f"GDA (base {t_base:.0f}°C)", showgrid=False),
    )
    return fig


def grafico_hr_viento(df_m: pd.DataFrame, nombre_lote: str = "") -> go.Figure:
    labels = df_m["mes_año"].dt.strftime("%b %Y")
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=labels, y=df_m["hr"],
        name="HR media (%)", marker_color="#a29bfe", opacity=0.75,
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=labels, y=df_m["viento"],
        name="Viento (m/s)", mode="lines+markers",
        line=dict(color="#fd79a8", width=2), marker=dict(size=5),
    ), secondary_y=True)

    titulo = f"Humedad Relativa · Velocidad de viento{' — ' + nombre_lote if nombre_lote else ''}"
    fig.update_layout(
        **_layout_base(titulo, 240),
        legend=dict(orientation="h", y=-0.3, font_size=11),
        yaxis2=dict(tickfont_size=10, color="#fd79a8", title="m/s", showgrid=False),
    )
    return fig


# ════════════════════════════════════════════════════════════
# GRÁFICOS COMPARATIVOS MULTI-LOTE
# ════════════════════════════════════════════════════════════

def grafico_comparar_precip(series_dict: dict) -> go.Figure:
    """
    Precipitación mensual de N lotes superpuesta.
    series_dict: {nombre: df_mensual}
    """
    fig = go.Figure()
    for i, (nombre, df_m) in enumerate(series_dict.items()):
        color = COLORES_LOTES[i % len(COLORES_LOTES)]
        labels = df_m["mes_año"].dt.strftime("%b %Y")
        fig.add_trace(go.Scatter(
            x=labels, y=df_m["precip"],
            name=nombre, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=5, color=color),
        ))
    fig.update_layout(
        **_layout_base("Precipitación mensual comparativa", 300),
        legend=dict(orientation="h", y=-0.25, font_size=11),
    )
    fig.update_yaxes(title_text="mm")
    return fig


def grafico_comparar_balance(series_dict: dict) -> go.Figure:
    """Balance hídrico mensual de N lotes."""
    fig = go.Figure()
    for i, (nombre, df_m) in enumerate(series_dict.items()):
        color = COLORES_LOTES[i % len(COLORES_LOTES)]
        labels = df_m["mes_año"].dt.strftime("%b %Y")
        fig.add_trace(go.Scatter(
            x=labels, y=df_m["balance_hidro"],
            name=nombre, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=5, color=color),
        ))
    fig.add_hline(y=0, line_color="#ffffff", line_width=1, opacity=0.3)
    fig.update_layout(
        **_layout_base("Balance Hídrico comparativo (Lluvia − ETo)", 300),
        legend=dict(orientation="h", y=-0.25, font_size=11),
    )
    fig.update_yaxes(title_text="mm")
    return fig


def grafico_comparar_temperatura(series_dict: dict) -> go.Figure:
    """Temperatura media mensual de N lotes."""
    fig = go.Figure()
    for i, (nombre, df_m) in enumerate(series_dict.items()):
        color = COLORES_LOTES[i % len(COLORES_LOTES)]
        labels = df_m["mes_año"].dt.strftime("%b %Y")
        fig.add_trace(go.Scatter(
            x=labels, y=df_m["t_med"],
            name=nombre, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=5, color=color),
        ))
    fig.update_layout(
        **_layout_base("Temperatura media mensual comparativa", 280),
        legend=dict(orientation="h", y=-0.25, font_size=11),
    )
    fig.update_yaxes(title_text="°C")
    return fig


def grafico_radar_comparativo(df_resumen: pd.DataFrame) -> go.Figure:
    """
    Gráfico de radar para comparar lotes en múltiples métricas normalizadas.
    """
    categorias = ["Lluvia mm", "ETo mm", "T°C media", "HR% media", "GDA total"]
    fig = go.Figure()

    for i, (lote, row) in enumerate(df_resumen.iterrows()):
        color = COLORES_LOTES[i % len(COLORES_LOTES)]
        # Normalizar 0-1 respecto al máximo de cada métrica
        vals = []
        for cat in categorias:
            col_max = df_resumen[cat].max()
            vals.append(row[cat] / col_max if col_max > 0 else 0)
        vals.append(vals[0])  # cerrar el polígono

        fig.add_trace(go.Scatterpolar(
            r=vals,
            theta=categorias + [categorias[0]],
            fill="toself",
            name=str(lote),
            line_color=color,
            fillcolor=color.replace(")", ", 0.15)").replace("rgb", "rgba")
                      if "rgb" in color else color + "26",
        ))

    fig.update_layout(
        polar=dict(
            bgcolor=DARK_BG,
            radialaxis=dict(visible=True, range=[0, 1],
                            gridcolor=DARK_BORDER, color=TEXT_SECONDARY),
            angularaxis=dict(gridcolor=DARK_BORDER, color=TEXT_SECONDARY),
        ),
        **_layout_base("Comparación multi-lote (normalizado)", 380),
        legend=dict(orientation="h", y=-0.15, font_size=11),
    )
    return fig


def grafico_barras_comparativas(df_resumen: pd.DataFrame) -> go.Figure:
    """Barras agrupadas por métrica para comparar lotes."""
    metricas = ["Lluvia mm", "ETo mm", "Balance mm", "GDA total"]
    fig = go.Figure()

    for i, (lote, row) in enumerate(df_resumen.iterrows()):
        color = COLORES_LOTES[i % len(COLORES_LOTES)]
        fig.add_trace(go.Bar(
            name=str(lote),
            x=metricas,
            y=[row[m] for m in metricas],
            marker_color=color, opacity=0.85,
        ))

    fig.update_layout(
        **_layout_base("Resumen comparativo por lote", 320),
        barmode="group",
        legend=dict(orientation="h", y=-0.2, font_size=11),
    )
    return fig
