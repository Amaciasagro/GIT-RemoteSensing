"""Global configuration: authorship, texture tables, indices and styles (dark theme)."""

AUTOR = "© 2026 Ariel Macías | Agronomist & GIS Analyst"

# Default hydrophysical properties by USDA textural class (approx. Rawls et al.)
# fc / wp: % volumetric; ksat: mm/h; por: porosity (m3/m3); hsg: hydrologic group
TEXTURA_DEFECTO = {
    "Sand":            dict(fc=12, wp=5,  ksat=210.0, hsg="A", por=0.43),
    "Loamy sand":      dict(fc=14, wp=6,  ksat=60.0,  hsg="A", por=0.44),
    "Sandy loam":      dict(fc=20, wp=9,  ksat=26.0,  hsg="B", por=0.45),
    "Loam":            dict(fc=28, wp=14, ksat=13.0,  hsg="B", por=0.46),
    "Silt loam":       dict(fc=31, wp=11, ksat=7.0,   hsg="B", por=0.48),
    "Silt":            dict(fc=30, wp=6,  ksat=7.0,   hsg="B", por=0.48),
    "Sandy clay loam": dict(fc=27, wp=17, ksat=4.0,   hsg="C", por=0.42),
    "Clay loam":       dict(fc=36, wp=22, ksat=2.5,   hsg="D", por=0.47),
    "Silty clay loam": dict(fc=38, wp=22, ksat=1.5,   hsg="C", por=0.50),
    "Sandy clay":      dict(fc=36, wp=25, ksat=1.2,   hsg="C", por=0.43),
    "Silty clay":      dict(fc=41, wp=27, ksat=0.9,   hsg="D", por=0.51),
    "Clay":            dict(fc=42, wp=30, ksat=0.6,   hsg="D", por=0.50),
}

TEXTURA_ES = {
    "Sand": "Sand", "Loamy sand": "Loamy sand", "Sandy loam": "Sandy loam",
    "Loam": "Loam", "Silt loam": "Silt loam", "Silt": "Silt",
    "Sandy clay loam": "Sandy clay loam", "Clay loam": "Clay loam",
    "Silty clay loam": "Silty clay loam", "Sandy clay": "Sandy clay",
    "Silty clay": "Silty clay", "Clay": "Clay",
}

# Index metadata: name -> (description, vmin, vmax, map palette)
INDICES = {
    "NDVI": ("Vigor / green biomass", -0.1, 0.9, ["#a50026", "#f46d43", "#fee08b", "#a6d96a", "#1a9850", "#006837"]),
    "LAI":  ("Leaf area index (m²/m²)", 0.0, 6.0, ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"]),
    "EVI":  ("Enhanced vigor (corrects soil/atmosphere)", 0.0, 1.0, ["#8c510a", "#dfc27d", "#f6e8c3", "#80cdc1", "#018571"]),
    "EVI2": ("2-band enhanced vigor", 0.0, 0.9, ["#ffffe5", "#78c679", "#004529"]),
    "SAVI": ("Soil-adjusted vigor", 0.0, 0.8, ["#8c510a", "#dfc27d", "#c7e9c0", "#41ab5d", "#006d2c"]),
    "NDWI": ("Surface water / leaf moisture (McFeeters)", -0.6, 0.4, ["#8c510a", "#f6e8c3", "#c7eae5", "#35978f", "#01665e"]),
    "NDMI": ("Canopy moisture content (NIR/SWIR)", -0.4, 0.6, ["#8c510a", "#f6e8c3", "#80cdc1", "#2166ac", "#053061"]),
}

CAPAS_VISUALES_CROP = {
    **{k: f"{k} · {v[0]}" for k, v in INDICES.items()},
    "TrueColor": "🎨 RGB True Color (B4, B3, B2)",
    "FalseColor": "🔴 False Color Infrared (NIR, B4, B3)",
}

CSS_GLOBAL = """
<style>
.stApp {background: linear-gradient(180deg,#0b1320 0%,#0e1a2c 100%); color:#dce6f2;}
section[data-testid="stSidebar"] {background:#0d1727; border-right:1px solid #1f3350;}
h1,h2,h3,h4 {color:#e8f1fb;}
.tarjeta {background:#111c2e; border:1px solid #1f3350; border-left:4px solid #2fd4a7;
          border-radius:10px; padding:12px 14px; margin-bottom:8px;}
.tarjeta.agua {border-left-color:#2f9bff;}
.tarjeta.alerta {border-left-color:#ff6b6b;}
.tarjeta.suelo {border-left-color:#d9a441;}
.tarjeta .t {font-size:11px; color:#7a99b8; text-transform:uppercase; letter-spacing:.06em;}
.tarjeta .v {font-size:24px; font-weight:700; color:#e8f1fb;}
.tarjeta .u {font-size:12px; color:#7a99b8; margin-left:4px;}
.tarjeta .s {font-size:11px; color:#5f7c9b;}
div[data-testid="stTabs"] button {font-weight:600;}
</style>
"""

CSS_WATERMARK = (
    "<style>.marca-agua{position:fixed;right:14px;bottom:8px;z-index:9999;font-size:11px;"
    "color:rgba(160,185,210,.55);pointer-events:none;letter-spacing:.03em;}</style>"
    "<div class='marca-agua'>__AUTOR__</div>"
).replace("__AUTOR__", AUTOR)


def tarjeta(titulo, valor, unidad="", sub="", tipo=""):
    """Returns the HTML of a styled metric card."""
    return (f"<div class='tarjeta {tipo}'><div class='t'>{titulo}</div>"
            f"<div class='v'>{valor}<span class='u'>{unidad}</span></div>"
            f"<div class='s'>{sub}</div></div>")
