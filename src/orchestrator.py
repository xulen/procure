"""
Orquestador principal: coordina scraping de listados, proyectos y descargas.
"""

import json
import math
import os
import re
import time
import logging

from config import OUTPUT_ROOT, HTTP_CONFIG
from listings import fetch_all_listings
from projects import fetch_project_details
from http_client import download_file, init_session
from filesystem import get_project_dirs, write_file, write_text_file, ensure_dir
from index import load_index, save_index, filter_duplicates, update_index

# Imports para BID (cargados perezosamente para no romper flujo CAF)
_bids_imports_ready = False


def _ensure_bid_imports():
    """Carga perezosamente los módulos del BID solo cuando se necesitan."""
    global _bids_imports_ready
    if not _bids_imports_ready:
        from bids_config import OUTPUT_ROOT as BIDS_OUTPUT_ROOT
        from bids_notices import (
            fetch_all_notices as bids_fetch_all_notices,
            slugify_project as bids_slugify_project,
        )
        from bids_index import load_notices_seen as bids_load_notices_seen, save_notices_seen as bids_save_notices_seen  # noqa: E501
        from bids_documents import download_document as bids_download_document

        globals().update({
            "_bids_output_root": BIDS_OUTPUT_ROOT,
            "_bids_fetch_all_notices": bids_fetch_all_notices,
            "_bids_slugify_project": bids_slugify_project,
            "_bids_load_notices_seen": bids_load_notices_seen,
            "_bids_save_notices_seen": bids_save_notices_seen,
            "_bids_download_document": bids_download_document,
        })
        _bids_imports_ready = True

logger = logging.getLogger(__name__)


def run_scraper(output_root=None, total_pages=None, delay_between_projects_ms=2000):
    """
    Ejecuta el pipeline completo de descarga.

    Args:
        output_root: Directorio de salida (default: OUTPUT_ROOT).
        total_pages: Número de páginas a procesar (default: TOTAL_PAGES o
                     el valor detectado automáticamente del HTML).
        delay_between_projects_ms: Delay entre proyectos en ms.

    Returns:
        dict con resultados del scraping.
    """
    output_root = output_root or OUTPUT_ROOT
    total_pages = total_pages or 43  # default from config

    print("╔══════════════════════════════════════════════╗")
    print("║   CAF Convocatorias Scraper — Inicializando  ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  Salida: {output_root}")
    print(f"  Páginas a procesar: {total_pages}")

    # Cargar índice persistente (slugs ya conocidos)
    index_data = load_index(output_root)
    existing_count = len(index_data["slugs"])
    if existing_count > 0:
        print(f"  📋 Índice previo: {existing_count} proyecto(s) conocido(s)")

    # Inicializar sesión HTTP con cookies del servidor
    print("\n🔌 Inicializando conexión con CAF...")
    init_session()

    start_time = time.time()

    # Paso 1: Obtener todos los proyectos del listado
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASO 1: Escaneando listados de convocatorias")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    all_projects = fetch_all_listings(total_pages=total_pages)

    # Filtrar duplicados usando el índice persistente
    new_projects, duplicate_count = filter_duplicates(all_projects, index_data)

    print(f"\n✅ Total proyectos encontrados: {len(all_projects)}")
    if duplicate_count > 0:
        print(f"  🔄 Duplicados filtrados (ya conocidos): {duplicate_count}")
    print(f"  ✨ Proyectos nuevos: {len(new_projects)}")

    # Paso 2: Obtener detalles y documentos de cada proyecto nuevo
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASO 2: Descargando documentación de proyectos")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    results = {
        "downloaded": [],
        "failed": [],
        "skipped": [],
        "duplicates_skipped": duplicate_count,
    }

    for i, project in enumerate(new_projects):
        print(f"\n[{i + 1}/{len(new_projects)}] {project['title']}")

        try:
            # Obtener detalles del proyecto (incluye links a documentos)
            details = fetch_project_details(project["url"])

            if not details["documents"]:
                print(f"  ⚠ Sin documentos para descargar")
                results["skipped"].append({
                    "slug": details["slug"],
                    "title": details["title"],
                    "url": details["url"],
                    "reason": "sin_documentos",
                })
                continue

            # Crear directorio del proyecto
            dirs = get_project_dirs(output_root, details["slug"])
            ensure_dir(dirs["docs_dir"])

            # Descargar cada documento
            for doc in details["documents"]:
                try:
                    print(f"  📥 Descargando: {doc['name']}")

                    result = download_file(doc["url"])
                    buffer = result["buffer"]
                    size = result["size"]

                    # Determinar nombre de archivo local
                    local_name = sanitize_file_name(doc["name"])

                    # Asegurar que tenga una extensión válida si no la tiene
                    if not any(
                        local_name.lower().endswith(ext)
                        for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx",
                                    ".ppt", ".pptx", ".odt", ".ods", ".odp",
                                    ".zip", ".rar", ".7z", ".tar", ".gz",
                                    ".csv", ".txt")
                    ):
                        # Si no tiene extensión reconocida, inferir de la URL
                        url_ext = _extract_extension(doc["url"])
                        if url_ext:
                            local_name += url_ext
                        else:
                            # Default a .pdf como último recurso
                            local_name += ".pdf"

                    local_path = os.path.join(dirs["docs_dir"], local_name)
                    write_file(local_path, buffer)

                    print(f"  ✅ {doc['name']} → {local_path} ({format_bytes(size)})")
                    results["downloaded"].append({
                        "project": details["slug"],
                        "document_name": doc["name"],
                        "local_path": local_path,
                        "size": size,
                        "source_url": doc["url"],
                    })

                except Exception as err:
                    print(f"  ❌ Error descargando {doc['name']}: {err}")
                    results["failed"].append({
                        "project": details["slug"],
                        "document_name": doc["name"],
                        "error": str(err),
                    })

        except Exception as err:
            print(f"  ❌ Error procesando proyecto {project['title']}: {err}")
            results["failed"].append({
                "project": project.get("slug", project.get("title", "unknown")),
                "document_name": "N/A",
                "error": str(err),
            })

        # Delay entre proyectos para respetar el servidor
        if i < len(new_projects) - 1:
            time.sleep(delay_between_projects_ms / 1000)

    # Paso 3: Actualizar y guardar índice persistente
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASO 3: Actualizando índice persistente")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    update_index(index_data, new_projects)
    save_index(index_data, output_root)
    total_known = len(index_data["slugs"])
    print(f"  💾 Índice actualizado: {total_known} proyecto(s) conocido(s)")

    # Paso 4: Generar resumen
    elapsed = round(time.time() - start_time, 1)
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("RESUMEN FINAL")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  ⏱ Tiempo total: {elapsed}s")
    print(f"  📦 Proyectos escaneados: {len(all_projects)}")
    print(f"  🔄 Duplicados filtrados: {duplicate_count}")
    print(f"  ✨ Proyectos nuevos procesados: {len(new_projects)}")
    print(f"  ✅ Documentos descargados: {len(results['downloaded'])}")
    print(f"  ⚠ Proyectos sin documentos: {len(results['skipped'])}")
    print(f"  ❌ Errores: {len(results['failed'])}")
    print(f"  📋 Total proyectos en índice: {total_known}")

    # Extraer fechas de cierre del índice
    closing_dates = []
    for slug, info in index_data["slugs"].items():
        if info.get("closing_date"):
            closing_dates.append({
                "slug": slug,
                "title": info.get("title", ""),
                "closing_date": info["closing_date"],
                "status": info.get("status"),
                "country": info.get("country"),
            })

    # Guardar resumen como JSON
    summary_path = os.path.join(output_root, "_summary.json")
    write_text_file(summary_path, json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": elapsed,
        "total_projects_scanned": len(all_projects),
        "duplicates_filtered": duplicate_count,
        "new_projects_processed": len(new_projects),
        "downloaded": len(results["downloaded"]),
        "skipped": len(results["skipped"]),
        "failed": len(results["failed"]),
        "total_in_index": total_known,
        "closing_dates_summary": closing_dates[:50],  # primeros 50 con fecha
        "downloaded_files": [
            {
                "project": d["project"],
                "document": d["document_name"],
                "local_path": d["local_path"].replace(f"{output_root}/", ""),
                "size_bytes": d["size"],
                "source_url": d["source_url"],
            }
            for d in results["downloaded"]
        ],
        "skipped_projects": results["skipped"],
        "errors": results["failed"],
    }, ensure_ascii=False, indent=2))

    print(f"\n  📄 Resumen guardado en: {summary_path}")

    return results


def sanitize_file_name(name):
    """Sanitiza un nombre de archivo para el sistema local."""
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", name)
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized[:150].strip()


def _extract_extension(url):
    """Extrae la extensión de archivo desde una URL (con punto, minúscula)."""
    try:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(unquote(url))
        pathname = parsed.path
        filename = pathname.split("/")[-1] if "/" in pathname else pathname
        # Buscar el último punto en el nombre de archivo
        dot_idx = filename.rfind(".")
        if dot_idx > 0:
            ext = filename[dot_idx:]  # incluye el punto
            return ext.lower()
    except Exception:
        pass
    return ""


def format_bytes(bytes_val):
    """Formatea bytes a string legible."""
    if bytes_val == 0:
        return "0 B"
    k = 1024
    sizes = ["B", "KB", "MB", "GB"]
    i = int(math.log(bytes_val, k))
    return f"{round(bytes_val / (k ** i), 1)} {sizes[i]}"


# =============================================================================
# BID Scraper — Banco Interamericano de Desarrollo
# =============================================================================


def run_bid_scraper(output_root=None, total_pages=None, delay_between_projects_ms=2000):
    """
    Ejecuta el pipeline completo de descarga de avisos de adquisiciones del BID.

    A diferencia de CAF, esto NO scrapea HTML: www.iadb.org está bloqueado
    por Cloudflare Bot Fight Mode (ver bids_config.py para el detalle de la
    investigación). En su lugar descarga el dataset abierto de avisos de
    adquisiciones que el BID publica en data.iadb.org y baja cada documento
    desde idbdocs.iadb.org, que no tiene protección anti-bot.

    Args:
        output_root: Directorio de salida (default: bids).
        total_pages: Límite de avisos nuevos a procesar en esta corrida,
                     priorizando los más recientes por fecha de publicación
                     (default: 43, mismo default que CAF).
        delay_between_projects_ms: Delay entre descargas en ms.

    Returns:
        dict con resultados del scraping.
    """
    _ensure_bid_imports()

    output_root = output_root or _bids_output_root
    notice_limit = total_pages or 43  # reutiliza el flag --pages como límite de avisos nuevos

    print("╔══════════════════════════════════════════════╗")
    print("║   BID Procurement Notices — Inicializando    ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  Salida: {output_root}")
    print(f"  Límite de avisos nuevos a procesar: {notice_limit}")

    # Cargar índice persistente de proyectos (para el reporte) y de avisos ya vistos (dedup)
    index_data = load_index(output_root)
    existing_count = len(index_data["slugs"])
    if existing_count > 0:
        print(f"  📋 Índice previo: {existing_count} proyecto(s) conocido(s)")

    notices_seen = _bids_load_notices_seen(output_root)

    start_time = time.time()

    # Paso 1: Descargar el dataset de avisos de adquisiciones (data.iadb.org)
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASO 1: Descargando dataset de avisos de adquisiciones del BID")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    all_notices = _bids_fetch_all_notices(output_root=output_root)

    new_notices = [n for n in all_notices if n["notice_id"] not in notices_seen]
    duplicate_count = len(all_notices) - len(new_notices)

    # Priorizar los avisos más recientes cuando hay más nuevos que el límite
    new_notices.sort(key=lambda n: n["publication_date"] or "", reverse=True)
    new_notices = new_notices[:notice_limit]

    print(f"\n✅ Total avisos en el dataset: {len(all_notices)}")
    if duplicate_count > 0:
        print(f"  🔄 Ya conocidos: {duplicate_count}")
    print(f"  ✨ Avisos nuevos a procesar: {len(new_notices)}")

    # Paso 2: Descargar el documento de cada aviso nuevo
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASO 2: Descargando documentos de adquisiciones")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    results = {
        "downloaded": [],
        "failed": [],
        "duplicates_skipped": duplicate_count,
    }

    touched_projects = {}  # slug -> metadata (para actualizar _index.json)

    for i, notice in enumerate(new_notices):
        slug = _bids_slugify_project(notice["project_number"])
        title = notice["project_name"] or notice["notice_title"] or notice["project_number"]
        print(f"\n[{i + 1}/{len(new_notices)}] {title} ({notice['project_number']}) — {notice['notice_type'] or 'notice'}")

        try:
            docs_dir = os.path.join(output_root, slug, "documentos")
            ensure_dir(docs_dir)

            fallback_name = sanitize_file_name(notice["notice_title"] or notice["notice_id"]) + ".pdf"
            doc = _bids_download_document(notice["document_url"], fallback_name=fallback_name)

            local_name = f"{notice['notice_id']}_{sanitize_file_name(doc['filename'])}"
            if not local_name.lower().endswith(".pdf") and doc["content_type"] == "application/pdf":
                local_name += ".pdf"

            local_path = os.path.join(docs_dir, local_name)
            write_file(local_path, doc["buffer"])

            print(f"  ✅ {doc['filename']} → {local_path} ({format_bytes(doc['size'])})")
            results["downloaded"].append({
                "project": slug,
                "project_number": notice["project_number"],
                "notice_id": notice["notice_id"],
                "notice_type": notice["notice_type"],
                "document_name": doc["filename"],
                "local_path": local_path,
                "size": doc["size"],
                "source_url": notice["document_url"],
            })
            notices_seen[notice["notice_id"]] = {
                "slug": slug,
                "status": "downloaded",
                "local_path": local_path,
            }

        except Exception as err:
            print(f"  ❌ Error descargando aviso {notice['notice_id']}: {err}")
            results["failed"].append({
                "project": slug,
                "notice_id": notice["notice_id"],
                "document_name": notice["notice_title"] or "N/A",
                "error": str(err),
            })
            notices_seen[notice["notice_id"]] = {"slug": slug, "status": "failed"}

        # El primer aviso visto por proyecto es el más reciente (lista ordenada desc)
        touched_projects.setdefault(slug, {
            "slug": slug,
            "title": title,
            "url": notice["project_url"] or "",
            "closing_date": notice["deadline"],
            "status": notice["project_status"],
            "country": notice["country"],
        })

        # Delay entre descargas para respetar el servidor
        if i < len(new_notices) - 1:
            time.sleep(delay_between_projects_ms / 1000)

    # Paso 3: Actualizar y guardar índices persistentes
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASO 3: Actualizando índices persistentes")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    update_index(index_data, list(touched_projects.values()))
    save_index(index_data, output_root)
    _bids_save_notices_seen(output_root, notices_seen)
    total_known = len(index_data["slugs"])
    print(f"  💾 Índice actualizado: {total_known} proyecto(s) conocido(s), {len(notices_seen)} aviso(s) rastreado(s)")

    # Paso 4: Generar resumen
    elapsed = round(time.time() - start_time, 1)
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("RESUMEN FINAL")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  ⏱ Tiempo total: {elapsed}s")
    print(f"  📦 Avisos en el dataset: {len(all_notices)}")
    print(f"  🔄 Ya conocidos: {duplicate_count}")
    print(f"  ✨ Avisos nuevos procesados: {len(new_notices)}")
    print(f"  ✅ Documentos descargados: {len(results['downloaded'])}")
    print(f"  ❌ Errores: {len(results['failed'])}")
    print(f"  📋 Total proyectos en índice: {total_known}")

    # Guardar resumen como JSON
    summary_path = os.path.join(output_root, "_summary.json")
    write_text_file(summary_path, json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "BID",
        "elapsed_seconds": elapsed,
        "total_notices_in_dataset": len(all_notices),
        "already_known": duplicate_count,
        "new_notices_processed": len(new_notices),
        "downloaded": len(results["downloaded"]),
        "failed": len(results["failed"]),
        "total_projects_in_index": total_known,
        "downloaded_files": [
            {
                "project": d["project"],
                "project_number": d["project_number"],
                "notice_id": d["notice_id"],
                "notice_type": d.get("notice_type"),
                "document": d["document_name"],
                "local_path": d["local_path"].replace(f"{output_root}/", ""),
                "size_bytes": d["size"],
                "source_url": d["source_url"],
            }
            for d in results["downloaded"]
        ],
        "errors": results["failed"],
    }, ensure_ascii=False, indent=2))

    print(f"\n  📄 Resumen guardado en: {summary_path}")

    return results
