"""
Módulo para obtener los documentos de una página de detalle de proyecto BID.

La metadata del proyecto (título, país, sector, estado, fecha) ya viene
completa desde el listado (bids_listings.py) — no hace falta repetirla acá.

Los documentos se renderizan como un web component:
    <idb-document-card url="https://www.iadb.org/document.cfm?id=..."
                        slot="grid-module-N" level="h3">
      <div slot="detail">TC Abstract</div>
      <div slot="heading">TC Abstract ME-T1569.pdf</div>
      <div slot="subtitle">May. 06, 2026</div>
      <div slot="cta">English</div>
    </idb-document-card>

No hay <a href> plano — la URL real vive en el atributo `url` del elemento
custom, no dentro de su Shadow DOM, así que BeautifulSoup la puede leer
directo del HTML servido por bids_browser.py.
"""

from bs4 import BeautifulSoup


def _slot_text(card, slot_name):
    el = card.find(attrs={"slot": slot_name})
    return el.get_text(strip=True) if el else None


def extract_documents(html):
    """
    Extrae los documentos (<idb-document-card>) de una página de detalle.

    Returns:
        Lista de dicts únicos por URL: {'url', 'name', 'category', 'date', 'language'}.
    """
    soup = BeautifulSoup(html, "lxml")
    seen = set()
    documents = []

    for card in soup.find_all("idb-document-card"):
        url = card.get("url")
        if not url or "document.cfm" not in url or url in seen:
            continue
        seen.add(url)

        documents.append({
            "url": url,
            "name": _slot_text(card, "heading"),
            "category": _slot_text(card, "detail"),
            "date": _slot_text(card, "subtitle"),
            "language": _slot_text(card, "cta"),
        })

    return documents


def fetch_project_documents(browser, project_url):
    """
    Navega a la página de detalle de un proyecto y devuelve sus documentos.

    Args:
        browser: instancia de BidBrowser ya iniciada.
        project_url: URL completa del proyecto (/en/project/{project_number}).

    Returns:
        Lista de dicts (ver extract_documents).
    """
    html = browser.get_html(project_url)
    return extract_documents(html)
