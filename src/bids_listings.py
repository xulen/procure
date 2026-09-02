"""
NO SE USA — reemplazado por bids_notices.py.

www.iadb.org/en/project-search está bloqueado por Cloudflare Bot Fight Mode
(bloquea incluso navegación real con Playwright, no solo requests). Se deja
este archivo como referencia de los selectores HTML, sin importarlo desde
orchestrator.py. Ver bids_config.py para el detalle.

Módulo para scrapear la lista de proyectos del BID (Banco Interamericano de Desarrollo).
Usa requests + BeautifulSoup — el HTML se sirve estáticamente desde el BID.

Extrae de cada fila de tabla (<tr>) en /en/project-search?page=N:
  - project_number: código único (ej: ME-T1569, RG-T5025)
  - title: título del proyecto
  - url: URL completa al detalle del proyecto
  - country: país beneficiario
  - sector: sector del proyecto
  - total_cost: costo total
  - status: estado del proyecto (Implementation, Preparation, Closed, Cancelled)
  - approval_date: fecha de aprobación

Paginación automática: detecta el total de páginas desde el texto "Total NNNN"
y lo guarda en bids_config para reutilizarlo sin rescanner.
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from bids_config import (
    BASE_URL, LISTINGS_PATH, HEADERS, TOTAL_PAGES,
)
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
        Lista de dicts con project_number, title, url, country, sector,
        total_cost, status, approval_date.
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
    """Lee el total de páginas cacheado desde bids_config.py (modo detectado)."""
    try:
        from importlib import import_module
        cfg = import_module("bids_config")
        return getattr(cfg, "TOTAL_PAGES_DETECTED", None)
    except Exception:
        return None


def _cache_total_pages(total):
    """Escribe el total de páginas detectado en bids_config.py como TOTAL_PAGES_DETECTED."""
    try:
        import os
        config_path = os.path.join(os.path.dirname(__file__), "bids_config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        marker = "TOTAL_PAGES_DETECTED"
        if marker in content:
            # Ya existe, reemplazar
            content = re.sub(
                rf'{marker}\s*=\s*\d+',
                f"{marker} = {total}",
                content,
            )
        else:
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


def _detect_total_from_html(soup):
    """
    Detecta el total de proyectos desde el texto "Total NNNN" en la página.

    Returns:
        int con el número total de proyectos, o None si no se detecta.
    """
    # Buscar "Total 28044" u otro patrón similar
    text = soup.get_text()
    match = re.search(r'Total\s+(\d+)', text)
    if match:
        total_projects = int(match.group(1))
        # Cada página muestra 10 proyectos
        projects_per_page = 10
        return (total_projects + projects_per_page - 1) // projects_per_page
    return None


def parse_listing_page(url):
    """
    Obtiene una página de listado y extrae las filas de la tabla de proyectos.

    Estructura HTML esperada:
        <table class="views-table ...">
            <tbody>
                <tr class="odd/even">
                    <td><a href="/en/project/ME-T1569">ME-T1569</a></td>
                    <td>ATN/OC-22726-HO</td>
                    <td>Mexico</td>
                    <td>SOCIAL INVESTMENT</td>
                    <td><a href="/en/project/ME-T1569">Title...</a></td>
                    <td>800,000.00</td>
                    <td>Implementation</td>
                    <td>Sep. 1 2026</td>
                </tr>
            </tbody>
        </table>

    Args:
        url: URL completa de la página.

    Returns:
        tuple (lista_de_dicts, total_pages_detectado) donde:
          - lista_de_dicts tiene project_number, title, url, country, sector,
            total_cost, status, approval_date
          - total_pages_detectado es un int o None
    """
    html = http_get(url)
    soup = BeautifulSoup(html, "lxml")

    projects = []
    seen_numbers = set()

    # Detectar total de proyectos desde el HTML
    detected_total = _detect_total_from_html(soup)

    # Seleccionar todas las filas de la tabla de proyectos
    # La tabla principal tiene clase views-table y rows con tr.odd o tr.even
    table_rows = soup.select("table.views-table tbody tr")

    if not table_rows:
        # Fallback: buscar cualquier tr que contenga un enlace a /en/project/
        project_links = soup.select('a[href*="/en/project/"]')
        if project_links:
            for link in project_links:
                href = link.get("href", "")
                project_num = _extract_project_number(href)
                if project_num and project_num not in seen_numbers:
                    seen_numbers.add(project_num)
                    title = link.get_text(strip=True)
                    full_url = urljoin(BASE_URL, href)
                    projects.append({
                        "project_number": project_num,
                        "title": title,
                        "url": full_url,
                        "country": None,
                        "sector": None,
                        "total_cost": None,
                        "status": None,
                        "approval_date": None,
                    })
            return projects, detected_total

    for row in table_rows:
        # Extraer celdas de la fila
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        # Columna 0: Project Number (con enlace)
        num_link = cells[0].find("a", href=True)
        project_number = ""
        if num_link:
            project_number = num_link.get_text(strip=True) or _extract_project_number(num_link["href"])
        else:
            project_number = cells[0].get_text(strip=True)

        if not project_number or project_number == "Project Number":
            continue

        if project_number in seen_numbers:
            continue
        seen_numbers.add(project_number)

        # Columna 1: Operation Number (opcional, no se almacena directamente)
        # operation_number = cells[1].get_text(strip=True) if len(cells) > 1 else ""

        # Columna 2: Country
        country = cells[2].get_text(strip=True) if len(cells) > 2 else None

        # Columna 3: Sector
        sector = cells[3].get_text(strip=True).upper() if len(cells) > 3 else None

        # Columna 4: Title (con enlace)
        title_link = cells[4].find("a", href=True) if len(cells) > 4 else None
        title = ""
        project_url = ""
        if title_link:
            title = title_link.get_text(strip=True)
            project_url = urljoin(BASE_URL, title_link["href"])

        if not title:
            title = cells[4].get_text(strip=True) if len(cells) > 4 else "Sin título"

        # Columna 5: Total Cost
        total_cost = cells[5].get_text(strip=True) if len(cells) > 5 else None

        # Columna 6: Project Status
        status = cells[6].get_text(strip=True) if len(cells) > 6 else None

        # Columna 7: Approval Date
        approval_date = cells[7].get_text(strip=True) if len(cells) > 7 else None

        projects.append({
            "project_number": project_number,
            "title": title,
            "url": project_url or f"{BASE_URL}/en/project/{project_number}",
            "country": country if country != "-" else None,
            "sector": sector if sector and sector != "-" else None,
            "total_cost": total_cost if total_cost and total_cost != "-" else None,
            "status": status if status and status != "-" else None,
            "approval_date": approval_date if approval_date and approval_date != "-" else None,
        })

    return projects, detected_total


def _extract_project_number(url):
    """Extrae el project number desde la URL del proyecto."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        # La última parte no vacía es el project number
        return path_parts[-1] if path_parts else "unknown"
    except Exception:
        return "unknown"
