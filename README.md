# Procurment — Scraper de Convocatorias y Proyectos Multilaterales

Script modular para escanear y descargar la documentación de convocatorias públicas y proyectos multilaterales (CAF, BID, Banco Mundial).

## Estructura del proyecto

```
procurment/
├── requirements.txt       # Dependencias Python
├── README.md
└── src/
    ├── main.py            # Entry point (CLI)
    ├── orchestrator.py    # Orquestador principal (CAF + BID + World Bank)
    ├── config.py          # Configuración CAF
    ├── listings.py        # Escáner de listados CAF (tarjetas HTML)
    ├── projects.py        # Parser de páginas de proyecto CAF
    ├── http_client.py     # HTTP híbrido Playwright+requests (solo CAF)
    ├── bids_config.py     # Configuración BID
    ├── bids_browser.py    # Chromium real + CDP-attach (esquiva Cloudflare) — ver bids_config.py
    ├── bids_listings.py   # Escáner de listados BID (tabla HTML, vía bids_browser)
    ├── bids_projects.py   # Extrae documentos de la página de detalle BID (vía bids_browser)
    ├── bids_notices.py    # Alternativa histórica: dataset abierto data.iadb.org (rezagado meses, no usado por default)
    ├── bids_documents.py  # Alternativa histórica: descarga vía idbdocs.iadb.org (no usado por default)
    ├── bids_index.py      # Alternativa histórica: dedup por aviso (_notices_seen.json, no usado por default)
    ├── worldbank_config.py    # Configuración World Bank
    ├── worldbank_projects.py  # Listado de proyectos vía API pública (search.worldbank.org)
    ├── worldbank_documents.py # Documentos + descarga vía API pública (sin navegador, sin anti-bot)
    ├── filesystem.py      # Operaciones de sistema de archivos
    ├── index.py           # Índice persistente por proyecto (_index.json)
    └── report.py          # Generador de reportes amigables (HTML + Excel)
```

## Instalación

Requiere **Python 3.10+**.

```bash
# Instalar dependencias
pip install -r requirements.txt

# Instalar el binario de Chromium para Playwright (CAF lo usa para el warmup,
# BID lo usa como navegador completo — ver sección BID más abajo)
playwright install chromium

# BID además necesita Xvfb (display virtual — Chrome corre "con pantalla"
# pero sin abrir ninguna ventana visible)
sudo apt install xvfb
```

**BID necesita un display real (no headless), pero no visible.** Por
defecto `bids_browser.py` lanza su propio Xvfb (display virtual `:97`) y
corre Chrome ahí — no aparece ninguna ventana en pantalla. Si hace falta
debuggear viendo el navegador (ej. en WSL2 con WSLg), se puede instanciar
`BidBrowser(use_virtual_display=False)` para que use el display real. Ver
la sección "BID — por qué no es scraping headless" para el motivo de por
qué hace falta esto en primer lugar.

### Dependencias

- `requests` — peticiones HTTP
- `beautifulsoup4` — parseo HTML
- `lxml` — parser HTML rápido para BeautifulSoup
- `openpyxl` — generación de archivos Excel (.xlsx)
- `playwright` — CAF: warmup anti-bot. BID: navegador completo (ver más abajo)

## Uso

### Scraping (descarga de convocatorias y proyectos)

```bash
python src/main.py                          # Scraping CAF (default)
python src/main.py --source bids            # Scraping BID (43 páginas de listado, ~430 proyectos)
python src/main.py --source bids --pages 5  # Solo las 5 páginas BID más nuevas (~50 proyectos)
python src/main.py --source all             # Las tres fuentes en una sola corrida
python src/main.py -o ./mi-caja             # Guardar en ./mi-caja
python src/main.py --verbose                # Logging detallado
```

### Opciones de scraping

| Flag | Descripción | Default |
|------|-------------|---------|
| `-s <fuente>` / `--source <fuente>` | Fuente: `caf`, `bids` (BID), `worldbank` (Banco Mundial) o `all` (las tres en secuencia) | `caf` |
| `-p <n>` / `--pages <n>` | Páginas de listado a recorrer (10 proyectos/página en BID, 20 en World Bank), orden más reciente primero | 43 |
| `-o <ruta>` / `--output <ruta>` | Directorio de salida para scraping | `./caf` / `./bids` / `./worldbank` |
| `-d <ms>` / `--delay <ms>` | Delay entre proyectos en ms | 2000 |
| `-v` / `--verbose` | Activar logging detallado | false |

### Fuentes soportadas

| Fuente | Tipo | Origen de los datos | Estructura |
|--------|------|----------------------|------------|
| **CAF** | Convocatorias | Scraping HTML de `caf.com/es/trabaja-con-nosotros/convocatorias/` (Playwright para warmup + requests) | Tarjetas HTML (`article.card`) |
| **BID** | Proyectos | Scraping HTML de `iadb.org/en/project-search` vía Chromium real (`bids_browser.py`) | Tabla HTML, ~2805 páginas (~28.000 proyectos), orden más reciente primero |
| **World Bank** | Proyectos | API pública en vivo de `search.worldbank.org` (sin scraping, sin navegador) | JSON, filtrado a Latin America and Caribbean (~3562 proyectos), orden más reciente primero |

### World Bank — API pública, sin scraping

A diferencia de CAF y BID, acá no hace falta scrapear HTML ni pelear con
ningún anti-bot: el Banco Mundial expone la misma API que usa
`projects.worldbank.org` internamente, documentada y sin protección tipo
Cloudflare Bot Fight Mode (se verificó en vivo — `requests` plano funciona
para todo, incluida la descarga de PDFs).

- Listado de proyectos: `search.worldbank.org/api/v2/projects` — filtro
  `regionname_exact=Latin America and Caribbean` (el mismo que usa la URL
  del sitio), orden `srt=boardapprovaldate&order=desc` para traer los más
  recientes primero, paginado con `rows`/`os` (offset).
- Documentos por proyecto: `search.worldbank.org/api/v3/wds?projectid=P...`
  — trae todos los documentos publicados (Procurement Plan, ISR, PAD,
  avisos de licitación, etc.) con su `pdfurl` directo.
- PDFs: `documents.worldbank.org` (CloudFront), redirige sin cookies ni
  sesión.

`worldbank_projects.py` arma el listado, `worldbank_documents.py` trae los
documentos de cada proyecto y los descarga. No se usa `bids_browser.py` ni
ningún navegador para esta fuente.

```bash
# Las 20 proyectos World Bank más nuevos de LAC (para probar)
python src/main.py --source worldbank --pages 1

# Exportar a directorio personalizado
python src/main.py --source worldbank -o ./proyectos-bm --pages 10
```

### BID — por qué no es scraping headless

`www.iadb.org` está detrás de **Cloudflare Bot Fight Mode**. Se verificó en vivo:

- `requests` o Playwright headless (con o sin cookies de warmup): **403 duro**
  ("Attention Required! | Cloudflare") en cualquier página salvo la home. No
  es un challenge de cookies como el de CAF (Incapsula).
- Chromium headless "puro" — lanzado a mano, sin las banderas de
  automatización de Playwright, controlado vía CDP: **también 403**. Es el
  modo headless en sí lo que Cloudflare detecta.
- Chromium con **pantalla real** (headed), lanzado como proceso normal (sin
  `--enable-automation` ni el resto de banderas que agrega
  `Playwright.launch()`) y recién después controlado vía
  `connect_over_cdp`: **pasa sin problema**, listados y detalle de proyecto.
- Las descargas de documentos (`document.cfm`, mismo host protegido) también
  son inconsistentes con `requests.get()` — el fingerprint TLS de
  `requests`/urllib3 no es el de un navegador real. `bids_browser.py`
  descarga usando `page.request` (comparte la pila de red del propio
  Chromium) y ahí sí es consistente.

Por eso `bids_browser.py` lanza el Chromium de Playwright a mano (headed) y
recién después se conecta vía `connect_over_cdp` — **necesita un display
real, no headless**, aunque no tiene que ser visible: por defecto usa un
Xvfb propio (display virtual), así que no aparece ninguna ventana en
pantalla.

Se evaluó primero una alternativa sin navegador: el BID también publica sus
avisos de adquisiciones como dato abierto en `data.iadb.org` (CKAN,
`bids_notices.py` + `bids_documents.py`, sin protección anti-bot). Se
descartó como fuente principal porque el dataset tiene varios meses de
rezago respecto al sitio en vivo — sirve como backfill histórico masivo,
no para trackear proyectos/avisos nuevos, que es el objetivo del scraper.
Esos módulos quedan en el repo pero no los usa `orchestrator.py` por default.

```bash
# Las 3 páginas BID más nuevas (para probar) — no abre ninguna ventana
python src/main.py --source bids --pages 3

# Exportar a directorio personalizado
python src/main.py --source bids -o ./proyectos-bid --pages 100
```

### Levantar las tres fuentes en una sola corrida

`--source all` ejecuta CAF, BID y World Bank en secuencia, cada uno en su
directorio por defecto (`caf/`, `bids/`, `worldbank/`). Al finalizar imprime
un resumen combinado con descargados, omitidos, duplicados y errores por
fuente.

```bash
# Las tres fuentes con 43 páginas por defecto
python src/main.py --source all

# Acotar páginas por fuente (ej. 5 páginas = ~50 BID, ~100 WB, 43 CAF)
python src/main.py --source all -p 5

# Con delay personalizado
python src/main.py --source all -d 3000
```

> **Nota:** cuando se usa `--source all` se ignora `-o` (cada fuente usa su
> directorio por defecto). Si necesitás un directorio personalizado para
> alguna fuente, ejecutá los scrapers por separado.

Después de levantar las tres fuentes, generá el reporte combinado:

```bash
# Reporte que incluye CAF, BID y World Bank en un solo HTML + Excel
python src/main.py --report -o ./resumen
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
caf/ (CAF)                               bids/ (BID)              worldbank/ (World Bank)
├── proyecto-slug-a/                     ├── me-t1569/            ├── p181166/
│   └── documentos/                      │   └── documentos/      │   └── documentos/
│       ├── documento1.pdf               │       ├── TC_Abstract.pdf │       ├── P181166_Procurement.pdf
│       └── documento2.pdf               │       └── Terms_of_Reference.pdf │       └── ISR.pdf
├── _index.json                          ├── _index.json          ├── _index.json
├── _summary.json                        ├── _summary.json        ├── _summary.json
├── _report.html                         ├── _report.html         ├── _report.html
└── _report.xlsx                         └── _report.xlsx         └── _report.xlsx
```

Cada fuente se descarga en su propia carpeta (`caf/`, `bids/`, `worldbank/`).
El dedup por proyecto se maneja con `_index.json` en cada carpeta: una vez
que un proyecto entra al índice, las corridas futuras no lo vuelven a
visitar — si más adelante se suben avisos/documentos nuevos a ese mismo
proyecto, no se detectan automáticamente.

## Arquitectura

```
main.py (CLI)
    │
    ├──► orchestrator.py  ← Coordina el pipeline completo de scraping
    │       │              ├► run_scraper()           → CAF
    │       │              ├► run_bid_scraper()        → BID
    │       │              └► run_worldbank_scraper()  → World Bank
    │       │
    │       ├─(CAF)──► listings.py      ← Escanea /convocatorias/?page=N (tarjetas)
    │       │         ├──► projects.py  ← Parsea páginas de proyecto CAF
    │       │         ├──► http_client.py ← Playwright (warmup) + requests, con reintentos
    │       │         └─(config.py)     ← Configuración CAF
    │       │
    │       ├─(BID)──► bids_browser.py   ← Chromium real (headed) + connect_over_cdp
    │       │         ├──► bids_listings.py  ← Escanea /en/project-search?page=N (tabla)
    │       │         ├──► bids_projects.py  ← Extrae <idb-document-card> de la página de detalle
    │       │         │        (bids_browser.download() baja cada doc vía page.request)
    │       │         └─(bids_config.py)     ← Configuración BID
    │       │
    │       ├─(World Bank)──► worldbank_projects.py  ← API v2/projects (listado, JSON)
    │       │                ├──► worldbank_documents.py ← API v3/wds (documentos + descarga)
    │       │                └─(worldbank_config.py)      ← Configuración World Bank
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

### Listado de proyectos BID (páginas de paginación)

La tabla no tiene una clase CSS estable (ya cambió una vez) — se ancla por
el `id` de un `<th>`, que es un identificador de campo de Drupal Views y
mucho menos probable que cambie:

```html
<table class="cols-8 ...">  <!-- la clase puede variar, no confiar en ella -->
  <thead>
    <tr>
      <th id="view-field-project-number-table-column">Project Number</th>
      <th id="view-field-operation-number-table-column">Operation Number</th>
      <th id="view-country-name-content-table-column">Country</th>
      <th id="view-project-sector-name-table-column">Sector</th>
      <th id="view-title-table-column">Title</th>
      <th id="view-field-total-cost-table-column">Total Cost</th>
      <th id="view-project-status-name-table-column">Project Status</th>
      <th id="view-field-approval-date-table-column">Approval Date</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>ME-T1569</td>
      <td></td>
      <td>Mexico</td>
      <td>SOCIAL INVESTMENT</td>
      <td><a href="/en/project/ME-T1569">Title...</a></td>
      <td>800,000.00</td>
      <td>Implementation</td>
      <td>Sep. 1 2026</td>
    </tr>
  </tbody>
</table>
```

**Selectores clave BID (listado):**

| Dato | Cómo se extrae | Notas |
|------|-----------------|-------|
| Tabla | `th#view-field-project-number-table-column` → `find_parent("table")` | No usar la clase CSS de la tabla |
| Filas | `tbody tr` de esa tabla | 10 por página |
| Columnas (0-indexed) | 0=Project Number, 2=Country, 3=Sector, 4=Title+link, 5=Total Cost, 6=Status, 7=Approval Date | Columna 1 (Operation Number) casi siempre vacía |
| Paginación | `?page=N`, **0-indexed** | `page=0` es la primera página; última página vía `a[aria-label='Last']` |
| Orden | Más reciente primero | No hace falta ordenar nada del lado del scraper |

### Detalle de proyecto BID — documentos

La página de detalle renderiza casi todo por JS/web components — no hay
`<dt>/<dd>` ni headers de texto plano para las fases ("Procurement Phase",
etc., como sí existían en versiones anteriores del sitio). Los documentos sí
quedan como elementos custom con la URL real en un atributo:

```html
<idb-document-card url="https://www.iadb.org/document.cfm?id=EZIDB000897-741482737-4">
  <div slot="detail">TC Abstract</div>
  <div slot="heading">TC Abstract ME-T1569.pdf</div>
  <div slot="subtitle">May. 06, 2026</div>
  <div slot="cta">English</div>
</idb-document-card>
```

**Selectores clave BID (detalle):**

| Dato | Cómo se extrae |
|------|-----------------|
| URL del documento | atributo `url` de `<idb-document-card>` (no hay `<a href>`) |
| Nombre de archivo | `[slot=heading]` |
| Categoría/fase | `[slot=detail]` (ej. "TC Abstract", "Electronic Links", "TC Document" — no es la taxonomía de 4 fases de versiones viejas del sitio) |
| Fecha | `[slot=subtitle]` |
| Idioma | `[slot=cta]` |

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
# Opción A: una sola corrida para las tres fuentes
python src/main.py --source all

# Opción B: fuentes individuales (útil para acotar páginas por fuente)
python src/main.py -s caf -p 43 -o caf
python src/main.py -s bids -p 43 -o bids
python src/main.py -s worldbank -p 3 -o worldbank

# Generar reportes amigables (detecta todas las fuentes bajo el root)
python src/main.py --report -o ./resumen

# Abrir reporte HTML en navegador
xdg-open resumen/_report.html   # Linux
open resumen/_report.html       # macOS
```

## Consideraciones

- **Respeto al servidor**: Delays configurables entre peticiones (configurable en `config.py`)
- **Reintentos automáticos**: 3 intentos por petición con backoff exponencial
- **CAF usa Playwright**: solo para el warmup inicial (resolver el challenge anti-bot y capturar cookies); el resto del scraping es `requests` + `BeautifulSoup`
- **BID usa un Chromium real, no headless**: `www.iadb.org` bloquea el modo headless (con o sin banderas de automatización), así que `bids_browser.py` lanza Chromium a mano (headed, sin banderas de Playwright.launch()) y se conecta vía `connect_over_cdp` — corre sobre un Xvfb propio por default, sin ventana visible (ver sección "BID — por qué no es scraping headless")
- **World Bank no necesita nada especial**: API pública sin protección anti-bot, todo por `requests` (ver sección "World Bank — API pública, sin scraping")
- **Reportes amigables**: `_report.html` y `_report.xlsx` para consulta sin conocimientos técnicos
- **Múltiples fuentes**: Soporta escanear y reportar sobre múltiples fuentes (CAF, BID, World Bank) simultáneamente. Usá `--source all` para correr las tres en secuencia, o ejecutá cada fuente por separado para acotar páginas por fuente. Los reportes detectan automáticamente todas las carpetas con `_index.json` bajo el directorio raíz.
