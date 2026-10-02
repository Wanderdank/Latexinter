"""
pdf_to_latex.py - Convierte un PDF a LaTeX.

Tubería:  PDF → (pymupdf4llm) Markdown → (pdfmath + mathfix) → (pandoc) LaTeX

pymupdf4llm reconoce títulos, listas, tablas e imágenes. pdfmath recupera lo
que solo se distingue mirando la maquetación —superíndices, subíndices y las
ecuaciones destacadas, que el extractor convierte en imagen— y mathfix traduce
los símbolos Unicode a LaTeX matemático agrupado.

Además se limpian los residuos típicos de un PDF: encabezados repetidos en
cada página, números de página sueltos, índices con puntos suspensivos y el
logotipo de LaTeX descompuesto en letras.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections import Counter
from dataclasses import replace as _replace
from pathlib import Path
from typing import Optional

from . import mathfix, mathocr, pdfmath, texpost
from .common import (
    ConversionError,
    ConversionResult,
    Logger,
    as_logger,
    human_size,
    relative_posix,
    require_module,
    require_tool,
    resolve_output,
    run_command,
    tail,
)

PANDOC_FROM = (
    "markdown+tex_math_dollars+tex_math_single_backslash+raw_tex"
    "+pipe_tables+grid_tables+backtick_code_blocks"
)

# Qué hacer con las ecuaciones centradas que el extractor convierte en imagen.
DISPLAY_IMAGE = "imagen"        # solo la imagen
DISPLAY_COMMENT = "comentario"  # la imagen, y el LaTeX reconstruido al final
DISPLAY_REPLACE = "latex"       # sustituir la imagen por el LaTeX reconstruido
DISPLAY_AUTO = None             # decidir según lo fiable que sea la lectura


# ────────────────────────────────────────────────────────────
# Selección de páginas
# ────────────────────────────────────────────────────────────

def parse_pages(spec: Optional[str], total: Optional[int] = None) -> Optional[list[int]]:
    """
    Convierte "1-5" o "1,3,8-10" en una lista de índices base 0.
    Devuelve None si no se pidió ninguna selección.
    """
    if not spec or not spec.strip():
        return None

    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                first, last = part.split("-", 1)
                start, end = int(first), int(last)
                if start > end:
                    start, end = end, start
                pages.extend(range(start - 1, end))
            else:
                pages.append(int(part) - 1)
        except ValueError as exc:
            raise ConversionError(
                f'No entiendo el rango de páginas "{part}". '
                "Usa por ejemplo  1-5  o  1,3,8-10"
            ) from exc

    pages = sorted({p for p in pages if p >= 0})
    if not pages:
        raise ConversionError("La selección de páginas quedó vacía.")
    if total is not None:
        fuera = [p + 1 for p in pages if p >= total]
        if fuera:
            raise ConversionError(
                f"El PDF tiene {total} páginas; no existen: {', '.join(map(str, fuera))}"
            )
    return pages


# ────────────────────────────────────────────────────────────
# Limpieza del Markdown intermedio
# ────────────────────────────────────────────────────────────

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_NUMBERED_TITLE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_EMPHASIS_WRAP = re.compile(r"^(?:\*\*|__)(.*?)(?:\*\*|__)$")
_DOT_LEADER = re.compile(r"(?:\.[ \t]*){3,}")
_TOC_TITLE = re.compile(
    r"^#{1,6}\s*(?:\*\*|__)?\s*(?:\d+[.\s]*)?"
    r"(índice|indice|contenido|contents|table of contents|tabla de contenido)"
    r"s?\s*(?:\*\*|__)?\s*$",
    re.IGNORECASE,
)
_PAGE_NUMBER_LINE = re.compile(r"^\s*\d{1,4}\s*$")
_LATEX_LOGO = re.compile(r"L\s*[\[{]?A[\]}]?\s*TEX|LATEX|LaTeX", re.NOFLAG)
_TEX_LOGO = re.compile(r"(?<![A-Za-z\\])TEX(?![A-Za-z])")


def normalize_headings(md: str) -> str:
    """
    El extractor deduce el nivel de los títulos por el tamaño de letra y suele
    ponerlos todos igual. Si el título empieza por su número ("4.1. Listas"),
    ese número dice el nivel real; se usa y se quita, porque LaTeX numera solo.
    """
    lines: list[str] = []
    for line in md.split("\n"):
        match = _HEADING.match(line)
        if not match:
            lines.append(line)
            continue

        level, text = len(match.group(1)), match.group(2).strip()
        wrapped = _EMPHASIS_WRAP.match(text)
        if wrapped:
            text = wrapped.group(1).strip()

        numbered = _NUMBERED_TITLE.match(text)
        if numbered:
            level = min(len(numbered.group(1).split(".")), 3)
            text = numbered.group(2).strip()

        lines.append("#" * level + " " + text if text else "")
    return "\n".join(lines)


def fix_latex_logo(md: str) -> str:
    """El logotipo de LaTeX sale del PDF descompuesto: "L [A] TEX"."""
    md = _LATEX_LOGO.sub("\\\\LaTeX{}", md)
    return _TEX_LOGO.sub("\\\\TeX{}", md)


# Una palabra, o un superíndice tal como lo marca pymupdf4llm: "[A]".
_TITLE_TOKEN = re.compile(r"\[[^\]\s]*\]|[^\s\[]+")


def _join_title(tokens: list[str]) -> str:
    """Junta las palabras; los superíndices van pegados a la anterior: "L[A]"."""
    text = ""
    for token in tokens:
        glue = token.startswith("[") or not text
        text += token if glue else " " + token
    return text


def raw_page_lines(page) -> list[list[str]]:
    """Las líneas de la página en el orden en que están dibujadas, en palabras."""
    try:
        from pymupdf4llm.helpers.get_text_lines import get_raw_lines

        raw = get_raw_lines(page.get_textpage(), clip=page.rect)
    except Exception:       # es una función interna: si cambia, no se toca nada
        return []
    return [
        _TITLE_TOKEN.findall(" ".join(span["text"] for span in spans))
        for _, spans in raw
    ]


def fix_heading_order(md: str, raw_lines: list[list[str]]) -> str:
    """
    El motor de maquetación de pymupdf4llm a veces desordena las palabras de un
    título que lleva un superíndice: "Documento de Ejemplo en L[A]TEX" sale como
    "Documento de en L[A] Ejemplo TEX". Si las palabras de un título son las
    mismas que las de una línea del PDF (o de dos o tres seguidas, si el título
    ocupa varias) pero en otro orden, se toma el orden del PDF.
    """
    if not raw_lines:
        return md

    candidates: list[list[str]] = []
    for size in (1, 2, 3):
        for start in range(len(raw_lines) - size + 1):
            candidates.append([t for line in raw_lines[start:start + size] for t in line])

    lines: list[str] = []
    for line in md.split("\n"):
        match = _HEADING.match(line)
        if match:
            text = match.group(2)
            wrapped = _EMPHASIS_WRAP.match(text)
            inner = wrapped.group(1) if wrapped else text
            tokens = _TITLE_TOKEN.findall(inner)
            if len(tokens) >= 2:
                wanted = Counter(tokens)
                for candidate in candidates:
                    if candidate != tokens and Counter(candidate) == wanted:
                        fixed = _join_title(candidate)
                        if wrapped:
                            fixed = text[:2] + fixed + text[-2:]
                        line = f"{match.group(1)} {fixed}"
                        break
        lines.append(line)
    return "\n".join(lines)


def strip_running_heads(pages: list[str]) -> list[str]:
    """
    Quita los encabezados y pies que se repiten en casi todas las páginas
    (título corto, fecha, nombre de la revista…). Solo actúa si hay suficientes
    páginas como para estar seguros.
    """
    if len(pages) < 3:
        return pages

    candidates: Counter[str] = Counter()
    for text in pages:
        useful = [ln.strip() for ln in text.split("\n") if ln.strip()]
        for line in useful[:2] + useful[-2:]:
            if 3 <= len(line) <= 120:
                candidates[line] += 1

    threshold = max(2, int(len(pages) * 0.6))
    repeated = {line for line, count in candidates.items() if count >= threshold}
    if not repeated:
        return pages

    cleaned: list[str] = []
    for text in pages:
        kept = [ln for ln in text.split("\n") if ln.strip() not in repeated]
        cleaned.append("\n".join(kept))
    return cleaned


def replace_toc_table(md: str) -> str:
    """
    El índice del documento sale como una tabla llena de puntos suspensivos.
    Es ilegible en LaTeX y además redundante: se cambia por \\tableofcontents.
    """
    lines = md.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            result.append(lines[i])
            i += 1
            continue

        start = i
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            i += 1
        block = lines[start:i]

        leaders = sum(1 for row in block if _DOT_LEADER.search(row))
        after_toc_title = any(
            _TOC_TITLE.match(previous)
            for previous in reversed([ln for ln in result if ln.strip()][-3:])
        )
        looks_like_toc = len(block) >= 3 and (
            leaders >= len(block) * 0.3 or after_toc_title
        )

        if looks_like_toc:
            # \tableofcontents ya pone su propio título.
            while result and not result[-1].strip():
                result.pop()
            if result and _TOC_TITLE.match(result[-1]):
                result.pop()
            result.extend(["", "\\tableofcontents", ""])
        else:
            result.extend(block)
    return "\n".join(result)


def clean_markdown(md: str) -> str:
    md = re.sub(r"^-{3,}\s*$", "", md, flags=re.MULTILINE)   # separadores de página
    md = _DOT_LEADER.sub(" ", md)                            # puntos de índice
    md = "\n".join(line.rstrip() for line in md.split("\n"))
    md = "\n".join(
        "" if _PAGE_NUMBER_LINE.match(line) else line for line in md.split("\n")
    )
    md = re.sub(r"\n{4,}", "\n\n\n", md)
    return md.strip() + "\n"


_IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")


def _relocate_images(md: str, base_dir: Path) -> tuple[str, int]:
    """
    pymupdf4llm escribe rutas absolutas y con barras de Windows. LaTeX necesita
    rutas relativas al .tex y con '/'.
    """
    count = 0

    def fix(match: re.Match) -> str:
        nonlocal count
        alt, target = match.group(1), match.group(2).strip()
        if target.startswith(("http://", "https://", "data:")):
            return match.group(0)
        count += 1
        path = Path(target)
        if path.is_absolute():
            return f"![{alt}]({relative_posix(path, base_dir)})"
        return f"![{alt}]({target.replace(chr(92), '/')})"

    return _IMAGE_LINK.sub(fix, md), count


# ────────────────────────────────────────────────────────────
# OCR de fórmulas
# ────────────────────────────────────────────────────────────

def _ocr_fractions(page, text: str, ocr, log, cache: dict) -> tuple[str, int]:
    """
    Reconoce las fracciones de la página y las mete en el Markdown.

    Una fracción no sobrevive a la extracción de texto: el numerador y el
    denominador salen pegados y la raya desaparece. Se localiza el rectángulo
    que ocupa, se recorta de la página y se le pasa al modelo, que sí ve la
    fórmula tal como está compuesta.
    """
    regiones = pdfmath.collect_fraction_regions(page)
    if not regiones:
        return text, 0

    reconocidas = 0
    for region in regiones:
        latex = _recognize(page, region.rect, region.exclude, ocr, cache)
        if not latex:
            continue
        try:
            text, cuantas = re.subn(
                region.pattern, lambda _m, r=latex: "$" + r + "$", text, count=1
            )
        except re.error:
            continue
        if cuantas:
            reconocidas += cuantas
            log(f"  fracción reconocida: {latex[:70]}")
    return text, reconocidas


def _ocr_display(page, equations, ocr, log, cache: dict) -> tuple[list, int]:
    """
    Decide, ecuación por ecuación, quién la lee mejor.

    El OCR solo entra donde la geometría no llega: donde hay una fracción y la
    fórmula está apilada. En una ecuación de una sola línea la reconstrucción
    por maquetación es más de fiar —lee los caracteres del PDF en vez de
    adivinarlos— y ahí el modelo se equivoca de vez en cuando.

    Si el modelo no saca en claro la ecuación entera, se recurre a un método
    mixto: la geometría pone las partes de una sola línea y el OCR, solo la
    fracción. Suele bastar para dejar la fórmula completa.
    """
    regiones = pdfmath.collect_fraction_regions(page)
    resultado: list = []
    cuantas = 0

    for racimo in pdfmath.cluster_equations(page, equations, regiones):
        if not racimo.has_fraction:
            resultado.append(_collapse(racimo))
            continue

        # 1) La ecuación entera de una vez.
        completo = _recognize(page, racimo.rect, (), ocr, cache)
        if completo:
            resultado.append(_replace(racimo.members[0], latex=completo, rect=racimo.rect))
            cuantas += 1
            log(f"  ecuación apilada reconocida: {completo[:70]}")
            continue

        # 2) Mixto: cada fracción por OCR, el resto por geometría.
        piezas: list[tuple[float, str]] = []
        fracciones = [r for r in regiones if pdfmath._intersecta(r.rect, racimo.rect)]
        reconocidas = 0
        for region in fracciones:
            latex = _recognize(page, region.rect, region.exclude, ocr, cache)
            if latex:
                piezas.append((region.rect[0], latex))
                reconocidas += 1

        if not reconocidas:
            resultado.append(_collapse(racimo))
            continue

        for miembro in racimo.members:
            # Lo que ya está dentro de una fracción no se repite.
            if any(pdfmath._dentro(miembro.rect, r.rect, 3) for r in fracciones):
                continue
            piezas.append((miembro.rect[0], miembro.latex))

        piezas.sort(key=lambda p: p[0])
        mezcla = " ".join(texto for _, texto in piezas if texto).strip()
        if mezcla:
            resultado.append(_replace(racimo.members[0], latex=mezcla, rect=racimo.rect))
            cuantas += reconocidas
            log(f"  ecuación apilada (mixta): {mezcla[:70]}")
        else:
            resultado.append(_collapse(racimo))

    resultado.sort(key=lambda e: e.y)
    return resultado, cuantas


def _collapse(racimo) -> "pdfmath.DisplayEquation":
    """
    Deja el racimo en una sola ecuación.

    El extractor parte una ecuación centrada en varios renglones, pero en el
    documento era una sola y ocupa una sola imagen. Si no se vuelven a juntar,
    salen tres ecuaciones donde había una y ya no cuadran con las imágenes que
    hay que sustituir.
    """
    miembros = racimo.members
    if len(miembros) == 1:
        return miembros[0]

    # Los que están a la misma altura formaban una línea; los demás, líneas
    # distintas de un sistema o de una demostración.
    filas: list[list] = []
    for miembro in sorted(miembros, key=lambda m: (m.rect[1], m.rect[0])):
        if filas and abs(miembro.rect[1] - filas[-1][0].rect[1]) < 6:
            filas[-1].append(miembro)
        else:
            filas.append([miembro])

    lineas = [
        " ".join(m.latex for m in sorted(fila, key=lambda m: m.rect[0]))
        for fila in filas
    ]
    if len(lineas) == 1:
        latex = lineas[0]
    else:
        latex = "\\begin{aligned} " + " \\\\ ".join(lineas) + " \\end{aligned}"

    return _replace(miembros[0], latex=latex, rect=racimo.rect)


def _recognize(page, rect, exclude, ocr, cache: dict) -> Optional[str]:
    """OCR de una región, guardando el resultado por si se vuelve a pedir."""
    clave = (id(page), tuple(round(v, 1) for v in rect))
    if clave not in cache:
        cache[clave] = mathocr.recognize_region(ocr, page, rect, exclude=exclude)
    return cache[clave]


# ────────────────────────────────────────────────────────────
# Ecuaciones destacadas
# ────────────────────────────────────────────────────────────

def _replace_text_with_math(page, text: str, equations: list) -> tuple[str, int, list]:
    """
    Cambia por su reconstrucción las ecuaciones que el extractor devolvió como
    texto en vez de como imagen.

    Cuál de las dos cosas hace depende de detalles del entorno ajenos a
    Latexinter, así que se contemplan las dos: aquí se resuelven las que están
    como texto y se devuelven aparte las que habrá que tratar como imagen.
    """
    sustituidas = 0
    pendientes: list = []

    for ecuacion in equations:
        plano = pdfmath.region_plain_text(page, ecuacion.rect)
        if len(plano) < 4:
            pendientes.append(ecuacion)
            continue
        try:
            nuevo, cuantas = re.subn(
                pdfmath.pattern_for_plain(plano),
                lambda _m, r=ecuacion.latex: "\n\n$$\n" + r + "\n$$\n\n",
                text,
                count=1,
            )
        except re.error:
            pendientes.append(ecuacion)
            continue

        if cuantas:
            text = nuevo
            sustituidas += cuantas
        else:
            pendientes.append(ecuacion)

    return text, sustituidas, pendientes


def _replace_images_with_math(text: str, equations: list[str]) -> tuple[str, int]:
    """
    Sustituye las imágenes de una página por las ecuaciones reconstruidas.
    Solo se hace si hay tantas imágenes como ecuaciones: si no coinciden, es
    que alguna imagen era una figura de verdad y no conviene tocar nada.
    """
    images = _IMAGE_LINK.findall(text)
    if not images or len(images) != len(equations):
        return text, 0

    pending = list(equations)

    def swap(_match: re.Match) -> str:
        return "\n$$\n" + pending.pop(0) + "\n$$\n"

    return _IMAGE_LINK.sub(swap, text), len(equations)


def _equation_appendix(found: list[tuple[int, str]]) -> str:
    """Bloque de comentarios con las ecuaciones que quedaron como imagen."""
    lines = [
        "",
        "% ══════════════════════════════════════════════════════════",
        "%  Ecuaciones destacadas detectadas en el PDF",
        "%",
        "%  Se insertaron arriba como imagen para conservar el aspecto",
        "%  original. Esta es la reconstrucción en LaTeX: revísala y, si te",
        "%  convence, sustituye la imagen correspondiente por la ecuación.",
        "% ══════════════════════════════════════════════════════════",
    ]
    for page, latex in found:
        lines.append(f"%  [página {page}]")
        lines.append("%  \\begin{equation}")
        lines.append("%      " + latex)
        lines.append("%  \\end{equation}")
        lines.append("%")
    lines.append("")
    return "\n".join(lines)


def _insert_appendix(tex_path: Path, appendix: str) -> None:
    content = tex_path.read_text(encoding="utf-8")
    anchor = content.rfind("\\end{document}")
    if anchor == -1:
        content += appendix
    else:
        content = content[:anchor] + appendix + content[anchor:]
    tex_path.write_text(content, encoding="utf-8")


# ────────────────────────────────────────────────────────────
# Conversión
# ────────────────────────────────────────────────────────────

def pdf_to_latex(
    pdf_path: Path | str,
    output: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    *,
    pages: Optional[str] = None,
    twocolumn: bool = False,
    extract_images: bool = True,
    math_reconstruction: bool = True,
    display_equations: Optional[str] = None,
    math_ocr: bool = False,
    ocr_backend: Optional[str] = None,
    keep_markdown: bool = False,
    logger: Optional[Logger] = None,
) -> ConversionResult:
    log = as_logger(logger)
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise ConversionError(f"No existe el archivo: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ConversionError("El archivo de entrada debe ser un .pdf")

    require_tool("pandoc")
    require_module("pymupdf4llm")
    require_module("fitz", "PyMuPDF")

    import fitz
    import pymupdf4llm

    target = resolve_output(pdf_path, ".tex", output, output_dir, overwrite=False)
    log(f"Entrada : {pdf_path.name} ({human_size(pdf_path)})")
    log(f"Salida  : {target}")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise ConversionError(f"No se pudo abrir el PDF: {exc}") from exc

    extras: list[Path] = []
    warnings: list[str] = []
    equations_found: list[tuple[int, str]] = []
    math_fixes = 0
    replaced_equations = 0
    ocr_count = 0
    ocr_cache: dict = {}      # una fórmula puede pedirse dos veces por página

    # El OCR solo entra en juego si se pidió y hay un modelo instalado.
    ocr = None
    ocr_pedido = math_ocr
    if math_ocr:
        ocr = mathocr.get_engine(ocr_backend, logger=log)
        if not ocr.available:
            warnings.append(
                "Se pidió reconocer las fórmulas con OCR, pero no hay ningún "
                "modelo instalado; se ha usado solo la reconstrucción por "
                "maquetación.\n" + mathocr.install_hint()
            )
            ocr = None
            ocr_pedido = False
        else:
            log(f"OCR de fórmulas: {ocr.name}")

    if display_equations is DISPLAY_AUTO:
        # Con OCR la lectura es de fiar y lo que se quiere es LaTeX editable;
        # sin él, más vale conservar la imagen, que al menos se ve igual que el
        # original, y dejar la reconstrucción comentada por si sirve.
        display_equations = DISPLAY_REPLACE if ocr_pedido else DISPLAY_COMMENT
        log(f"Ecuaciones destacadas: {display_equations}")

    with doc:
        if doc.needs_pass:
            raise ConversionError("El PDF está protegido con contraseña.")

        page_list = parse_pages(pages, doc.page_count)
        selected = page_list if page_list is not None else list(range(doc.page_count))
        log(f"Páginas : {len(selected)} de {doc.page_count}")

        kwargs = {
            "show_progress": False,
            "page_chunks": True,
            "margins": 0,
            "dpi": 200,
        }
        if page_list is not None:
            kwargs["pages"] = page_list

        images_dir = target.parent / f"{target.stem}_imagenes"
        if extract_images:
            images_dir.mkdir(parents=True, exist_ok=True)
            kwargs.update(
                write_images=True,
                image_path=str(images_dir),
                image_format="png",
            )

        log("Extrayendo texto y maquetación…")
        try:
            chunks = pymupdf4llm.to_markdown(doc, **kwargs)
        except Exception as exc:
            raise ConversionError(f"Falló la extracción del PDF: {exc}") from exc

        if not isinstance(chunks, list):                 # por si cambia la API
            chunks = [{"text": str(chunks)}]

        parts: list[str] = []
        for index, chunk in enumerate(chunks):
            text = chunk["text"] if isinstance(chunk, dict) else str(chunk)
            # Los trozos llegan en el mismo orden que las páginas pedidas.
            page_index = selected[index] if index < len(selected) else None

            # Antes que nada el logotipo: "L[A]TEX" es una A en superíndice y
            # si no se arregla aquí acaba convertido en la fórmula $L^{A}$.
            # Ese mismo superíndice puede desordenar el título que lo lleva,
            # así que primero se recupera el orden de las palabras.
            if page_index is not None:
                text = fix_heading_order(text, raw_page_lines(doc[page_index]))
            text = fix_latex_logo(text)

            if page_index is not None and math_reconstruction:
                page = doc[page_index]

                # Las fracciones primero: su texto plano ("b2−4ac") es el que
                # luego trocearía la reconstrucción de superíndices.
                if ocr is not None:
                    text, reconocidas = _ocr_fractions(page, text, ocr, log, ocr_cache)
                    ocr_count += reconocidas

                fixes = pdfmath.collect_math_fixes(page)
                text, applied = pdfmath.apply_fixes_to_text(text, fixes)
                math_fixes += applied

                if display_equations != DISPLAY_IMAGE:
                    equations = pdfmath.collect_display_equations(page)
                    if equations and ocr is not None:
                        equations, mejoradas = _ocr_display(
                            page, equations, ocr, log, ocr_cache
                        )
                        ocr_count += mejoradas
                    elif equations:
                        # Sin OCR también hay que juntar los trozos: en el
                        # documento era una sola ecuación y una sola imagen.
                        equations = [
                            _collapse(racimo)
                            for racimo in pdfmath.cluster_equations(page, equations)
                        ]
                    if equations:
                        # Primero las que el extractor dejó como texto suelto:
                        # ahí no hay imagen que valga y quedarían como restos
                        # ilegibles en medio del documento.
                        text, sustituidas, pendientes = _replace_text_with_math(
                            page, text, equations
                        )
                        replaced_equations += sustituidas

                        latex_list = [e.latex for e in pendientes]
                        swapped = 0
                        if latex_list and display_equations == DISPLAY_REPLACE:
                            text, swapped = _replace_images_with_math(text, latex_list)
                            replaced_equations += swapped
                        if latex_list and not swapped:
                            equations_found.extend(
                                (page_index + 1, latex) for latex in latex_list
                            )
            parts.append(text)

        parts = strip_running_heads(parts)
        md = "\n\n".join(parts)

    if math_reconstruction:
        log(f"Índices reconstruidos: {math_fixes}")
        total_eqs = replaced_equations + len(equations_found)
        if total_eqs:
            log(f"Ecuaciones destacadas reconstruidas: {total_eqs}")
        if ocr_count:
            log(f"Fórmulas reconocidas con OCR: {ocr_count}")

    # El índice se detecta por sus puntos suspensivos, así que hay que
    # buscarlo antes de que la limpieza los borre.
    md = replace_toc_table(md)
    md = clean_markdown(md)
    md = normalize_headings(md)
    md, image_count = _relocate_images(md, target.parent)

    if extract_images:
        log(f"Imágenes extraídas: {image_count}")
        if images_dir.exists():
            if image_count == 0:
                # Todas las imágenes eran ecuaciones y se han sustituido por su
                # LaTeX: los archivos ya no los referencia nadie.
                shutil.rmtree(images_dir, ignore_errors=True)
            elif any(images_dir.iterdir()):
                extras.append(images_dir)
            else:
                images_dir.rmdir()

    log("Traduciendo símbolos a LaTeX matemático…")
    md = mathfix.latexify_markdown(md)

    # El .md tiene que estar junto al .tex para que las rutas relativas de las
    # imágenes sigan siendo válidas.
    if keep_markdown:
        md_path = target.with_suffix(".md")
    else:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".md", dir=str(target.parent), delete=False, encoding="utf-8"
        )
        handle.close()
        md_path = Path(handle.name)
    md_path.write_text(md, encoding="utf-8")

    try:
        cmd = [
            "pandoc", str(md_path),
            "-o", str(target),
            f"--from={PANDOC_FROM}",
            "--to=latex",
            "--standalone",
            "--wrap=none",
            "-V", "documentclass=article",
            "-V", "geometry:margin=2.5cm",
            "-V", "fontenc=T1",
            "-V", "lang=es",
        ]
        if twocolumn:
            cmd.extend(["-V", "classoption=twocolumn"])

        log("Convirtiendo a LaTeX con pandoc…")
        result = run_command(cmd, cwd=target.parent, logger=None)
        if result.returncode != 0 or not target.exists():
            raise ConversionError(
                "pandoc no pudo generar el LaTeX:\n" + tail(result.stderr)
            )
        if result.stderr.strip():
            warnings.append(tail(result.stderr, 8))
    finally:
        if keep_markdown:
            extras.append(md_path)
        elif md_path.exists():
            md_path.unlink()

    stats = texpost.postprocess(
        target,
        source=pdf_path.name,
        tool="pymupdf4llm + pandoc",
        twocolumn=twocolumn,
    )

    if equations_found:
        _insert_appendix(target, _equation_appendix(equations_found))

    stats.update({
        "paginas": len(selected),
        "imagenes": image_count,
        "indices_reconstruidos": math_fixes,
        "ecuaciones_destacadas": replaced_equations + len(equations_found),
        "formulas_ocr": ocr_count,
    })

    if stats["unicode_sin_traducir"]:
        warnings.append(
            "Quedaron caracteres poco comunes sin traducir: "
            + " ".join(stats["unicode_sin_traducir"])
        )
    if equations_found:
        warnings.append(
            f"{len(equations_found)} ecuaciones destacadas quedaron como imagen; "
            "su reconstrucción en LaTeX está comentada al final del .tex."
        )

    log(f"Listo: {stats['formulas']} fórmulas, {human_size(target)}")
    return ConversionResult(output=target, extras=extras, warnings=warnings, stats=stats)
