# ============================================================
# plots.py — Visualizaciones Plotly para Climate Analyzer
# ============================================================
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from IPython.display import display


def _fmt_mes(ts) -> str:
    """Formatea timestamp a 'Ene 24'."""
    meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    return f"{meses[ts.month - 1]} {str(ts.year)[2:]}"


# ─────────────────────────────────────────────
# PANEL 1 — Histórico Mensual
# ─────────────────────────────────────────────

def grafico_historico(df_mensual: pd.DataFrame, daily_start: str, daily_end: str) -> go.Figure:
    """
    Panel histórico mensual:
      - Barras: Precipitación y ETo mensual
      - Líneas: T. máx y mín media
      - Barras de balance hídrico (+ verde / - rojo)
    """
    df = df_mensual.copy()
    df["label"] = df["mes_año"].apply(_fmt_mes)

    colores_balance = ["#27ae60" if v >= 0 else "#e74c3c" for v in df["balance_hidro"]]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=("Precipitación & ETo mensual", "Balance hídrico mensual (Lluvia − ETo)"),
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
        row_heights=[0.6, 0.4],
    )

    # Precipitación
    fig.add_trace(go.Bar(
        x=df["label"], y=df["precip"],
        name="Lluvia (mm)", marker_color="#3498db", opacity=0.8,
        hovertemplate="<b>%{x}</b><br>Lluvia: %{y:.1f} mm<extra></extra>"
    ), row=1, col=1, secondary_y=False)

    # ETo
    fig.add_trace(go.Bar(
        x=df["label"], y=df["eto"],
        name="ETo Penman-Monteith (mm)", marker_color="#f39c12", opacity=0.6,
        hovertemplate="<b>%{x}</b><br>ETo: %{y:.1f} mm<extra></extra>"
    ), row=1, col=1, secondary_y=False)

    # Temperatura máxima
    fig.add_trace(go.Scatter(
        x=df["label"], y=df["t_max"],
        name="T. Máx media (°C)", mode="lines+markers",
        line=dict(color="#e74c3c", width=2),
        hovertemplate="<b>%{x}</b><br>T.Máx: %{y:.1f}°C<extra></extra>"
    ), row=1, col=1, secondary_y=True)

    # Temperatura mínima
    fig.add_trace(go.Scatter(
        x=df["label"], y=df["t_min"],
        name="T. Mín media (°C)", mode="lines+markers",
        line=dict(color="#2c3e50", width=2, dash="dash"),
        hovertemplate="<b>%{x}</b><br>T.Mín: %{y:.1f}°C<extra></extra>"
    ), row=1, col=1, secondary_y=True)

    # Humedad relativa
    fig.add_trace(go.Scatter(
        x=df["label"], y=df["hr"],
        name="HR media (%)", mode="lines",
        line=dict(color="#8e44ad", width=1.5, dash="dot"),
        hovertemplate="<b>%{x}</b><br>HR: %{y:.0f}%<extra></extra>"
    ), row=1, col=1, secondary_y=True)

    # Balance hídrico
    fig.add_trace(go.Bar(
        x=df["label"], y=df["balance_hidro"],
        name="Balance Hídrico (mm)", marker_color=colores_balance,
        hovertemplate="<b>%{x}</b><br>Balance: %{y:.1f} mm<extra></extra>"
    ), row=2, col=1)

    # Línea cero en balance
    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="grey", row=2, col=1)

    fig.update_layout(
        height=650, template="plotly_white",
        title_text="🌦️ Análisis Climático Histórico — ERA5-Land (Penman-Monteith FAO-56)",
        hovermode="x unified", barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Precipitación / ETo (mm)", secondary_y=False, row=1, col=1, showgrid=False)
    fig.update_yaxes(title_text="Temperatura °C / HR %",   secondary_y=True,  row=1, col=1, showgrid=True)
    fig.update_yaxes(title_text="Balance Hídrico (mm)",    row=2, col=1)

    return fig


# ─────────────────────────────────────────────
# PANEL 2 — Detalle Diario del mes actual
# ─────────────────────────────────────────────

def grafico_diario(df_diario: pd.DataFrame, daily_start: str, daily_end: str) -> go.Figure:
    """
    Panel diario del mes actual:
      - Barras: lluvia diaria
      - Líneas: lluvia acumulada, ETo acumulada, balance hídrico acumulado
      - Eje secundario: T. media diaria y GDA acumulados
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=("Agua: Lluvia, ETo y Balance Acumulado", "Temperatura media diaria y GDA acumulados"),
        specs=[[{"secondary_y": False}], [{"secondary_y": True}]],
        row_heights=[0.55, 0.45],
    )

    # Lluvia diaria
    fig.add_trace(go.Bar(
        x=df_diario["fecha"], y=df_diario["precip"],
        name="Lluvia diaria (mm)", marker_color="#2980b9",
        hovertemplate="<b>%{x|%d %b}</b><br>Lluvia: %{y:.1f} mm<extra></extra>"
    ), row=1, col=1)

    # Lluvia acumulada
    fig.add_trace(go.Scatter(
        x=df_diario["fecha"], y=df_diario["precip_acum"],
        name="Lluvia acum. (mm)", mode="lines",
        line=dict(color="#3498db", width=2.5),
        hovertemplate="<b>%{x|%d %b}</b><br>Lluvia acum: %{y:.1f} mm<extra></extra>"
    ), row=1, col=1)

    # ETo acumulada
    fig.add_trace(go.Scatter(
        x=df_diario["fecha"], y=df_diario["eto_acum"],
        name="ETo acum. (mm)", mode="lines",
        line=dict(color="#f39c12", width=2.5, dash="dash"),
        hovertemplate="<b>%{x|%d %b}</b><br>ETo acum: %{y:.1f} mm<extra></extra>"
    ), row=1, col=1)

    # Balance hídrico acumulado
    fig.add_trace(go.Scatter(
        x=df_diario["fecha"], y=df_diario["balance_hidro_acum"],
        name="Balance hídrico acum. (mm)", mode="lines",
        line=dict(color="#27ae60", width=2, dash="dot"),
        hovertemplate="<b>%{x|%d %b}</b><br>Balance acum: %{y:.1f} mm<extra></extra>"
    ), row=1, col=1)

    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="grey", row=1, col=1)

    # Temperatura media
    fig.add_trace(go.Scatter(
        x=df_diario["fecha"], y=df_diario["t_med"],
        name="T. Media diaria (°C)", mode="lines+markers",
        line=dict(color="#e67e22", width=2.5),
        hovertemplate="<b>%{x|%d %b}</b><br>T.Med: %{y:.1f}°C<extra></extra>"
    ), row=2, col=1, secondary_y=False)

    # GDA acumulados
    fig.add_trace(go.Scatter(
        x=df_diario["fecha"], y=df_diario["gda"],
        name=f"GDA acum. (Tbase={df_diario.attrs.get('t_base', 10)}°C)",
        mode="lines", line=dict(color="#8e44ad", width=2, dash="dot"),
        hovertemplate="<b>%{x|%d %b}</b><br>GDA: %{y:.0f}°C·día<extra></extra>"
    ), row=2, col=1, secondary_y=True)

    fig.update_layout(
        height=650, template="plotly_white",
        title_text=f"📅 Detalle Diario: {daily_start} → {daily_end}",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Agua (mm)",          row=1, col=1)
    fig.update_yaxes(title_text="Temperatura (°C)",   secondary_y=False, row=2, col=1, showgrid=True)
    fig.update_yaxes(title_text="GDA (°C·día)",       secondary_y=True,  row=2, col=1, showgrid=False)

    return fig


# ─────────────────────────────────────────────
# Función orquestadora
# ─────────────────────────────────────────────

def mostrar_graficos(df_mensual: pd.DataFrame, df_diario: pd.DataFrame,
                     daily_start: str, daily_end: str) -> None:
    """Genera y muestra ambos paneles en el notebook."""
    fig1 = grafico_historico(df_mensual, daily_start, daily_end)
    fig2 = grafico_diario(df_diario, daily_start, daily_end)
    display(fig1)
    display(fig2)
