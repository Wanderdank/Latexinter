"""
latex_to_docx.py - Convierte un documento LaTeX a Word (.docx).

Lo hace pandoc. Dos detalles importantes:

  · --resource-path apunta a la carpeta del .tex, para que encuentre las
    imágenes de \\includegraphics y las incruste en el documento.
  · Las matemáticas se traducen a OMML, el formato nativo de Word, así que las
    fórmulas quedan editables con el editor de ecuaciones y no como imágenes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .common import (
    ConversionError,
    ConversionResult,
    Logger,
    as_logger,
    find_tool,
    human_size,
    require_tool,
    resolve_output,
    run_command,
    tail,
)

_BIBLIOGRAPHY = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^}]*)\}")


def _find_bibliography(tex_path: Path, source: str) -> list[Path]:
    """Archivos .bib referenciados por el documento y que existan en disco."""
    found: list[Path] = []
    for match in _BIBLIOGRAPHY.finditer(source):
        for name in match.group(1).split(","):
            name = name.strip()
            if not name:
                continue
            candidate = tex_path.parent / name
            if candidate.suffix.lower() != ".bib":
                candidate = candidate.with_suffix(".bib")
            if candidate.exists():
                found.append(candidate)
    return found


def latex_to_docx(
    tex_path: Path | str,
    output: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    *,
    reference_doc: Optional[Path | str] = None,
    number_sections: bool = True,
    toc: bool = False,
    logger: Optional[Logger] = None,
) -> ConversionResult:
    log = as_logger(logger)
    tex_path = Path(tex_path).resolve()

    if not tex_path.exists():
        raise ConversionError(f"No existe el archivo: {tex_path}")
    if tex_path.suffix.lower() != ".tex":
        raise ConversionError("El archivo de entrada debe ser un .tex")

    require_tool("pandoc")
    source = tex_path.read_text(encoding="utf-8", errors="replace")

    # El .docx se regenera a partir del .tex, así que se puede sobrescribir.
    target = resolve_output(tex_path, ".docx", output, output_dir, overwrite=True)
    log(f"Entrada : {tex_path.name} ({human_size(tex_path)})")
    log(f"Salida  : {target}")

    cmd = [
        "pandoc", str(tex_path),
        "-o", str(target),
        "--from=latex+raw_tex",
        "--to=docx",
        "--standalone",
        "--wrap=none",
        f"--resource-path={tex_path.parent}",
    ]
    if number_sections:
        cmd.append("--number-sections")
    if toc:
        cmd.extend(["--toc", "--toc-depth=3"])
    if reference_doc:
        reference = Path(reference_doc)
        if not reference.exists():
            raise ConversionError(f"No existe la plantilla de Word: {reference}")
        cmd.append(f"--reference-doc={reference}")

    warnings: list[str] = []
    bibs = _find_bibliography(tex_path, source)
    if bibs:
        if find_tool("pandoc"):
            log(f"Bibliografía: {', '.join(b.name for b in bibs)}")
            cmd.append("--citeproc")
            for bib in bibs:
                cmd.append(f"--bibliography={bib}")
    elif _BIBLIOGRAPHY.search(source):
        warnings.append(
            "El documento cita una bibliografía pero no se encontró el archivo .bib; "
            "las citas saldrán como texto sin resolver."
        )

    log("Convirtiendo con pandoc…")
    result = run_command(cmd, cwd=tex_path.parent, logger=None, timeout=600)

    if result.returncode != 0 or not target.exists():
        raise ConversionError(
            "pandoc no pudo generar el documento de Word:\n" + tail(result.stderr)
        )
    if result.stderr.strip():
        warnings.append(tail(result.stderr, 8))

    log(f"Listo: {target.name} ({human_size(target)})")
    return ConversionResult(
        output=target,
        warnings=warnings,
        stats={"origen": tex_path.name},
    )
