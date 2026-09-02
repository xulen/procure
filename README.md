# Procurment — Scraper de Convocatorias y Proyectos Multilaterales

Script modular para escanear y descargar la documentación de convocatorias públicas y proyectos multilaterales (CAF, BID, etc.).

## Estructura del proyecto

```
procurment/
├── requirements.txt       # Dependencias Python
├── README.md
└── src/
    ├── main.py            # Entry point (CLI)
    ├── orchestrator.py    # Orquestador principal (CAF + BID)
    ├── config.py          # Configuración CAF
    ├── listings.py        # Escáner de listados CAF (tarjetas HTML)
    ├── projects.py        # Parser de páginas de proyecto CAF
    ├── http_client.py     # HTTP híbrido Playwright+requests (solo CAF)
    ├── bids_config.py     # Configuración BID
    ├── bids_notices.py    # Dataset abierto de avisos de adquisiciones BID (data.iadb.org)
    ├── bids_documents.py  # Descarga de documentos BID (idbdocs.iadb.org)
    ├── bids_index.py      # Índice de avisos BID ya procesados (_notices_seen.json)
    ├── bids_listings.py   # NO SE USA — referencia de selectores HTML BID (bloqueado por Cloudflare)
    ├── bids_projects.py   # NO SE USA — referencia de selectores HTML BID (bloqueado por Cloudflare)
    ├── filesystem.py      # Operaciones de sistema de archivos
    ├── index.py           # Índice persistente por proyecto (_index.json)
    └── report.py          # Generador de reportes amigables (HTML + Excel)
```

## Instalación

Requiere **Python 3.10+**.

```bash
# Instalar dependencias
pip install -r requirements.txt

# Instalar el binario de Chromium para Playwright (solo lo usa CAF)
playwright install chromium
```

### Dependencias

- `requests` — peticiones HTTP
- `beautifulsoup4` — parseo HTML
- `lxml` — parser HTML rápido para BeautifulSoup
- `openpyxl` — generación de archivos Excel (.xlsx)
- `playwright` — warmup anti-bot para CAF (`www.caf.com`); BID no lo necesita

## Uso

### Scraping (descarga de convocatorias y proyectos)

```bash
python src/main.py                          # Scraping CAF (default)
python src/main.py --source bids            # Scraping BID (43 avisos nuevos más recientes)
python src/main.py --source bids --pages 5  # Solo los 5 avisos BID más nuevos
python src/main.py -o ./mi-caja             # Guardar en ./mi-caja
python src/main.py --verbose                # Logging detallado
```

### Opciones de scraping

| Flag | Descripción | Default |
|------|-------------|---------|
| `-s <fuente>` / `--source <fuente>` | Fuente: `caf` o `bids` | `caf` |
| `-p <n>` / `--pages <n>` | CAF: páginas de listado. BID: límite de avisos nuevos a procesar (los más recientes primero) | 43 |
| `-o <ruta>` / `--output <ruta>` | Directorio de salida para scraping | `./caf` / `./bids` |
| `-d <ms>` / `--delay <ms>` | Delay entre descargas en ms | 2000 |
| `-v` / `--verbose` | Activar logging detallado | false |

### Fuentes soportadas

| Fuente | Tipo | Origen de los datos | Estructura |
|--------|------|----------------------|------------|
| **CAF** | Convocatorias | Scraping HTML de `caf.com/es/trabaja-con-nosotros/convocatorias/` (Playwright + requests) | Tarjetas HTML (`article.card`) |
| **BID** | Avisos de adquisiciones | Dataset abierto CKAN de `data.iadb.org` + documentos desde `idbdocs.iadb.org` | CSV (~decenas de miles de avisos, 2000–presente) |

### BID — por qué no es scraping HTML

`www.iadb.org/en/project-search` está detrás de **Cloudflare Bot Fight Mode**.
Se comprobó que incluso una navegación real con Playwright (Chromium headless,
cookies de warmup válidas) recibe un bloqueo duro (`403 Attention Required!`)
en cualquier página del sitio salvo la home — no es un simple challenge de
cookies como el de CAF (Incapsula).

En cambio, el BID publica sus **avisos de adquisiciones** (bidding notices,
expressions of interest, notificaciones de adjudicación) como dato abierto:

- Dataset: [IDB Project procurement bidding notices and notification of contract awards](https://data.iadb.org/dataset/project-procurement-bidding-notices-and-notification-of-contract-awards) (CKAN, sin protección anti-bot)
- Cada fila trae el `documenturl`, que apunta a `idbdocs.iadb.org` y redirige (sin cookies ni sesión) a un bucket S3 público con el PDF

`bids_notices.py` descarga y parsea ese CSV; `bids_documents.py` baja cada
PDF. No se necesita Playwright para BID en absoluto.

```bash
# Los 3 avisos BID más nuevos (para probar)
python src/main.py --source bids --pages 3

# Exportar a directorio personalizado
python src/main.py --source bids -o ./proyectos-bid --pages 100
```

### Reportes (HTML + Excel)

Después de ejecutar el scraper, genera reportes amigables para usuarios finales:

```bash
python src/main.py --report                 # HTML + Excel desde índice existente
python src/main.py --report --format html   # Solo reporte HTML
python src/main.py --report --format xlsx   # Solo reporte Excel
```

También puedes usar el módulo directamente:

```bash
python src/report.py --output-dir nachus    # Genera en nachus/
python src/report.py --project-root .       # Detecta todas las fuentes automáticamente
```

### Estructura de descarga

```
nachus/ (CAF)                              bids/ (BID)
├── proyecto-slug-a/                       ├── me-t1569/
│   └── documentos/                        │   └── documentos/
│       ├── documento1.pdf                 │       ├── {noticeid}_....pdf
│       └── documento2.pdf                 │       └── {noticeid}_....pdf
├── _index.json                            ├── _index.json
├── _summary.json                          ├── _summary.json
├── _report.html                           ├── _notices_seen.json  (dedup por aviso)
└── _report.xlsx                           ├── _report.html
                                            └── _report.xlsx
```

Un mismo proyecto BID (ej. `me-t1569`) puede acumular documentos de varios
avisos publicados en distintos momentos — cada corrida solo agrega los
avisos nuevos que todavía no estén en `_notices_seen.json`.

## Arquitectura

```
main.py (CLI)
    │
    ├──► orchestrator.py  ← Coordina el pipeline completo de scraping
    │       │              ├► run_scraper()     → CAF
    │       │              └► run_bid_scraper() → BID
    │       │
    │       ├─(CAF)──► listings.py      ← Escanea /convocatorias/?page=N (tarjetas)
    │       │         ├──► projects.py  ← Parsea páginas de proyecto CAF
    │       │         ├──► http_client.py ← Playwright (warmup) + requests, con reintentos
    │       │         └─(config.py)     ← Configuración CAF
    │       │
    │       ├─(BID)──► bids_notices.py   ← Descarga+parsea el CSV de avisos (data.iadb.org, CKAN)
    │       │         ├──► bids_documents.py ← Baja cada PDF (idbdocs.iadb.org, sin sesión)
    │       │         ├──► bids_index.py     ← Dedup por aviso (_notices_seen.json)
    │       │         └─(bids_config.py)     ← Configuración BID
    │       │
    │       ├─(común)──► filesystem.py ← Creación de directorios y escritura
    │       │           └──► index.py  ← Índice persistente por proyecto (_index.json)
    │       │                   filter_duplicates + update_index + save_index
    │       │
    │       └──► report.py      ← Generador de reportes amigables
    │                   ├─(común)  Descubre todas las fuentes automáticamente
    │                   ├─ HTML estático (_report.html)
    │                   └─ Excel (_report.xlsx)
```

## Selectores HTML utilizados

### Listado de convocatorias (páginas de paginación)

Cada convocatoria se renderiza como una tarjeta `<article class="card">`:

```html
<article class="card">
    <a href="/es/trabaja-con-nosotros/convocatorias/{slug}/">
        <img class="img--cover ..." src="..." alt="">
    </a>
    <h3 class="card__title padding__bottom-spacing-02">
        <a class="no-underline" href="/es/trabaja-con-nosotros/convocatorias/{slug}/">
            {Título de la convocatoria}
        </a>
    </h3>
    <p class="p-body-m padding__bottom-spacing-02 text-color-gris-900">
        <strong>Cierre:</strong> 12 octubre 2026
    </p>
    <div class="margin__bottom-spacing-03">
        <p class="card__capacitacion card__capacitacion--abierta">Convocatoria abierta</p>
        <!-- o card__capacitacion--cerrada para cerradas -->
    </div>
</article>
```

**Selectores clave:**

| Dato | Selector CSS | Extrae |
|------|-------------|--------|
| Tarjeta completa | `article.card` | Bloque de cada convocatoria |
| Título + enlace | `.card__title a` | Texto del título y URL |
| Fecha de cierre | `.p-body-m strong` | "Cierre: ..." |
| Estado | `.card__capacitacion` | `"abierta"` o `"cerrada"` según clase |

## Reportes para usuarios finales

Además del scraping, el proyecto genera reportes accesibles para usuarios no técnicos.

### HTML (`_report.html`)

Página estática autocontenida con:
- **Tarjetas de estadísticas** — fuentes, proyectos y documentos totales
- **Tabla organizada por fuente** — cada fila muestra título, país, fecha de cierre, estado y cantidad de documentos
- **Enlaces a carpetas locales** — clic en "📁 Abrir" o en el nombre del proyecto abre la carpeta con los documentos descargados
- **Badges de estado** — colores verde (abierta), rojo (cerrada), amarillo (desconocido)
- **Responsive** — se visualiza bien en móvil y escritorio

### Excel (`_report.xlsx`)

Archivo con una hoja por fuente:
- **Columnas**: Fuente, Título, País, Fecha Cierre, Estado, URL Origen, Documentos Descargados, Ruta Local
- **Celdas de estado coloreadas** — verde para abiertas, rojo para cerradas
- **Ancho automático** de columnas
- **Listado de archivos** descargados por proyecto

### Flujo de trabajo recomendado

```bash
# 1. Ejecutar scraping (genera _index.json y descarga documentos)
python src/main.py -o nachus

# 2. Generar reportes amigables
python src/main.py --report -o nachus

# 3. Abrir reporte HTML en navegador
xdg-open nachus/_report.html   # Linux
open nachus/_report.html       # macOS
```

## Consideraciones

- **Respeto al servidor**: Delays configurables entre peticiones (configurable en `config.py`)
- **Reintentos automáticos**: 3 intentos por petición con backoff exponencial
- **CAF usa Playwright**: solo para el warmup inicial (resolver el challenge anti-bot y capturar cookies); el resto del scraping es `requests` + `BeautifulSoup`
- **BID no usa Playwright**: `www.iadb.org` está bloqueado por Cloudflare Bot Fight Mode incluso con Playwright, así que BID va directo al dataset abierto de `data.iadb.org` y a `idbdocs.iadb.org` (ver sección "BID — por qué no es scraping HTML")
- **Reportes amigables**: `_report.html` y `_report.xlsx` para consulta sin conocimientos técnicos
- **Múltiples fuentes**: Soporta escanear y reportar sobre múltiples fuentes (CAF, BID) simultáneamente
