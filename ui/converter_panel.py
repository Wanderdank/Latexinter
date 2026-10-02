"""
converter_panel.py - El conversor entre PDF, LaTeX y Word.

Es la pestaña «Conversor» de la ventana principal: se elige un archivo (o se
pega código LaTeX), se elige el destino y se convierte en un hilo aparte para
que la ventana siga respondiendo.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QThread, Qt, QTimer, pyqtSignal
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from converters import (
    CONVERSIONS,
    SUPPORTED_EXTENSIONS,
    ConversionError,
    ConversionResult,
    conversions_for,
    convert,
    human_size,
    open_in_explorer,
    reveal_in_explorer,
)

from . import theme
from .latex_syntax import LatexHighlighter
from .pdf_view import PdfView

FILE_FILTER = (
    "Documentos compatibles (*.pdf *.tex *.docx);;"
    "PDF (*.pdf);;LaTeX (*.tex);;Word (*.docx);;Todos los archivos (*)"
)


# ════════════════════════════════════════════════════════════
# Zona para soltar archivos
# ════════════════════════════════════════════════════════════

class DropZone(QFrame):
    fileDropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("zona")
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)

        self.icono = QLabel("📄")
        self.icono.setAlignment(Qt.AlignCenter)
        self.icono.setStyleSheet("font-size: 32px;")

        self.titulo = QLabel("Arrastra aquí un PDF, un .tex o un .docx")
        self.titulo.setAlignment(Qt.AlignCenter)
        self.titulo.setWordWrap(True)

        self.detalle = QLabel("o pulsa el botón de abajo")
        self.detalle.setObjectName("pista")
        self.detalle.setAlignment(Qt.AlignCenter)
        self.detalle.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)
        layout.addWidget(self.icono)
        layout.addWidget(self.titulo)
        layout.addWidget(self.detalle)

    def _first_supported(self, event) -> Optional[str]:
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            ruta = url.toLocalFile()
            if ruta and Path(ruta).suffix.lower() in SUPPORTED_EXTENSIONS:
                return ruta
        return None

    def dragEnterEvent(self, event) -> None:
        if self._first_supported(event):
            event.acceptProposedAction()
            self.setProperty("activa", "true")
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("activa", "false")
        self.style().polish(self)

    def dropEvent(self, event) -> None:
        ruta = self._first_supported(event)
        self.setProperty("activa", "false")
        self.style().polish(self)
        if ruta:
            event.acceptProposedAction()
            self.fileDropped.emit(ruta)

    def show_file(self, path: Path) -> None:
        iconos = {".pdf": "📕", ".tex": "📐", ".docx": "📘"}
        self.icono.setText(iconos.get(path.suffix.lower(), "📄"))
        self.titulo.setText(path.name)
        self.detalle.setText(f"{human_size(path)}  ·  {path.parent}")


# ════════════════════════════════════════════════════════════
# Hilo de conversión
# ════════════════════════════════════════════════════════════

class ConversionWorker(QThread):
    message = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, key: str, source: Path, output_dir: Optional[Path], options: dict):
        super().__init__()
        self.key = key
        self.source = source
        self.output_dir = output_dir
        self.options = options

    def run(self) -> None:
        try:
            resultado = convert(
                self.key, self.source,
                output_dir=self.output_dir,
                logger=self.message.emit,
                **self.options,
            )
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
    Compila el .tex recién convertido para enseñar cómo queda. Se conservan
    el .synctex y el .aux: si luego se abre en el editor, el salto entre
    código y PDF funciona sin tener que volver a compilar.
    """

    message = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, tex_path: Path):
        super().__init__()
        self.tex_path = Path(tex_path)

    def run(self) -> None:
        try:
            texto = self.tex_path.read_text(encoding="utf-8", errors="replace")
            # Lo que exige fontspec no compila con pdflatex.
            motor = "xelatex" if "{fontspec}" in texto else "pdflatex"
            resultado = convert(
                "tex2pdf", self.tex_path,
                logger=self.message.emit,
                engine=motor, clean_aux=False, synctex=True,
            )
        except ConversionError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Error inesperado al compilar:\n\n" + traceback.format_exc())
        else:
            self.succeeded.emit(resultado)


# ════════════════════════════════════════════════════════════
# Panel
# ════════════════════════════════════════════════════════════

class ConverterPanel(QWidget):
    """Pestaña completa del conversor."""

    documentReady = pyqtSignal(object)          # .tex generado, para abrirlo en el editor

    def __init__(self, scratch_dir: Path, parent=None):
        super().__init__(parent)
        self.scratch_dir = Path(scratch_dir)
        self.source: Optional[Path] = None
        self.worker: Optional[ConversionWorker] = None
        self.preview_worker: Optional[PreviewWorker] = None
        self.result: Optional[ConversionResult] = None

        cuerpo = QHBoxLayout(self)
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(14)
        cuerpo.addWidget(self._build_left_panel(), 4)
        cuerpo.addWidget(self._build_right_panel(), 6)

        self._refresh_targets()

    # ── Panel izquierdo ─────────────────────────────────────
    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("tarjeta")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.entrada = QTabWidget()

        pestana_archivo = QWidget()
        pestana_archivo.setStyleSheet("background: transparent;")
        archivo_layout = QVBoxLayout(pestana_archivo)
        archivo_layout.setContentsMargins(0, 12, 0, 0)
        archivo_layout.setSpacing(10)
        self.zona = DropZone()
        self.zona.fileDropped.connect(self.set_source)
        archivo_layout.addWidget(self.zona)
        boton_examinar = QPushButton("Elegir archivo…")
        boton_examinar.clicked.connect(self._browse)
        archivo_layout.addWidget(boton_examinar)
        archivo_layout.addStretch(1)

        pestana_codigo = QWidget()
        pestana_codigo.setStyleSheet("background: transparent;")
        codigo_layout = QVBoxLayout(pestana_codigo)
        codigo_layout.setContentsMargins(0, 12, 0, 0)
        codigo_layout.setSpacing(8)
        self.editor = QPlainTextEdit()
        self.editor.setFont(theme.mono_font(10))
        self.editor.setPlaceholderText(
            "\\documentclass{article}\n\\begin{document}\nHola mundo\n\\end{document}"
        )
        LatexHighlighter(self.editor.document())
        codigo_layout.addWidget(self.editor, 1)
        pista = QLabel("Se guardará como .tex en la carpeta de salida antes de convertir.")
        pista.setObjectName("pista")
        pista.setWordWrap(True)
        codigo_layout.addWidget(pista)

        self.entrada.addTab(pestana_archivo, "  Archivo  ")
        self.entrada.addTab(pestana_codigo, "  Código LaTeX  ")
        self.entrada.currentChanged.connect(lambda _: self._refresh_targets())
        layout.addWidget(self.entrada, 1)

        layout.addWidget(self._section_label("Convertir a"))
        self.destino = QComboBox()
        self.destino.currentIndexChanged.connect(self._refresh_options)
        layout.addWidget(self.destino)

        layout.addWidget(self._section_label("Opciones"))
        layout.addWidget(self._build_options())

        layout.addWidget(self._section_label("Carpeta de salida"))
        salida = QHBoxLayout()
        self.carpeta_salida = QLineEdit()
        self.carpeta_salida.setPlaceholderText("Junto al archivo original")
        boton_carpeta = QPushButton("…")
        boton_carpeta.setFixedWidth(38)
        boton_carpeta.clicked.connect(self._choose_output_dir)
        salida.addWidget(self.carpeta_salida, 1)
        salida.addWidget(boton_carpeta)
        layout.addLayout(salida)

        self.boton_convertir = QPushButton("Convertir")
        self.boton_convertir.setObjectName("principal")
        self.boton_convertir.clicked.connect(self.start_conversion)
        layout.addWidget(self.boton_convertir)

        self.progreso = QProgressBar()
        self.progreso.setRange(0, 0)
        self.progreso.setTextVisible(False)
        self.progreso.hide()
        layout.addWidget(self.progreso)

        contenedor = QScrollArea()
        contenedor.setWidgetResizable(True)
        contenedor.setWidget(panel)
        contenedor.setFrameStyle(0)
        return contenedor

    def _section_label(self, text: str) -> QLabel:
        etiqueta = QLabel(text)
        etiqueta.setObjectName("seccion")
        return etiqueta

    def _build_options(self) -> QWidget:
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        rejilla = QGridLayout(contenedor)
        rejilla.setContentsMargins(0, 0, 0, 0)
        rejilla.setHorizontalSpacing(10)
        rejilla.setVerticalSpacing(8)

        self.opcion_paginas = QLineEdit()
        self.opcion_paginas.setPlaceholderText("todas   (ej.: 1-5 o 1,3,8-10)")
        self.etiqueta_paginas = QLabel("Páginas")

        self.etiqueta_ecuaciones = QLabel("Ecuaciones destacadas")
        self.opcion_ecuaciones = QComboBox()
        self.opcion_ecuaciones.addItem("Automático", None)
        self.opcion_ecuaciones.addItem("Imagen + LaTeX en comentario", "comentario")
        self.opcion_ecuaciones.addItem("LaTeX reconstruido", "latex")
        self.opcion_ecuaciones.addItem("Solo la imagen", "imagen")
        self.opcion_ecuaciones.setToolTip(
            "Las ecuaciones centradas se extraen del PDF como imagen.\n"
            "Latexinter puede además reconstruirlas en LaTeX.\n\n"
            "En automático: con OCR activado sustituye la imagen por el LaTeX,\n"
            "y sin OCR conserva la imagen y deja la reconstrucción comentada."
        )

        self.etiqueta_motor = QLabel("Motor")
        self.opcion_motor = QComboBox()
        self.opcion_motor.addItems(["pdflatex", "xelatex", "lualatex"])

        self.opcion_imagenes = QCheckBox("Extraer las imágenes")
        self.opcion_imagenes.setChecked(True)
        self.opcion_matematicas = QCheckBox("Reconstruir fórmulas")
        self.opcion_matematicas.setChecked(True)
        self.opcion_matematicas.setToolTip(
            "Deduce superíndices, subíndices y ecuaciones a partir de la\n"
            "maquetación del PDF, en vez de dejarlos como texto plano."
        )
        self.opcion_ocr = QCheckBox("Reconocer las fórmulas con OCR")
        self.opcion_ocr.setToolTip(
            "Recorta cada fórmula del PDF y se la pasa a un modelo de\n"
            "reconocimiento. Es la única forma de recuperar lo que está\n"
            "apilado: fracciones, matrices, binomios.\n"
            "Necesita un modelo instalado y va bastante más lento."
        )
        self.opcion_ocr.toggled.connect(self._comprobar_ocr)

        self.etiqueta_motor_ocr = QLabel("Modelo de OCR")
        self.opcion_motor_ocr = QComboBox()
        self._rellenar_motores_ocr()

        self.opcion_dos_columnas = QCheckBox("Documento a dos columnas")
        self.opcion_markdown = QCheckBox("Conservar el Markdown intermedio")
        self.opcion_limpiar = QCheckBox("Borrar los archivos auxiliares")
        self.opcion_limpiar.setChecked(True)
        self.opcion_indice = QCheckBox("Añadir índice al documento de Word")
        self.opcion_numerar = QCheckBox("Numerar las secciones")
        self.opcion_numerar.setChecked(True)
        self.opcion_vista_previa = QCheckBox("Compilar y enseñar el resultado")
        self.opcion_vista_previa.setChecked(True)
        self.opcion_vista_previa.setToolTip(
            "Al terminar, compila el .tex generado y lo enseña aquí mismo:\n"
            "el código LaTeX a un lado y el PDF al otro."
        )

        filas = [
            (self.etiqueta_paginas, self.opcion_paginas),
            (self.etiqueta_ecuaciones, self.opcion_ecuaciones),
            (self.etiqueta_motor_ocr, self.opcion_motor_ocr),
            (self.etiqueta_motor, self.opcion_motor),
        ]
        for fila, (etiqueta, control) in enumerate(filas):
            rejilla.addWidget(etiqueta, fila, 0)
            rejilla.addWidget(control, fila, 1)

        sueltos = [
            self.opcion_imagenes, self.opcion_matematicas, self.opcion_ocr,
            self.opcion_dos_columnas, self.opcion_markdown, self.opcion_limpiar,
            self.opcion_indice, self.opcion_numerar, self.opcion_vista_previa,
        ]
        for indice, control in enumerate(sueltos):
            rejilla.addWidget(control, len(filas) + indice, 0, 1, 2)

        self.controles = {
            "pages": (self.opcion_paginas, self.etiqueta_paginas),
            "display_equations": (self.opcion_ecuaciones, self.etiqueta_ecuaciones),
            "math_ocr": (self.opcion_ocr, None),
            "ocr_backend": (self.opcion_motor_ocr, self.etiqueta_motor_ocr),
            "engine": (self.opcion_motor, self.etiqueta_motor),
            "extract_images": (self.opcion_imagenes, None),
            "math_reconstruction": (self.opcion_matematicas, None),
            "twocolumn": (self.opcion_dos_columnas, None),
            "keep_markdown": (self.opcion_markdown, None),
            "clean_aux": (self.opcion_limpiar, None),
            "toc": (self.opcion_indice, None),
            "number_sections": (self.opcion_numerar, None),
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

    def _comprobar_ocr(self, activo: bool) -> None:
        """Al activar el OCR sin modelo, se explica qué hay que instalar."""
        if not activo:
            return
        from converters import mathocr

        self._rellenar_motores_ocr()
        if mathocr.any_backend_installed():
            return

        self.opcion_ocr.setChecked(False)
        texto = [
            "El OCR de fórmulas necesita un modelo de reconocimiento, y no hay "
            "ninguno instalado.",
            "",
            "Sin él, Latexinter recupera los índices y los símbolos leyendo la "
            "maquetación, pero no puede reconstruir lo que está apilado "
            "(fracciones, matrices).",
            "",
            "Para instalarlo, desde una consola en la carpeta del proyecto:",
        ]
        for backend in mathocr.BACKENDS:
            texto.append("")
            texto.append(f"  {backend.name}  —  {backend.size}")
            texto.append(f"      {backend.install}")
            texto.append(f"      {backend.description}")
        QMessageBox.information(self, "Latexinter", "\n".join(texto))

    # ── Panel derecho ───────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("tarjeta")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.resumen = QLabel("Sin conversiones todavía.")
        self.resumen.setObjectName("pista")
        self.resumen.setWordWrap(True)
        layout.addWidget(self.resumen)

        self.pestanas = QTabWidget()
        self.vista_pdf = PdfView()
        self.vista_pdf.clear("Aquí aparecerá el documento compilado.")
        self.vista_texto = QPlainTextEdit()
        self.vista_texto.setReadOnly(True)
        self.vista_texto.setFont(theme.mono_font(10))
        LatexHighlighter(self.vista_texto.document())
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setFont(theme.mono_font(10))

        # Código y PDF lado a lado: así se ve a la vez qué ha salido de la
        # conversión y cómo queda impreso.
        self.vista_resultado = QSplitter(Qt.Horizontal)
        self.vista_resultado.addWidget(self.vista_texto)
        self.vista_resultado.addWidget(self.vista_pdf)
        self.vista_resultado.setChildrenCollapsible(False)
        self.vista_pdf.hide()

        self.pestanas.addTab(self.vista_resultado, "  Resultado  ")
        self.pestanas.addTab(self.registro, "  Registro  ")
        layout.addWidget(self.pestanas, 1)

        acciones = QHBoxLayout()
        self.boton_editar = QPushButton("Abrir en el editor")
        self.boton_editar.clicked.connect(self._edit_result)
        self.boton_abrir = QPushButton("Abrir el archivo")
        self.boton_abrir.clicked.connect(self._open_result)
        self.boton_carpeta = QPushButton("Ver en la carpeta")
        self.boton_carpeta.clicked.connect(self._reveal_result)
        for boton in (self.boton_editar, self.boton_abrir, self.boton_carpeta):
            boton.setEnabled(False)
            acciones.addWidget(boton)
        acciones.addStretch(1)
        layout.addLayout(acciones)
        return panel

    # ── Entrada ─────────────────────────────────────────────
    def _browse(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir documento", str(Path.home()), FILE_FILTER
        )
        if ruta:
            self.set_source(ruta)

    def set_source(self, path: str | Path) -> None:
        source = Path(path)
        if not source.exists():
            QMessageBox.warning(self, "Latexinter", f"No existe el archivo:\n{source}")
            return
        if not conversions_for(source):
            QMessageBox.warning(
                self, "Latexinter",
                f"No sé qué hacer con un archivo {source.suffix}.\n"
                f"Formatos admitidos: {', '.join(SUPPORTED_EXTENSIONS)}",
            )
            return
        self.source = source
        self.zona.show_file(source)
        self.entrada.setCurrentIndex(0)
        self._refresh_targets()

    def _choose_output_dir(self) -> None:
        inicio = self.carpeta_salida.text() or (
            str(self.source.parent) if self.source else str(Path.home())
        )
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de salida", inicio)
        if carpeta:
            self.carpeta_salida.setText(carpeta)

    # ── Destinos y opciones ─────────────────────────────────
    def _refresh_targets(self) -> None:
        self.destino.blockSignals(True)
        self.destino.clear()

        if self.entrada.currentIndex() == 1:
            disponibles = [CONVERSIONS["tex2pdf"], CONVERSIONS["tex2docx"]]
        elif self.source:
            disponibles = conversions_for(self.source)
        else:
            disponibles = []

        for conversion in disponibles:
            self.destino.addItem(conversion.label, conversion.key)
        self.destino.setEnabled(bool(disponibles))
        self.destino.blockSignals(False)

        self.boton_convertir.setEnabled(bool(disponibles))
        self._refresh_options()

    def _refresh_options(self) -> None:
        clave = self.destino.currentData()
        opciones = CONVERSIONS[clave].options if clave else frozenset()
        for nombre, (control, etiqueta) in self.controles.items():
            visible = nombre in opciones
            control.setVisible(visible)
            if etiqueta is not None:
                etiqueta.setVisible(visible)
        # No es una opción del conversor sino de la ventana: vale para todo lo
        # que produce un .tex.
        self.opcion_vista_previa.setVisible(
            bool(clave) and CONVERSIONS[clave].target_extension == ".tex"
        )
        if clave:
            self.resumen.setText(CONVERSIONS[clave].description)

    def _collect_options(self) -> dict:
        return {
            "pages": self.opcion_paginas.text().strip() or None,
            "display_equations": self.opcion_ecuaciones.currentData(),
            "engine": self.opcion_motor.currentText(),
            "extract_images": self.opcion_imagenes.isChecked(),
            "math_reconstruction": self.opcion_matematicas.isChecked(),
            "math_ocr": self.opcion_ocr.isChecked(),
            "ocr_backend": self.opcion_motor_ocr.currentData(),
            "twocolumn": self.opcion_dos_columnas.isChecked(),
            "keep_markdown": self.opcion_markdown.isChecked(),
            "clean_aux": self.opcion_limpiar.isChecked(),
            "toc": self.opcion_indice.isChecked(),
            "number_sections": self.opcion_numerar.isChecked(),
        }

    # ── Conversión ──────────────────────────────────────────
    def _resolve_source(self) -> Optional[Path]:
        if self.entrada.currentIndex() == 0:
            if self.source is None:
                QMessageBox.information(
                    self, "Latexinter", "Primero elige o arrastra un archivo."
                )
            return self.source

        codigo = self.editor.toPlainText().strip()
        if not codigo:
            QMessageBox.information(self, "Latexinter", "La caja de código está vacía.")
            return None

        carpeta = (
            Path(self.carpeta_salida.text()) if self.carpeta_salida.text()
            else self.scratch_dir
        )
        carpeta.mkdir(parents=True, exist_ok=True)

        destino = carpeta / "documento.tex"
        indice = 1
        while destino.exists() and destino.read_text(
            encoding="utf-8", errors="replace"
        ) != codigo:
            destino = carpeta / f"documento_{indice}.tex"
            indice += 1

        destino.write_text(codigo, encoding="utf-8")
        self._log(f"Código guardado en: {destino}")
        return destino

    def start_conversion(self) -> None:
        if self.is_busy():
            return
        clave = self.destino.currentData()
        if not clave:
            return

        self.registro.clear()
        source = self._resolve_source()
        if source is None:
            return

        carpeta_texto = self.carpeta_salida.text().strip()
        carpeta = Path(carpeta_texto) if carpeta_texto else None

        self.result = None
        for boton in (self.boton_editar, self.boton_abrir, self.boton_carpeta):
            boton.setEnabled(False)
        self.boton_convertir.setEnabled(False)
        self.boton_convertir.setText("Convirtiendo…")
        self.progreso.show()
        self.pestanas.setCurrentWidget(self.registro)
        self.resumen.setText(f"{CONVERSIONS[clave].label} · {source.name}")

        self.worker = ConversionWorker(clave, source, carpeta, self._collect_options())
        self.worker.message.connect(self._log)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _log(self, mensaje: str) -> None:
        self.registro.appendPlainText(mensaje)

    def _on_finished(self) -> None:
        # La conversión termina cuando la vista previa ya ha arrancado: el
        # botón sigue ocupado hasta que acabe también ella.
        previa = self.preview_worker
        if previa is not None and previa.isRunning() and self.sender() is not previa:
            return
        self.progreso.hide()
        self.boton_convertir.setEnabled(True)
        self.boton_convertir.setText("Convertir")

    def _on_failure(self, mensaje: str) -> None:
        self._log("")
        self._log("✗ " + mensaje)
        self.resumen.setText("La conversión falló. Mira el registro.")
        QMessageBox.critical(self, "Latexinter", mensaje)

    def _on_success(self, resultado: ConversionResult) -> None:
        self.result = resultado
        self.boton_abrir.setEnabled(True)
        self.boton_carpeta.setEnabled(True)
        self.boton_editar.setEnabled(resultado.output.suffix.lower() == ".tex")

        detalles = [f"<b>{resultado.output.name}</b> · {human_size(resultado.output)}"]
        nombres = {
            "formulas": ("fórmula", "fórmulas"),
            "paginas": ("página", "páginas"),
            "imagenes": ("imagen", "imágenes"),
            "indices_reconstruidos": ("índice reconstruido", "índices reconstruidos"),
            "ecuaciones_destacadas": ("ecuación destacada", "ecuaciones destacadas"),
            "formulas_ocr": ("fórmula por OCR", "fórmulas por OCR"),
        }
        for clave, (singular, plural) in nombres.items():
            valor = resultado.stats.get(clave)
            if valor:
                detalles.append(f"{valor} {singular if valor == 1 else plural}")
        if resultado.stats.get("motor"):
            detalles.append(str(resultado.stats["motor"]))
        self.resumen.setText("  ·  ".join(detalles))

        for aviso in resultado.warnings:
            self._log("⚠ " + aviso)
        self._log("")
        self._log(f"✓ Generado: {resultado.output}")
        for extra in resultado.extras:
            self._log(f"  + {extra.name}")

        self._show_preview(resultado.output)

        if resultado.output.suffix.lower() == ".tex" and self.opcion_vista_previa.isChecked():
            self._start_preview(resultado.output)

    def _show_preview(self, path: Path) -> None:
        extension = path.suffix.lower()
        if extension == ".pdf":
            self.vista_texto.hide()
            self.vista_pdf.show()
            self.vista_pdf.load(path, conservar_posicion=False)
        elif extension == ".tex":
            self.vista_texto.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
            self.vista_texto.show()
            compilar = self.opcion_vista_previa.isChecked()
            self.vista_pdf.setVisible(compilar)
            if compilar:
                self.vista_pdf.clear("Compilando el documento…")
                self._repartir_vista()
        else:
            self.vista_pdf.hide()
            self.vista_texto.show()
            self.vista_texto.setPlainText(
                f"{path.name}\n\n"
                "Los documentos de Word no se pueden previsualizar aquí.\n"
                'Pulsa "Abrir el archivo" para verlo.'
            )
        self.pestanas.setCurrentIndex(0)

    def _repartir_vista(self) -> None:
        # Se espera a que Qt coloque el panel recién mostrado para medirlo.
        def repartir() -> None:
            mitad = max(1, self.vista_resultado.width() // 2)
            self.vista_resultado.setSizes([mitad, mitad])

        QTimer.singleShot(0, repartir)

    # ── Vista previa del .tex generado ──────────────────────
    def _start_preview(self, tex_path: Path) -> None:
        self._log("")
        self._log("Compilando la vista previa…")
        self.progreso.show()
        self.boton_convertir.setEnabled(False)
        self.boton_convertir.setText("Compilando la vista previa…")

        self.preview_worker = PreviewWorker(tex_path)
        self.preview_worker.message.connect(self._log)
        self.preview_worker.succeeded.connect(self._on_preview_ready)
        self.preview_worker.failed.connect(self._on_preview_failed)
        self.preview_worker.finished.connect(self._on_finished)
        self.preview_worker.start()

    def _on_preview_ready(self, resultado: ConversionResult) -> None:
        self.vista_pdf.load(resultado.output, conservar_posicion=False)
        paginas = resultado.stats.get("paginas")
        self._log(f"✓ Vista previa: {resultado.output.name}"
                  + (f" ({paginas} páginas)" if paginas else ""))
        for aviso in resultado.warnings:
            self._log("⚠ " + aviso)
        if resultado.warnings:
            self._log("  Abre el documento en el editor para corregirlo.")
        self.pestanas.setCurrentIndex(0)

    def _on_preview_failed(self, mensaje: str) -> None:
        self._log("")
        self._log("✗ La vista previa no compiló: " + mensaje)
        self.vista_pdf.clear(
            "El documento convertido no compila todavía.\n\n"
            "Mira el registro para ver el error, o pulsa «Abrir en el editor» "
            "para corregirlo: el editor marca cada error en su línea."
        )
        self.pestanas.setCurrentIndex(0)

    def _open_result(self) -> None:
        if self.result:
            open_in_explorer(self.result.output)

    def _reveal_result(self) -> None:
        if self.result:
            reveal_in_explorer(self.result.output)

    def _edit_result(self) -> None:
        if self.result and self.result.output.suffix.lower() == ".tex":
            self.documentReady.emit(self.result.output)

    def is_busy(self) -> bool:
        return any(
            hilo is not None and hilo.isRunning()
            for hilo in (self.worker, self.preview_worker)
        )

    def stop(self) -> None:
        for hilo in (self.worker, self.preview_worker):
            if hilo is not None and hilo.isRunning():
                hilo.terminate()
                hilo.wait(2000)
