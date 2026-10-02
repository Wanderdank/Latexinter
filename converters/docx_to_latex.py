"""
docx_to_latex.py - Convierte un documento de Word (.docx) a LaTeX.

pandoc lee el .docx directamente, incluidas las ecuaciones (que en Word se
guardan como OMML y se traducen a matemáticas de LaTeX de verdad, no a
imágenes). Las imágenes incrustadas se vuelcan a una carpeta junto al .tex.

Después se pasa el resultado por texpost, que añade los paquetes necesarios y
traduce los símbolos Unicode que pdflatex no sabe imprimir.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from . import texpost
from .common import (
    ConversionError,
    ConversionResult,
    Logger,
    as_logger,
    human_size,
    require_tool,
    resolve_output,
    run_command,
    tail,
)

PANDOC_TO = "latex"
PANDOC_FROM = "docx+styles"

# Formatos de imagen que \includegraphics entiende con pdflatex.
_IMAGENES_LATEX = {".png", ".jpg", ".jpeg", ".pdf", ".eps"}


def docx_to_latex(
    docx_path: Path | str,
    output: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    *,
    twocolumn: bool = False,
    extract_images: bool = True,
    standalone: bool = True,
    logger: Optional[Logger] = None,
) -> ConversionResult:
    log = as_logger(logger)
    docx_path = Path(docx_path).resolve()

    if not docx_path.exists():
        raise ConversionError(f"No existe el archivo: {docx_path}")
    if docx_path.suffix.lower() not in (".docx", ".doc", ".odt", ".rtf"):
        raise ConversionError("El archivo de entrada debe ser un .docx")
    if docx_path.suffix.lower() == ".doc":
        raise ConversionError(
            "El formato .doc antiguo no se puede leer directamente. "
            "Ábrelo en Word y guárdalo como .docx."
        )

    require_tool("pandoc")

    target = resolve_output(docx_path, ".tex", output, output_dir, overwrite=False)
    log(f"Entrada : {docx_path.name} ({human_size(docx_path)})")
    log(f"Salida  : {target}")

    extras: list[Path] = []
    warnings: list[str] = []

    # pandoc reescribe los enlaces a las imágenes relativos a esta carpeta,
    # así que se le pasa una ruta relativa y se ejecuta desde el destino.
    media_name = f"{target.stem}_imagenes"
    media_dir = target.parent / media_name

    cmd = [
        "pandoc", str(docx_path),
        "-o", str(target),
        f"--from={PANDOC_FROM}",
        f"--to={PANDOC_TO}",
        "--wrap=preserve",
        "--top-level-division=section",
    ]
    if standalone:
        cmd.extend([
            "--standalone",
            "-V", "documentclass=article",
            "-V", "geometry:margin=2.5cm",
            "-V", "fontenc=T1",
            "-V", "lang=es",
        ])
    if twocolumn:
        cmd.extend(["-V", "classoption=twocolumn"])
    if extract_images:
        cmd.append(f"--extract-media={media_name}")

    log("Convirtiendo con pandoc…")
    result = run_command(cmd, cwd=target.parent, logger=None, timeout=600)

    if result.returncode != 0 or not target.exists():
        raise ConversionError(
            "pandoc no pudo leer el documento de Word:\n" + tail(result.stderr)
        )
    if result.stderr.strip():
        warnings.append(tail(result.stderr, 8))

    image_count = 0
    if extract_images and media_dir.exists():
        images = [p for p in media_dir.rglob("*") if p.is_file()]
        image_count = len(images)
        if image_count:
            _flatten_media(target, media_dir, media_name)
            extras.append(media_dir)
            log(f"Imágenes extraídas: {image_count}")
            # Word guarda a veces dibujos en formatos de Windows (EMF, WMF)
            # que pdflatex no sabe incluir: el documento no compilaría.
            raras = sorted({
                p.suffix.lower() for p in images
                if p.suffix.lower() not in _IMAGENES_LATEX
            })
            if raras:
                warnings.append(
                    f"Hay imágenes en formato {', '.join(raras)}, que pdflatex no "
                    "sabe incluir. Ábrelas y guárdalas como PNG, o cámbialas en "
                    "el .tex, para que el documento compile."
                )
        else:
            shutil.rmtree(media_dir, ignore_errors=True)

    stats = texpost.postprocess(
        target,
        source=docx_path.name,
        tool="pandoc (docx → latex)",
        twocolumn=twocolumn,
    )
    stats["imagenes"] = image_count

    if stats["unicode_sin_traducir"]:
        warnings.append(
            "Quedaron caracteres poco comunes sin traducir: "
            + " ".join(stats["unicode_sin_traducir"])
        )

    log(f"Listo: {stats['formulas']} fórmulas, {human_size(target)}")
    return ConversionResult(output=target, extras=extras, warnings=warnings, stats=stats)


def _flatten_media(tex_path: Path, media_dir: Path, media_name: str) -> None:
    """
    pandoc anida las imágenes en <carpeta>/media/. Se suben un nivel para que
    las rutas del .tex queden cortas y legibles.
    """
    nested = media_dir / "media"
    if not nested.is_dir():
        return

    content = tex_path.read_text(encoding="utf-8")
    moved = False
    for image in list(nested.iterdir()):
        destination = media_dir / image.name
        if destination.exists():
            continue
        shutil.move(str(image), str(destination))
        moved = True
    if moved:
        content = content.replace(f"{media_name}/media/", f"{media_name}/")
        tex_path.write_text(content, encoding="utf-8")
    if not any(nested.iterdir()):
        nested.rmdir()
