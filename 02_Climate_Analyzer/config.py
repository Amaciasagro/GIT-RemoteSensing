# ============================================================
# config.py — Constantes globales · Climate Analyzer
# ============================================================

# ── Colecciones GEE ──────────────────────────────────────────
ERA5_COLLECTION    = "ECMWF/ERA5_LAND/DAILY_AGGR"
CHIRPS_COLLECTION  = "UCSB-CHG/CHIRPS/DAILY"
CHIRPS_PENTAD      = "UCSB-CHG/CHIRPS/PENTAD"   # para anomalías rápidas

# ── Parámetros agronómicos ───────────────────────────────────
T_BASE_DEFAULT     = 10.0    # °C — Temperatura base GDA
T_HELADA           = 3.0     # °C — Umbral mínima para riesgo helada
T_CALOR            = 35.0    # °C — Umbral máxima estrés térmico
CHIRPS_BASELINE_YEARS = 20   # Años usados para calcular promedio histórico CHIRPS

# ── Paletas de color (GEE style) ─────────────────────────────
PALETA_ANOMALIA = [
    "#67001f", "#b2182b", "#d6604d", "#f4a582",
    "#fddbc7", "#f7f7f7",
    "#d1e5f0", "#92c5de", "#4393c3", "#2166ac", "#053061",
]
PALETA_BALANCE = [
    "#8B0000", "#D2691E", "#DAA520", "#FFFACD",
    "#90EE90", "#32CD32", "#006400",
]
PALETA_PRECIPITACION = [
    "#f7fbff", "#deebf7", "#c6dbef",
    "#9ecae1", "#6baed6", "#4292c6",
    "#2171b5", "#08519c", "#08306b",
]
PALETA_TEMPERATURA = [
    "#313695", "#4575b4", "#74add1", "#abd9e9",
    "#e0f3f8", "#ffffbf",
    "#fee090", "#fdae61", "#f46d43", "#d73027", "#a50026",
]
PALETA_HELADAS  = ["#ffffff", "#b3cde3", "#6baed6", "#2171b5", "#084594"]
PALETA_CALOR    = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]

# ── Colores para lotes (ciclo automático) ────────────────────
COLORES_LOTES = [
    "#f1c40f",  # amarillo
    "#e74c3c",  # rojo
    "#2ecc71",  # verde
    "#3498db",  # azul
    "#9b59b6",  # violeta
    "#1abc9c",  # turquesa
    "#e67e22",  # naranja
    "#fd79a8",  # rosa
    "#00b894",  # menta
    "#fdcb6e",  # ocre
]

# ── Estilos UI ───────────────────────────────────────────────
DARK_BG        = "#0d1520"
DARK_PANEL     = "#111c2a"
DARK_BORDER    = "#1a2d42"
TEXT_PRIMARY   = "#d4e2f0"
TEXT_SECONDARY = "#7a99b8"

CSS_GLOBAL = f"""
<style>
  [data-testid="stSidebar"] {{ background: {DARK_BG}; }}
  .block-container {{ padding-top: 1.2rem; padding-bottom: 1rem; }}
  div[data-testid="metric-container"] {{
    background: {DARK_PANEL};
    border: 1px solid {DARK_BORDER};
    border-radius: 10px;
    padding: 12px 16px;
  }}
  div[data-testid="metric-container"] label {{ color: {TEXT_SECONDARY} !important; font-size:12px; }}
  .stAlert {{ border-radius: 8px; }}
  .lote-badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    margin: 2px;
  }}
</style>
"""

CSS_WATERMARK = """
<style>
.watermark {
    position: fixed; bottom: 15px; right: 15px;
    opacity: 0.5; font-size: 13px; color: #7a99b8;
    z-index: 9999; pointer-events: none;
    background-color: rgba(13,21,32,0.7);
    padding: 5px 10px; border-radius: 5px;
}
</style>
<div class="watermark">© 2026 Ariel Macías | Ingeniero Agrónomo & Analista SIG</div>
"""
