"""
Configuración del scraper de proyectos del Banco Interamericano de Desarrollo (BID / IDB).

IMPORTANTE — por qué esto no scrapea www.iadb.org con requests ni con
Playwright.launch() normal:
Ese dominio está protegido por Cloudflare Bot Fight Mode. Se verificó en
vivo que:
  - requests / Playwright headless (con o sin cookies de warmup): 403
    duro ("Attention Required! | Cloudflare") en cualquier página salvo
    la home. No es un challenge de cookies como el de CAF (Incapsula).
  - Playwright headless "puro" (sin launch(), lanzado a mano vía
    connect_over_cdp): también 403. Es el modo headless en sí lo que
    Cloudflare detecta, no las banderas de automatización.
  - Chromium con pantalla real (headed), lanzado como proceso normal
    (SIN --enable-automation ni el resto de banderas de Playwright.launch())
    y recién después controlado vía connect_over_cdp: pasa sin problema.

Por eso bids_browser.py lanza Chromium a mano (headed) — requiere una
pantalla real (WSLg en WSL2, DISPLAY=:0). Ver bids_listings.py /
bids_projects.py para el scraping en sí.

Alternativa histórica (sin Chromium): el BID también publica sus avisos de
adquisiciones como dato abierto en data.iadb.org (CKAN) vía bids_notices.py
+ bids_index.py, pero ese dataset tiene un rezago de varios meses — no sirve
para trackear avisos nuevos, solo como backfill histórico masivo.
"""

BASE_URL = "https://www.iadb.org"
LISTINGS_PATH = "/en/project-search"
OUTPUT_ROOT = "bids"

# Portal de datos abiertos del BID (CKAN) — ver nota arriba, uso histórico
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
