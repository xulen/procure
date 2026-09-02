"""
Configuración del scraper de proyectos del Banco Interamericano de Desarrollo (BID / IDB).

IMPORTANTE — por qué esto NO scrapea www.iadb.org/en/project-search:
Ese dominio está protegido por Cloudflare Bot Fight Mode. Se verificó que
incluso una navegación real con Playwright (Chromium headless, cookies de
warmup válidas, sin señales obvias de automatización) recibe un bloqueo
duro ("Attention Required! | Cloudflare") en cualquier página salvo la home.
No es un simple challenge de cookies como el de CAF (Incapsula): es un
bloqueo de comportamiento que persiste incluso resolviendo el warmup.

En cambio, el BID publica sus avisos de adquisiciones (procurement notices)
como dato abierto en data.iadb.org (portal CKAN, sin protección anti-bot),
con un enlace directo a cada documento en idbdocs.iadb.org que redirige a
un bucket S3 público. Ese es el camino que usan bids_notices.py y
bids_documents.py — no requiere Playwright ni cookies de sesión.
"""

OUTPUT_ROOT = "bids"

# Portal de datos abiertos del BID (CKAN)
CKAN_API_BASE = "https://data.iadb.org/api/3/action"
NOTICES_DATASET_ID = "project-procurement-bidding-notices-and-notification-of-contract-awards"

HTTP_CONFIG = {
    "retries": 3,
    "retry_delay_ms": 1000,
    "timeout_ms": 30000,
    "delay_between_requests_ms": 1500,
}

HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-language": "en,en;q=0.9,es;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
}
