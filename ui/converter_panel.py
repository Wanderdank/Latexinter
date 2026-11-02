"""
converter_panel.py - El conversor entre PDF, LaTeX y Word.

Es la pantalla «Conversor» de la ventana principal. A la izquierda, la cola de
documentos y qué hacer con ellos; a la derecha, el resultado junto al original
para revisarlo. Cada conversión corre en un hilo aparte, de una en una.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QSettings, QThread, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from converters import (
    CONVERSIONS,
    SUPPORTED_EXTENSIONS,
    Cancelled,
    CancelToken,
    ConversionError,
    ConversionResult,
    cancellable,
    common_targets,
    conversion_to,
    convert,
    human_size,
    office,
    open_in_explorer,
    reveal_in_explorer,
)

from . import icons, theme
from .latex_syntax import LatexHighlighter
from .pdf_view import PdfView
from .widgets import Disclosure, ElidedLabel, FormatBadge, Segmented, boton_icono, separador

FILE_FILTER = (
    "Documentos compatibles (*.pdf *.tex *.docx);;"
    "PDF (*.pdf);;LaTeX (*.tex);;Word (*.docx);;Todos los archivos (*)"
)
NOMBRES_DESTINO = {".docx": "Word", ".tex": "LaTeX", ".pdf": "PDF"}

EN_COLA = "en_cola"
CONVIRTIENDO = "convirtiendo"
LISTO = "listo"
FALLO = "fallo"
CANCELADO = "cancelado"

_PAGINA = re.compile(r"^Página (\d+) de (\d+)$")


@dataclass(eq=False)
class Trabajo:
    """Un documento de la cola y lo que le ha pasado."""

    fuente: Path
    estado: str = EN_COLA
    destino: Optional[str] = None
    resultado: Optional[ConversionResult] = None
    error: str = ""
    registro: list[str] = field(default_factory=list)
    vista: Optional[Path] = None          # el PDF con el que se enseña el resultado
    fallo_vista: str = ""
    fila: Optional["FilaDeCola"] = None


# ════════════════════════════════════════════════════════════
# Hilos
# ════════════════════════════════════════════════════════════

class ConversionWorker(QThread):
    message = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, key: str, source: Path, output_dir: Optional[Path], options: dict):
        super().__init__()
        self.key = key
        self.source = source
        self.output_dir = output_dir
        self.options = options
        self.cancelacion = CancelToken()

    def run(self) -> None:
        try:
            with cancellable(self.cancelacion):
                resultado = convert(
                    self.key, self.source,
                    output_dir=self.output_dir,
                    logger=self.message.emit,
                    **self.options,
                )
        except Cancelled:
            self.cancelled.emit()
        except ConversionError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit(
                "Error inesperado durante la conversión:\n\n" + traceback.format_exc()
            )
        else:
            self.succeeded.emit(resultado)


class PreviewWorker(QThread):
    """
    Consigue un PDF con el que enseñar el resultado. Un .tex se compila, y se
    conservan el .synctex y el .aux: si luego se abre en el editor, el salto
    entre código y PDF funciona sin volver a compilar. Un .docx se exporta con
    Word o LibreOffice a una carpeta temporal.
    """

    message = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: Path, carpeta_temporal: Path):
        super().__init__()
        self.path = Path(path)
        self.carpeta_temporal = carpeta_temporal
        self.cancelacion = CancelToken()

    def run(self) -> None:
        try:
            with cancellable(self.cancelacion):
                self.succeeded.emit(self._generar())
        except Cancelled:
            pass
        except ConversionError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Error inesperado en la vista previa:\n\n" + traceback.format_exc())

    def _generar(self) -> Path:
        if self.path.suffix.lower() == ".docx":
            destino = self.carpeta_temporal / (self.path.stem + "-vista.pdf")
            office.export_pdf(self.path, destino)
            return destino
        texto = self.path.read_text(encoding="utf-8", errors="replace")
        # Lo que exige fontspec no compila con pdflatex.
        motor = "xelatex" if "{fontspec}" in texto else "pdflatex"
        return convert(
            "tex2pdf", self.path,
            logger=self.message.emit,
            engine=motor, clean_aux=False, synctex=True,
        ).output


# ════════════════════════════════════════════════════════════
# La cola de documentos
# ════════════════════════════════════════════════════════════

class FilaDeCola(QFrame):
    elegida = pyqtSignal(object)
    quitada = pyqtSignal(object)

    _DIBUJO = {
        EN_COLA: None,
        CONVIRTIENDO: "reloj",
        LISTO: "correcto",
        FALLO: "error",
        CANCELADO: "menos",
    }

    def __init__(self, trabajo: Trabajo):
        super().__init__()
        self.trabajo = trabajo
        trabajo.fila = self
        self.setObjectName("fila")
        self.setCursor(Qt.PointingHandCursor)

        fila = QHBoxLayout(self)
        fila.setContentsMargins(6, 4, 2, 4)
        fila.setSpacing(8)
        fila.addWidget(FormatBadge(trabajo.fuente))

        textos = QVBoxLayout()
        textos.setSpacing(0)
        self.nombre = ElidedLabel(trabajo.fuente.name)
        self.detalle = QLabel(self._detalle_inicial())
        self.detalle.setObjectName("tenue")
        textos.addWidget(self.nombre)
        textos.addWidget(self.detalle)
        fila.addLayout(textos, 1)

        self.indicador = QLabel()
        self.indicador.setFixedSize(16, 16)
        fila.addWidget(self.indicador)
        self.boton_quitar = boton_icono("cerrar", "Quitar de la lista", lambda: self.quitada.emit(self.trabajo), 22)
        fila.addWidget(self.boton_quitar)
        self.actualizar()
        theme.avisador.cambiado.connect(self.actualizar)

    def _detalle_inicial(self) -> str:
        return human_size(self.trabajo.fuente) if self.trabajo.fuente.exists() else ""

    def mousePressEvent(self, event) -> None:
        self.elegida.emit(self.trabajo)
        super().mousePressEvent(event)

    def set_elegida(self, elegida: bool) -> None:
        self.setProperty("elegida", "true" if elegida else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def actualizar(self) -> None:
        estado = self.trabajo.estado
        dibujo = self._DIBUJO.get(estado)
        color = {LISTO: theme.VERDE, FALLO: theme.ROJO}.get(estado, theme.TEXTO_SUAVE)
        self.indicador.setPixmap(icons.icono(dibujo, color).pixmap(16, 16) if dibujo else icons.vacio())
        if estado == LISTO and self.trabajo.resultado is not None:
            salida = self.trabajo.resultado.output
            self.detalle.setText(f"{NOMBRES_DESTINO.get(salida.suffix.lower(), salida.suffix)} · {human_size(salida)}")
        elif estado == FALLO:
            self.detalle.setText("No se pudo convertir")
        elif estado == CANCELADO:
            self.detalle.setText("Cancelado")
        elif estado == CONVIRTIENDO:
            self.detalle.setText("Convirtiendo…")
        else:
            self.detalle.setText(self._detalle_inicial())


class ListaDeDocumentos(QFrame):
    """La cola; admite soltar archivos encima."""

    filesDropped = pyqtSignal(list)
    browseRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("lista")
        self.setAcceptDrops(True)
        self.setMinimumHeight(132)

        self.vacio = QWidget()
        centro = QVBoxLayout(self.vacio)
        centro.setSpacing(8)
        centro.addStretch(1)
        texto = QLabel("Arrastra aquí tus documentos")
        texto.setAlignment(Qt.AlignCenter)
        pista = QLabel("PDF, .tex o .docx, uno o varios")
        pista.setObjectName("tenue")
        pista.setAlignment(Qt.AlignCenter)
        boton = QPushButton("Elegir archivos…")
        boton.clicked.connect(self.browseRequested.emit)
        fila_boton = QHBoxLayout()
        fila_boton.addStretch(1)
        fila_boton.addWidget(boton)
        fila_boton.addStretch(1)
        centro.addWidget(texto)
        centro.addWidget(pista)
        centro.addLayout(fila_boton)
        centro.addStretch(1)

        self.interior = QWidget()
        self.filas = QVBoxLayout(self.interior)
        self.filas.setContentsMargins(4, 4, 4, 4)
        self.filas.setSpacing(1)
        self.filas.addStretch(1)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameStyle(0)
        desplazable.setWidget(self.interior)

        self.paginas = QStackedWidget()
        self.paginas.addWidget(self.vacio)
        self.paginas.addWidget(desplazable)
        columna = QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.addWidget(self.paginas)

    def add_row(self, fila: FilaDeCola) -> None:
        self.filas.insertWidget(self.filas.count() - 1, fila)
        self.paginas.setCurrentIndex(1)

    def remove_row(self, fila: FilaDeCola) -> None:
        self.filas.removeWidget(fila)
        fila.deleteLater()
        self.paginas.setCurrentIndex(1 if self.filas.count() > 1 else 0)

    # ── Soltar archivos ──
    def _admitidos(self, event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        rutas = (url.toLocalFile() for url in event.mimeData().urls())
        return [r for r in rutas if r and Path(r).suffix.lower() in SUPPORTED_EXTENSIONS]

    def _marcar(self, activa: bool) -> None:
        self.setProperty("activa", "true" if activa else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:
        if self._admitidos(event):
            event.acceptProposedAction()
            self._marcar(True)

    def dragLeaveEvent(self, _event) -> None:
        self._marcar(False)

    def dropEvent(self, event) -> None:
        rutas = self._admitidos(event)
        self._marcar(False)
        if rutas:
            event.acceptProposedAction()
            self.filesDropped.emit(rutas)


# ════════════════════════════════════════════════════════════
# Panel
# ════════════════════════════════════════════════════════════

class ConverterPanel(QWidget):
    """Pantalla completa del conversor."""

    documentReady = pyqtSignal(object)          # .tex generado, para abrirlo en el editor

    def __init__(self, scratch_dir: Path, parent=None):
        super().__init__(parent)
        self.scratch_dir = Path(scratch_dir)
        self.ajustes = QSettings("Latexinter", "Latexinter")
        self.trabajos: list[Trabajo] = []
        self.pendientes: list[Trabajo] = []
        self.en_curso: Optional[Trabajo] = None
        self.elegido: Optional[Trabajo] = None
        self.worker: Optional[ConversionWorker] = None
        self.preview_worker: Optional[PreviewWorker] = None
        self._previa_de: Optional[Trabajo] = None
        self._cancelando = False
        self._total_lote = 0
        self._prefijo_estado = ""
        self._sincronizando = False
        self._carpeta_vistas = Path(tempfile.mkdtemp(prefix="latexinter-vistas-"))

        cuerpo = QHBoxLayout(self)
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(0)
        cuerpo.addWidget(self._build_left_panel())
        cuerpo.addWidget(separador(vertical=True))
        cuerpo.addWidget(self._build_right_panel(), 1)

        self._refresh_targets()

    # ── Panel izquierdo ─────────────────────────────────────
    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(372)
        raiz = QVBoxLayout(panel)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        contenido = QWidget()
        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(14)

        # Qué convertir
        cabecera = QHBoxLayout()
        self.modo_entrada = Segmented()
        self.modo_entrada.set_items([(0, "Archivos"), (1, "Pegar LaTeX")])
        self.modo_entrada.changed.connect(self._cambio_de_entrada)
        cabecera.addWidget(self.modo_entrada)
        cabecera.addStretch(1)
        self.boton_anadir = boton_icono("mas", "Añadir archivos", self._browse)
        cabecera.addWidget(self.boton_anadir)
        layout.addLayout(cabecera)

        self.lista = ListaDeDocumentos()
        self.lista.filesDropped.connect(self.add_sources)
        self.lista.browseRequested.connect(self._browse)

        pagina_codigo = QWidget()
        codigo = QVBoxLayout(pagina_codigo)
        codigo.setContentsMargins(0, 0, 0, 0)
        codigo.setSpacing(6)
        self.editor = QPlainTextEdit()
        self.editor.setFont(theme.mono_font(10))
        self.editor.setPlaceholderText(
            "\\documentclass{article}\n\\begin{document}\nHola mundo\n\\end{document}"
        )
        LatexHighlighter(self.editor.document())
        codigo.addWidget(self.editor, 1)
        pista = QLabel("Se guarda como .tex en la carpeta de salida antes de convertir.")
        pista.setObjectName("tenue")
        pista.setWordWrap(True)
        codigo.addWidget(pista)

        self.entrada = QStackedWidget()
        self.entrada.addWidget(self.lista)
        self.entrada.addWidget(pagina_codigo)
        self.entrada.setMinimumHeight(132)
        layout.addWidget(self.entrada, 1)

        # A qué
        layout.addWidget(self._section_label("Convertir a"))
        layout.addSpacing(-8)
        self.destino = Segmented()
        self.destino.changed.connect(self._cambio_de_destino)
        layout.addWidget(self.destino)
        self.sin_destino = QLabel("Estos documentos no tienen un formato de destino en común.")
        self.sin_destino.setObjectName("tenue")
        self.sin_destino.setWordWrap(True)
        self.sin_destino.hide()
        layout.addWidget(self.sin_destino)

        layout.addWidget(self._build_options())

        # Dónde
        layout.addWidget(self._section_label("Guardar en"))
        layout.addSpacing(-8)
        salida = QHBoxLayout()
        salida.setSpacing(6)
        self.carpeta_salida = QLineEdit()
        self.carpeta_salida.setPlaceholderText("Junto al archivo original")
        salida.addWidget(self.carpeta_salida, 1)
        salida.addWidget(boton_icono("carpeta", "Elegir la carpeta", self._choose_output_dir, 28))
        layout.addLayout(salida)

        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameStyle(0)
        desplazable.setWidget(contenido)
        raiz.addWidget(desplazable, 1)

        # Siempre a la vista, por larga que sea la lista de opciones.
        raiz.addWidget(separador())
        pie = QVBoxLayout()
        pie.setContentsMargins(16, 10, 16, 12)
        pie.setSpacing(6)
        self.progreso = QProgressBar()
        self.progreso.setTextVisible(False)
        self.progreso.hide()
        pie.addWidget(self.progreso)
        self.estado = ElidedLabel("", modo=Qt.ElideRight)
        self.estado.setObjectName("tenue")
        self.estado.hide()
        pie.addWidget(self.estado)
        self.boton_convertir = QPushButton("Convertir")
        self.boton_convertir.setObjectName("principal")
        self.boton_convertir.clicked.connect(self.start_conversion)
        pie.addWidget(self.boton_convertir)
        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.clicked.connect(self.cancel)
        self.boton_cancelar.hide()
        pie.addWidget(self.boton_cancelar)
        raiz.addLayout(pie)
        return panel

    def _section_label(self, text: str) -> QLabel:
        etiqueta = QLabel(text)
        etiqueta.setObjectName("seccion")
        return etiqueta

    def _build_options(self) -> QWidget:
        contenedor = QWidget()
        columna = QVBoxLayout(contenedor)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(10)

        # Lo importante, a la vista
        principales = QGridLayout()
        principales.setHorizontalSpacing(10)
        principales.setVerticalSpacing(8)
        principales.setColumnStretch(1, 1)

        self.etiqueta_paginas = QLabel("Páginas")
        self.opcion_paginas = QLineEdit()
        self.opcion_paginas.setPlaceholderText("Todas (ej.: 1-5 o 1,3,8-10)")
        self.boton_paginas = QPushButton("Elegir…")
        self.boton_paginas.clicked.connect(self._elegir_paginas)
        fila_paginas = QHBoxLayout()
        fila_paginas.setSpacing(6)
        fila_paginas.addWidget(self.opcion_paginas, 1)
        fila_paginas.addWidget(self.boton_paginas)
        principales.addWidget(self.etiqueta_paginas, 0, 0)
        principales.addLayout(fila_paginas, 0, 1)

        self.etiqueta_formulas = QLabel("Fórmulas")
        self.opcion_formulas = QComboBox()
        self.opcion_formulas.addItem("Rápido: leer la maquetación", "rapido")
        self.opcion_formulas.addItem("Preciso: añadir OCR (mucho más lento)", "ocr")
        self.opcion_formulas.addItem("Dejar como texto", "no")
        self.opcion_formulas.setToolTip(
            "Rápido deduce índices, fracciones y ecuaciones de la posición de cada\n"
            "glifo en el PDF. Preciso además recorta cada fórmula y se la pasa a un\n"
            "modelo, y solo se fía de él si usa los mismos glifos y su LaTeX compila.\n"
            "La primera vez descarga el modelo (120 MB)."
        )
        indice = self.opcion_formulas.findData(self.ajustes.value("conversor/formulas", "rapido", type=str))
        self.opcion_formulas.setCurrentIndex(max(indice, 0))
        self.opcion_formulas.currentIndexChanged.connect(self._cambio_de_formulas)
        principales.addWidget(self.etiqueta_formulas, 1, 0)
        principales.addWidget(self.opcion_formulas, 1, 1)

        self.etiqueta_motor = QLabel("Motor")
        self.opcion_motor = QComboBox()
        self.opcion_motor.addItems(["pdflatex", "xelatex", "lualatex"])
        principales.addWidget(self.etiqueta_motor, 2, 0)
        principales.addWidget(self.opcion_motor, 2, 1)
        columna.addLayout(principales)

        self.opcion_indice = QCheckBox("Añadir un índice")
        columna.addWidget(self.opcion_indice)
        self.opcion_numerar = QCheckBox("Numerar las secciones")
        self.opcion_numerar.setChecked(True)
        columna.addWidget(self.opcion_numerar)

        # El resto, plegado
        mas = QWidget()
        rejilla = QGridLayout(mas)
        rejilla.setContentsMargins(0, 2, 0, 0)
        rejilla.setHorizontalSpacing(10)
        rejilla.setVerticalSpacing(8)
        rejilla.setColumnStretch(1, 1)

        self.etiqueta_motor_ocr = QLabel("Modelo de OCR")
        self.opcion_motor_ocr = QComboBox()
        self._rellenar_motores_ocr()
        self.etiqueta_ecuaciones = QLabel("Ecuaciones")
        self.opcion_ecuaciones = QComboBox()
        self.opcion_ecuaciones.addItem("Automático", None)
        self.opcion_ecuaciones.addItem("Imagen + LaTeX en comentario", "comentario")
        self.opcion_ecuaciones.addItem("LaTeX reconstruido", "latex")
        self.opcion_ecuaciones.addItem("Solo la imagen", "imagen")
        self.opcion_ecuaciones.setToolTip(
            "Qué hacer con las ecuaciones centradas. En automático: con OCR se\n"
            "sustituye la imagen por su LaTeX, y sin OCR se conserva la imagen\n"
            "y la reconstrucción queda en un comentario."
        )
        rejilla.addWidget(self.etiqueta_motor_ocr, 0, 0)
        rejilla.addWidget(self.opcion_motor_ocr, 0, 1)
        rejilla.addWidget(self.etiqueta_ecuaciones, 1, 0)
        rejilla.addWidget(self.opcion_ecuaciones, 1, 1)

        self.opcion_imagenes = QCheckBox("Extraer las imágenes")
        self.opcion_imagenes.setChecked(True)
        self.opcion_dos_columnas = QCheckBox("Documento a dos columnas")
        self.opcion_conservar_tex = QCheckBox("Conservar el .tex intermedio")
        self.opcion_markdown = QCheckBox("Conservar el Markdown intermedio")
        self.opcion_limpiar = QCheckBox("Borrar los archivos auxiliares")
        self.opcion_limpiar.setChecked(True)
        self.opcion_via_latex = QCheckBox("Compilar con LaTeX aunque haya Word instalado")
        self.opcion_vista_previa = QCheckBox("Enseñar el resultado al terminar")
        self.opcion_vista_previa.setChecked(True)
        self.opcion_vista_previa.setToolTip(
            "Compila el .tex, o exporta el .docx si hay Word o LibreOffice,\n"
            "para ver el resultado junto al original."
        )
        sueltos = (
            self.opcion_imagenes, self.opcion_dos_columnas, self.opcion_conservar_tex,
            self.opcion_markdown, self.opcion_limpiar, self.opcion_via_latex,
            self.opcion_vista_previa,
        )
        for indice, control in enumerate(sueltos):
            rejilla.addWidget(control, 2 + indice, 0, 1, 2)

        self.mas_opciones = Disclosure("Más opciones", mas)
        columna.addWidget(self.mas_opciones)

        self.controles = {
            "pages": (self.opcion_paginas, self.etiqueta_paginas, self.boton_paginas),
            "math_reconstruction": (self.opcion_formulas, self.etiqueta_formulas),
            "engine": (self.opcion_motor, self.etiqueta_motor),
            "toc": (self.opcion_indice,),
            "number_sections": (self.opcion_numerar,),
            "display_equations": (self.opcion_ecuaciones, self.etiqueta_ecuaciones),
            "extract_images": (self.opcion_imagenes,),
            "twocolumn": (self.opcion_dos_columnas,),
            "keep_latex": (self.opcion_conservar_tex,),
            "keep_markdown": (self.opcion_markdown,),
            "clean_aux": (self.opcion_limpiar,),
            "via_latex": (self.opcion_via_latex,),
        }
        return contenedor

    # ── OCR de fórmulas ─────────────────────────────────────
    def _rellenar_motores_ocr(self) -> None:
        from converters import mathocr

        self.opcion_motor_ocr.clear()
        instalados = mathocr.installed_backends()
        for backend in instalados:
            self.opcion_motor_ocr.addItem(backend.name, backend.key)
        if not instalados:
            self.opcion_motor_ocr.addItem("ninguno instalado", None)
        self.opcion_motor_ocr.setEnabled(bool(instalados))

    def _cambio_de_formulas(self, _indice: int = 0) -> None:
        modo = self.opcion_formulas.currentData()
        self.ajustes.setValue("conversor/formulas", modo)
        self._comprobar_ocr(modo == "ocr")
        self._refresh_options()

    def _comprobar_ocr(self, activo: bool) -> None:
        """Al pedir OCR sin modelo, se explica qué hay que instalar."""
        if not activo:
            return
        from converters import mathocr

        self._rellenar_motores_ocr()
        if mathocr.any_backend_installed():
            return

        self.opcion_formulas.setCurrentIndex(self.opcion_formulas.findData("rapido"))
        texto = [
            "El OCR de fórmulas necesita un modelo de reconocimiento, y no hay "
            "ninguno disponible en este equipo.",
            "",
            "Sin él, Latexinter recupera índices, fracciones y ecuaciones leyendo "
            "la maquetación del PDF.",
        ]
        for backend in mathocr.BACKENDS:
            texto.extend(["", f"{backend.name} ({backend.size})", f"    {backend.install}"])
        QMessageBox.information(self, "Latexinter", "\n".join(texto))

    # ── Panel derecho ───────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        self.derecha = QStackedWidget()
        self.derecha.addWidget(self._build_intro())
        self.derecha.addWidget(self._build_result_page())
        return self.derecha

    def _build_intro(self) -> QWidget:
        pagina = QWidget()
        centro = QVBoxLayout(pagina)
        centro.addStretch(2)
        titulo = QLabel("Convierte entre PDF, LaTeX y Word")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignCenter)
        centro.addWidget(titulo)
        centro.addSpacing(16)

        rutas = QGridLayout()
        rutas.setHorizontalSpacing(10)
        rutas.setVerticalSpacing(8)
        filas = (
            (".pdf", "a Word o LaTeX, con las fórmulas reconstruidas"),
            (".docx", "a LaTeX o PDF"),
            (".tex", "a PDF o Word, con ecuaciones editables"),
        )
        for numero, (extension, texto) in enumerate(filas):
            rutas.addWidget(FormatBadge(f"x{extension}"), numero, 0)
            descripcion = QLabel(texto)
            descripcion.setObjectName("pista")
            rutas.addWidget(descripcion, numero, 1)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addLayout(rutas)
        fila.addStretch(1)
        centro.addLayout(fila)
        centro.addStretch(3)
        return pagina

    def _build_result_page(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        cabecera = QHBoxLayout()
        cabecera.setSpacing(6)
        textos = QVBoxLayout()
        textos.setSpacing(1)
        self.titulo = ElidedLabel("")
        self.titulo.setObjectName("titulo")
        self.titulo.setMinimumHeight(24)
        self.resumen = ElidedLabel("", modo=Qt.ElideRight)
        self.resumen.setObjectName("tenue")
        self.resumen.setMinimumHeight(18)
        textos.addWidget(self.titulo)
        textos.addWidget(self.resumen)
        cabecera.addLayout(textos, 1)

        self.opcion_a_la_vez = QCheckBox("Desplazar a la vez")
        self.opcion_a_la_vez.setChecked(True)
        cabecera.addWidget(self.opcion_a_la_vez)
        cabecera.addSpacing(8)

        self.boton_editar = QPushButton("Abrir en el editor")
        self.boton_editar.clicked.connect(self._edit_result)
        self.boton_abrir = QPushButton("Abrir")
        self.boton_abrir.setObjectName("principal")
        self.boton_abrir.clicked.connect(self._open_result)
        self.boton_carpeta = QPushButton("Mostrar en la carpeta")
        self.boton_carpeta.clicked.connect(self._reveal_result)
        for boton in (self.boton_editar, self.boton_abrir, self.boton_carpeta):
            cabecera.addWidget(boton)
        layout.addLayout(cabecera)

        self.caja_avisos = QFrame()
        self.caja_avisos.setObjectName("avisos")
        avisos = QVBoxLayout(self.caja_avisos)
        avisos.setContentsMargins(10, 6, 10, 6)
        self.texto_avisos = QLabel()
        self.texto_avisos.setObjectName("subtitulo")
        self.texto_avisos.setWordWrap(True)
        self.texto_avisos.setTextInteractionFlags(Qt.TextSelectableByMouse)
        avisos.addWidget(self.texto_avisos)
        self.caja_avisos.hide()
        layout.addWidget(self.caja_avisos)

        self.pestanas = QTabWidget()
        self.pestanas.setDocumentMode(True)

        # Original y resultado lado a lado: una conversión se revisa comparando.
        comparar = QWidget()
        comparar_layout = QVBoxLayout(comparar)
        comparar_layout.setContentsMargins(0, 0, 0, 0)
        comparar_layout.setSpacing(0)

        self.vista_original = PdfView(compacta=True, titulo="Original")
        self.vista_pdf = PdfView(compacta=True, titulo="Resultado")
        self.vista_comparar = QSplitter(Qt.Horizontal)
        self.vista_comparar.addWidget(self.vista_original)
        self.vista_comparar.addWidget(self.vista_pdf)
        self.vista_comparar.setChildrenCollapsible(False)
        comparar_layout.addWidget(self.vista_comparar, 1)
        self.vista_original.scroll.verticalScrollBar().valueChanged.connect(
            lambda _: self._desplazar_a_la_vez(self.vista_original, self.vista_pdf)
        )
        self.vista_pdf.scroll.verticalScrollBar().valueChanged.connect(
            lambda _: self._desplazar_a_la_vez(self.vista_pdf, self.vista_original)
        )

        self.vista_texto = QPlainTextEdit()
        self.vista_texto.setReadOnly(True)
        self.vista_texto.setFont(theme.mono_font(10))
        LatexHighlighter(self.vista_texto.document())
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setFont(theme.mono_font(9))

        self.pestana_vista = self.pestanas.addTab(comparar, "Vista")
        self.pestana_codigo = self.pestanas.addTab(self.vista_texto, "Código")
        self.pestana_registro = self.pestanas.addTab(self.registro, "Registro")
        self.pestanas.currentChanged.connect(lambda _: self._actualizar_a_la_vez())
        layout.addWidget(self.pestanas, 1)
        return pagina

    def _desplazar_a_la_vez(self, origen: PdfView, destino: PdfView) -> None:
        if self._sincronizando or not self.opcion_a_la_vez.isChecked() or not destino.isVisible():
            return
        barra_origen = origen.scroll.verticalScrollBar()
        barra_destino = destino.scroll.verticalScrollBar()
        if barra_origen.maximum() <= 0:
            return
        self._sincronizando = True
        barra_destino.setValue(round(barra_origen.value() / barra_origen.maximum() * barra_destino.maximum()))
        self._sincronizando = False

    # ── Entrada ─────────────────────────────────────────────
    def _browse(self) -> None:
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Elegir documentos", self.ajustes.value("conversor/carpeta", str(Path.home()), type=str),
            FILE_FILTER,
        )
        if rutas:
            self.ajustes.setValue("conversor/carpeta", str(Path(rutas[0]).parent))
            self.add_sources(rutas)

    def set_source(self, path: str | Path) -> None:
        """Compatibilidad con quien abre un solo documento (la línea de comandos)."""
        self.add_sources([path])

    def add_sources(self, rutas: list) -> None:
        nuevos: list[Trabajo] = []
        vistos = {t.fuente.resolve() for t in self.trabajos}
        for ruta in rutas:
            fuente = Path(ruta)
            if not fuente.exists():
                QMessageBox.warning(self, "Latexinter", f"No existe el archivo:\n{fuente}")
                continue
            if fuente.suffix.lower() not in SUPPORTED_EXTENSIONS:
                QMessageBox.warning(
                    self, "Latexinter",
                    f"No sé qué hacer con un archivo {fuente.suffix}.\n"
                    f"Formatos admitidos: {', '.join(SUPPORTED_EXTENSIONS)}",
                )
                continue
            if fuente.resolve() in vistos:
                continue
            vistos.add(fuente.resolve())
            nuevos.append(Trabajo(fuente))

        for trabajo in nuevos:
            self.trabajos.append(trabajo)
            fila = FilaDeCola(trabajo)
            fila.elegida.connect(self._elegir)
            fila.quitada.connect(self._quitar)
            self.lista.add_row(fila)

        if nuevos:
            self.modo_entrada.set_value(0)
            self.entrada.setCurrentIndex(0)
            self._elegir(nuevos[-1])
        self._refresh_targets()

    def _quitar(self, trabajo: Trabajo) -> None:
        if trabajo is self.en_curso:
            return
        if trabajo in self.pendientes:
            self.pendientes.remove(trabajo)
        self.trabajos.remove(trabajo)
        self.lista.remove_row(trabajo.fila)
        if self.elegido is trabajo:
            self.elegido = None
            self._elegir(self.trabajos[-1] if self.trabajos else None)
        self._refresh_targets()

    def _cambio_de_entrada(self, modo: int) -> None:
        self.entrada.setCurrentIndex(modo)
        self.boton_anadir.setVisible(modo == 0)
        self._refresh_targets()

    def _choose_output_dir(self) -> None:
        inicio = self.carpeta_salida.text() or (
            str(self.trabajos[0].fuente.parent) if self.trabajos else str(Path.home())
        )
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de salida", inicio)
        if carpeta:
            self.carpeta_salida.setText(carpeta)

    def _elegir_paginas(self) -> None:
        from .page_picker import PagePickerDialog

        pdfs = [t.fuente for t in self.trabajos if t.fuente.suffix.lower() == ".pdf"]
        if len(pdfs) != 1:
            return
        dialogo = PagePickerDialog(pdfs[0], self.opcion_paginas.text().strip(), self)
        if dialogo.exec_():
            self.opcion_paginas.setText(dialogo.selection())

    # ── Destinos y opciones ─────────────────────────────────
    def _rutas_de_entrada(self) -> list[Path]:
        """Los documentos a convertir (el código pegado se trata como un .tex)."""
        if self.entrada.currentIndex() == 1:
            return [Path("documento.tex")]
        return [t.fuente for t in self.trabajos]

    def _refresh_targets(self) -> None:
        rutas = self._rutas_de_entrada()
        # Sin documentos todavía se enseña todo lo que se puede hacer.
        objetivos = common_targets(rutas) if rutas else list(NOMBRES_DESTINO)
        preferido = self.destino.value() or self.ajustes.value("conversor/destino", ".docx", type=str)
        self.destino.set_items([(e, NOMBRES_DESTINO[e]) for e in objetivos], preferido)
        self.destino.setVisible(bool(objetivos))
        self.sin_destino.setVisible(not objetivos)
        self._refresh_options()

    def _cambio_de_destino(self, extension: str) -> None:
        self.ajustes.setValue("conversor/destino", extension)
        self._refresh_options()

    def _refresh_options(self) -> None:
        rutas = self._rutas_de_entrada()
        extension = self.destino.value()
        opciones: set[str] = set()
        for ruta in rutas:
            conversion = conversion_to(ruta, extension) if extension else None
            if conversion:
                opciones |= conversion.options

        for nombre, controles in self.controles.items():
            for control in controles:
                control.setVisible(nombre in opciones)

        # El rango de páginas es de un documento concreto: no vale para un lote.
        pdfs = [r for r in rutas if r.suffix.lower() == ".pdf"]
        por_paginas = "pages" in opciones and len(rutas) == 1 and len(pdfs) == 1
        for control in self.controles["pages"]:
            control.setVisible(por_paginas)

        con_ocr = "math_ocr" in opciones and self.opcion_formulas.currentData() == "ocr"
        self.etiqueta_motor_ocr.setVisible(con_ocr)
        self.opcion_motor_ocr.setVisible(con_ocr)

        self.opcion_vista_previa.setVisible(extension in (".tex", ".docx"))
        self.mas_opciones.setVisible(bool(rutas) and bool(extension))

        self.boton_convertir.setEnabled(bool(extension) and bool(rutas) and not self.is_converting())
        if extension and rutas:
            cuantos = len(rutas)
            nombre = NOMBRES_DESTINO[extension]
            self.boton_convertir.setText(
                f"Convertir {cuantos} documentos a {nombre}" if cuantos > 1 else f"Convertir a {nombre}"
            )
        else:
            self.boton_convertir.setText("Convertir")

    def _collect_options(self) -> dict:
        formulas = self.opcion_formulas.currentData()
        return {
            "pages": self.opcion_paginas.text().strip() or None,
            "display_equations": self.opcion_ecuaciones.currentData(),
            "engine": self.opcion_motor.currentText(),
            "extract_images": self.opcion_imagenes.isChecked(),
            "math_reconstruction": formulas != "no",
            "math_ocr": formulas == "ocr",
            "ocr_backend": self.opcion_motor_ocr.currentData(),
            "twocolumn": self.opcion_dos_columnas.isChecked(),
            "keep_markdown": self.opcion_markdown.isChecked(),
            "keep_latex": self.opcion_conservar_tex.isChecked(),
            "clean_aux": self.opcion_limpiar.isChecked(),
            "toc": self.opcion_indice.isChecked(),
            "number_sections": self.opcion_numerar.isChecked(),
            "via_latex": self.opcion_via_latex.isChecked(),
        }

    # ── Conversión ──────────────────────────────────────────
    def _guardar_codigo(self) -> Optional[Path]:
        """Escribe lo pegado en un .tex y lo pone en la cola."""
        codigo = self.editor.toPlainText().strip()
        if not codigo:
            QMessageBox.information(self, "Latexinter", "No hay código LaTeX que convertir.")
            return None

        carpeta = Path(self.carpeta_salida.text()) if self.carpeta_salida.text() else self.scratch_dir
        carpeta.mkdir(parents=True, exist_ok=True)

        destino = carpeta / "documento.tex"
        indice = 1
        while destino.exists() and destino.read_text(encoding="utf-8", errors="replace") != codigo:
            destino = carpeta / f"documento_{indice}.tex"
            indice += 1
        destino.write_text(codigo, encoding="utf-8")
        return destino

    def start_conversion(self) -> None:
        if self.is_converting():
            return
        extension = self.destino.value()
        if not extension:
            return

        if self.entrada.currentIndex() == 1:
            guardado = self._guardar_codigo()
            if guardado is None:
                return
            self.add_sources([guardado])

        # Lo ya convertido a este mismo formato no se repite, salvo que no haya
        # nada más que hacer: entonces volver a pulsar repite todo.
        pendientes = [
            t for t in self.trabajos if not (t.estado == LISTO and t.destino == extension)
        ] or list(self.trabajos)
        if not pendientes:
            return

        self._cancelando = False
        self._parar_vista_previa()
        for trabajo in pendientes:
            trabajo.estado = EN_COLA
            trabajo.destino = extension
            trabajo.resultado = None
            trabajo.error = ""
            trabajo.registro = []
            trabajo.vista = None
            trabajo.fallo_vista = ""
            trabajo.fila.actualizar()

        self.pendientes = pendientes
        self._total_lote = len(pendientes)
        self._set_ocupado(True)
        self._siguiente_trabajo()

    def _siguiente_trabajo(self) -> None:
        if not self.pendientes or self._cancelando:
            for trabajo in self.pendientes:
                trabajo.estado = CANCELADO
                trabajo.fila.actualizar()
            self.pendientes = []
            self._fin_del_lote()
            return

        trabajo = self.pendientes.pop(0)
        self.en_curso = trabajo
        trabajo.estado = CONVIRTIENDO
        trabajo.fila.actualizar()
        self._elegir(trabajo)

        numero = self._total_lote - len(self.pendientes)
        self._prefijo_estado = f"{numero} de {self._total_lote} · " if self._total_lote > 1 else ""
        self.estado.setText(f"{self._prefijo_estado}{trabajo.fuente.name}")
        self.progreso.setRange(0, 0)

        carpeta_texto = self.carpeta_salida.text().strip()
        carpeta = Path(carpeta_texto) if carpeta_texto else None
        conversion = conversion_to(trabajo.fuente, trabajo.destino)
        opciones = self._collect_options()
        if len(self.trabajos) > 1:
            opciones["pages"] = None

        self.worker = ConversionWorker(conversion.key, trabajo.fuente, carpeta, opciones)
        self.worker.message.connect(self._log)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _log(self, mensaje: str) -> None:
        trabajo = self.en_curso or self._previa_de
        if trabajo is not None:
            trabajo.registro.append(mensaje)
            if trabajo is self.elegido:
                self.registro.appendPlainText(mensaje)

        pagina = _PAGINA.match(mensaje)
        if pagina:
            self.progreso.setRange(0, int(pagina.group(2)))
            self.progreso.setValue(int(pagina.group(1)))
        if mensaje and not mensaje.startswith("  ") and self.is_converting():
            self.estado.setText(f"{self._prefijo_estado}{mensaje}")

    def _on_success(self, resultado: ConversionResult) -> None:
        trabajo = self.en_curso
        trabajo.resultado = resultado
        trabajo.estado = LISTO
        for aviso in resultado.warnings:
            trabajo.registro.append("Aviso: " + aviso)
        trabajo.registro.append(f"Generado: {resultado.output}")
        trabajo.fila.actualizar()

    def _on_failure(self, mensaje: str) -> None:
        trabajo = self.en_curso
        trabajo.estado = FALLO
        trabajo.error = mensaje
        trabajo.registro.extend(["", "Error: " + mensaje])
        trabajo.fila.actualizar()

    def _on_cancelled(self) -> None:
        trabajo = self.en_curso
        trabajo.estado = CANCELADO
        trabajo.registro.append("Cancelado.")
        trabajo.fila.actualizar()

    def _on_worker_finished(self) -> None:
        # Lo siguiente enseña el trabajo que toque: el próximo de la cola o,
        # al acabarse, el elegido. La señal llega con el hilo aún terminando.
        self.en_curso = None
        self.worker.wait()
        self.worker = None
        self._siguiente_trabajo()

    def _fin_del_lote(self) -> None:
        self._set_ocupado(False)
        hechos = [t for t in self.trabajos if t.estado == LISTO]
        fallidos = [t for t in self.trabajos if t.estado == FALLO]
        if self._total_lote > 1:
            texto = f"{len(hechos)} de {len(self.trabajos)} convertidos"
            if fallidos:
                texto += f" · {len(fallidos)} con error"
            self.estado.setText(texto)
            self.estado.show()
        if self.elegido is not None:
            self._mostrar(self.elegido)

    def cancel(self) -> None:
        self._cancelando = True
        self.boton_cancelar.setEnabled(False)
        self.boton_cancelar.setText("Cancelando…")
        self.estado.setText("Cancelando…")
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancelacion.cancel()

    def _set_ocupado(self, ocupado: bool) -> None:
        self.boton_convertir.setVisible(not ocupado)
        self.boton_cancelar.setVisible(ocupado)
        self.boton_cancelar.setEnabled(True)
        self.boton_cancelar.setText("Cancelar")
        self.progreso.setVisible(ocupado)
        self.estado.setVisible(ocupado)
        self._refresh_options()

    # ── Resultado ───────────────────────────────────────────
    def _elegir(self, trabajo: Optional[Trabajo]) -> None:
        anterior, self.elegido = self.elegido, trabajo
        if anterior is not None and anterior.fila is not None and anterior in self.trabajos:
            anterior.fila.set_elegida(False)
        if trabajo is None:
            self.derecha.setCurrentIndex(0)
            return
        trabajo.fila.set_elegida(True)
        self.derecha.setCurrentIndex(1)
        self._mostrar(trabajo)

    def _mostrar(self, trabajo: Trabajo) -> None:
        resultado = trabajo.resultado
        self.titulo.setText(resultado.output.name if resultado else trabajo.fuente.name)
        self.resumen.setText(self._resumen_de(trabajo))

        hay_resultado = resultado is not None
        self.boton_abrir.setVisible(hay_resultado)
        self.boton_carpeta.setVisible(hay_resultado)
        es_tex = hay_resultado and resultado.output.suffix.lower() == ".tex"
        self.boton_editar.setVisible(es_tex)

        self.registro.setPlainText("\n".join(trabajo.registro))
        self.registro.verticalScrollBar().setValue(self.registro.verticalScrollBar().maximum())

        avisos = list(resultado.warnings) if resultado else []
        if trabajo.error:
            self.texto_avisos.setText(trabajo.error.splitlines()[0] if trabajo.error else "")
            self.caja_avisos.show()
        elif avisos:
            self.texto_avisos.setText("\n".join(avisos))
            self.caja_avisos.show()
        else:
            self.caja_avisos.hide()

        self.pestanas.setTabVisible(self.pestana_codigo, es_tex)
        if es_tex:
            self.vista_texto.setPlainText(resultado.output.read_text(encoding="utf-8", errors="replace"))
        elif self.pestanas.currentIndex() == self.pestana_codigo:
            self.pestanas.setCurrentIndex(self.pestana_vista)

        self._mostrar_original(trabajo)
        self._mostrar_vista(trabajo)

    def _mostrar_original(self, trabajo: Trabajo) -> None:
        es_pdf = trabajo.fuente.suffix.lower() == ".pdf"
        self.vista_original.setVisible(es_pdf)
        self._actualizar_a_la_vez()
        if es_pdf and self.vista_original.path != trabajo.fuente:
            self.vista_original.load(trabajo.fuente, conservar_posicion=False)
        if es_pdf:
            QTimer.singleShot(0, self._repartir_vista)

    def _actualizar_a_la_vez(self) -> None:
        """Solo tiene sentido viendo dos documentos lado a lado."""
        self.opcion_a_la_vez.setVisible(
            self.pestanas.currentIndex() == self.pestana_vista
            and self.elegido is not None
            and self.elegido.fuente.suffix.lower() == ".pdf"
            and self.elegido.resultado is not None
        )

    def _repartir_vista(self) -> None:
        mitad = max(1, self.vista_comparar.width() // 2)
        self.vista_comparar.setSizes([mitad, mitad])

    def _mostrar_vista(self, trabajo: Trabajo) -> None:
        resultado = trabajo.resultado
        if trabajo.estado in (EN_COLA, CONVIRTIENDO, CANCELADO):
            mensaje = "Convirtiendo…" if trabajo.estado == CONVIRTIENDO else "Todavía sin convertir."
            if trabajo.estado == CANCELADO:
                mensaje = "Conversión cancelada."
            self.vista_pdf.clear(mensaje)
            return
        if trabajo.estado == FALLO:
            self.vista_pdf.clear("La conversión falló. Mira el registro para ver el motivo.")
            return
        if resultado is None:
            return

        salida = resultado.output
        extension = salida.suffix.lower()
        if extension == ".pdf":
            self.vista_pdf.load(salida, conservar_posicion=False)
        elif trabajo.vista is not None:
            self.vista_pdf.load(trabajo.vista, conservar_posicion=False)
        elif trabajo.fallo_vista:
            self.vista_pdf.clear(trabajo.fallo_vista)
        elif not self.opcion_vista_previa.isChecked():
            self.vista_pdf.clear("Vista previa desactivada.")
        elif extension == ".docx" and office.office_name() is None:
            self.vista_pdf.clear(
                "Para ver aquí el documento de Word hace falta Word o LibreOffice.\n"
                "Pulsa «Abrir» para abrirlo con tu programa."
            )
        elif self.is_converting():
            self.vista_pdf.clear("La vista previa se genera al terminar la cola.")
        else:
            self._start_preview(trabajo)

    def _resumen_de(self, trabajo: Trabajo) -> str:
        if trabajo.resultado is None:
            return human_size(trabajo.fuente) if trabajo.fuente.exists() else ""
        resultado = trabajo.resultado
        partes = [human_size(resultado.output)]
        nombres = {
            "paginas": ("página", "páginas"),
            "ecuaciones_word": ("ecuación editable", "ecuaciones editables"),
            "formulas": ("fórmula", "fórmulas"),
            "imagenes": ("imagen", "imágenes"),
            "formulas_ocr": ("fórmula por OCR", "fórmulas por OCR"),
        }
        for clave, (singular, plural) in nombres.items():
            valor = resultado.stats.get(clave)
            if clave == "formulas" and resultado.stats.get("ecuaciones_word") is not None:
                continue
            if valor:
                partes.append(f"{valor} {singular if valor == 1 else plural}")
        if resultado.stats.get("motor"):
            partes.append(str(resultado.stats["motor"]))
        return "  ·  ".join(partes)

    # ── Vista previa ────────────────────────────────────────
    def _start_preview(self, trabajo: Trabajo) -> None:
        if self._previa_de is trabajo and self.preview_worker is not None and self.preview_worker.isRunning():
            return
        self._parar_vista_previa()
        self._previa_de = trabajo
        extension = trabajo.resultado.output.suffix.lower()
        self.vista_pdf.clear("Exportando con " + office.office_name() + "…" if extension == ".docx"
                             else "Compilando el documento…")
        self.preview_worker = PreviewWorker(trabajo.resultado.output, self._carpeta_vistas)
        self.preview_worker.message.connect(self._log)
        self.preview_worker.succeeded.connect(lambda pdf, t=trabajo: self._on_preview_ready(t, pdf))
        self.preview_worker.failed.connect(lambda mensaje, t=trabajo: self._on_preview_failed(t, mensaje))
        self.preview_worker.start()

    def _parar_vista_previa(self) -> None:
        if self.preview_worker is not None and self.preview_worker.isRunning():
            self.preview_worker.cancelacion.cancel()
            if not self.preview_worker.wait(3000):
                self.preview_worker.terminate()
                self.preview_worker.wait(2000)
        self._previa_de = None

    def _on_preview_ready(self, trabajo: Trabajo, pdf: Path) -> None:
        trabajo.vista = Path(pdf)
        if trabajo is self.elegido:
            self.vista_pdf.load(trabajo.vista, conservar_posicion=False)

    def _on_preview_failed(self, trabajo: Trabajo, mensaje: str) -> None:
        trabajo.registro.extend(["", "La vista previa falló: " + mensaje])
        trabajo.fallo_vista = (
            "El documento convertido no compila todavía.\n\n"
            "Pulsa «Abrir en el editor» para corregirlo: el editor marca cada error en su línea."
            if trabajo.resultado.output.suffix.lower() == ".tex"
            else "No se pudo generar la vista previa. Pulsa «Abrir» para ver el documento."
        )
        if trabajo is self.elegido:
            self.vista_pdf.clear(trabajo.fallo_vista)
            self.registro.setPlainText("\n".join(trabajo.registro))

    def _open_result(self) -> None:
        if self.elegido and self.elegido.resultado:
            open_in_explorer(self.elegido.resultado.output)

    def _reveal_result(self) -> None:
        if self.elegido and self.elegido.resultado:
            reveal_in_explorer(self.elegido.resultado.output)

    def _edit_result(self) -> None:
        if self.elegido and self.elegido.resultado:
            if self.elegido.resultado.output.suffix.lower() == ".tex":
                self.documentReady.emit(self.elegido.resultado.output)

    def is_converting(self) -> bool:
        # No se pregunta al hilo: puede haber acabado con sus señales aún por llegar.
        return self.en_curso is not None or bool(self.pendientes)

    def is_busy(self) -> bool:
        return self.is_converting() or (
            self.preview_worker is not None and self.preview_worker.isRunning()
        )

    def stop(self) -> None:
        self._cancelando = True
        self.pendientes = []
        for hilo in (self.worker, self.preview_worker):
            if hilo is not None and hilo.isRunning():
                # Primero se matan pandoc y pdflatex y se avisa a lo que corre
                # dentro de Python; terminate() es para lo que no llegue a enterarse.
                hilo.cancelacion.cancel()
                if not hilo.wait(3000):
                    hilo.terminate()
                    hilo.wait(2000)
        shutil.rmtree(self._carpeta_vistas, ignore_errors=True)
