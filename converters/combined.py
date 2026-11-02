"""
combined.py - Las conversiones directas entre PDF y Word.

Para quien las usa son un solo paso. Por dentro, PDF → Word reutiliza lo que ya
recupera las fórmulas de un PDF y lo traduce a ecuaciones nativas de Word: el
.tex intermedio se queda en una carpeta temporal, salvo que se pida conservarlo.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from . import office
from .common import (
    ConversionError,
    ConversionResult,
    Logger,
    as_logger,
    human_size,
    resolve_output,
    unique_path,
)
from .docx_to_latex import docx_to_latex
from .latex_to_docx import latex_to_docx
from .latex_to_pdf import latex_to_pdf
from .pdf_to_latex import pdf_to_latex


def pdf_to_docx(
    pdf_path: Path | str,
    output: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    *,
    pages: Optional[str] = None,
    extract_images: bool = True,
    math_reconstruction: bool = True,
    math_ocr: bool = False,
    ocr_backend: Optional[str] = None,
    toc: bool = False,
    number_sections: bool = False,
    reference_doc: Optional[Path | str] = None,
    keep_latex: bool = False,
    logger: Optional[Logger] = None,
) -> ConversionResult:
    log = as_logger(logger)
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise ConversionError(f"No existe el archivo: {pdf_path}")

    # El usuario pudo haber retocado un .docx anterior: no se pisa.
    target = resolve_output(pdf_path, ".docx", output, output_dir, overwrite=False)

    temporal = Path(tempfile.mkdtemp(prefix="latexinter-"))
    try:
        carpeta = target.parent if keep_latex else temporal
        tex = unique_path(carpeta / (target.stem + ".tex"))
        # Las ecuaciones tienen que llegar como LaTeX: en imagen, Word no
        # dejaría editarlas.
        leido = pdf_to_latex(
            pdf_path, output=tex,
            pages=pages,
            extract_images=extract_images,
            math_reconstruction=math_reconstruction,
            display_equations="latex",
            math_ocr=math_ocr,
            ocr_backend=ocr_backend,
            logger=log,
        )
        escrito = latex_to_docx(
            leido.output, output=target,
            toc=toc,
            number_sections=number_sections,
            reference_doc=reference_doc,
            logger=log,
        )
    finally:
        shutil.rmtree(temporal, ignore_errors=True)

    extras = list(leido.extras) if keep_latex else []
    if keep_latex:
        extras.insert(0, leido.output)
    return ConversionResult(
        output=escrito.output,
        extras=extras,
        warnings=[*_sin_hablar_del_tex(leido.warnings, keep_latex), *escrito.warnings],
        stats={**leido.stats, **escrito.stats},
    )


def _sin_hablar_del_tex(avisos: list[str], tex_visible: bool) -> list[str]:
    """Quien pide un Word no tiene por qué saber que hubo un .tex por medio."""
    if tex_visible:
        return avisos
    return [
        re.sub(
            r"^(\d+) ecuaciones destacadas quedaron como imagen; .*\.tex\.$",
            r"\1 ecuaciones destacadas no se pudieron colocar en el documento; revisa que no falte ninguna.",
            aviso,
        )
        for aviso in avisos
    ]


def docx_to_pdf(
    docx_path: Path | str,
    output: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    *,
    via_latex: bool = False,
    engine: str = "pdflatex",
    logger: Optional[Logger] = None,
) -> ConversionResult:
    log = as_logger(logger)
    docx_path = Path(docx_path).resolve()
    if not docx_path.exists():
        raise ConversionError(f"No existe el archivo: {docx_path}")

    target = resolve_output(docx_path, ".pdf", output, output_dir, overwrite=False)
    programa = None if via_latex else office.office_name()

    if programa:
        log(f"Exportando con {programa}…")
        office.export_pdf(docx_path, target)
        log(f"Listo: {target.name} ({human_size(target)})")
        return ConversionResult(output=target, stats={"motor": programa})

    log("Sin Word ni LibreOffice: se compila a través de LaTeX." if not via_latex
        else "Compilando a través de LaTeX…")
    temporal = Path(tempfile.mkdtemp(prefix="latexinter-"))
    try:
        leido = docx_to_latex(docx_path, output=temporal / (target.stem + ".tex"), logger=log)
        compilado = latex_to_pdf(leido.output, engine=engine, logger=log)
        shutil.move(str(compilado.output), target)
    finally:
        shutil.rmtree(temporal, ignore_errors=True)

    avisos = [*leido.warnings, *compilado.warnings]
    if not via_latex:
        avisos.insert(0, "Instala Word o LibreOffice para conservar mejor la maquetación del documento.")
    log(f"Listo: {target.name} ({human_size(target)})")
    return ConversionResult(output=target, warnings=avisos, stats={"motor": engine})
