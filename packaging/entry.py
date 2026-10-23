"""Punto de entrada de Traffiqui.exe (PyInstaller).

El ejecutable trae la base (Python, librerías y modelos); el código de Traffiqui está al lado, en la carpeta
`codigo`, para que las actualizaciones solo tengan que cambiar esa carpeta. La lógica está en app/launcher.py.
"""
import multiprocessing
import sys
from pathlib import Path


def _error(msg: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "Traffiqui", 0x10)
    except Exception:  # noqa: BLE001 — fuera de Windows
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    here = Path(sys.executable).parent
    code = here / "codigo"
    sys.path.insert(0, str(code))
    try:
        base = (Path(getattr(sys, "_MEIPASS", here)) / "base_version.txt").read_text().strip()
        import app
    except (OSError, ImportError) as e:
        _error(f"Falta el código de Traffiqui ({e}). Vuelve a instalar Traffiqui con el instalador completo.")
        sys.exit(1)
    if app.BASE_REQUIRED != base:
        _error(f"Esta actualización necesita la base {app.BASE_REQUIRED} y la instalada es la {base}. "
               "Instala Traffiqui con el instalador completo (tus datos se conservan).")
        sys.exit(1)
    from app.launcher import main
    sys.exit(main())
