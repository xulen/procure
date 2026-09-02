"""
Descarga de documentos de adquisiciones del BID.

Los enlaces del dataset apuntan a idbdocs.iadb.org, que redirige
(idbdocs.iadb.org -> ezws.iadb.org -> bucket S3 público) sin pedir cookies
ni sesión — a diferencia de www.iadb.org, no está detrás de Cloudflare.
"""

import re
import time

import requests

from bids_config import HEADERS, HTTP_CONFIG

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def _filename_from_headers(response, fallback):
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
    if match:
        return match.group(1)
    return fallback


def download_document(url, fallback_name="BID_document.pdf", retries=None, retry_delay_ms=None):
    """
    Descarga un documento de adquisiciones del BID.

    Args:
        url: URL del documento (idbdocs.iadb.org/wsdocs/getdocument.aspx?docnum=...).
        fallback_name: nombre a usar si el servidor no manda Content-Disposition.

    Returns:
        dict con 'buffer' (bytes), 'size', 'filename', 'content_type'.
    """
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

            return {
                "buffer": response.content,
                "size": len(response.content),
                "filename": _filename_from_headers(response, fallback_name),
                "content_type": response.headers.get("Content-Type", ""),
            }

        except Exception as err:
            last_error = err
            if attempt < retries:
                time.sleep(retry_delay_ms * attempt / 1000)

    raise last_error
