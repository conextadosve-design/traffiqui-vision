# PyInstaller: genera dist/Traffiqui/Traffiqui.exe con la BASE (Python, librerías y modelos).
#   python packaging/make_icon.py
#   pyinstaller packaging/traffiqui.spec --noconfirm
#   python packaging/preparar_codigo.py      → copia app/ y cloud/ a dist/Traffiqui/codigo
# El código va aparte (dist/Traffiqui/codigo): así una actualización solo cambia esa carpeta.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
OWN = ("app", "cloud")   # nuestros paquetes: se analizan para encontrar sus dependencias, pero no se empaquetan

datas = [
    (str(ROOT / "models" / "detector-personas.onnx"), "models"),
    (str(ROOT / "models" / "detector-personas.json"), "models"),
    (str(ROOT / "models" / "detector-personas-rapido.onnx"), "models"),
    (str(ROOT / "models" / "detector-personas-rapido.json"), "models"),
    (str(ROOT / "models" / "LEEME.md"), "models"),
    (str(ROOT / "packaging" / "BASE_VERSION"), "."),
]

binaries = []
hiddenimports = (collect_submodules("uvicorn") + collect_submodules("sqlalchemy.dialects.sqlite")
                 + ["pystray._win32", "app.main", "app.launcher", "cloud.main"]
                 # dependencias que el código usa y la base debe traer aunque hoy nadie las importe al arrancar
                 + ["smtplib", "email.message", "zipfile", "sqlite3", "ipaddress", "statistics", "uuid"])
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
    # torch, transformers y ultralytics solo sirven para exportar o comparar modelos (tools/detector)
    excludes=["tkinter", "matplotlib.tests", "pytest", "IPython", "notebook", "torch", "torchvision",
              "transformers", "ultralytics", "onnx", "onnxscript", "pycocotools", "pyarrow", "playwright",
              "av", "matplotlib"],   # supervision los importa solo para anotar vídeo; ByteTrack no los usa
    noarchive=False,
)
a.pure = [m for m in a.pure if m[0].split(".")[0] not in OWN]   # el código va en la carpeta "codigo"
a.datas = [(dest.replace("BASE_VERSION", "base_version.txt"), src, kind) for dest, src, kind in a.datas]
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
