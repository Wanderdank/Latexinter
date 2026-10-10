"""
ui - La interfaz de escritorio de Latexinter.

    from ui import run
    run()

Módulos:
    theme            colores, tipografías y hoja de estilos
    latex_syntax     resaltado, comandos para autocompletar y fragmentos
    latex_editor     el editor de código
    pdf_view         el visor de PDF con zoom y SyncTeX
    panels           esquema, problemas, archivos y barra de búsqueda
    templates        documentos de partida
    editor_page      el entorno de edición completo
    converter_panel  el conversor entre formatos
    main_window      la ventana que junta todo
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── PyMuPDF tiene que cargarse ANTES que PyQt5 ──────────────────────────
# Las dos bibliotecas traen su propia copia de dependencias nativas. Si Qt
# entra primero, PyMuPDF acaba resolviendo las suyas contra las de Qt y
# extrae los PDF de otra manera: las ecuaciones centradas dejan de salir como
# imagen y aparecen como texto descuadrado, y el índice deja de detectarse.
# Cargándolo aquí, lo primero de todo, el conversor se comporta igual desde la
# ventana que desde la línea de comandos.
try:
    import fitz  # noqa: F401
    import pymupdf4llm  # noqa: F401
except ImportError:      # sin PyMuPDF la app arranca igual, sin conversor
    pass

__version__ = "0.2.0"

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRATCH_DIR = PROJECT_DIR / "documentos"
ICONO = PROJECT_DIR / "assets" / "latexinter.ico"

# Instalado (empaquetado con PyInstaller), la carpeta del programa no admite
# escritura: los documentos de trabajo van a «Documentos\Latexinter».
EMPAQUETADO = getattr(sys, "frozen", False)

__all__ = ["run", "PROJECT_DIR", "SCRATCH_DIR", "__version__"]


def _carpeta_de_trabajo() -> Path:
    if not EMPAQUETADO:
        return SCRATCH_DIR
    from PyQt5.QtCore import QStandardPaths

    documentos = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    return Path(documentos or Path.home()) / "Latexinter"


def _instalar_avisador_de_errores() -> None:
    """
    PyQt5 cierra la aplicación de golpe si una excepción escapa de un slot,
    y con ella se pierde lo que no estuviera guardado. En su lugar se enseña
    el error y la ventana sigue viva.
    """
    import traceback

    from PyQt5.QtWidgets import QMessageBox

    def avisar(tipo, valor, rastro) -> None:
        texto = "".join(traceback.format_exception(tipo, valor, rastro))
        if sys.stderr is not None:          # instalado no hay consola
            sys.stderr.write(texto)
        try:
            caja = QMessageBox(QMessageBox.Critical, "Latexinter",
                               f"Error inesperado: {valor}")
            caja.setInformativeText("La aplicación sigue abierta. Guarda tu trabajo.")
            caja.setDetailedText(texto)
            caja.exec_()
        except Exception:
            pass

    sys.excepthook = avisar


def run(argv: list[str] | None = None) -> int:
    """Arranca la aplicación. Devuelve el código de salida."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication

    from converters.common import refresh_path

    from . import theme
    from .main_window import APP_NAME, MainWindow

    argv = list(sys.argv if argv is None else argv)
    refresh_path()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    if ICONO.exists():
        app.setWindowIcon(QIcon(str(ICONO)))
    app.setStyleSheet(theme.STYLESHEET)
    app.setFont(theme.ui_font(10))

    _instalar_avisador_de_errores()

    ventana = MainWindow(_carpeta_de_trabajo())
    ventana.show()

    # Permite abrir archivos directamente:  python app.py documento.tex
    for argumento in argv[1:]:
        ruta = Path(argumento)
        if not ruta.exists():
            continue
        if ruta.suffix.lower() in (".tex", ".bib", ".cls", ".sty"):
            ventana.abrir_documento(str(ruta))
        else:
            ventana.paginas.setCurrentIndex(1)
            ventana.converter_page.set_source(ruta)

    return app.exec_()
