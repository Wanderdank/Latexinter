"""
pdfmath.py - Reconstruye matemáticas leyendo la maquetación del PDF.

Un PDF no guarda fórmulas, guarda glifos colocados en la página. El extractor
de texto devuelve "x2" tanto para «x por 2» como para «x al cuadrado»: la
diferencia solo existe en la geometría. Aquí se mira el tamaño de letra, la
línea base y el nombre de la fuente de cada fragmento para deducir:

  · qué trozos son superíndices o subíndices  → x^{2}, v_{\\mathrm{max}}
  · qué líneas enteras son ecuaciones destacadas, que el extractor convierte
    en imagen y por tanto pierde como LaTeX.

Las fuentes matemáticas de TeX (LMMathItalic, CMMI, CMSY, MSBM…) marcan sin
ambigüedad qué partes de una línea son fórmula.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import mathfix

# Fuentes que solo se usan para componer matemáticas.
MATH_FONT_RE = re.compile(
    r"CMMI|CMSY|CMEX|CMBSY|MSAM|MSBM|EUSM|EUFM|RSFS|"
    r"MathItalic|MathSymbol|MathExtension|MathJax|"
    r"STIX.*Math|XITSMath|Cambria\s*Math|Asana.*Math|Math\b|Symbol|StandardSym|"
    # newtx y newpx (Times y Palatino con matemáticas), Euler y MnSymbol
    r"NewTX|NewPX|tx(?:sy|ex|mia)|px(?:sy|ex|mia)|ntx(?:mi|sy|ex)|npx(?:mi|sy|ex)|"
    r"EUR[MB]|EUEX|MnSymbol",
    re.IGNORECASE,
)

# Marcadores de énfasis que Markdown intercala dentro de una fórmula.
_EMPHASIS = r"(?:\*\*|__|[_*`])*"

_WORD = re.compile(r"^[A-Za-z]{2,}$")
_ONLY_DIGITS = re.compile(r"^\d+$")

# La fuente de extensión de TeX (CMEX / LMMathExtension) guarda los operadores
# grandes en posiciones ASCII: la integral es una 'Z' y el sumatorio una 'X'.
# Sin esta tabla, una integral se extrae del PDF como la letra Z.
EXTENSION_FONT_RE = re.compile(
    r"MathExtension|CMEX|LMEX|txex|pxex|ntxex|npxex|EUEX", re.IGNORECASE
)

BIG_OPERATORS: dict[str, str] = {
    "F": "\\bigsqcup", "G": "\\bigsqcup", "H": "\\oint", "I": "\\oint",
    "J": "\\bigodot", "K": "\\bigodot", "L": "\\bigoplus", "M": "\\bigoplus",
    "N": "\\bigotimes", "O": "\\bigotimes",
    "P": "\\sum", "Q": "\\prod", "R": "\\int", "S": "\\bigcup", "T": "\\bigcap",
    "U": "\\biguplus", "V": "\\bigwedge", "W": "\\bigvee",
    "X": "\\sum", "Y": "\\prod", "Z": "\\int", "[": "\\bigcup", "\\": "\\bigcap",
    "]": "\\biguplus", "^": "\\bigwedge", "_": "\\bigvee", "`": "\\coprod", "a": "\\coprod",
}

# Los delimitadores grandes de esa misma fuente: en tamaño fijo ocupan los
# códigos de control 0x00-0x2F (sin traducir, pdflatex se encuentra caracteres
# invisibles) y 'h'-'o'. Los de tamaño variable se componen con piezas
# (0x30-0x43) que, sueltas, no se pueden leer: se quitan.
_CMEX_DELIMITERS = (
    "( ) [ ] \\lfloor \\rfloor \\lceil \\rceil \\{ \\} \\langle \\rangle | \\| / \\backslash "
    "( ) ( ) [ ] \\lfloor \\rfloor \\lceil \\rceil \\{ \\} \\langle \\rangle / \\backslash "
    "( ) [ ] \\lfloor \\rfloor \\lceil \\rceil \\{ \\} \\langle \\rangle / \\backslash / \\backslash"
).split()
BIG_DELIMITERS: dict[str, str] = {
    chr(code): latex for code, latex in enumerate(_CMEX_DELIMITERS) if chr(code) not in "\t\n\r "
}
BIG_DELIMITERS.update({
    "D": "\\langle", "E": "\\rangle",
    "h": "[", "i": "]", "j": "\\lfloor", "k": "\\rfloor", "l": "\\lceil", "m": "\\rceil",
    "n": "\\{", "o": "\\}",
    # El signo de raíz, en sus cuatro tamaños.
    "p": "\\surd", "q": "\\surd", "r": "\\surd", "s": "\\surd",
})
BIG_DELIMITERS.update({chr(code): "" for code in range(0x30, 0x44)})

_BIG_OPERATOR_START = re.compile(
    r"^(\\(?:int|iint|iiint|oint|sum|prod|coprod|big[a-z]+))"
)


@dataclass(frozen=True)
class MathFix:
    """Una sustitución deducida de la maquetación."""

    plain: str      # el texto tal como aparece en el PDF ("mc2")
    pattern: str    # regex tolerante al marcado de Markdown ("_mc_[2]")
    latex: str      # el reemplazo ("$mc^{2}$")


# ────────────────────────────────────────────────────────────
# Clasificación de fragmentos dentro de una línea
# ────────────────────────────────────────────────────────────

def _line_baseline(spans: list[dict]) -> tuple[float, float]:
    """Tamaño de letra y línea base dominantes de la línea (los del cuerpo)."""
    weights: dict[float, int] = {}
    for span in spans:
        size = round(span["size"], 1)
        weights[size] = weights.get(size, 0) + len(span["text"].strip())
    if not weights:
        return 0.0, 0.0
    # El cuerpo es el tamaño mayor con una parte razonable de la línea: en
    # "p_{1,0}^X p_{0,1}^X" hay más letras en índices que fuera de ellos.
    total = sum(weights.values())
    base_size = max(s for s in weights if weights[s] >= 0.2 * total)

    baselines = sorted(
        span["origin"][1] for span in spans if round(span["size"], 1) == base_size
    )
    base_y = baselines[len(baselines) // 2] if baselines else 0.0
    return base_size, base_y


def _script_kind(span: dict, base_size: float, base_y: float) -> Optional[str]:
    """'sup', 'sub' o None."""
    if base_size <= 0:
        return None
    # Un índice se compone más pequeño; con el mismo cuerpo es texto normal.
    if span["size"] >= base_size - 0.4:
        return None
    dy = span["origin"][1] - base_y
    if dy < -0.14 * base_size:
        return "sup"
    if dy > 0.08 * base_size:
        return "sub"
    return None


def _is_math_font(span: dict) -> bool:
    return bool(MATH_FONT_RE.search(span.get("font", "")))


# Los dígitos, paréntesis y signos se componen en fuente normal incluso dentro
# de una fórmula, así que no dicen nada sobre si la línea es matemática.
_NEUTRAL_CHARS = set("()[]{}0123456789+-=.,;:!/|<> \t")


def _math_ratio(spans: list[dict]) -> tuple[int, int]:
    """
    Cuántos caracteres de la línea deciden si es matemática, y cuántos de
    ellos van en fuente matemática.
    """
    total = 0
    math_chars = 0
    for span in spans:
        decisive = sum(1 for ch in span["text"] if ch not in _NEUTRAL_CHARS)
        total += decisive
        if _is_math_font(span):
            math_chars += decisive
    return total, math_chars


# ────────────────────────────────────────────────────────────
# Traducción de fragmentos
# ────────────────────────────────────────────────────────────

def _to_math(text: str) -> str:
    """Traduce un fragmento suelto a notación matemática LaTeX."""
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch.isascii():
            out.append(ch)
            continue
        cmd = mathfix._symbol_to_latex(ch)
        if cmd is None:
            out.append(ch)
        elif re.fullmatch(r"\\[A-Za-z]+", cmd):
            following = text[i + 1: i + 2]
            out.append(cmd + " " if following.isalnum() else cmd)
        else:
            out.append(cmd)
    return "".join(out).strip()


def _script_body(text: str) -> str:
    """Contenido de un ^{...} o _{...}."""
    body = _to_math(text)
    if _WORD.match(body) and body not in mathfix.FUNCTIONS:
        return "\\mathrm{" + body + "}"
    if body in mathfix.FUNCTIONS:
        return "\\" + body
    return body


def _trailing_word(text: str) -> str:
    """Último trozo sin espacios de un fragmento: la base del superíndice."""
    match = re.search(r"\S+$", text)
    return match.group(0) if match else ""


def _tolerant_pattern(base: str, scripts: list[tuple[str, str]]) -> str:
    """
    El extractor intercala marcadores de Markdown y encierra los superíndices
    entre corchetes: "mc2" aparece en el texto como "_mc_[2]". Este patrón
    reconoce ambas formas.
    """
    parts = [r"(?<![A-Za-z0-9])", _EMPHASIS, re.escape(base), _EMPHASIS]
    for _, text in scripts:
        parts.append(r"[ \t]*\[?" + re.escape(text) + r"\]?" + _EMPHASIS)
    parts.append(r"(?![A-Za-z0-9])")
    return "".join(parts)


# ────────────────────────────────────────────────────────────
# Superíndices y subíndices en línea
# ────────────────────────────────────────────────────────────

def _page_fixes(page) -> list[MathFix]:
    fixes: list[MathFix] = []

    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:                 # 0 = texto
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s["text"].strip()]
            if len(spans) < 2:
                continue
            base_size, base_y = _line_baseline(spans)
            kinds = [_script_kind(s, base_size, base_y) for s in spans]
            if not any(kinds):
                continue

            i = 0
            while i < len(spans):
                if kinds[i] is None:
                    i += 1
                    continue

                # Base: el final del fragmento anterior ("mc" de "mc²").
                base_raw = _trailing_word(spans[i - 1]["text"]) if i > 0 else ""
                if not base_raw:
                    i += 1
                    continue

                # Todos los índices consecutivos que cuelgan de esa base.
                scripts: list[tuple[str, str]] = []
                j = i
                while j < len(spans) and kinds[j] is not None:
                    scripts.append((kinds[j], spans[j]["text"].strip()))
                    j += 1

                plain = base_raw + "".join(text for _, text in scripts)
                too_long = any(len(text) > 12 for _, text in scripts)
                if len(plain) < 2 or _ONLY_DIGITS.match(plain) or too_long:
                    i = j
                    continue

                latex = _to_math(_styled(base_raw, spans[i - 1]))
                for (kind, text), span in zip(scripts, spans[i:j]):
                    body = _script_body(_styled(text, span))
                    if body:
                        latex += ("^" if kind == "sup" else "_") + "{" + body + "}"

                fixes.append(MathFix(
                    plain=plain,
                    pattern=_tolerant_pattern(base_raw, scripts),
                    latex="$" + latex + "$",
                ))
                i = j

    return fixes


def collect_math_fixes(page) -> list[MathFix]:
    """
    Sustituciones deducidas de la maquetación de una página, sin duplicados y
    de más largas a más cortas para que la más específica gane.
    """
    seen: dict[str, MathFix] = {}
    for fix in _page_fixes(page):
        seen.setdefault(fix.plain, fix)
    return sorted(seen.values(), key=lambda f: -len(f.plain))


def apply_fixes_to_text(text: str, fixes: list[MathFix]) -> tuple[str, int]:
    """
    Aplica las sustituciones al Markdown de esa misma página. Devuelve el
    texto corregido y cuántas sustituciones se hicieron.
    """
    applied = 0
    for fix in fixes:
        # El reemplazo se pasa como función para que las barras invertidas de
        # LaTeX no se interpreten como referencias de grupo.
        text, count = re.subn(fix.pattern, lambda _m, r=fix.latex: r, text)
        applied += count
    return text, applied


# ────────────────────────────────────────────────────────────
# Ecuaciones destacadas
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DisplayEquation:
    """Una ecuación centrada, reconstruida a partir de sus glifos."""

    latex: str
    y: float
    confidence: float       # proporción de la línea compuesta en fuente matemática
    rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


def _union(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(r[0] for r in rects), min(r[1] for r in rects),
        max(r[2] for r in rects), max(r[3] for r in rects),
    )


# Fuentes cuyas letras son de otro alfabeto: la E de MSBM es 𝔼 y la S de CMSY
# es 𝒮, pero el PDF las da como letras normales.
_ALPHABET_FONTS = [
    (re.compile(r"MSBM|txsyb|pxsyb|STbb|BBold|DoubleStruck|dsrom|bbm", re.IGNORECASE), "\\mathbb{%s}", "[A-Z]"),
    (re.compile(r"CMSY|CMBSY|txsys|pxsys|LMMathSymbols|MathSymbols", re.IGNORECASE), "\\mathcal{%s}", "[A-Z]"),
    (re.compile(r"EUFM|EUFB|frak", re.IGNORECASE), "\\mathfrak{%s}", "[A-Za-z]"),
]


def _styled(text: str, span: dict) -> str:
    """Pasa las letras al alfabeto de su fuente: E en MSBM → \\mathbb{E}."""
    font = span.get("font", "")
    for pattern, template, letters in _ALPHABET_FONTS:
        if pattern.search(font):
            return re.sub(letters, lambda m: template % m.group(), text)
    return text


def _unshift(text: str) -> str:
    """
    La fuente de extensión de newtx/newpx lleva los operadores 0x7D
    posiciones más arriba que CMEX: su ∑ se extrae como «Í» o «Õ».
    """
    return "".join(
        chr(ord(ch) - 0x7D) if ord(ch) >= 0xC0 and chr(ord(ch) - 0x7D) in BIG_OPERATORS else ch
        for ch in text
    )


def _span_text(span: dict) -> str:
    """Texto de un fragmento, traduciendo la fuente de operadores grandes."""
    if "latex" in span:                     # una pieza ya armada: \frac, \sum…
        return span["latex"]
    text = span["text"].strip()
    if EXTENSION_FONT_RE.search(span.get("font", "")):
        text = _unshift(text)
        translated = [BIG_OPERATORS.get(ch, BIG_DELIMITERS.get(ch)) for ch in text]
        if any(cmd is not None for cmd in translated):
            return "".join(
                ch if cmd is None else cmd + " " if cmd else ""
                for cmd, ch in zip(translated, text)
            ).strip()
    return _to_math(_styled(text, span))


def _normalize_extension(spans: list[dict]) -> list[dict]:
    """
    Los glifos de la fuente de extensión (∑, ∫, paréntesis grandes) cuelgan
    por debajo de su línea base, que TeX pone arriba del todo, y el extractor
    les da una caja de unos pocos puntos. Se les pone la caja de verdad —desde
    el origen hasta el simétrico respecto al eje del renglón— y la línea base
    y el cuerpo del renglón, para que no parezcan índices.
    """
    if not any(EXTENSION_FONT_RE.search(s.get("font", "")) for s in spans):
        return spans
    normales = [s for s in spans if not EXTENSION_FONT_RE.search(s.get("font", ""))]
    if not normales:
        return spans
    size, _ = _line_baseline(normales)
    bases = sorted(s["origin"][1] for s in normales if abs(s["size"] - size) < 0.6)
    salida = []
    for span in spans:
        if "latex" in span or not EXTENSION_FONT_RE.search(span.get("font", "")):
            salida.append(span)
            continue
        arriba = min(span["origin"][1], span["bbox"][1])
        debajo = [b for b in bases if b > arriba]
        base = min(debajo) if debajo else (bases[-1] if bases else span["origin"][1])
        eje = base - 0.25 * size
        nuevo = dict(span)
        nuevo["bbox"] = (span["bbox"][0], arriba, span["bbox"][2], max(span["bbox"][3], 2 * eje - arriba))
        nuevo["origin"] = (span["bbox"][0], base)
        nuevo["size"] = size
        salida.append(nuevo)
    return salida


def _reconstruct_line(spans: list[dict]) -> str:
    """
    LaTeX de una línea completa. Los índices se anidan por tamaño de letra:
    en "e⁻ˣ²" la x y el 2 están en cuerpos distintos, así que el resultado es
    e^{-x^{2}} y no e^{-}^{x}^{2}.
    """
    if any(_accent_of(span) for span in spans):
        spans = sorted(_attach_accents(spans), key=lambda s: s["bbox"][0])
    spans = _normalize_extension(spans)
    base_size, base_y = _line_baseline(spans)
    pieces: list[str] = []
    open_scripts: list[tuple[float, str]] = []      # (tamaño, sup/sub) abiertos
    previous_right: Optional[float] = None

    def close_to(size: Optional[float], kind: Optional[str] = None) -> None:
        """
        Cierra los índices más pequeños que el tamaño indicado, y el del mismo
        tamaño si es del otro tipo: en p_{1,0}^{X} el 1,0 y la X van a la
        misma altura de letra, pero uno abajo y otro arriba.
        """
        while open_scripts and (
            size is None
            or open_scripts[-1][0] < size
            or (open_scripts[-1][0] == size and open_scripts[-1][1] != kind)
        ):
            open_scripts.pop()
            pieces.append("}")

    def append(piece: str) -> None:
        if pieces:
            pieces[-1] = mathfix.join_math(pieces[-1], piece)
        else:
            pieces.append(piece)

    for span in spans:
        text = span["text"].strip()
        if not text:
            continue

        size = span["size"]
        kind = _script_kind(span, base_size, base_y)

        if kind is None:
            close_to(None)
            gap = (
                previous_right is not None
                and span["bbox"][0] - previous_right > 0.2 * base_size
            )
            if gap and pieces:
                pieces.append("\\;")
            append(_span_text(span))
        else:
            close_to(size, kind)
            if not open_scripts or open_scripts[-1][0] > size:
                pieces.append(("^" if kind == "sup" else "_") + "{")
                open_scripts.append((size, kind))
            append(span["latex"] if "latex" in span else _script_body(_styled(text, span)))

        previous_right = span["bbox"][2]

    close_to(None)
    body = re.sub(r"(\\;)+", "\\\\;", "".join(pieces))
    return mathfix._tidy_math(body)


def _merge_fragments(fragments: list[str]) -> str:
    """
    Une los trozos de una ecuación de varias líneas. Un trozo corto justo
    encima de un operador grande es su límite superior:  ∞ + ∑ → \\sum^{\\infty}
    """
    merged: list[str] = []
    i = 0
    while i < len(fragments):
        current = fragments[i]
        following = fragments[i + 1] if i + 1 < len(fragments) else None
        if (
            following is not None
            and len(current) <= 10
            and "=" not in current
            and _BIG_OPERATOR_START.match(following)
        ):
            match = _BIG_OPERATOR_START.match(following)
            merged.append(
                match.group(1) + "^{" + current + "}" + following[match.end():]
            )
            i += 2
            continue
        merged.append(current)
        i += 1
    return " ".join(part for part in merged if part).strip()


def collect_display_equations(page) -> list[DisplayEquation]:
    """
    Ecuaciones centradas de la página. El extractor de Markdown las convierte
    en imagen, así que reconstruirlas aquí es la única forma de recuperarlas
    como LaTeX.

    Se reconocen por dos rasgos: están compuestas casi enteras en fuentes
    matemáticas y van centradas en la página. Lo segundo es lo que las
    distingue de una fórmula dentro de un párrafo.
    """
    page_center = page.rect.width / 2
    page_width = page.rect.width or 1
    equations: list[DisplayEquation] = []

    def flush(group: list[tuple[float, str, float, tuple]]) -> None:
        if not group:
            return
        group.sort(key=lambda item: item[0])
        latex = _merge_fragments([item[1] for item in group])
        if len(latex) < 6:
            return
        equations.append(DisplayEquation(
            latex=latex,
            y=group[0][0],
            confidence=sum(item[2] for item in group) / len(group),
            rect=_union([item[3] for item in group]),
        ))

    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue

        group: list[tuple[float, str, float, tuple]] = []
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s["text"].strip()]
            total, math_chars = _math_ratio(spans)

            centered = False
            if spans:
                left = min(s["bbox"][0] for s in spans)
                right = max(s["bbox"][2] for s in spans)
                centered = abs((left + right) / 2 - page_center) / page_width < 0.15

            if not spans or total < 1 or not centered or math_chars / total < 0.45:
                flush(group)
                group = []
                continue

            latex = _reconstruct_line(sorted(spans, key=lambda s: s["bbox"][0]))
            if latex:
                caja = _union([tuple(s["bbox"]) for s in spans])
                group.append((spans[0]["origin"][1], latex, math_chars / total, caja))
        flush(group)

    equations.sort(key=lambda e: e.y)
    return _join_split_equations(equations)


# Un operador grande y sus límites suelen quedar en bloques distintos: la
# integral por un lado y "de −∞ a ∞ …" por otro.
_ENDS_WITH_OPERATOR = re.compile(
    r"\\(?:int|iint|iiint|oint|sum|prod|coprod|big[a-z]+)"
    r"(?:[\^_]\{[^{}]*\})*\s*$"
)


def _join_split_equations(equations: list[DisplayEquation]) -> list[DisplayEquation]:
    joined: list[DisplayEquation] = []
    for equation in equations:
        if joined:
            previous = joined[-1]
            dangling_limit = equation.latex.startswith(("_{", "^{"))
            open_operator = bool(_ENDS_WITH_OPERATOR.search(previous.latex))
            if (dangling_limit or open_operator) and equation.y - previous.y < 60:
                joined[-1] = DisplayEquation(
                    latex=(previous.latex + equation.latex).strip(),
                    y=previous.y,
                    confidence=min(previous.confidence, equation.confidence),
                    rect=_union([previous.rect, equation.rect]),
                )
                continue
        joined.append(equation)
    return joined


# ────────────────────────────────────────────────────────────
# Fracciones y demás fórmulas «verticales»
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MathRegion:
    """
    Un trozo de página que contiene una fórmula apilada (una fracción, una
    matriz, un binomio…). Se guarda su rectángulo, para poder recortarlo y
    pasárselo al OCR, y el texto plano que el extractor sacó de ahí, para saber
    qué hay que sustituir en el Markdown.
    """

    rect: tuple[float, float, float, float]
    plain: str
    pattern: str
    kind: str = "fraccion"
    # Renglones ajenos que se cuelan en el recorte (la raíz de una fracción es
    # tan alta que su caja invade la línea de texto de encima). Se tapan de
    # blanco antes de pasarle la imagen al modelo.
    exclude: tuple[tuple[float, float, float, float], ...] = ()


# Una raya de fracción es corta, fina y horizontal. Las de las tablas y las
# reglas de encabezado son mucho más largas.
_RAYA_MAX_ANCHO = 260.0
_RAYA_MIN_ANCHO = 5.0
_RAYA_MAX_ALTO = 2.2


def _fraction_bars(page) -> list[tuple[float, float, float, float]]:
    """Rectángulos de las rayas que parecen barras de fracción."""
    barras: list[tuple[float, float, float, float]] = []
    try:
        dibujos = page.get_drawings()
    except Exception:
        return barras

    for dibujo in dibujos:
        rect = dibujo.get("rect")
        if rect is None:
            continue
        ancho, alto = rect.width, rect.height
        if not (_RAYA_MIN_ANCHO <= ancho <= _RAYA_MAX_ANCHO):
            continue
        if alto > _RAYA_MAX_ALTO or ancho < alto * 4:
            continue
        barras.append((rect.x0, rect.y0, rect.x1, rect.y1))
    return barras


def _lines_with_spans(page) -> list[tuple[tuple, list[dict]]]:
    resultado: list[tuple[tuple, list[dict]]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s["text"].strip()]
            if spans:
                resultado.append((_union([tuple(s["bbox"]) for s in spans]), spans))
    return resultado


def _dentro(caja: tuple, marco: tuple, holgura: float = 1.5) -> bool:
    """¿La caja está contenida en el marco, con un poco de holgura?"""
    return (
        caja[0] >= marco[0] - holgura and caja[2] <= marco[2] + holgura
        and caja[1] >= marco[1] - holgura and caja[3] <= marco[3] + holgura
    )


def _intersecta(caja: tuple, marco: tuple) -> bool:
    return (
        caja[0] < marco[2] and caja[2] > marco[0]
        and caja[1] < marco[3] and caja[3] > marco[1]
    )


def _candidatos_a_lado(renglones, barra, arriba: bool) -> list[tuple]:
    """
    Renglones que pueden ser el numerador (o el denominador) de esa raya.

    Un numerador nunca es más ancho que la raya y está justo encima; si el
    renglón desborda la raya o queda lejos, la raya no era una fracción sino
    un subrayado o el filete de una tabla.
    """
    x0, y0, x1, y1 = barra
    centro_y = (y0 + y1) / 2
    ancho_barra = x1 - x0
    elegidos: list[tuple] = []

    for caja, spans in renglones:
        ancho_caja = caja[2] - caja[0]
        solape = min(caja[2], x1) - max(caja[0], x0)
        if solape <= 0 or solape < 0.6 * min(ancho_barra, ancho_caja):
            continue
        if ancho_caja > ancho_barra * 1.3:
            continue

        alto = max(6.0, caja[3] - caja[1])
        if arriba:
            distancia = centro_y - caja[3]          # hueco entre la raya y el texto
        else:
            distancia = caja[1] - centro_y
        if 0 <= distancia < alto * 1.4:
            elegidos.append((caja, spans, distancia))
    return elegidos


def collect_fraction_regions(page) -> list[MathRegion]:
    """
    Busca las fracciones de la página. Una fracción no deja rastro en el texto
    extraído: el numerador y el denominador salen como dos trozos sueltos y la
    raya no sale en absoluto. Aquí se localiza la raya en los gráficos de la
    página y se recogen los renglones que tiene justo encima y justo debajo.
    """
    barras = _fraction_bars(page)
    if not barras:
        return []

    renglones = _lines_with_spans(page)
    regiones: list[MathRegion] = []
    usadas: set[tuple] = set()

    for barra in barras:
        arriba = _candidatos_a_lado(renglones, barra, arriba=True)
        abajo = _candidatos_a_lado(renglones, barra, arriba=False)
        if not arriba or not abajo:
            continue

        # Una raya de fracción está a la misma distancia del numerador que del
        # denominador. Un subrayado está pegado a su texto y lejos del de
        # abajo, que además es otro párrafo.
        hueco_arriba = min(d for _, _, d in arriba)
        hueco_abajo = min(d for _, _, d in abajo)
        mayor = max(hueco_arriba, hueco_abajo, 1.0)
        if abs(hueco_arriba - hueco_abajo) > mayor * 0.65 + 1.5:
            continue

        partes = [(c, s) for c, s, _ in arriba] + [(c, s) for c, s, _ in abajo]

        # Y por encima de todo: una fracción lleva tipografía matemática.
        if not any(_is_math_font(span) for _, spans in partes for span in spans):
            continue

        rect = _union([barra] + [c for c, _ in partes])

        # El extractor parte el numerador en varios trozos (el signo, la raíz,
        # el radicando…). Se recogen todos los que caen dentro del rectángulo,
        # que es el texto que de verdad va a aparecer en el Markdown.
        dentro = [
            (caja, spans) for caja, spans in renglones
            if _dentro(caja, rect)
        ]
        if dentro:
            partes = dentro
            rect = _union([barra] + [c for c, _ in dentro])

        if rect in usadas:
            continue
        usadas.add(rect)

        # Sin reordenar: los renglones vienen en el mismo orden en que el
        # extractor los va a escribir en el Markdown, y es ese orden —no el
        # geométrico— el que hay que reproducir para poder sustituirlos. El
        # trazo de una raíz, por ejemplo, se compone alto pero se lee después
        # del signo que lo precede.
        piezas = [
            "".join(s["text"] for s in spans).strip() for _, spans in partes
        ]
        piezas = [p for p in piezas if p]
        plain = "".join(piezas)
        if len(plain) < 2:
            continue

        propias = {tuple(c) for c, _ in partes}
        intrusos = tuple(
            caja for caja, _ in renglones
            if tuple(caja) not in propias and _intersecta(caja, rect)
        )

        regiones.append(MathRegion(
            rect=(rect[0] - 3, rect[1] - 1, rect[2] + 3, rect[3] + 1),
            plain=plain,
            pattern=_tolerant_plain_pattern(piezas),
            exclude=intrusos,
        ))

    return regiones


# Basura que el extractor intercala dentro de una fórmula: marcas de cursiva y
# negrita, los corchetes con que señala los superíndices, y espacios sueltos.
_BASURA = r"[\s_*`\[\]]{0,6}"


def _tolerant_plain_pattern(piezas: list[str]) -> str:
    """
    Patrón que reconoce la fórmula en el Markdown por muy troceada que venga.

    El extractor no escribe «−b±√b2−4ac2a» de un tirón: lo parte en cursivas,
    marca el exponente con corchetes y mete espacios, de modo que acaba como
    «_−b±√b_[2] _−_ 4 _ac_ 2 _a_». Por eso el patrón se construye carácter a
    carácter, admitiendo ese ruido entre uno y el siguiente.
    """
    texto = "".join(piezas)
    if len(texto) < 4:
        return r"(?!)"                       # demasiado corto: no arriesgar

    partes = [r"(?<![A-Za-z0-9])", _EMPHASIS]
    for indice, caracter in enumerate(texto):
        if indice:
            partes.append(_BASURA)
        partes.append(re.escape(caracter))
    partes.append(_EMPHASIS)
    return "".join(partes)


# ────────────────────────────────────────────────────────────
# Agrupación de ecuaciones para el OCR
# ────────────────────────────────────────────────────────────

@dataclass
class EquationCluster:
    """
    Un conjunto de trozos que en realidad son una sola ecuación.

    El extractor parte una ecuación destacada en varios renglones —el
    operador, sus límites, el numerador, el denominador—, y a veces en varios
    bloques. Aquí se vuelven a juntar para saber qué rectángulo hay que
    recortar si se va a pasar por el OCR.
    """

    rect: tuple[float, float, float, float]
    members: list[DisplayEquation]
    has_fraction: bool

    @property
    def y(self) -> float:
        return min((m.y for m in self.members), default=self.rect[1])


def cluster_equations(
    page,
    equations: list[DisplayEquation],
    regiones: Optional[list[MathRegion]] = None,
) -> list[EquationCluster]:
    """
    Junta los trozos contiguos de una misma ecuación y marca cuáles contienen
    una fracción.

    Esa marca es la que decide el método: donde hay una fracción, la fórmula
    está apilada y solo el OCR puede leerla; donde no la hay, la
    reconstrucción por geometría es más de fiar que el modelo, porque lee los
    caracteres del PDF en vez de adivinarlos.

    Se comprueban las fracciones ya validadas, no las rayas sueltas: el trazo
    horizontal de una raíz cuadrada también es una raya, y no es una fracción.
    """
    if not equations:
        return []

    if regiones is None:
        regiones = collect_fraction_regions(page)
    ordenadas = sorted(equations, key=lambda e: (e.rect[1], e.rect[0]))

    grupos: list[list[DisplayEquation]] = []
    for ecuacion in ordenadas:
        if grupos:
            actual = _union([m.rect for m in grupos[-1]])
            hueco = ecuacion.rect[1] - actual[3]
            solapa = min(actual[2], ecuacion.rect[2]) - max(actual[0], ecuacion.rect[0])
            if hueco < 14 and solapa > -18:
                grupos[-1].append(ecuacion)
                continue
        grupos.append([ecuacion])

    racimos: list[EquationCluster] = []
    for grupo in grupos:
        rect = _union([m.rect for m in grupo])
        dentro = [r for r in regiones if _intersecta(r.rect, rect)]
        if dentro:
            # La fracción puede sobresalir por arriba o por abajo del recorte.
            rect = _union([rect] + [r.rect for r in dentro])
            rect = (rect[0] - 4, rect[1] - 3, rect[2] + 4, rect[3] + 3)
        # Al crecer para abarcar sus fracciones, un racimo puede pisar al
        # siguiente (ecuaciones apiladas una debajo de otra): entonces son la
        # misma y se juntan, o su contenido saldría repetido.
        if racimos and _intersecta(racimos[-1].rect, rect):
            anterior = racimos[-1]
            racimos[-1] = EquationCluster(
                rect=_union([anterior.rect, rect]),
                members=anterior.members + grupo,
                has_fraction=anterior.has_fraction or bool(dentro),
            )
            continue
        racimos.append(EquationCluster(
            rect=rect, members=grupo, has_fraction=bool(dentro),
        ))
    return racimos


# ────────────────────────────────────────────────────────────
# Reconstrucción de una ecuación apilada por geometría
# ────────────────────────────────────────────────────────────

_UNICODE_BIG_OPERATORS = {"∑": "\\sum", "∏": "\\prod", "∐": "\\coprod",
                          "⋃": "\\bigcup", "⋂": "\\bigcap"}
# Funciones que en una ecuación destacada llevan el límite debajo: lím, máx…
_LIMIT_WORDS = {"lim", "liminf", "limsup", "max", "min", "sup", "inf"}


def _center(caja: tuple) -> tuple[float, float]:
    return (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2


def _piece(latex: str, partes: list[dict], eje: float, size: float) -> dict:
    """
    Un trozo ya armado (una fracción, un sumatorio con sus límites) que se
    coloca en la línea como si fuera un fragmento más. Su línea base se pone
    un cuarto de cuerpo por debajo del eje matemático, que es donde la tiene
    el resto de la ecuación.
    """
    caja = _union([tuple(p["bbox"]) for p in partes])
    return {
        "text": "x", "latex": latex, "bbox": caja, "size": size,
        "origin": (caja[0], eje + 0.25 * size), "font": "",
    }


def _layout(spans: list[dict]) -> str:
    """LaTeX de un grupo de fragmentos que forman una sola línea."""
    return _reconstruct_line(sorted(spans, key=lambda s: s["bbox"][0]))


# Acentos que el PDF guarda como un glifo suelto encima de la letra.
_ACCENTS = {
    "ˆ": "\\hat", "^": "\\hat", "˜": "\\tilde", "~": "\\tilde",
    "¯": "\\bar", "ˉ": "\\bar", "˙": "\\dot", "¨": "\\ddot",
    "ˇ": "\\check", "˘": "\\breve", "→": "\\vec", "⃗": "\\vec",
}
_WIDE_ACCENTS = {"b": "\\widehat", "c": "\\widehat", "d": "\\widehat",
                 "e": "\\widetilde", "f": "\\widetilde", "g": "\\widetilde"}


def _accent_of(span: dict) -> Optional[str]:
    text = span["text"].strip()
    if "latex" in span or len(text) != 1:
        return None
    if EXTENSION_FONT_RE.search(span.get("font", "")):
        return _WIDE_ACCENTS.get(text)
    return _ACCENTS.get(text)


def _attach_accents(items: list[dict]) -> list[dict]:
    """X con un ˆ suelto encima → \\hat{X}."""
    for acento in [it for it in items if _accent_of(it)]:
        comando = _accent_of(acento)
        ax, ay = _center(acento["bbox"])
        # La letra que tiene debajo. Algunos PDF dan a todos los glifos de un
        # renglón la misma caja de alto, así que basta con que no quede por
        # encima del acento.
        debajo = [
            it for it in items
            if it is not acento and "latex" not in it and not _accent_of(it)
            and it["bbox"][0] - 1 <= ax <= it["bbox"][2] + 1
            and _center(it["bbox"])[1] >= ay - 0.5
            and it["bbox"][3] >= acento["bbox"][3] - 1
            and it["bbox"][1] - acento["bbox"][3] < 0.5 * it["size"]
        ]
        if not debajo:
            continue
        base = min(debajo, key=lambda it: (_center(it["bbox"])[1] - ay, abs(_center(it["bbox"])[0] - ax)))
        text = base["text"].strip()
        if not text:
            continue
        # Si el fragmento tiene varias letras, el acento va sobre la que tiene
        # justo debajo; se calcula por la posición, a partes iguales.
        x0, x1 = base["bbox"][0], base["bbox"][2]
        ancho = (x1 - x0) / len(text) or 1.0
        i = min(len(text) - 1, max(0, int((ax - x0) / ancho)))
        trozos = []
        for desde, hasta in ((0, i), (i + 1, len(text))):
            if desde < hasta:
                trozo = dict(base)
                trozo["text"] = text[desde:hasta]
                trozo["bbox"] = (x0 + desde * ancho, base["bbox"][1], x0 + hasta * ancho, base["bbox"][3])
                trozos.append(trozo)
        letra = dict(base)
        letra["text"] = text[i]
        letra["latex"] = comando + "{" + _span_text(letra) + "}"
        letra["bbox"] = (x0 + i * ancho, base["bbox"][1], x0 + (i + 1) * ancho, base["bbox"][3])
        items = [it for it in items if it is not acento and it is not base] + trozos + [letra]
    return items


def _stack_fractions(items: list[dict], bars: list[tuple]) -> list[dict]:
    """
    Cambia cada fracción por una pieza \\frac{…}{…}. Se empieza por las rayas
    más cortas, que son las de dentro: así una fracción dentro de otra ya está
    armada cuando se llega a la de fuera.
    """
    for x0, y0, x1, y1 in sorted(bars, key=lambda b: b[2] - b[0]):
        eje = (y0 + y1) / 2

        def lado(arriba: bool) -> list[dict]:
            cerca = []
            for it in items:
                caja = it["bbox"]
                if caja[0] < x0 - 3 or caja[2] > x1 + 3:
                    continue
                hueco = eje - caja[3] if arriba else caja[1] - eje
                if -1.0 <= hueco < 1.6 * it["size"]:
                    cerca.append(it)
            return cerca

        num, den = lado(True), lado(False)
        if not num and den:
            # Una raya con algo solo debajo y un √ justo a su izquierda es el
            # trazo de una raíz: lo de debajo es el radicando.
            signo = [
                it for it in items
                if _is_radical(it) and "latex" not in it
                and x0 - 4 <= it["bbox"][2] <= x0 + 3
            ]
            if signo:
                size = max(it["size"] for it in den)
                latex = "\\sqrt{" + _layout(den) + "}"
                usados = {id(it) for it in den + signo[:1]}
                items = [it for it in items if id(it) not in usados]
                items.append(_piece(latex, den + signo[:1], eje + 0.6 * size, size))
            continue
        if not num or not den:
            continue            # un subrayado, el filete de una tabla…
        size = max(it["size"] for it in num + den)
        latex = "\\frac{" + _layout(num) + "}{" + _layout(den) + "}"
        usados = {id(it) for it in num + den}
        items = [it for it in items if id(it) not in usados]
        items.append(_piece(latex, num + den, eje, size))
    return items


def _chains(items: list[dict], gap: float) -> list[list[dict]]:
    """Agrupa en tramos los fragmentos seguidos en horizontal."""
    tramos: list[list[dict]] = []
    for it in sorted(items, key=lambda s: s["bbox"][0]):
        if tramos and it["bbox"][0] - max(s["bbox"][2] for s in tramos[-1]) < gap:
            tramos[-1].append(it)
        else:
            tramos.append([it])
    return tramos


def _span_x(items: list[dict]) -> tuple[float, float]:
    return min(s["bbox"][0] for s in items), max(s["bbox"][2] for s in items)


# ────────────────────────────────────────────────────────────
# Matrices y casos: delimitadores altos
# ────────────────────────────────────────────────────────────

# Las piezas con que se componen los paréntesis, corchetes y llaves grandes.
# Llegan con los códigos de uso privado de la codificación Symbol de Adobe
# (U+F8E5…U+F8FE) o en las posiciones 0x30-0x43 de la fuente de extensión.
_PIECES: dict[str, str] = {}
for _kind, _codes in {
    "(": "\x30\x40\x42", ")": "\x31\x41\x43",
    "[": "\x32\x34\x36", "]": "\x33\x35\x37",
    # El tramo recto de las llaves (U+F8F4, 0x3E) es el mismo para las dos;
    # se cuenta como de la izquierda, que es la de los casos.
    "\\{": "\x38\x3a\x3c\x3e", "\\}": "\x39\x3b\x3d",
}.items():
    for _code in _codes:
        _PIECES[_code] = _kind

_MATRIX_ENV = {"(": "pmatrix", "[": "bmatrix", "\\{": "Bmatrix", "|": "vmatrix"}
_CLOSING = {"(": ")", "[": "]", "\\{": "\\}", "|": "|"}


def _delimiter_kind(span: dict) -> Optional[str]:
    """Qué delimitador es un glifo de la fuente de extensión, o None."""
    if not EXTENSION_FONT_RE.search(span.get("font", "")) or "latex" in span:
        return None
    text = span["text"].strip()
    if text and all(c in _PIECES for c in text):
        kinds = {_PIECES[c] for c in text}
        return kinds.pop() if len(kinds) == 1 else None
    latex = BIG_DELIMITERS.get(text) if len(text) == 1 else None
    return latex if latex in _MATRIX_ENV or latex in _CLOSING.values() else None


def _delimiter_box(span: dict) -> tuple:
    """
    La caja de verdad de un delimitador. Las piezas traen una aceptable; los
    de tamaño fijo cuelgan de su origen y miden, según la posición que
    ocupan en la fuente, 1,2, 1,8, 2,4 o 3 veces el cuerpo.
    """
    text = span["text"].strip()
    x0, _, x1, _ = span["bbox"]
    if len(text) != 1 or text in _PIECES:
        return tuple(span["bbox"])
    code = ord(text)
    if code < 0x10:
        alto = 1.2
    elif code < 0x12 or 0x44 <= code <= 0x45 or 0x68 <= code <= 0x6F:
        alto = 1.8
    elif code < 0x20:
        alto = 2.4
    else:
        alto = 3.0
    arriba = min(span["origin"][1], span["bbox"][1])
    return (x0, arriba, x1, arriba + alto * span["size"])


def _tall_delimiters(items: list[dict]) -> list[tuple[str, tuple, list[dict]]]:
    """
    Delimitadores que abarcan varios renglones: (tipo, caja, piezas). Las
    piezas de uno grande van en la misma columna, una encima de otra.
    """
    size, _ = _line_baseline(items)
    candidatos = sorted(
        ((k, it) for it in items if (k := _delimiter_kind(it))),
        key=lambda par: (round(par[1]["bbox"][0]), par[1]["bbox"][1]),
    )
    altos: list[tuple[str, tuple, list[dict]]] = []
    for kind, it in candidatos:
        caja = _delimiter_box(it)
        if altos:
            k, c, piezas = altos[-1]
            if k == kind and abs(c[0] - caja[0]) < 3 and caja[1] - c[3] < 1.2 * size:
                altos[-1] = (k, _union([c, caja]), piezas + [it])
                continue
        altos.append((kind, caja, [it]))
    return [a for a in altos if a[1][3] - a[1][1] >= 1.8 * size]


def _cells(row: list[dict], gap: float) -> list[str]:
    """Las celdas de un renglón de una matriz: lo separado por huecos anchos."""
    return [_layout(tramo) for tramo in _chains(row, gap)]


def _matrices(items: list[dict], sin_rayas: bool = False) -> list[dict]:
    """
    Matrices (un delimitador alto a cada lado) y casos (una llave alta sola a
    la izquierda): se arman como pmatrix/bmatrix o cases, celda a celda.
    """
    altos = _tall_delimiters(items)
    if not altos:
        return items
    size, _ = _line_baseline(items)
    usados: set[int] = set()
    nuevas: list[dict] = []
    for i, (kind, caja, piezas) in enumerate(altos):
        if any(id(p) in usados for p in piezas) or kind in (")", "]", "\\}"):
            continue
        cierre = None
        for kind2, caja2, piezas2 in altos[i + 1:]:
            solape = min(caja[3], caja2[3]) - max(caja[1], caja2[1])
            if (kind2 == _CLOSING.get(kind) and caja2[0] > caja[2]
                    and solape > 0.7 * (caja[3] - caja[1])):
                cierre = (caja2, piezas2)
                break
        derecha = cierre[0][0] if cierre else float("inf")
        dentro = [
            it for it in items
            if id(it) not in usados and it not in piezas
            and caja[2] - 1 <= _center(it["bbox"])[0] < derecha
            and caja[1] - 0.6 * size <= _center(it["bbox"])[1] <= caja[3] + 0.6 * size
        ]
        filas = _rows(dentro)
        if len(filas) < 2:
            continue
        # Sin rayas en el PDF, un paréntesis alto alrededor de una fracción
        # (numerador y denominador aún sueltos) parece una matriz de dos
        # renglones: se pide más para creérselo.
        if sin_rayas and cierre and len(filas) == 2 and not all(
            len(_chains(f, 0.9 * size)) > 1 for f in filas
        ):
            continue
        if cierre:
            cuerpo = " \\\\ ".join(" & ".join(_cells(f, 0.9 * size)) for f in filas)
            latex = "\\begin{" + _MATRIX_ENV[kind] + "} " + cuerpo + " \\end{" + _MATRIX_ENV[kind] + "}"
            partes = piezas + cierre[1] + dentro
        elif kind == "\\{":
            renglones = []
            for fila in filas:
                tramos = _chains(fila, 0.9 * size)
                if len(tramos) > 1:
                    renglones.append(_layout(tramos[0]) + " & " + _layout([s for t in tramos[1:] for s in t]))
                else:
                    renglones.append(_layout(fila))
            latex = "\\begin{cases} " + " \\\\ ".join(renglones) + " \\end{cases}"
            partes = piezas + dentro
        else:
            continue
        usados.update(id(p) for p in partes)
        nuevas.append(_piece(latex, partes, (caja[1] + caja[3]) / 2, size))
    if not nuevas:
        return items
    return [it for it in items if id(it) not in usados] + nuevas


def _is_radical(span: dict) -> bool:
    """El signo √, sea el carácter Unicode o el de la fuente de extensión."""
    text = span["text"].strip()
    if text == "√":
        return True
    return text in ("p", "q", "r", "s") and bool(EXTENSION_FONT_RE.search(span.get("font", "")))


def _virtual_fractions(items: list[dict]) -> list[dict]:
    """
    Fracciones sin raya. Algunos PDF (los que pasan por Ghostscript, por
    ejemplo) no guardan la raya como un dibujo, y solo queda la geometría:
    algo a cuerpo normal por encima del renglón, algo por debajo, en la misma
    columna, y nada del renglón en medio. Es lo que hacen los programas de
    reconocimiento por maquetación (Infty, MaxTract): deducir la estructura de
    las posiciones relativas.
    """
    size, _ = _line_baseline(items)
    if size <= 0:
        return items
    normales = [it for it in items if it["size"] >= size - 0.6]
    # Cada renglón posible, empezando por el que tiene más fragmentos.
    cuenta: dict[float, int] = {}
    for it in normales:
        y = round(it["origin"][1])
        cuenta[y] = cuenta.get(y, 0) + 1
    for base in sorted(cuenta, key=lambda y: -cuenta[y]):
        presentes = {id(it) for it in items}
        renglon = [it for it in normales if id(it) in presentes and abs(it["origin"][1] - base) < 0.25 * size]
        if not renglon:
            continue
        arriba = [it for it in normales if id(it) in presentes
                  and 0.3 * size < base - it["origin"][1] < 1.2 * size]
        abajo = [it for it in normales if id(it) in presentes
                 and 0.3 * size < it["origin"][1] - base < 1.2 * size]
        if not arriba or not abajo:
            continue
        for num in _chains(arriba, 0.6 * size):
            nx0, nx1 = _span_x(num)
            for den in _chains(abajo, 0.6 * size):
                dx0, dx1 = _span_x(den)
                solape = min(nx1, dx1) - max(nx0, dx0)
                if solape < 0.5 * min(nx1 - nx0, dx1 - dx0):
                    continue
                x0, x1 = min(nx0, dx0), max(nx1, dx1)
                # Si el renglón pasa por esa columna, no es una fracción sino
                # otro renglón (o un índice).
                if any(r["bbox"][0] < x1 - 1 and r["bbox"][2] > x0 + 1 for r in renglon):
                    continue
                if any(id(it) not in presentes for it in num + den):
                    continue
                # Los índices del numerador y del denominador van con ellos.
                metidos = {id(it) for it in num + den}
                for it in items:
                    if id(it) in metidos or it["size"] >= size - 0.6:
                        continue
                    cx = _center(it["bbox"])[0]
                    if not x0 - 1 <= cx <= x1 + 1:
                        continue
                    dy = it["origin"][1] - base
                    if -1.6 * size < dy < -0.1 * size:
                        num = num + [it]
                    elif 0.1 * size < dy < 1.6 * size:
                        den = den + [it]
                latex = "\\frac{" + _layout(num) + "}{" + _layout(den) + "}"
                usados = {id(it) for it in num + den}
                items = [it for it in items if id(it) not in usados]
                items.append(_piece(latex, num + den, base - 0.25 * size, size))
                presentes = {id(it) for it in items}
                break
    return items


def _attach_limits(items: list[dict]) -> list[dict]:
    """∑ con un índice debajo y otro encima → \\sum_{abajo}^{arriba}."""
    operadores: list[tuple[dict, str, bool]] = []
    for op in items:
        if "latex" in op:
            continue
        text = op["text"].strip()
        extension = EXTENSION_FONT_RE.search(op.get("font", ""))
        command = (
            (BIG_OPERATORS.get(_unshift(text)) if extension else None)
            or _UNICODE_BIG_OPERATORS.get(text)
            or ("\\" + text if text in _LIMIT_WORDS else None)
        )
        # Una palabra con algo escrito debajo: «minimize» sobre sus variables.
        palabra = command is None and re.fullmatch(r"[A-Za-z]{3,}", text) is not None
        if palabra:
            command = "\\text{" + text + "}"
        if command and command not in ("\\int", "\\oint"):
            # (las integrales llevan los límites a la derecha)
            operadores.append((op, command, palabra))
    if not operadores:
        return items

    # Cada trozo pequeño de debajo o de encima es límite del operador más
    # cercano: en «min lím» cada uno se queda con el suyo.
    limites: dict[int, tuple[list[dict], list[dict]]] = {id(op): ([], []) for op, _, _ in operadores}
    for it in items:
        cx, cy = _center(it["bbox"])
        mejor = None
        for op, _, _ in operadores:
            caja = op["bbox"]
            ancho, alto = caja[2] - caja[0], caja[3] - caja[1]
            # Los límites van en letra más pequeña. Se mira el centro: las
            # cajas de las letras llevan aire de sobra y se solapan.
            if it is op or it["size"] > op["size"] - 0.4:
                continue
            if caja[3] - 0.2 * alto < cy < caja[3] + 1.6 * alto:
                lado, margen = 0, ancho
            elif caja[1] - 1.6 * alto < cy < caja[1] + 0.2 * alto:
                lado, margen = 1, 0.3 * ancho
            else:
                continue
            if not caja[0] - margen <= cx <= caja[2] + margen:
                continue
            distancia = abs(cx - _center(caja)[0])
            if mejor is None or distancia < mejor[0]:
                mejor = (distancia, op, lado)
        if mejor:
            limites[id(mejor[1])][mejor[2]].append(it)

    for op, command, palabra in operadores:
        abajo, arriba = limites[id(op)]
        caja = op["bbox"]
        if not abajo and not arriba:
            continue
        if palabra:
            if not abajo or arriba:
                continue
            latex = "\\underset{" + _layout(abajo) + "}{" + command + "}"
        else:
            latex = command
            filas = _rows(abajo) if abajo else []
            if len(filas) > 1:
                # Varias condiciones una debajo de otra: \inf_{\substack{t∈J \\ x∈Ω}}
                latex += "_{\\substack{" + " \\\\ ".join(_layout(f) for f in filas) + "}}"
            elif abajo:
                latex += "_{" + _layout(abajo) + "}"
            if arriba:
                latex += "^{" + _layout(arriba) + "}"
        usados = {id(op)} | {id(it) for it in abajo + arriba}
        resto = [it for it in items if id(it) not in usados]
        size = max((it["size"] for it in resto), default=op["size"])
        items = resto + [_piece(latex, [op, *abajo, *arriba], _center(caja)[1], size)]
    return items


def _rows(items: list[dict]) -> list[list[dict]]:
    """
    Reparte los fragmentos en renglones. Los de cuerpo normal marcan dónde
    está cada renglón; los índices van con el renglón que les queda más cerca.
    """
    if not items:
        return []
    cuerpo, _ = _line_baseline(items)
    normales = sorted(
        (it for it in items if it["size"] >= cuerpo - 0.6),
        key=lambda it: it["origin"][1],
    )
    bases: list[float] = []
    for it in normales:
        y = it["origin"][1]
        if not bases or y - bases[-1] > 0.9 * cuerpo:
            bases.append(y)
    filas: list[list[dict]] = [[] for _ in bases]
    for it in items:
        y = it["origin"][1]
        cerca = min(range(len(bases)), key=lambda i: abs(bases[i] - y))
        filas[cerca].append(it)
    return [f for f in filas if f]


def expand_region(page, rect: tuple) -> tuple:
    """
    Amplía la región de una ecuación hacia los lados con los trozos de la misma
    altura que tiene pegados. La detección se queda a veces con un pedazo (la
    fracción y poco más) y el resto de la línea —el sumatorio, el signo igual—
    se perdería. El hueco admitido es corto para no saltar a la otra columna.
    """
    renglones = _lines_with_spans(page)
    centro_y = (rect[1] + rect[3]) / 2
    while True:
        creciendo = rect
        for caja, spans in renglones:
            _, cy = _center(caja)
            if not rect[1] - 2 <= cy <= rect[3] + 2 or _dentro(caja, rect, 1.0):
                continue
            if not caja[1] <= centro_y <= caja[3] and not _intersecta(caja, rect):
                continue
            hueco = max(caja[0] - rect[2], rect[0] - caja[2], 0.0)
            size = max(s["size"] for s in spans)
            total, math_chars = _math_ratio(spans)
            if hueco < 1.2 * size and (total == 0 or math_chars / total >= 0.5):
                rect = _union([rect, caja])
        if rect == creciendo:
            return rect


_EQUATION_NUMBER = re.compile(r"^\(\d{1,3}[a-z]?\)$")


def reconstruct_region(page, rect: tuple) -> Optional[str]:
    """
    LaTeX de una ecuación destacada leyendo toda su región a la vez: las
    fracciones se arman con su raya y los sumatorios con sus límites, en vez
    de leer renglón a renglón, que deja el numerador y el denominador uno
    detrás del otro.
    """
    todos = [dict(span) for _, spans in _lines_with_spans(page) for span in spans]
    items = [it for it in todos if _dentro(tuple(it["bbox"]), rect, 2.0)]
    if not items:
        return None
    # Lo pequeño que asoma por arriba o por abajo (el límite de una integral,
    # el signo de una raíz) también es de la fórmula, aunque la caja que da
    # el extractor lo deje fuera.
    cuerpo = max(it["size"] for it in items)
    for it in todos:
        cx, cy = _center(it["bbox"])
        if (it not in items and rect[0] - 2 <= cx <= rect[2] + 2
                and rect[1] - 0.8 * cuerpo <= cy <= rect[3] + 0.8 * cuerpo
                and (it["size"] < cuerpo - 0.5 or _is_radical(it)
                     or _intersecta(tuple(it["bbox"]), rect))):
            items.append(it)
    # El número de la ecuación, «(5)» suelto a la derecha, no es parte de ella.
    derecha = max((it["bbox"][2] for it in items if not _EQUATION_NUMBER.match(it["text"].strip())),
                  default=0.0)
    items = [
        it for it in items
        if not (_EQUATION_NUMBER.match(it["text"].strip()) and it["bbox"][0] > derecha + 5)
    ]
    if not items:
        return None
    bars = [b for b in _fraction_bars(page) if _dentro(b, rect, 2.0)]
    items = _attach_accents(items)
    items = _stack_fractions(items, bars)
    # Las matrices antes que las fracciones sin raya: sus renglones, uno
    # encima de otro, se confundirían con numeradores y denominadores.
    items = _matrices(items, sin_rayas=not bars)
    if not bars:
        items = _virtual_fractions(items)
    # Después de las fracciones: así sus numeradores ya no despistan al buscar
    # el renglón en que está cada glifo grande.
    items = _normalize_extension(items)
    items = _attach_limits(items)
    filas = [_layout(fila) for fila in _rows(items)]
    filas = [f for f in filas if f]
    if not filas:
        return None
    if len(filas) == 1:
        return filas[0]
    return "\\begin{aligned} " + " \\\\ ".join(filas) + " \\end{aligned}"


# ────────────────────────────────────────────────────────────
# ¿Cuadra una lectura del OCR con los glifos del PDF?
# ────────────────────────────────────────────────────────────

_ATOM = re.compile(r"\\[A-Za-z]+|\\.|[^\s{}^_&$]")
# Lo que da forma a la fórmula pero no es ningún glifo.
_STRUCTURE = {
    "\\frac", "\\dfrac", "\\tfrac", "\\left", "\\right", "\\big", "\\Big", "\\bigg",
    "\\Bigg", "\\bigl", "\\bigr", "\\Bigl", "\\Bigr", "\\mathrm", "\\text", "\\mathbb",
    "\\mathcal", "\\mathbf", "\\boldsymbol", "\\mathit", "\\mathsf", "\\mathfrak",
    "\\operatorname", "\\begin", "\\end", "\\\\", "\\,", "\\;", "\\:", "\\!", "\\quad",
    "\\qquad", "\\displaystyle", "\\textstyle", "\\limits", "\\nolimits", "\\underset",
    "\\overset", "\\mathop", "\\hat", "\\bar", "\\tilde", "\\vec", "\\dot", "\\ddot",
    "\\widehat", "\\widetilde", "\\overline", "\\underline", "\\sqrt", "\\surd", "\\ ",
    "\\bigm", "\\Bigm", "\\biggm", "\\Biggm", "\\biggl", "\\biggr", "\\Biggl", "\\Biggr",
    "\\middle", "\\substack", "\\boldsymbol", "\\mathscr", "\\textstyle", "\\scriptstyle",
}
_ENVIRONMENTS = re.compile(r"\\(begin|end)\{[^{}]*\}")
_ATOM_SYNONYMS = {
    "\\to": "\\rightarrow", "\\le": "\\leq", "\\ge": "\\geq", "\\ne": "\\neq",
    "\\cdots": "\\dots", "\\ldots": "\\dots", "\\varepsilon": "\\epsilon",
    "\\varphi": "\\phi", "\\vert": "|", "\\mid": "|", "\\lbrace": "\\{", "\\rbrace": "\\}",
    "\\colon": ":", "\\ast": "*", "\\Vert": "\\|", "\\parallel": "\\|",
}


def latex_atoms(latex: str) -> list[str]:
    """
    Los glifos que pinta una fórmula: letras, cifras y símbolos, sin la
    estructura (llaves, \\frac, \\left…). \\lim cuenta como l, i, m, que es
    lo que hay en el PDF.
    """
    # Los glifos del PDF pueden venir aún sin traducir (letras matemáticas
    # recortadas, símbolos Unicode): se traducen igual que en el documento.
    latex = mathfix._translate_inside_math(mathfix.repair_truncated_alphanumerics(latex))
    atoms: list[str] = []
    for token in _ATOM.findall(_ENVIRONMENTS.sub(" ", latex)):
        token = _ATOM_SYNONYMS.get(token, token)
        if token in _STRUCTURE:
            continue
        if token[1:] in mathfix.FUNCTIONS:
            atoms.extend(token[1:])
        else:
            atoms.append(token)
    return atoms


def agreement(latex: str, reference: str) -> float:
    """
    Cuánto se parecen los glifos de dos fórmulas (1 = los mismos), sin mirar
    cómo están colocados. La reconstrucción por geometría lee los glifos
    exactos del PDF aunque los coloque mal; el OCR los coloca bien pero a
    veces se inventa alguno. Si los glifos del OCR son los del PDF, su
    colocación es de fiar.
    """
    from collections import Counter

    a, b = Counter(latex_atoms(latex)), Counter(latex_atoms(reference))
    total = sum(a.values()) + sum(b.values())
    if not total:
        return 0.0
    return 2 * sum((a & b).values()) / total


def region_plain_text(page, rect) -> str:
    """
    Texto que el extractor saca de una región, en el mismo orden en que lo va
    a escribir.

    Hace falta porque una ecuación centrada no siempre acaba convertida en
    imagen: según cómo se hayan cargado las bibliotecas, el extractor la
    devuelve como texto suelto y descuadrado. Teniendo ese texto se puede
    localizar y cambiar por la reconstrucción, salga como salga.
    """
    piezas = [
        "".join(span["text"] for span in spans).strip()
        for caja, spans in _lines_with_spans(page)
        if _dentro(caja, rect, 2.0)
    ]
    return "".join(pieza for pieza in piezas if pieza)


def pattern_for_plain(plain: str) -> str:
    """Patrón tolerante para localizar ese texto dentro del Markdown."""
    return _tolerant_plain_pattern([plain])


def has_font_math(page) -> bool:
    """¿La página usa fuentes matemáticas? Sirve para avisar al usuario."""
    try:
        return any(MATH_FONT_RE.search(font[3] or "") for font in page.get_fonts(full=False))
    except Exception:
        return False
