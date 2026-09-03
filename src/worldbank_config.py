"""
Configuración del scraper de proyectos del Banco Mundial (World Bank).

A diferencia del BID, esto no necesita navegador ni scraping HTML: el Banco
Mundial expone una API pública, documentada y en vivo (sin protección
anti-bot tipo Cloudflare Bot Fight Mode ni rezago de meses como el CSV que
se evaluó para el BID):

  - Listado de proyectos: search.worldbank.org/api/v2/projects
  - Documentos por proyecto: search.worldbank.org/api/v3/wds?projectid=...
  - PDFs: documents.worldbank.org (CloudFront, sin protección)

Todo funciona con requests plano — confirmado en vivo, sin bloqueos.
"""

OUTPUT_ROOT = "worldbank"

PROJECTS_API = "https://search.worldbank.org/api/v2/projects"
DOCS_API = "https://search.worldbank.org/api/v3/wds"

# Coincide con el filtro que pidió el usuario (regionname_exact en la URL
# de projects.worldbank.org)
REGION_FILTER = "Latin America and Caribbean"

# Filtro de estado: valores separados por ^ (OR).
# Opciones válidas: Active, Pipeline, Closed, Effective, Economic Evaluation,
# Appraisal, Signed, Board Approval, Board Presentation, Board Approved
# Ejemplo: "Active^Pipeline" = Active O Pipeline
STATUS_FILTER = "Active^Pipeline"

ROWS_PER_PAGE = 20

HTTP_CONFIG = {
    "retries": 3,
    "retry_delay_ms": 1000,
    "timeout_ms": 30000,
}

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
}
