"""
Módulo para obtener y descargar los documentos de un proyecto del Banco
Mundial, vía su API pública de Documents & Reports (ver worldbank_config.py).
"""

import re
import time

import requests

from worldbank_config import DOCS_API, HEADERS, HTTP_CONFIG

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def fetch_project_documents(project_id, rows=200):
    """
    Devuelve los documentos publicados de un proyecto del Banco Mundial.

    Args:
        project_id: id del proyecto (ej. "P181166").
        rows: máximo de documentos a traer.

    Returns:
        Lista de dicts: {'id', 'name', 'doc_type', 'date', 'language', 'pdf_url'}.
    """
    response = _get_session().get(
        DOCS_API,
        params={
            "format": "json",
            "projectid": project_id,
            "rows": rows,
        },
        timeout=HTTP_CONFIG["timeout_ms"] / 1000,
    )
    response.raise_for_status()
    payload = response.json()

    documents = []
    for doc_id, data in payload.get("documents", {}).items():
        if not isinstance(data, dict):
            continue
        pdf_url = data.get("pdfurl")
        if not pdf_url:
            continue

        name = data.get("display_title")
        if not name:
            docna = data.get("docna") or {}
            name = docna.get("0", {}).get("docna") if isinstance(docna, dict) else None

        documents.append({
            "id": doc_id,
            "name": name or doc_id,
            "doc_type": data.get("docty"),
            "date": data.get("docdt"),
            "language": data.get("lang"),
            "pdf_url": pdf_url,
        })

    return documents


def download_document(url, fallback_name="worldbank_document.pdf", retries=None, retry_delay_ms=None):
    """Descarga un documento del Banco Mundial (documents.worldbank.org)."""
    retries = retries or HTTP_CONFIG["retries"]
    retry_delay_ms = retry_delay_ms or HTTP_CONFIG["retry_delay_ms"]

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = _get_session().get(
                url,
                timeout=HTTP_CONFIG["timeout_ms"] / 1000,
                allow_redirects=True,
            )
            response.raise_for_status()

            disposition = response.headers.get("Content-Disposition", "")
            match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
            filename = match.group(1) if match else fallback_name

            return {
                "buffer": response.content,
                "size": len(response.content),
                "filename": filename,
                "content_type": response.headers.get("Content-Type", ""),
            }

        except Exception as err:
            last_error = err
            if attempt < retries:
                time.sleep(retry_delay_ms * attempt / 1000)

    raise last_error
