"""
Módulo de índice persistente para deduplicación entre ejecuciones.

Mantiene un archivo JSON (_index.json) con todos los slugs vistos,
sus metadatos (título, fecha de cierre, estado, país) y la última
fecha de escaneo. Esto permite:

  1. Filtrar proyectos duplicados al reejecutar el scraper.
  2. Conservar la fecha de cierre y metadata sin necesidad de rescanner.
  3. Saber cuántos proyectos nuevos se encontraron vs. ya conocidos.
"""

import json
import os
import time
from datetime import datetime, timezone


INDEX_FILENAME = "_index.json"


def _index_path(output_root):
    """Ruta al archivo de índice dentro del directorio de salida."""
    return os.path.join(output_root, INDEX_FILENAME)


def load_index(output_root):
    """
    Carga el índice persistente desde disco.

    Returns:
        dict con la estructura del índice (vacío si no existe).
    """
    path = _index_path(output_root)
    if not os.path.exists(path):
        return {"slugs": {}, "last_run": None, "total_scraped": 0}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Validar estructura mínima
        if "slugs" not in data:
            data["slugs"] = {}
        if "last_run" not in data:
            data["last_run"] = None
        if "total_scraped" not in data:
            data["total_scraped"] = 0
        return data
    except (json.JSONDecodeError, IOError) as err:
        print(f"  ⚠ No se pudo leer el índice ({err}): usando índice vacío")
        return {"slugs": {}, "last_run": None, "total_scraped": 0}


def save_index(index_data, output_root):
    """
    Guarda el índice persistente en disco.

    Args:
        index_data: dict con 'slugs', 'last_run', 'total_scraped'.
        output_root: directorio de salida donde se guarda el archivo.
    """
    path = _index_path(output_root)
    data_to_save = {
        "slugs": index_data["slugs"],
        "last_run": datetime.now(timezone.utc).isoformat(),
        "total_scraped": len(index_data["slugs"]),
    }

    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=2)


def ensure_dir(dir_path):
    """Asegura que un directorio exista."""
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)


def filter_duplicates(projects, index_data):
    """
    Filtra proyectos duplicados usando el índice persistente.

    Compara cada proyecto por su slug contra los slugs ya conocidos.
    Los nuevos se marcan con 'is_new: True', los existentes con 'is_new: False'.

    Args:
        projects: lista de dicts con 'slug', 'title', 'closing_date', etc.
        index_data: dict del índice cargado (con 'slugs' dict).

    Returns:
        tuple (nuevos, duplicados_filtrados) donde:
          - nuevos: lista de proyectos sin duplicar (con 'is_new': True)
          - duplicados_filtrados: count de proyectos ya conocidos
    """
    seen_slugs = set(index_data["slugs"].keys())
    new_projects = []
    duplicate_count = 0

    for project in projects:
        slug = project.get("slug")
        if not slug or slug == "unknown":
            # Si no tiene slug válido, siempre incluirlo
            project["is_new"] = True
            new_projects.append(project)
            continue

        if slug in seen_slugs:
            duplicate_count += 1
            continue

        seen_slugs.add(slug)
        project["is_new"] = True
        new_projects.append(project)

    return new_projects, duplicate_count


def update_index(index_data, projects):
    """
    Actualiza el índice con los nuevos proyectos.

    Args:
        index_data: dict del índice a actualizar.
        projects: lista de dicts con 'slug', 'title', 'closing_date', etc.

    Returns:
        El índice actualizado.
    """
    for project in projects:
        slug = project.get("slug")
        if not slug or slug == "unknown":
            continue

        index_data["slugs"][slug] = {
            "title": project.get("title", ""),
            "url": project.get("url", ""),
            "closing_date": project.get("closing_date"),
            "status": project.get("status"),
            "country": project.get("country"),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }

    return index_data


def get_closing_dates(index_data):
    """
    Extrae todas las fechas de cierre del índice.

    Returns:
        lista de dicts {'slug': ..., 'closing_date': ...} para todos los proyectos conocidos.
    """
    dates = []
    for slug, info in index_data["slugs"].items():
        dates.append({
            "slug": slug,
            "closing_date": info.get("closing_date"),
            "status": info.get("status"),
            "country": info.get("country"),
        })
    return dates
