"""
editor_page.py - El entorno de edición: código a la izquierda, PDF a la derecha.

Aquí se junta todo lo demás y se añade lo que hace que esto se parezca a un
entorno de trabajo y no a un bloc de notas:

  · varios documentos abiertos a la vez, en pestañas;
  · compilación en segundo plano, con opción de lanzarla sola al dejar de
    escribir;
  · los errores del .log convertidos en una lista donde se puede pinchar;
  · SyncTeX en los dos sentidos, para saltar del código al PDF y al revés.
"""

from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from converters import ConversionError, latex_to_pdf
from converters.tools import (
    Problem,
    forward_search,
    inverse_search,
    lint,
    parse_log,
    rough_word_count,
    word_count,
)

from . import theme
from .latex_editor import LatexEditor
from .panels import FindBar, OutlinePanel, ProblemsPanel, ProjectPanel
from .pdf_view import PdfView
from .templates import DOCUMENTO_VACIO

FILTRO_TEX = "LaTeX (*.tex);;Todos los archivos (*)"
_RE_DOCUMENTCLASS = re.compile(r"^[ \t]*\\documentclass", re.M)
EXTENSIONES_TEXTO = {".tex", ".bib", ".cls", ".sty", ".txt", ".md", ".log"}


# ════════════════════════════════════════════════════════════
# Compilación en segundo plano
# ════════════════════════════════════════════════════════════

class CompileWorker(QThread):
    message = pyqtSignal(str)
    finished_ok = pyqtSignal(object, object)    # ConversionResult, problemas
    failed = pyqtSignal(str, object)            # mensaje, problemas

    def __init__(self, tex_path: Path, engine: str, usar_chktex: bool = True):
        super().__init__()
        self.tex_path = Path(tex_path)
        self.engine = engine
        self.usar_chktex = usar_chktex

    def run(self) -> None:
        try:
            resultado = latex_to_pdf(
                self.tex_path,
                engine=self.engine,
                # Los auxiliares se conservan: sin el .synctex no hay salto
                # entre el código y el PDF, y sin el .aux no hay referencias.
                clean_aux=False,
                synctex=True,
                logger=self.message.emit,
            )
        except ConversionError as exc:
            self.failed.emit(str(exc), self._problemas())
        except Exception:
            self.failed.emit("Error inesperado:\n\n" + traceback.format_exc(), [])
        else:
            self.finished_ok.emit(resultado, self._problemas())

    def _problemas(self) -> list[Problem]:
        """
        Errores del .log y avisos de chktex. Se calculan aquí y no en la
        ventana porque chktex es un programa aparte y puede tardar.
        """
        problemas: list[Problem] = []
        registro = self.tex_path.with_suffix(".log")
        try:
            if registro.exists():
                problemas.extend(parse_log(
                    registro.read_text(encoding="utf-8", errors="replace"),
                    self.tex_path.parent,
                ))
            if self.usar_chktex:
                problemas.extend(lint(self.tex_path))
        except Exception:
            pass
        return problemas


# ════════════════════════════════════════════════════════════
# Página del editor
# ════════════════════════════════════════════════════════════

class OcrWorker(QThread):
    """
    Reconoce una fórmula en segundo plano. Cargar el modelo tarda varios
    segundos la primera vez, así que no puede hacerse en el hilo de la ventana.
    """

    message = pyqtSignal(str)
    recognized = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, imagen, backend: Optional[str] = None):
        super().__init__()
        self.imagen = imagen
        self.backend = backend

    def run(self) -> None:
        from converters import mathocr

        try:
            motor = mathocr.get_engine(self.backend, logger=self.message.emit)
            if not motor.available:
                self.failed.emit(
                    "No hay ningún modelo de OCR instalado.\n\n"
                    + mathocr.install_hint()
                )
                return
            latex = mathocr.recognize_image(motor, self.imagen)
        except Exception:
            self.failed.emit("El OCR falló:\n\n" + traceback.format_exc())
            return

        if latex:
            self.recognized.emit(latex)
        else:
            self.failed.emit(
                "El modelo no ha sabido leer esa imagen.\n"
                "Prueba con un recorte más ajustado y sin texto alrededor."
            )


class EditorPage(QWidget):
    """Editor, visor y paneles."""

    statusMessage = pyqtSignal(str, int)         # texto, milisegundos
    cursorMoved = pyqtSignal(int, int)
    documentChanged = pyqtSignal()               # cambió la pestaña activa o su estado
    compileStateChanged = pyqtSignal(str)        # inactivo | compilando | ok | error

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = "pdflatex"
        self.auto_compilar = False
        self.usar_chktex = True
        self.modo_ajuste = QPlainTextEdit.WidgetWidth
        self.documento_principal: Optional[Path] = None
        self.worker: Optional[CompileWorker] = None
        self._ocr_worker: Optional[OcrWorker] = None
        self._pendiente_recompilar = False
        self._resultados_busqueda: list[tuple[int, int]] = []
        self._indice_busqueda = -1

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)

        self.divisor = QSplitter(Qt.Horizontal)
        self.divisor.addWidget(self._build_side_panel())
        self.divisor.addWidget(self._build_center())
        self.divisor.addWidget(self._build_pdf_panel())
        self.divisor.setStretchFactor(0, 0)
        self.divisor.setStretchFactor(1, 5)
        self.divisor.setStretchFactor(2, 5)
        self.divisor.setSizes([230, 620, 620])
        raiz.addWidget(self.divisor)

        # Compilar sola tras dejar de escribir
        self._temporizador_auto = QTimer(self)
        self._temporizador_auto.setSingleShot(True)
        self._temporizador_auto.setInterval(2500)
        self._temporizador_auto.timeout.connect(self._auto_compilar)

        # Refrescar el esquema y el recuento sin castigar cada pulsación
        self._temporizador_esquema = QTimer(self)
        self._temporizador_esquema.setSingleShot(True)
        self._temporizador_esquema.setInterval(600)
        self._temporizador_esquema.timeout.connect(self._refrescar_esquema)

    # ════════════════════════════════════════════════════════
    # Construcción
    # ════════════════════════════════════════════════════════

    def _build_side_panel(self) -> QWidget:
        self.lateral = QTabWidget()
        self.lateral.setMinimumWidth(180)

        self.esquema = OutlinePanel()
        self.esquema.goto.connect(self._ir_a_linea)
        self.archivos = ProjectPanel()
        self.archivos.openFile.connect(self.open_file)

        self.lateral.addTab(self.esquema, " Esquema ")
        self.lateral.addTab(self.archivos, " Archivos ")
        return self.lateral

    def _build_center(self) -> QWidget:
        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.documentos = QTabWidget()
        self.documentos.setTabsClosable(True)
        self.documentos.setMovable(True)
        self.documentos.setDocumentMode(True)
        self.documentos.tabCloseRequested.connect(self.close_document)
        self.documentos.currentChanged.connect(self._cambio_de_pestana)
        layout.addWidget(self.documentos, 1)

        self.barra_busqueda = FindBar()
        self.barra_busqueda.buscar.connect(self._buscar)
        self.barra_busqueda.reemplazar.connect(self._reemplazar)
        self.barra_busqueda.cerrada.connect(self._cerrar_busqueda)
        layout.addWidget(self.barra_busqueda)

        self.inferior = QTabWidget()
        self.inferior.setMaximumHeight(220)
        self.problemas = ProblemsPanel()
        self.problemas.goto.connect(self._ir_a_problema)
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setFont(theme.mono_font(9))
        self.inferior.addTab(self.problemas, " Problemas ")
        self.inferior.addTab(self.registro, " Registro ")
        layout.addWidget(self.inferior)

        return contenedor

    def _build_pdf_panel(self) -> QWidget:
        self.pdf = PdfView()
        self.pdf.syncRequested.connect(self._sync_desde_pdf)
        return self.pdf

    # ════════════════════════════════════════════════════════
    # Documentos abiertos
    # ════════════════════════════════════════════════════════

    @property
    def editor(self) -> Optional[LatexEditor]:
        widget = self.documentos.currentWidget()
        return widget if isinstance(widget, LatexEditor) else None

    def _editores(self) -> list[LatexEditor]:
        return [
            self.documentos.widget(i)
            for i in range(self.documentos.count())
            if isinstance(self.documentos.widget(i), LatexEditor)
        ]

    def _buscar_abierto(self, path: Path) -> Optional[int]:
        path = Path(path).resolve()
        for indice, editor in enumerate(self._editores()):
            if editor.path and editor.path.resolve() == path:
                return indice
        return None

    def _nuevo_editor(self) -> LatexEditor:
        editor = LatexEditor()
        editor.setLineWrapMode(self.modo_ajuste)
        editor.cursorMoved.connect(self.cursorMoved.emit)
        editor.saveRequested.connect(self.save_document)
        editor.textChanged.connect(self._al_escribir)
        editor.document().modificationChanged.connect(
            lambda _: self._actualizar_titulos()
        )
        return editor

    def new_document(self, contenido: str = DOCUMENTO_VACIO, nombre: str = "sin título.tex") -> LatexEditor:
        editor = self._nuevo_editor()
        editor.setPlainText(contenido)
        # Recién creado desde una plantilla no cuenta como «con cambios»: si el
        # usuario abre otro archivo sin tocarlo, esta pestaña se cierra sola.
        editor.document().setModified(False)
        self._add_document_tab(editor, nombre)
        self._refrescar_esquema()
        return editor

    def _add_document_tab(self, editor: LatexEditor, nombre: str) -> None:
        """Añade la pestaña con un botón de cierre acorde con el tema."""
        indice = self.documentos.addTab(editor, nombre)

        boton = QPushButton("✕")
        boton.setObjectName("plano")
        boton.setFixedSize(18, 18)
        boton.setCursor(Qt.PointingHandCursor)
        boton.setToolTip("Cerrar")
        boton.clicked.connect(lambda: self._cerrar_desde_boton(boton))
        self.documentos.tabBar().setTabButton(indice, QTabBar.RightSide, boton)

        self.documentos.setCurrentWidget(editor)

    def _cerrar_desde_boton(self, boton: QPushButton) -> None:
        barra = self.documentos.tabBar()
        for indice in range(barra.count()):
            if barra.tabButton(indice, QTabBar.RightSide) is boton:
                self.close_document(indice)
                return

    def _cerrar_pestana_intacta(self) -> None:
        """Quita la pestaña en blanco del arranque cuando se abre un archivo."""
        editores = self._editores()
        if len(editores) != 1:
            return
        solitario = editores[0]
        if solitario.path is None and not solitario.document().isModified():
            self.documentos.removeTab(0)
            solitario.deleteLater()

    def open_file(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            QMessageBox.warning(self, "Latexinter", f"No existe:\n{path}")
            return

        if path.suffix.lower() == ".pdf":
            self.pdf.load(path, conservar_posicion=False)
            return
        if path.suffix.lower() not in EXTENSIONES_TEXTO:
            from converters import open_in_explorer

            open_in_explorer(path)
            return

        existente = self._buscar_abierto(path)
        if existente is not None:
            self.documentos.setCurrentIndex(existente)
            return

        editor = self._nuevo_editor()
        try:
            editor.load(path)
        except OSError as exc:
            QMessageBox.warning(self, "Latexinter", f"No se pudo abrir:\n{exc}")
            return

        self._cerrar_pestana_intacta()
        self._add_document_tab(editor, path.name)
        self.archivos.set_root(path.parent)

        if path.suffix.lower() == ".tex" and self.documento_principal is None:
            self.set_main_document(path)

        # Si ya hay un PDF compilado al lado, se enseña directamente.
        pdf = path.with_suffix(".pdf")
        if pdf.exists():
            self.pdf.load(pdf, conservar_posicion=False)
        self._refrescar_esquema()

    def close_document(self, indice: int) -> bool:
        widget = self.documentos.widget(indice)
        if not isinstance(widget, LatexEditor):
            return True
        if widget.document().isModified():
            respuesta = QMessageBox.question(
                self, "Latexinter",
                f"«{widget.title.rstrip(' •')}» tiene cambios sin guardar.\n¿Guardarlos?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if respuesta == QMessageBox.Cancel:
                return False
            if respuesta == QMessageBox.Save and not self.save_document(widget):
                return False
        self.documentos.removeTab(indice)
        widget.deleteLater()
        return True

    def close_all(self) -> bool:
        while self.documentos.count():
            if not self.close_document(0):
                return False
        return True

    def save_document(self, editor: Optional[LatexEditor] = None) -> bool:
        editor = editor if isinstance(editor, LatexEditor) else self.editor
        if editor is None:
            return False
        if editor.path is None:
            return self.save_document_as(editor)
        try:
            editor.save()
        except OSError as exc:
            QMessageBox.warning(self, "Latexinter", f"No se pudo guardar:\n{exc}")
            return False

        self._actualizar_titulos()
        self.statusMessage.emit(f"Guardado {editor.path.name}", 2500)
        if self.auto_compilar:
            self.compile()
        return True

    def save_document_as(self, editor: Optional[LatexEditor] = None) -> bool:
        editor = editor if isinstance(editor, LatexEditor) else self.editor
        if editor is None:
            return False
        inicio = str(editor.path or Path.home() / "documento.tex")
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar como", inicio, FILTRO_TEX)
        if not ruta:
            return False
        try:
            editor.save(Path(ruta))
        except OSError as exc:
            QMessageBox.warning(self, "Latexinter", f"No se pudo guardar:\n{exc}")
            return False

        self._actualizar_titulos()
        self.archivos.set_root(editor.path.parent)
        if self.documento_principal is None:
            self.set_main_document(editor.path)
        return True

    def _actualizar_titulos(self) -> None:
        for indice, editor in enumerate(self._editores()):
            titulo = editor.title
            if (
                self.documento_principal is not None
                and editor.path is not None
                and editor.path.resolve() == self.documento_principal.resolve()
            ):
                titulo = "★ " + titulo
            self.documentos.setTabText(indice, titulo)
        self.documentChanged.emit()

    def _cambio_de_pestana(self) -> None:
        self._refrescar_esquema()
        self.documentChanged.emit()
        editor = self.editor
        if editor is not None:
            cursor = editor.textCursor()
            self.cursorMoved.emit(cursor.blockNumber() + 1, cursor.positionInBlock() + 1)

    def _al_escribir(self) -> None:
        self._temporizador_esquema.start()
        if self.auto_compilar:
            self._temporizador_auto.start()

    def _refrescar_esquema(self) -> None:
        editor = self.editor
        self.esquema.refresh(editor.toPlainText() if editor else "")
        self.documentChanged.emit()

    def _ir_a_linea(self, numero: int) -> None:
        if self.editor is not None:
            self.editor.goto_line(numero)

    # ════════════════════════════════════════════════════════
    # Documento principal
    # ════════════════════════════════════════════════════════

    def set_main_document(self, path: Optional[Path]) -> None:
        self.documento_principal = Path(path) if path else None
        self._actualizar_titulos()
        if path:
            self.statusMessage.emit(f"Documento principal: {Path(path).name}", 3000)

    def _documento_a_compilar(self) -> Optional[LatexEditor]:
        """
        Al editar un capítulo suelto lo que hay que compilar es el maestro, el
        documento principal. Pero si la pestaña activa es un documento
        completo (tiene su \\documentclass), se compila ella: si no, con dos
        documentos independientes abiertos F5 compilaría siempre el primero.
        """
        editor = self.editor
        es_tex = editor is not None and (
            editor.path is None or editor.path.suffix.lower() == ".tex"
        )
        if es_tex and _RE_DOCUMENTCLASS.search(editor.toPlainText()):
            return editor
        if self.documento_principal is not None:
            indice = self._buscar_abierto(self.documento_principal)
            if indice is not None:
                return self._editores()[indice]
        return editor if es_tex else None

    # ════════════════════════════════════════════════════════
    # Compilación
    # ════════════════════════════════════════════════════════

    def compile(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._pendiente_recompilar = True
            return

        editor = self._documento_a_compilar()
        if editor is None:
            self.statusMessage.emit("No hay ningún .tex que compilar.", 4000)
            return
        if editor.path is None and not self.save_document_as(editor):
            return

        # Se guardan todos: el principal puede incluir a los demás.
        for abierto in self._editores():
            if abierto.path is not None and abierto.document().isModified():
                try:
                    abierto.save()
                except OSError:
                    pass
        self._actualizar_titulos()

        self.registro.clear()
        self.compileStateChanged.emit("compilando")
        self.statusMessage.emit(f"Compilando {editor.path.name}…", 0)

        self.worker = CompileWorker(editor.path, self.engine, self.usar_chktex)
        self.worker.message.connect(self.registro.appendPlainText)
        self.worker.finished_ok.connect(self._compilacion_ok)
        self.worker.failed.connect(self._compilacion_fallida)
        self.worker.finished.connect(self._compilacion_terminada)
        self.worker.start()

    def _compilacion_ok(self, resultado, problemas) -> None:
        self.pdf.load(resultado.output, conservar_posicion=True)
        con_errores = self._mostrar_problemas(problemas)
        for aviso in resultado.warnings:
            self.registro.appendPlainText("⚠ " + aviso)

        # LaTeX genera el PDF aunque encuentre errores; conviene decirlo.
        self.compileStateChanged.emit("con_errores" if con_errores else "ok")
        paginas = resultado.stats.get("paginas")
        self.statusMessage.emit(
            f"Compilado: {resultado.output.name}"
            + (f" ({paginas} páginas)" if paginas else "")
            + (" — con errores en el documento" if con_errores else ""),
            5000 if con_errores else 4000,
        )

    def _compilacion_fallida(self, mensaje: str, problemas) -> None:
        self.registro.appendPlainText("")
        self.registro.appendPlainText("✗ " + mensaje)
        self._mostrar_problemas(problemas)
        self.inferior.setCurrentWidget(self.problemas)
        self.compileStateChanged.emit("error")
        self.statusMessage.emit("La compilación falló. Mira el panel de problemas.", 6000)

    def _compilacion_terminada(self) -> None:
        if self._pendiente_recompilar:
            self._pendiente_recompilar = False
            QTimer.singleShot(100, self.compile)

    def _mostrar_problemas(self, problemas: list[Problem]) -> bool:
        """Rellena el panel de problemas. Devuelve si hay errores de verdad."""
        problemas = list(problemas or [])
        self.problemas.set_problems(problemas)
        hay_errores = any(p.severity == "error" for p in problemas)
        if hay_errores:
            self.inferior.setCurrentWidget(self.problemas)
        return hay_errores

    def _ir_a_problema(self, archivo, linea: int) -> None:
        if archivo is not None and Path(archivo).exists():
            self.open_file(Path(archivo))
        if self.editor is not None:
            self.editor.goto_line(linea, marcar=True)

    def _auto_compilar(self) -> None:
        if not self.auto_compilar:
            return
        editor = self._documento_a_compilar()
        if editor is None or editor.path is None:
            return
        self.compile()

    def set_auto_compile(self, activo: bool) -> None:
        self.auto_compilar = activo
        if not activo:
            self._temporizador_auto.stop()

    def set_engine(self, motor: str) -> None:
        self.engine = motor

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def stop(self) -> None:
        if self.is_busy():
            self.worker.terminate()
            self.worker.wait(3000)
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            self._ocr_worker.terminate()
            self._ocr_worker.wait(3000)

    # ════════════════════════════════════════════════════════
    # SyncTeX
    # ════════════════════════════════════════════════════════

    def sync_a_pdf(self) -> None:
        """Del código al PDF: enseña dónde acabó impresa la línea actual."""
        editor = self.editor
        if editor is None or editor.path is None or self.pdf.path is None:
            self.statusMessage.emit("Compila el documento antes de sincronizar.", 4000)
            return

        linea = editor.textCursor().blockNumber() + 1
        punto = forward_search(editor.path, linea, self.pdf.path)
        if punto is None:
            self.statusMessage.emit(
                "SyncTeX no encontró esa línea en el PDF. ¿Está recién compilado?", 5000
            )
            return
        self.pdf.highlight(punto.page, punto.x, punto.y, punto.width, punto.height)
        self.statusMessage.emit(f"Línea {linea} → página {punto.page}", 3000)

    def _sync_desde_pdf(self, pagina: int, x: float, y: float) -> None:
        """Del PDF al código: doble clic en el PDF y salta el editor."""
        if self.pdf.path is None:
            return
        destino = inverse_search(self.pdf.path, pagina, x, y)
        if destino is None:
            self.statusMessage.emit("SyncTeX no supo de dónde viene ese punto.", 4000)
            return

        archivo, linea = destino
        if archivo.exists():
            self.open_file(archivo)
        if self.editor is not None:
            self.editor.goto_line(linea, marcar=True)
        self.statusMessage.emit(f"Página {pagina} → línea {linea}", 3000)

    # ════════════════════════════════════════════════════════
    # Buscar y reemplazar
    # ════════════════════════════════════════════════════════

    def show_find(self, con_reemplazo: bool = False) -> None:
        editor = self.editor
        seleccion = ""
        if editor is not None and editor.textCursor().hasSelection():
            seleccion = editor.textCursor().selectedText().replace("\u2029", " ")[:80]
        self.barra_busqueda.mostrar(seleccion, con_reemplazo=con_reemplazo)
        self._buscar(
            self.barra_busqueda.campo.text(), False,
            self.barra_busqueda.mayusculas.isChecked(),
            self.barra_busqueda.regex.isChecked(),
        )

    def _cerrar_busqueda(self) -> None:
        if self.editor is not None:
            self.editor.clear_match_highlight()
            self.editor.setFocus()

    def _compilar_patron(self, texto: str, mayusculas: bool, regex: bool):
        if not texto:
            return None
        banderas = 0 if mayusculas else re.IGNORECASE
        try:
            return re.compile(texto if regex else re.escape(texto), banderas)
        except re.error:
            return None

    def _buscar(self, texto: str, atras: bool, mayusculas: bool, regex: bool) -> None:
        editor = self.editor
        if editor is None:
            return

        patron = self._compilar_patron(texto, mayusculas, regex)
        if patron is None:
            editor.clear_match_highlight()
            self.barra_busqueda.set_resultado(0, 0)
            return

        contenido = editor.toPlainText()
        self._resultados_busqueda = [
            (m.start(), m.end() - m.start()) for m in patron.finditer(contenido) if m.end() > m.start()
        ]
        editor.highlight_matches(self._resultados_busqueda)

        if not self._resultados_busqueda:
            self.barra_busqueda.set_resultado(0, 0)
            return

        posicion = editor.textCursor().selectionStart()
        if atras:
            candidatos = [i for i, (p, _) in enumerate(self._resultados_busqueda) if p < posicion]
            self._indice_busqueda = candidatos[-1] if candidatos else len(self._resultados_busqueda) - 1
        else:
            candidatos = [i for i, (p, _) in enumerate(self._resultados_busqueda) if p >= posicion]
            self._indice_busqueda = candidatos[0] if candidatos else 0

        self._saltar_a_resultado()

    def _saltar_a_resultado(self) -> None:
        editor = self.editor
        if editor is None or not self._resultados_busqueda:
            return
        inicio, longitud = self._resultados_busqueda[self._indice_busqueda]
        cursor = editor.textCursor()
        cursor.setPosition(inicio)
        cursor.setPosition(inicio + longitud, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.centerCursor()
        self.barra_busqueda.set_resultado(
            self._indice_busqueda + 1, len(self._resultados_busqueda)
        )

    def find_next(self, atras: bool = False) -> None:
        if not self._resultados_busqueda:
            self.show_find()
            return
        paso = -1 if atras else 1
        self._indice_busqueda = (
            self._indice_busqueda + paso
        ) % len(self._resultados_busqueda)
        self._saltar_a_resultado()

    def _reemplazar(self, buscar: str, poner: str, todo: bool) -> None:
        editor = self.editor
        if editor is None:
            return
        patron = self._compilar_patron(
            buscar,
            self.barra_busqueda.mayusculas.isChecked(),
            self.barra_busqueda.regex.isChecked(),
        )
        if patron is None:
            return

        regex = self.barra_busqueda.regex.isChecked()
        if todo:
            contenido = editor.toPlainText()
            try:
                # Sin expresión regular el reemplazo va literal: con una
                # función, re no interpreta las «\» de los comandos de LaTeX.
                nuevo, cuantos = patron.subn(
                    poner if regex else (lambda _m: poner), contenido
                )
            except re.error as exc:
                self.statusMessage.emit(f"Reemplazo no válido: {exc}", 5000)
                return
            if cuantos:
                cursor = editor.textCursor()
                cursor.beginEditBlock()
                cursor.select(QTextCursor.Document)
                cursor.insertText(nuevo)
                cursor.endEditBlock()
            self.statusMessage.emit(f"{cuantos} sustituciones", 3000)
            self._buscar(buscar, False, self.barra_busqueda.mayusculas.isChecked(), regex)
            return

        cursor = editor.textCursor()
        coincidencia = (
            patron.fullmatch(cursor.selectedText().replace("\u2029", "\n"))
            if cursor.hasSelection() else None
        )
        if coincidencia:
            try:
                cursor.insertText(coincidencia.expand(poner) if regex else poner)
            except re.error as exc:
                self.statusMessage.emit(f"Reemplazo no v\u00e1lido: {exc}", 5000)
                return
        # Las posiciones guardadas ya no valen tras editar: se vuelve a buscar.
        self._buscar(buscar, False, self.barra_busqueda.mayusculas.isChecked(), regex)

    # ════════════════════════════════════════════════════════
    # Fórmula desde una imagen
    # ════════════════════════════════════════════════════════

    def insert_formula_from_image(self, path: Optional[Path] = None) -> None:
        """
        Convierte una imagen de una fórmula en LaTeX y la inserta donde esté
        el cursor. Si no se da un archivo, se mira primero el portapapeles:
        así se puede recortar una fórmula de la pantalla, copiarla y pegarla ya
        traducida.
        """
        editor = self.editor
        if editor is None:
            return
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            self.statusMessage.emit("Ya hay una fórmula en proceso…", 3000)
            return

        imagen = None
        origen = ""

        if path is None:
            imagen, origen = self._imagen_del_portapapeles()

        if imagen is None:
            if path is None:
                path, _ = QFileDialog.getOpenFileName(
                    self, "Imagen de la fórmula",
                    str(editor.path.parent if editor.path else Path.home()),
                    "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;"
                    "Todos los archivos (*)",
                )
                if not path:
                    return
            try:
                from converters import mathocr

                imagen = mathocr.load_image(path)
                origen = Path(path).name
            except Exception as exc:
                QMessageBox.warning(self, "Latexinter", f"No se pudo abrir la imagen:\n{exc}")
                return

        self.statusMessage.emit(f"Reconociendo la fórmula de {origen}…", 0)
        self._ocr_worker = OcrWorker(imagen)
        self._ocr_worker.message.connect(self.registro.appendPlainText)
        self._ocr_worker.recognized.connect(self._insertar_formula)
        self._ocr_worker.failed.connect(self._ocr_fallido)
        self._ocr_worker.start()

    def _imagen_del_portapapeles(self):
        """Imagen del portapapeles convertida a PIL, si la hay."""
        from PyQt5.QtWidgets import QApplication

        portapapeles = QApplication.clipboard()
        qimagen = portapapeles.image()
        if qimagen.isNull():
            return None, ""

        try:
            from PIL import Image
        except ImportError:
            return None, ""

        import io

        from PyQt5.QtCore import QBuffer, QByteArray

        datos = QByteArray()
        buffer = QBuffer(datos)
        buffer.open(QBuffer.WriteOnly)
        qimagen.save(buffer, "PNG")
        buffer.close()
        return Image.open(io.BytesIO(bytes(datos))).convert("RGB"), "el portapapeles"

    def _insertar_formula(self, latex: str) -> None:
        editor = self.editor
        if editor is None:
            return
        # Si la fórmula ocupa lo suyo, se inserta destacada; si es corta, en línea.
        if len(latex) > 45 or any(
            marca in latex for marca in ("\\frac", "\\begin", "\\sum", "\\int")
        ):
            sangria = editor.textCursor().block().text()
            sangria = sangria[: len(sangria) - len(sangria.lstrip())]
            texto = (
                f"\n{sangria}\\begin{{equation}}\n"
                f"{sangria}    {latex}\n"
                f"{sangria}\\end{{equation}}\n"
            )
        else:
            texto = f"${latex}$"
        editor.insertPlainText(texto)
        editor.setFocus()
        self.statusMessage.emit("Fórmula insertada", 4000)

    def _ocr_fallido(self, mensaje: str) -> None:
        self.statusMessage.emit("No se pudo reconocer la fórmula", 5000)
        QMessageBox.information(self, "Latexinter", mensaje)

    # ════════════════════════════════════════════════════════
    # Recuentos
    # ════════════════════════════════════════════════════════

    def quick_word_count(self) -> int:
        editor = self.editor
        return rough_word_count(editor.toPlainText()) if editor else 0

    def detailed_word_count(self) -> Optional[dict]:
        editor = self.editor
        if editor is None or editor.path is None:
            return None
        return word_count(editor.path)
