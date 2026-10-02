"""
theme.py - Colores, tipografías y hoja de estilos de la aplicación.

Todo el aspecto visual está aquí para que los demás módulos no lleven colores
sueltos por dentro.
"""

from __future__ import annotations

from PyQt5.QtGui import QFont, QFontDatabase

# ── Paleta ──────────────────────────────────────────────────
FONDO = "#0f1020"
FONDO_TARJETA = "#171834"
FONDO_CAMPO = "#101128"
BORDE = "#2a2b55"
BORDE_SUAVE = "#23244a"
BORDE_ACTIVO = "#6d4aff"

TEXTO = "#e6e6f0"
TEXTO_SUAVE = "#8b8bab"
TEXTO_TENUE = "#5f6084"

ACENTO = "#6d4aff"
ACENTO_CLARO = "#a78bfa"
CIAN = "#38bdf8"
VERDE = "#34d399"
AMBAR = "#fbbf24"
ROJO = "#f87171"
ROSA = "#f472b6"

# ── Colores del resaltado de sintaxis ───────────────────────
COLOR_COMANDO = ACENTO_CLARO
COLOR_ENTORNO = ROSA
COLOR_MATEMATICAS = CIAN
COLOR_COMENTARIO = TEXTO_TENUE
COLOR_LLAVE = "#6b6c96"
COLOR_SECCION = "#ffffff"
COLOR_REFERENCIA = VERDE
COLOR_LINEA_ACTUAL = "#181936"
COLOR_SELECCION_BUSQUEDA = "#4b3a8f"
COLOR_SYNCTEX = "#f0b429"


def mono_font(size: int = 11) -> QFont:
    """La mejor tipografía monoespaciada que haya instalada."""
    familias = QFontDatabase().families()
    for candidata in ("Cascadia Code", "Cascadia Mono", "JetBrains Mono",
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


STYLESHEET = f"""
QWidget {{
    background: {FONDO};
    color: {TEXTO};
    font-size: 13px;
}}
QLabel, QCheckBox, QRadioButton, QScrollArea,
QScrollArea > QWidget > QWidget, QTabWidget, QTabBar, QProgressBar,
QSplitter, QToolBar, QStatusBar, QMenuBar {{
    background: transparent;
}}

/* ── Textos ─────────────────────────────────────────── */
QLabel#titulo      {{ font-size: 22px; font-weight: 700; color: #ffffff; }}
QLabel#subtitulo,
QLabel#pista       {{ color: {TEXTO_SUAVE}; }}
QLabel#seccion     {{
    color: #a5a5c8; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px; font-size: 11px;
}}
QLabel#estado      {{ color: {TEXTO_SUAVE}; padding: 0 8px; }}

/* ── Tarjetas y paneles ─────────────────────────────── */
QFrame#tarjeta {{
    background: {FONDO_TARJETA};
    border: 1px solid {BORDE};
    border-radius: 12px;
}}
QFrame#zona {{
    background: #14152c;
    border: 2px dashed #3a3b72;
    border-radius: 12px;
}}
QFrame#zona[activa="true"] {{
    border-color: {ACENTO};
    background: #1b1c3d;
}}
QFrame#barra {{
    background: {FONDO_TARJETA};
    border: 1px solid {BORDE};
    border-radius: 8px;
}}

/* ── Botones ────────────────────────────────────────── */
QPushButton {{
    background: {BORDE_SUAVE};
    border: 1px solid #33356a;
    border-radius: 8px;
    padding: 7px 14px;
    color: #dcdcf0;
}}
QPushButton:hover    {{ background: #2c2d5c; }}
QPushButton:pressed  {{ background: #1d1e40; }}
QPushButton:disabled {{ color: #5c5c7a; background: #1a1b33; }}
QPushButton:checked  {{ background: {ACENTO}; border-color: {ACENTO}; color: white; }}
QPushButton#principal {{
    background: {ACENTO}; border: none; color: white;
    font-weight: 600; font-size: 15px; padding: 12px;
}}
QPushButton#principal:hover    {{ background: #7d5eff; }}
QPushButton#principal:disabled {{ background: #35305e; color: #8a8aa8; }}
QPushButton#plano {{
    background: transparent; border: none; padding: 4px 8px; color: {TEXTO_SUAVE};
}}
QPushButton#plano:hover {{ color: {TEXTO}; background: {BORDE_SUAVE}; }}

/* ── Campos ─────────────────────────────────────────── */
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QTextEdit {{
    background: {FONDO_CAMPO};
    border: 1px solid #2e2f5e;
    border-radius: 7px;
    padding: 6px 8px;
    selection-background-color: {ACENTO};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus {{
    border-color: {ACENTO};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {FONDO_TARJETA};
    border: 1px solid #33356a;
    selection-background-color: {ACENTO};
    outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #3a3b72; border-radius: 4px; background: {FONDO_CAMPO};
}}
QCheckBox::indicator:checked {{ background: {ACENTO}; border-color: {ACENTO}; }}

/* ── Pestañas ───────────────────────────────────────── */
QTabWidget::pane {{ border: 1px solid {BORDE}; border-radius: 10px; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {TEXTO_SUAVE};
    padding: 8px 16px; border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: #ffffff; border-bottom: 2px solid {ACENTO}; }}
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
    padding: 4px 2px; border-radius: 5px;
}}
QTreeView::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {ACENTO};
    color: white;
}}
QTreeView::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{
    background: {BORDE_SUAVE};
}}
QHeaderView::section {{
    background: transparent; color: {TEXTO_SUAVE};
    border: none; border-bottom: 1px solid {BORDE}; padding: 4px;
}}

/* ── Menús y barra de herramientas ──────────────────── */
QMenuBar::item {{ padding: 6px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {BORDE_SUAVE}; border-radius: 6px; }}
QMenu {{
    background: {FONDO_TARJETA};
    border: 1px solid {BORDE};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACENTO}; }}
QMenu::separator {{ height: 1px; background: {BORDE}; margin: 5px 8px; }}
QToolBar {{ border: none; spacing: 4px; padding: 4px 6px; }}
QToolBar QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: 7px; padding: 5px 10px; color: {TEXTO};
}}
QToolBar QToolButton:hover  {{ background: {BORDE_SUAVE}; border-color: #33356a; }}
QToolBar QToolButton:checked {{ background: {ACENTO}; color: white; }}
QToolBar::separator {{ background: {BORDE}; width: 1px; margin: 5px 6px; }}

/* ── Varios ─────────────────────────────────────────── */
QProgressBar {{
    background: {FONDO_CAMPO}; border: 1px solid {BORDE_SUAVE};
    border-radius: 3px; max-height: 6px; text-align: center;
}}
QProgressBar::chunk {{ background: {ACENTO}; border-radius: 3px; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical   {{ height: 6px; }}
QScrollBar:vertical   {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical   {{ background: #33356a; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:horizontal {{ background: #33356a; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: #45478a; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{
    background: {FONDO_TARJETA}; color: {TEXTO};
    border: 1px solid {BORDE}; border-radius: 6px; padding: 6px;
}}
"""
