"""
panels.py - Los paneles laterales e inferiores del editor.

OutlinePanel    el esquema del documento (partes, capítulos, secciones…)
ProblemsPanel   los errores y avisos de la última compilación
ProjectPanel    los archivos de la carpeta del documento
FindBar         la barra de buscar y reemplazar
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QDir, QModelIndex, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileSystemModel,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from . import theme
from converters.tools import ERROR, INFO, WARNING, Problem


# ════════════════════════════════════════════════════════════
# Esquema del documento
# ════════════════════════════════════════════════════════════

_NIVELES = {
    "part": 0, "chapter": 1, "section": 2, "subsection": 3,
    "subsubsection": 4, "paragraph": 5,
}

_SECCION = re.compile(
    r"^[ \t]*\\(?P<tipo>part|chapter|section|subsection|subsubsection|paragraph)"
    r"\*?\s*(?:\[[^\]]*\])?\{(?P<titulo>.*)$"
)
_FRAME = re.compile(r"^[ \t]*\\begin\{frame\}(?:\[[^\]]*\])?\s*\{(?P<titulo>.*)$")


def _titulo_equilibrado(resto: str) -> str:
    """Extrae el contenido de {…} contando las llaves que se abren y cierran."""
    profundidad = 1
    salida: list[str] = []
    for caracter in resto:
        if caracter == "{":
            profundidad += 1
        elif caracter == "}":
            profundidad -= 1
            if profundidad == 0:
                break
        salida.append(caracter)
    texto = "".join(salida)
    texto = re.sub(r"\\[A-Za-z]+\*?\s*", "", texto)
    return re.sub(r"[{}$\\]", "", texto).strip()


class OutlinePanel(QWidget):
    """Árbol de secciones. Al pinchar, el editor salta a esa línea."""

    goto = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setIndentation(14)
        self.arbol.itemActivated.connect(self._activado)
        self.arbol.itemClicked.connect(self._activado)
        layout.addWidget(self.arbol)

        self.vacio = QLabel("El documento todavía no tiene secciones.")
        self.vacio.setObjectName("pista")
        self.vacio.setWordWrap(True)
        self.vacio.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.vacio)

    def refresh(self, texto: str) -> None:
        self.arbol.clear()
        pila: list[tuple[int, QTreeWidgetItem]] = []
        encontrados = 0

        for numero, linea in enumerate(texto.split("\n"), start=1):
            if linea.lstrip().startswith("%"):
                continue

            match = _SECCION.match(linea)
            if match:
                nivel = _NIVELES[match.group("tipo")]
                titulo = _titulo_equilibrado(match.group("titulo")) or match.group("tipo")
            else:
                match = _FRAME.match(linea)
                if not match:
                    continue
                nivel = 3
                titulo = _titulo_equilibrado(match.group("titulo")) or "Diapositiva"

            item = QTreeWidgetItem([titulo])
            item.setData(0, Qt.UserRole, numero)
            if nivel <= 2:
                fuente = item.font(0)
                fuente.setWeight(QFont.DemiBold)
                item.setFont(0, fuente)

            while pila and pila[-1][0] >= nivel:
                pila.pop()
            if pila:
                pila[-1][1].addChild(item)
            else:
                self.arbol.addTopLevelItem(item)
            pila.append((nivel, item))
            encontrados += 1

        self.arbol.expandAll()
        self.arbol.setVisible(bool(encontrados))
        self.vacio.setVisible(not encontrados)

    def _activado(self, item: QTreeWidgetItem, _columna: int = 0) -> None:
        numero = item.data(0, Qt.UserRole)
        if numero:
            self.goto.emit(int(numero))


# ════════════════════════════════════════════════════════════
# Problemas
# ════════════════════════════════════════════════════════════

_ICONOS = {ERROR: "✗", WARNING: "⚠", INFO: "•"}
_COLORES = {ERROR: theme.ROJO, WARNING: theme.AMBAR, INFO: theme.TEXTO_SUAVE}


class ProblemsPanel(QWidget):
    """Errores y avisos de la última compilación, clicables."""

    goto = pyqtSignal(object, int)              # archivo (Path o None), línea

    def __init__(self, parent=None):
        super().__init__(parent)
        self._problemas: list[Problem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        cabecera = QHBoxLayout()
        self.resumen = QLabel("Sin compilar todavía.")
        self.resumen.setObjectName("pista")
        cabecera.addWidget(self.resumen)
        cabecera.addStretch(1)

        self.ver_avisos = QCheckBox("Mostrar avisos")
        self.ver_avisos.setChecked(True)
        self.ver_avisos.toggled.connect(lambda _: self._pintar())
        cabecera.addWidget(self.ver_avisos)
        layout.addLayout(cabecera)

        self.lista = QTreeWidget()
        self.lista.setHeaderLabels(["", "Problema", "Dónde"])
        self.lista.setRootIsDecorated(False)
        cabecera = self.lista.header()
        cabecera.setSectionResizeMode(0, QHeaderView.Fixed)
        cabecera.setSectionResizeMode(1, QHeaderView.Stretch)
        cabecera.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.lista.setColumnWidth(0, 26)
        self.lista.itemActivated.connect(self._activado)
        self.lista.itemDoubleClicked.connect(self._activado)
        layout.addWidget(self.lista, 1)

    def set_problems(self, problemas: list[Problem]) -> None:
        self._problemas = problemas
        self._pintar()

    def clear(self) -> None:
        self.set_problems([])

    def _pintar(self) -> None:
        self.lista.clear()
        errores = [p for p in self._problemas if p.severity == ERROR]
        avisos = [p for p in self._problemas if p.severity != ERROR]

        mostrados = errores + (avisos if self.ver_avisos.isChecked() else [])
        for problema in mostrados:
            item = QTreeWidgetItem([
                _ICONOS.get(problema.severity, "•"),
                problema.message,
                problema.location,
            ])
            item.setForeground(0, QBrush(QColor(_COLORES.get(problema.severity, theme.TEXTO))))
            if problema.severity != ERROR:
                item.setForeground(1, QBrush(QColor(theme.TEXTO_SUAVE)))
            pista = problema.message
            if problema.origin == "chktex":
                pista += "\n\n(aviso de estilo detectado por chktex)"
            item.setToolTip(1, pista)
            item.setData(0, Qt.UserRole, (problema.file, problema.line))
            self.lista.addTopLevelItem(item)

        if not self._problemas:
            self.resumen.setText("Ningún problema. El documento compila limpio.")
            self.resumen.setStyleSheet(f"color: {theme.VERDE};")
        else:
            partes = []
            if errores:
                partes.append(f"{len(errores)} error{'es' if len(errores) != 1 else ''}")
            if avisos:
                partes.append(f"{len(avisos)} aviso{'s' if len(avisos) != 1 else ''}")
            self.resumen.setText(" · ".join(partes))
            self.resumen.setStyleSheet(
                f"color: {theme.ROJO if errores else theme.AMBAR};"
            )

    def _activado(self, item: QTreeWidgetItem, _columna: int = 0) -> None:
        datos = item.data(0, Qt.UserRole)
        if not datos:
            return
        archivo, linea = datos
        if linea:
            self.goto.emit(archivo, int(linea))


# ════════════════════════════════════════════════════════════
# Archivos del proyecto
# ════════════════════════════════════════════════════════════

class ProjectPanel(QWidget):
    """Los archivos que hay junto al documento."""

    openFile = pyqtSignal(object)               # Path

    EXTENSIONES = [
        "*.tex", "*.bib", "*.cls", "*.sty", "*.md", "*.txt", "*.pdf",
        "*.png", "*.jpg", "*.jpeg", "*.svg", "*.eps", "*.docx", "*.csv",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.raiz: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.etiqueta = QLabel("Ninguna carpeta abierta")
        self.etiqueta.setObjectName("pista")
        self.etiqueta.setWordWrap(True)
        layout.addWidget(self.etiqueta)

        self.modelo = QFileSystemModel()
        self.modelo.setNameFilters(self.EXTENSIONES)
        self.modelo.setNameFilterDisables(False)
        self.modelo.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        self.vista = QTreeView()
        self.vista.setModel(self.modelo)
        self.vista.setHeaderHidden(True)
        self.vista.setIndentation(14)
        for columna in range(1, 4):
            self.vista.hideColumn(columna)
        self.vista.doubleClicked.connect(self._abrir)
        layout.addWidget(self.vista, 1)

    def set_root(self, carpeta: Path) -> None:
        carpeta = Path(carpeta)
        if not carpeta.is_dir():
            return
        self.raiz = carpeta
        self.etiqueta.setText(str(carpeta))
        self.modelo.setRootPath(str(carpeta))
        self.vista.setRootIndex(self.modelo.index(str(carpeta)))

    def _abrir(self, indice: QModelIndex) -> None:
        ruta = Path(self.modelo.filePath(indice))
        if ruta.is_file():
            self.openFile.emit(ruta)


# ════════════════════════════════════════════════════════════
# Buscar y reemplazar
# ════════════════════════════════════════════════════════════

class FindBar(QFrame):
    """Barra de búsqueda del editor. Se muestra con Ctrl+F."""

    buscar = pyqtSignal(str, bool, bool, bool)      # texto, hacia atrás, mayúsculas, regex
    reemplazar = pyqtSignal(str, str, bool)         # buscar, poner, todo
    cerrada = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("barra")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # Fila de búsqueda
        fila = QHBoxLayout()
        fila.setSpacing(6)
        self.campo = QLineEdit()
        self.campo.setPlaceholderText("Buscar")
        self.campo.returnPressed.connect(lambda: self._buscar(False))
        self.campo.textChanged.connect(lambda _: self._buscar(False, mover=False))
        fila.addWidget(self.campo, 1)

        self.resultado = QLabel("")
        self.resultado.setObjectName("pista")
        self.resultado.setMinimumWidth(90)
        fila.addWidget(self.resultado)

        for texto, tooltip, accion in (
            ("↑", "Anterior (Shift+F3)", lambda: self._buscar(True)),
            ("↓", "Siguiente (F3)", lambda: self._buscar(False)),
        ):
            boton = QPushButton(texto)
            boton.setObjectName("plano")
            boton.setFixedWidth(30)
            boton.setToolTip(tooltip)
            boton.clicked.connect(accion)
            fila.addWidget(boton)

        self.mayusculas = QCheckBox("Aa")
        self.mayusculas.setToolTip("Distinguir mayúsculas")
        self.mayusculas.toggled.connect(lambda _: self._buscar(False, mover=False))
        fila.addWidget(self.mayusculas)

        self.regex = QCheckBox(".*")
        self.regex.setToolTip("Expresión regular")
        self.regex.toggled.connect(lambda _: self._buscar(False, mover=False))
        fila.addWidget(self.regex)

        cerrar = QPushButton("✕")
        cerrar.setObjectName("plano")
        cerrar.setFixedWidth(30)
        cerrar.clicked.connect(self.ocultar)
        fila.addWidget(cerrar)
        layout.addLayout(fila)

        # Fila de reemplazo
        self.fila_reemplazo = QWidget()
        fila2 = QHBoxLayout(self.fila_reemplazo)
        fila2.setContentsMargins(0, 0, 0, 0)
        fila2.setSpacing(6)
        self.campo_reemplazo = QLineEdit()
        self.campo_reemplazo.setPlaceholderText("Reemplazar por")
        self.campo_reemplazo.returnPressed.connect(lambda: self._reemplazar(False))
        fila2.addWidget(self.campo_reemplazo, 1)

        boton_uno = QPushButton("Reemplazar")
        boton_uno.clicked.connect(lambda: self._reemplazar(False))
        fila2.addWidget(boton_uno)

        boton_todo = QPushButton("Todo")
        boton_todo.clicked.connect(lambda: self._reemplazar(True))
        fila2.addWidget(boton_todo)
        layout.addWidget(self.fila_reemplazo)

        self.hide()

    def mostrar(self, texto: str = "", *, con_reemplazo: bool = False) -> None:
        self.fila_reemplazo.setVisible(con_reemplazo)
        self.show()
        if texto:
            self.campo.setText(texto)
        self.campo.setFocus()
        self.campo.selectAll()

    def ocultar(self) -> None:
        self.hide()
        self.cerrada.emit()

    def set_resultado(self, actual: int, total: int) -> None:
        if not self.campo.text():
            self.resultado.setText("")
        elif total == 0:
            self.resultado.setText("sin resultados")
        else:
            self.resultado.setText(f"{actual} de {total}")

    def _buscar(self, atras: bool, *, mover: bool = True) -> None:
        self.buscar.emit(
            self.campo.text(), atras, self.mayusculas.isChecked(), self.regex.isChecked()
        )

    def _reemplazar(self, todo: bool) -> None:
        self.reemplazar.emit(self.campo.text(), self.campo_reemplazo.text(), todo)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.ocultar()
            return
        super().keyPressEvent(event)
