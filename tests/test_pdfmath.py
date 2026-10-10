"""Reconstrucción de fórmulas a partir de la geometría de los glifos."""

from converters import pdfmath


def span(text, x0, y0, x1, y1, base, size=10.0, font="CMMI10"):
    return {"text": text, "bbox": (x0, y0, x1, y1), "origin": (x0, base),
            "size": size, "font": font}


def test_fraccion_apilada():
    items = [
        span("a=", 10, 92, 25, 102, 100, font="CMR10"),
        span("1", 37, 85, 43, 95, 94, font="CMR10"),
        span("n", 37, 98, 43, 108, 106),
    ]
    raya = (30, 96, 50, 97)
    piezas = pdfmath._stack_fractions(items, [raya])
    assert pdfmath._layout(piezas) == r"a=\frac{1}{n}"


def test_limites_de_un_sumatorio():
    items = [
        span("∑", 30, 90, 42, 104, 100, font="CMSY10"),
        span("i=1", 31, 105, 41, 111, 110, size=7.0),
        span("n", 33, 82, 39, 88, 87, size=7.0),
        span("x", 43, 93, 48, 101, 100),
    ]
    piezas = pdfmath._attach_limits(items)
    assert pdfmath._layout(piezas) == r"\sum_{i=1}^{n}x"


def test_subindice_y_superindice_en_la_misma_letra():
    spans = [
        span("p", 10, 92, 16, 102, 100),
        span("X", 16, 88, 21, 95, 94, size=7.0),
        span("1,0", 16, 99, 24, 105, 103, size=7.0, font="CMR7"),
    ]
    assert pdfmath._reconstruct_line(spans) == r"p_{1,0}^{X}"


def test_letras_de_pizarra_y_caligraficas():
    assert pdfmath._span_text(span("E", 0, 0, 5, 10, 8, font="MSBM10")) == r"\mathbb{E}"
    assert pdfmath._span_text(span("S", 0, 0, 5, 10, 8, font="CMSY10")) == r"\mathcal{S}"


def test_sumatorio_de_newtx():
    # La fuente de extensión de newtx lleva el ∑ 0x7D posiciones más arriba.
    assert pdfmath._span_text(span("Õ", 0, 0, 5, 10, 8, font="txexs")) == r"\sum"


def test_fraccion_sin_raya():
    # PDF pasado por Ghostscript: no hay dibujo de la raya, solo el 1 encima
    # del renglón y el 2 debajo, en una columna donde el renglón no pasa.
    items = [
        span("R", 365, 199, 373, 209, 206),
        span("+", 385, 199, 392, 209, 206, font="CMR10"),
        span("1", 396, 192, 401, 202, 199.3, font="CMR10"),
        span("2", 396, 205, 401, 215, 213, font="CMR10"),
        span("g", 402, 199, 407, 209, 206),
    ]
    assert pdfmath._layout(pdfmath._virtual_fractions(items)) == r"R+\frac{1}{2}g"


def test_raiz_con_su_raya():
    items = [
        span("=", 310, 185, 323, 196, 194, font="CMR12"),
        span("√", 325, 180, 337, 198, 181, font="CMSY10"),
        span("π", 337, 185, 343, 196, 194),
    ]
    raya = (337, 184, 344, 184.4)
    piezas = pdfmath._stack_fractions(items, [raya])
    assert pdfmath._layout(piezas) == r"=\sqrt{\pi}"


def test_limites_en_dos_renglones():
    items = [
        span("inf", 30, 92, 45, 102, 100, font="CMR10"),
        span("t∈J", 31, 103, 44, 109, 108, size=7.0),
        span("x∈Ω", 31, 110, 44, 116, 115, size=7.0),
    ]
    assert pdfmath._layout(pdfmath._attach_limits(items)) == r"\inf_{\substack{t\in J \\ x\in \Omega}}"


def test_operador_de_la_fuente_de_extension_no_es_un_indice():
    # La fuente de extensión pone el origen del ∑ arriba del todo y el
    # extractor le da una caja diminuta.
    spans = [
        span("f", 230, 231, 236, 242, 239, size=12.0),
        span("=", 250, 231, 262, 242, 239, size=12.0, font="CMR12"),
        span("X", 263, 229, 278, 235, 229, font="CMEX10"),
        span("x", 279, 231, 285, 242, 239, size=12.0),
    ]
    assert pdfmath._reconstruct_line(spans) == r"f=\sum x"


def test_matriz_con_corchetes_por_piezas():
    # Corchetes grandes compuestos con piezas (codificación Symbol de Adobe).
    items = [
        span("", 78, 500, 84, 510, 500, font="CMEX10"),
        span("", 78, 512, 84, 524, 512, font="CMEX10"),
        span("a", 90, 500, 95, 510, 508),
        span("b", 110, 500, 115, 510, 508),
        span("c", 90, 512, 95, 522, 520),
        span("d", 110, 512, 115, 522, 520),
        span("", 120, 500, 126, 510, 500, font="CMEX10"),
        span("", 120, 512, 126, 524, 512, font="CMEX10"),
    ]
    piezas = pdfmath._matrices(items)
    assert pdfmath._layout(piezas) == r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}"


def test_casos_con_llave():
    items = [
        span("", 60, 498, 66, 508, 498, font="CMEX10"),
        span("", 60, 512, 66, 524, 512, font="CMEX10"),
        span("0,", 70, 500, 78, 510, 508, font="CMR10"),
        span("x>0", 100, 500, 115, 510, 508),
        span("1,", 70, 512, 78, 522, 520, font="CMR10"),
        span("x≤0", 100, 512, 115, 522, 520),
    ]
    piezas = pdfmath._matrices(items)
    assert pdfmath._layout(piezas) == r"\begin{cases} 0, & x>0 \\ 1, & x\leq 0 \end{cases}"
