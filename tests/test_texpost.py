"""Retoques finales sobre el .tex generado."""

from converters import texpost


def test_declara_los_caracteres_que_no_se_pudieron_traducir(tmp_path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "llave \ufffd y pieza \uf8f1 y \x12control\n\\end{document}\n",
        encoding="utf-8",
    )
    texpost.postprocess(tex, source="doc.pdf", tool="prueba")
    content = tex.read_text(encoding="utf-8")
    assert r"\DeclareUnicodeCharacter{FFFD}{\ensuremath{\square}}" in content
    assert r"\DeclareUnicodeCharacter{F8F1}{}" in content
    assert "\x12" not in content
    assert r"\usepackage{iftex}" in content
    # El carácter se queda en el texto para poder buscarlo.
    assert "llave \ufffd" in content


def test_no_redeclara_las_letras_con_acentos(tmp_path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\nção ß ő\n\\end{document}\n",
        encoding="utf-8",
    )
    texpost.postprocess(tex, source="doc.pdf", tool="prueba")
    assert "DeclareUnicodeCharacter" not in tex.read_text(encoding="utf-8")
