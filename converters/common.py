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
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

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


class Cancelled(ConversionError):
    """El usuario detuvo el trabajo (o se cerró la aplicación)."""

    def __init__(self) -> None:
        super().__init__("Cancelado.")


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

def refresh_path() -> None:
    """
    Añade al PATH del proceso lo que el registro de Windows tenga y falte.
    Cada programa recibe el PATH al arrancar: si MiKTeX o pandoc se instalan
    justo antes (el instalador de Latexinter lo hace), sin esto no se
    encontrarían hasta reiniciar la sesión.
    """
    if sys.platform != "win32":
        return
    import winreg

    claves = (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    )
    actuales = os.environ.get("PATH", "").split(os.pathsep)
    vistas = {os.path.normcase(p.rstrip("\\/")) for p in actuales if p}
    nuevas: list[str] = []
    for raiz, subclave in claves:
        try:
            with winreg.OpenKey(raiz, subclave) as clave:
                valor, _ = winreg.QueryValueEx(clave, "Path")
        except OSError:
            continue
        for carpeta in os.path.expandvars(valor).split(os.pathsep):
            normal = os.path.normcase(carpeta.rstrip("\\/"))
            if carpeta and normal not in vistas:
                vistas.add(normal)
                nuevas.append(carpeta)
    if nuevas:
        os.environ["PATH"] = os.pathsep.join([p for p in actuales if p] + nuevas)


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
    refresh_path()
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

class CancelToken:
    """
    Permite detener desde otro hilo los programas externos que lanza un hilo
    de trabajo. Matar el hilo no basta: pdflatex seguiría vivo, y en Windows
    mantendría bloqueado el PDF.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._procesos: set[subprocess.Popen] = set()
        self.cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            procesos = list(self._procesos)
        for proceso in procesos:
            _kill(proceso)

    def _register(self, proceso: subprocess.Popen) -> None:
        with self._lock:
            self._procesos.add(proceso)
            cancelado = self.cancelled
        if cancelado:
            _kill(proceso)

    def _unregister(self, proceso: subprocess.Popen) -> None:
        with self._lock:
            self._procesos.discard(proceso)


_hilo = threading.local()


@contextmanager
def cancellable(token: CancelToken) -> Iterator[CancelToken]:
    """Lo que se ejecute dentro, en este hilo, se puede detener con el token."""
    anterior = getattr(_hilo, "token", None)
    _hilo.token = token
    try:
        yield token
    finally:
        _hilo.token = anterior


def _current_token() -> Optional[CancelToken]:
    return getattr(_hilo, "token", None)


def _kill(proceso: subprocess.Popen) -> None:
    """Mata el proceso y lo que haya lanzado (MiKTeX instala paquetes así)."""
    if proceso.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proceso.pid)],
                capture_output=True, timeout=10, creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proceso.kill()
    except OSError:
        pass


def run_command(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    logger: Optional[Logger] = None,
    timeout: Optional[int] = 600,
) -> subprocess.CompletedProcess:
    """
    Ejecuta un comando y captura su salida (sin ventana de consola). Si el
    hilo trabaja dentro de cancellable(), el comando se puede detener.
    """
    log = as_logger(logger)
    log(f"$ {' '.join(str(c) for c in cmd)}")

    token = _current_token()
    if token is not None and token.cancelled:
        raise Cancelled()

    argumentos = [str(c) for c in cmd]
    try:
        proceso = subprocess.Popen(
            argumentos,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise MissingDependency(str(cmd[0]), INSTALL_HINTS.get(str(cmd[0]), "")) from exc

    if token is not None:
        token._register(proceso)
    try:
        with proceso:
            try:
                stdout, stderr = proceso.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                _kill(proceso)
                proceso.communicate()
                raise ConversionError(
                    f"'{cmd[0]}' tardó más de {timeout} s y se canceló."
                ) from exc
            except BaseException:
                _kill(proceso)
                raise
    finally:
        if token is not None:
            token._unregister(proceso)

    if token is not None and token.cancelled:
        raise Cancelled()
    return subprocess.CompletedProcess(argumentos, proceso.returncode, stdout, stderr)


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
    # Rutas absolutas: pandoc se ejecuta dentro de la carpeta de salida, y una
    # ruta relativa como «out/doc.tex» acabaría en «out/out/doc.tex».
    source = Path(source).resolve()
    if output is not None:
        target = Path(output).resolve()
        if target.is_dir():
            target = target / (source.stem + suffix)
    else:
        folder = Path(output_dir).resolve() if output_dir else source.parent
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
