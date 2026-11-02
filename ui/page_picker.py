"""
page_picker.py - Elegir qué páginas de un PDF convertir, viéndolas.

Las miniaturas se pintan de una en una con un temporizador: un PDF de cientos
de páginas abre el diálogo al instante y se va rellenando.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QIcon, QImage, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from converters.pdf_to_latex import format_pages, parse_pages

_ANCHO = 132
_ALTO = 187         # lo que mide un A4 a ese ancho


class PagePickerDialog(QDialog):
    def __init__(self, pdf: Path, seleccion: Optional[str] = None, parent=None):
        super().__init__(parent)
        import fitz

        self.setWindowTitle(f"Páginas de {Path(pdf).name}")
        self.resize(780, 620)
        self._doc = fitz.open(str(pdf))

        self.lista = QListWidget()
        self.lista.setObjectName("miniaturas")
        self.lista.setViewMode(QListView.IconMode)
        self.lista.setResizeMode(QListView.Adjust)
        self.lista.setMovement(QListView.Static)
        self.lista.setIconSize(QSize(_ANCHO, _ALTO))
        self.lista.setGridSize(QSize(_ANCHO + 24, _ALTO + 40))
        self.lista.setUniformItemSizes(True)
        self.lista.setSelectionMode(QAbstractItemView.MultiSelection)

        try:
            elegidas = parse_pages(seleccion, self._doc.page_count) if seleccion else None
        except Exception:
            elegidas = None
        for numero in range(self._doc.page_count):
            item = QListWidgetItem(str(numero + 1))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setSizeHint(QSize(_ANCHO + 16, _ALTO + 32))
            self.lista.addItem(item)
            item.setSelected(elegidas is None or numero in elegidas)
        self.lista.scrollToTop()

        self.resumen = QLabel()
        self.resumen.setObjectName("pista")
        todas = QPushButton("Todas")
        todas.clicked.connect(self.lista.selectAll)
        ninguna = QPushButton("Ninguna")
        ninguna.clicked.connect(self.lista.clearSelection)

        self.botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botones.button(QDialogButtonBox.Ok).setText("Usar estas páginas")
        self.botones.button(QDialogButtonBox.Ok).setObjectName("principal")
        self.botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)

        pie = QHBoxLayout()
        pie.addWidget(todas)
        pie.addWidget(ninguna)
        pie.addSpacing(8)
        pie.addWidget(self.resumen)
        pie.addStretch(1)
        pie.addWidget(self.botones)

        columna = QVBoxLayout(self)
        columna.addWidget(self.lista, 1)
        columna.addLayout(pie)
        self.lista.itemSelectionChanged.connect(self._actualizar)
        self._actualizar()

        self._siguiente = 0
        self._pintor = QTimer(self)
        self._pintor.setInterval(0)
        self._pintor.timeout.connect(self._pintar_una)
        self._pintor.start()

    def _pintar_una(self) -> None:
        import fitz

        if self._siguiente >= self._doc.page_count:
            self._pintor.stop()
            return
        pagina = self._doc[self._siguiente]
        escala = 2 * _ANCHO / max(pagina.rect.width, 1)
        imagen = pagina.get_pixmap(matrix=fitz.Matrix(escala, escala), alpha=False)
        qimagen = QImage(imagen.samples, imagen.width, imagen.height, imagen.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimagen.copy())
        pixmap.setDevicePixelRatio(2.0)
        icono = QIcon(pixmap)
        # Sin esto, Qt tiñe de azul la miniatura elegida y no se ve la página.
        icono.addPixmap(pixmap, QIcon.Selected)
        self.lista.item(self._siguiente).setIcon(icono)
        self._siguiente += 1

    def _indices(self) -> list[int]:
        return sorted(self.lista.row(item) for item in self.lista.selectedItems())

    def _actualizar(self) -> None:
        total = self.lista.count()
        elegidas = len(self._indices())
        self.resumen.setText(f"{elegidas} de {total} páginas")
        self.botones.button(QDialogButtonBox.Ok).setEnabled(elegidas > 0)

    def selection(self) -> str:
        """El rango para el campo de páginas; vacío si están todas."""
        indices = self._indices()
        return "" if len(indices) == self.lista.count() else format_pages(indices)

    def done(self, resultado: int) -> None:
        self._pintor.stop()
        self._doc.close()
        super().done(resultado)
