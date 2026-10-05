# -*- mode: python -*-
"""
latexinter.spec - Empaqueta Latexinter con PyInstaller.

    pyinstaller installer/latexinter.spec

Deja en dist/Latexinter/ dos programas que comparten las bibliotecas:
Latexinter.exe (la ventana) y latexinter-cli.exe (la línea de comandos).
Lo normal es no llamarlo a mano, sino con installer/build.ps1.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

RAIZ = Path(SPECPATH).parent
ICONO = str(RAIZ / "assets" / "latexinter.ico")

datas = [(str(RAIZ / "assets"), "assets")]
binaries = []
hiddenimports = []
# PyMuPDF trae módulos que se cargan sin import explícito y los modelos .onnx
# del análisis de maquetación: sin collect_all no entran en el paquete.
for paquete in ("pymupdf", "fitz", "pymupdf4llm"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

# El OCR de fórmulas (pix2tex) es opcional y arrastra PyTorch: 1,5 GB.
EXCLUIR = [
    "pix2tex", "torch", "torchvision", "transformers", "timm",
    "tkinter", "matplotlib", "IPython", "pytest",
]


def analizar(script: str) -> Analysis:
    return Analysis(
        [str(RAIZ / script)],
        pathex=[str(RAIZ)],
        datas=datas,
        binaries=binaries,
        hiddenimports=hiddenimports,
        excludes=EXCLUIR,
    )


ventana = analizar("app.py")
consola = analizar("cli.py")

exe_ventana = EXE(
    PYZ(ventana.pure),
    ventana.scripts,
    [],
    exclude_binaries=True,
    name="Latexinter",
    icon=ICONO,
    console=False,
    upx=False,          # UPX hace que algunos antivirus lo marquen como sospechoso
)
exe_consola = EXE(
    PYZ(consola.pure),
    consola.scripts,
    [],
    exclude_binaries=True,
    name="latexinter-cli",
    icon=ICONO,
    console=True,
    upx=False,
)

COLLECT(
    exe_ventana, ventana.binaries, ventana.datas,
    exe_consola, consola.binaries, consola.datas,
    upx=False,
    name="Latexinter",
)
