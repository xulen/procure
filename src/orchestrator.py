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
        from bids_browser import BidBrowser
        from bids_listings import fetch_all_listings as bids_fetch_all_listings
        from bids_projects import fetch_project_documents as bids_fetch_project_documents

        globals().update({
            "_bids_output_root": BIDS_OUTPUT_ROOT,
            "_bids_browser_cls": BidBrowser,
            "_bids_fetch_all_listings": bids_fetch_all_listings,
            "_bids_fetch_project_documents": bids_fetch_project_documents,
        })
        _bids_imports_ready = True

# Imports para World Bank (cargados perezosamente para no romper flujo CAF/BID)
_wb_imports_ready = False


def _ensure_worldbank_imports():
    """Carga perezosamente los módulos del Banco Mundial solo cuando se necesitan."""
    global _wb_imports_ready
    if not _wb_imports_ready:
        from worldbank_config import OUTPUT_ROOT as WB_OUTPUT_ROOT
        from worldbank_projects import fetch_all_projects as wb_fetch_all_projects
        from worldbank_documents import (
            fetch_project_documents as wb_fetch_project_documents,
            download_document as wb_download_document,
        )

        globals().update({
            "_wb_output_root": WB_OUTPUT_ROOT,
            "_wb_fetch_all_projects": wb_fetch_all_projects,
            "_wb_fetch_project_documents": wb_fetch_project_documents,
            "_wb_download_document": wb_download_document,
        })
        _wb_imports_ready = True

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
    Ejecuta el pipeline completo de descarga de proyectos del BID.

    Mismo patrón que CAF (listado → detalle → documentos → índice), pero
    para pasar el bloqueo de Cloudflare de www.iadb.org, todo el fetching de
    HTML se hace con un Chromium real lanzado a mano y controlado vía
    CDP-attach (ver bids_browser.py) — ni requests ni Playwright.launch()
    normal alcanzan. Las descargas de documentos sí van directo por
    requests (document.cfm no está protegido, redirige a un bucket S3).

    Args:
        output_root: Directorio de salida (default: bids).
        total_pages: Páginas de listado a recorrer, 10 proyectos c/u, orden
                     más reciente primero (default: 43).
        delay_between_projects_ms: Delay entre proyectos en ms.

    Returns:
        dict con resultados del scraping.
    """
    _ensure_bid_imports()

    output_root = output_root or _bids_output_root
    total_pages = total_pages or 43

    print("╔══════════════════════════════════════════════╗")
    print("║   BID Projects Scraper — Inicializando       ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  Salida: {output_root}")
    print(f"  Páginas de listado a recorrer: {total_pages}")

    index_data = load_index(output_root)
    existing_count = len(index_data["slugs"])
    if existing_count > 0:
        print(f"  📋 Índice previo: {existing_count} proyecto(s) conocido(s)")

    start_time = time.time()

    print("\n🔌 Lanzando Chromium real (con pantalla) para pasar Cloudflare...")
    browser = _bids_browser_cls()
    browser.start()

    try:
        # Paso 1: Obtener todos los proyectos del listado
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("PASO 1: Escaneando listados de proyectos del BID")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        all_projects = _bids_fetch_all_listings(browser, total_pages=total_pages)

        new_projects, duplicate_count = filter_duplicates(all_projects, index_data)

        print(f"\n✅ Total proyectos encontrados: {len(all_projects)}")
        if duplicate_count > 0:
            print(f"  🔄 Duplicados filtrados (ya conocidos): {duplicate_count}")
        print(f"  ✨ Proyectos nuevos: {len(new_projects)}")

        # Paso 2: Obtener documentos de cada proyecto nuevo
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
            print(f"\n[{i + 1}/{len(new_projects)}] {project['title']} ({project['project_number']})")

            try:
                documents = _bids_fetch_project_documents(browser, project["url"])

                if not documents:
                    print("  ⚠ Sin documentos para descargar")
                    results["skipped"].append({
                        "project_number": project["project_number"],
                        "title": project["title"],
                        "url": project["url"],
                        "reason": "sin_documentos",
                    })
                    continue

                docs_dir = os.path.join(output_root, project["slug"], "documentos")
                ensure_dir(docs_dir)

                for doc_meta in documents:
                    doc_url = doc_meta["url"]
                    try:
                        print(f"  📥 Descargando: {doc_meta['name'] or doc_url} [{doc_meta.get('category') or 'N/A'}]")

                        fallback_name = sanitize_file_name(doc_meta["name"] or doc_url) + ".pdf"
                        doc = browser.download(doc_url, fallback_name=fallback_name)
                        local_name = sanitize_file_name(doc["filename"])
                        local_path = os.path.join(docs_dir, local_name)
                        write_file(local_path, doc["buffer"])

                        print(f"  ✅ {doc['filename']} → {local_path} ({format_bytes(doc['size'])})")
                        results["downloaded"].append({
                            "project": project["slug"],
                            "project_number": project["project_number"],
                            "document_name": doc["filename"],
                            "category": doc_meta.get("category"),
                            "date": doc_meta.get("date"),
                            "language": doc_meta.get("language"),
                            "local_path": local_path,
                            "size": doc["size"],
                            "source_url": doc_url,
                        })

                    except Exception as err:
                        print(f"  ❌ Error descargando {doc_url}: {err}")
                        results["failed"].append({
                            "project": project["slug"],
                            "document_name": doc_meta.get("name") or doc_url,
                            "error": str(err),
                        })

            except Exception as err:
                print(f"  ❌ Error procesando proyecto {project['title']}: {err}")
                results["failed"].append({
                    "project": project["slug"],
                    "document_name": "N/A",
                    "error": str(err),
                })

            if i < len(new_projects) - 1:
                time.sleep(delay_between_projects_ms / 1000)
    finally:
        browser.close()

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

    summary_path = os.path.join(output_root, "_summary.json")
    write_text_file(summary_path, json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "BID",
        "elapsed_seconds": elapsed,
        "total_projects_scanned": len(all_projects),
        "duplicates_filtered": duplicate_count,
        "new_projects_processed": len(new_projects),
        "downloaded": len(results["downloaded"]),
        "skipped": len(results["skipped"]),
        "failed": len(results["failed"]),
        "total_in_index": total_known,
        "downloaded_files": [
            {
                "project": d["project"],
                "project_number": d.get("project_number", ""),
                "document": d["document_name"],
                "category": d.get("category"),
                "date": d.get("date"),
                "language": d.get("language"),
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


# =============================================================================
# World Bank Scraper — Banco Mundial
# =============================================================================


def run_worldbank_scraper(output_root=None, total_pages=None, delay_between_projects_ms=2000):
    """
    Ejecuta el pipeline completo de descarga de proyectos del Banco Mundial.

    Mismo patrón que CAF/BID (listado → documentos → índice), pero acá no
    hace falta scraping HTML ni navegador: el Banco Mundial expone una API
    pública, documentada y en vivo, sin protección anti-bot (ver
    worldbank_config.py). Todo va directo por requests.

    Args:
        output_root: Directorio de salida (default: worldbank).
        total_pages: Páginas de listado a recorrer (worldbank_config.ROWS_PER_PAGE
                     proyectos c/u), orden más reciente primero por fecha de
                     aprobación (default: 3).
        delay_between_projects_ms: Delay entre proyectos en ms.

    Returns:
        dict con resultados del scraping.
    """
    _ensure_worldbank_imports()

    output_root = output_root or _wb_output_root
    total_pages = total_pages or 3

    print("╔══════════════════════════════════════════════╗")
    print("║   World Bank Projects Scraper — Inicializando║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  Salida: {output_root}")
    print(f"  Páginas de listado a recorrer: {total_pages}")

    index_data = load_index(output_root)
    existing_count = len(index_data["slugs"])
    if existing_count > 0:
        print(f"  📋 Índice previo: {existing_count} proyecto(s) conocido(s)")

    start_time = time.time()

    # Paso 1: Obtener todos los proyectos del listado
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASO 1: Escaneando listado de proyectos del Banco Mundial")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    all_projects = _wb_fetch_all_projects(total_pages=total_pages)

    new_projects, duplicate_count = filter_duplicates(all_projects, index_data)

    print(f"\n✅ Total proyectos encontrados: {len(all_projects)}")
    if duplicate_count > 0:
        print(f"  🔄 Duplicados filtrados (ya conocidos): {duplicate_count}")
    print(f"  ✨ Proyectos nuevos: {len(new_projects)}")

    # Paso 2: Obtener documentos de cada proyecto nuevo
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
        print(f"\n[{i + 1}/{len(new_projects)}] {project['title']} ({project['project_id']})")

        try:
            documents = _wb_fetch_project_documents(project["project_id"])

            if not documents:
                print("  ⚠ Sin documentos para descargar")
                results["skipped"].append({
                    "project_id": project["project_id"],
                    "title": project["title"],
                    "url": project["url"],
                    "reason": "sin_documentos",
                })
                continue

            docs_dir = os.path.join(output_root, project["slug"], "documentos")
            ensure_dir(docs_dir)

            for doc_meta in documents:
                pdf_url = doc_meta["pdf_url"]
                try:
                    print(f"  📥 Descargando: {doc_meta['name']} [{doc_meta.get('doc_type') or 'N/A'}]")

                    fallback_name = sanitize_file_name(doc_meta["name"]) + ".pdf"
                    doc = _wb_download_document(pdf_url, fallback_name=fallback_name)
                    local_name = sanitize_file_name(doc["filename"])
                    if not local_name.lower().endswith(".pdf"):
                        local_name += ".pdf"
                    local_path = os.path.join(docs_dir, local_name)
                    write_file(local_path, doc["buffer"])

                    print(f"  ✅ {doc['filename']} → {local_path} ({format_bytes(doc['size'])})")
                    results["downloaded"].append({
                        "project": project["slug"],
                        "project_id": project["project_id"],
                        "document_name": doc["filename"],
                        "doc_type": doc_meta.get("doc_type"),
                        "date": doc_meta.get("date"),
                        "language": doc_meta.get("language"),
                        "local_path": local_path,
                        "size": doc["size"],
                        "source_url": pdf_url,
                    })

                except Exception as err:
                    print(f"  ❌ Error descargando {pdf_url}: {err}")
                    results["failed"].append({
                        "project": project["slug"],
                        "document_name": doc_meta.get("name") or pdf_url,
                        "error": str(err),
                    })

        except Exception as err:
            print(f"  ❌ Error procesando proyecto {project['title']}: {err}")
            results["failed"].append({
                "project": project["slug"],
                "document_name": "N/A",
                "error": str(err),
            })

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

    summary_path = os.path.join(output_root, "_summary.json")
    write_text_file(summary_path, json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "World Bank",
        "elapsed_seconds": elapsed,
        "total_projects_scanned": len(all_projects),
        "duplicates_filtered": duplicate_count,
        "new_projects_processed": len(new_projects),
        "downloaded": len(results["downloaded"]),
        "skipped": len(results["skipped"]),
        "failed": len(results["failed"]),
        "total_in_index": total_known,
        "downloaded_files": [
            {
                "project": d["project"],
                "project_id": d.get("project_id", ""),
                "document": d["document_name"],
                "doc_type": d.get("doc_type"),
                "date": d.get("date"),
                "language": d.get("language"),
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
