"""
Módulo para obtener avisos de adquisiciones (procurement notices) del BID.

Extiende la idea del scraper de CAF, pero adaptada a lo que realmente es
accesible del lado del BID: en vez de scrapear www.iadb.org/en/project-search
(bloqueado por Cloudflare, ver bids_config.py), descarga el dataset abierto
de avisos de adquisiciones que el BID publica en su portal CKAN
(data.iadb.org). Cada fila trae el proyecto, el aviso y el enlace directo
al documento en idbdocs.iadb.org.
"""

import csv
import io
import os
import time

import requests

from bids_config import CKAN_API_BASE, NOTICES_DATASET_ID, HEADERS, HTTP_CONFIG

_session = None

CACHE_FILENAME = "_notices_cache.csv"
CACHE_MAX_AGE_SECONDS = 12 * 3600  # el dataset no cambia más que a diario


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def _clean(value):
    """Normaliza un valor de celda CSV: None/"" para vacíos o literal "null"."""
    if value is None:
        return None
    value = value.strip()
    if not value or value.lower() == "null":
        return None
    return value


def slugify_project(project_number):
    """Convierte un project number BID en un slug de directorio (ME-T1569 -> me-t1569)."""
    return project_number.lower().replace(" ", "-")


def _cache_path(output_root):
    return os.path.join(output_root, CACHE_FILENAME)


def _load_cached_csv(output_root):
    """Devuelve los bytes del CSV cacheado si existe y no venció, si no None."""
    path = _cache_path(output_root)
    if not os.path.exists(path):
        return None
    age_seconds = time.time() - os.path.getmtime(path)
    if age_seconds > CACHE_MAX_AGE_SECONDS:
        return None
    with open(path, "rb") as f:
        return f.read()


def _save_cache(output_root, content):
    os.makedirs(output_root, exist_ok=True)
    with open(_cache_path(output_root), "wb") as f:
        f.write(content)


def _looks_like_csv(content):
    """Detecta una página de verificación anti-bot (AWS WAF challenge, etc.) en vez del CSV real."""
    head = content[:200].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return False
    return b"," in content[:500]


def _resolve_resource_url(dataset_id):
    """Obtiene la URL de descarga del recurso CSV de un dataset CKAN del BID."""
    response = _get_session().get(
        f"{CKAN_API_BASE}/package_show",
        params={"id": dataset_id},
        timeout=HTTP_CONFIG["timeout_ms"] / 1000,
    )
    response.raise_for_status()
    payload = response.json()
    resources = payload["result"]["resources"]
    if not resources:
        raise RuntimeError(f"El dataset '{dataset_id}' no tiene recursos descargables")
    return resources[0]["url"]


def fetch_all_notices(output_root=None, force_refresh=False):
    """
    Descarga y parsea el dataset de avisos de adquisiciones del BID.

    Si output_root se pasa, cachea el CSV en disco (12h) para no volver a
    descargar el archivo completo en cada corrida — data.iadb.org tiene un
    WAF (AWS) que puede empezar a exigir un challenge JS si se lo golpea
    demasiado seguido desde la misma IP en poco tiempo.

    Args:
        output_root: directorio de salida, usado como ubicación de caché.
        force_refresh: ignora la caché y vuelve a descargar el CSV.

    Returns:
        Lista de dicts con: notice_id, notice_type, country, project_number,
        project_url, notice_title, document_url, project_name,
        publication_date, deadline, sector, project_status.
        Solo incluye filas con project_number, notice_id y document_url.
    """
    content = None
    if output_root and not force_refresh:
        content = _load_cached_csv(output_root)
        if content is not None:
            print("  💾 Usando caché local del dataset (< 12h, evita re-descargar)")

    if content is None:
        csv_url = _resolve_resource_url(NOTICES_DATASET_ID)

        # data.iadb.org sirve el CSV desde un CloudFront con WAF: un cache-hit
        # en el borde pasa directo, un cache-miss puede caer en un challenge
        # anti-bot. Reintentar unas pocas veces suele alcanzar otro borde/estado.
        retries = HTTP_CONFIG["retries"]
        retry_delay_ms = HTTP_CONFIG["retry_delay_ms"]
        last_error = None

        for attempt in range(1, retries + 1):
            response = _get_session().get(csv_url, timeout=HTTP_CONFIG["timeout_ms"] / 1000)
            response.raise_for_status()

            if _looks_like_csv(response.content):
                content = response.content
                break

            last_error = (
                "data.iadb.org devolvió una página de verificación en vez del CSV "
                f"(HTTP {response.status_code}, waf-action={response.headers.get('x-amzn-waf-action')})."
            )
            if attempt < retries:
                print(f"  ⚠ Intento {attempt}/{retries}: challenge anti-bot, reintentando...")
                time.sleep(retry_delay_ms * attempt / 1000)

        if content is None:
            raise RuntimeError(
                f"{last_error} Es un challenge anti-bot de AWS WAF en el endpoint de "
                "descarga, probablemente temporal por volumen de pedidos — probá de "
                "nuevo en un rato."
            )

        if output_root:
            _save_cache(output_root, content)

    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))

    notices = []
    for row in reader:
        project_number = _clean(row.get("projectnumber"))
        document_url = _clean(row.get("documenturl"))
        notice_id = _clean(row.get("noticeid"))

        if not project_number or not document_url or not notice_id:
            continue

        notices.append({
            "notice_id": notice_id,
            "notice_type": _clean(row.get("type")),
            "country": _clean(row.get("countryname")),
            "project_number": project_number,
            "project_url": _clean(row.get("proyecturl")),
            "notice_title": _clean(row.get("noticetitle")),
            "document_url": document_url,
            "project_name": _clean(row.get("projectname")),
            "publication_date": _clean(row.get("publicationdate")),
            "deadline": _clean(row.get("deadline")),
            "sector": _clean(row.get("sector")),
            "project_status": _clean(row.get("projectstatus")),
        })

    return notices
