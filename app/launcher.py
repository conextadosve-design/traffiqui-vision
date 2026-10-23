"""Arranque de Traffiqui instalado como programa (Traffiqui.exe).

Un solo programa con dos modos, elegidos al instalar (se guarda en C:\\ProgramData\\Traffiqui\\modo.json):

  tienda           cámaras, conteo y panel local en http://localhost:8000; envía sus datos a la sede principal
  sede-principal   servidor central y panel de todas las sedes en http://localhost:9000; las tiendas llegan
                   por Tailscale (red privada), nunca desde internet abierto

Sin ventana de terminal: un icono en la bandeja de Windows abre el panel o cierra el programa. El panel se abre en
una ventana propia (Microsoft Edge en modo aplicación, que trae todo Windows 10/11): sin pestañas ni barra de
direcciones, con el nombre y el icono de Traffiqui. Si no hay Edge ni Chrome, se usa el navegador normal.

    python -m app.launcher --modo sede-principal      (en desarrollo)
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from app.config import DATA_DIR

MODES = {
    "tienda": {"port": 8000, "host": "127.0.0.1", "title": "Traffiqui · Tienda"},
    # 0.0.0.0: las tiendas llegan por la IP de Tailscale; el instalador solo abre el puerto a esa red
    "sede-principal": {"port": 9000, "host": "0.0.0.0", "title": "Traffiqui · Sede principal"},
}
MODE_FILE = DATA_DIR / "modo.json"
log = logging.getLogger("traffiqui.launcher")


def read_mode(cli: str | None) -> str:
    if cli:
        return cli
    try:
        mode = json.loads(MODE_FILE.read_text(encoding="utf-8")).get("modo")
        if mode in MODES:
            return mode
    except (OSError, ValueError):
        pass
    return "tienda"


def setup_logging() -> None:
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:  # con consola (desarrollo)
        handlers.append(logging.StreamHandler())
    try:
        (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(DATA_DIR / "logs" / "traffiqui.log",
                                                             maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def build_app(mode: str):
    if mode == "sede-principal":
        os.environ.setdefault("TRAFFIQUI_COOKIE_SECURE", "0")
        from app.backup import BackupManager
        from cloud.main import create_app
        backup = BackupManager(DATA_DIR)   # en modo tienda las copias las arranca app.main
        backup.start()
        return create_app(backup=backup)
    from app.main import app
    return app


def app_browser() -> str | None:
    """Edge (o Chrome) para abrir el panel como ventana propia. None fuera de Windows o si no hay ninguno."""
    if sys.platform != "win32":
        return None
    bases = [os.environ.get(v) for v in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    rel = (Path("Microsoft", "Edge", "Application", "msedge.exe"), Path("Google", "Chrome", "Application", "chrome.exe"))
    for r in rel:
        for b in bases:
            if b and (Path(b) / r).is_file():
                return str(Path(b) / r)
    return None


def open_panel(url: str, browser: bool = False) -> None:
    """Abre el panel en su ventana (o en el navegador si `browser` o si no se puede)."""
    exe = None if browser else app_browser()
    if exe:
        # perfil propio: la ventana va aparte del navegador del usuario y recuerda su tamaño y posición
        profile = Path(os.environ.get("LOCALAPPDATA") or DATA_DIR) / "Traffiqui" / "ventana"
        try:
            subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                              "--no-default-browser-check", "--disable-features=Translate",
                              "--window-size=1440,900"], close_fds=True)
            return
        except OSError as e:
            log.warning("No se pudo abrir la ventana de Traffiqui (%s); se usa el navegador.", e)
    webbrowser.open(url)


def open_when_ready(url: str, port: int, browser: bool = False) -> None:
    def wait():
        for _ in range(240):
            if port_in_use(port):
                open_panel(url, browser)
                return
            time.sleep(0.5)
    threading.Thread(target=wait, name="abrir-panel", daemon=True).start()


def tray_icon(title: str, url: str, on_quit, browser: bool = False):
    """Icono en la bandeja. Devuelve None si no se puede (p. ej. un servidor sin escritorio)."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), 14, fill=(224, 165, 38, 255))   # latón de la marca
    d.ellipse((17, 17, 47, 47), outline=(23, 32, 43, 255), width=6)
    d.ellipse((27, 27, 37, 37), fill=(23, 32, 43, 255))
    menu = pystray.Menu(pystray.MenuItem("Abrir Traffiqui", lambda: open_panel(url, browser), default=True),
                        pystray.MenuItem("Abrir en el navegador", lambda: webbrowser.open(url)),
                        pystray.MenuItem("Salir", lambda icon: (icon.stop(), on_quit())))
    return pystray.Icon("traffiqui", img, title, menu)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Traffiqui")
    ap.add_argument("--modo", choices=list(MODES), help="por defecto, el elegido al instalar")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el panel al arrancar")
    ap.add_argument("--navegador", action="store_true", help="abrir el panel en el navegador, no en su ventana")
    ap.add_argument("--sin-bandeja", action="store_true", help="sin icono en la bandeja (Ctrl+C para cerrar)")
    args = ap.parse_args(argv)
    setup_logging()
    mode = read_mode(args.modo)
    cfg = MODES[mode]
    url = f"http://localhost:{cfg['port']}"

    if port_in_use(cfg["port"]):  # ya está abierto (doble clic otra vez): solo mostrar el panel
        log.info("Traffiqui ya está en marcha; se abre el panel.")
        open_panel(url, args.navegador)
        return 0

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(build_app(mode), host=cfg["host"], port=cfg["port"],
                                           log_level="warning", log_config=None))
    log.info("%s en %s", cfg["title"], url)
    if not args.no_abrir:
        open_when_ready(url, cfg["port"], args.navegador)

    icon = None if args.sin_bandeja else tray_icon(cfg["title"], url, lambda: setattr(server, "should_exit", True),
                                                 args.navegador)
    if icon is None:
        server.run()
        return 0
    worker = threading.Thread(target=server.run, name="servidor", daemon=True)
    worker.start()
    icon.run()           # hasta "Salir"
    server.should_exit = True
    worker.join(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
