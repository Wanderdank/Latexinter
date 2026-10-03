"""
latex_editor.py - El editor de LaTeX.

Un QPlainTextEdit al que se le han añadido las cosas que uno espera de un
editor de LaTeX: números de línea, resaltado, autocompletado de comandos y
entornos, cierre automático de llaves y de \\begin{…}, sangrado con el
tabulador, comentar con un atajo y fragmentos que se insertan enteros.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QRect, QSize, QStringListModel, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
    QTextCursor,
    QTextFormat,
)
from PyQt5.QtWidgets import (
    QCompleter,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from converters.textfiles import TextFormat, read_source, write_source

from . import theme
from .latex_syntax import CURSOR, SNIPPETS_POR_NOMBRE, LatexHighlighter, completion_entries


class _LineNumberArea(QWidget):
    """La franja de la izquierda con los números de línea."""

    def __init__(self, editor: "LatexEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_line_numbers(event)


class LatexEditor(QPlainTextEdit):
    """Editor de un documento LaTeX."""

    cursorMoved = pyqtSignal(int, int)          # línea, columna (desde 1)
    saveRequested = pyqtSignal()
    compileRequested = pyqtSignal()

    INDENT = "    "

    # Pares que se cierran solos al escribir el de apertura.
    PARES = {"{": "}", "[": "]", "(": ")", "$": "$"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: Optional[Path] = None
        self.text_format = TextFormat()
        # Nombre de su copia de recuperación mientras tenga cambios sin guardar.
        self.recovery_id = uuid.uuid4().hex

        self.setFont(theme.mono_font(11))
        self.setTabStopDistance(QFontMetrics(self.font()).horizontalAdvance(" ") * 4)
        # Los párrafos de LaTeX son largos: se ajustan a la ventana, como en
        # cualquier editor pensado para escribir y no solo para programar.
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setFrameStyle(0)

        self.highlighter = LatexHighlighter(self.document())
        self._line_numbers = _LineNumberArea(self)
        self._busqueda: list[QTextEdit.ExtraSelection] = []
        self._synctex: list[QTextEdit.ExtraSelection] = []

        self.blockCountChanged.connect(lambda _: self._update_margins())
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_moved)

        self._setup_completer()
        self._update_margins()
        self._refresh_extra_selections()

    # ════════════════════════════════════════════════════════
    # Números de línea
    # ════════════════════════════════════════════════════════

    def line_number_width(self) -> int:
        digitos = max(2, len(str(max(1, self.blockCount()))))
        return 16 + QFontMetrics(self.font()).horizontalAdvance("9") * digitos

    def _update_margins(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_numbers.scroll(0, dy)
        else:
            self._line_numbers.update(0, rect.y(), self._line_numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_numbers.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_width(), cr.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_numbers)
        painter.fillRect(event.rect(), QColor(theme.FONDO))

        bloque = self.firstVisibleBlock()
        numero = bloque.blockNumber()
        arriba = round(self.blockBoundingGeometry(bloque).translated(self.contentOffset()).top())
        abajo = arriba + round(self.blockBoundingRect(bloque).height())
        actual = self.textCursor().blockNumber()

        while bloque.isValid() and arriba <= event.rect().bottom():
            if bloque.isVisible() and abajo >= event.rect().top():
                painter.setPen(QColor(theme.TEXTO if numero == actual else theme.TEXTO_TENUE))
                painter.drawText(
                    0, arriba, self._line_numbers.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignRight, str(numero + 1),
                )
            bloque = bloque.next()
            arriba = abajo
            abajo = arriba + round(self.blockBoundingRect(bloque).height())
            numero += 1

    # ════════════════════════════════════════════════════════
    # Resaltados de fondo
    # ════════════════════════════════════════════════════════

    def _on_cursor_moved(self) -> None:
        cursor = self.textCursor()
        self.cursorMoved.emit(cursor.blockNumber() + 1, cursor.positionInBlock() + 1)
        self._refresh_extra_selections()

    def _refresh_extra_selections(self) -> None:
        selecciones: list[QTextEdit.ExtraSelection] = []

        if not self.isReadOnly():
            actual = QTextEdit.ExtraSelection()
            actual.format.setBackground(QColor(theme.COLOR_LINEA_ACTUAL))
            actual.format.setProperty(QTextFormat.FullWidthSelection, True)
            actual.cursor = self.textCursor()
            actual.cursor.clearSelection()
            selecciones.append(actual)

        selecciones.extend(self._synctex)
        selecciones.extend(self._busqueda)
        self.setExtraSelections(selecciones)

    def highlight_matches(self, posiciones: list[tuple[int, int]]) -> None:
        """Marca los resultados de una búsqueda."""
        self._busqueda = []
        for inicio, longitud in posiciones[:2000]:
            seleccion = QTextEdit.ExtraSelection()
            seleccion.format.setBackground(QColor(theme.COLOR_SELECCION_BUSQUEDA))
            cursor = self.textCursor()
            cursor.setPosition(inicio)
            cursor.setPosition(inicio + longitud, QTextCursor.KeepAnchor)
            seleccion.cursor = cursor
            self._busqueda.append(seleccion)
        self._refresh_extra_selections()

    def clear_match_highlight(self) -> None:
        self._busqueda = []
        self._refresh_extra_selections()

    def flash_line(self, numero: int) -> None:
        """Marca una línea entera: la que señala el PDF o un error."""
        seleccion = QTextEdit.ExtraSelection()
        color = QColor(theme.COLOR_SYNCTEX)
        color.setAlpha(60)
        seleccion.format.setBackground(color)
        seleccion.format.setProperty(QTextFormat.FullWidthSelection, True)
        cursor = QTextCursor(self.document().findBlockByNumber(max(0, numero - 1)))
        seleccion.cursor = cursor
        self._synctex = [seleccion]
        self._refresh_extra_selections()

    def clear_flash(self) -> None:
        self._synctex = []
        self._refresh_extra_selections()

    # ════════════════════════════════════════════════════════
    # Autocompletado
    # ════════════════════════════════════════════════════════

    def _setup_completer(self) -> None:
        self._entradas = completion_entries()
        modelo = QStringListModel([texto for texto, _ in self._entradas], self)

        self.completer = QCompleter(modelo, self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitive)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated[str].connect(self._insert_completion)

    def _prefix_under_cursor(self) -> str:
        """El \\comando que se está escribiendo, si es que hay uno."""
        cursor = self.textCursor()
        texto = cursor.block().text()[: cursor.positionInBlock()]
        match = re.search(r"\\[A-Za-z@]*\{?[A-Za-z*]*\}?$", texto)
        return match.group(0) if match else ""

    def _insert_completion(self, completion: str) -> None:
        prefijo = self._prefix_under_cursor()
        cursor = self.textCursor()
        cursor.movePosition(
            QTextCursor.Left, QTextCursor.KeepAnchor, len(prefijo)
        )
        cursor.removeSelectedText()

        nombre = completion.lstrip("\\")
        if nombre in SNIPPETS_POR_NOMBRE:
            self._insert_snippet(cursor, SNIPPETS_POR_NOMBRE[nombre].body)
            return

        entorno = re.fullmatch(r"\\begin\{([^}]+)\}", completion)
        if entorno:
            sangria = self._current_indent()
            cuerpo = (
                f"\\begin{{{entorno.group(1)}}}\n"
                f"{sangria}{self.INDENT}{CURSOR}\n"
                f"{sangria}\\end{{{entorno.group(1)}}}"
            )
            self._insert_snippet(cursor, cuerpo)
            return

        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def _insert_snippet(self, cursor: QTextCursor, cuerpo: str) -> None:
        """Inserta un fragmento respetando la sangría y dejando el cursor en ·."""
        sangria = self._current_indent()
        lineas = cuerpo.split("\n")
        texto = lineas[0] + "".join("\n" + sangria + linea for linea in lineas[1:])

        destino = texto.find(CURSOR)
        cursor.insertText(texto.replace(CURSOR, ""))
        if destino != -1:
            posicion = cursor.position() - (len(texto) - destino - len(CURSOR))
            cursor.setPosition(posicion)
        self.setTextCursor(cursor)

    def _current_indent(self) -> str:
        texto = self.textCursor().block().text()
        return texto[: len(texto) - len(texto.lstrip())]

    def _maybe_show_completer(self) -> None:
        prefijo = self._prefix_under_cursor()
        if len(prefijo) < 2:
            self.completer.popup().hide()
            return

        self.completer.setCompletionPrefix(prefijo)
        if self.completer.completionCount() == 0:
            self.completer.popup().hide()
            return

        self.completer.popup().setCurrentIndex(
            self.completer.completionModel().index(0, 0)
        )
        rect = self.cursorRect()
        rect.setWidth(
            self.completer.popup().sizeHintForColumn(0)
            + self.completer.popup().verticalScrollBar().sizeHint().width()
            + 20
        )
        self.completer.complete(rect)

    # ════════════════════════════════════════════════════════
    # Teclado
    # ════════════════════════════════════════════════════════

    def keyPressEvent(self, event) -> None:
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (
            Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab, Qt.Key_Escape,
            Qt.Key_Up, Qt.Key_Down,
        ):
            event.ignore()
            return

        modificadores = event.modifiers()
        tecla = event.key()

        # Ctrl+Espacio fuerza el autocompletado
        if tecla == Qt.Key_Space and modificadores & Qt.ControlModifier:
            self._maybe_show_completer()
            return

        if modificadores & Qt.ControlModifier:
            if tecla == Qt.Key_S:
                self.saveRequested.emit()
                return
            if tecla in (Qt.Key_Slash, Qt.Key_7):
                self.toggle_comment()
                return
            if tecla == Qt.Key_B:
                self.wrap_selection("\\textbf{", "}")
                return
            if tecla == Qt.Key_I and not modificadores & Qt.ShiftModifier:
                self.wrap_selection("\\textit{", "}")
                return
            if tecla == Qt.Key_M:
                self.wrap_selection("$", "$")
                return
            if tecla == Qt.Key_D:
                self.duplicate_line()
                return

        if tecla == Qt.Key_Tab and not modificadores & Qt.ShiftModifier:
            if self.textCursor().hasSelection():
                self.change_indent(+1)
                return
            self.insertPlainText(self.INDENT)
            return
        if tecla == Qt.Key_Backtab or (
            tecla == Qt.Key_Tab and modificadores & Qt.ShiftModifier
        ):
            self.change_indent(-1)
            return

        if tecla in (Qt.Key_Return, Qt.Key_Enter):
            if self._handle_return():
                return

        # Escribir el cierre justo encima del que se puso solo: se sobrescribe.
        # Va antes que el autocierre porque «$» abre y cierra a la vez: sin
        # esto, cerrar $x$ dejaba un tercer $ suelto.
        if (
            event.text() in ("}", ")", "]", "$")
            and not self.textCursor().hasSelection()
            and self._next_char() == event.text()
        ):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.Right)
            self.setTextCursor(cursor)
            return

        if event.text() in self.PARES and self._should_autoclose(event.text()):
            self._insert_pair(event.text())
            return

        super().keyPressEvent(event)

        if event.text() and (event.text().isalpha() or event.text() == "\\"):
            self._maybe_show_completer()
        elif popup.isVisible():
            popup.hide()

    def _next_char(self) -> str:
        cursor = self.textCursor()
        texto = cursor.block().text()
        posicion = cursor.positionInBlock()
        return texto[posicion] if posicion < len(texto) else ""

    def _should_autoclose(self, caracter: str) -> bool:
        if self.textCursor().hasSelection():
            return True
        siguiente = self._next_char()
        if caracter == "$":
            # No duplicar el cierre de una fórmula que ya está escrita.
            return siguiente in ("", " ", "\t", ".", ",", ";", ")", "}")
        return siguiente in ("", " ", "\t", "\n", "}", ")", "]", "$", ",", ".")

    def _insert_pair(self, apertura: str) -> None:
        cierre = self.PARES[apertura]
        cursor = self.textCursor()
        if cursor.hasSelection():
            seleccion = cursor.selectedText()
            cursor.insertText(apertura + seleccion + cierre)
            return
        cursor.insertText(apertura + cierre)
        cursor.movePosition(QTextCursor.Left)
        self.setTextCursor(cursor)

    def _handle_return(self) -> bool:
        """Al pulsar Intro: mantener la sangría y cerrar entornos y llaves."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False

        linea = cursor.block().text()
        sangria = linea[: len(linea) - len(linea.lstrip())]
        antes = linea[: cursor.positionInBlock()]

        entorno = re.search(r"\\begin\{([^}]+)\}\s*$", antes)
        if entorno:
            cursor.beginEditBlock()
            cursor.insertText(
                f"\n{sangria}{self.INDENT}\n{sangria}\\end{{{entorno.group(1)}}}"
            )
            cursor.movePosition(QTextCursor.Up)
            cursor.movePosition(QTextCursor.EndOfLine)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return True

        # Entre llaves recién abiertas: se dejan tres líneas.
        if antes.endswith("{") and self._next_char() == "}":
            cursor.beginEditBlock()
            cursor.insertText(f"\n{sangria}{self.INDENT}\n{sangria}")
            cursor.movePosition(QTextCursor.Up)
            cursor.movePosition(QTextCursor.EndOfLine)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return True

        # Dentro de una lista, seguir poniendo \item
        if re.match(r"^\s*\\item\b", linea) and linea.strip() != "\\item":
            cursor.insertText(f"\n{sangria}\\item ")
            return True

        if sangria:
            cursor.insertText("\n" + sangria)
            return True
        return False

    # ════════════════════════════════════════════════════════
    # Acciones de edición
    # ════════════════════════════════════════════════════════

    def wrap_selection(self, antes: str, despues: str) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            texto = cursor.selectedText().replace("\u2029", "\n")
            cursor.insertText(antes + texto + despues)
        else:
            cursor.insertText(antes + despues)
            for _ in range(len(despues)):
                cursor.movePosition(QTextCursor.Left)
            self.setTextCursor(cursor)

    def toggle_comment(self) -> None:
        cursor = self.textCursor()
        inicio, fin = cursor.selectionStart(), cursor.selectionEnd()

        cursor.beginEditBlock()
        cursor.setPosition(inicio)
        primera = cursor.blockNumber()
        cursor.setPosition(fin)
        ultima = cursor.blockNumber()

        bloques = [
            self.document().findBlockByNumber(n) for n in range(primera, ultima + 1)
        ]
        comentar = not all(
            b.text().lstrip().startswith("%") for b in bloques if b.text().strip()
        )

        for bloque in bloques:
            texto = bloque.text()
            if not texto.strip() and comentar:
                continue
            edicion = QTextCursor(bloque)
            if comentar:
                edicion.movePosition(QTextCursor.StartOfLine)
                edicion.insertText("% ")
            else:
                despojado = texto.lstrip()
                if despojado.startswith("%"):
                    sangria = len(texto) - len(despojado)
                    quitar = 2 if despojado.startswith("% ") else 1
                    edicion.setPosition(bloque.position() + sangria)
                    edicion.setPosition(
                        bloque.position() + sangria + quitar, QTextCursor.KeepAnchor
                    )
                    edicion.removeSelectedText()
        cursor.endEditBlock()

    def change_indent(self, direccion: int) -> None:
        cursor = self.textCursor()
        inicio, fin = cursor.selectionStart(), cursor.selectionEnd()

        cursor.beginEditBlock()
        cursor.setPosition(inicio)
        primera = cursor.blockNumber()
        cursor.setPosition(fin)
        ultima = cursor.blockNumber()

        for numero in range(primera, ultima + 1):
            bloque = self.document().findBlockByNumber(numero)
            edicion = QTextCursor(bloque)
            if direccion > 0:
                edicion.insertText(self.INDENT)
            else:
                texto = bloque.text()
                sobra = len(texto) - len(texto.lstrip())
                quitar = min(len(self.INDENT), sobra)
                if quitar:
                    edicion.setPosition(bloque.position())
                    edicion.setPosition(bloque.position() + quitar, QTextCursor.KeepAnchor)
                    edicion.removeSelectedText()
        cursor.endEditBlock()

    def duplicate_line(self) -> None:
        cursor = self.textCursor()
        bloque = cursor.block()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.EndOfBlock)
        cursor.insertText("\n" + bloque.text())
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def goto_line(self, numero: int, *, marcar: bool = False) -> None:
        bloque = self.document().findBlockByNumber(max(0, numero - 1))
        if not bloque.isValid():
            return
        cursor = QTextCursor(bloque)
        self.setTextCursor(cursor)
        self.centerCursor()
        if marcar:
            self.flash_line(numero)
        self.setFocus()

    # ════════════════════════════════════════════════════════
    # Archivo
    # ════════════════════════════════════════════════════════

    def load(self, path: Path) -> None:
        texto, self.text_format = read_source(path)
        self.path = Path(path)
        self.setPlainText(texto)
        self.document().setModified(False)

    def source_text(self) -> str:
        """
        El texto tal cual, para guardarlo. toPlainText() cambia los espacios
        duros (U+00A0) por espacios normales, y guardar alteraría el archivo.
        """
        return (
            self.document().toRawText()
            .replace("\u2029", "\n")
            .replace("\u2028", "\n")
        )

    def save(self, path: Optional[Path] = None) -> Path:
        """
        Lanza UnicodeEncodeError si el texto tiene caracteres que no caben en
        la codificación del archivo; en ese caso el disco no se toca.
        """
        destino = Path(path) if path else self.path
        if destino is None:
            raise ValueError("El documento no tiene todavía un archivo asociado.")
        write_source(destino, self.source_text(), self.text_format)
        self.path = destino
        self.document().setModified(False)
        return destino

    @property
    def title(self) -> str:
        nombre = self.path.name if self.path else "sin título.tex"
        return nombre + (" •" if self.document().isModified() else "")
