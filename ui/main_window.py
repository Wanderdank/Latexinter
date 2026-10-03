"""
main_window.py - La ventana de Latexinter.

Dos modos en una sola ventana: el editor de LaTeX y el conversor entre
formatos. El menú, la barra de herramientas y la barra de estado viven aquí,
y se limitan a llamar a los métodos de la página que toque.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QSettings, QSize, QStandardPaths, Qt, QTimer
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from converters import SUPPORTED_EXTENSIONS, dependency_report
from converters.textfiles import RecoveryStore
from converters.tools import synctex_available

from . import theme
from .converter_panel import ConverterPanel
from .editor_page import EditorPage
from .templates import TEMPLATES, TEMPLATES_POR_CLAVE

APP_NAME = "Latexinter"
ORGANIZACION = "Latexinter"
MAX_RECIENTES = 8

ATAJOS = """
<table cellspacing="6">
<tr><td><b>Ctrl+N</b></td><td>Documento nuevo</td>
    <td><b>Ctrl+F</b></td><td>Buscar</td></tr>
<tr><td><b>Ctrl+O</b></td><td>Abrir</td>
    <td><b>Ctrl+H</b></td><td>Buscar y reemplazar</td></tr>
<tr><td><b>Ctrl+S</b></td><td>Guardar</td>
    <td><b>F3</b></td><td>Buscar siguiente</td></tr>
<tr><td><b>F5</b></td><td>Compilar</td>
    <td><b>Ctrl+/</b></td><td>Comentar o descomentar</td></tr>
<tr><td><b>F7</b></td><td>Ir del código al PDF</td>
    <td><b>Ctrl+B</b></td><td>Negrita</td></tr>
<tr><td><b>Doble clic en el PDF</b></td><td>Ir del PDF al código</td>
    <td><b>Ctrl+I</b></td><td>Cursiva</td></tr>
<tr><td><b>Ctrl+Espacio</b></td><td>Autocompletar</td>
    <td><b>Ctrl+M</b></td><td>Modo matemático</td></tr>
<tr><td><b>Tab</b> / <b>Mayús+Tab</b></td><td>Sangrar</td>
    <td><b>Ctrl+D</b></td><td>Duplicar la línea</td></tr>
<tr><td><b>Mayús+F5</b></td><td>Detener la compilación</td>
    <td></td><td></td></tr>
</table>
"""


class TemplateDialog(QDialog):
    """Elegir con qué documento empezar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Documento nuevo")
        self.setMinimumSize(QSize(460, 380))
        self.elegida: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        titulo = QLabel("Elige una plantilla")
        titulo.setObjectName("seccion")
        layout.addWidget(titulo)

        self.lista = QListWidget()
        for plantilla in TEMPLATES:
            item = QListWidgetItem(f"{plantilla.name}\n{plantilla.description}")
            item.setData(Qt.UserRole, plantilla.key)
            self.lista.addItem(item)
        vacio = QListWidgetItem("Documento en blanco\nSolo el preámbulo mínimo en español.")
        vacio.setData(Qt.UserRole, "")
        self.lista.addItem(vacio)
        self.lista.setCurrentRow(0)
        self.lista.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.lista, 1)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Crear")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def accept(self) -> None:
        item = self.lista.currentItem()
        self.elegida = item.data(Qt.UserRole) if item else None
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self, scratch_dir: Path):
        super().__init__()
        self.settings = QSettings(ORGANIZACION, APP_NAME)
        self.scratch_dir = Path(scratch_dir)

        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1000, 640))
        self.setAcceptDrops(True)

        self.recuperacion = self._abrir_recuperacion()

        self.paginas = QTabWidget()
        self.editor_page = EditorPage(self.recuperacion)
        self.converter_page = ConverterPanel(self.scratch_dir)
        self.converter_page.documentReady.connect(self._abrir_desde_conversor)

        self.paginas.addTab(self.editor_page, "  Editor  ")
        self.paginas.addTab(self.converter_page, "  Conversor  ")
        self.paginas.currentChanged.connect(self._cambio_de_pagina)
        self.setCentralWidget(self.paginas)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.editor_page.statusMessage.connect(self._mensaje)
        self.editor_page.cursorMoved.connect(self._posicion)
        self.editor_page.documentChanged.connect(self._actualizar_titulo)
        self.editor_page.compileStateChanged.connect(self._estado_compilacion)

        self._contador = QTimer(self)
        self._contador.setSingleShot(True)
        self._contador.setInterval(1200)
        self._contador.timeout.connect(self._actualizar_palabras)
        self.editor_page.documentChanged.connect(lambda: self._contador.start())

        self._restaurar_ajustes()
        self._comprobar_dependencias()
        if self.editor_page.documentos.count() == 0:
            self.editor_page.new_document()
        self._actualizar_titulo()
        # Después de mostrarse la ventana, para que el aviso salga encima.
        QTimer.singleShot(0, self._ofrecer_recuperacion)

    # ════════════════════════════════════════════════════════
    # Acciones
    # ════════════════════════════════════════════════════════

    def _accion(self, texto, atajo=None, tooltip="", triggered=None,
                checkable=False, checked=False) -> QAction:
        accion = QAction(texto, self)
        if atajo:
            accion.setShortcut(atajo)
        if tooltip:
            accion.setToolTip(tooltip)
            accion.setStatusTip(tooltip)
        if triggered is not None:
            accion.triggered.connect(triggered)
        accion.setCheckable(checkable)
        accion.setChecked(checked)
        return accion

    def _build_actions(self) -> None:
        editor = self.editor_page

        self.a_nuevo = self._accion("Nuevo…", "Ctrl+N", "Crear un documento desde una plantilla", self.nuevo_documento)
        self.a_abrir = self._accion("Abrir…", "Ctrl+O", "Abrir un .tex", self.abrir_documento)
        self.a_abrir_carpeta = self._accion("Abrir carpeta…", "Ctrl+Shift+O", "Ver los archivos de una carpeta", self.abrir_carpeta)
        self.a_guardar = self._accion("Guardar", "Ctrl+S", "Guardar el documento", lambda: editor.save_document())
        self.a_guardar_como = self._accion("Guardar como…", "Ctrl+Shift+S", "", lambda: editor.save_document_as())
        self.a_cerrar = self._accion("Cerrar documento", "Ctrl+W", "", lambda: editor.close_document(editor.documentos.currentIndex()))
        self.a_salir = self._accion("Salir", "Ctrl+Q", "", self.close)

        self.a_deshacer = self._accion("Deshacer", "Ctrl+Z", "", lambda: self._al_editor("undo"))
        self.a_rehacer = self._accion("Rehacer", "Ctrl+Y", "", lambda: self._al_editor("redo"))
        self.a_buscar = self._accion("Buscar…", "Ctrl+F", "", lambda: editor.show_find(False))
        self.a_reemplazar = self._accion("Buscar y reemplazar…", "Ctrl+H", "", lambda: editor.show_find(True))
        self.a_siguiente = self._accion("Buscar siguiente", "F3", "", lambda: editor.find_next(False))
        self.a_anterior = self._accion("Buscar anterior", "Shift+F3", "", lambda: editor.find_next(True))
        self.a_comentar = self._accion("Comentar o descomentar", "Ctrl+7", "", lambda: self._al_editor("toggle_comment"))
        self.a_ajustar_lineas = self._accion(
            "Ajustar las líneas a la ventana", None,
            "Parte las líneas largas en vez de desplazarlas",
            self._alternar_ajuste, checkable=True, checked=True,
        )

        self.a_compilar = self._accion("Compilar", "F5", "Compilar el documento principal", editor.compile)
        self.a_detener = self._accion("Detener la compilación", "Shift+F5", "", editor.cancel_compile)
        self.a_detener.setEnabled(False)
        self.a_auto = self._accion(
            "Compilar al escribir", None,
            "Recompila sola tras dos segundos sin teclear",
            self._alternar_auto, checkable=True,
        )
        self.a_sync = self._accion("Ir del código al PDF", "F7", "Enseña en el PDF dónde está el cursor", editor.sync_a_pdf)
        self.a_principal = self._accion("Marcar como documento principal", None, "El que se compila aunque estés editando otro", self._marcar_principal)
        self.a_limpiar = self._accion("Limpiar archivos auxiliares", None, "", self._limpiar_auxiliares)

        self.a_formula_imagen = self._accion(
            "Fórmula desde una imagen…", "Ctrl+Shift+V",
            "Convierte en LaTeX una fórmula copiada al portapapeles o guardada "
            "en un archivo de imagen",
            lambda: editor.insert_formula_from_image(),
        )
        self.a_palabras = self._accion("Contar palabras", None, "", self._contar_palabras)
        self.a_chktex = self._accion(
            "Revisar el estilo con chktex", None,
            "Añade los avisos de chktex al panel de problemas",
            self._alternar_chktex, checkable=True, checked=True,
        )
        self.a_atajos = self._accion("Atajos de teclado", "F1", "", self._mostrar_atajos)
        self.a_dependencias = self._accion("Comprobar dependencias", None, "", self._mostrar_dependencias)

        self.a_ir_conversor = self._accion("Ir al conversor", "Ctrl+Shift+C", "", lambda: self.paginas.setCurrentIndex(1))
        self.a_ir_editor = self._accion("Ir al editor", "Ctrl+Shift+E", "", lambda: self.paginas.setCurrentIndex(0))

    def _al_editor(self, metodo: str) -> None:
        editor = self.editor_page.editor
        if editor is not None:
            getattr(editor, metodo)()

    # ════════════════════════════════════════════════════════
    # Menús y barras
    # ════════════════════════════════════════════════════════

    def _build_menus(self) -> None:
        barra = self.menuBar()

        archivo = barra.addMenu("&Archivo")
        archivo.addAction(self.a_nuevo)
        archivo.addAction(self.a_abrir)
        archivo.addAction(self.a_abrir_carpeta)
        archivo.addSeparator()
        self.menu_recientes = archivo.addMenu("Documentos recientes")
        archivo.addSeparator()
        archivo.addAction(self.a_guardar)
        archivo.addAction(self.a_guardar_como)
        archivo.addAction(self.a_cerrar)
        archivo.addSeparator()
        archivo.addAction(self.a_salir)

        edicion = barra.addMenu("&Edición")
        for accion in (self.a_deshacer, self.a_rehacer, None, self.a_buscar,
                       self.a_reemplazar, self.a_siguiente, self.a_anterior,
                       None, self.a_comentar, self.a_ajustar_lineas):
            edicion.addSeparator() if accion is None else edicion.addAction(accion)

        compilar = barra.addMenu("&Compilar")
        compilar.addAction(self.a_compilar)
        compilar.addAction(self.a_detener)
        compilar.addAction(self.a_auto)
        compilar.addAction(self.a_sync)
        compilar.addSeparator()
        compilar.addAction(self.a_principal)

        menu_motor = compilar.addMenu("Motor")
        self.grupo_motor = QActionGroup(self)
        self.grupo_motor.setExclusive(True)
        for nombre in ("pdflatex", "xelatex", "lualatex"):
            accion = self._accion(nombre, None, "", checkable=True)
            accion.setChecked(nombre == "pdflatex")
            accion.triggered.connect(lambda _, m=nombre: self._elegir_motor(m))
            self.grupo_motor.addAction(accion)
            menu_motor.addAction(accion)

        compilar.addSeparator()
        compilar.addAction(self.a_limpiar)

        herramientas = barra.addMenu("&Herramientas")
        herramientas.addAction(self.a_formula_imagen)
        herramientas.addSeparator()
        herramientas.addAction(self.a_palabras)
        herramientas.addAction(self.a_chktex)
        herramientas.addSeparator()
        herramientas.addAction(self.a_ir_conversor)
        herramientas.addAction(self.a_ir_editor)

        ayuda = barra.addMenu("A&yuda")
        ayuda.addAction(self.a_atajos)
        ayuda.addAction(self.a_dependencias)

    def _build_toolbar(self) -> None:
        barra = self.addToolBar("Principal")
        barra.setMovable(False)
        barra.setIconSize(QSize(16, 16))

        barra.addAction(self.a_nuevo)
        barra.addAction(self.a_abrir)
        barra.addAction(self.a_guardar)
        barra.addSeparator()
        barra.addAction(self.a_compilar)
        barra.addAction(self.a_auto)
        barra.addAction(self.a_sync)
        barra.addSeparator()

        self.selector_motor = QComboBox()
        self.selector_motor.addItems(["pdflatex", "xelatex", "lualatex"])
        self.selector_motor.setFixedWidth(110)
        self.selector_motor.currentTextChanged.connect(self._elegir_motor)
        barra.addWidget(self.selector_motor)

        barra.addSeparator()
        barra.addAction(self.a_buscar)

        espaciador = QWidget()
        espaciador.setSizePolicy(
            espaciador.sizePolicy().Expanding, espaciador.sizePolicy().Preferred
        )
        barra.addWidget(espaciador)

        self.indicador_dependencias = QLabel()
        self.indicador_dependencias.setObjectName("estado")
        barra.addWidget(self.indicador_dependencias)

    def _build_statusbar(self) -> None:
        barra = self.statusBar()

        self.estado_compilacion = QLabel("Listo")
        self.estado_compilacion.setObjectName("estado")
        self.etiqueta_posicion = QLabel("Ln 1, Col 1")
        self.etiqueta_posicion.setObjectName("estado")
        self.etiqueta_palabras = QLabel("")
        self.etiqueta_palabras.setObjectName("estado")

        barra.addPermanentWidget(self.etiqueta_palabras)
        barra.addPermanentWidget(self.etiqueta_posicion)
        barra.addPermanentWidget(self.estado_compilacion)

    # ════════════════════════════════════════════════════════
    # Acciones concretas
    # ════════════════════════════════════════════════════════

    def nuevo_documento(self) -> None:
        self.paginas.setCurrentIndex(0)
        dialogo = TemplateDialog(self)
        if dialogo.exec_() != QDialog.Accepted:
            return
        clave = dialogo.elegida
        if clave:
            plantilla = TEMPLATES_POR_CLAVE[clave]
            self.editor_page.new_document(plantilla.content, plantilla.filename)
        else:
            self.editor_page.new_document()

    def abrir_documento(self, ruta: Optional[str] = None) -> None:
        if not ruta:
            ruta, _ = QFileDialog.getOpenFileName(
                self, "Abrir documento", self._carpeta_inicial(),
                "LaTeX (*.tex);;Bibliografía (*.bib);;Todos los archivos (*)",
            )
        if not ruta:
            return
        self.paginas.setCurrentIndex(0)
        self.editor_page.open_file(Path(ruta))
        self._anadir_reciente(Path(ruta))

    def abrir_carpeta(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(
            self, "Abrir carpeta", self._carpeta_inicial()
        )
        if carpeta:
            self.paginas.setCurrentIndex(0)
            self.editor_page.archivos.set_root(Path(carpeta))
            self.editor_page.lateral.setCurrentWidget(self.editor_page.archivos)

    def _carpeta_inicial(self) -> str:
        editor = self.editor_page.editor
        if editor is not None and editor.path is not None:
            return str(editor.path.parent)
        return str(Path.home())

    def _marcar_principal(self) -> None:
        editor = self.editor_page.editor
        if editor is None or editor.path is None:
            QMessageBox.information(
                self, APP_NAME, "Guarda el documento antes de marcarlo como principal."
            )
            return
        self.editor_page.set_main_document(editor.path)

    def _elegir_motor(self, motor: str) -> None:
        self.editor_page.set_engine(motor)
        if self.selector_motor.currentText() != motor:
            self.selector_motor.blockSignals(True)
            self.selector_motor.setCurrentText(motor)
            self.selector_motor.blockSignals(False)
        for accion in self.grupo_motor.actions():
            accion.setChecked(accion.text() == motor)
        self.settings.setValue("motor", motor)

    def _alternar_auto(self, activo: bool) -> None:
        self.editor_page.set_auto_compile(activo)
        self.settings.setValue("auto_compilar", activo)
        self._mensaje(
            "Compilación automática activada" if activo
            else "Compilación automática desactivada",
            3000,
        )

    def _alternar_ajuste(self, activo: bool) -> None:
        from PyQt5.QtWidgets import QPlainTextEdit

        modo = QPlainTextEdit.WidgetWidth if activo else QPlainTextEdit.NoWrap
        self.editor_page.modo_ajuste = modo         # para las pestañas futuras
        for editor in self.editor_page._editores():
            editor.setLineWrapMode(modo)
        self.settings.setValue("ajustar_lineas", activo)

    def _alternar_chktex(self, activo: bool) -> None:
        self.editor_page.usar_chktex = activo
        self.settings.setValue("chktex", activo)

    def _limpiar_auxiliares(self) -> None:
        from converters.latex_to_pdf import clean_aux_files

        editor = self.editor_page._documento_a_compilar()
        if editor is None or editor.path is None:
            self._mensaje("No hay ningún documento compilado.", 3000)
            return
        borrados = clean_aux_files(editor.path)
        self._mensaje(f"{borrados} archivos auxiliares eliminados", 3000)

    def _contar_palabras(self) -> None:
        detalle = self.editor_page.detailed_word_count()
        if detalle is None:
            propio = self.editor_page.quick_word_count()
            QMessageBox.information(
                self, APP_NAME,
                f"<b>{propio}</b> palabras.<br><br>"
                "<span style='color:#8b8bab'>Se han descartado el preámbulo, "
                "los comentarios, las fórmulas y el código.<br>"
                "Para usar texcount (el contador de TeX) hace falta tener Perl "
                "instalado.</span>",
            )
            return

        lineas = [f"<b>{detalle['total']}</b> palabras en total"]
        for clave, nombre in (("texto", "en el texto"), ("titulos", "en los títulos"),
                              ("leyendas", "en los pies de figura")):
            if clave in detalle:
                lineas.append(f"{detalle[clave]} {nombre}")
        QMessageBox.information(self, APP_NAME, "<br>".join(lineas))

    def _mostrar_atajos(self) -> None:
        QMessageBox.information(self, "Atajos de teclado", ATAJOS)

    def _comprobar_dependencias(self) -> None:
        estado = dependency_report()
        etiquetas = {"pandoc": "pandoc", "pdflatex": "LaTeX", "pymupdf4llm": "PyMuPDF"}
        partes, faltan = [], []
        for clave, nombre in etiquetas.items():
            if estado.get(clave):
                partes.append(f"✓ {nombre}")
            else:
                partes.append(f"✗ {nombre}")
                faltan.append(nombre)
        if not synctex_available():
            partes.append("✗ SyncTeX")

        self.indicador_dependencias.setText("   ".join(partes) + "   ")
        color = theme.AMBAR if faltan else theme.VERDE
        self.indicador_dependencias.setStyleSheet(f"color: {color}; padding-right: 8px;")
        self.a_sync.setEnabled(synctex_available())

    def _mostrar_dependencias(self) -> None:
        estado = dependency_report()
        filas = []
        for clave, nombre in (
            ("pandoc", "pandoc — conversiones con Word"),
            ("pdflatex", "pdflatex — compilar LaTeX"),
            ("bibtex", "bibtex — bibliografías"),
            ("pymupdf4llm", "pymupdf4llm — leer PDF"),
            ("fitz", "PyMuPDF — leer PDF"),
        ):
            ruta = estado.get(clave)
            filas.append(f"{'✓' if ruta else '✗'} {nombre}")
        filas.append(f"{'✓' if synctex_available() else '✗'} synctex — saltar entre código y PDF")
        filas.append("")
        filas.append("Si falta algo:")
        filas.append("winget install --id JohnMacFarlane.Pandoc")
        filas.append("winget install --id MiKTeX.MiKTeX")
        filas.append("pip install -r requirements.txt")
        QMessageBox.information(self, "Dependencias", "\n".join(filas))

    def _abrir_desde_conversor(self, path: Path) -> None:
        self.paginas.setCurrentIndex(0)
        self.editor_page.open_file(Path(path))
        self._anadir_reciente(Path(path))

    # ════════════════════════════════════════════════════════
    # Estado
    # ════════════════════════════════════════════════════════

    def _mensaje(self, texto: str, milisegundos: int = 3000) -> None:
        self.statusBar().showMessage(texto, milisegundos)

    def _posicion(self, linea: int, columna: int) -> None:
        self.etiqueta_posicion.setText(f"Ln {linea}, Col {columna}")

    def _estado_compilacion(self, estado: str) -> None:
        textos = {
            "compilando": ("Compilando…", theme.AMBAR),
            "ok": ("Compilado", theme.VERDE),
            "con_errores": ("Compilado con errores", theme.AMBAR),
            "error": ("No compila", theme.ROJO),
            "inactivo": ("Listo", theme.TEXTO_SUAVE),
        }
        texto, color = textos.get(estado, ("Listo", theme.TEXTO_SUAVE))
        self.estado_compilacion.setText(texto)
        self.estado_compilacion.setStyleSheet(f"color: {color}; padding: 0 8px;")
        self.a_compilar.setEnabled(estado != "compilando")
        self.a_detener.setEnabled(estado == "compilando")

    def _actualizar_palabras(self) -> None:
        total = self.editor_page.quick_word_count()
        self.etiqueta_palabras.setText(f"{total} palabras" if total else "")

    def _actualizar_titulo(self) -> None:
        editor = self.editor_page.editor
        if editor is None:
            self.setWindowTitle(APP_NAME)
            return
        nombre = editor.path.name if editor.path else "sin título"
        marca = " •" if editor.document().isModified() else ""
        self.setWindowTitle(f"{nombre}{marca} — {APP_NAME}")

    def _cambio_de_pagina(self, indice: int) -> None:
        en_editor = indice == 0
        for accion in (self.a_guardar, self.a_guardar_como, self.a_cerrar,
                       self.a_compilar, self.a_auto, self.a_sync,
                       self.a_buscar, self.a_reemplazar, self.a_principal):
            accion.setEnabled(en_editor)
        if en_editor:
            self.a_sync.setEnabled(synctex_available())
            self._actualizar_titulo()
        else:
            self.setWindowTitle(f"Conversor — {APP_NAME}")

    # ════════════════════════════════════════════════════════
    # Recuperación tras un cierre inesperado
    # ════════════════════════════════════════════════════════

    def _abrir_recuperacion(self) -> Optional[RecoveryStore]:
        carpeta = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not carpeta:
            return None
        try:
            return RecoveryStore(Path(carpeta) / "recuperacion")
        except OSError:
            return None             # sin copias, pero la aplicación funciona

    def _ofrecer_recuperacion(self) -> None:
        if self.recuperacion is None:
            return
        documentos = self.recuperacion.orphans()
        if not documentos:
            return

        nombres = "\n".join(
            f"  · {d.path if d.path else 'Documento sin título'}" for d in documentos
        )
        caja = QMessageBox(self)
        caja.setWindowTitle(APP_NAME)
        caja.setIcon(QMessageBox.Question)
        caja.setText(
            f"{APP_NAME} se cerró sin que se guardaran estos cambios:\n\n"
            f"{nombres}\n\n¿Recuperarlos?"
        )
        recuperar = caja.addButton("Recuperar", QMessageBox.AcceptRole)
        descartar = caja.addButton("Descartar", QMessageBox.DestructiveRole)
        caja.addButton("Ahora no", QMessageBox.RejectRole)
        caja.setDefaultButton(recuperar)
        caja.exec_()

        if caja.clickedButton() is recuperar:
            self.paginas.setCurrentIndex(0)
            self.editor_page.restore(documentos)
            self.recuperacion.forget(documentos)
            self._mensaje(f"{len(documentos)} documentos recuperados. Guárdalos con Ctrl+S.", 6000)
        elif caja.clickedButton() is descartar:
            self.recuperacion.forget(documentos)

    # ════════════════════════════════════════════════════════
    # Recientes y ajustes
    # ════════════════════════════════════════════════════════

    def _recientes(self) -> list[str]:
        return list(self.settings.value("recientes", [], type=list) or [])

    def _anadir_reciente(self, path: Path) -> None:
        ruta = str(Path(path).resolve())
        recientes = [r for r in self._recientes() if r != ruta]
        recientes.insert(0, ruta)
        self.settings.setValue("recientes", recientes[:MAX_RECIENTES])
        self._reconstruir_recientes()

    def _reconstruir_recientes(self) -> None:
        self.menu_recientes.clear()
        recientes = [r for r in self._recientes() if Path(r).exists()]
        if not recientes:
            vacio = self.menu_recientes.addAction("(ninguno)")
            vacio.setEnabled(False)
            return
        for ruta in recientes:
            accion = self.menu_recientes.addAction(Path(ruta).name)
            accion.setToolTip(ruta)
            accion.triggered.connect(lambda _, r=ruta: self.abrir_documento(r))
        self.menu_recientes.addSeparator()
        self.menu_recientes.addAction("Vaciar la lista", self._vaciar_recientes)

    def _vaciar_recientes(self) -> None:
        self.settings.setValue("recientes", [])
        self._reconstruir_recientes()

    def _restaurar_ajustes(self) -> None:
        geometria = self.settings.value("geometria")
        if geometria:
            self.restoreGeometry(geometria)

        motor = self.settings.value("motor", "pdflatex", type=str)
        self._elegir_motor(motor)

        auto = self.settings.value("auto_compilar", False, type=bool)
        self.a_auto.setChecked(auto)
        self.editor_page.set_auto_compile(auto)

        chktex = self.settings.value("chktex", True, type=bool)
        self.a_chktex.setChecked(chktex)
        self.editor_page.usar_chktex = chktex

        ajuste = self.settings.value("ajustar_lineas", True, type=bool)
        self.a_ajustar_lineas.setChecked(ajuste)
        self._alternar_ajuste(ajuste)

        self._reconstruir_recientes()

        ultimo = self.settings.value("ultimo_documento", "", type=str)
        if ultimo and Path(ultimo).exists():
            self.editor_page.open_file(Path(ultimo))

    def _guardar_ajustes(self, ultimo: Optional[Path] = None) -> None:
        self.settings.setValue("geometria", self.saveGeometry())
        if ultimo is not None:
            self.settings.setValue("ultimo_documento", str(ultimo))

    # ════════════════════════════════════════════════════════
    # Arrastrar y soltar
    # ════════════════════════════════════════════════════════

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            ruta = Path(url.toLocalFile())
            if not ruta.is_file():
                continue
            if ruta.suffix.lower() in (".tex", ".bib", ".cls", ".sty"):
                self.paginas.setCurrentIndex(0)
                self.editor_page.open_file(ruta)
                self._anadir_reciente(ruta)
            elif ruta.suffix.lower() in SUPPORTED_EXTENSIONS:
                self.paginas.setCurrentIndex(1)
                self.converter_page.set_source(ruta)
            event.acceptProposedAction()
            return

    def closeEvent(self, event) -> None:
        if self.editor_page.is_busy() or self.converter_page.is_busy():
            respuesta = QMessageBox.question(
                self, APP_NAME,
                "Hay trabajo en marcha. ¿Cerrar de todas formas?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                event.ignore()
                return
            self.editor_page.stop()
            self.converter_page.stop()

        # Se apunta antes de cerrar las pestañas: después ya no hay editor.
        editor = self.editor_page.editor
        ultimo = editor.path if editor is not None else None

        if not self.editor_page.close_all():
            event.ignore()
            return

        if self.recuperacion is not None:
            self.recuperacion.close()
        self._guardar_ajustes(ultimo)
        event.accept()
