"""
Módulo HTTP híbrido: Playwright para resolver el challenge anti-bot de CAF
al inicio, luego requests con cookies capturadas para todo el scraping.

Solo cubre CAF (www.caf.com — Incapsula/hCaptcha). El BID no usa este
módulo: www.iadb.org está detrás de Cloudflare Bot Fight Mode, que bloquea
incluso navegación real con Playwright (ver bids_config.py), así que
bids_notices.py / bids_documents.py van directo al dataset abierto del BID
y a idbdocs.iadb.org, ninguno de los dos con protección anti-bot.
"""

import time
import logging
from urllib.parse import urlparse

import requests
from config import HTTP_CONFIG, HEADERS, BASE_URL, LISTINGS_PATH

logger = logging.getLogger(__name__)

# Sesiones por host (ej: "www.caf.com" → requests.Session)
_sessions = {}

# Metadatos de las fuentes conocidas para el warmup con Playwright
SOURCES = {
    "caf": {
        "base_url": "https://www.caf.com",
        "listings_path": "/es/trabaja-con-nosotros/convocatorias/",
        "cookie_domain": ".caf.com",
        "locale": "es-ES",
    },
}


def _host_of(url):
    """Extrae el hostname de una URL (ej: www.iadb.org)."""
    try:
        return urlparse(url).netloc
    except Exception:
        return "unknown"


def _warmup_browser(base_url, listings_path, locale):
    """
    Usa Playwright para navegar de forma natural (home → listado)
    y capturar las cookies del servidor. Esto resuelve el challenge
    anti-bot que no se puede resolver con requests solo.

    Args:
        base_url: URL base del sitio (ej: https://www.iadb.org).
        listings_path: ruta del listado (ej: /en/project-search).
        locale: locale del navegador (es-ES, en-US, ...).

    Returns:
        dict con las cookies {name: value}.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS.get("User-Agent", ""),
            locale=locale,
        )
        page = context.new_page()

        # Paso 1: Ir a la home para establecer cookies base
        try:
            page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=30000)
        except Exception as err:
            logger.warning(f"⚠ Home warmup falló: {err}")

        time.sleep(2)

        # Paso 2: Navegar al listado para obtener cookies de sesión
        try:
            page.goto(
                f"{base_url}{listings_path}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception as err:
            logger.warning(f"⚠ Listings warmup falló: {err}")

        # Capturar cookies como dict
        cookies = context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        browser.close()
        return cookie_dict


def _cookie_domain_for(host):
    """Determina el dominio de cookie para un host."""
    for source_cfg in SOURCES.values():
        if host in source_cfg["base_url"]:
            return source_cfg["cookie_domain"]
    # Fallback: dominio de segundo nivel
    parts = host.split(".")
    if len(parts) >= 2:
        return "." + ".".join(parts[-2:])
    return host


def _config_for(host):
    """Busca la configuración de fuente cuyo base_url contenga el host."""
    for source_cfg in SOURCES.values():
        if host in source_cfg["base_url"]:
            return source_cfg
    return None


def init_session():
    """
    Inicializa la sesión HTTP para CAF con cookies capturadas desde Playwright.
    (API compatible con el flujo CAF existente.)

    Primero resuelve el challenge navegando home → convocatorias,
    luego configura requests.Session con las cookies obtenidas.
    """
    init_source_session("caf")


def init_source_session(source):
    """
    Inicializa la sesión HTTP de una fuente específica.

    Args:
        source: "caf".
    """
    global _sessions

    if source not in SOURCES:
        raise ValueError(f"Fuente desconocida: {source} (disponibles: {', '.join(SOURCES)})")

    cfg = SOURCES[source]
    host = _host_of(cfg["base_url"])

    if host in _sessions:
        return  # Ya inicializada

    print(f"  🔌 Resolviendo protección del servidor ({host})...")
    cookies = _warmup_browser(cfg["base_url"], cfg["listings_path"], cfg["locale"])
    print(f"  🍪 {len(cookies)} cookies capturadas: {', '.join(list(cookies.keys())[:6])}...")

    # Crear session con las cookies del dominio correspondiente
    session = requests.Session()
    session.headers.update(HEADERS)
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=cfg["cookie_domain"])

    _sessions[host] = session


def _get_session_for_url(url):
    """
    Retorna la sesión correspondiente al host de la URL.

    Si la URL apunta a www.caf.com y no hay sesión, la inicializa
    automáticamente.
    """
    host = _host_of(url)

    if host in _sessions:
        return _sessions[host]

    # Detectar la fuente a partir del host y auto-inicializar
    source_cfg = _config_for(host)
    if source_cfg:
        source_name = next(
            (name for name, c in SOURCES.items() if c["base_url"] == source_cfg["base_url"]),
            None,
        )
        if source_name:
            init_source_session(source_name)
            if host in _sessions:
                return _sessions[host]

    raise RuntimeError(
        f"No hay sesión HTTP inicializada para {host}. "
        f"Llama a init_session() antes de hacer peticiones."
    )


def http_get(url, retries=None, retry_delay_ms=None):
    """
    Realiza una petición GET con reintentos y delay entre intentos.

    Args:
        url: URL a obtener.
        retries: Número de reintentos (default: HTTP_CONFIG['retries']).
        retry_delay_ms: Delay base entre reintentos en ms.

    Returns:
        HTML como string.

    Raises:
        Exception: Si todos los intentos fallan.
    """
    retries = retries or HTTP_CONFIG["retries"]
    retry_delay_ms = retry_delay_ms or HTTP_CONFIG["retry_delay_ms"]

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            session = _get_session_for_url(url)
            response = session.get(
                url,
                timeout=HTTP_CONFIG["timeout_ms"] / 1000,
                verify=False,
            )
            response.raise_for_status()

            # Verificar que no recibimos un challenge anti-bot
            if len(response.text) < 500 or "Incapsula" in response.text:
                logger.warning(
                    f"  ⚠ Intento {attempt}/{retries}: respuesta sospechosa "
                    f"(len={len(response.text)}, has_incapsula={'Incapsula' in response.text})"
                )
                if attempt < retries:
                    time.sleep(retry_delay_ms * attempt / 1000)
                    # Re-inicializar sesión para obtener nuevas cookies
                    host = _host_of(url)
                    if host in _sessions:
                        del _sessions[host]
                    _get_session_for_url(url)
                continue

            return response.text

        except Exception as err:
            last_error = err
            logger.warning(
                f"  ⚠ Intento {attempt}/{retries} falló para {url}: {err}"
            )
            if attempt < retries:
                time.sleep(retry_delay_ms * attempt / 1000)

    raise last_error


def download_file(url, retries=None, retry_delay_ms=None):
    """
    Descarga un archivo binario (PDF). Devuelve buffer + metadata.

    Args:
        url: URL del archivo.
        retries: Número de reintentos.
        retry_delay_ms: Delay base entre reintentos en ms.

    Returns:
        dict con keys: 'url', 'buffer' (bytes), 'size' (int).

    Raises:
        Exception: Si todos los intentos fallan.
    """
    retries = retries or HTTP_CONFIG["retries"]
    retry_delay_ms = retry_delay_ms or HTTP_CONFIG["retry_delay_ms"]

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            session = _get_session_for_url(url)
            response = session.get(
                url,
                timeout=HTTP_CONFIG["timeout_ms"] / 1000,
                stream=True,
                verify=False,
            )
            response.raise_for_status()

            buffer = response.content
            size = len(buffer)
            return {"url": url, "buffer": buffer, "size": size}

        except Exception as err:
            last_error = err
            logger.warning(
                f"  ⚠ Descarga {attempt}/{retries} falló para {url}: {err}"
            )
            if attempt < retries:
                time.sleep(retry_delay_ms * attempt / 1000)

    raise last_error
