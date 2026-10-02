"""
texpost.py - Retoques finales sobre un .tex recién generado.

pandoc produce LaTeX correcto pero pelado: sin los paquetes que hacen falta
para imágenes, tablas o matemáticas, y dejando caracteres Unicode que pdflatex
no sabe imprimir. Aquí se arregla eso, de forma que el .tex compile a la
primera y siga siendo cómodo de editar a mano.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import mathfix

# Paquetes que casi cualquier documento convertido acaba necesitando.
DEFAULT_PACKAGES: list[tuple[str, str]] = [
    ("amsmath", "\\usepackage{amsmath}"),
    ("amssymb", "\\usepackage{amssymb}"),
    ("graphicx", "\\usepackage{graphicx}"),
    ("booktabs", "\\usepackage{booktabs}"),
    ("longtable", "\\usepackage{longtable}"),
    ("array", "\\usepackage{array}"),
    ("float", "\\usepackage{float}"),
    ("textcomp", "\\usepackage{textcomp}"),
    ("enumitem", "\\usepackage{enumitem}"),
    ("xcolor", "\\usepackage{xcolor}"),
    ("hyperref", "\\usepackage{hyperref}"),
]


def _has_package(content: str, name: str) -> bool:
    pattern = re.compile(
        r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\b" + re.escape(name) + r"\b[^}]*\}"
    )
    return bool(pattern.search(content))


def ensure_packages(content: str, extra: list[str] | None = None) -> str:
    """Añade los \\usepackage que falten justo antes de \\begin{document}."""
    missing = [line for name, line in DEFAULT_PACKAGES if not _has_package(content, name)]
    for line in extra or []:
        name_match = re.search(r"\{([^}]+)\}", line)
        if name_match and not _has_package(content, name_match.group(1)):
            missing.append(line)
    if not missing:
        return content

    anchor = content.find("\\begin{document}")
    if anchor == -1:
        return content

    block = (
        "\n% ── Paquetes añadidos por Latexinter ─────────────────────\n"
        + "\n".join(missing)
        + "\n\n"
    )
    return content[:anchor] + block + content[anchor:]


def strip_pandoc_noise(content: str) -> str:
    """Quita los apaños de pandoc que estorban al editar el documento a mano."""
    content = content.replace("\\tightlist\n", "")
    content = re.sub(
        r"\\providecommand\{\\tightlist\}\{%?\s*\n?"
        r"\s*\\setlength\{\\itemsep\}\{0pt\}\\setlength\{\\parskip\}\{0pt\}\}\s*\n?",
        "",
        content,
    )
    # Líneas en blanco de más
    content = re.sub(r"\n{4,}", "\n\n\n", content)
    return content


def tables_for_twocolumn(content: str) -> str:
    """
    longtable no funciona dentro de una columna: se cambia por un table*
    que ocupa todo el ancho de la página.
    """
    content = content.replace(
        "\\begin{longtable}", "\\begin{table*}[htbp]\n\\centering\n\\begin{tabular}"
    )
    content = content.replace("\\end{longtable}", "\\end{tabular}\n\\end{table*}")
    for command in ("\\endhead", "\\endfirsthead", "\\endfoot", "\\endlastfoot"):
        content = content.replace(command + "\n", "")
    return content


def add_header(content: str, source: str, tool: str) -> str:
    if content.startswith("% ═"):
        return content
    header = (
        "% ══════════════════════════════════════════════════════════\n"
        f"%  Documento generado por Latexinter desde: {source}\n"
        f"%  Motor: {tool}\n"
        "%  Revisa el resultado: la conversión automática nunca es perfecta.\n"
        "% ══════════════════════════════════════════════════════════\n"
    )
    return header + content


def postprocess(
    tex_path: Path,
    *,
    source: str,
    tool: str,
    twocolumn: bool = False,
    extra_packages: list[str] | None = None,
) -> dict:
    """
    Aplica todos los retoques al archivo y devuelve estadísticas
    (nº de fórmulas, caracteres Unicode que no se pudieron traducir).
    """
    tex_path = Path(tex_path)
    content = tex_path.read_text(encoding="utf-8")

    content = mathfix.latexify_tex(content)
    content = strip_pandoc_noise(content)
    if twocolumn:
        content = tables_for_twocolumn(content)

    # Se mide aquí, antes de añadir los bloques de comentarios de Latexinter:
    # sus caracteres de adorno no le importan a pdflatex.
    leftovers = mathfix.remaining_unicode(content)

    content = ensure_packages(content, extra_packages)
    content = add_header(content, source, tool)
    tex_path.write_text(content, encoding="utf-8")

    return {
        "formulas": mathfix.count_math(content),
        "caracteres": len(content),
        "unicode_sin_traducir": sorted(leftovers)[:20],
    }
