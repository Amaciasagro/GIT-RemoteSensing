"""Configuración global: autoría, tablas de referencia hidrológica y estilos (tema oscuro)."""

AUTOR = "© 2026 Ariel Macías | Ingeniero agrónomo & Analista SIG"

# Propiedades hidrofísicas por defecto según clase textural USDA (aprox. Rawls et al. / Saxton & Rawls)
# fc / wp: % volumétrico; ksat: mm/h; por: porosidad (m3/m3); hsg: grupo hidrológico; psi_m: succión capilar media (m)
TEXTURA_DEFECTO = {
    "Sand":            dict(fc=12, wp=5,  ksat=210.0, hsg="A", por=0.43, psi_m=0.07),
    "Loamy sand":      dict(fc=14, wp=6,  ksat=60.0,  hsg="A", por=0.44, psi_m=0.10),
    "Sandy loam":      dict(fc=20, wp=9,  ksat=26.0,  hsg="B", por=0.45, psi_m=0.18),
    "Loam":            dict(fc=28, wp=14, ksat=13.0,  hsg="B", por=0.46, psi_m=0.32),
    "Silt loam":       dict(fc=31, wp=11, ksat=7.0,   hsg="B", por=0.48, psi_m=0.50),
    "Silt":            dict(fc=30, wp=6,  ksat=7.0,   hsg="B", por=0.48, psi_m=0.55),
    "Sandy clay loam": dict(fc=27, wp=17, ksat=4.0,   hsg="C", por=0.42, psi_m=0.38),
    "Clay loam":       dict(fc=36, wp=22, ksat=2.5,   hsg="D", por=0.47, psi_m=0.52),
    "Silty clay loam": dict(fc=38, wp=22, ksat=1.5,   hsg="C", por=0.50, psi_m=0.60),
    "Sandy clay":      dict(fc=36, wp=25, ksat=1.2,   hsg="C", por=0.43, psi_m=0.48),
    "Silty clay":      dict(fc=41, wp=27, ksat=0.9,   hsg="D", por=0.51, psi_m=0.68),
    "Clay":            dict(fc=42, wp=30, ksat=0.6,   hsg="D", por=0.50, psi_m=0.75),
}

# Profundidad radicular efectiva típica por cultivo (cm) para el criterio agronómico vs. edáfico
PROF_RADICULAR_CULTIVOS = {
    "Personalizada (usar slider)": None,
    "Maíz (Zea mays) — 120 cm": 120,
    "Soja (Glycine max) — 100 cm": 100,
    "Trigo / Cereales de invierno — 90 cm": 90,
    "Sorgo granífero — 110 cm": 110,
    "Girasol — 130 cm": 130,
    "Algodón — 110 cm": 110,
    "Alfalfa / Pasturas — 150 cm": 150,
    "Hortalizas / Raíz superficial — 60 cm": 60,
}

TEXTURA_ES = {
    "Sand": "Arenoso", "Loamy sand": "Areno franco", "Sandy loam": "Franco arenoso",
    "Loam": "Franco", "Silt loam": "Franco limoso", "Silt": "Limoso",
    "Sandy clay loam": "Franco arcillo-arenoso", "Clay loam": "Franco arcilloso",
    "Silty clay loam": "Franco arcillo-limoso", "Sandy clay": "Arcillo-arenoso",
    "Silty clay": "Arcillo-limoso", "Clay": "Arcilloso",
}

# Número de curva (SCS-CN, condición AMC II) por grupo hidrológico
CN_DESNUDO  = {"A": 77.0, "B": 86.0, "C": 91.0, "D": 94.0}   # suelo desnudo / barbecho
CN_VEGETADO = {"A": 39.0, "B": 61.0, "C": 74.0, "D": 80.0}   # cobertura densa (NDVI alto)

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
    """Devuelve el HTML de una tarjeta de métrica estilizada."""
    return (f"<div class='tarjeta {tipo}'><div class='t'>{titulo}</div>"
            f"<div class='v'>{valor}<span class='u'>{unidad}</span></div>"
            f"<div class='s'>{sub}</div></div>")
