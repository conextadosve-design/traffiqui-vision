# PyInstaller: genera dist/Traffiqui/Traffiqui.exe (carpeta, no un solo archivo: arranca mucho más rápido).
#   pyinstaller packaging/traffiqui.spec --noconfirm
# Antes: el modelo en models/yolo11n.pt y el icono (python packaging/make_icon.py).
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / "cloud" / "static"), "cloud/static"),
    (str(ROOT / "models" / "detector-personas.onnx"), "models"),
    (str(ROOT / "models" / "detector-personas.json"), "models"),
    (str(ROOT / "models" / "detector-personas-rapido.onnx"), "models"),
    (str(ROOT / "models" / "detector-personas-rapido.json"), "models"),
    (str(ROOT / "models" / "LEEME.md"), "models"),
]
licencia = ROOT / "cloud" / "licencia_publica.txt"
if licencia.exists():
    datas.append((str(licencia), "cloud"))

binaries = []
hiddenimports = (collect_submodules("uvicorn") + collect_submodules("sqlalchemy.dialects.sqlite")
                 + ["pystray._win32", "app.main", "cloud.main"])
for pkg in ("tzdata",):   # tzdata: zonas horarias en Windows
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib.tests", "pytest", "IPython", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Traffiqui",
    icon=str(ROOT / "packaging" / "traffiqui.ico"),
    console=False,          # sin ventana negra: se maneja desde el icono de la bandeja
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Traffiqui", upx=False)
