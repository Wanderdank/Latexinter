"""
tools.py - Las herramientas de LaTeX que no convierten nada.

Aquí viven los envoltorios de los programas auxiliares que trae cualquier
distribución de TeX y que el editor necesita:

  synctex   relaciona una línea del .tex con un punto del PDF y al revés.
            Es lo que permite hacer doble clic en el PDF y aterrizar en la
            línea que lo generó.
  texcount  cuenta palabras de verdad, sin contar los comandos.
  chktex    revisa el documento y avisa de errores tipográficos típicos.

También está el analizador del registro de compilación, que convierte el .log
de LaTeX —que es un muro de texto— en una lista de problemas con archivo y
línea, para poder pinchar en ellos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .common import find_tool, run_command

# ────────────────────────────────────────────────────────────
# Problemas del documento
# ────────────────────────────────────────────────────────────

ERROR = "error"
WARNING = "aviso"
INFO = "info"


@dataclass(frozen=True)
class Problem:
    """Un error o aviso, situado en un archivo y una línea."""

    severity: str
    message: str
    file: Optional[Path] = None
    line: Optional[int] = None
    origin: str = "latex"          # latex | chktex

    @property
    def location(self) -> str:
        if self.file is None:
            return ""
        return f"{self.file.name}:{self.line}" if self.line else self.file.name


# ────────────────────────────────────────────────────────────
# Análisis del registro de compilación
# ────────────────────────────────────────────────────────────

# Con -file-line-error los errores salen como "./doc.tex:42: mensaje".
_FILE_LINE = re.compile(r"^(?P<file>[^\s:]{1,200}\.\w{1,6}):(?P<line>\d+):\s*(?P<msg>.+)$")
_BANG = re.compile(r"^!\s*(?P<msg>.+)$")
_LINE_HINT = re.compile(r"^l\.(?P<line>\d+)")
_WARNING = re.compile(
    r"^(?:LaTeX|Package|Class)\s*(?P<pkg>[\w@-]+)?\s*Warning:\s*(?P<msg>.+)$"
)
_WARNING_LINE = re.compile(r"on input line (\d+)")
_OVERFULL = re.compile(
    r"^(Overfull|Underfull) \\[hv]box .*?(?:at lines? (\d+)|in paragraph at lines? (\d+))"
)
_MISSING_FILE = re.compile(r"File `([^']+)' not found")

# Avisos que solo hacen ruido y nunca hay que arreglar.
_NOISE = re.compile(
    r"Font shape|has changed|Some font shapes|Marginpar|"
    r"Package hyperref Warning: Token not allowed|"
    r"Package microtype Warning|rerunfilecheck",
    re.IGNORECASE,
)


def parse_log(log_text: str, base_dir: Path, *, include_boxes: bool = False) -> list[Problem]:
    """
    Convierte el .log de LaTeX en una lista de problemas.

    Con include_boxes=True se incluyen también los avisos de líneas que se
    salen del margen (Overfull/Underfull), que suelen ser muchos y casi
    siempre inofensivos.
    """
    problems: list[Problem] = []
    pending: Optional[dict] = None

    def resolve(name: str) -> Optional[Path]:
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = base_dir / name
        return candidate if candidate.exists() else None

    def flush() -> None:
        nonlocal pending
        if pending:
            problems.append(Problem(
                severity=ERROR,
                message=pending["msg"],
                file=pending.get("file"),
                line=pending.get("line"),
            ))
            pending = None

    for raw in log_text.splitlines():
        line = raw.rstrip()

        match = _FILE_LINE.match(line)
        if match and not line.lower().startswith(("package", "latex")):
            flush()
            message = match.group("msg").strip()
            problems.append(Problem(
                severity=ERROR,
                message=message,
                file=resolve(match.group("file")),
                line=int(match.group("line")),
            ))
            continue

        match = _BANG.match(line)
        if match:
            flush()
            pending = {"msg": match.group("msg").strip()}
            continue

        match = _LINE_HINT.match(line)
        if match and pending is not None:
            pending["line"] = int(match.group("line"))
            flush()
            continue

        match = _WARNING.match(line)
        if match and not _NOISE.search(line):
            flush()
            message = match.group("msg").strip()
            paquete = match.group("pkg")
            numero = _WARNING_LINE.search(line)
            problems.append(Problem(
                severity=WARNING,
                message=f"[{paquete}] {message}" if paquete else message,
                line=int(numero.group(1)) if numero else None,
            ))
            continue

        match = _OVERFULL.match(line)
        if match and include_boxes:
            flush()
            numero = match.group(2) or match.group(3)
            problems.append(Problem(
                severity=INFO,
                message=line.strip(),
                line=int(numero) if numero else None,
            ))
            continue

        match = _MISSING_FILE.search(line)
        if match:
            flush()
            problems.append(Problem(
                severity=ERROR,
                message=(
                    f"No se encuentra «{match.group(1)}». "
                    "Si es un paquete, instálalo desde la consola de MiKTeX."
                ),
            ))

    flush()

    # Sin duplicados exactos, conservando el orden.
    vistos: set[tuple] = set()
    unicos: list[Problem] = []
    for problem in problems:
        clave = (problem.severity, problem.message, problem.line)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(problem)
    return unicos


# ────────────────────────────────────────────────────────────
# SyncTeX
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SyncPoint:
    """Un rectángulo del PDF, en puntos y con el origen arriba a la izquierda."""

    page: int          # 1 en adelante
    x: float
    y: float
    width: float
    height: float


def synctex_available() -> bool:
    return find_tool("synctex") is not None


def _synctex_data(path: Path) -> bool:
    """¿Existe el archivo .synctex que produce la compilación?"""
    stem = path.with_suffix("")
    return any(
        stem.with_name(stem.name + sufijo).exists()
        for sufijo in (".synctex.gz", ".synctex")
    )


def forward_search(tex_path: Path, line: int, pdf_path: Path, column: int = 1) -> Optional[SyncPoint]:
    """Del .tex al PDF: dónde acabó impresa esta línea."""
    if not find_tool("synctex") or not pdf_path.exists() or not _synctex_data(pdf_path):
        return None

    tex_path = Path(tex_path).resolve()
    pdf_path = Path(pdf_path).resolve()
    result = run_command(
        ["synctex", "view", "-i", f"{line}:{column}:{tex_path}", "-o", str(pdf_path)],
        cwd=pdf_path.parent,
        timeout=30,
    )
    if result.returncode != 0:
        return None

    # Puede devolver varios rectángulos: nos quedamos con el primero completo.
    bloque: dict[str, float] = {}
    for renglon in result.stdout.splitlines():
        if ":" not in renglon:
            continue
        clave, _, valor = renglon.partition(":")
        clave = clave.strip()
        if clave in ("Page", "x", "y", "h", "v", "W", "H"):
            try:
                bloque[clave] = float(valor)
            except ValueError:
                continue
        if clave == "H" and {"Page", "h", "v", "W"} <= set(bloque):
            return SyncPoint(
                page=int(bloque["Page"]),
                x=bloque["h"],
                y=max(0.0, bloque["v"] - bloque["H"]),
                width=bloque["W"],
                height=bloque["H"] or 12.0,
            )
    return None


def inverse_search(pdf_path: Path, page: int, x: float, y: float) -> Optional[tuple[Path, int]]:
    """Del PDF al .tex: qué línea generó este punto de la página."""
    pdf_path = Path(pdf_path).resolve()
    if not find_tool("synctex") or not _synctex_data(pdf_path):
        return None

    result = run_command(
        ["synctex", "edit", "-o", f"{page}:{x:.2f}:{y:.2f}:{pdf_path}"],
        cwd=pdf_path.parent,
        timeout=30,
    )
    if result.returncode != 0:
        return None

    archivo: Optional[Path] = None
    numero: Optional[int] = None
    for renglon in result.stdout.splitlines():
        if renglon.startswith("Input:"):
            archivo = Path(renglon.partition(":")[2].strip())
        elif renglon.startswith("Line:"):
            try:
                numero = int(renglon.partition(":")[2].strip())
            except ValueError:
                numero = None
        if archivo is not None and numero is not None:
            return archivo, max(1, numero)
    return None


# ────────────────────────────────────────────────────────────
# Recuento de palabras
# ────────────────────────────────────────────────────────────

_TEXCOUNT_TOTAL = re.compile(r"^(\d+)\+(\d+)\+(\d+)")


def word_count(tex_path: Path) -> Optional[dict]:
    """
    Palabras del documento según texcount, que ignora los comandos.
    Devuelve None si texcount no está instalado.
    """
    if not find_tool("texcount"):
        return None

    tex_path = Path(tex_path)
    result = run_command(
        ["texcount", "-1", "-sum", "-merge", "-q", tex_path.name],
        cwd=tex_path.parent,
        timeout=60,
    )
    if result.returncode != 0:
        return None

    for renglon in result.stdout.splitlines():
        renglon = renglon.strip()
        if renglon.isdigit():
            return {"total": int(renglon)}
        match = _TEXCOUNT_TOTAL.match(renglon)
        if match:
            texto, cabeceras, leyendas = (int(g) for g in match.groups())
            return {
                "total": texto + cabeceras + leyendas,
                "texto": texto,
                "titulos": cabeceras,
                "leyendas": leyendas,
            }
    return None


# Entornos cuyo contenido no es prosa y no debe contarse.
_ENTORNOS_SIN_TEXTO = (
    "equation", "align", "gather", "multline", "eqnarray", "displaymath",
    "array", "matrix", "bmatrix", "pmatrix", "vmatrix", "cases", "split",
    "verbatim", "lstlisting", "minted", "alltt", "tikzpicture", "picture",
    "tabular", "tabularx", "longtable", "thebibliography",
)


def rough_word_count(text: str) -> int:
    """
    Recuento de palabras hecho en Python, sin depender de texcount (que en
    Windows necesita Perl). Se descartan el preámbulo, los comentarios, las
    matemáticas, el código y las tablas, que no son prosa.
    """
    # Solo el cuerpo del documento.
    cuerpo = text.split("\\begin{document}", 1)
    texto = cuerpo[1] if len(cuerpo) > 1 else text
    texto = texto.split("\\end{document}", 1)[0]

    texto = re.sub(r"(?<!\\)%[^\n]*", " ", texto)

    for entorno in _ENTORNOS_SIN_TEXTO:
        texto = re.sub(
            r"\\begin\{" + entorno + r"\*?\}[\s\S]*?\\end\{" + entorno + r"\*?\}",
            " ", texto,
        )

    texto = re.sub(r"\$\$[\s\S]*?\$\$", " ", texto)
    texto = re.sub(r"(?<!\\)\$(?:[^$\\\n]|\\.)*\$", " ", texto)
    texto = re.sub(r"\\\[[\s\S]*?\\\]", " ", texto)

    # Los comandos desaparecen, pero lo que va entre llaves suele ser texto
    # visible (títulos, pies de figura) y se conserva.
    texto = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]\n]*\])?", " ", texto)
    texto = re.sub(r"\\[^A-Za-z]", " ", texto)
    texto = re.sub(r"[{}&#_^~]", " ", texto)

    return len([p for p in texto.split() if any(c.isalnum() for c in p)])


# ────────────────────────────────────────────────────────────
# Revisión con chktex
# ────────────────────────────────────────────────────────────

# Avisos de chktex que en español dan más ruido que ayuda.
_CHKTEX_SILENCED = {
    "1",    # comando terminado en espacio
    "8",    # coma mal colocada en un rango
    "13",   # "..." en vez de \ldots
    "17",   # numero seguido de unidad
    "36",   # espacio antes de un signo
    "44",   # usa \( \) en vez de $
}


def lint(tex_path: Path, *, silenced: Optional[set[str]] = None) -> list[Problem]:
    """Pasa chktex al documento y devuelve sus avisos ya situados."""
    if not find_tool("chktex"):
        return []

    tex_path = Path(tex_path)
    apagados = _CHKTEX_SILENCED if silenced is None else silenced
    result = run_command(
        ["chktex", "-q", "-f", "%l:%c:%n:%m\n", tex_path.name],
        cwd=tex_path.parent,
        timeout=60,
    )

    problems: list[Problem] = []
    for renglon in result.stdout.splitlines():
        partes = renglon.split(":", 3)
        if len(partes) != 4 or not partes[0].isdigit():
            continue
        numero, _columna, codigo, mensaje = partes
        if codigo.strip() in apagados:
            continue
        problems.append(Problem(
            severity=WARNING,
            message=mensaje.strip(),
            file=tex_path,
            line=int(numero),
            origin="chktex",
        ))
    return problems
