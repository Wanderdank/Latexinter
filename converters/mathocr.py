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
# principio o al final, delimitadores vacíos, y el punto o la coma que en el
# original pertenecían a la frase y no a la fórmula.
_RUIDO_INICIAL = re.compile(r"^(?:\\[,;!:> ]|\\quad|\\qquad|\\left\.|\s)+")
_RUIDO_FINAL = re.compile(
    r"(?:\\[,;!:> ]|\\quad|\\qquad|\\right\.|\\vert|\\mid|[.,;|]|\s)+$"
)


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

    salida = _RUIDO_INICIAL.sub("", salida)
    salida = _RUIDO_FINAL.sub("", salida)
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
    return True


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
    def recognize(self, imagen) -> Optional[str]:
        """
        Devuelve el LaTeX de la fórmula de la imagen, o None si no se pudo
        reconocer o el resultado no es de fiar.
        """
        if not self.load():
            return None
        try:
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
