#!/usr/bin/env python3
"""
Entry point del scraper de convocatorias y proyectos multilaterales.

Soporta múltiples fuentes:
  - CAF: Convocatorias de la Corporación Andina de Fomento (scraping HTML)
  - BID: Proyectos del Banco Interamericano de Desarrollo (scraping HTML vía
         un Chromium real, necesario para pasar Cloudflare — ver
         src/bids_config.py y src/bids_browser.py)
  - World Bank: Proyectos del Banco Mundial (API pública en vivo, sin
         scraping HTML ni navegador — ver src/worldbank_config.py)
  - all:  Las tres fuentes en una sola corrida (usa directorios por defecto)

Uso:
    python src/main.py                          # Scraping completo (CAF)
    python src/main.py --source bids            # Scraping BID
    python src/main.py --source worldbank       # Scraping World Bank
    python src/main.py --source all             # Las tres fuentes en secuencia
    python src/main.py --source bids --pages 5  # Solo las 5 páginas BID más nuevas (~50 proyectos)
    python src/main.py -o ./caf-dl              # Directorio de salida personalizado
    python src/main.py --report                 # Generar reportes HTML + Excel desde índice existente

Estructura de salida (misma para las tres fuentes):
  caf/ (CAF)             bids/ (BID)          worldbank/ (World Bank)
  ├── proyecto-slug-a/   ├── me-t1569/        ├── p181166/
  │   └── documentos/    │   └── documentos/  │   └── documentos/
  │       └── ....pdf    │       └── ....pdf  │       └── ....pdf
  ├── _index.json        ├── _index.json      ├── _index.json
  ├── _summary.json      ├── _summary.json    ├── _summary.json
  ├── _report.html       ├── _report.html     ├── _report.html
  └── _report.xlsx       └── _report.xlsx     └── _report.xlsx
"""

import sys
import os
import argparse
import logging

# Añadir el directorio src al path para imports relativos
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator import run_scraper


def main():
    parser = argparse.ArgumentParser(
        description="Procurment Scraper — Descarga y genera reportes de convocatorias y proyectos multilaterales",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python src/main.py                          # Scraping completo (CAF)
  python src/main.py --source bids            # Scraping BID
  python src/main.py --source worldbank       # Scraping World Bank
  python src/main.py --source all             # Las tres fuentes en secuencia
  python src/main.py --source bids --pages 10 # Primeras 10 páginas BID
  python src/main.py -o ./mi-caja             # Guardar en ./mi-caja
  python src/main.py --report                 # Generar reportes desde índice existente
  python src/main.py --report --format html   # Solo reporte HTML
        """,
    )

    parser.add_argument(
        "--source", "-s",
        choices=["caf", "bids", "worldbank", "all"],
        default="caf",
        help="Fuente a scrapear: 'caf', 'bids' (BID), 'worldbank' (Banco Mundial) o 'all' (las tres). Default: caf",
    )
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=43,
        help="Número de páginas de listado a procesar, orden más reciente primero (default: 43)",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Directorio de salida (default: OUTPUT_ROOT del config.py de la fuente elegida)",
    )
    parser.add_argument(
        "-d", "--delay",
        type=int,
        default=2000,
        help="Delay entre proyectos en ms (default: 2000)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Activar logging detallado",
    )

    # Modo reporte (sin scraping)
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generar reportes HTML + Excel desde el índice existente (sin scraping)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["html", "xlsx", "all"],
        default="all",
        help="Formato de reporte a generar (default: all)",
    )

    args = parser.parse_args()

    # Configurar logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Modo reporte standalone (sin scraping)
    if args.report:
        from report import main as report_main
        # Re-crear parser para el módulo de reportes
        report_parser = argparse.ArgumentParser()
        report_parser.add_argument("--output-dir", "-o", type=str, default=None)
        report_parser.add_argument("--project-root", type=str, default=None)
        report_parser.add_argument("--format", "-f", choices=["html", "xlsx", "all"], default=args.format)

        # Pasar los args al report module
        extra_args = []
        if args.output:
            extra_args.extend(["-o", args.output])
        src_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(src_dir)
        extra_args.extend(["--project-root", project_root])
        if args.format != "all":
            extra_args.extend(["--format", args.format])

        sys.argv = ["report"] + extra_args
        report_main()
        sys.exit(0)

    try:
        # Seleccionar scraper según fuente
        if args.source == "all":
            # Correr las tres fuentes en secuencia
            from orchestrator import run_scraper, run_bid_scraper, run_worldbank_scraper

            all_results = {}
            all_failed = []

            # --- CAF ---
            if args.output:
                print("\n⚠️  Con --source all se ignora -o y cada fuente usa su directorio por defecto.\n")
            results = run_scraper(
                output_root=None,
                total_pages=args.pages,
                delay_between_projects_ms=args.delay,
            )
            all_results["CAF"] = results
            if results["failed"]:
                for err in results["failed"]:
                    all_failed.append({"source": "CAF", **err})

            # --- BID ---
            results = run_bid_scraper(
                output_root=None,
                total_pages=args.pages,
                delay_between_projects_ms=args.delay,
            )
            all_results["BID"] = results
            if results["failed"]:
                for err in results["failed"]:
                    all_failed.append({"source": "BID", **err})

            # --- World Bank ---
            results = run_worldbank_scraper(
                output_root=None,
                total_pages=args.pages,
                delay_between_projects_ms=args.delay,
            )
            all_results["World Bank"] = results
            if results["failed"]:
                for err in results["failed"]:
                    all_failed.append({"source": "World Bank", **err})

            # Resumen combinado
            print("\n" + "=" * 60)
            print("  RESUMEN COMBINADO — LAS TRES FUENTES")
            print("=" * 60)
            for name, res in all_results.items():
                total = len(res.get("downloaded", []))
                failed = len(res.get("failed", []))
                skipped = len(res.get("skipped", []))
                dupes = res.get("duplicates_skipped", 0)
                print(f"  {name}: {total} descargados | {skipped} omitidos | {dupes} duplicados | {failed} errores")
            print()
            if all_failed:
                print(f"⚠️  {len(all_failed)} error(es) en total:")
                for err in all_failed[:10]:
                    print(f"  [{err['source']}] {err.get('project', 'unknown')}: {err.get('error', 'unknown')}")
                if len(all_failed) > 10:
                    print(f"  ... y {len(all_failed) - 10} más")
            else:
                print("✅ Scraping de las tres fuentes completado exitosamente.")
            sys.exit(0)

        elif args.source == "bids":
            from orchestrator import run_bid_scraper

            results = run_bid_scraper(
                output_root=args.output,
                total_pages=args.pages,
                delay_between_projects_ms=args.delay,
            )
        elif args.source == "worldbank":
            from orchestrator import run_worldbank_scraper

            results = run_worldbank_scraper(
                output_root=args.output,
                total_pages=args.pages,
                delay_between_projects_ms=args.delay,
            )
        else:
            # CAF (default)
            results = run_scraper(
                output_root=args.output,
                total_pages=args.pages,
                delay_between_projects_ms=args.delay,
            )

        # Verificar si hubo errores críticos
        if results["failed"]:
            print(f"\n⚠️  {len(results['failed'])} error(es) durante la ejecución.")
            for err in results["failed"][:5]:  # Mostrar primeros 5 errores
                print(f"  - {err.get('project', 'unknown')}: {err.get('error', 'unknown')}")

        print("\n✅ Scraping completado exitosamente.")
        sys.exit(0)

    except KeyboardInterrupt:
        print("\n\n⚠️  Ejecución interrumpida por el usuario.")
        sys.exit(130)
    except Exception as err:
        print(f"\n❌ Error fatal: {err}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
