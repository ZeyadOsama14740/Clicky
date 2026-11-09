# PyInstaller spec: builds dist/Clicky.exe (run scripts/fetch_model.py first)
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = [
    ("clicky/static", "clicky/static"),
    ("clicky/assets", "clicky/assets"),
]
datas += collect_data_files("mediapipe", includes=["**/*.binarypb", "**/*.tflite", "**/*.txt"])
binaries = collect_dynamic_libs("mediapipe")

a = Analysis(
    ["run_clicky.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "mediapipe.tasks.python.vision",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "pystray._win32",
    ],
    excludes=["tkinter", "matplotlib.tests", "IPython", "jupyter", "jax", "tensorflow", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Clicky",
    console=False,
    icon="assets/clicky.ico",
    upx=False,
)
