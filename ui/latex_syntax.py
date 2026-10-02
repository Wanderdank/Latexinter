"""
latex_syntax.py - Lo que el editor sabe de LaTeX.

Tres cosas: cómo se colorea el código (LatexHighlighter), qué comandos y
entornos existen para autocompletar, y los fragmentos que se insertan enteros
(tablas, figuras, ecuaciones…).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PyQt5.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from . import theme


# ════════════════════════════════════════════════════════════
# Resaltado
# ════════════════════════════════════════════════════════════

def _format(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    fmt.setFontItalic(italic)
    return fmt


class LatexHighlighter(QSyntaxHighlighter):
    """
    Resaltado por líneas. Las matemáticas entre $$…$$ o \\[…\\] pueden ocupar
    varias líneas, así que se marca el estado del bloque para continuarlas.
    """

    ESTADO_NORMAL = 0
    ESTADO_MATEMATICAS = 1
    ESTADO_VERBATIM = 2

    def __init__(self, document):
        super().__init__(document)

        self.f_comando = _format(theme.COLOR_COMANDO, bold=True)
        self.f_entorno = _format(theme.COLOR_ENTORNO, bold=True)
        self.f_matematicas = _format(theme.COLOR_MATEMATICAS)
        self.f_comentario = _format(theme.COLOR_COMENTARIO, italic=True)
        self.f_llave = _format(theme.COLOR_LLAVE)
        self.f_seccion = _format(theme.COLOR_SECCION, bold=True)
        self.f_referencia = _format(theme.COLOR_REFERENCIA)
        self.f_pendiente = _format(theme.AMBAR, bold=True)

        self.reglas = [
            # \begin{...} y \end{...}: el nombre del entorno en otro color
            (re.compile(r"(\\(?:begin|end)\s*)(\{)([^}]*)(\})"),
             [self.f_comando, self.f_llave, self.f_entorno, self.f_llave]),
            # Títulos de sección: el texto en blanco
            (re.compile(r"(\\(?:part|chapter|section|subsection|subsubsection|"
                        r"paragraph|title)\*?\s*)(\{)([^}]*)(\})"),
             [self.f_comando, self.f_llave, self.f_seccion, self.f_llave]),
            # Referencias, citas y etiquetas
            (re.compile(r"(\\(?:label|ref|eqref|autoref|pageref|cite[a-zA-Z]*|"
                        r"includegraphics|input|include|bibliography)\*?\s*)"
                        r"(\[[^\]]*\])?(\{)([^}]*)(\})"),
             [self.f_comando, self.f_comando, self.f_llave,
              self.f_referencia, self.f_llave]),
        ]

        self.regla_comando = re.compile(r"\\(?:[A-Za-z@]+\*?|[^A-Za-z\s])")
        self.regla_llaves = re.compile(r"[{}\[\]]")
        self.regla_math_inline = re.compile(r"(?<!\\)\$(?:[^$\\\n]|\\.)*\$")
        self.regla_comentario = re.compile(r"(?<!\\)%[^\n]*")
        self.regla_pendiente = re.compile(r"\b(TODO|FIXME|REVISAR|OJO|XXX)\b")

        self.inicio_math = re.compile(r"(?<!\\)\$\$|\\\[|\\begin\{(?:equation|align|"
                                      r"gather|multline|eqnarray|displaymath)\*?\}")
        self.fin_math = re.compile(r"(?<!\\)\$\$|\\\]|\\end\{(?:equation|align|"
                                   r"gather|multline|eqnarray|displaymath)\*?\}")
        self.inicio_verbatim = re.compile(r"\\begin\{(?:verbatim|lstlisting|minted|alltt)\}")
        self.fin_verbatim = re.compile(r"\\end\{(?:verbatim|lstlisting|minted|alltt)\}")

    # ── Pintado ──
    def highlightBlock(self, text: str) -> None:
        estado = self.previousBlockState()
        if estado == -1:
            estado = self.ESTADO_NORMAL

        if estado == self.ESTADO_VERBATIM:
            self.setFormat(0, len(text), self.f_comentario)
            self.setCurrentBlockState(
                self.ESTADO_NORMAL if self.fin_verbatim.search(text) else self.ESTADO_VERBATIM
            )
            return

        if estado == self.ESTADO_MATEMATICAS:
            fin = self.fin_math.search(text)
            hasta = fin.end() if fin else len(text)
            self.setFormat(0, hasta, self.f_matematicas)
            self._comandos_dentro(text, 0, hasta)
            if not fin:
                self.setCurrentBlockState(self.ESTADO_MATEMATICAS)
                return
            self.setCurrentBlockState(self.ESTADO_NORMAL)
            self._normal(text, fin.end())
            return

        self.setCurrentBlockState(self.ESTADO_NORMAL)
        self._normal(text, 0)

    def _normal(self, text: str, desde: int) -> None:
        # Llaves y corchetes primero: son el fondo de todo lo demás.
        for match in self.regla_llaves.finditer(text, desde):
            self.setFormat(match.start(), 1, self.f_llave)
        for match in self.regla_comando.finditer(text, desde):
            self.setFormat(match.start(), match.end() - match.start(), self.f_comando)

        for patron, formatos in self.reglas:
            for match in patron.finditer(text, desde):
                ultimo = match.lastindex or 0
                for indice, formato in enumerate(formatos, start=1):
                    if indice <= ultimo and match.group(indice):
                        self.setFormat(
                            match.start(indice),
                            match.end(indice) - match.start(indice),
                            formato,
                        )

        for match in self.regla_math_inline.finditer(text, desde):
            self.setFormat(match.start(), match.end() - match.start(), self.f_matematicas)
            self._comandos_dentro(text, match.start(), match.end())

        # ¿Empieza aquí un bloque que sigue en la línea siguiente?
        verbatim = self.inicio_verbatim.search(text, desde)
        if verbatim and not self.fin_verbatim.search(text, verbatim.end()):
            self.setCurrentBlockState(self.ESTADO_VERBATIM)
        else:
            abre = self.inicio_math.search(text, desde)
            if abre and not self.fin_math.search(text, abre.end()):
                self.setFormat(abre.start(), len(text) - abre.start(), self.f_matematicas)
                self._comandos_dentro(text, abre.start(), len(text))
                self.setCurrentBlockState(self.ESTADO_MATEMATICAS)

        comentario = self.regla_comentario.search(text, desde)
        if comentario:
            self.setFormat(
                comentario.start(), len(text) - comentario.start(), self.f_comentario
            )
            for match in self.regla_pendiente.finditer(text, comentario.start()):
                self.setFormat(match.start(), match.end() - match.start(), self.f_pendiente)

    def _comandos_dentro(self, text: str, inicio: int, fin: int) -> None:
        """Dentro de una fórmula los comandos siguen siendo comandos."""
        for match in self.regla_comando.finditer(text, inicio, fin):
            self.setFormat(match.start(), match.end() - match.start(), self.f_comando)


# ════════════════════════════════════════════════════════════
# Autocompletado
# ════════════════════════════════════════════════════════════

ENVIRONMENTS = [
    "abstract", "align", "align*", "alignat", "array", "aligned", "axis",
    "bmatrix", "cases", "center", "corollary", "definition", "description",
    "displaymath", "document", "enumerate", "eqnarray", "equation", "equation*",
    "figure", "figure*", "flushleft", "flushright", "frame", "gather", "gather*",
    "itemize", "lemma", "longtable", "lstlisting", "matrix", "minipage",
    "multline", "pmatrix", "proof", "proposition", "quotation", "quote",
    "remark", "split", "subequations", "subfigure", "table", "table*",
    "tabular", "tabularx", "textblock", "theorem", "thebibliography",
    "tikzpicture", "verbatim", "vmatrix", "wrapfigure",
]

COMMANDS = [
    # Estructura
    "documentclass", "usepackage", "begin", "end", "title", "author", "date",
    "maketitle", "part", "chapter", "section", "subsection", "subsubsection",
    "paragraph", "subparagraph", "appendix", "tableofcontents", "listoffigures",
    "listoftables", "newpage", "clearpage", "pagebreak", "newline", "linebreak",
    "input", "include", "includeonly",
    # Texto
    "textbf", "textit", "texttt", "textsc", "textsf", "textrm", "underline",
    "emph", "textsuperscript", "textsubscript", "textcolor", "colorbox",
    "footnote", "marginpar", "today", "LaTeX", "TeX", "quad", "qquad",
    "hspace", "vspace", "hfill", "vfill", "noindent", "indent", "centering",
    "raggedright", "raggedleft", "small", "footnotesize", "large", "Large",
    "LARGE", "huge", "Huge", "normalsize", "scriptsize", "tiny",
    # Listas
    "item", "itemsep", "setlist",
    # Referencias
    "label", "ref", "eqref", "pageref", "autoref", "cite", "citep", "citet",
    "nocite", "bibliography", "bibliographystyle", "printbibliography",
    "addbibresource", "url", "href", "hyperref",
    # Figuras y tablas
    "includegraphics", "caption", "captionsetup", "graphicspath", "subfloat",
    "hline", "cline", "toprule", "midrule", "bottomrule", "multicolumn",
    "multirow", "resizebox", "scalebox", "rotatebox", "centerline",
    # Matemáticas
    "frac", "dfrac", "tfrac", "sqrt", "sum", "prod", "int", "iint", "oint",
    "lim", "limits", "infty", "partial", "nabla", "cdot", "cdots", "ldots",
    "times", "div", "pm", "mp", "leq", "geq", "neq", "approx", "equiv",
    "sim", "propto", "subset", "supset", "subseteq", "in", "notin", "cup",
    "cap", "emptyset", "forall", "exists", "neg", "land", "lor",
    "rightarrow", "leftarrow", "leftrightarrow", "Rightarrow", "Leftarrow",
    "Leftrightarrow", "mapsto", "to", "left", "right", "big", "Big", "bigg",
    "mathbb", "mathcal", "mathfrak", "mathbf", "mathrm", "mathit", "mathsf",
    "mathtt", "text", "operatorname", "binom", "overline", "underline",
    "hat", "bar", "vec", "dot", "ddot", "tilde", "widehat", "widetilde",
    "sin", "cos", "tan", "log", "ln", "exp", "max", "min", "sup", "inf",
    "det", "dim", "ker", "arg", "gcd", "deg", "alpha", "beta", "gamma",
    "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma",
    "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega", "Gamma",
    "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi",
    "Psi", "Omega", "tag", "notag", "nonumber", "qedhere",
    # Definiciones
    "newcommand", "renewcommand", "providecommand", "newenvironment",
    "newtheorem", "def", "let", "setlength", "addtolength", "newcounter",
    "setcounter", "stepcounter", "arabic", "roman", "alph",
]


@dataclass(frozen=True)
class Snippet:
    """Un fragmento que se inserta entero. El · marca dónde queda el cursor."""

    trigger: str
    description: str
    body: str


CURSOR = "·"

SNIPPETS: list[Snippet] = [
    Snippet("figura", "Figura con imagen y pie",
            "\\begin{figure}[htbp]\n"
            "    \\centering\n"
            "    \\includegraphics[width=0.8\\textwidth]{·}\n"
            "    \\caption{}\n"
            "    \\label{fig:}\n"
            "\\end{figure}"),
    Snippet("tabla", "Tabla con booktabs",
            "\\begin{table}[htbp]\n"
            "    \\centering\n"
            "    \\caption{·}\n"
            "    \\label{tab:}\n"
            "    \\begin{tabular}{lcc}\n"
            "        \\toprule\n"
            "        Columna & Columna & Columna \\\\\n"
            "        \\midrule\n"
            "        & & \\\\\n"
            "        \\bottomrule\n"
            "    \\end{tabular}\n"
            "\\end{table}"),
    Snippet("ecuacion", "Ecuación numerada",
            "\\begin{equation}\n    ·\n\\end{equation}"),
    Snippet("align", "Varias ecuaciones alineadas",
            "\\begin{align}\n    · &= \\\\\n     &=\n\\end{align}"),
    Snippet("lista", "Lista con viñetas",
            "\\begin{itemize}\n    \\item ·\n    \\item \n\\end{itemize}"),
    Snippet("enumerar", "Lista numerada",
            "\\begin{enumerate}\n    \\item ·\n    \\item \n\\end{enumerate}"),
    Snippet("matriz", "Matriz entre paréntesis",
            "\\begin{pmatrix}\n    · & \\\\\n     & \n\\end{pmatrix}"),
    Snippet("casos", "Definición por casos",
            "\\begin{cases}\n    · & \\text{si } \\\\\n     & \\text{en otro caso}\n\\end{cases}"),
    Snippet("codigo", "Bloque de código",
            "\\begin{lstlisting}[language=Python]\n·\n\\end{lstlisting}"),
    Snippet("cita", "Cita destacada",
            "\\begin{quote}\n    ·\n\\end{quote}"),
    Snippet("fraccion", "Fracción", "\\frac{·}{}"),
    Snippet("raiz", "Raíz cuadrada", "\\sqrt{·}"),
    Snippet("integral", "Integral definida", "\\int_{·}^{} \\, dx"),
    Snippet("sumatorio", "Sumatorio", "\\sum_{i=·}^{n}"),
    Snippet("subfigura", "Dos figuras lado a lado",
            "\\begin{figure}[htbp]\n"
            "    \\centering\n"
            "    \\begin{subfigure}{0.48\\textwidth}\n"
            "        \\includegraphics[width=\\textwidth]{·}\n"
            "        \\caption{}\n"
            "    \\end{subfigure}\\hfill\n"
            "    \\begin{subfigure}{0.48\\textwidth}\n"
            "        \\includegraphics[width=\\textwidth]{}\n"
            "        \\caption{}\n"
            "    \\end{subfigure}\n"
            "    \\caption{}\n"
            "\\end{figure}"),
]

SNIPPETS_POR_NOMBRE = {s.trigger: s for s in SNIPPETS}


def completion_entries() -> list[tuple[str, str]]:
    """
    Lista para el autocompletado: (texto a insertar, descripción).
    Los comandos van con su barra, los entornos como \\begin{...}.
    """
    entradas: list[tuple[str, str]] = []
    for nombre in sorted(set(COMMANDS)):
        entradas.append(("\\" + nombre, "comando"))
    for nombre in sorted(set(ENVIRONMENTS)):
        entradas.append(("\\begin{" + nombre + "}", "entorno"))
    for fragmento in SNIPPETS:
        entradas.append(("\\" + fragmento.trigger, fragmento.description))
    return entradas
