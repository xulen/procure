"""
NO SE USA — reemplazado por bids_notices.py + bids_documents.py.

www.iadb.org/en/project/{...} está bloqueado por Cloudflare Bot Fight Mode
(bloquea incluso navegación real con Playwright, no solo requests). Se deja
este archivo como referencia de los selectores HTML, sin importarlo desde
orchestrator.py. Ver bids_config.py para el detalle.

Módulo para scrapear páginas individuales de proyectos del BID.
Usa requests + BeautifulSoup — el HTML se sirve estáticamente desde el BID.

Extrae los documentos (PDFs) organizados por fase y metadata del proyecto.

Estructura de la página de detalle:
  - Project Detail: Country, Project Number, Approval Date, Status, Type, Sector,
    Subsector, Lending Instrument, Total Cost, etc.
  - Project Documentation: organizada por fases (Preparation, Procurement,
    Implementation, Closing) con enlaces a document.cfm?id=...
"""

import logging
import re
from urllib.parse import urljoin, urlparse, parse_qs

from bids_config import BASE_URL, COUNTRY_CODES

logger = logging.getLogger(__name__)


def fetch_project_details(project_url):
    """
    Obtiene la información completa de un proyecto dado su URL.

    Args:
        project_url: URL completa del proyecto.

    Returns:
        dict con 'title', 'url', 'project_number', 'documents', 'metadata'.
    """
    print(f"\n📋 Obteniendo detalles del proyecto: {project_url}")

    html = http_get(project_url)
    return parse_project_page(html, project_url)


def http_get(url):
    """Importa la función http_get del módulo principal."""
    from http_client import http_get as _http_get
    return _http_get(url)


def parse_project_page(html, url):
    """
    Parsea una página de proyecto BID y extrae metadata + documentos.

    Args:
        html: HTML de la página.
        url: URL del proyecto (para resolver URLs relativas).

    Returns:
        dict con datos del proyecto.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    # Extraer título principal
    title = _extract_main_title(soup)

    # Extraer project number desde la URL
    project_number = _extract_project_number(url)

    # Extraer metadata del proyecto
    metadata = {
        "country": _extract_country(soup),
        "sector": _extract_sector(soup),
        "status": _extract_status(soup),
        "approval_date": _extract_approval_date(soup),
        "project_type": _extract_project_type(soup),
        "subsector": _extract_subsector(soup),
        "total_cost": _extract_total_cost(soup),
        "original_amount": _extract_original_amount(soup),
        "lending_instrument": _extract_lending_instrument(soup),
        "description": _extract_description(soup),
    }

    # Extraer documentos organizados por fase
    documents = _extract_documents(soup, url)

    return {
        "title": title,
        "url": url,
        "project_number": project_number,
        "documents": documents,
        "metadata": metadata,
    }


def _extract_main_title(soup):
    """Extrae el título principal del proyecto (h1)."""
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    # Fallback: meta title
    title_tag = soup.find("title")
    if title_tag:
        text = title_tag.get_text(strip=True)
        return text.split("|")[0].split("-")[0].strip() if text else "Sin título"

    return "Sin título"


def _extract_project_number(url):
    """Extrae el project number desde la URL."""
    try:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        # /en/project/{PROJECT_NUMBER} → última parte
        return path_parts[-1] if path_parts else "unknown"
    except Exception:
        return "unknown"


def _extract_field(soup, label_pattern):
    """
    Busca un campo en la sección Project Detail.

    El HTML tiene estructura de lista con dt/dd:
        <dt>Country</dt><dd>Mexico</dd>
        <dt>Project Number</dt><dd>ME-T1569</dd>
    """
    text = soup.get_text()
    match = re.search(
        rf'{label_pattern}\s*[:\-–]\s*([^<]+)',
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


def _extract_country(soup):
    """Extrae el país del proyecto."""
    # Buscar en la sección Project Detail
    project_detail = soup.select_one("h2:contains('Project Detail')")
    if not project_detail:
        # Fallback: buscar por texto
        for dt in soup.find_all("dt"):
            if dt.get_text(strip=True).lower() == "country":
                dd = dt.find_next_sibling("dd")
                if dd:
                    return dd.get_text(strip=True)

    text = soup.get_text()
    match = re.search(r'Country\s*[:\-–]\s*([^<]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_sector(soup):
    """Extrae el sector del proyecto."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "sector":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True).upper()

    text = soup.get_text()
    match = re.search(r'Sector\s*[:\-–]\s*([^<]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip().upper()
    return None


def _extract_status(soup):
    """Extrae el estado del proyecto."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "project status":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)

    text = soup.get_text()
    match = re.search(r'Project Status\s*[:\-–]\s*([^<]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_approval_date(soup):
    """Extrae la fecha de aprobación."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "approval date":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)

    text = soup.get_text()
    match = re.search(r'Approval Date\s*[:\-–]\s*([^<]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_project_type(soup):
    """Extrae el tipo de proyecto (Technical Cooperation, Loan, Grant, etc.)."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "project type":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)
    return None


def _extract_subsector(soup):
    """Extrae el subsector del proyecto."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "subsector":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)
    return None


def _extract_total_cost(soup):
    """Extrae el costo total del proyecto."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "total cost":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)
    return None


def _extract_original_amount(soup):
    """Extrae el monto original aprobado."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "original amount approved":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)
    return None


def _extract_lending_instrument(soup):
    """Extrae el instrumento de préstamo."""
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == "lending instrument":
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)
    return None


def _extract_description(soup):
    """Extrae la descripción del proyecto (primer párrafo largo)."""
    for p_tag in soup.find_all("p"):
        text = p_tag.get_text(strip=True)
        if len(text) > 100:
            return text[:500] + ("..." if len(text) > 500 else "")

    # Fallback: buscar en el primer <h2> siguiente al título
    h2 = soup.find("h2")
    if h2:
        next_p = h2.find_next_sibling("p")
        if next_p:
            text = next_p.get_text(strip=True)
            if len(text) > 50:
                return text[:500] + ("..." if len(text) > 500 else "")

    return None


def _extract_documents(soup, base_url):
    """
    Extrae los documentos descargables de la página, organizados por fase.

    Busca enlaces a document.cfm?id=... dentro de las secciones de fase:
      - Preparation Phase
      - Procurement Phase
      - Implementation Phase
      - Closing Phase

    Returns:
        lista de dicts con 'name', 'url', 'phase', 'date', 'language'.
    """
    documents = []
    seen_urls = set()

    # Buscar secciones de fase (h3 o h4 con texto de fase)
    phase_patterns = [
        "Preparation Phase",
        "Procurement Phase",
        "Implementation Phase",
        "Closing Phase",
        "Completed Projects",
    ]

    # Encontrar todos los encabezados que indiquen una fase
    all_headers = soup.find_all(["h2", "h3", "h4"])

    current_phase = None
    phase_elements = []

    for header in all_headers:
        text = header.get_text(strip=True)
        if any(pattern.lower() in text.lower() for pattern in phase_patterns):
            current_phase = text
            continue

        # Si estamos en una fase, recolectar elementos hasta la siguiente fase
        if current_phase:
            phase_elements.append((current_phase, header))

    # Para cada elemento dentro de una fase, buscar enlaces de documentos
    for phase, element in phase_elements:
        # Buscar enlaces document.cfm en los hermanos siguientes
        sibling = element.find_next_sibling()
        while sibling:
            # Si encontramos otro header, terminamos esta fase
            if sibling.name in ("h2", "h3", "h4"):
                next_text = sibling.get_text(strip=True)
                if any(p.lower() in next_text.lower() for p in phase_patterns):
                    break

            # Buscar enlaces a document.cfm
            for a_tag in sibling.find_all("a", href=True):
                href = a_tag["href"]

                # Normalizar URL relativa
                if not href.startswith(("http://", "https://")):
                    try:
                        href = urljoin(base_url, href)
                    except Exception:
                        continue

                # Solo documentos del BID
                if "document.cfm" not in href:
                    continue

                if href in seen_urls:
                    continue
                seen_urls.add(href)

                # Extraer nombre del documento
                doc_name = a_tag.get_text(strip=True) or _extract_doc_name_from_url(href)

                # Extraer fecha y lenguaje (texto adyacente)
                date = None
                language = None
                parent = a_tag.parent

                # Buscar en el mismo contenedor
                container = a_tag.find_parent(["div", "td", "li"])
                if container:
                    container_text = container.get_text()
                    date_match = re.search(
                        r'(\w+\.\s+\d{1,2},?\s+\d{4})',
                        container_text,
                    )
                    if date_match:
                        date = date_match.group(1)

                    lang_match = re.search(
                        r'\b(Spanish|English|Portuguese)\b',
                        container_text,
                        re.IGNORECASE,
                    )
                    if lang_match:
                        language = lang_match.group(1)

                documents.append({
                    "name": doc_name,
                    "url": href,
                    "phase": phase,
                    "date": date,
                    "language": language,
                })

            # Mover al siguiente hermano
            sibling = sibling.find_next_sibling()

    return documents


def _extract_doc_name_from_url(url):
    """Extrae un nombre de documento desde la URL document.cfm."""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        doc_id = qs.get("id", ["unknown"])[0]
        # Formato: EZIDB001434-932639620-4 → TC_Abstract o similar
        return f"BID_Document_{doc_id[:8]}.pdf"
    except Exception:
        return "BID_document.pdf"


def _slugify_project(project_number):
    """
    Convierte un project number BID en un slug válido para directorio.

    Ejemplo: ME-T1569 → me-t1569
             RG-T5025 → rg-t5025
    """
    return project_number.lower().replace(" ", "-")
