"""
latex_to_docx.py - Convierte un documento LaTeX a Word (.docx).

Lo hace pandoc. Algunos detalles importantes:

  · --resource-path apunta a la carpeta del .tex, para que encuentre las
    imágenes de \\includegraphics y las incruste en el documento.
  · Las matemáticas se traducen a OMML, el formato nativo de Word, así que las
    fórmulas quedan editables con el editor de ecuaciones y no como imágenes.
  · Los estilos salen de assets/word-plantilla.docx. Los de pandoc por defecto
    (títulos azules, mucho aire) delatan una conversión automática.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
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
_MATH_WARNING = "Could not convert TeX math"
# Instalado, los módulos están en _internal/converters y los datos en
# _internal/assets: la misma ruta relativa que en el proyecto.
WORD_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "word-plantilla.docx"


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


def word_friendly_source(source: str) -> str:
    """
    Lo que pandoc no sabe leer de sus propios .tex: envuelve las imágenes en
    \\pandocbounded, una macro que al leerla expande a un \\sbox, y la imagen
    se pierde sin ningún aviso.
    """
    return source.replace("\\pandocbounded{", "{")


def split_pandoc_warnings(stderr: str) -> tuple[int, list[str]]:
    """Cuántas fórmulas no pudo traducir pandoc, y el resto de sus avisos."""
    avisos = re.split(r"(?m)^(?=\[WARNING\])", stderr or "")
    formulas = sum(1 for aviso in avisos if _MATH_WARNING in aviso)
    otros = [aviso.strip() for aviso in avisos if aviso.strip() and _MATH_WARNING not in aviso]
    return formulas, otros


def count_word_content(docx: Path) -> dict[str, int]:
    """Ecuaciones editables e imágenes que hay de verdad dentro de un .docx."""
    with zipfile.ZipFile(docx) as paquete:
        documento = paquete.read("word/document.xml").decode("utf-8", "replace")
        imagenes = sum(1 for nombre in paquete.namelist() if nombre.startswith("word/media/"))
    return {
        "ecuaciones_word": len(re.findall(r"<m:oMath[ >]", documento)),
        "imagenes": imagenes,
    }


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
    # Nunca se pisa un .docx: pueden ser horas de retoques hechos en Word.
    target = resolve_output(tex_path, ".docx", output, output_dir, overwrite=False)
    log(f"Entrada : {tex_path.name} ({human_size(tex_path)})")
    log(f"Salida  : {target}")

    legible = word_friendly_source(source)
    temporal: Optional[Path] = None
    entrada = tex_path
    if legible != source:
        # Junto al original, porque las rutas de \input se resuelven desde ahí.
        descriptor, nombre = tempfile.mkstemp(prefix=".latexinter-", suffix=".tex", dir=tex_path.parent)
        os.close(descriptor)
        temporal = Path(nombre)
        temporal.write_text(legible, encoding="utf-8")
        entrada = temporal

    cmd = [
        "pandoc", str(entrada),
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
    elif WORD_TEMPLATE.exists():
        cmd.append(f"--reference-doc={WORD_TEMPLATE}")

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

    log("Generando el documento de Word…")
    try:
        result = run_command(cmd, cwd=tex_path.parent, logger=None, timeout=600)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)

    if result.returncode != 0 or not target.exists():
        raise ConversionError(
            "pandoc no pudo generar el documento de Word:\n" + tail(result.stderr)
        )

    formulas_sin_traducir, otros_avisos = split_pandoc_warnings(result.stderr)
    if formulas_sin_traducir:
        warnings.append(
            f"{formulas_sin_traducir} "
            + ("fórmula no se pudo convertir" if formulas_sin_traducir == 1
               else "fórmulas no se pudieron convertir")
            + " a ecuación de Word y "
            + ("quedó" if formulas_sin_traducir == 1 else "quedaron")
            + " como texto LaTeX."
        )
    if otros_avisos:
        warnings.append(tail("\n".join(otros_avisos), 8))

    stats = {"origen": tex_path.name, **count_word_content(target)}
    log(f"Listo: {target.name} ({human_size(target)})")
    return ConversionResult(output=target, warnings=warnings, stats=stats)
