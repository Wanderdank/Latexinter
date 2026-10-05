"""
formulas.py - Sacar las fórmulas de un .tex y compararlas con las originales.

Dos .tex que se ven igual pueden escribirse muy distinto: «x^{2}» y «x^2»,
«\\le» y «\\leq», «\\left(» y «(». Antes de comparar, cada fórmula se pasa a
una lista de piezas («tokens») sin esas diferencias de forma. Lo que queda
distinto es un error de verdad: un índice perdido, una fracción aplanada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ────────────────────────────────────────────────────────────
# Comentarios y macros del autor
# ────────────────────────────────────────────────────────────

def strip_comments(tex: str) -> str:
    """Quita los comentarios (% hasta el final de la línea, salvo «\\%»)."""
    return re.sub(r"(?<!\\)%.*", "", tex)


def _group(tex: str, inicio: int) -> tuple[str, int] | None:
    """El grupo entre llaves que empieza en 'inicio' y dónde acaba."""
    i = inicio
    while i < len(tex) and tex[i] in " \t\n":
        i += 1
    if i >= len(tex):
        return None
    if tex[i] != "{":
        # Un argumento sin llaves es una sola pieza: \frac12, \mathbb R.
        if tex[i] == "\\":
            m = re.match(r"\\([a-zA-Z]+|.)", tex[i:])
            return m.group(0), i + m.end()
        return tex[i], i + 1
    nivel = 0
    for j in range(i, len(tex)):
        c = tex[j]
        if c == "\\":
            continue
        if c == "{" and tex[j - 1] != "\\":
            nivel += 1
        elif c == "}" and tex[j - 1] != "\\":
            nivel -= 1
            if nivel == 0:
                return tex[i + 1:j], j + 1
    return None


_RE_NEWCOMMAND = re.compile(
    r"\\(?:re|provide)?newcommand\*?\s*\{?\s*(\\[a-zA-Z]+)\s*\}?\s*(?:\[(\d)\])?\s*(\[[^\]]*\])?\s*\{"
)
_RE_DEF = re.compile(r"\\def\s*(\\[a-zA-Z]+)\s*((?:#\d)*)\s*\{")
_RE_OPERATOR = re.compile(r"\\DeclareMathOperator\*?\s*\{?\s*(\\[a-zA-Z]+)\s*\}?\s*\{")


def find_macros(tex: str) -> dict[str, tuple[int, str]]:
    """
    Las macros que define el autor: nombre → (argumentos, cuerpo). Las que
    tienen un argumento opcional se ignoran: son raras en fórmulas y
    expandirlas bien obligaría a imitar a TeX.
    """
    macros: dict[str, tuple[int, str]] = {}
    for patron in (_RE_NEWCOMMAND, _RE_DEF, _RE_OPERATOR):
        for m in patron.finditer(tex):
            cuerpo = _group(tex, m.end() - 1)
            if cuerpo is None:
                continue
            nombre = m.group(1)
            if patron is _RE_NEWCOMMAND:
                if m.group(3):
                    continue
                macros[nombre] = (int(m.group(2) or 0), cuerpo[0])
            elif patron is _RE_DEF:
                macros[nombre] = (len(m.group(2)) // 2, cuerpo[0])
            else:
                macros[nombre] = (0, f"\\operatorname{{{cuerpo[0]}}}")
    return macros


def expand_macros(tex: str, macros: dict[str, tuple[int, str]], pasadas: int = 6) -> str:
    """Sustituye las macros del autor por lo que significan."""
    if not macros:
        return tex
    nombres = sorted(macros, key=len, reverse=True)
    patron = re.compile("(" + "|".join(re.escape(n) for n in nombres) + r")(?![a-zA-Z])")

    for _ in range(pasadas):
        partes: list[str] = []
        pos = 0
        cambio = False
        for m in patron.finditer(tex):
            if m.start() < pos:
                continue
            argumentos, cuerpo = macros[m.group(1)]
            fin = m.end()
            valores = []
            for _ in range(argumentos):
                grupo = _group(tex, fin)
                if grupo is None:
                    break
                valores.append(grupo[0])
                fin = grupo[1]
            if len(valores) < argumentos:
                continue
            for n, valor in enumerate(valores, 1):
                cuerpo = cuerpo.replace(f"#{n}", valor)
            # Se separa con espacios para no pegar \alpha con la letra siguiente.
            partes.append(tex[pos:m.start()] + " " + cuerpo + " ")
            pos = fin
            cambio = True
        partes.append(tex[pos:])
        tex = "".join(partes)
        if not cambio:
            break
    return tex


# ────────────────────────────────────────────────────────────
# Extraer fórmulas
# ────────────────────────────────────────────────────────────

ENTORNOS_DESTACADOS = (
    "equation", "align", "gather", "multline", "flalign", "alignat",
    "eqnarray", "displaymath", "dmath", "math",
)
_RE_ENTORNO = re.compile(
    r"\\begin\{(" + "|".join(ENTORNOS_DESTACADOS) + r")(\*?)\}(\{\d+\})?"
)
_RE_IGNORAR = re.compile(r"\\begin\{(verbatim|lstlisting|minted|comment)\*?\}")


@dataclass
class Formula:
    text: str
    display: bool
    tokens: list[str] = field(default_factory=list)


def _split_rows(cuerpo: str) -> list[str]:
    """
    Parte un bloque destacado en sus filas («\\\\»), pero no las de una
    matriz o un array que vaya dentro.
    """
    filas, actual = [], []
    nivel = 0
    i = 0
    while i < len(cuerpo):
        if cuerpo.startswith("\\begin{", i):
            nivel += 1
        elif cuerpo.startswith("\\end{", i):
            nivel -= 1
        c = cuerpo[i]
        if c == "{":
            nivel += 1
        elif c == "}":
            nivel -= 1
        if cuerpo.startswith("\\\\", i) and nivel == 0:
            filas.append("".join(actual))
            actual = []
            i += 2
            continue
        if c == "\\" and i + 1 < len(cuerpo):
            actual.append(cuerpo[i:i + 2])
            i += 2
            continue
        actual.append(c)
        i += 1
    filas.append("".join(actual))
    return [f for f in filas if f.strip()]


def extract(tex: str) -> list[Formula]:
    """Las fórmulas del documento, en orden, con las filas por separado."""
    tex = strip_comments(tex)
    inicio = tex.find("\\begin{document}")
    if inicio >= 0:
        tex = tex[inicio + len("\\begin{document}"):]

    formulas: list[Formula] = []

    def anadir(texto: str, display: bool) -> None:
        filas = _split_rows(texto) if display else [texto]
        for fila in filas:
            tokens = normalize(fila)
            if tokens:
                formulas.append(Formula(fila.strip(), display, tokens))

    i = 0
    n = len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            m = _RE_IGNORAR.match(tex, i)
            if m:
                fin = tex.find(f"\\end{{{m.group(1)}", m.end())
                i = n if fin < 0 else fin + 1
                continue
            m = _RE_ENTORNO.match(tex, i)
            if m:
                cierre = f"\\end{{{m.group(1)}{m.group(2)}}}"
                fin = tex.find(cierre, m.end())
                if fin < 0:
                    break
                anadir(tex[m.end():fin], display=m.group(1) != "math")
                i = fin + len(cierre)
                continue
            if tex.startswith("\\[", i) or tex.startswith("\\(", i):
                cierre = "\\]" if tex[i + 1] == "[" else "\\)"
                fin = tex.find(cierre, i + 2)
                if fin < 0:
                    break
                anadir(tex[i + 2:fin], display=cierre == "\\]")
                i = fin + 2
                continue
            i += 2                                   # \$, \\, \{ y demás
            continue
        if c == "$":
            doble = tex.startswith("$$", i)
            delim = "$$" if doble else "$"
            j = i + len(delim)
            while j < n:
                if tex[j] == "\\":
                    j += 2
                    continue
                if tex.startswith(delim, j):
                    break
                j += 1
            if j >= n:
                break
            anadir(tex[i + len(delim):j], display=doble)
            i = j + len(delim)
            continue
        i += 1
    return formulas


# ────────────────────────────────────────────────────────────
# Normalizar
# ────────────────────────────────────────────────────────────

_RE_TOKEN = re.compile(r"\\[a-zA-Z]+\*?|\\.|[^\s]")

# Lo que no cambia lo que se ve, o lo cambia tan poco que no es un error.
_SOBRAN = {
    "\\left", "\\right", "\\middle", "\\displaystyle", "\\textstyle",
    "\\scriptstyle", "\\scriptscriptstyle", "\\limits", "\\nolimits",
    "\\big", "\\Big", "\\bigg", "\\Bigg", "\\bigl", "\\bigr", "\\Bigl",
    "\\Bigr", "\\biggl", "\\biggr", "\\Biggl", "\\Biggr", "\\bigm", "\\Bigm",
    "\\,", "\\;", "\\:", "\\!", "\\ ", "\\quad", "\\qquad", "~",
    "\\nonumber", "\\notag", "&", "\\allowbreak", "\\nobreak",
}
# Comandos con argumento que no aportan nada a la fórmula.
_SOBRAN_CON_ARGUMENTO = {"\\label", "\\tag", "\\hspace", "\\vspace", "\\hspace*",
                         "\\vspace*", "\\phantom", "\\hphantom", "\\vphantom"}
# Cambian la letra pero no el contenido: se quitan y se queda lo de dentro.
_SOLO_FORMA = {"\\mathrm", "\\text", "\\textrm", "\\mbox", "\\textnormal",
               "\\operatorname", "\\mathit", "\\textit", "\\mathnormal", "\\hbox"}
_SINONIMOS = {
    "\\le": "\\leq", "\\ge": "\\geq", "\\ne": "\\neq", "\\to": "\\rightarrow",
    "\\gets": "\\leftarrow", "\\lbrace": "\\{", "\\rbrace": "\\}",
    "\\vert": "|", "\\lvert": "|", "\\rvert": "|", "\\mid": "|",
    "\\lVert": "\\|", "\\rVert": "\\|", "\\Vert": "\\|",
    "\\ldots": "\\dots", "\\cdots": "\\dots", "\\dotsc": "\\dots",
    "\\dotsb": "\\dots", "\\dotsm": "\\dots", "\\colon": ":",
    "\\lbrack": "[", "\\rbrack": "]",
    "\\land": "\\wedge", "\\lor": "\\vee", "\\lnot": "\\neg",
    "\\ast": "*", "\\dfrac": "\\frac", "\\tfrac": "\\frac", "\\varepsilon": "\\epsilon",
    "\\varphi": "\\phi", "\\emptyset": "\\varnothing",
}


def normalize(formula: str) -> list[str]:
    """La fórmula como lista de piezas, sin lo que no cambia lo que se ve."""
    tokens = _RE_TOKEN.findall(formula)

    limpios: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _SOBRAN_CON_ARGUMENTO:
            i = _skip_group(tokens, i + 1)
            continue
        if t in _SOLO_FORMA:
            i += 1
            continue
        if t not in _SOBRAN:
            limpios.append(_SINONIMOS.get(t, t))
        i += 1

    limpios = _drop_single_braces(limpios)
    # «x^{\prime}» y «x'» son lo mismo.
    limpios = _replace_seq(limpios, ["^", "\\prime"], ["'"])
    while limpios and limpios[-1] in {",", ".", ";"}:
        limpios.pop()
    return limpios


def _skip_group(tokens: list[str], i: int) -> int:
    if i < len(tokens) and tokens[i] == "{":
        nivel = 0
        while i < len(tokens):
            if tokens[i] == "{":
                nivel += 1
            elif tokens[i] == "}":
                nivel -= 1
                if nivel == 0:
                    return i + 1
            i += 1
        return i
    return i + 1


def _drop_single_braces(tokens: list[str]) -> list[str]:
    """«{x}» → «x», y «{}» fuera: «x^{2}» queda igual que «x^2»."""
    cambio = True
    while cambio:
        cambio = False
        salida: list[str] = []
        i = 0
        while i < len(tokens):
            if tokens[i] == "{" and i + 1 < len(tokens) and tokens[i + 1] == "}":
                i += 2
                cambio = True
                continue
            if (tokens[i] == "{" and i + 2 < len(tokens) and tokens[i + 2] == "}"
                    and tokens[i + 1] not in "{}"):
                salida.append(tokens[i + 1])
                i += 3
                cambio = True
                continue
            salida.append(tokens[i])
            i += 1
        tokens = salida
    return tokens


def _replace_seq(tokens: list[str], buscar: list[str], poner: list[str]) -> list[str]:
    salida: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i:i + len(buscar)] == buscar:
            salida.extend(poner)
            i += len(buscar)
        else:
            salida.append(tokens[i])
            i += 1
    return salida


# ────────────────────────────────────────────────────────────
# Comparar
# ────────────────────────────────────────────────────────────

def similarity(a: list[str], b: list[str]) -> float:
    """1 si son iguales, 0 si no se parecen en nada (distancia de edición)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    anterior = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        actual = [i]
        for j, y in enumerate(b, 1):
            actual.append(min(
                anterior[j] + 1,
                actual[j - 1] + 1,
                anterior[j - 1] + (x != y),
            ))
        anterior = actual
    return 1.0 - anterior[-1] / max(len(a), len(b))


@dataclass
class Match:
    original: Formula
    found: Formula | None
    score: float


def match(originales: list[Formula], encontradas: list[Formula], ventana: int = 40) -> list[Match]:
    """
    Para cada fórmula original, la más parecida de las encontradas. Las dos
    listas van en el orden del documento, así que se busca cerca de donde
    debería estar y no en todo el documento.
    """
    resultado: list[Match] = []
    if not encontradas:
        return [Match(f, None, 0.0) for f in originales]

    escala = len(encontradas) / max(1, len(originales))
    for i, original in enumerate(originales):
        centro = round(i * escala)
        desde = max(0, centro - ventana)
        hasta = min(len(encontradas), centro + ventana + 1)
        mejor, puntos = None, 0.0
        largo = len(original.tokens)
        for candidata in encontradas[desde:hasta]:
            otro = len(candidata.tokens)
            # Si el largo es muy distinto, la nota no puede superar la mejor.
            if 1.0 - abs(largo - otro) / max(largo, otro) <= puntos:
                continue
            s = similarity(original.tokens, candidata.tokens)
            if s > puntos:
                mejor, puntos = candidata, s
                if s == 1.0:
                    break
        resultado.append(Match(original, mejor, puntos))
    return resultado


# ────────────────────────────────────────────────────────────
# Tipos de fórmula, para saber dónde falla
# ────────────────────────────────────────────────────────────

def kinds(formula: Formula) -> set[str]:
    t = formula.tokens
    tipos = {"destacada" if formula.display else "en línea"}
    if len(t) >= 5:
        tipos.add("no trivial")
    if "^" in t or "_" in t:
        tipos.add("índices")
    if "\\frac" in t:
        tipos.add("fracciones")
    if {"\\sum", "\\int", "\\prod", "\\oint", "\\iint", "\\bigcup", "\\bigcap"} & set(t):
        tipos.add("sumas e integrales")
    if "\\sqrt" in t:
        tipos.add("raíces")
    if _RE_MATRIZ.search(formula.text):
        tipos.add("matrices")
    return tipos


_RE_MATRIZ = re.compile(r"\\begin\{(\w*matrix|array|cases)\*?\}")
