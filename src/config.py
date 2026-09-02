"""
Configuración del scraper de convocatorias de CAF.
"""

BASE_URL = "https://www.caf.com"
LISTINGS_PATH = "/es/trabaja-con-nosotros/convocatorias/"
TOTAL_PAGES = 43
TOTAL_PAGES_DETECTED = 43

OUTPUT_ROOT = "caf"

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
    "accept-language": "es,en;q=0.9,es-ES;q=0.8",
    "cache-control": "max-age=0",
    "dnt": "1",
    "priority": "u=0, i",
    "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
}

COUNTRIES = [
    "Argentina", "Bolivia", "Brasil", "Colombia", "Costa Rica",
    "Ecuador", "El Salvador", "España", "Grenada", "Honduras",
    "Jamaica", "México", "Panamá", "Paraguay", "Perú",
    "Portugal", "República Dominicana", "Trinidad y Tobago",
    "Uruguay", "Venezuela", "Chile",
]

COUNTRY_CODES = {
    "Argentina": "AR", "Bolivia": "BO", "Brasil": "BR", "Colombia": "CO",
    "Costa Rica": "CR", "Ecuador": "EC", "El Salvador": "SV",
    "España": "ES", "Grenada": "GD", "Honduras": "HN", "Jamaica": "JM",
    "México": "MX", "Panamá": "PA", "Paraguay": "PY", "Perú": "PE",
    "Portugal": "PT", "República Dominicana": "DO", "Trinidad y Tobago": "TT",
    "Uruguay": "UY", "Venezuela": "VE", "Chile": "CL",
}
