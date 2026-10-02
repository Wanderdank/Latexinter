"""
Latexinter - Conversores entre PDF, LaTeX y Word.

    from converters import convert, CONVERSIONS
    resultado = convert("pdf2tex", "documento.pdf", logger=print)

Cada conversor devuelve un ConversionResult con el archivo generado, los
archivos accesorios (imágenes, markdown), los avisos y unas estadísticas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .common import (
    ConversionError,
    ConversionResult,
    Logger,
    MissingDependency,
    dependency_report,
    human_size,
    open_in_explorer,
    reveal_in_explorer,
)
from .docx_to_latex import docx_to_latex
from .latex_to_docx import latex_to_docx
from .latex_to_pdf import latex_to_pdf
from .pdf_to_latex import pdf_to_latex

__all__ = [
    "CONVERSIONS",
    "Conversion",
    "ConversionError",
    "ConversionResult",
    "MissingDependency",
    "SUPPORTED_EXTENSIONS",
    "conversions_for",
    "convert",
    "dependency_report",
    "docx_to_latex",
    "human_size",
    "latex_to_docx",
    "latex_to_pdf",
    "open_in_explorer",
    "pdf_to_latex",
    "reveal_in_explorer",
]


@dataclass(frozen=True)
class Conversion:
    """Una dirección de conversión, con lo que la interfaz necesita saber."""

    key: str
    label: str
    description: str
    source_extensions: tuple[str, ...]
    target_extension: str
    function: Callable[..., ConversionResult]
    options: frozenset[str] = field(default_factory=frozenset)

    def accepts(self, path: Path | str) -> bool:
        return Path(path).suffix.lower() in self.source_extensions


CONVERSIONS: dict[str, Conversion] = {
    "pdf2tex": Conversion(
        key="pdf2tex",
        label="PDF → LaTeX",
        description="Extrae texto, estructura, imágenes y fórmulas del PDF.",
        source_extensions=(".pdf",),
        target_extension=".tex",
        function=pdf_to_latex,
        options=frozenset({"pages", "twocolumn", "extract_images",
                           "math_reconstruction", "display_equations",
                           "math_ocr", "ocr_backend", "keep_markdown"}),
    ),
    "tex2pdf": Conversion(
        key="tex2pdf",
        label="LaTeX → PDF",
        description="Compila el documento con pdflatex, resolviendo referencias.",
        source_extensions=(".tex",),
        target_extension=".pdf",
        function=latex_to_pdf,
        options=frozenset({"engine", "clean_aux", "max_passes", "synctex"}),
    ),
    "tex2docx": Conversion(
        key="tex2docx",
        label="LaTeX → Word",
        description="Genera un .docx con las ecuaciones editables en Word.",
        source_extensions=(".tex",),
        target_extension=".docx",
        function=latex_to_docx,
        options=frozenset({"toc", "number_sections", "reference_doc"}),
    ),
    "docx2tex": Conversion(
        key="docx2tex",
        label="Word → LaTeX",
        description="Convierte el .docx a LaTeX, con sus imágenes y ecuaciones.",
        source_extensions=(".docx",),
        target_extension=".tex",
        function=docx_to_latex,
        options=frozenset({"twocolumn", "extract_images"}),
    ),
}

# Extensiones que la interfaz sabe abrir.
SUPPORTED_EXTENSIONS = tuple(
    sorted({ext for c in CONVERSIONS.values() for ext in c.source_extensions})
)


def conversions_for(path: Path | str) -> list[Conversion]:
    """Conversiones disponibles para un archivo, en orden de uso más probable."""
    return [c for c in CONVERSIONS.values() if c.accepts(path)]


def convert(
    key: str,
    source: Path | str,
    output: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    *,
    logger: Optional[Logger] = None,
    **options,
) -> ConversionResult:
    """Ejecuta una conversión por su clave ('pdf2tex', 'tex2pdf', …)."""
    try:
        conversion = CONVERSIONS[key]
    except KeyError:
        raise ConversionError(
            f"Conversión desconocida: {key}. Opciones: {', '.join(CONVERSIONS)}"
        ) from None

    # Se descartan las opciones que este conversor no entiende, para que la
    # interfaz pueda mandar siempre el mismo diccionario.
    accepted = {k: v for k, v in options.items() if k in conversion.options}
    return conversion.function(source, output, output_dir, logger=logger, **accepted)
