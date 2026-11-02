"""
widgets.py - Controles pequeños que comparten varias pantallas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

_NOMBRES_DE_FORMATO = {".pdf": "PDF", ".docx": "DOCX", ".doc": "DOC", ".tex": "TEX"}


class Segmented(QWidget):
    """Varias opciones excluyentes, a la vista: mejor que un desplegable si son pocas."""

    changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._valores: dict[QPushButton, object] = {}
        self._fila = QHBoxLayout(self)
        self._fila.setContentsMargins(0, 0, 0, 0)
        self._fila.setSpacing(0)
        self._fila.addStretch(1)
        self._grupo.buttonClicked.connect(lambda boton: self.changed.emit(self._valores[boton]))

    def set_items(self, elementos: Sequence[tuple[object, str]], actual: object = None) -> None:
        """Pone las opciones (valor, texto) y marca `actual`, o la primera."""
        for boton in list(self._valores):
            self._grupo.removeButton(boton)
            self._fila.removeWidget(boton)
            boton.deleteLater()
        self._valores.clear()

        total = len(elementos)
        for indice, (valor, texto) in enumerate(elementos):
            boton = QPushButton(texto)
            boton.setObjectName("segmento")
            boton.setCheckable(True)
            boton.setCursor(Qt.PointingHandCursor)
            posicion = (
                "unico" if total == 1 else
                "primero" if indice == 0 else
                "ultimo" if indice == total - 1 else "medio"
            )
            boton.setProperty("posicion", posicion)
            self._grupo.addButton(boton)
            self._valores[boton] = valor
            self._fila.insertWidget(indice, boton)

        valores = [valor for valor, _ in elementos]
        elegido = actual if actual in valores else (valores[0] if valores else None)
        self.set_value(elegido)

    def set_value(self, valor: object) -> None:
        for boton, propio in self._valores.items():
            boton.setChecked(propio == valor)

    def value(self) -> object:
        boton = self._grupo.checkedButton()
        return self._valores.get(boton) if boton else None


class FormatBadge(QLabel):
    """La etiqueta «PDF», «DOCX» o «TEX»: dice el formato sin necesidad de iconos."""

    def __init__(self, path: Optional[Path | str] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("formato")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(36, 18)
        if path is not None:
            self.set_format(Path(path).suffix)

    def set_format(self, extension: str) -> None:
        extension = extension.lower()
        self.setText(_NOMBRES_DE_FORMATO.get(extension, extension.lstrip(".").upper()))
        self.setProperty("formato", extension.lstrip("."))
        self.style().unpolish(self)
        self.style().polish(self)


class ElidedLabel(QLabel):
    """Etiqueta de una línea que recorta con «…» lo que no le cabe."""

    def __init__(self, text: str = "", parent=None, modo=Qt.ElideMiddle):
        super().__init__(parent)
        self._completo = text
        self._modo = modo
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def setText(self, text: str) -> None:
        self._completo = text
        self.setToolTip(text)
        self.update()

    def text(self) -> str:
        return self._completo

    def sizeHint(self) -> QSize:
        return QSize(40, self.fontMetrics().height())

    def paintEvent(self, _event) -> None:
        pincel = QPainter(self)
        pincel.setPen(self.palette().windowText().color())
        pincel.drawText(
            self.rect(), int(Qt.AlignVCenter | Qt.AlignLeft),
            self.fontMetrics().elidedText(self._completo, self._modo, self.width()),
        )


def separador(vertical: bool = False) -> QFrame:
    linea = QFrame()
    linea.setObjectName("separador")
    if vertical:
        linea.setFixedWidth(1)
    else:
        linea.setFixedHeight(1)
    return linea


class BotonIcono(QPushButton):
    """Botón plano con solo un icono, que se vuelve a teñir al cambiar de tema."""

    def __init__(self, nombre: str, tooltip: str, accion=None, lado: int = 26):
        super().__init__()
        self.nombre = nombre
        self.setObjectName("plano")
        self.setToolTip(tooltip)
        self.setFixedSize(lado, lado)
        self.setIconSize(QSize(min(16, lado - 8), min(16, lado - 8)))
        self.setCursor(Qt.PointingHandCursor)
        if accion is not None:
            self.clicked.connect(accion)
        self._tenir()
        # Un método del propio botón: Qt deshace la conexión cuando se destruye.
        theme.avisador.cambiado.connect(self._tenir)

    def _tenir(self) -> None:
        self.setIcon(icons.icono(self.nombre))


def boton_icono(nombre: str, tooltip: str, accion=None, lado: int = 26) -> QPushButton:
    return BotonIcono(nombre, tooltip, accion, lado)


class Disclosure(QWidget):
    """Una sección plegable: «Más opciones»."""

    def __init__(self, titulo: str, contenido: QWidget, parent=None):
        super().__init__(parent)
        self.contenido = contenido
        self.boton = QPushButton(titulo)
        self.boton.setObjectName("desplegar")
        self.boton.setCheckable(True)
        self.boton.setCursor(Qt.PointingHandCursor)
        self.boton.setIconSize(QSize(12, 12))
        self.boton.toggled.connect(self._alternar)
        theme.avisador.cambiado.connect(self._tenir)

        columna = QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(6)
        columna.addWidget(self.boton)
        columna.addWidget(contenido)
        self._alternar(False)

    def _tenir(self) -> None:
        nombre = "chevron_abajo" if self.boton.isChecked() else "chevron_derecha"
        self.boton.setIcon(icons.icono(nombre))

    def _alternar(self, abierta: bool) -> None:
        self.contenido.setVisible(abierta)
        self._tenir()
