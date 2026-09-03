"""
Módulo para scrapear la lista de proyectos del BID.

Recibe un BidBrowser ya iniciado (ver bids_browser.py) — es lo que permite
pasar el bloqueo de Cloudflare de www.iadb.org.

Estructura real de /en/project-search?page=N (verificada en vivo, 2026-09):
  - Paginación 0-indexed: page=0 es la primera página, ~2805 páginas en total.
  - Orden por defecto: más recientes primero.
  - Tabla anclada por th#view-field-project-number-table-column — no confiar
    en la clase CSS de la tabla, cambió al menos una vez ya.
  - Columnas: Project Number, Operation Number, Country, Sector,
    Title (+ link a /en/project/{project_number}), Total Cost,
    Project Status, Approval Date.
"""

import re

from bs4 import BeautifulSoup

from bids_config import BASE_URL, LISTINGS_PATH


def slugify_project(project_number):
    """Convierte un project number BID en un slug de directorio (ME-T1569 -> me-t1569)."""
    return project_number.lower().replace(" ", "-")


def _clean(text):
    text = (text or "").strip()
    return text or None


def _detect_total_pages(soup):
    """Detecta la cantidad total de páginas a partir del link 'Last' del paginador."""
    last_link = soup.select_one("a[aria-label='Last']")
    if not last_link or not last_link.has_attr("href"):
        return None
    match = re.search(r"page=(\d+)", last_link["href"])
    if not match:
        return None
    return int(match.group(1)) + 1  # 0-indexed -> cantidad total de páginas


def parse_listing_page(html):
    """
    Parsea una página de listado del BID.

    Returns:
        tuple (lista_de_proyectos, total_paginas_detectado_o_None)
    """
    soup = BeautifulSoup(html, "lxml")

    anchor_th = soup.find("th", id="view-field-project-number-table-column")
    table = anchor_th.find_parent("table") if anchor_th else None

    projects = []
    if table:
        for tr in table.select("tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < 8:
                continue

            project_number = _clean(cells[0].get_text())
            if not project_number:
                continue

            title_link = cells[4].find("a")
            title = _clean(title_link.get_text()) if title_link else _clean(cells[4].get_text())
            href = title_link["href"] if title_link and title_link.has_attr("href") else f"/en/project/{project_number}"
            url = href if href.startswith("http") else f"{BASE_URL}{href}"

            projects.append({
                "project_number": project_number,
                "slug": slugify_project(project_number),
                "title": title or project_number,
                "url": url,
                "country": _clean(cells[2].get_text()),
                "sector": _clean(cells[3].get_text()),
                "total_cost": _clean(cells[5].get_text()),
                "status": _clean(cells[6].get_text()),
                "approval_date": _clean(cells[7].get_text()),
            })

    return projects, _detect_total_pages(soup)


def fetch_all_listings(browser, total_pages=None, start_page=0):
    """
    Recorre páginas de listado del BID empezando por start_page (0-indexed).

    Args:
        browser: instancia de BidBrowser ya iniciada (browser.start()).
        total_pages: cuántas páginas recorrer (default: 5).
        start_page: página 0-indexed por la que empezar.

    Returns:
        Lista de dicts de proyecto (puede tener duplicados entre corridas,
        el caller filtra con index.py — ver orchestrator.py).
    """
    total_pages = total_pages or 5

    all_projects = []
    detected_total = None

    for i in range(total_pages):
        page_index = start_page + i
        url = f"{BASE_URL}{LISTINGS_PATH}?page={page_index}"
        print(f"\n📄 Obteniendo página {i + 1}/{total_pages} (page={page_index}): {url}")

        html = browser.get_html(url)
        projects, detected = parse_listing_page(html)
        if detected:
            detected_total = detected

        if not projects:
            print("  ⚠ Sin proyectos en esta página, se corta la paginación")
            break

        all_projects.extend(projects)
        print(f"  ✅ {len(projects)} proyecto(s) encontrados")

        if detected_total and page_index >= detected_total - 1:
            print("  📋 Se llegó a la última página del listado")
            break

    return all_projects
