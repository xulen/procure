"""
Módulo para scrapear páginas individuales de proyectos/convocatorias.
Usa requests + BeautifulSoup — el HTML se sirve estáticamente desde CAF.

Extrae los links a documentos (PDFs) y metadata del proyecto.
"""

import logging
import re
from urllib.parse import urljoin, urlparse

from config import BASE_URL, COUNTRY_CODES
from http_client import http_get

logger = logging.getLogger(__name__)


def fetch_project_details(project_url):
    """
    Obtiene la información completa de un proyecto dado su URL.

    Args:
        project_url: URL completa del proyecto.

    Returns:
        dict con 'title', 'url', 'slug', 'documents', 'metadata'.
    """
    print(f"\n📋 Obteniendo detalles del proyecto: {project_url}")

    html = http_get(project_url)
    return parse_project_page(html, project_url)


def parse_project_page(html, url):
    """
    Parsea una página de proyecto y extrae documentos.

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

    # Extraer slug desde la URL
    slug = _extract_slug(url)

    # Extraer documentos (PDFs)
    documents = _extract_documents(soup, url)

    # Extraer metadata adicional
    metadata = {
        "closing_date": _extract_closing_date(soup),
        "description": _extract_description(soup),
        "countries": _extract_countries(soup),
    }

    return {
        "title": title,
        "url": url,
        "slug": slug,
        "documents": documents,
        "metadata": metadata,
    }


def _extract_main_title(soup):
    """Extrae el título principal del proyecto."""
    # Buscar <h1> o primer <h2> con título
    for tag_name in ["h1", "h2"]:
        tag = soup.find(tag_name)
        if tag:
            text = tag.get_text(separator=" ", strip=True)
            return text.strip() or "Sin título"

    # Fallback: meta title
    title_tag = soup.find("title")
    if title_tag:
        text = title_tag.get_text(strip=True)
        return text.split("-")[0].strip() if text else "Sin título"

    return "Sin título"


def _extract_slug(url):
    """Extrae el slug del proyecto desde la URL."""
    try:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        return path_parts[-1] if path_parts else "unknown"
    except Exception:
        return "unknown"


# Extensiones de archivos descargables que se deben extraer del contenido
# principal de la convocatoria (main.post-convoc-licit).
# Se incluyen formatos de documento, hoja de cálculo, presentación,
# archivos comprimidos y datos planos.
DOWNLOADABLE_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".csv", ".txt",
)


def _is_downloadable_url(url):
    """
    Verifica si una URL apunta a un archivo descargable.

    Comprueba la extensión del archivo (case-insensitive).
    """
    url_lower = url.lower()
    # Eliminar query strings para verificar la extensión
    url_no_query = url_lower.split("?")[0]
    return any(url_no_query.endswith(ext) for ext in DOWNLOADABLE_EXTENSIONS)


def _extract_documents(soup, base_url):
    """
    Extrae los links a documentos descargables de la página.

    Solo busca dentro del elemento <main class="post-convoc-licit">,
    que es el contenedor principal del contenido de la convocatoria.
    Esto garantiza que solo se descarguen documentos específicos de la
    convocatoria y no archivos genéricos del sitio (footer, header, etc.).

    Soporta múltiples tipos de archivo: PDF, DOC/DOCX, XLS/XLSX, PPT/PPTX,
    ODT/ODS/ODP, ZIP, RAR, CSV, entre otros.
    """
    documents = []
    seen_urls = set()

    # --- Paso 1: Extraer SOLO desde main.post-convoc-licit ---
    main_content = soup.select_one("main.post-convoc-licit")
    if not main_content:
        # Fallback: si no se encuentra el main, buscar cualquier elemento
        # con 'post-convoc' en la clase (variantes posibles)
        main_content = soup.select_one("[class*='post-convoc']")

    if main_content:
        # Buscar todos los enlaces <a> dentro del contenido principal
        for a_tag in main_content.find_all("a", href=True):
            href = a_tag["href"]

            # Normalizar URL relativa
            if not href.startswith(("http://", "https://")):
                try:
                    href = urljoin(base_url, href)
                except Exception:
                    continue

            # Solo archivos descargables (múltiples extensiones)
            if not _is_downloadable_url(href):
                continue

            if href in seen_urls:
                continue
            seen_urls.add(href)

            doc_name = a_tag.get_text(strip=True) or _extract_file_name(href)
            documents.append({"name": doc_name, "url": href})

        # Buscar en atributos src/data-url/data-href de imágenes/media
        # dentro del mismo main content
        for tag in main_content.find_all(True):
            if tag.name == "a":
                continue  # Ya procesado arriba

            for attr in ["src", "data-url", "data-href"]:
                value = tag.get(attr)
                if value and _is_downloadable_url(value):
                    file_url = value
                    if not file_url.startswith(("http://", "https://")):
                        try:
                            file_url = urljoin(base_url, file_url)
                        except Exception:
                            continue

                    if file_url in seen_urls:
                        continue
                    seen_urls.add(file_url)

                    doc_name = tag.get("alt", "") or _extract_file_name(file_url)
                    documents.append({"name": doc_name, "url": file_url})

    # --- Paso 2: Fallback — buscar URLs de /media/ en el HTML crudo ---
    # Solo si no se encontraron documentos en el main content
    if not documents:
        # Patrón ampliado para múltiples extensiones
        ext_pattern = "|".join(
            ext.lstrip(".") for ext in DOWNLOADABLE_EXTENSIONS
        )
        media_pattern = rf'href="(/media/\d+/[^"]+\.(?:{ext_pattern}))"'
        for match in re.finditer(media_pattern, soup.decode(), re.IGNORECASE):
            file_url = match.group(1)
            full_url = BASE_URL + file_url
            if full_url not in seen_urls:
                seen_urls.add(full_url)
                documents.append({
                    "name": _extract_file_name(full_url),
                    "url": full_url,
                })

    return documents


def _extract_closing_date(soup):
    """Extrae la fecha de cierre de la convocatoria."""
    text = soup.get_text(separator=" ", strip=True)

    # Buscar patrones como "Cierre:" o "Fecha de cierre"
    closure_match = re.search(
        r'(?:cierre|fecha\s*de?\s*cierre)\s*[:\u2013-]\s*([^\n<]+)',
        text,
        re.IGNORECASE,
    )
    if closure_match:
        return closure_match.group(1).strip()

    # Buscar rango de fechas
    date_range = re.search(
        r'Convocatoria\s*del\s*(.+?)\s*(?:al|hasta)\s*(\d+\s+de\s+\w+\s+\d{4})',
        text,
        re.IGNORECASE,
    )
    if date_range:
        return f"Hasta: {date_range.group(2).strip()}"

    return None


def _extract_description(soup):
    """Extrae la descripción del proyecto (primer párrafo largo)."""
    for p_tag in soup.find_all("p"):
        text = p_tag.get_text(strip=True)
        if len(text) > 100:
            return text[:300] + ("..." if len(text) > 300 else "")

    return None


def _extract_countries(soup):
    """Extrae los países mencionados en la página."""
    text = soup.get_text(separator=" ", strip=True).lower()
    countries = []

    for name, code in COUNTRY_CODES.items():
        if name.lower() in text:
            countries.append({"name": name, "code": code})

    return countries


def _extract_file_name(url):
    """Extrae el nombre de archivo desde una URL."""
    try:
        parsed = urlparse(url)
        pathname = parsed.path
        filename = pathname.split("/")[-1] or "documento.pdf"
        return filename
    except Exception:
        parts = url.split("/")
        return parts[-1] if parts else "documento.pdf"
