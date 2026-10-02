"""Limpieza del Markdown que sale del PDF, antes de pasarlo a pandoc."""

import sys

import pytest

import converters  # noqa: F401  (registra el submódulo)
from converters.common import ConversionError

p = sys.modules["converters.pdf_to_latex"]


# ── Selección de páginas ────────────────────────────────────

def test_parse_pages_rangos_y_sueltas():
    assert p.parse_pages("1-3,5", 10) == [0, 1, 2, 4]


def test_parse_pages_sin_seleccion():
    assert p.parse_pages(None, 10) is None


def test_parse_pages_fuera_del_documento():
    with pytest.raises(ConversionError):
        p.parse_pages("8-9", 5)


# ── Títulos ─────────────────────────────────────────────────

def test_normalize_headings_usa_la_numeracion():
    md = "# **4.1. Listas**\n## 2 Métodos\ntexto"
    assert p.normalize_headings(md) == "## Listas\n# Métodos\ntexto"


def test_fix_heading_order_recupera_el_orden_del_pdf():
    # Así lo devolvía pymupdf4llm para "Documento de Ejemplo en LaTeX".
    md = "## **Documento de en L[A] Ejemplo TEX**\npárrafo"
    raw = [["Documento", "de", "Ejemplo", "en", "L", "[A]", "TEX"]]
    assert p.fix_heading_order(md, raw) == "## **Documento de Ejemplo en L[A] TEX**\npárrafo"


def test_fix_heading_order_titulo_en_dos_lineas():
    md = "# Reconstrucción de en fórmulas documentos PDF"
    raw = [["Reconstrucción", "de", "fórmulas", "en"], ["documentos", "PDF"]]
    assert p.fix_heading_order(md, raw) == "# Reconstrucción de fórmulas en documentos PDF"


def test_fix_heading_order_no_toca_lo_que_ya_esta_bien():
    md = "## Referencias y Enlaces"
    assert p.fix_heading_order(md, [["Referencias", "y", "Enlaces"]]) == md


def test_fix_heading_order_no_toca_parrafos():
    md = "mundo Hola"
    assert p.fix_heading_order(md, [["Hola", "mundo"]]) == md


def test_fix_heading_order_sin_coincidencia_exacta():
    md = "## Hola mundo cruel"
    assert p.fix_heading_order(md, [["mundo", "Hola"]]) == md


def test_logo_de_latex_y_tex():
    md = "Escrito en L [A] TEX y en TEX puro, no TEXTO"
    assert p.fix_latex_logo(md) == r"Escrito en \LaTeX{} y en \TeX{} puro, no TEXTO"


def test_titulo_desordenado_acaba_con_el_logo_bien():
    md = "## **Documento de en L[A] Ejemplo TEX**"
    raw = [["Documento", "de", "Ejemplo", "en", "L", "[A]", "TEX"]]
    fixed = p.fix_latex_logo(p.fix_heading_order(md, raw))
    assert fixed == r"## **Documento de Ejemplo en \LaTeX{}**"


# ── Restos del PDF ──────────────────────────────────────────

def test_indice_con_puntos_se_cambia_por_tableofcontents():
    md = "## **Índice**\n\n|**1.**|**Intro**|2|\n|---|---|---|\n|2.|Más|3|\n\n# Intro\n"
    out = p.replace_toc_table(md)
    assert r"\tableofcontents" in out
    assert "|" not in out
    assert "# Intro" in out


def test_encabezados_repetidos_en_cada_pagina():
    pages = [f"Revista X 2024\n{letra}" for letra in "ABCD"]
    assert p.strip_running_heads(pages) == ["A", "B", "C", "D"]
