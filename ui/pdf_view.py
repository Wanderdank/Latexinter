"""
pdf_view.py - Visor de PDF con zoom, búsqueda y SyncTeX.

Las páginas se dibujan solo cuando entran en pantalla: un documento de cien
páginas no cabría en memoria si se rasterizaran todas de golpe.

Dos detalles que marcan la diferencia al escribir:
  · al recompilar se conserva la posición del scroll, así que el documento no
    salta al principio cada vez;
  · un doble clic en el PDF pregunta a SyncTeX qué línea del .tex generó ese
    punto y lo comunica, para que el editor salte allí.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

NIVELES_ZOOM = [0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]


class _PageLabel(QLabel):
    """Una página del PDF. Se dibuja solo cuando hace falta."""

    clicked = pyqtSignal(int, float, float)     # página (1..n), x, y en puntos

    def __init__(self, numero: int, ancho_pt: float, alto_pt: float):
        super().__init__()
        self.numero = numero
        self.ancho_pt = ancho_pt
        self.alto_pt = alto_pt
        self.zoom = 1.0
        self.dibujada = False
        self.marcas: list[QRectF] = []          # en puntos del PDF
        self.destacado: Optional[QRectF] = None

        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(f"background: white; border: 1px solid {theme.BORDE};")

    def aplicar_zoom(self, zoom: float) -> None:
        self.zoom = zoom
        self.setFixedSize(round(self.ancho_pt * zoom), round(self.alto_pt * zoom))
        self.limpiar()

    def limpiar(self) -> None:
        if self.dibujada:
            self.setPixmap(QPixmap())
            self.dibujada = False

    def mouseDoubleClickEvent(self, event) -> None:
        self.clicked.emit(
            self.numero,
            event.pos().x() / self.zoom,
            event.pos().y() / self.zoom,
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not (self.marcas or self.destacado):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.marcas:
            color = QColor(theme.CIAN)
            color.setAlpha(70)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            for rect in self.marcas:
                painter.drawRect(self._a_pixeles(rect))

        if self.destacado is not None:
            relleno = QColor(theme.COLOR_SYNCTEX)
            relleno.setAlpha(60)
            painter.setBrush(relleno)
            painter.setPen(QPen(QColor(theme.COLOR_SYNCTEX), 2))
            painter.drawRect(self._a_pixeles(self.destacado))

    def _a_pixeles(self, rect: QRectF) -> QRectF:
        return QRectF(
            rect.x() * self.zoom, rect.y() * self.zoom,
            rect.width() * self.zoom, rect.height() * self.zoom,
        )


class PdfView(QWidget):
    """Panel completo: barra de herramientas más las páginas."""

    syncRequested = pyqtSignal(int, float, float)   # página, x, y (puntos)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: Optional[Path] = None
        self._doc = None
        self._paginas: list[_PageLabel] = []
        self._zoom = 1.0
        self._ajustar_ancho = True

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(6)
        raiz.addWidget(self._build_toolbar())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.contenedor = QWidget()
        self.contenedor.setStyleSheet("background: #0b0c1a;")
        self.columna = QVBoxLayout(self.contenedor)
        self.columna.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.columna.setSpacing(14)
        self.columna.setContentsMargins(16, 16, 16, 16)
        self.scroll.setWidget(self.contenedor)
        raiz.addWidget(self.scroll, 1)

        self.vacio = QLabel("Compila el documento para ver el PDF aquí.")
        self.vacio.setObjectName("pista")
        self.vacio.setAlignment(Qt.AlignCenter)
        self.columna.addWidget(self.vacio)

        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(40)
        self._temporizador.timeout.connect(self._render_visible)
        self.scroll.verticalScrollBar().valueChanged.connect(
            lambda _: self._temporizador.start()
        )

        self._apagar_marca = QTimer(self)
        self._apagar_marca.setSingleShot(True)
        self._apagar_marca.setInterval(2500)
        self._apagar_marca.timeout.connect(self._quitar_destacado)

    # ════════════════════════════════════════════════════════
    # Barra de herramientas
    # ════════════════════════════════════════════════════════

    def _build_toolbar(self) -> QWidget:
        barra = QFrame()
        barra.setObjectName("barra")
        fila = QHBoxLayout(barra)
        fila.setContentsMargins(8, 5, 8, 5)
        fila.setSpacing(6)

        def boton(texto: str, tooltip: str, accion) -> QPushButton:
            b = QPushButton(texto)
            b.setObjectName("plano")
            b.setToolTip(tooltip)
            b.setFixedWidth(30)
            b.clicked.connect(accion)
            return b

        fila.addWidget(boton("−", "Alejar", lambda: self.zoom_step(-1)))
        self.selector_zoom = QComboBox()
        self.selector_zoom.setEditable(False)
        self.selector_zoom.addItem("Ajustar al ancho", "ancho")
        self.selector_zoom.addItem("Página completa", "pagina")
        for nivel in NIVELES_ZOOM:
            self.selector_zoom.addItem(f"{nivel * 100:.0f} %", nivel)
        self.selector_zoom.setFixedWidth(150)
        self.selector_zoom.currentIndexChanged.connect(self._zoom_elegido)
        fila.addWidget(self.selector_zoom)
        fila.addWidget(boton("+", "Acercar", lambda: self.zoom_step(1)))

        fila.addSpacing(10)
        fila.addWidget(boton("▲", "Página anterior", lambda: self.step_page(-1)))
        self.etiqueta_pagina = QLabel("—")
        self.etiqueta_pagina.setObjectName("pista")
        self.etiqueta_pagina.setMinimumWidth(70)
        self.etiqueta_pagina.setAlignment(Qt.AlignCenter)
        fila.addWidget(self.etiqueta_pagina)
        fila.addWidget(boton("▼", "Página siguiente", lambda: self.step_page(1)))

        fila.addStretch(1)

        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar en el PDF…")
        self.buscador.setFixedWidth(200)
        self.buscador.returnPressed.connect(self._buscar)
        self.buscador.textChanged.connect(
            lambda t: self._limpiar_marcas() if not t else None
        )
        fila.addWidget(self.buscador)

        return barra

    # ════════════════════════════════════════════════════════
    # Carga
    # ════════════════════════════════════════════════════════

    def load(self, pdf_path: Path, *, conservar_posicion: bool = True) -> bool:
        try:
            import fitz
        except ImportError:
            self._mostrar_mensaje("PyMuPDF no está instalado.")
            return False

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            self._mostrar_mensaje(f"No existe {pdf_path.name}.")
            return False

        relativo = self._posicion_relativa() if conservar_posicion else 0.0

        self._cerrar()
        try:
            # Se lee entero a memoria: las páginas se dibujan más tarde, y para
            # entonces pdflatex puede estar reescribiendo el archivo.
            self._doc = fitz.open(stream=pdf_path.read_bytes(), filetype="pdf")
        except Exception as exc:
            self._mostrar_mensaje(f"No se pudo abrir el PDF: {exc}")
            return False

        self.path = pdf_path
        self._limpiar_columna()

        for numero in range(self._doc.page_count):
            rect = self._doc[numero].rect
            etiqueta = _PageLabel(numero + 1, rect.width, rect.height)
            etiqueta.clicked.connect(self.syncRequested.emit)
            self._paginas.append(etiqueta)
            self.columna.addWidget(etiqueta, alignment=Qt.AlignHCenter)

        self._aplicar_zoom()
        # El dibujado espera a que Qt haya colocado las páginas: antes de eso
        # todas estarían en la posición cero y parecerían visibles.
        self._restaurar_posicion(relativo)
        return True

    def clear(self, texto: str = "") -> None:
        """Quita el documento y deja un mensaje en su lugar."""
        self.path = None
        self._mostrar_mensaje(texto)

    def reload(self) -> bool:
        return self.load(self.path, conservar_posicion=True) if self.path else False

    def _cerrar(self) -> None:
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None

    def _limpiar_columna(self) -> None:
        while self.columna.count():
            item = self.columna.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._paginas = []

    def _mostrar_mensaje(self, texto: str) -> None:
        self._cerrar()
        self._limpiar_columna()
        etiqueta = QLabel(texto)
        etiqueta.setObjectName("pista")
        etiqueta.setAlignment(Qt.AlignCenter)
        etiqueta.setWordWrap(True)
        self.columna.addWidget(etiqueta)
        self.etiqueta_pagina.setText("—")

    # ════════════════════════════════════════════════════════
    # Zoom
    # ════════════════════════════════════════════════════════

    def _zoom_elegido(self) -> None:
        dato = self.selector_zoom.currentData()
        if dato == "ancho":
            self._ajustar_ancho = "ancho"
        elif dato == "pagina":
            self._ajustar_ancho = "pagina"
        else:
            self._ajustar_ancho = False
            self._zoom = float(dato)
        self._aplicar_zoom()
        self._render_visible()

    def zoom_step(self, direccion: int) -> None:
        actual = self._zoom
        niveles = NIVELES_ZOOM
        if direccion > 0:
            siguiente = next((n for n in niveles if n > actual + 0.01), niveles[-1])
        else:
            siguiente = next(
                (n for n in reversed(niveles) if n < actual - 0.01), niveles[0]
            )
        self._ajustar_ancho = False
        self._zoom = siguiente
        indice = self.selector_zoom.findData(siguiente)
        self.selector_zoom.blockSignals(True)
        self.selector_zoom.setCurrentIndex(indice if indice >= 0 else 0)
        self.selector_zoom.blockSignals(False)
        self._aplicar_zoom()
        self._render_visible()

    def _aplicar_zoom(self) -> None:
        if not self._paginas:
            return
        if self._ajustar_ancho:
            disponible = max(200, self.scroll.viewport().width() - 48)
            primera = self._paginas[0]
            if self._ajustar_ancho == "pagina":
                alto = max(200, self.scroll.viewport().height() - 48)
                self._zoom = min(disponible / primera.ancho_pt, alto / primera.alto_pt)
            else:
                self._zoom = disponible / primera.ancho_pt
        for pagina in self._paginas:
            pagina.aplicar_zoom(self._zoom)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._ajustar_ancho and self._paginas:
            self._aplicar_zoom()
            self._temporizador.start()

    # ════════════════════════════════════════════════════════
    # Dibujado perezoso
    # ════════════════════════════════════════════════════════

    def _render_visible(self) -> None:
        if not self._paginas or self._doc is None:
            return
        try:
            import fitz
        except ImportError:
            return

        barra = self.scroll.verticalScrollBar()
        arriba = barra.value()
        alto = self.scroll.viewport().height()
        margen = alto                     # una pantalla de adelanto
        dibujadas = 0

        for pagina in self._paginas:
            cima = pagina.pos().y()
            base = cima + pagina.height()
            visible = base >= arriba - margen and cima <= arriba + alto + margen

            if visible and not pagina.dibujada and dibujadas < 8:
                dibujadas += 1
                try:
                    page = self._doc[pagina.numero - 1]
                    matriz = fitz.Matrix(self._zoom, self._zoom)
                    pix = page.get_pixmap(matrix=matriz, alpha=False)
                except Exception:
                    continue                  # página dañada: se deja en blanco
                imagen = QImage(
                    pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888
                ).copy()
                pagina.setPixmap(QPixmap.fromImage(imagen))
                pagina.dibujada = True
            elif not visible and pagina.dibujada:
                pagina.limpiar()

        self._actualizar_etiqueta_pagina()

    # ════════════════════════════════════════════════════════
    # Navegación
    # ════════════════════════════════════════════════════════

    def _posicion_relativa(self) -> float:
        barra = self.scroll.verticalScrollBar()
        return barra.value() / barra.maximum() if barra.maximum() else 0.0

    def _restaurar_posicion(self, relativo: float) -> None:
        def aplicar() -> None:
            barra = self.scroll.verticalScrollBar()
            barra.setValue(round(relativo * barra.maximum()))
            self._render_visible()

        QTimer.singleShot(0, aplicar)

    def pagina_actual(self) -> int:
        if not self._paginas:
            return 0
        centro = self.scroll.verticalScrollBar().value() + self.scroll.viewport().height() / 3
        for pagina in self._paginas:
            if pagina.pos().y() + pagina.height() >= centro:
                return pagina.numero
        return self._paginas[-1].numero

    def _actualizar_etiqueta_pagina(self) -> None:
        if not self._paginas:
            self.etiqueta_pagina.setText("—")
            return
        self.etiqueta_pagina.setText(
            f"{self.pagina_actual()} / {len(self._paginas)}"
        )

    def step_page(self, direccion: int) -> None:
        destino = self.pagina_actual() + direccion
        self.goto_page(destino)

    def goto_page(self, numero: int) -> None:
        if not self._paginas:
            return
        numero = max(1, min(numero, len(self._paginas)))

        def desplazar() -> None:
            # Se espera a que Qt haya recolocado las páginas: justo después de
            # un cambio de zoom sus posiciones todavía son las de antes.
            pagina = self._paginas[numero - 1]
            self.scroll.verticalScrollBar().setValue(max(0, pagina.pos().y() - 16))
            self._render_visible()

        QTimer.singleShot(0, desplazar)

    # ════════════════════════════════════════════════════════
    # SyncTeX y búsqueda
    # ════════════════════════════════════════════════════════

    def highlight(self, page: int, x: float, y: float, width: float, height: float) -> None:
        """Marca un rectángulo del PDF y lo trae a la vista."""
        if not self._paginas or not 1 <= page <= len(self._paginas):
            return
        self._quitar_destacado()
        pagina = self._paginas[page - 1]
        pagina.destacado = QRectF(x, y, max(width, 8.0), max(height, 10.0))
        pagina.update()

        objetivo = pagina.pos().y() + round(y * self._zoom) - self.scroll.viewport().height() // 3
        self.scroll.verticalScrollBar().setValue(max(0, objetivo))
        self._render_visible()
        self._apagar_marca.start()

    def _quitar_destacado(self) -> None:
        for pagina in self._paginas:
            if pagina.destacado is not None:
                pagina.destacado = None
                pagina.update()

    def _buscar(self) -> None:
        texto = self.buscador.text().strip()
        if not texto or self._doc is None:
            self._limpiar_marcas()
            return

        self._limpiar_marcas()
        primera: Optional[int] = None
        total = 0
        for pagina in self._paginas:
            try:
                encontrados = self._doc[pagina.numero - 1].search_for(texto)
            except Exception:
                encontrados = []
            if encontrados:
                pagina.marcas = [
                    QRectF(r.x0, r.y0, r.width, r.height) for r in encontrados
                ]
                pagina.update()
                total += len(encontrados)
                if primera is None:
                    primera = pagina.numero
        if primera is not None:
            self.goto_page(primera)
        self.buscador.setToolTip(f"{total} resultados" if total else "Sin resultados")

    def _limpiar_marcas(self) -> None:
        for pagina in self._paginas:
            if pagina.marcas:
                pagina.marcas = []
                pagina.update()

    def closeEvent(self, event) -> None:
        self._cerrar()
        super().closeEvent(event)
