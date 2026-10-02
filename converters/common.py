"""
common.py - Utilidades compartidas por todos los conversores.

Aquí vive lo aburrido pero necesario: detección de dependencias, ejecución de
procesos externos sin abrir ventanas de consola, rutas de salida que no pisan
archivos existentes y el objeto que devuelve cada conversión.
"""

from __future__ import annotations

import os
import subprocess
import shutil
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Sequence

# Una función que recibe una línea de texto y la muestra donde corresponda
# (consola en el CLI, panel de registro en la GUI).
Logger = Callable[[str], None]

# En Windows evita que cada subproceso abra una ventana negra de consola.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


# ────────────────────────────────────────────────────────────
# Errores
# ────────────────────────────────────────────────────────────

class ConversionError(RuntimeError):
    """Error esperable durante una conversión, con mensaje apto para el usuario."""


class MissingDependency(ConversionError):
    def __init__(self, tool: str, hint: str = ""):
        self.tool = tool
        self.hint = hint
        msg = f"No se encontró '{tool}' en el sistema."
        if hint:
            msg += f"\n{hint}"
        super().__init__(msg)


INSTALL_HINTS = {
    "pandoc": "Instálalo con:  winget install --id JohnMacFarlane.Pandoc",
    "pdflatex": "Instala MiKTeX con:  winget install --id MiKTeX.MiKTeX",
    "xelatex": "Instala MiKTeX con:  winget install --id MiKTeX.MiKTeX",
    "lualatex": "Instala MiKTeX con:  winget install --id MiKTeX.MiKTeX",
    "bibtex": "Viene incluido con MiKTeX / TeX Live.",
    "biber": "Instálalo desde el gestor de paquetes de MiKTeX.",
}


# ────────────────────────────────────────────────────────────
# Registro
# ────────────────────────────────────────────────────────────

def _silent(_msg: str) -> None:
    pass


def as_logger(logger: Optional[Logger]) -> Logger:
    return logger if logger is not None else _silent


# ────────────────────────────────────────────────────────────
# Resultado de una conversión
# ────────────────────────────────────────────────────────────

@dataclass
class ConversionResult:
    """Lo que devuelve cualquier conversor."""

    output: Path                                   # archivo principal generado
    extras: list[Path] = field(default_factory=list)   # imágenes, .md intermedio, etc.
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)      # métricas para mostrar en la GUI


# ────────────────────────────────────────────────────────────
# Dependencias externas
# ────────────────────────────────────────────────────────────

def find_tool(name: str) -> Optional[str]:
    """Ruta del ejecutable, o None si no está instalado."""
    return shutil.which(name)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MissingDependency(name, INSTALL_HINTS.get(name, ""))
    return path


def require_module(module: str, pip_name: Optional[str] = None) -> None:
    import importlib.util

    if importlib.util.find_spec(module) is None:
        raise MissingDependency(
            module,
            f"Instálalo con:  pip install {pip_name or module}",
        )


@lru_cache(maxsize=8)
def engine_is_miktex(engine: str = "pdflatex") -> bool:
    """MiKTeX puede instalar paquetes faltantes al vuelo; TeX Live no."""
    exe = shutil.which(engine)
    if not exe:
        return False
    try:
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return False
    return "miktex" in (out.stdout or "").lower()


def dependency_report() -> dict[str, Optional[str]]:
    """Estado de todas las herramientas externas, para mostrarlo en la GUI."""
    report: dict[str, Optional[str]] = {}
    for tool in ("pandoc", "pdflatex", "bibtex"):
        report[tool] = find_tool(tool)
    import importlib.util
    for mod in ("pymupdf4llm", "fitz"):
        spec = importlib.util.find_spec(mod)
        report[mod] = spec.origin if spec else None
    return report


# ────────────────────────────────────────────────────────────
# Procesos externos
# ────────────────────────────────────────────────────────────

def run_command(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    logger: Optional[Logger] = None,
    timeout: Optional[int] = 600,
) -> subprocess.CompletedProcess:
    """Ejecuta un comando y captura su salida (sin ventana de consola)."""
    log = as_logger(logger)
    log(f"$ {' '.join(str(c) for c in cmd)}")
    try:
        return subprocess.run(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise MissingDependency(str(cmd[0]), INSTALL_HINTS.get(str(cmd[0]), "")) from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            f"'{cmd[0]}' tardó más de {timeout} s y se canceló."
        ) from exc


def tail(text: str, lines: int = 25) -> str:
    """Últimas líneas no vacías de una salida, para mensajes de error."""
    useful = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(useful[-lines:])


# ────────────────────────────────────────────────────────────
# Rutas
# ────────────────────────────────────────────────────────────

def unique_path(path: Path, siblings: Sequence[str] = ()) -> Path:
    """
    Devuelve una ruta libre. Si 'salida.tex' ya existe prueba 'salida_1.tex',
    etc. Se usa cuando el archivo destino podría ser algo del usuario
    (por ejemplo, convertir 'tesis.pdf' no debe machacar 'tesis.tex').

    'siblings' son extensiones que tampoco pueden existir con ese nombre: un
    .tex junto a un .pdf del mismo nombre acabaría machacándolo al compilar.
    """
    path = Path(path)

    def free(candidate: Path) -> bool:
        return not candidate.exists() and not any(
            candidate.with_suffix(ext).exists() for ext in siblings
        )

    if free(path):
        return path
    for i in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if free(candidate):
            return candidate
    raise ConversionError(f"No se pudo encontrar un nombre libre para {path.name}")


def resolve_output(
    source: Path,
    suffix: str,
    output: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Calcula la ruta de salida.

    - Si el usuario dio una ruta explícita, se respeta.
    - Si dio una carpeta, se usa esa carpeta con el nombre del original.
    - Si no, el archivo sale junto al original.

    Con overwrite=False se evita pisar un archivo que ya existía (los .tex
    generados), con overwrite=True se pisa (los artefactos de compilación:
    .pdf y .docx regenerables a partir del .tex).
    """
    source = Path(source)
    if output is not None:
        target = Path(output)
        if target.is_dir():
            target = target / (source.stem + suffix)
    else:
        folder = Path(output_dir) if output_dir else source.parent
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (source.stem + suffix)

    target.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        # Un .tex se compila a un .pdf con su mismo nombre: si ese PDF ya
        # existe (el original de un pdf2tex, sin ir más lejos) se buscaría
        # otro nombre, porque compilar lo sobrescribiría.
        siblings = (".pdf",) if suffix == ".tex" and output is None else ()
        target = unique_path(target, siblings)
    return target


def human_size(path: Path | int) -> str:
    size = path if isinstance(path, int) else Path(path).stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def relative_posix(path: Path, base: Path) -> str:
    """Ruta relativa con '/' — LaTeX no acepta '\\' en \\includegraphics."""
    try:
        rel = os.path.relpath(str(path), str(base))
    except ValueError:            # unidades distintas en Windows
        rel = str(path)
    return rel.replace("\\", "/")


def open_in_explorer(path: Path) -> None:
    """Abre el archivo en su aplicación por defecto (o la carpeta que lo contiene)."""
    path = Path(path)
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - API estándar de Windows
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_in_explorer(path: Path) -> None:
    """Abre el explorador de archivos con el archivo seleccionado."""
    path = Path(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        open_in_explorer(path.parent)
