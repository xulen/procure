"""
Motor de navegación para BID: Chromium real lanzado directamente (sin las
banderas de automatización que agrega Playwright.launch()), controlado
después vía CDP-attach.

www.iadb.org está detrás de Cloudflare Bot Fight Mode. Se verificó en vivo:
  - Un Chromium headless SIEMPRE es bloqueado (403) — lanzado por Playwright
    o lanzado a mano, da igual. Cloudflare detecta el modo headless en sí.
  - Un Chromium con pantalla real (headed) lanzado por Playwright (con sus
    banderas de automatización, ej. --enable-automation) también es
    bloqueado.
  - Un Chromium con pantalla real, lanzado como proceso normal (SIN esas
    banderas) y recién después controlado por Playwright vía
    connect_over_cdp, pasa sin problema — listados y páginas de detalle.

Por eso este módulo lanza el binario de Chromium a mano (headed) y recién
después conecta Playwright. Necesita una pantalla real — no headless —
pero no hace falta que sea visible: por defecto se lanza sobre un display
virtual propio (Xvfb, sin ventana en el escritorio), no sobre WSLg. Xvfb es
un X server real (Chrome no sabe que es virtual, no se anuncia como
headless), así que sigue pasando Cloudflare igual que con pantalla visible.
Requiere el paquete `xvfb` instalado (`apt install xvfb`).

Ojo con las descargas: los enlaces a documentos (document.cfm) viven en
www.iadb.org, el mismo host protegido por Cloudflare. Un `requests.get()`
plano a esas URLs es intermitente — pasa a veces, da 403 otras — porque el
fingerprint TLS de `requests`/urllib3 no es el de un navegador real (a
diferencia de idbdocs.iadb.org, que no está detrás de Cloudflare y sí anda
bien con requests). Por eso `download()` acá abajo usa `page.request`, que
comparte la pila de red del propio Chromium.
"""

import glob
import os
import re
import subprocess
import time

from playwright.sync_api import sync_playwright

_CHROMIUM_CACHE = os.path.expanduser("~/.cache/ms-playwright")
_DEFAULT_PROFILE_DIR = os.path.expanduser("~/.cache/procurment/bid-chrome-profile")
_DEFAULT_PORT = 9421
_DEFAULT_VIRTUAL_DISPLAY = ":97"


def _find_chromium_binary():
    candidates = sorted(glob.glob(os.path.join(_CHROMIUM_CACHE, "chromium-*", "chrome-linux64", "chrome")))
    if not candidates:
        raise RuntimeError(
            "No se encontró el Chromium de Playwright en "
            f"{_CHROMIUM_CACHE}. Corré `playwright install chromium`."
        )
    return candidates[-1]


class BidBrowser:
    """Maneja el ciclo de vida de un Chromium real + la conexión Playwright.

    Por defecto corre sobre un display virtual propio (Xvfb) para no abrir
    una ventana visible. Pasá use_virtual_display=False para usar el
    display real (ej. WSLg) y ver la ventana — útil para debuggear.
    """

    def __init__(self, port=_DEFAULT_PORT, profile_dir=_DEFAULT_PROFILE_DIR,
                 use_virtual_display=True, virtual_display=_DEFAULT_VIRTUAL_DISPLAY):
        self._port = port
        self._profile_dir = profile_dir
        self._use_virtual_display = use_virtual_display
        self._virtual_display = virtual_display
        self._proc = None
        self._xvfb_proc = None
        self._playwright = None
        self._browser = None
        self._page = None

    def start(self):
        os.makedirs(self._profile_dir, exist_ok=True)
        chrome_bin = _find_chromium_binary()

        env = os.environ.copy()

        if self._use_virtual_display:
            self._xvfb_proc = subprocess.Popen(
                ["Xvfb", self._virtual_display, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
            env["DISPLAY"] = self._virtual_display

        self._proc = subprocess.Popen(
            [
                chrome_bin,
                f"--remote-debugging-port={self._port}",
                f"--user-data-dir={self._profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        self._playwright = sync_playwright().start()

        last_error = None
        for _ in range(20):
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(f"http://localhost:{self._port}")
                break
            except Exception as err:
                last_error = err
                time.sleep(0.5)
        else:
            raise RuntimeError(f"No se pudo conectar al Chromium recién lanzado: {last_error}")

        context = self._browser.contexts[0]
        self._page = context.pages[0] if context.pages else context.new_page()
        return self

    def get_html(self, url, wait_ms=1200, retries=3, retry_delay_s=3):
        """Navega a una URL y devuelve el HTML final. Reintenta ante 4xx/errores de red."""
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                response = self._page.goto(url, wait_until="load", timeout=30000)
                self._page.wait_for_timeout(wait_ms)
                status = response.status if response else None
                if status and status >= 400:
                    raise RuntimeError(f"HTTP {status} para {url}")
                return self._page.content()
            except Exception as err:
                last_error = err
                if attempt < retries:
                    time.sleep(retry_delay_s)
        raise RuntimeError(f"No se pudo obtener {url} tras {retries} intento(s): {last_error}")

    def download(self, url, fallback_name="BID_document.pdf", retries=3, retry_delay_s=3):
        """
        Descarga un archivo vía el request context del browser (page.request),
        que comparte cookies y pila de red con la navegación real — a
        diferencia de requests.get(), pasa Cloudflare de forma consistente.

        Returns:
            dict con 'buffer' (bytes), 'size', 'filename', 'content_type'.
        """
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                response = self._page.request.get(url)
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status} para {url}")

                body = response.body()
                disposition = response.headers.get("content-disposition", "")
                match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
                filename = match.group(1) if match else fallback_name

                return {
                    "buffer": body,
                    "size": len(body),
                    "filename": filename,
                    "content_type": response.headers.get("content-type", ""),
                }
            except Exception as err:
                last_error = err
                if attempt < retries:
                    time.sleep(retry_delay_s)
        raise RuntimeError(f"No se pudo descargar {url} tras {retries} intento(s): {last_error}")

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        if self._xvfb_proc:
            self._xvfb_proc.terminate()
            try:
                self._xvfb_proc.wait(timeout=5)
            except Exception:
                self._xvfb_proc.kill()

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
