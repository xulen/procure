"""
Módulo para obtener la lista de proyectos del Banco Mundial vía su API
pública de proyectos (ver worldbank_config.py).
"""

import requests

from worldbank_config import PROJECTS_API, REGION_FILTER, STATUS_FILTER, HEADERS, HTTP_CONFIG, ROWS_PER_PAGE

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def slugify_project(project_id):
    """Convierte un project id del Banco Mundial en un slug de directorio (P181166 -> p181166)."""
    return project_id.lower()


def _clean(value):
    if value is None:
        return None
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if v)
    value = str(value).strip()
    return value or None


def parse_projects_page(payload):
    """Convierte la respuesta cruda de la API en una lista de dicts de proyecto."""
    projects = []
    for project_id, data in payload.get("projects", {}).items():
        if not isinstance(data, dict):
            continue

        projects.append({
            "project_id": project_id,
            "slug": slugify_project(project_id),
            "title": _clean(data.get("project_name")) or project_id,
            "url": _clean(data.get("url")) or (
                f"https://projects.worldbank.org/en/projects-operations/project-detail/{project_id}"
            ),
            "country": _clean(data.get("countryname")) or _clean(data.get("countryshortname")),
            "status": _clean(data.get("projectstatusdisplay")) or _clean(data.get("status")),
            "approval_date": _clean(data.get("boardapprovaldate")),
            "closing_date": _clean(data.get("closingdate")),
            "total_commitment": _clean(data.get("totalcommamt")),
        })

    return projects


def fetch_all_projects(total_pages=None, rows_per_page=None, region=None, status=None):
    """
    Recorre páginas de la API de proyectos del Banco Mundial, orden más
    reciente primero (por fecha de aprobación).

    Args:
        total_pages: cuántas páginas recorrer (default: 3).
        rows_per_page: proyectos por página (default: ROWS_PER_PAGE).
        region: filtro de región exacto (default: REGION_FILTER, LAC).
        status: filtro de estado (default: STATUS_FILTER, "Active^Pipeline").
                Valores separados por ^ (OR): Active, Pipeline, Closed, etc.

    Returns:
        Lista de dicts de proyecto (puede tener duplicados entre corridas,
        el caller filtra con index.py — ver orchestrator.py).
    """
    total_pages = total_pages or 3
    rows_per_page = rows_per_page or ROWS_PER_PAGE
    region = region or REGION_FILTER
    status = status or STATUS_FILTER

    all_projects = []

    for i in range(total_pages):
        offset = i * rows_per_page
        print(f"\n📄 Obteniendo página {i + 1}/{total_pages} (os={offset}) de proyectos del Banco Mundial")

        response = _get_session().get(
            PROJECTS_API,
            params={
                "format": "json",
                "regionname_exact": region,
                "status_exact": status,
                "rows": rows_per_page,
                "os": offset,
                "srt": "boardapprovaldate",
                "order": "desc",
            },
            timeout=HTTP_CONFIG["timeout_ms"] / 1000,
        )
        response.raise_for_status()
        payload = response.json()

        projects = parse_projects_page(payload)
        if not projects:
            print("  ⚠ Sin proyectos en esta página, se corta la paginación")
            break

        all_projects.extend(projects)
        print(f"  ✅ {len(projects)} proyecto(s) encontrados (total en la API: {payload.get('total', '?')})")

    return all_projects
