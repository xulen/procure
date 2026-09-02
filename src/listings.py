"""
Módulo para scrapear la lista de convocatorias (páginas con tarjetas).
Usa requests + BeautifulSoup — el HTML se sirve estáticamente desde CAF.

Extrae de cada <article class="card">:
  - título y URL desde .card__title a
  - fecha de cierre desde .p-body-m strong
  - estado (abierta/cerrada) desde .card__capacitacion

Paginación automática: detecta el total de páginas desde el selector HTML
y lo guarda en config para reutilizarlo sin rescanner.
"""

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import BASE_URL, LISTINGS_PATH, HEADERS, TOTAL_PAGES
from http_client import http_get

logger = logging.getLogger(__name__)


def fetch_all_listings(total_pages=None, delay_between_pages_ms=2000):
    """
    Obtiene todas las URLs de proyectos desde todas las páginas.

    Args:
        total_pages: Número de páginas a procesar (default: TOTAL_PAGES o
                     el valor detectado automáticamente del HTML).
        delay_between_pages_ms: Delay entre páginas en ms.

    Returns:
        Lista de dicts con 'title', 'url', 'slug', 'country', 'status'.
    """
    if total_pages is None:
        total_pages = _get_cached_total_pages() or TOTAL_PAGES

    all_projects = []

    for page_num in range(1, total_pages + 1):
        url = f"{BASE_URL}{LISTINGS_PATH}?page={page_num}"
        print(f"\n📄 Obteniendo página {page_num}/{total_pages}: {url}")

        projects, detected_total = parse_listing_page(url)

        # Si esta es la primera página y detectamos un total diferente,
        # ajustamos el rango (solo la primera vez).
        if page_num == 1 and detected_total and detected_total != total_pages:
            print(f"  🔍 Total de páginas detectado en HTML: {detected_total}")
            total_pages = detected_total

        all_projects.extend(projects)
        print(f"  ✅ Página {page_num}: {len(projects)} proyectos encontrados")

        # Cachear el total detectado para futuras ejecuciones
        if page_num == 1 and detected_total:
            _cache_total_pages(detected_total)

        if page_num < total_pages:
            import time
            time.sleep(delay_between_pages_ms / 1000)

    return all_projects


def _get_cached_total_pages():
    """Lee el total de páginas cacheado desde config.py (modo detectado)."""
    try:
        from importlib import import_module
        cfg = import_module("config")
        return getattr(cfg, "TOTAL_PAGES_DETECTED", None)
    except Exception:
        return None


def _cache_total_pages(total):
    """Escribe el total de páginas detectado en config.py como TOTAL_PAGES_DETECTED."""
    try:
        import os
        config_path = os.path.join(os.path.dirname(__file__), "config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        marker = "TOTAL_PAGES_DETECTED"
        if marker in content:
            # Ya existe, reemplazar
            import re
            content = re.sub(
                rf'{marker}\s*=\s*\d+',
                f"{marker} = {total}",
                content,
            )
        else:
            # Agregar después de TOTAL_PAGES
            content = content.replace(
                "TOTAL_PAGES = ",
                f"TOTAL_PAGES = ",
            )
            # Insertar después de la línea de TOTAL_PAGES
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("TOTAL_PAGES = "):
                    lines.insert(i + 1, f"TOTAL_PAGES_DETECTED = {total}")
                    break
            content = "\n".join(lines)

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"  💾 Total de páginas cacheado: {total}")
    except Exception as err:
        logger.warning(f"No se pudo cachear el total de páginas: {err}")


def _detect_total_pages_from_html(soup):
    """
    Detecta el total de páginas desde el elemento de paginación HTML.

    Busca el último enlace numerado en la barra de paginación y extrae
    su número. Si no se encuentra, retorna None.

    Ejemplo del HTML:
        <section class="pagination ...">
            <ul>
                <li><a ... href="?page=1">1</a></li>
                ...
                <li>
                    <a class="... bg-color-fondo-paginacion ..." href="?page=43">43</a>
                </li>
            </ul>
        </section>

    Returns:
        int con el número de la última página, o None si no se detecta.
    """
    pagination = soup.select_one("section.pagination")
    if not pagination:
        return None

    # Buscar todos los enlaces <a> dentro de la paginación que tengan href="?page=N"
    page_links = pagination.select("ul a[href*='page=']")
    if not page_links:
        return None

    max_page = 0
    for link in page_links:
        href = link.get("href", "")
        # Extraer el número de página del href
        import re
        match = re.search(r"page=(\d+)", href)
        if match:
            page_num = int(match.group(1))
            max_page = max(max_page, page_num)

    return max_page if max_page > 0 else None


def parse_listing_page(url):
    """
    Obtiene una página de listado y extrae las tarjetas de proyectos.

    Estructura HTML esperada (por tarjeta):
        <article class="card">
            <a href="/es/trabaja-con-nosotros/convocatorias/{slug}/">
                <img class="img--cover ..." ...>
            </a>
            <h3 class="card__title padding__bottom-spacing-02">
                <a class="no-underline" href="/.../{slug}/">Título</a>
            </h3>
            <p class="p-body-m padding__bottom-spacing-02 text-color-gris-900">
                <strong>Cierre:</strong> 12 octubre 2026
            </p>
            <div class="margin__bottom-spacing-03">
                <p class="card__capacitacion card__capacitacion--abierta">Convocatoria abierta</p>
            </div>
        </article>

    Args:
        url: URL completa de la página.

    Returns:
        tuple (lista_de_dicts, total_pages_detectado) donde:
          - lista_de_dicts tiene 'title', 'url', 'slug', 'country', 'status'
          - total_pages_detectado es un int o None
    """
    html = http_get(url)
    soup = BeautifulSoup(html, "lxml")

    projects = []
    seen_slugs = set()

    # Detectar total de páginas desde el HTML
    detected_total = _detect_total_pages_from_html(soup)

    # Seleccionar todas las tarjetas: article.card
    cards = soup.select("article.card")

    for card in cards:
        # Extraer título y URL desde .card__title a
        title_link = card.select_one(".card__title a")
        if not title_link:
            continue

        href = title_link.get("href", "")
        title = title_link.get_text(strip=True)

        if not href or not title:
            continue

        # Normalizar URL relativa
        full_url = urljoin(BASE_URL, href)

        # Extraer slug
        slug = _extract_slug(full_url)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        # Extraer fecha de cierre desde .p-body-m strong
        closing_date = _extract_closing_date(card)

        # Extraer estado (abierta/cerrada) desde .card__capacitacion
        status_tag = card.select_one(".card__capacitacion")
        status = None
        if status_tag:
            classes = status_tag.get("class", [])
            if "card__capacitacion--cerrada" in classes:
                status = "cerrada"
            elif "card__capacitacion--abierta" in classes:
                status = "abierta"

        # Extraer país del contexto de la tarjeta
        country = _extract_country_from_card(card)

        projects.append({
            "title": title,
            "url": full_url,
            "slug": slug,
            "closing_date": closing_date,
            "status": status,
            "country": country,
        })

    return projects, detected_total


def _extract_slug(url):
    """Extrae el slug del proyecto desde la URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        # La última parte no vacía es el slug (antes del trailing slash)
        return path_parts[-1] if path_parts else "unknown"
    except Exception:
        return "unknown"


def _extract_closing_date(card):
    """Extrae la fecha de cierre desde <p class="p-body-m ..."><strong>Cierre:</strong> ...</p>."""
    p_tag = card.select_one("p.p-body-m, p.text-color-gris-900")
    if not p_tag:
        return None

    strong_tag = p_tag.find("strong")
    if strong_tag:
        # El texto después del <strong>Cierre:</strong>
        date_text = strong_tag.next_sibling
        if date_text:
            return date_text.strip()
        # Fallback: todo el texto del <p> sin el <strong>
        return p_tag.get_text(strip=True).replace("Cierre:", "").strip()

    return p_tag.get_text(strip=True)


def _extract_country_from_card(card):
    """Extrae el país del contexto de la tarjeta.

    Los países aparecen como enlaces con texto simple dentro de la tarjeta,
    o como texto plano en la página. Busca en el texto completo de la card.
    """
    countries = [
        "Argentina", "Bolivia", "Brasil", "Colombia", "Costa Rica",
        "Ecuador", "El Salvador", "España", "Grenada", "Honduras",
        "Jamaica", "México", "Panamá", "Paraguay", "Perú",
        "Portugal", "República Dominicana", "Trinidad y Tobago",
        "Uruguay", "Venezuela", "Chile", "Antigua y Barbuda", "Barbados",
        "Bahamas", "Caribe", "Europa", "Quito", "Lima",
    ]

    card_text = card.get_text(separator=" ", strip=True).lower()

    for country in countries:
        if country.lower() in card_text:
            return country

    return None
