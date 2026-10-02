"""
latex_to_pdf.py - Compila un documento LaTeX a PDF.

Se compila siempre en la carpeta del .tex para que las rutas relativas de
\\includegraphics y \\input sigan funcionando, y luego se mueve el PDF si se
pidió otra carpeta de salida. Se repiten las pasadas necesarias para que el
índice y las referencias cruzadas queden bien, y se ejecuta bibtex si el
documento tiene bibliografía.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from .common import (
    ConversionError,
    ConversionResult,
    Logger,
    as_logger,
    engine_is_miktex,
    find_tool,
    human_size,
    require_tool,
    run_command,
)

ENGINES = ("pdflatex", "xelatex", "lualatex")

AUX_EXTENSIONS = (
    ".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls", ".fdb_latexmk",
    ".bbl", ".blg", ".bcf", ".run.xml", ".nav", ".snm", ".vrb", ".idx",
    ".ilg", ".ind", ".synctex.gz", ".xdv",
)

# "./doc.tex:42: Undefined control sequence."  y  "! LaTeX Error: ..."
_FILE_LINE_ERROR = re.compile(r"^(?P<file>[^\s:]+\.\w+):(?P<line>\d+): (?P<msg>.+)$", re.M)
_BANG_ERROR = re.compile(r"^! (?P<msg>.+)$", re.M)
_MISSING_PACKAGE = re.compile(r"File `([^']+\.sty)' not found", re.M)
_RERUN = re.compile(r"Rerun to get|Rerun LaTeX|There were undefined references", re.I)
_CITATIONS = re.compile(r"\\(?:cite[a-zA-Z]*|nocite)\s*[\[{]")
_BIBLIOGRAPHY = re.compile(r"\\(?:bibliography|addbibresource)\s*\{")


def _collect_errors(log_text: str) -> list[str]:
    errors: list[str] = []
    for match in _FILE_LINE_ERROR.finditer(log_text):
        msg = match.group("msg").strip()
        if msg.lower().startswith(("warning", "info")):
            continue
        errors.append(f"{match.group('file')}:{match.group('line')}: {msg}")
    if not errors:
        for match in _BANG_ERROR.finditer(log_text):
            errors.append(match.group("msg").strip())
    missing = _MISSING_PACKAGE.findall(log_text)
    for sty in dict.fromkeys(missing):
        errors.append(
            f"Falta el paquete '{sty}'. Instálalo desde la consola de MiKTeX "
            f"(MiKTeX Console → Packages)."
        )
    # Sin duplicados, conservando el orden
    return list(dict.fromkeys(errors))


def clean_aux_files(tex_path: Path, *, keep_log: bool = False) -> int:
    """Borra los archivos auxiliares que deja LaTeX. Devuelve cuántos borró."""
    removed = 0
    for ext in AUX_EXTENSIONS:
        if keep_log and ext == ".log":
            continue
        candidate = tex_path.parent / (tex_path.stem + ext)
        if candidate.exists() and candidate.is_file():
            try:
                candidate.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def latex_to_pdf(
    tex_path: Path | str,
    output: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    *,
    engine: str = "pdflatex",
    max_passes: int = 3,
    clean_aux: bool = True,
    synctex: bool = True,
    logger: Optional[Logger] = None,
) -> ConversionResult:
    log = as_logger(logger)
    tex_path = Path(tex_path).resolve()

    if not tex_path.exists():
        raise ConversionError(f"No existe el archivo: {tex_path}")
    if tex_path.suffix.lower() != ".tex":
        raise ConversionError("El archivo de entrada debe ser un .tex")
    if engine not in ENGINES:
        raise ConversionError(f"Motor desconocido: {engine}")

    require_tool(engine)
    source = tex_path.read_text(encoding="utf-8", errors="replace")

    base_cmd = [
        engine,
        "-interaction=nonstopmode",
        "-file-line-error",
    ]
    if synctex:
        base_cmd.append("-synctex=1")
    if engine_is_miktex(engine):
        # Deja que MiKTeX descargue solo los paquetes que falten.
        base_cmd.append("--enable-installer")
    base_cmd.append(tex_path.name)

    log(f"Entrada : {tex_path.name} ({human_size(tex_path)})")
    log(f"Motor   : {engine}")

    produced = tex_path.with_suffix(".pdf")
    # Si LaTeX se para con un error fatal no escribe el PDF, pero el de la
    # compilación anterior sigue ahí: hay que distinguirlo del recién hecho.
    previous_mtime = produced.stat().st_mtime_ns if produced.exists() else None
    warnings: list[str] = []
    last_log = ""

    for attempt in range(1, max_passes + 1):
        log(f"Pasada {attempt} de {engine}…")
        result = run_command(base_cmd, cwd=tex_path.parent, logger=None, timeout=600)
        log_file = tex_path.with_suffix(".log")
        last_log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else result.stdout

        if attempt == 1 and _BIBLIOGRAPHY.search(source) and _CITATIONS.search(source):
            bib_tool = "biber" if "\\addbibresource" in source else "bibtex"
            if find_tool(bib_tool):
                log(f"Procesando bibliografía con {bib_tool}…")
                run_command([bib_tool, tex_path.stem], cwd=tex_path.parent, timeout=300)
            else:
                warnings.append(
                    f"El documento tiene bibliografía pero '{bib_tool}' no está instalado."
                )
            continue                                  # obliga a otra pasada

        if not _RERUN.search(last_log):
            break

    stale = produced.exists() and produced.stat().st_mtime_ns == previous_mtime
    if not produced.exists() or stale:
        errors = _collect_errors(last_log)
        detail = "\n".join(f"  · {e}" for e in errors[:8]) or "  (revisa el .log)"
        raise ConversionError(
            f"LaTeX no generó el PDF. Errores encontrados:\n{detail}\n\n"
            f"Registro completo: {tex_path.with_suffix('.log')}"
        )

    # Avisos que no impiden compilar pero conviene ver.
    errors = _collect_errors(last_log)
    if errors:
        warnings.append("LaTeX informó de errores (el PDF se generó igualmente):")
        warnings.extend(errors[:5])
    if re.search(r"LaTeX Warning: .*undefined", last_log, re.I):
        warnings.append("Hay referencias cruzadas sin resolver (¿faltan \\label?).")

    # Colocar el PDF donde toca.
    if output is not None:
        target = Path(output)
        if target.is_dir():
            target = target / produced.name
    elif output_dir is not None:
        target = Path(output_dir) / produced.name
    else:
        target = produced

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.resolve() != produced.resolve():
        shutil.move(str(produced), str(target))

    if clean_aux:
        removed = clean_aux_files(tex_path, keep_log=bool(errors))
        log(f"Archivos auxiliares eliminados: {removed}")

    log(f"Listo: {target.name} ({human_size(target)})")
    return ConversionResult(
        output=target,
        warnings=warnings,
        stats={"motor": engine, "paginas": _page_count(target)},
    )


def _page_count(pdf_path: Path) -> Optional[int]:
    try:
        import fitz

        with fitz.open(str(pdf_path)) as doc:
            return doc.page_count
    except Exception:
        return None
