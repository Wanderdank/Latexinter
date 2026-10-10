"""
mathfix.py - Traduce texto plano con símbolos Unicode a LaTeX matemático.

Un PDF no guarda fórmulas: guarda glifos. Cuando se extrae el texto queda algo
como "si a <= b entonces x2 pertenece a R", con los símbolos como caracteres
Unicode sueltos. La conversión ingenua sustituye símbolo por símbolo y produce
"si $\\alpha$ $\\leq$ $\\beta$ entonces x2 $\\in$ $\\mathbb{R}$": compila, pero
se ve mal y no es LaTeX que nadie querría editar.

Este módulo hace lo contrario: detecta el *tramo* matemático completo y lo
envuelve una sola vez, produciendo
"si $\\alpha \\leq \\beta$ entonces $x^{2} \\in \\mathbb{R}$".

Entradas públicas
-----------------
latexify_markdown(md)   Para el Markdown recién extraído de un PDF. Detecta
                        tramos matemáticos, superíndices/subíndices y
                        ecuaciones centradas (incluidas las numeradas).

latexify_tex(tex)       Para un .tex ya generado (por ejemplo por pandoc desde
                        Word). Sustituye los símbolos Unicode sueltos que
                        pdflatex no sabe imprimir, respetando el modo
                        matemático, los verbatim y los comentarios.

count_math(tex)         Número aproximado de fórmulas, para estadísticas.
"""

from __future__ import annotations

import re
from typing import Optional

# ════════════════════════════════════════════════════════════
# Tablas de símbolos
# ════════════════════════════════════════════════════════════

# Símbolos tipográficos: se traducen en modo texto y NUNCA activan modo
# matemático (un guion largo o unas comillas no convierten la frase en fórmula).
TEXT_SYMBOLS: dict[str, str] = {
    "\u2010": "-", "\u2011": "-", "\u2012": "--", "\u2013": "--", "\u2014": "---",
    "\u2015": "---",
    "\u2018": "`", "\u2019": "'", "\u201a": ",", "\u201b": "`",
    "\u201c": "``", "\u201d": "''", "\u201e": ",,",
    "\u00ab": "\\guillemotleft{}", "\u00bb": "\\guillemotright{}",
    "\u2039": "\\guilsinglleft{}", "\u203a": "\\guilsinglright{}",
    "\u2026": "\\ldots{}",
    "\u2022": "\\textbullet{}", "\u25cf": "\\textbullet{}", "\u25aa": "\\textbullet{}",
    "\u00b7": "\\textperiodcentered{}",
    "\u00b0": "\\textdegree{}",
    "\u00a9": "\\textcopyright{}", "\u00ae": "\\textregistered{}",
    "\u2122": "\\texttrademark{}",
    "\u00a7": "\\S{}", "\u00b6": "\\P{}",
    "\u2020": "\\dag{}", "\u2021": "\\ddag{}",
    "\u20ac": "\\texteuro{}", "\u00a3": "\\pounds{}", "\u00a5": "\\textyen{}",
    "\u00bd": "$\\tfrac{1}{2}$", "\u00bc": "$\\tfrac{1}{4}$", "\u00be": "$\\tfrac{3}{4}$",
    "\u2153": "$\\tfrac{1}{3}$", "\u2154": "$\\tfrac{2}{3}$",
    "\u0141": "\\L{}", "\u0142": "\\l{}",
    "\u2423": " ",   # \u2423 que los listados de c\u00f3digo usan para marcar espacios
    # Espacios y caracteres invisibles
    "\u00a0": "~", "\u2002": " ", "\u2005": " ", "\u2007": "~",
    "\u2009": "\\,", "\u202f": "\\,", "\u2003": "\\quad{}",
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "", "\u00ad": "",
}

# Cómo se renderizan esos mismos símbolos si caen DENTRO de una fórmula.
TEXT_SYMBOLS_IN_MATH: dict[str, str] = {
    "\u00b7": "\\cdot", "\u2026": "\\dots", "\u00b0": "^{\\circ}",
    "\u2013": "-", "\u2014": "-", "\u2010": "-", "\u2011": "-", "\u2012": "-",
    "\u2018": "'", "\u2019": "'",
    "\u00a0": "\\,", "\u2009": "\\,", "\u202f": "\\,",
    "\u2020": "\\dagger", "\u2021": "\\ddagger",
    # Acentos sueltos: en texto pdflatex los imprime, en una f\u00f3rmula no.
    "\u02c6": "\\hat{}", "\u02dc": "\\tilde{}", "\u02c7": "\\check{}",
    "\u02d9": "\\dot{}", "\u02d8": "\\breve{}", "\u02da": "\\mathring{}",
    # Las íes sin punto: en texto la ı es turca y pdflatex ya la imprime.
    "\u0131": "\\imath", "\u0237": "\\jmath",
    "\u00bd": "\\tfrac{1}{2}", "\u00bc": "\\tfrac{1}{4}", "\u00be": "\\tfrac{3}{4}",
    "\u2153": "\\tfrac{1}{3}", "\u2154": "\\tfrac{2}{3}",
    "\u200b": "", "\ufeff": "", "\u00ad": "",
}

GREEK: dict[str, str] = {
    "\u03b1": "\\alpha", "\u03b2": "\\beta", "\u03b3": "\\gamma", "\u03b4": "\\delta",
    "\u03b5": "\\varepsilon", "\u03f5": "\\epsilon", "\u03b6": "\\zeta", "\u03b7": "\\eta",
    "\u03b8": "\\theta", "\u03d1": "\\vartheta", "\u03b9": "\\iota", "\u03ba": "\\kappa",
    "\u03bb": "\\lambda", "\u03bc": "\\mu", "\u00b5": "\\mu", "\u03bd": "\\nu",
    "\u03be": "\\xi", "\u03c0": "\\pi", "\u03d6": "\\varpi", "\u03c1": "\\rho",
    "\u03f1": "\\varrho", "\u03c3": "\\sigma", "\u03c2": "\\varsigma", "\u03c4": "\\tau",
    "\u03c5": "\\upsilon", "\u03c6": "\\varphi", "\u03d5": "\\phi", "\u03c7": "\\chi",
    "\u03c8": "\\psi", "\u03c9": "\\omega",
    "\u0393": "\\Gamma", "\u0394": "\\Delta", "\u0398": "\\Theta", "\u039b": "\\Lambda",
    "\u039e": "\\Xi", "\u03a0": "\\Pi", "\u03a3": "\\Sigma", "\u03a5": "\\Upsilon",
    "\u03a6": "\\Phi", "\u03a8": "\\Psi", "\u03a9": "\\Omega", "\u2126": "\\Omega",
}

# Símbolos que SÍ activan modo matemático.
MATH_SYMBOLS: dict[str, str] = {
    **GREEK,
    # Operadores
    "\u2212": "-", "\u00b1": "\\pm", "\u2213": "\\mp",
    "\u00d7": "\\times", "\u00f7": "\\div", "\u2217": "\\ast", "\u2218": "\\circ",
    "\u2219": "\\bullet", "\u22c5": "\\cdot", "\u2295": "\\oplus", "\u2296": "\\ominus",
    "\u2297": "\\otimes", "\u2298": "\\oslash", "\u2299": "\\odot",
    "\u221a": "\\surd", "\u2044": "/",
    # Relaciones
    "\u2260": "\\neq", "\u2264": "\\leq", "\u2265": "\\geq", "\u2266": "\\leqq",
    "\u2267": "\\geqq", "\u226a": "\\ll", "\u226b": "\\gg",
    "\u2248": "\\approx", "\u2245": "\\cong", "\u2261": "\\equiv", "\u223c": "\\sim",
    "\u2243": "\\simeq", "\u221d": "\\propto", "\u2225": "\\parallel", "\u22a5": "\\perp",
    "\u2254": ":=", "\u225c": "\\triangleq", "\u2250": "\\doteq",
    "\u2272": "\\lesssim", "\u2273": "\\gtrsim", "\u227a": "\\prec", "\u227b": "\\succ",
    "\u227c": "\\preccurlyeq", "\u227d": "\\succcurlyeq", "\u2aaf": "\\preceq",
    "\u2ab0": "\\succeq", "\u224d": "\\asymp", "\u2224": "\\nmid", "\u2226": "\\nparallel",
    "\u2270": "\\nleq", "\u2271": "\\ngeq", "\u2a7d": "\\leqslant", "\u2a7e": "\\geqslant",
    "\u22a2": "\\vdash", "\u22a8": "\\models", "\u22a4": "\\top", "\u27c2": "\\perp",
    "\u2291": "\\sqsubseteq", "\u2292": "\\sqsupseteq", "\u2284": "\\not\\subset",
    "\u2288": "\\nsubseteq",
    "\u228e": "\\uplus", "\u2293": "\\sqcap", "\u2294": "\\sqcup", "\u2240": "\\wr",
    "\u22c0": "\\bigwedge", "\u22c1": "\\bigvee", "\u2a01": "\\bigoplus", "\u2a02": "\\bigotimes",
    # Cálculo y conjuntos
    "\u221e": "\\infty", "\u2202": "\\partial", "\u2207": "\\nabla",
    "\u2211": "\\sum", "\u220f": "\\prod", "\u2210": "\\coprod",
    "\u222b": "\\int", "\u222c": "\\iint", "\u222d": "\\iiint", "\u222e": "\\oint",
    "\u2205": "\\emptyset", "\u2208": "\\in", "\u2209": "\\notin", "\u220b": "\\ni",
    "\u2282": "\\subset", "\u2283": "\\supset", "\u2286": "\\subseteq", "\u2287": "\\supseteq",
    "\u228a": "\\subsetneq", "\u222a": "\\cup", "\u2229": "\\cap", "\u2216": "\\setminus",
    "\u22c3": "\\bigcup", "\u22c2": "\\bigcap",
    # Lógica
    "\u2227": "\\land", "\u2228": "\\lor", "\u00ac": "\\neg", "\u2234": "\\therefore",
    "\u2235": "\\because", "\u2200": "\\forall", "\u2203": "\\exists", "\u2204": "\\nexists",
    # Flechas
    "\u2192": "\\rightarrow", "\u2190": "\\leftarrow", "\u2194": "\\leftrightarrow",
    "\u21d2": "\\Rightarrow", "\u21d0": "\\Leftarrow", "\u21d4": "\\Leftrightarrow",
    "\u2191": "\\uparrow", "\u2193": "\\downarrow", "\u2195": "\\updownarrow",
    "\u21a6": "\\mapsto", "\u27f6": "\\longrightarrow", "\u27f5": "\\longleftarrow",
    "\u27f9": "\\Longrightarrow", "\u21c0": "\\rightharpoonup", "\u21bc": "\\leftharpoonup",
    "\u2197": "\\nearrow", "\u2198": "\\searrow",
    "\u27f8": "\\Longleftarrow", "\u27fa": "\\Longleftrightarrow", "\u27fc": "\\longmapsto",
    "\u21aa": "\\hookrightarrow", "\u21a9": "\\hookleftarrow", "\u21dd": "\\leadsto",
    "\u21c4": "\\rightleftarrows", "\u21cc": "\\rightleftharpoons",
    # Delimitadores y varios
    "\u2308": "\\lceil", "\u2309": "\\rceil", "\u230a": "\\lfloor", "\u230b": "\\rfloor",
    "\u27e8": "\\langle", "\u27e9": "\\rangle", "\u2329": "\\langle", "\u232a": "\\rangle",
    "\u2223": "\\mid", "\u2016": "\\|",
    "\u2206": "\\Delta", "\u2113": "\\ell", "\u2127": "\\mho", "\u03f0": "\\varkappa",
    "\u2201": "\\complement", "\u210e": "h", "\u25e6": "\\circ",
    "\u25a0": "\\blacksquare", "\u220e": "\\blacksquare", "\u25bd": "\\triangledown",
    "\u25b5": "\\vartriangle", "\u2662": "\\diamondsuit", "\u2663": "\\clubsuit",
    "\u2032": "'", "\u2033": "''", "\u2034": "'''",
    "\u2135": "\\aleph", "\u210f": "\\hbar", "\u2118": "\\wp",
    "\u2111": "\\Im", "\u211c": "\\Re", "\u2220": "\\angle", "\u2221": "\\measuredangle",
    "\u25a1": "\\square", "\u25b3": "\\triangle", "\u25c7": "\\diamond",
    "\u2713": "\\checkmark", "\u2717": "\\times", "\u2606": "\\star", "\u22c6": "\\star",
    "\u22ef": "\\cdots", "\u22ee": "\\vdots", "\u22f1": "\\ddots",
    # Conjuntos numéricos y letras caligráficas
    "\u211d": "\\mathbb{R}", "\u2115": "\\mathbb{N}", "\u2124": "\\mathbb{Z}",
    "\u211a": "\\mathbb{Q}", "\u2102": "\\mathbb{C}", "\u210d": "\\mathbb{H}",
    "\u2110": "\\mathcal{I}", "\u2112": "\\mathcal{L}", "\u2130": "\\mathcal{E}",
    "\u2131": "\\mathcal{F}", "\u210b": "\\mathcal{H}", "\u2133": "\\mathcal{M}",
    "\u212c": "\\mathcal{B}", "\u2128": "\\mathfrak{Z}", "\u212d": "\\mathfrak{C}",
}

# Superíndices y subíndices Unicode → carácter normal.
SUPERSCRIPTS: dict[str, str] = {
    "\u2070": "0", "\u00b9": "1", "\u00b2": "2", "\u00b3": "3", "\u2074": "4",
    "\u2075": "5", "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9",
    "\u207a": "+", "\u207b": "-", "\u207c": "=", "\u207d": "(", "\u207e": ")",
    "\u207f": "n", "\u2071": "i",
    "\u1d43": "a", "\u1d47": "b", "\u1d9c": "c", "\u1d48": "d", "\u1d49": "e",
    "\u1da0": "f", "\u1d4d": "g", "\u02b0": "h", "\u02b2": "j", "\u1d4f": "k",
    "\u02e1": "l", "\u1d50": "m", "\u1d52": "o", "\u1d56": "p", "\u02b3": "r",
    "\u02e2": "s", "\u1d57": "t", "\u1d58": "u", "\u1d5b": "v", "\u02b7": "w",
    "\u02e3": "x", "\u02b8": "y", "\u1dbb": "z", "\u1d40": "T",
}

SUBSCRIPTS: dict[str, str] = {
    "\u2080": "0", "\u2081": "1", "\u2082": "2", "\u2083": "3", "\u2084": "4",
    "\u2085": "5", "\u2086": "6", "\u2087": "7", "\u2088": "8", "\u2089": "9",
    "\u208a": "+", "\u208b": "-", "\u208c": "=", "\u208d": "(", "\u208e": ")",
    "\u2090": "a", "\u2091": "e", "\u2095": "h", "\u1d62": "i", "\u2c7c": "j",
    "\u2096": "k", "\u2097": "l", "\u2098": "m", "\u2099": "n", "\u2092": "o",
    "\u209a": "p", "\u1d63": "r", "\u209b": "s", "\u209c": "t", "\u1d64": "u",
    "\u1d65": "v", "\u2093": "x",
}

# Funciones que en LaTeX llevan su propio comando (\sin, no sin).
FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh", "coth",
    "arcsin", "arccos", "arctan", "log", "ln", "lg", "exp", "lim", "liminf",
    "limsup", "max", "min", "sup", "inf", "det", "dim", "ker", "deg", "gcd",
    "arg", "hom",
}


# ════════════════════════════════════════════════════════════
# Alfabetos matemáticos Unicode (U+1D400…) → \mathbf, \mathcal, …
# ════════════════════════════════════════════════════════════

_ALPHABET_RANGES = [
    (0x1D400, "\\mathbf{%s}"), (0x1D434, "%s"), (0x1D468, "\\mathbf{%s}"),
    (0x1D49C, "\\mathcal{%s}"), (0x1D4D0, "\\mathcal{%s}"),
    (0x1D504, "\\mathfrak{%s}"), (0x1D538, "\\mathbb{%s}"),
    (0x1D56C, "\\mathfrak{%s}"), (0x1D5A0, "\\mathsf{%s}"),
    (0x1D5D4, "\\mathsf{%s}"), (0x1D608, "\\mathsf{%s}"),
    (0x1D63C, "\\mathsf{%s}"), (0x1D670, "\\mathtt{%s}"),
]


# Las griegas vienen en bloques de 58: 25 mayúsculas, ∇, 25 minúsculas, ∂ y
# seis variantes. Las mayúsculas y minúsculas siguen el orden de U+0391 y
# U+03B1, con ϴ y ς en el hueco 17.
_GREEK_RANGES = [
    (0x1D6A8, True), (0x1D6E2, False), (0x1D71C, True), (0x1D756, True), (0x1D790, True),
]
_GREEK_TAIL = "\u2202\u03f5\u03d1\u03f0\u03d5\u03f1\u03d6"   # ∂ϵϑϰϕϱϖ
_GREEK_LIKE_LATIN = dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΧο", "ABEZHIKMNOPTXo"))


def _math_greek(cp: int) -> Optional[str]:
    for start, bold in _GREEK_RANGES:
        offset = cp - start
        if not 0 <= offset < 58:
            continue
        if offset < 25:
            ch = "\u03f4" if offset == 17 else chr(0x391 + offset)
        elif offset == 25:
            ch = "\u2207"
        elif offset < 51:
            ch = chr(0x3B1 + offset - 26)
        else:
            ch = _GREEK_TAIL[offset - 51]
        if ch in _GREEK_LIKE_LATIN:
            latex = _GREEK_LIKE_LATIN[ch]
            return "\\mathbf{" + latex + "}" if bold else latex
        latex = "\\Theta" if ch == "\u03f4" else MATH_SYMBOLS[ch]
        return "\\boldsymbol{" + latex + "}" if bold else latex
    return None


def _math_alphanumeric(ch: str) -> Optional[str]:
    """Traduce los 'Mathematical Alphanumeric Symbols' a su comando LaTeX."""
    cp = ord(ch)
    if 0x1D7CE <= cp <= 0x1D7FF:                      # dígitos estilizados
        return str((cp - 0x1D7CE) % 10)
    if cp in (0x1D6A4, 0x1D6A5):                      # ı y ȷ cursivas
        return "\\imath" if cp == 0x1D6A4 else "\\jmath"
    if 0x1D6A8 <= cp < 0x1D7CE:
        return _math_greek(cp)
    for start, template in _ALPHABET_RANGES:
        if start <= cp < start + 52:
            offset = cp - start
            letter = chr(ord("A") + offset) if offset < 26 else chr(ord("a") + offset - 26)
            return template % letter
    return None


def repair_truncated_alphanumerics(text: str) -> str:
    """
    Algunas fuentes (newtx, STIX) traen mal el mapa a Unicode de sus letras
    matemáticas: 𝑥 (U+1D465) se extrae como 푥 (U+D465), una sílaba coreana.
    Si el documento no tiene más texto en coreano, esas «sílabas» son letras
    matemáticas recortadas a 16 bits y se recuperan.
    """
    if not re.search("[\ud400-\ud7ff]", text) or re.search("[\uac00-\ud3ff]", text):
        return text
    return re.sub("[\ud400-\ud7ff]", lambda m: chr(ord(m.group()) + 0x10000), text)


def _symbol_to_latex(ch: str) -> Optional[str]:
    """Comando LaTeX (modo matemático) para un carácter suelto, o None."""
    if ch in MATH_SYMBOLS:
        return MATH_SYMBOLS[ch]
    if ch in TEXT_SYMBOLS_IN_MATH:
        return TEXT_SYMBOLS_IN_MATH[ch]
    if ord(ch) > 0x1D3FF:
        return _math_alphanumeric(ch)
    return None


# ════════════════════════════════════════════════════════════
# Marcadores internos (zona de uso privado de Unicode)
# ════════════════════════════════════════════════════════════

_SUP = chr(0xE010)      # marca de superíndice
_SUB = chr(0xE011)      # marca de subíndice
_OPEN = chr(0xE0F0)     # delimitadores de un fragmento protegido
_CLOSE = chr(0xE0F1)


class _Vault:
    """
    Guarda fragmentos que no deben tocarse (código, enlaces, matemáticas ya
    escritas), los sustituye por un marcador invisible y los repone al final.
    """

    def __init__(self, kind: int = 0):
        self.kind = kind
        self.items: list[str] = []
        self._pattern = re.compile(
            re.escape(_OPEN) + f"{kind:02x}" + r"([0-9a-f]{4})" + re.escape(_CLOSE)
        )

    def stash(self, text: str) -> str:
        self.items.append(text)
        return f"{_OPEN}{self.kind:02x}{len(self.items) - 1:04x}{_CLOSE}"

    def restore(self, text: str) -> str:
        return self._pattern.sub(lambda m: self.items[int(m.group(1), 16)], text)


# ════════════════════════════════════════════════════════════
# Renderizado del interior de una fórmula
# ════════════════════════════════════════════════════════════

_MATH_OK_PUNCT = set("+-=<>()[]{}/,.:;'!^")
_TRIM_TAIL = set(",.:;! \t")

_TOKEN_RE = re.compile(
    r"(?P<space>[ \t]+)"
    r"|(?P<word>[A-Za-z]+)"
    r"|(?P<number>\d+(?:[.,]\d+)*)"
    r"|(?P<char>[\s\S])"
)

_UPRIGHT_SUB = re.compile(r"^[A-Za-z]{2,}$")


class _Token:
    __slots__ = ("text", "kind", "strong")

    def __init__(self, text: str, kind: str, strong: bool):
        self.text = text
        self.kind = kind        # space | word | number | char | script
        self.strong = strong    # ¿obliga a entrar en modo matemático?

    def __repr__(self) -> str:      # pragma: no cover - solo depuración
        return f"<{self.kind}{'!' if self.strong else ''} {self.text!r}>"


def _classify(text: str, kind: str) -> Optional[_Token]:
    """Devuelve el token, o None si el fragmento rompe el tramo matemático."""
    if kind == "space":
        return _Token(text, "space", False)
    if kind == "number":
        return _Token(text, "number", False)
    if kind == "word":
        # Una sola letra es una variable; una palabra entera es prosa.
        if len(text) == 1 or text in FUNCTIONS:
            return _Token(text, "word", False)
        return None
    # kind == "char"
    if text in (_SUP, _SUB):
        return _Token(text, "script", True)
    if _symbol_to_latex(text) is not None:
        # Los símbolos tipográficos no activan modo matemático por sí solos,
        # pero sí pueden formar parte de un tramo ya activado.
        strong = text in MATH_SYMBOLS or ord(text) > 0x1D3FF
        return _Token(text, "char", strong)
    if text in _MATH_OK_PUNCT:
        return _Token(text, "char", False)
    return None


def _wrap_script(marker: str, content: str) -> str:
    """v_max → v_{\\mathrm{max}} ; x^2 → x^{2}"""
    content = content.strip()
    if not content:
        return ""
    if content.startswith("\\"):        # ya es un comando: \circ, \max, \pi
        return marker + "{" + content + "}"
    if content in FUNCTIONS:
        return marker + "{\\" + content + "}"
    if _UPRIGHT_SUB.match(content):
        return marker + "{\\mathrm{" + content + "}}"
    return marker + "{" + content + "}"


_ENDS_IN_COMMAND = re.compile(r"\\[A-Za-z]+$")


def join_math(left: str, right: str) -> str:
    """Une dos trozos de fórmula sin pegar un comando a la letra siguiente
    ("\\langle" + "x" daría el comando inexistente \\langlex)."""
    if _ENDS_IN_COMMAND.search(left) and right[:1].isalpha():
        return left + " " + right
    return left + right


def _script_argument(body: str, pos: int) -> tuple[Optional[str], int]:
    """Argumento de un ^ o _ que empieza en pos: (contenido, fin)."""
    while pos < len(body) and body[pos] in " \t":
        pos += 1
    if pos >= len(body):
        return None, pos
    if body[pos] == "{":
        depth = 0
        i = pos
        while i < len(body):
            if body[i] == "\\":
                i += 2
                continue
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
                if depth == 0:
                    return body[pos + 1:i], i + 1
            i += 1
        return None, pos
    command = re.match(r"\\(?:[A-Za-z]+|.)", body[pos:])
    if command:
        return command.group(), pos + command.end()
    if body[pos] in "}^_":
        return None, pos
    return body[pos], pos + 1


def merge_double_scripts(body: str) -> str:
    """
    x^{a}^{b} → x^{ab}. Cuando el PDF guarda cada glifo de un índice por
    separado, la reconstrucción los encadena así, y pdflatex lo rechaza con
    «Double superscript».
    """
    if body.count("^") + body.count("_") < 2:
        return body
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            out.append(body[i:i + 2])
            i += 2
            continue
        if ch not in "^_":
            out.append(ch)
            i += 1
            continue
        # Todos los índices seguidos que cuelgan de la misma base.
        groups: list[tuple[str, str, int, int]] = []      # (marca, contenido, desde, hasta)
        pos = i
        while pos < len(body) and body[pos] in "^_'":
            if body[pos] == "'":
                # Una prima es un superíndice más: S^{z}' → S^{z\prime}.
                primas = len(body[pos:]) - len(body[pos:].lstrip("'"))
                groups.append(("^", "\\prime" * primas, pos, pos + primas))
                pos += primas
                continue
            arg, arg_end = _script_argument(body, pos + 1)
            if arg is None:
                break
            groups.append((body[pos], arg, pos, arg_end))
            pos = arg_end
            while pos < len(body) and body[pos] in " \t" and body[pos + 1:pos + 2] in ("^", "_"):
                pos += 1
        if not groups:
            out.append(ch)
            i += 1
            continue
        subs = [arg for mark, arg, _, _ in groups if mark == "_"]
        sups = [arg for mark, arg, _, _ in groups if mark == "^"]
        if len(subs) <= 1 and len(sups) <= 1:
            # x^{b}_{a} se ve igual que x_{a}^{b}, que es como se suele escribir.
            for mark, arg, start, stop in sorted(groups, key=lambda g: g[0] != "_"):
                braced = body[start + 1:stop].lstrip().startswith("{")
                out.append(mark + "{" + merge_double_scripts(arg) + "}" if braced else body[start:stop])
        else:
            # x_{1}^{s}_{,b} → x_{1,b}^{s}
            for mark, parts in (("_", subs), ("^", sups)):
                if not parts:
                    continue
                merged = parts[0]
                for part in parts[1:]:
                    merged = join_math(merged, part)
                out.append(mark + "{" + merge_double_scripts(merged) + "}")
        i = groups[-1][3]
    return "".join(out)


def balance_braces(fragment: str) -> str:
    """
    Escapa las llaves sin pareja de una fórmula. Suelen ser llaves de verdad
    del PDF, como las de un conjunto {x | x ≤ 1} partido entre texto y
    fórmula, y sin escapar rompen la compilación.
    """
    unmatched: set[int] = set()
    opened: list[int] = []
    i = 0
    while i < len(fragment):
        ch = fragment[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            opened.append(i)
        elif ch == "}":
            if opened:
                opened.pop()
            else:
                unmatched.add(i)
        i += 1
    unmatched.update(opened)
    if not unmatched:
        return fragment
    return "".join(
        "\\" + ch if i in unmatched else ch for i, ch in enumerate(fragment)
    )


_SURD_COMMAND = re.compile(r"\\surd\s*(\\[A-Za-z]+)\s?")


def _wrap_surd_commands(body: str) -> str:
    """√ seguido de un comando: el comando entra en la raíz con sus argumentos
    (\\sqrt{\\frac{1}{N}}, no \\sqrt{\\frac}{1}{N})."""
    while True:
        match = _SURD_COMMAND.search(body)
        if not match:
            return body
        end = match.end()
        while end < len(body) and body[end] == "{":
            arg, fin = _script_argument(body, end)
            if arg is None:
                break
            end = fin
        contenido = match.group(1) + body[match.end():end]
        body = body[:match.start()] + "\\sqrt{" + contenido + "}" + body[end:]


def _tidy_math(body: str) -> str:
    """Retoques finales sobre el interior de una fórmula."""
    # Raíces: el glifo suelto no lleva argumento, aquí se lo damos.
    body = re.sub(r"\\surd\s*\(([^()]{1,40})\)", r"\\sqrt{\1}", body)
    body = _wrap_surd_commands(body)
    body = re.sub(r"\\surd\s*([A-Za-z0-9]+)", r"\\sqrt{\1}", body)
    # Agrupa el contenido de ^ y _ : x^{2}, v_{\mathrm{max}}
    body = re.sub(
        r"([\^_])\{([^{}]{1,20})\}",
        lambda m: _wrap_script(m.group(1), m.group(2)),
        body,
    )
    body = re.sub(
        r"([\^_])(?!\{)(\d+|[A-Za-z])",
        lambda m: _wrap_script(m.group(1), m.group(2)),
        body,
    )
    # Espacios sobrantes
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"\s+([,;])", r"\1", body)
    # El espacio ancho no pinta nada pegado a un operador binario.
    body = re.sub(r"\\;\s*(?=[-+=<>])", "", body)
    body = re.sub(r"(?<=[-+=<>])\s*\\;", "", body)
    return merge_double_scripts(body.strip())


def _render_tokens(tokens: list[_Token]) -> str:
    """Convierte una lista de tokens en el interior de una fórmula LaTeX."""
    out: list[str] = []
    for tok in tokens:
        if tok.kind == "space":
            out.append(" ")
        elif tok.kind == "script":
            out.append("^" if tok.text == _SUP else "_")
        elif tok.kind == "word":
            out.append("\\" + tok.text + " " if tok.text in FUNCTIONS else tok.text)
        elif tok.kind == "number":
            out.append(tok.text.replace(",", "{,}"))
        else:
            cmd = _symbol_to_latex(tok.text)
            if cmd is None:
                out.append(tok.text)
            elif re.fullmatch(r"\\[A-Za-z]+", cmd):
                out.append(cmd + " ")      # espacio para no pegar \alpha con la x
            else:
                out.append(cmd)
    return _tidy_math("".join(out))


# ════════════════════════════════════════════════════════════
# Superíndices / subíndices escritos en Unicode
# ════════════════════════════════════════════════════════════

_SUP_RUN = re.compile("[" + re.escape("".join(SUPERSCRIPTS)) + "]+")
_SUB_RUN = re.compile("[" + re.escape("".join(SUBSCRIPTS)) + "]+")


def _expand_unicode_scripts(text: str) -> str:
    """x² → x·SUP·{2}   ·   Hᵢ → H·SUB·{i}"""
    text = _SUP_RUN.sub(
        lambda m: _SUP + "{" + "".join(SUPERSCRIPTS[c] for c in m.group(0)) + "}", text
    )
    text = _SUB_RUN.sub(
        lambda m: _SUB + "{" + "".join(SUBSCRIPTS[c] for c in m.group(0)) + "}", text
    )
    return text


# ════════════════════════════════════════════════════════════
# Detección de tramos matemáticos
# ════════════════════════════════════════════════════════════

def _wrap_math_runs(text: str) -> str:
    """
    Recorre el texto acumulando tokens compatibles con matemáticas y envuelve
    en $...$ cada tramo que contenga al menos un símbolo inequívocamente
    matemático. Los tramos sin ningún símbolo fuerte se dejan tal cual.
    """
    out: list[str] = []
    run: list[_Token] = []

    def flush() -> None:
        nonlocal run
        if not run:
            return
        # La coma final de una frase no forma parte de la fórmula.
        start, end = 0, len(run)
        while start < end and (run[start].kind == "space" or run[start].text in _TRIM_TAIL):
            start += 1
        while end > start and (run[end - 1].kind == "space" or run[end - 1].text in _TRIM_TAIL):
            end -= 1
        trimmed = run[start:end]

        if trimmed and any(t.strong for t in trimmed):
            prefix = "".join(t.text for t in run[:start])
            suffix = "".join(t.text for t in run[end:])
            body = _render_tokens(trimmed)
            out.append(prefix + ("$" + body + "$" if body else "") + suffix)
        else:
            out.append("".join(t.text for t in run))
        run = []

    for match in _TOKEN_RE.finditer(text):
        kind = match.lastgroup or "char"
        piece = match.group()
        token = _classify(piece, kind)
        if token is None and kind == "word" and text[match.end():match.end() + 1] in (_SUP, _SUB):
            # "mc²" o "Fig₁": la palabra es la base de un superíndice, así que
            # forma parte de la fórmula aunque tenga varias letras.
            token = _Token(piece, "word", False)
        if token is None:
            flush()
            out.append(piece)
        else:
            run.append(token)
    flush()

    result = "".join(out)
    # Marcadores que quedaron fuera de una fórmula: vuelven a ser texto.
    return result.replace(_SUP, "^").replace(_SUB, "_")


def _merge_adjacent_math(text: str) -> str:
    """$a$ $b$ → $a b$  (fórmulas partidas por la detección token a token)."""
    pattern = re.compile(r"\$([^$\n]+)\$([ ]?)\$([^$\n]+)\$")
    for _ in range(6):
        merged = pattern.sub(
            lambda m: "$" + m.group(1) + (m.group(2) or " ") + m.group(3) + "$", text
        )
        if merged == text:
            break
        text = merged
    return text


# Relaciones y operadores que siempre esperan un operando a su lado.
_BINARY_END = re.compile(
    r"(?:\\(?:leq|geq|neq|approx|equiv|sim|simeq|cong|ll|gg|in|notin|subset|"
    r"subseteq|supset|pm|mp|times|div|cdot|leqq|geqq|propto|to|rightarrow|lesssim|gtrsim|prec|succ|preceq|succeq)\s*"
    r"|[=<>+\-])$"
)
_BINARY_START = re.compile(
    r"^(?:\\(?:leq|geq|neq|approx|equiv|sim|simeq|cong|ll|gg|in|notin|subset|"
    r"subseteq|supset|pm|mp|times|div|cdot|leqq|geqq|propto|to|rightarrow|lesssim|gtrsim|prec|succ|preceq|succeq)\b"
    r"|[=<>])"
)


def _absorb_operands(text: str) -> str:
    """
    Rescata el operando que quedó fuera de la fórmula:
    "$\\gamma \\leq$ 5"  →  "$\\gamma \\leq 5$"
    """
    def after(match: re.Match) -> str:
        body, gap, operand = match.group(1), match.group(2), match.group(3)
        if not _BINARY_END.search(body):
            return match.group(0)
        return "$" + body.rstrip() + " " + operand + "$"

    def before(match: re.Match) -> str:
        operand, gap, body = match.group(1), match.group(2), match.group(3)
        if not _BINARY_START.match(body.lstrip()):
            return match.group(0)
        return "$" + operand + " " + body.lstrip() + "$"

    text = re.sub(r"\$([^$\n]+)\$([ ]?)(\d+(?:[.,]\d+)?|[A-Za-z])(?![\w])", after, text)
    text = re.sub(r"(?<![\w$])(\d+(?:[.,]\d+)?|[A-Za-z])([ ]?)\$([^$\n]+)\$", before, text)
    return text


# ════════════════════════════════════════════════════════════
# Ecuaciones centradas y numeradas
# ════════════════════════════════════════════════════════════

_DISPLAY_LINE = re.compile(r"^\s*\$(?P<body>.+?)\$\s*$")
_NUMBERED_LINE = re.compile(r"^\s*\$(?P<body>.+?)\$\s*\((?P<num>\d{1,3})\)\s*$")

# El número de ecuación queda a la derecha y la detección de tramos se lo
# traga: "$E = mc^{2} (3)$" vuelve a ser "$E = mc^{2}$ (3)".
_SWALLOWED_NUMBER = re.compile(r"^(\s*\$.+?)\s*\((\d{1,3})\)\$\s*$")


def _promote_display_math(md: str) -> str:
    """
    Una línea suelta que es solo una fórmula era, casi seguro, una ecuación
    centrada en el PDF original: se convierte en $$...$$, o en un entorno
    equation si llevaba número a la derecha.
    """
    lines = [_SWALLOWED_NUMBER.sub(r"\1$ (\2)", ln) for ln in md.split("\n")]
    result: list[str] = []
    for i, line in enumerate(lines):
        numbered = _NUMBERED_LINE.match(line)
        if numbered and len(numbered.group("body")) >= 4:
            result.extend([
                "",
                "\\begin{equation}",
                numbered.group("body").strip() + " \\tag{" + numbered.group("num") + "}",
                "\\end{equation}",
                "",
            ])
            continue

        display = _DISPLAY_LINE.match(line)
        if display and len(display.group("body")) >= 6:
            prev_blank = i == 0 or not lines[i - 1].strip()
            next_blank = i == len(lines) - 1 or not lines[i + 1].strip()
            if prev_blank and next_blank:
                result.append("$$" + display.group("body").strip() + "$$")
                continue
        result.append(line)
    return "\n".join(result)


# ════════════════════════════════════════════════════════════
# API pública: Markdown
# ════════════════════════════════════════════════════════════

# Fragmentos que se dejan exactamente como están.
_MD_VERBATIM = re.compile(
    r"```[\s\S]*?```"                      # bloques de código
    r"|~~~[\s\S]*?~~~"
    r"|`[^`\n]+`"                          # código en línea
    r"|!?\[[^\]\n]*\]\([^)\n]*\)"          # imágenes y enlaces
    r"|<[^>\n]{1,200}>"                    # HTML y autoenlaces
)

# Fórmulas que el extractor ya reconoció: no se reenvuelven, pero sí se
# traducen los símbolos Unicode que hayan quedado dentro.
_MD_EXISTING_MATH = re.compile(
    r"\$\$[\s\S]*?\$\$"
    r"|(?<!\\)\$(?:[^$\n\\]|\\.)+\$"
    r"|\\\[[\s\S]*?\\\]"
    r"|\\\([\s\S]*?\\\)"
)


def latexify_markdown(md: str) -> str:
    """
    Convierte los símbolos Unicode del Markdown extraído de un PDF en LaTeX
    matemático agrupado. El resultado sigue siendo Markdown válido: pandoc lo
    leerá con  markdown+tex_math_dollars+raw_tex.
    """
    md = repair_truncated_alphanumerics(md)
    verbatim = _Vault(kind=1)
    md = _MD_VERBATIM.sub(lambda m: verbatim.stash(m.group(0)), md)

    existing = _Vault(kind=4)
    md = _MD_EXISTING_MATH.sub(
        lambda m: existing.stash(_translate_inside_math(m.group(0))), md
    )

    md = _expand_unicode_scripts(md)
    md = _wrap_math_runs(md)

    # Símbolos tipográficos que quedaron en modo texto.
    for ch, repl in TEXT_SYMBOLS.items():
        if ch in md:
            md = md.replace(ch, repl)

    # Las fórmulas que ya venían del extractor vuelven ahora, antes de unir
    # tramos contiguos: así "$-b\\pm$" y "$b^{2}$" acaban en una sola fórmula.
    md = existing.restore(md)
    md = _strip_emphasis_around_math(md)
    md = _merge_adjacent_math(md)
    md = _retidy_inline_math(md)
    md = _promote_display_math(md)
    return verbatim.restore(md)


_EMPHASIZED_MATH = re.compile(r"(?<![\w*_])([*_]{1,2})(\$[^$\n]+\$)\1(?![\w*_])")
_INLINE_MATH = re.compile(r"(?<!\$)\$([^$\n]{1,400})\$(?!\$)")


def _strip_emphasis_around_math(text: str) -> str:
    """
    El extractor marca las fórmulas en cursiva; en LaTeX sobra. Además la
    reconstrucción de índices puede haberse comido la marca de cierre, y un
    guion bajo suelto acabaría impreso como tal.
    """
    text = _EMPHASIZED_MATH.sub(r"\2", text)
    text = re.sub(r"(?<![\w\\*_])[*_]{1,2}(?=\$)", "", text)
    text = re.sub(r"(?<=\$)[*_]{1,2}(?![\w*_])", "", text)
    return text


def _retidy_inline_math(text: str) -> str:
    """Vuelve a ordenar el interior de las fórmulas después de unirlas."""
    return _INLINE_MATH.sub(lambda m: "$" + _tidy_math(m.group(1)) + "$", text)


# ════════════════════════════════════════════════════════════
# API pública: LaTeX ya generado
# ════════════════════════════════════════════════════════════

_TEX_UNTOUCHABLE = re.compile(
    r"\\begin\{(verbatim|Verbatim|lstlisting|minted|alltt|filecontents\*?)\}"
    r"[\s\S]*?\\end\{\1\}"
    r"|(?<!\\)%[^\n]*"
    r"|\\(?:url|href|includegraphics|input|include|label|ref|eqref|autoref|cite[a-zA-Z]*"
    r"|bibliography|bibliographystyle|usepackage|documentclass|graphicspath|lstinline"
    r"|verb)\b(?:\[[^\]\n]*\])?(?:\{[^{}]*\})*"
)

_TEX_MATH = re.compile(
    r"\$\$[\s\S]*?\$\$"
    r"|(?<!\\)\$(?:[^$\\]|\\.)+\$"
    r"|\\\[[\s\S]*?\\\]"
    r"|\\\([\s\S]*?\\\)"
    r"|\\begin\{(equation\*?|align\*?|alignat\*?|gather\*?|multline\*?|eqnarray\*?"
    r"|array|cases|split|[bBpvV]?matrix)\}[\s\S]*?\\end\{\1\}"
)


def _translate_inside_math(fragment: str) -> str:
    """Traduce símbolos Unicode dentro de una fórmula que ya existe."""
    out: list[str] = []
    for i, ch in enumerate(fragment):
        if ch.isascii():
            out.append(ch)
            continue
        cmd = _symbol_to_latex(ch)
        if cmd is None:
            out.append(ch)
        elif re.fullmatch(r"\\[A-Za-z]+", cmd):
            # El espacio solo hace falta si lo que sigue es alfanumérico:
            # "\alpha x" sí, "\leq +" no.
            following = fragment[i + 1: i + 2]
            out.append(cmd + " " if following.isalnum() else cmd)
        else:
            out.append(cmd)
    return _COMBINING_AFTER.sub(_apply_combining, "".join(out))


# Acentos que Unicode escribe detrás de la letra (x⃗ = x + U+20D7).
COMBINING_ACCENTS: dict[str, str] = {
    "̂": "\\hat", "̃": "\\tilde", "̄": "\\bar", "̅": "\\bar",
    "̇": "\\dot", "̈": "\\ddot", "̌": "\\check", "̆": "\\breve",
    "⃗": "\\vec", "⃑": "\\vec", "̸": "\\not",
}
_COMBINING_AFTER = re.compile(
    r"(\\[A-Za-z]+|\{[^{}]*\}|[A-Za-z0-9=<>])\s*([" + "".join(COMBINING_ACCENTS) + r"])"
)


def _apply_combining(match: re.Match) -> str:
    base, accent = match.group(1), COMBINING_ACCENTS[match.group(2)]
    if accent == "\\not":
        return "\\not" + (base if base.startswith("\\") else " " + base)
    result = accent + (base if base.startswith("{") else "{" + base + "}")
    # Detrás de ^ o _ el acento necesita su grupo: d^{\vec{3}}, no d^\vec{3}.
    if match.string[:match.start()].rstrip().endswith(("^", "_")):
        result = "{" + result + "}"
    return result


_STRAY_MATH_COMMAND = re.compile(
    r"(?<![\\$])\\("
    + "|".join(sorted(
        {cmd[1:] for cmd in MATH_SYMBOLS.values() if re.fullmatch(r"\\[A-Za-z]+", cmd)},
        key=len, reverse=True,
    ))
    + r")(?![A-Za-z])"
)


def latexify_tex(tex: str) -> str:
    """
    Sustituye los caracteres Unicode que pdflatex no sabe imprimir por sus
    comandos LaTeX, respetando comentarios, verbatim, rutas de archivo y el
    modo matemático ya existente.
    """
    untouchable = _Vault(kind=2)
    tex = _TEX_UNTOUCHABLE.sub(lambda m: untouchable.stash(m.group(0)), tex)

    math = _Vault(kind=3)
    tex = _TEX_MATH.sub(
        lambda m: math.stash(
            merge_double_scripts(balance_braces(_translate_inside_math(m.group(0))))
        ),
        tex,
    )

    # Un comando de símbolo matemático que quedó fuera de la fórmula (\sigma
    # suelto en un párrafo) para a pdflatex en seco: se mete en su $…$.
    tex = _STRAY_MATH_COMMAND.sub(lambda m: "$" + m.group(0) + "$", tex)

    # Texto normal: primero los símbolos tipográficos…
    for ch, repl in TEXT_SYMBOLS.items():
        if ch in tex:
            tex = tex.replace(ch, repl)

    # …y luego los matemáticos, cada uno en su propio $…$.
    for ch, cmd in MATH_SYMBOLS.items():
        if ch in tex:
            tex = tex.replace(ch, "$" + cmd + "$")

    # Superíndices / subíndices sueltos en modo texto.
    tex = _SUP_RUN.sub(
        lambda m: "$^{" + "".join(SUPERSCRIPTS[c] for c in m.group(0)) + "}$", tex
    )
    tex = _SUB_RUN.sub(
        lambda m: "$_{" + "".join(SUBSCRIPTS[c] for c in m.group(0)) + "}$", tex
    )

    # Alfabetos matemáticos Unicode sueltos.
    tex = re.sub(
        r"[\U0001D400-\U0001D7FF]+",
        lambda m: "$" + "".join(_math_alphanumeric(c) or c for c in m.group(0)) + "$",
        tex,
    )

    tex = _merge_adjacent_math(tex)
    tex = _absorb_operands(tex)
    tex = math.restore(tex)
    return untouchable.restore(tex)


# ════════════════════════════════════════════════════════════
# Métricas
# ════════════════════════════════════════════════════════════

def count_math(tex: str) -> int:
    """Número aproximado de expresiones matemáticas en un documento LaTeX."""
    count = len(re.findall(r"(?<!\\)\$(?:[^$\\]|\\.)+\$", tex))
    count += len(re.findall(r"\\\([\s\S]*?\\\)", tex))
    count += len(re.findall(r"\\\[|\\begin\{(?:equation|align|gather|multline)", tex))
    return count


# Símbolos fuera del latín que inputenc ya sabe imprimir en texto: acentos
# sueltos (ˆ ˇ ˘ ˙ ˚ ˛ ˜ ˝) y tipografía.
_KNOWN_TO_PDFLATEX = set(
    "ˆˇ˘˙˚˛˜˝"
    "–—‘’‚“”„†‡•…"
    "‰‹›€™"
)


def remaining_unicode(tex: str) -> set[str]:
    """
    Caracteres no ASCII que quedaron sin traducir y que pdflatex podría
    rechazar. Se ignoran las letras latinas con acentos, que inputenc sí
    maneja, y lo que va en comentarios, que pdflatex no lee.
    """
    tex = re.sub(r"(?<!\\)%[^\n]*", "", tex)
    return {
        c for c in tex
        if ord(c) > 127
        and not (0xA0 <= ord(c) <= 0x24F)        # latín con acentos
        and not (0x1E00 <= ord(c) <= 0x1EFF)
        and c not in _KNOWN_TO_PDFLATEX
        and not (0xE000 <= ord(c) <= 0xE0FF)     # marcadores internos
    }
