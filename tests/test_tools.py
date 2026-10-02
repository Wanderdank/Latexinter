"""Recuento de palabras propio (sin texcount ni Perl)."""

from converters import tools


def test_recuento_solo_cuenta_la_prosa():
    tex = (
        "\\documentclass{article}\n"
        "\\usepackage{amsmath}\n"
        "\\begin{document}\n"
        "\\section{Introducción}\n"
        "Hola mundo % esto es un comentario\n"
        "$x^2 + y^2$ tres palabras aquí\n"
        "\\begin{equation}\n"
        "E = mc^2\n"
        "\\end{equation}\n"
        "\\end{document}\n"
    )
    # "Introducción", "Hola", "mundo", "tres", "palabras", "aquí"
    assert tools.rough_word_count(tex) == 6
