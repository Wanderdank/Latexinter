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


def test_indice_de_un_indice():
    # ∫_{ℝⁿ}: la n está por debajo del renglón, pero encima de la ℝ.
    spans = [
        span("Z", 308.5, 462.3, 314.0, 472.3, 463.0, font="CMEX10"),
        span("R", 314.0, 478.6, 319.1, 485.6, 485.6, size=7.0, font="MSBM7"),
        span("n", 319.1, 479.7, 323.5, 484.7, 483.6, size=5.0, font="CMMI5"),
        span("f", 324.5, 468.7, 331.0, 478.7, 476.5),
        span("(", 332.1, 468.7, 336.0, 478.7, 476.5, font="CMR10"),
        span("x", 336.0, 468.7, 341.6, 478.7, 476.5),
        span(")", 341.6, 468.7, 345.5, 478.7, 476.5, font="CMR10"),
    ]
    assert pdfmath._reconstruct_line(spans) == r"\int_{\mathbb{R}^{n}}f(x)"
    # Y al revés: e^{x_i}, con la i por encima del renglón pero bajo la x.
    spans = [
        span("e", 10, 92, 16, 102, 100),
        span("x", 16, 88, 21, 95, 96, size=7.0),
        span("i", 21, 91, 24, 97, 97.5, size=5.0, font="CMMI5"),
    ]
    assert pdfmath._reconstruct_line(spans) == r"e^{x_{i}}"


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


def test_fraccion_sin_raya_con_indices_que_asoman():
    # E²/(c⁴M²_Pl): los índices de la M quedan a la derecha de la columna.
    items = [
        span("α", 439.9, 129.9, 448.4, 139.9, 137.4),
        span("E", 457.3, 123.2, 464.7, 133.2, 130.7),
        span("2", 465.2, 121.8, 469.2, 128.8, 127.1, size=7.0, font="CMR7"),
        span("c", 449.6, 136.8, 453.9, 146.7, 144.2),
        span("4", 454.0, 136.1, 457.9, 143.1, 141.4, size=7.0, font="CMR7"),
        span("M", 458.4, 136.8, 468.1, 146.7, 144.2),
        span("2", 469.2, 135.6, 473.2, 142.6, 140.9, size=7.0, font="CMR7"),
        span("Pl", 468.1, 142.0, 476.8, 149.0, 147.2, size=7.0, font="CMMI7"),
        span(".", 487.4, 129.9, 490.2, 139.9, 137.4),
    ]
    latex = pdfmath._layout(pdfmath._virtual_fractions(items))
    assert latex.startswith(r"\alpha\frac{E^{2}}{c^{4}M_{\mathrm{Pl}}^{2}}")


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


def test_limites_de_sumatorios_en_renglones_seguidos():
    # En un aligned con un ∑ en cada renglón, el límite de abajo de uno casi
    # toca el de arriba del siguiente, y los dos ∑ están en la misma columna.
    items = [
        span("v", 77.4, 324.5, 85.0, 334.4, 332.3),
        span("N", 93.7, 314.4, 99.9, 321.4, 319.8, size=7.0, font="CMMI7"),
        span("X", 88.8, 322.2, 103.2, 332.2, 322.8, font="CMEX10"),
        span("m=1", 87.0, 338.5, 104.1, 345.4, 343.9, size=7.0, font="CMMI7"),
        span("ν", 77.4, 359.3, 85.1, 369.3, 367.1),
        span("N−2", 87.4, 349.2, 104.6, 356.2, 354.6, size=7.0, font="CMMI7"),
        span("X", 88.8, 357.0, 103.2, 367.0, 357.6, font="CMEX10"),
        span("m=1", 87.4, 373.3, 104.6, 380.3, 378.7, size=7.0, font="CMMI7"),
    ]
    piezas = pdfmath._attach_limits(pdfmath._normalize_extension(items))
    assert sorted(p["latex"] for p in piezas if "latex" in p) == [
        r"\sum_{m=1}^{N-2}", r"\sum_{m=1}^{N}",
    ]


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


class PaginaFalsa:
    """Lo justo de una página de PyMuPDF: el texto en dict/rawdict y sin dibujos."""

    def __init__(self, renglones, flags=None):
        self.renglones = renglones
        self.flags = flags or {}

        class Rect:
            width = 612.0
        self.rect = Rect()

    def get_drawings(self):
        return []

    def get_text(self, modo):
        lineas = []
        for renglon in self.renglones:
            spans = []
            for s in renglon:
                s = dict(s, flags=self.flags.get(id(s), 4))
                if modo == "rawdict":
                    ancho = (s["bbox"][2] - s["bbox"][0]) / max(1, len(s["text"]))
                    s["chars"] = [
                        {"c": c, "origin": (s["bbox"][0] + i * ancho, s["origin"][1]),
                         "bbox": (s["bbox"][0] + i * ancho, s["bbox"][1],
                                  s["bbox"][0] + (i + 1) * ancho, s["bbox"][3])}
                        for i, c in enumerate(s["text"])
                    ]
                    del s["text"]
                spans.append(s)
            lineas.append({"spans": spans})
        return {"blocks": [{"type": 0, "lines": lineas}]}


def _renglon_con_sumatorio():
    """«the global magnetization, [H, ∑_r S_r^z] = 0, and we will», de un paper real."""
    resto = [
        span("r", 210.0, 433.4, 213.7, 440.4, 438.6, size=7.0, font="CMMI7"),
        span("]", 215.2, 428.7, 218.0, 438.6, 436.1, font="CMR10"),
        span("=", 222.6, 428.7, 230.3, 438.6, 436.1, font="CMR10"),
        span(" 0,", 230.3, 428.7, 242.7, 438.6, 436.1, font="CMR10"),
        span(" and", 242.7, 428.7, 263.4, 438.6, 436.1, font="CMR10"),
        span(" we", 263.4, 428.7, 279.2, 438.6, 436.1, font="CMR10"),
        span(" will", 279.2, 428.7, 299.1, 438.6, 436.1, font="CMR10"),
    ]
    renglones = [
        [
            span("the global magnetization, ", 54.0, 428.7, 171.6, 438.6, 436.1, font="CMR10"),
            span("[", 171.6, 428.7, 174.4, 438.6, 436.1, font="CMR10"),
            span("H,", 174.4, 428.7, 185.7, 438.6, 436.1),
            span("P", 187.3, 428.1, 197.8, 438.0, 428.7, font="CMEX10"),
        ],
        [
            span("r", 197.8, 433.9, 201.5, 440.9, 439.1, size=7.0, font="CMMI7"),
            span("S", 203.9, 428.7, 210.0, 438.6, 436.1),
            span("z", 210.6, 427.3, 214.4, 434.3, 432.5, size=7.0, font="CMMI7"),
        ],
        resto,
    ]
    # PyMuPDF marca como superíndice todo lo que va detrás del ∑.
    flags = {id(s): 5 for s in resto[1:]}
    flags[id(renglones[0][3])] = 5
    return PaginaFalsa(renglones, flags)


MARKDOWN_SUMATORIO = (
    "the global magnetization, [ _H,_[�] _r[S] r[z]_[]][=][0,][and][we][will] particularly"
)


def test_quita_los_superindices_de_mentira():
    texto, cuantos = pdfmath.unmark_false_superscripts(_renglon_con_sumatorio(), MARKDOWN_SUMATORIO)
    assert cuantos == 1
    # La z, que sí es un índice, conserva sus corchetes.
    assert texto == "the global magnetization, [ _H,_[�] _r[S] r[z]_] = 0, and we will particularly"


def test_sumatorio_dentro_de_un_parrafo():
    pagina = _renglon_con_sumatorio()
    texto, _ = pdfmath.unmark_false_superscripts(pagina, MARKDOWN_SUMATORIO)
    fixes = pdfmath.collect_inline_operators(pagina)
    texto, cuantas = pdfmath.apply_inline_operators(texto, fixes)
    assert cuantas == 1
    assert texto == r"the global magnetization, $[H,\sum_{r}\;S_{r}^{z}]=0$, and we will particularly"


def test_sin_corchetes_no_sale_un_enlace():
    # «Z[β](ω)» sería un enlace de Markdown: pandoc lo convierte en \href.
    renglon = [
        span("where ", 10, 92, 40, 102, 100, font="CMR10"),
        span("Z", 40, 92, 47, 102, 100),
        span("β", 47, 88, 51, 95, 96, size=7.0, font="CMMI7"),
        span("(", 52, 92, 55, 102, 100, font="CMR10"),
        span("ω", 55, 92, 61, 102, 100),
        span(")", 61, 92, 64, 102, 100, font="CMR10"),
    ]
    flags = {id(s): 5 for s in renglon[2:]}
    texto, _ = pdfmath.unmark_false_superscripts(
        PaginaFalsa([renglon], flags), "where 𝑍[𝛽][(][ω][)] is"
    )
    assert texto == "where 𝑍[𝛽] (ω) is"
