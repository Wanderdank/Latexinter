"""
mathocr.py - Reconocimiento de fórmulas a partir de una imagen.

La reconstrucción por geometría (pdfmath) recupera muy bien lo que va en una
sola línea —índices, símbolos, operadores grandes—, pero no puede con lo que
está apilado: una fracción está escrita en el PDF como numerador, raya y
denominador, tres cosas sueltas que ningún extractor de texto sabe volver a
juntar.

Para eso hace falta mirar la fórmula como una imagen. Este módulo envuelve los
modelos que hacen ese trabajo y los deja detrás de una interfaz única:

    from converters.mathocr import get_engine

    motor = get_engine()
    if motor.available:
        latex = motor.recognize(imagen)     # imagen: PIL.Image

El modelo se carga una sola vez y se queda en memoria, porque cargarlo tarda
varios segundos. Nada se importa hasta que de verdad se usa: sin OCR
instalado, el resto de Latexinter funciona igual.
"""

from __future__ import annotations

import importlib.util
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .common import ConversionError, Logger, as_logger

# ────────────────────────────────────────────────────────────
# Motores disponibles
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Backend:
    key: str
    name: str
    module: str
    description: str
    install: str
    size: str

    @property
    def installed(self) -> bool:
        try:
            return importlib.util.find_spec(self.module) is not None
        except (ImportError, ValueError):
            return False


BACKENDS: tuple[Backend, ...] = (
    Backend(
        key="mfr",
        name="Pix2Text-MFR",
        module="onnxruntime",
        description=(
            "El más preciso de los tres y el único que no necesita PyTorch: "
            "funciona con onnxruntime, que ya viene con Latexinter. El modelo "
            "se descarga la primera vez."
        ),
        install="incluido; descarga el modelo la primera vez",
        size="120 MB",
    ),
    Backend(
        key="pix2tex",
        name="LaTeX-OCR (pix2tex)",
        module="pix2tex",
        description=(
            "El más conocido para fórmulas sueltas. Rápido y con un modelo "
            "pequeño; acierta bien con fracciones, raíces, matrices y sumatorios."
        ),
        install="pip install pix2tex",
        size="unos 1,5 GB con PyTorch incluido",
    ),
    Backend(
        key="texify",
        name="Texify",
        module="texify",
        description=(
            "Más moderno y algo más preciso con ecuaciones largas o con texto "
            "mezclado, a cambio de ir más lento."
        ),
        install="pip install texify",
        size="unos 2 GB con PyTorch incluido",
    ),
)

BACKENDS_POR_CLAVE = {b.key: b for b in BACKENDS}


def installed_backends() -> list[Backend]:
    return [b for b in BACKENDS if b.installed]


def any_backend_installed() -> bool:
    return bool(installed_backends())


def install_hint() -> str:
    lineas = ["Para reconocer fórmulas en imagen hace falta un modelo de OCR:"]
    for backend in BACKENDS:
        lineas.append(f"  · {backend.name} — {backend.install}  ({backend.size})")
    return "\n".join(lineas)


# ────────────────────────────────────────────────────────────
# Limpieza del LaTeX que devuelven los modelos
# ────────────────────────────────────────────────────────────

_ENVOLTURAS = (
    (r"^\s*\\\[(.*)\\\]\s*$", 1),
    (r"^\s*\$\$(.*)\$\$\s*$", 1),
    (r"^\s*\\begin\{(?:equation|align|displaymath)\*?\}(.*)"
     r"\\end\{(?:equation|align|displaymath)\*?\}\s*$", 1),
)


# Restos que los modelos añaden por su cuenta: espacios finos sueltos al
# principio o al final, y el punto o la coma que en el original pertenecían a
# la frase y no a la fórmula.
_RUIDO_INICIAL = re.compile(r"^(?:\\[,;!:> ]|\\quad|\\qquad|\s)+")
_RUIDO_FINAL = re.compile(
    r"(?:\\[,;!:> ]|\\quad|\\qquad|\\hspace\*?\{[^{}]*\}|\\vert|\\mid|[.,;|]|\s)$"
)
# El número de la ecuación, que el modelo copia como «\tag*{(14)}».
_ETIQUETA = re.compile(r"\\tag\*?\{[^{}]*\}")
_PIDE_DELIMITADOR = re.compile(r"\\(?:left|right|middle|[bB]igg?[lrm]?)\s*$")
_BARRA = re.compile(r"\\vert(?![A-Za-z])|\\mid(?![A-Za-z])|(?<!\\)\|")


def _quitar_ruido_inicial(latex: str) -> str:
    latex = _RUIDO_INICIAL.sub("", latex)
    # Un \left. solo sobra si no tiene pareja: en «\left. f \right|_0» hace falta.
    if latex.startswith(r"\left.") and latex.count(r"\left") > latex.count(r"\right"):
        return _quitar_ruido_inicial(latex[len(r"\left."):])
    return latex


def _quitar_ruido_final(latex: str) -> str:
    """
    Quita el ruido del final de uno en uno, porque no todo lo que lo parece lo
    es: la barra de «\\right|» o de «\\|» es parte de la fórmula, y la última
    barra de «|x|» cierra la primera.
    """
    while True:
        if latex.endswith(r"\right.") and latex.count(r"\right") > latex.count(r"\left"):
            latex = latex[:-len(r"\right.")]
            continue
        ruido = _RUIDO_FINAL.search(latex)
        if not ruido:
            return latex
        resto = latex[:ruido.start()]
        if resto.endswith("\\") or _PIDE_DELIMITADOR.search(resto):
            return latex
        if ruido.group(0) in ("|", r"\vert", r"\mid") and len(_BARRA.findall(latex)) % 2 == 0:
            return latex
        latex = resto


def clean_latex(texto: str) -> str:
    """
    Quita las envolturas y el ruido que añaden los modelos. Lo que interesa es
    el cuerpo de la fórmula; quien la inserte decidirá si va en línea o
    destacada.
    """
    salida = (texto or "").strip()
    for patron, grupo in _ENVOLTURAS:
        match = re.match(patron, salida, re.DOTALL)
        if match:
            salida = match.group(grupo).strip()
            break

    salida = salida.replace("\r", " ")
    salida = re.sub(r"[ \t]{2,}", " ", salida)
    salida = re.sub(r"\s*\n\s*", " ", salida)
    # Los modelos a veces dejan un espacio pegado a la llave.
    salida = re.sub(r"\{\s+", "{", salida)
    salida = re.sub(r"\s+\}", "}", salida)

    salida = _ETIQUETA.sub("", salida)
    salida = _quitar_ruido_inicial(salida)
    salida = _quitar_ruido_final(salida)
    salida = _quitar_llaves_externas(salida)
    return salida.strip()


def _quitar_llaves_externas(latex: str) -> str:
    """`{\\frac{a}{b}}` → `\\frac{a}{b}`, pero sin romper `{a}{b}`."""
    while len(latex) > 2 and latex.startswith("{") and latex.endswith("}"):
        profundidad = 0
        for indice, caracter in enumerate(latex):
            if caracter == "{":
                profundidad += 1
            elif caracter == "}":
                profundidad -= 1
                if profundidad == 0 and indice != len(latex) - 1:
                    return latex          # las llaves no envuelven todo
        latex = latex[1:-1].strip()
    return latex


def looks_usable(latex: str) -> bool:
    """
    Descarta las salidas que claramente no valen: vacías, larguísimas (el
    modelo se ha ido por las ramas) o con las llaves descuadradas.
    """
    if not latex or len(latex) > 600:
        return False
    if latex.count("{") != latex.count("}"):
        return False
    if latex.count("$"):
        return False
    # Un modelo atascado repite el mismo trozo una y otra vez.
    if re.search(r"(.{4,})\1{4,}", latex):
        return False
    return structure_error(latex) is None


# ────────────────────────────────────────────────────────────
# ¿Compilará?
# ────────────────────────────────────────────────────────────
#
# Que los glifos de una lectura coincidan con los del PDF no dice nada de su
# LaTeX: el modelo puede acertar todos los caracteres y dejar un \left sin
# \right, o cortarse a mitad de un aligned. Una sola fórmula así le rompe a
# pdflatex el resto de la página, así que estas lecturas se descartan y se
# queda la reconstrucción por geometría.

# Los comandos existen con el preámbulo que genera el conversor (amsmath y
# amssymb). Fuera se quedan los que necesitan otro paquete, y los que compilan
# solo en ciertos sitios (\hline, \tag, \label) o de forma infija y frágil
# (\over, \atop, \atopwithdelims): el modelo no los necesita para acertar.
_COMANDOS = frozenset("""
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa
    varkappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi
    varphi chi psi omega digamma Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi
    Psi Omega varGamma varDelta varTheta varLambda varXi varPi varSigma varUpsilon
    varPhi varPsi varOmega
    aleph beth gimel daleth ell hbar hslash imath jmath wp Re Im partial nabla infty
    emptyset varnothing angle measuredangle sphericalangle prime backprime top bot
    forall exists nexists neg lnot flat natural sharp clubsuit diamondsuit
    heartsuit spadesuit mho Box Diamond square blacksquare triangle triangledown
    vartriangle blacktriangle blacktriangledown blacktriangleright star bigstar
    bullet circ cdot ast dagger ddagger complement surd cdotp colon
    pm mp times div setminus smallsetminus wedge vee land lor cap cup sqcap sqcup
    uplus amalg oplus ominus otimes oslash odot bigcirc dotplus barwedge veebar
    doublebarwedge boxdot boxminus boxplus boxtimes circledast circledcirc
    circleddash centerdot divideontimes intercal leftthreetimes rightthreetimes
    ltimes rtimes lhd rhd unlhd unrhd wr Cup Cap triangleleft triangleright diamond
    sum prod coprod int oint iint iiint iiiint idotsint bigcap bigcup bigoplus
    bigotimes bigodot bigsqcup biguplus bigvee bigwedge intop ointop smallint
    leq le geq ge neq ne ll gg lll ggg equiv sim simeq cong approx approxeq asymp
    propto prec succ preceq succeq precsim succsim precapprox succapprox
    preccurlyeq succcurlyeq subset supset subseteq supseteq subsetneq supsetneq
    subsetneqq supsetneqq Subset Supset sqsubset sqsupset sqsubseteq sqsupseteq in
    ni notin owns mid parallel shortmid shortparallel nmid nparallel perp models
    vdash dashv Vdash vDash nVdash doteq doteqdot bumpeq circeq triangleq
    risingdotseq eqsim backsim backsimeq thicksim thickapprox leqq geqq leqslant
    geqslant lesssim gtrsim lessapprox gtrapprox lessdot gtrdot lessgtr gtrless
    ncong nsim nleq ngeq nprec nsucc nsubseteq nsupseteq gneq lneq lvertneqq
    varsubsetneq varsubsetneqq precneqq trianglelefteq trianglerighteq frown smile
    smallfrown smallsmile pitchfork because therefore between not
    leftarrow gets rightarrow to Leftarrow Rightarrow leftrightarrow Leftrightarrow
    longleftarrow longrightarrow Longleftarrow Longrightarrow longleftrightarrow
    Longleftrightarrow mapsto longmapsto hookleftarrow hookrightarrow uparrow
    downarrow updownarrow Uparrow Downarrow Updownarrow nearrow searrow swarrow
    nwarrow leftharpoonup leftharpoondown rightharpoonup rightharpoondown
    rightleftharpoons leftrightharpoons leftrightarrows rightleftarrows
    rightrightarrows leftleftarrows twoheadrightarrow twoheadleftarrow
    rightarrowtail leftarrowtail rightsquigarrow leftrightsquigarrow leadsto
    circlearrowleft circlearrowright curvearrowleft curvearrowright looparrowleft
    looparrowright upharpoonleft upharpoonright downharpoonleft downharpoonright
    nleftarrow nrightarrow nleftrightarrow nRightarrow Rrightarrow dashrightarrow
    dashleftarrow impliedby implies iff
    langle rangle lfloor rfloor lceil rceil lbrace rbrace lbrack rbrack lvert rvert
    lVert rVert vert Vert lgroup rgroup backslash ulcorner urcorner llcorner
    lrcorner arrowvert Arrowvert
    arccos arcsin arctan arg cos cosh cot coth csc deg det dim exp gcd hom inf
    injlim ker lg lim liminf limsup ln log max min Pr projlim sec sin sinh sup tan
    tanh varinjlim varliminf varlimsup varprojlim bmod
    dots dotsb dotsc dotsi dotsm dotso cdots ldots vdots ddots hdots
    bf rm it sf tt cal displaystyle textstyle scriptstyle scriptscriptstyle limits
    nolimits displaylimits mathstrut
    quad qquad thinspace medspace thickspace negthinspace negmedspace negthickspace
    enspace enskip
""".split())

# Comandos que piden argumentos: sin ellos, pdflatex da error.
_ARGUMENTOS = {
    **{c: 1 for c in """
        hat widehat tilde widetilde bar breve check acute grave dot ddot dddot ddddot
        vec mathring overline underline overbrace underbrace overleftarrow
        overrightarrow overleftrightarrow underleftarrow underrightarrow
        underleftrightarrow boxed phantom hphantom vphantom smash mathrm mathbf mathit
        mathsf mathtt mathcal mathbb mathfrak mathnormal boldsymbol pmb Bbb mathop
        mathbin mathrel mathord mathopen mathclose mathinner sqrt operatorname
        operatornamewithlimits substack pmod pod xrightarrow xleftarrow
    """.split()},
    **{c: 2 for c in "frac dfrac tfrac cfrac binom dbinom tbinom overset underset stackrel sideset".split()},
}
# Lo de dentro es texto, no matemáticas: ahí ^, _ o \alpha son un error.
_COMANDOS_DE_TEXTO = frozenset("text mbox textrm textbf textit textsf texttt textnormal textup".split())
_SIGNOS = frozenset(",;:!> {}|%#&_\\")
_SIGNOS_EN_TEXTO = frozenset(",;:! {}%#&_\\")
_TAMANOS = frozenset(
    prefijo + sufijo for prefijo in ("big", "Big", "bigg", "Bigg") for sufijo in ("", "l", "r", "m")
)
_DELIMITADORES = frozenset(r"""
    ( ) [ ] | / . < > \{ \} \| \langle \rangle \lfloor \rfloor \lceil \rceil \lbrace
    \rbrace \lbrack \rbrack \vert \Vert \lvert \rvert \lVert \rVert \uparrow \downarrow
    \updownarrow \Uparrow \Downarrow \Updownarrow \backslash \lgroup \rgroup \ulcorner
    \urcorner \llcorner \lrcorner \arrowvert \Arrowvert
""".split())
# Solo los que pueden ir dentro de una fórmula destacada: equation o align
# dentro de \[ … \] no compilan.
_ENTORNOS = frozenset("""
    matrix pmatrix bmatrix Bmatrix vmatrix Vmatrix smallmatrix cases aligned
    alignedat gathered split array subarray
""".split())
_TOKEN_LATEX = re.compile(r"\\[A-Za-z]+|\\.|\s+|.", re.DOTALL)


@dataclass
class _Marco:
    """Un nivel de anidamiento: llaves, \\left…\\right o un entorno."""
    tipo: str
    entorno: bool = False
    texto: bool = False
    es_argumento: bool = False
    argumentos: int = 0            # los que aún debe el último comando
    argumento_de_texto: bool = False
    sup: bool = False              # este átomo ya tiene superíndice…
    sub: bool = False              # …o subíndice

    def atomo(self) -> None:
        """Llega algo que ocupa sitio: un argumento pendiente o un átomo nuevo."""
        if self.argumentos:
            self.argumentos -= 1
        else:
            self.sup = self.sub = False


def _leer_grupo(tokens: list[str], i: int) -> tuple[Optional[str], int]:
    """El contenido de «{…}» sin llaves anidadas (nombre de entorno, columnas)."""
    if i >= len(tokens) or tokens[i] != "{":
        return None, i
    fin = i + 1
    while fin < len(tokens) and tokens[fin] not in "{}":
        fin += 1
    if fin >= len(tokens) or tokens[fin] != "}":
        return None, i
    return "".join(tokens[i + 1:fin]), fin + 1


def structure_error(latex: str) -> Optional[str]:
    """
    Por qué esta fórmula no compilaría con pdflatex, o None si no se le ve
    ningún problema. Mira la estructura y los comandos, sin compilar nada: se
    llama para cada lectura del OCR y pdflatex puede no estar instalado.
    """
    tokens = [t for t in _TOKEN_LATEX.findall(latex) if not t.isspace()]
    pila = [_Marco("raíz")]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        i += 1
        m = pila[-1]
        if t in ("%", "#", "$"):
            return f"«{t}» sin escapar"

        if m.argumentos and t in ("}", "&", "^", "_", "\\\\", r"\right", r"\end", r"\middle"):
            return f"falta un argumento antes de «{t}»"

        if t == "{":
            es_argumento = m.argumentos > 0
            texto = m.texto or (es_argumento and m.argumento_de_texto)
            m.atomo()
            if not m.argumentos:
                m.argumento_de_texto = False
            pila.append(_Marco("{", texto=texto, es_argumento=es_argumento))
        elif t == "}":
            if m.tipo != "{":
                return "«}» sin abrir" if len(pila) == 1 else f"«}}» cierra mal un {m.tipo}"
            pila.pop()
        elif m.texto:
            if t in ("^", "_", "&"):
                return f"«{t}» dentro de texto"
            if t.startswith("\\") and t[1:] not in _SIGNOS_EN_TEXTO:
                return f"{t} dentro de texto"
        elif t in ("^", "_"):
            if t == "^" and m.sup or t == "_" and m.sub:
                return f"doble «{t}»"
            m.sup, m.sub = m.sup or t == "^", m.sub or t == "_"
            m.argumentos = 1
        elif t == "'":
            if m.sup:
                return "prima después de un superíndice"
        elif t == "&":
            if not m.entorno:
                return "«&» fuera de una tabla"
            m.sup = m.sub = False
        elif t == r"\left":
            if i >= len(tokens) or tokens[i] not in _DELIMITADORES:
                return r"\left sin delimitador"
            i += 1
            m.atomo()
            pila.append(_Marco(r"\left"))
        elif t == r"\right":
            if m.tipo != r"\left":
                return r"\right sin su \left"
            if i >= len(tokens) or tokens[i] not in _DELIMITADORES:
                return r"\right sin delimitador"
            i += 1
            pila.pop()
        elif t == r"\middle":
            if m.tipo != r"\left":
                return r"\middle fuera de \left…\right"
            if i >= len(tokens) or tokens[i] not in _DELIMITADORES:
                return r"\middle sin delimitador"
            i += 1
        elif t == r"\begin":
            nombre, i = _leer_grupo(tokens, i)
            if nombre not in _ENTORNOS:
                return f"entorno desconocido: {nombre}"
            if nombre in ("array", "subarray", "alignedat"):
                columnas, i = _leer_grupo(tokens, i)
                if not columnas:
                    return f"{nombre} sin columnas"
            m.atomo()
            pila.append(_Marco(nombre, entorno=True))
        elif t == r"\end":
            nombre, i = _leer_grupo(tokens, i)
            if not m.entorno or nombre != m.tipo:
                return rf"\end{{{nombre}}} no cierra lo último que se abrió"
            pila.pop()
        elif t.startswith("\\") and t[1:] in _TAMANOS:
            if i >= len(tokens) or tokens[i] not in _DELIMITADORES:
                return f"{t} sin delimitador"
            i += 1
            m.atomo()
        elif t in (r"\limits", r"\nolimits", r"\displaylimits"):
            pass
        elif t.startswith("\\") and len(t) == 2 and not t[1].isalpha():
            if t[1] not in _SIGNOS:
                return f"comando desconocido: {t}"
            m.atomo()
            if t == "\\\\":
                m.sup = m.sub = False
        elif t.startswith("\\"):
            nombre = t[1:]
            if nombre in _COMANDOS_DE_TEXTO:
                m.atomo()
                m.argumentos += 1
                m.argumento_de_texto = True
            elif nombre in _ARGUMENTOS:
                m.atomo()
                m.argumentos += _ARGUMENTOS[nombre]
                if nombre in ("operatorname", "operatornamewithlimits") and tokens[i:i + 1] == ["*"]:
                    i += 1
                if nombre in ("sqrt", "xrightarrow", "xleftarrow") and tokens[i:i + 1] == ["["]:
                    try:
                        i = tokens.index("]", i) + 1
                    except ValueError:
                        return f"{t}[ sin cerrar"
            elif nombre in _COMANDOS:
                m.atomo()
            else:
                return f"comando desconocido: {t}"
        else:
            m.atomo()

    if len(pila) > 1:
        return f"sin cerrar: {pila[-1].tipo}"
    if pila[0].argumentos:
        return "falta un argumento al final"
    return None


# ────────────────────────────────────────────────────────────
# Pix2Text-MFR con onnxruntime
# ────────────────────────────────────────────────────────────
#
# Pix2Text-MFR (https://huggingface.co/breezedeus/pix2text-mfr-1.5, licencia
# MIT) es un TrOCR reentrenado con imágenes de fórmulas. Viene exportado a
# ONNX, así que basta onnxruntime —que Latexinter ya trae— y se evita PyTorch,
# que pesa más de un giga. Lo que hace transformers por debajo se hace aquí a
# mano: preparar la imagen, el bucle que va eligiendo token a token y pasar
# los tokens a texto.

MFR_REPO = "breezedeus/pix2text-mfr-1.5"
MFR_REVISION = "1cef9f0bdcd6a4c63df7de1311fb0894593340cc"
MFR_FILES = {
    "encoder_model.onnx": "080a3f660f08bc9ebcacdd96e34be6b6400f8c7e62d7cd0dd8251badc37f610b",
    "decoder_model.onnx": "917deb98e91a0453c5f234f58a0f32f9fb037de8527c7eb4ed394daf9e692f2a",
    "tokenizer.json": "4ffbeb2143e6a38324bb6111b7a8109530d38a076a8439aa5777535f0a32758a",
}
_MFR_START, _MFR_END, _MFR_SPECIAL = 1, 2, 4
_MFR_SIZE = 384
_MFR_MAX_TOKENS = 512


def models_dir() -> Path:
    """Dónde se guardan los modelos descargados (fuera de la carpeta del programa)."""
    import os
    import sys

    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Latexinter" / "modelos"
    return Path.home() / ".cache" / "latexinter"


def download_mfr(log: Logger = print) -> Path:
    """
    Descarga el modelo la primera vez, comprobando que cada archivo es
    exactamente el esperado. Devuelve la carpeta donde está.
    """
    import hashlib
    import urllib.request

    carpeta = models_dir() / "pix2text-mfr-1.5"
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, esperado in MFR_FILES.items():
        destino = carpeta / nombre
        if destino.exists():
            continue
        url = f"https://huggingface.co/{MFR_REPO}/resolve/{MFR_REVISION}/{nombre}"
        log(f"Descargando el modelo de fórmulas: {nombre}…")
        parcial = destino.with_suffix(destino.suffix + ".part")
        resumen = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as respuesta, open(parcial, "wb") as salida:
            while True:
                bloque = respuesta.read(1 << 20)
                if not bloque:
                    break
                resumen.update(bloque)
                salida.write(bloque)
        if resumen.hexdigest() != esperado:
            parcial.unlink(missing_ok=True)
            raise ConversionError(f"El archivo descargado {nombre} no es el esperado.")
        parcial.replace(destino)
    return carpeta


def _byte_decoder() -> dict[str, int]:
    """El alfabeto de los tokenizadores de nivel byte (el de GPT-2), al revés."""
    imprimibles = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    bytes_, caracteres = imprimibles[:], imprimibles[:]
    extra = 0
    for byte in range(256):
        if byte not in imprimibles:
            bytes_.append(byte)
            caracteres.append(256 + extra)
            extra += 1
    return {chr(c): b for b, c in zip(bytes_, caracteres)}


_TOKEN_SUELTO = re.compile(r"\\[A-Za-z]+\*?|\\.|\S")


def join_spaced_latex(latex: str) -> str:
    """
    El modelo escribe un token por palabra: «\\operatorname* { l i m } _ { T }».
    Se juntan, dejando un espacio solo donde hace falta (tras un comando, si
    sigue una letra), y las palabras de texto vuelven a ser texto.
    """
    salida = ""
    for token in _TOKEN_SUELTO.findall(latex):
        if salida and re.search(r"\\[A-Za-z]+\*?$", salida) and token[0].isalpha():
            salida += " "
        salida += token
    # Dentro de \mathrm{…} la tilde era un espacio de la palabra.
    salida = re.sub(
        r"\\(mathrm|text)\{([^{}\\]*)\}",
        lambda m: "\\" + m.group(1) + "{" + m.group(2).replace("~", " ") + "}",
        salida,
    )
    # «\operatorname*{lim}» es \lim; con texto entre espacios, \text{ and }.
    # Si sigue una letra hace falta el espacio: \logA no existe.
    salida = re.sub(
        r"\\operatorname\*?\{(lim|max|min|sup|inf|limsup|liminf|det|exp|log|sin|cos)\}(?=([A-Za-z])?)",
        lambda m: "\\" + m.group(1) + (" " if m.group(2) else ""), salida,
    )
    salida = re.sub(r"\\mathrm\{( [^{}]* )\}", r"\\text{\1}", salida)
    # Un \i suelto (la i sin punto de texto) es ruido del modelo y en una
    # fórmula ni siquiera compila.
    salida = re.sub(r"\\i(?![A-Za-z])\s*", "", salida)
    return salida


class MFRModel:
    """Pix2Text-MFR: imagen de una fórmula → LaTeX."""

    def __init__(self, carpeta: Path):
        import json

        import onnxruntime

        opciones = onnxruntime.SessionOptions()
        opciones.log_severity_level = 3
        proveedores = ["CPUExecutionProvider"]
        self.encoder = onnxruntime.InferenceSession(
            str(carpeta / "encoder_model.onnx"), opciones, providers=proveedores
        )
        self.decoder = onnxruntime.InferenceSession(
            str(carpeta / "decoder_model.onnx"), opciones, providers=proveedores
        )
        vocabulario = json.loads((carpeta / "tokenizer.json").read_text(encoding="utf-8"))
        self.tokens = {i: t for t, i in vocabulario["model"]["vocab"].items()}
        self.bytes = _byte_decoder()

    def __call__(self, imagen, max_tokens: Optional[int] = None) -> str:
        import numpy as np
        from PIL import Image

        imagen = imagen.convert("RGB").resize((_MFR_SIZE, _MFR_SIZE), Image.BICUBIC)
        pixeles = (np.asarray(imagen, dtype=np.float32) / 255.0 - 0.5) / 0.5
        pixeles = pixeles.transpose(2, 0, 1)[None]
        estado = self.encoder.run(None, {"pixel_values": pixeles})[0]

        ids = [_MFR_START]
        for _ in range(min(max_tokens or _MFR_MAX_TOKENS, _MFR_MAX_TOKENS)):
            logits = self.decoder.run(None, {
                "input_ids": np.array([ids], dtype=np.int64),
                "encoder_hidden_states": estado,
            })[0]
            siguiente = int(logits[0, -1].argmax())
            if siguiente == _MFR_END:
                break
            ids.append(siguiente)

        texto = "".join(self.tokens.get(i, "") for i in ids if i > _MFR_SPECIAL)
        crudo = bytes(self.bytes.get(c, 32) for c in texto).decode("utf-8", "replace")
        return join_spaced_latex(crudo)


# ────────────────────────────────────────────────────────────
# Motor
# ────────────────────────────────────────────────────────────

class MathOCREngine:
    """
    Envoltorio de un modelo de OCR matemático. Se crea barato; el modelo de
    verdad no se carga hasta la primera llamada a recognize().
    """

    def __init__(self, backend: Optional[Backend] = None, logger: Optional[Logger] = None):
        self.log = as_logger(logger)
        self._modelo = None
        self._reconocer: Optional[Callable] = None
        self._candado = threading.Lock()
        self._error: Optional[str] = None

        disponibles = installed_backends()
        if backend is not None:
            self.backend: Optional[Backend] = backend if backend.installed else None
        else:
            self.backend = disponibles[0] if disponibles else None

    # ── Estado ──
    @property
    def available(self) -> bool:
        return self.backend is not None and self._error is None

    @property
    def name(self) -> str:
        return self.backend.name if self.backend else "ninguno"

    @property
    def loaded(self) -> bool:
        return self._reconocer is not None

    @property
    def error(self) -> Optional[str]:
        return self._error

    # ── Carga del modelo ──
    def load(self) -> bool:
        """Carga el modelo. Tarda unos segundos y descarga pesos la primera vez."""
        if self._reconocer is not None:
            return True
        if self.backend is None:
            self._error = "No hay ningún motor de OCR instalado."
            return False

        with self._candado:
            if self._reconocer is not None:
                return True
            self.log(f"Cargando el modelo de {self.backend.name}…")
            try:
                cargador = getattr(self, f"_load_{self.backend.key}")
                self._reconocer = cargador()
            except Exception as exc:
                self._error = (
                    f"No se pudo cargar {self.backend.name}: {exc}\n"
                    "Puede que el modelo no sea compatible con esta versión de "
                    "Python o que falte descargarlo."
                )
                self.log(self._error)
                return False
            self.log(f"{self.backend.name} listo.")
            return True

    def _load_mfr(self) -> Callable:
        modelo = MFRModel(download_mfr(self.log))
        self._modelo = modelo
        return modelo

    def _load_pix2tex(self) -> Callable:
        from pix2tex.cli import LatexOCR

        modelo = LatexOCR()
        self._modelo = modelo
        return lambda imagen: modelo(imagen)

    def _load_texify(self) -> Callable:
        from texify.inference import batch_inference
        from texify.model.model import load_model
        from texify.model.processor import load_processor

        modelo = load_model()
        procesador = load_processor()
        self._modelo = modelo

        def reconocer(imagen):
            resultado = batch_inference([imagen], modelo, procesador)
            return resultado[0] if resultado else ""

        return reconocer

    # ── Uso ──
    def recognize(self, imagen, max_tokens: Optional[int] = None) -> Optional[str]:
        """
        Devuelve el LaTeX de la fórmula de la imagen, o None si no se pudo
        reconocer o el resultado no es de fiar. Con max_tokens se corta al
        modelo si se alarga más de la cuenta (solo Pix2Text-MFR lo admite).
        """
        if not self.load():
            return None
        try:
            if max_tokens and isinstance(self._modelo, MFRModel):
                crudo = self._reconocer(imagen, max_tokens=max_tokens)
            else:
                crudo = self._reconocer(imagen)
        except Exception as exc:
            self.log(f"El OCR falló en una fórmula: {exc}")
            return None

        latex = clean_latex(crudo if isinstance(crudo, str) else str(crudo))
        return latex if looks_usable(latex) else None

    def recognize_many(self, imagenes: list) -> list[Optional[str]]:
        return [self.recognize(imagen) for imagen in imagenes]


# ────────────────────────────────────────────────────────────
# Instancia compartida
# ────────────────────────────────────────────────────────────

_motor: Optional[MathOCREngine] = None
_candado_global = threading.Lock()


def get_engine(backend_key: Optional[str] = None,
               logger: Optional[Logger] = None) -> MathOCREngine:
    """
    Motor compartido por toda la aplicación: así el modelo se carga una vez y
    no en cada conversión.
    """
    global _motor
    with _candado_global:
        deseado = BACKENDS_POR_CLAVE.get(backend_key) if backend_key else None
        if _motor is None or (deseado is not None and _motor.backend is not deseado):
            _motor = MathOCREngine(deseado, logger)
        elif logger is not None:
            _motor.log = as_logger(logger)
        return _motor


def reset_engine() -> None:
    """Suelta el modelo de memoria (son cientos de megas)."""
    global _motor
    with _candado_global:
        _motor = None


# ────────────────────────────────────────────────────────────
# Utilidades de imagen
# ────────────────────────────────────────────────────────────

def render_region(page, rect, *, dpi: int = 200, margen: int = 10, exclude=()):
    """
    Recorta un trozo de página del PDF y lo devuelve como imagen PIL, con un
    margen blanco alrededor: los modelos aciertan bastante más si la fórmula
    no llega pegada al borde.

    En `exclude` van los rectángulos de texto ajeno que caen dentro del
    recorte; se tapan de blanco. Sin eso, la línea de prosa que hay encima de
    una fracción alta entra en la imagen y el modelo intenta transcribirla.
    """
    try:
        import fitz
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ConversionError(
            "Para el OCR de fórmulas hace falta Pillow:  pip install Pillow"
        ) from exc

    import io

    caja = fitz.Rect(*rect)
    if caja.is_empty or caja.width < 4 or caja.height < 4:
        return None

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=caja, alpha=False)
    recorte = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

    if exclude:
        pincel = ImageDraw.Draw(recorte)
        for ajeno in exclude:
            x0 = (ajeno[0] - caja.x0) * zoom
            y0 = (ajeno[1] - caja.y0) * zoom
            x1 = (ajeno[2] - caja.x0) * zoom
            y1 = (ajeno[3] - caja.y0) * zoom
            if x1 > 0 and y1 > 0 and x0 < recorte.width and y0 < recorte.height:
                pincel.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))

    lienzo = Image.new(
        "RGB",
        (recorte.width + margen * 2, recorte.height + margen * 2),
        (255, 255, 255),
    )
    lienzo.paste(recorte, (margen, margen))
    return lienzo


# ────────────────────────────────────────────────────────────
# Lectura con varias escalas
# ────────────────────────────────────────────────────────────

# El modelo se entrenó con fórmulas de un tamaño concreto. Si la imagen viene
# mucho más grande, se pierde: en las pruebas, a 400 dpi convertía f(x) en
# \hat{f}(\mathcal{A}). Estas son las resoluciones donde acierta.
DPI_PREFERIDOS = (200, 150, 260)

# Comandos que casi nunca aparecen en una fórmula de verdad y sí cuando el
# modelo se pone a inventar.
_SOSPECHOSOS = (
    "\\stackrel", "\\mathcal", "\\displaystyle", "\\begin{array}",
    "\\hat{", "\\vphantom", "\\Bigl", "\\Bigr", "\\longrightarrow",
)


def _puntuacion(latex: str) -> tuple:
    """
    Para ordenar candidatos de peor a mejor: primero los que no traen
    comandos sospechosos, y entre esos, el más corto. Las alucinaciones son
    largas y barrocas; la lectura correcta es escueta.
    """
    rarezas = sum(latex.count(marca) for marca in _SOSPECHOSOS)
    return (rarezas, len(latex))


def _elegir(candidatos: list[str]) -> Optional[str]:
    """
    De varias lecturas de la misma fórmula, la de consenso; y si no hay dos
    iguales, la que menos pinta tiene de invento.
    """
    utiles = [c for c in candidatos if c]
    if not utiles:
        return None

    repetidos = {}
    for candidato in utiles:
        repetidos[candidato] = repetidos.get(candidato, 0) + 1
    consenso = [texto for texto, veces in repetidos.items() if veces > 1]
    if consenso:
        return min(consenso, key=_puntuacion)
    return min(utiles, key=_puntuacion)


def recognize_region(engine: MathOCREngine, page, rect, *, exclude=(),
                     dpis: tuple[int, ...] = DPI_PREFERIDOS) -> Optional[str]:
    """
    Lee una fórmula de una página del PDF probando varias resoluciones y
    quedándose con la lectura más creíble.
    """
    lecturas: list[str] = []
    for dpi in dpis:
        imagen = render_region(page, rect, dpi=dpi, exclude=exclude)
        if imagen is None:
            continue
        latex = engine.recognize(imagen)
        if latex:
            lecturas.append(latex)
            # Dos lecturas iguales ya son suficiente garantía.
            if lecturas.count(latex) > 1:
                break
    return _elegir(lecturas)


# Alturas, en píxeles, a las que el modelo va cómodo con una fórmula suelta.
_ALTURAS_OBJETIVO = (90, 70, 130)


def recognize_image(engine: MathOCREngine, imagen,
                    alturas: tuple[int, ...] = _ALTURAS_OBJETIVO) -> Optional[str]:
    """
    Lee una fórmula de una imagen cualquiera (un recorte de pantalla, un
    archivo). Como no se puede volver a renderizar, se reescala a los tamaños
    con los que el modelo trabaja mejor.
    """
    try:
        from PIL import Image
    except ImportError:
        return engine.recognize(imagen)

    lecturas: list[str] = []
    for altura in alturas:
        if imagen.height < 12:
            continue
        factor = altura / imagen.height
        if 0.95 < factor < 1.05:
            version = imagen
        else:
            ancho = max(8, int(imagen.width * factor))
            alto = max(8, int(imagen.height * factor))
            version = imagen.resize((ancho, alto), Image.LANCZOS)
        latex = engine.recognize(version)
        if latex:
            lecturas.append(latex)
            if lecturas.count(latex) > 1:
                break
    return _elegir(lecturas)


def load_image(path: Path | str):
    """Carga una imagen de disco para pasársela al OCR."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ConversionError(
            "Para el OCR de fórmulas hace falta Pillow:  pip install Pillow"
        ) from exc

    imagen = Image.open(str(path))
    return imagen.convert("RGB")
