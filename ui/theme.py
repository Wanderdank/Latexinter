"""
theme.py - Colores, tipografías y hoja de estilos de la aplicación.

Todo el aspecto visual está aquí para que los demás módulos no lleven colores
sueltos por dentro. Hay dos paletas de neutros cálidos, como papel y tinta, con
un solo color de acento: lo que manda en la pantalla es el documento.

Los colores se leen como `theme.TEXTO`. Al cambiar de paleta, `aplicar()` los
reemplaza y avisa por `avisador.cambiado` a quien los haya guardado (el
resaltado de sintaxis, el fondo del visor de PDF).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QSettings, QStandardPaths, pyqtSignal
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QApplication

CLARO = "claro"
OSCURO = "oscuro"
SISTEMA = "sistema"

_PALETAS = {
    CLARO: {
        "FONDO": "#f6f5f2",
        "FONDO_PANEL": "#ffffff",
        "FONDO_CAMPO": "#ffffff",
        "FONDO_HOVER": "#ecebe6",
        "FONDO_ACTIVO": "#e2e0da",
        "FONDO_VISOR": "#e6e4de",
        "BORDE": "#d8d6cf",
        "BORDE_SUAVE": "#e6e4de",
        "BORDE_FUERTE": "#b5b3ab",
        "TEXTO": "#1d1d1b",
        "TEXTO_SUAVE": "#5e5d58",
        "TEXTO_TENUE": "#8f8e88",
        "ACENTO": "#0f6f63",
        "ACENTO_HOVER": "#0b5c52",
        "SOBRE_ACENTO": "#ffffff",
        "SELECCION": "#cfe5e0",
        "VERDE": "#1e7d4f",
        "AMBAR": "#96650a",
        "ROJO": "#b3362b",
        "FORMATO_PDF": "#a33a2c",
        "FORMATO_WORD": "#2b5c9e",
        "FORMATO_LATEX": "#2f7a5b",
        "COLOR_COMANDO": "#1f5f99",
        "COLOR_ENTORNO": "#8a5a14",
        "COLOR_MATEMATICAS": "#0f6f63",
        "COLOR_COMENTARIO": "#8f8e88",
        "COLOR_LLAVE": "#77766f",
        "COLOR_SECCION": "#1d1d1b",
        "COLOR_REFERENCIA": "#6b4c9a",
        "COLOR_LINEA_ACTUAL": "#f3f2ee",
        "COLOR_SELECCION_BUSQUEDA": "#f2dfa6",
        "COLOR_SYNCTEX": "#c9860a",
        "COLOR_MARCA_PDF": "#2b7f73",
    },
    OSCURO: {
        "FONDO": "#18191b",
        "FONDO_PANEL": "#1f2023",
        "FONDO_CAMPO": "#141517",
        "FONDO_HOVER": "#2a2b2f",
        "FONDO_ACTIVO": "#333539",
        "FONDO_VISOR": "#111214",
        "BORDE": "#303236",
        "BORDE_SUAVE": "#26282b",
        "BORDE_FUERTE": "#4c4e53",
        "TEXTO": "#e3e2de",
        "TEXTO_SUAVE": "#a1a09b",
        "TEXTO_TENUE": "#6f6f6b",
        "ACENTO": "#58b09f",
        "ACENTO_HOVER": "#6cc0af",
        "SOBRE_ACENTO": "#0f1413",
        "SELECCION": "#2c4a45",
        "VERDE": "#6fb98f",
        "AMBAR": "#d9a54a",
        "ROJO": "#e5736b",
        "FORMATO_PDF": "#e08a7c",
        "FORMATO_WORD": "#8fb3e3",
        "FORMATO_LATEX": "#7fc2a3",
        "COLOR_COMANDO": "#8ab4d8",
        "COLOR_ENTORNO": "#c9a26b",
        "COLOR_MATEMATICAS": "#7fb8a4",
        "COLOR_COMENTARIO": "#6f6f6b",
        "COLOR_LLAVE": "#8a8a85",
        "COLOR_SECCION": "#f2f1ed",
        "COLOR_REFERENCIA": "#b5a6d0",
        "COLOR_LINEA_ACTUAL": "#1f2023",
        "COLOR_SELECCION_BUSQUEDA": "#5c4a1f",
        "COLOR_SYNCTEX": "#e0a93f",
        "COLOR_MARCA_PDF": "#58b09f",
    },
}

# Se rellenan con aplicar(); estos valores son los del arranque.
FONDO = FONDO_PANEL = FONDO_CAMPO = FONDO_HOVER = FONDO_ACTIVO = FONDO_VISOR = ""
BORDE = BORDE_SUAVE = BORDE_FUERTE = ""
TEXTO = TEXTO_SUAVE = TEXTO_TENUE = ""
ACENTO = ACENTO_HOVER = SOBRE_ACENTO = SELECCION = ""
VERDE = AMBAR = ROJO = ""
FORMATO_PDF = FORMATO_WORD = FORMATO_LATEX = ""
COLOR_COMANDO = COLOR_ENTORNO = COLOR_MATEMATICAS = COLOR_COMENTARIO = COLOR_LLAVE = ""
COLOR_SECCION = COLOR_REFERENCIA = COLOR_LINEA_ACTUAL = COLOR_SELECCION_BUSQUEDA = ""
COLOR_SYNCTEX = COLOR_MARCA_PDF = ""

actual: str = CLARO


class _Avisador(QObject):
    cambiado = pyqtSignal()


avisador = _Avisador()


def sistema_oscuro() -> bool:
    """Si Windows está en modo oscuro (en otros sistemas, se supone que no)."""
    if sys.platform != "win32":
        return False
    registro = QSettings(
        r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        QSettings.NativeFormat,
    )
    return registro.value("AppsUseLightTheme", 1, type=int) == 0


def resolver(preferencia: Optional[str]) -> str:
    """De lo que eligió el usuario (o «sistema») a una paleta concreta."""
    if preferencia in _PALETAS:
        return preferencia
    return OSCURO if sistema_oscuro() else CLARO


def _cargar(nombre: str) -> None:
    global actual
    actual = nombre
    globals().update(_PALETAS[nombre])


def aplicar(preferencia: Optional[str] = None) -> None:
    """Cambia la paleta y restyla toda la aplicación."""
    _cargar(resolver(preferencia))
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(hoja_de_estilos())
    avisador.cambiado.emit()


def mono_font(size: int = 11) -> QFont:
    """La mejor tipografía monoespaciada que haya instalada."""
    familias = QFontDatabase().families()
    for candidata in ("Cascadia Mono", "Cascadia Code", "JetBrains Mono",
                      "Fira Code", "Consolas"):
        if candidata in familias:
            fuente = QFont(candidata)
            break
    else:
        fuente = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    fuente.setPointSize(size)
    fuente.setStyleHint(QFont.Monospace)
    return fuente


def ui_font(size: int = 10) -> QFont:
    familias = QFontDatabase().families()
    nombre = "Segoe UI" if "Segoe UI" in familias else ""
    fuente = QFont(nombre) if nombre else QFont()
    fuente.setPointSize(size)
    return fuente


def _carpeta_recursos() -> Path:
    """Dónde se guardan los dibujos que la hoja de estilos necesita como archivo."""
    base = QStandardPaths.writableLocation(QStandardPaths.TempLocation)
    carpeta = Path(base or ".") / "latexinter-iconos"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def hoja_de_estilos() -> str:
    from . import icons

    carpeta = _carpeta_recursos()

    def imagen(nombre: str, color: str) -> str:
        return icons.exportar(nombre, color, carpeta).as_posix()

    marca = imagen("marca", SOBRE_ACENTO)
    flecha = imagen("chevron_abajo", TEXTO_SUAVE)
    derecha = imagen("chevron_derecha", TEXTO_SUAVE)

    return f"""
QWidget {{
    background: {FONDO};
    color: {TEXTO};
    font-size: 13px;
}}
QLabel, QCheckBox, QRadioButton, QScrollArea,
QScrollArea > QWidget > QWidget, QTabWidget, QTabBar, QProgressBar,
QSplitter, QToolBar, QStatusBar, QMenuBar, QStackedWidget {{
    background: transparent;
}}

/* ── Textos ─────────────────────────────────────────── */
QLabel#titulo      {{ font-size: 16px; font-weight: 600; }}
QLabel#subtitulo,
QLabel#pista       {{ color: {TEXTO_SUAVE}; }}
QLabel#tenue       {{ color: {TEXTO_TENUE}; font-size: 12px; }}
QLabel#seccion     {{ color: {TEXTO_SUAVE}; font-weight: 600; font-size: 12px; }}
QLabel#estado      {{ color: {TEXTO_SUAVE}; padding: 0 8px; font-size: 12px; }}
QLabel#aviso       {{ color: {AMBAR}; }}
QLabel#error       {{ color: {ROJO}; }}
QLabel#correcto    {{ color: {VERDE}; }}

/* ── Etiquetas de formato ───────────────────────────── */
QLabel#formato {{
    font-size: 10px; font-weight: 700;
    border: 1px solid {BORDE_FUERTE}; border-radius: 3px;
    padding: 1px 0; color: {TEXTO_SUAVE};
}}
QLabel#formato[formato="pdf"]  {{ color: {FORMATO_PDF}; border-color: {FORMATO_PDF}; }}
QLabel#formato[formato="docx"] {{ color: {FORMATO_WORD}; border-color: {FORMATO_WORD}; }}
QLabel#formato[formato="tex"]  {{ color: {FORMATO_LATEX}; border-color: {FORMATO_LATEX}; }}

/* ── Paneles ────────────────────────────────────────── */
QFrame#panel       {{ background: {FONDO_PANEL}; border: none; }}
QFrame#panel QLabel, QFrame#panel QCheckBox {{ background: transparent; }}
QFrame#separador   {{ background: {BORDE}; border: none; }}
QFrame#lista {{
    background: {FONDO_PANEL};
    border: 1px solid {BORDE};
    border-radius: 4px;
}}
QFrame#lista[activa="true"] {{ border: 1px solid {ACENTO}; background: {SELECCION}; }}
QFrame#fila {{ background: transparent; border: none; border-radius: 3px; }}
QFrame#fila QLabel {{ background: transparent; }}
QFrame#fila:hover {{ background: {FONDO_HOVER}; }}
QFrame#fila[elegida="true"] {{ background: {FONDO_ACTIVO}; }}
QFrame#barra {{
    background: {FONDO};
    border: none;
    border-bottom: 1px solid {BORDE};
}}
QFrame#barra QLabel {{ background: transparent; }}
QFrame#avisos {{
    background: transparent;
    border: 1px solid {BORDE};
    border-left: 2px solid {AMBAR};
}}
QFrame#avisos QLabel {{ background: transparent; }}
QWidget#visor {{ background: {FONDO_VISOR}; }}
QLabel#pagina {{ background: white; border: 1px solid {BORDE_FUERTE}; }}

/* ── Botones ────────────────────────────────────────── */
QPushButton {{
    background: {FONDO_PANEL};
    border: 1px solid {BORDE};
    border-radius: 4px;
    padding: 5px 12px;
    color: {TEXTO};
}}
QPushButton:hover    {{ background: {FONDO_HOVER}; border-color: {BORDE_FUERTE}; }}
QPushButton:pressed  {{ background: {FONDO_ACTIVO}; }}
QPushButton:disabled {{ color: {TEXTO_TENUE}; background: transparent; border-color: {BORDE_SUAVE}; }}
QPushButton:focus    {{ border-color: {ACENTO}; }}
QPushButton#principal {{
    background: {ACENTO}; border: 1px solid {ACENTO}; color: {SOBRE_ACENTO};
    font-weight: 600; padding: 8px 12px;
}}
QPushButton#principal:hover    {{ background: {ACENTO_HOVER}; border-color: {ACENTO_HOVER}; }}
QPushButton#principal:disabled {{
    background: {FONDO_ACTIVO}; border-color: {FONDO_ACTIVO}; color: {TEXTO_TENUE};
}}
QPushButton#plano {{
    background: transparent; border: none; padding: 4px; color: {TEXTO_SUAVE};
}}
QPushButton#plano:hover {{ color: {TEXTO}; background: {FONDO_HOVER}; }}
QPushButton#plano:disabled {{ color: {TEXTO_TENUE}; background: transparent; }}
QPushButton#desplegar {{
    background: transparent; border: none; padding: 4px 0;
    color: {TEXTO_SUAVE}; text-align: left; font-weight: 600; font-size: 12px;
}}
QPushButton#desplegar:hover {{ color: {TEXTO}; }}

/* ── Control segmentado ─────────────────────────────── */
QPushButton#segmento {{
    background: transparent;
    color: {TEXTO_SUAVE};
    border: 1px solid {BORDE};
    border-radius: 0;
    padding: 5px 14px;
    margin-left: -1px;
}}
QPushButton#segmento:hover {{ background: {FONDO_HOVER}; color: {TEXTO}; }}
QPushButton#segmento:checked {{
    background: {FONDO_ACTIVO}; color: {TEXTO};
    border-color: {BORDE_FUERTE};
}}
QPushButton#segmento[posicion="primero"] {{
    border-top-left-radius: 4px; border-bottom-left-radius: 4px; margin-left: 0;
}}
QPushButton#segmento[posicion="ultimo"] {{
    border-top-right-radius: 4px; border-bottom-right-radius: 4px;
}}
QPushButton#segmento[posicion="unico"] {{ border-radius: 4px; margin-left: 0; }}

/* ── Campos ─────────────────────────────────────────── */
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QTextEdit {{
    background: {FONDO_CAMPO};
    border: 1px solid {BORDE};
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: {SELECCION};
    selection-color: {TEXTO};
}}
QPlainTextEdit, QTextEdit {{ padding: 4px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACENTO}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {TEXTO_TENUE}; background: transparent; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({flecha}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {FONDO_PANEL};
    border: 1px solid {BORDE_FUERTE};
    selection-background-color: {FONDO_ACTIVO};
    selection-color: {TEXTO};
    outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDE_FUERTE}; border-radius: 3px; background: {FONDO_CAMPO};
}}
QCheckBox::indicator:hover {{ border-color: {TEXTO_SUAVE}; }}
QCheckBox::indicator:checked {{
    background: {ACENTO}; border-color: {ACENTO}; image: url({marca});
}}

/* ── Pestañas ───────────────────────────────────────── */
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDE}; top: -1px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {TEXTO_SUAVE};
    padding: 6px 12px; border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXTO}; border-bottom: 2px solid {TEXTO}; }}
QTabBar::tab:hover:!selected {{ color: {TEXTO}; }}
QTabBar::close-button {{ subcontrol-position: right; }}

/* ── Listas y árboles ───────────────────────────────── */
QTreeView, QTreeWidget, QListWidget {{
    background: transparent;
    border: none;
    outline: none;
    show-decoration-selected: 1;
}}
QTreeView::item, QTreeWidget::item, QListWidget::item {{
    padding: 3px 2px; border-radius: 3px;
}}
QTreeView::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {FONDO_ACTIVO};
    color: {TEXTO};
}}
QTreeView::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{
    background: {FONDO_HOVER};
}}
QListWidget#miniaturas::item {{ border: 2px solid transparent; padding: 2px; }}
QListWidget#miniaturas::item:hover {{ background: {FONDO_HOVER}; }}
QListWidget#miniaturas::item:selected {{ background: {SELECCION}; border: 2px solid {ACENTO}; }}
QTreeView::branch:has-children:closed{{ image: url({derecha}); }}
QTreeView::branch:has-children:open   {{ image: url({flecha}); }}
QHeaderView::section {{
    background: transparent; color: {TEXTO_SUAVE}; font-size: 12px;
    border: none; border-bottom: 1px solid {BORDE}; padding: 3px 4px;
}}

/* ── Menús y barra de herramientas ──────────────────── */
QMenuBar {{ padding: 0 4px; }}
QMenuBar::item {{ padding: 4px 8px; background: transparent; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {FONDO_HOVER}; }}
QMenu {{
    background: {FONDO_PANEL};
    border: 1px solid {BORDE_FUERTE};
    padding: 4px;
}}
QMenu::item {{ padding: 5px 24px 5px 10px; border-radius: 3px; }}
QMenu::item:selected {{ background: {FONDO_ACTIVO}; }}
QMenu::item:disabled {{ color: {TEXTO_TENUE}; }}
QMenu::separator {{ height: 1px; background: {BORDE}; margin: 4px 6px; }}
QToolBar {{ border: none; border-bottom: 1px solid {BORDE}; spacing: 2px; padding: 4px 8px; }}
QToolBar QToolButton {{
    background: transparent; border: none;
    border-radius: 3px; padding: 4px 6px; color: {TEXTO};
}}
QToolBar QToolButton:hover   {{ background: {FONDO_HOVER}; }}
QToolBar QToolButton:pressed {{ background: {FONDO_ACTIVO}; }}
QToolBar QToolButton:checked {{ background: {FONDO_ACTIVO}; }}
QToolBar QToolButton:disabled {{ color: {TEXTO_TENUE}; }}
QToolBar::separator {{ background: {BORDE}; width: 1px; margin: 4px 6px; }}

/* ── Varios ─────────────────────────────────────────── */
QProgressBar {{
    background: {BORDE_SUAVE}; border: none; max-height: 2px; min-height: 2px;
}}
QProgressBar::chunk {{ background: {ACENTO}; }}
QSplitter::handle {{ background: {BORDE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}
QScrollBar:vertical   {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {BORDE}; border: 2px solid transparent; border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDE}; border: 2px solid transparent; border-radius: 3px; min-width: 30px;
}}
QScrollBar::handle:hover {{ background: {BORDE_FUERTE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ border-top: 1px solid {BORDE}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {FONDO_PANEL}; color: {TEXTO};
    border: 1px solid {BORDE_FUERTE}; padding: 4px;
}}
QDialog {{ background: {FONDO}; }}
QMessageBox QLabel {{ background: transparent; }}
"""


_cargar(CLARO)
