"""OCR de fórmulas: lo que no necesita el modelo descargado."""

import pytest

from converters import mathocr, pdfmath


def test_junta_la_salida_de_pix2text_mfr():
    crudo = r"\operatorname* { l i m } _ { T \rightarrow \infty } \frac { 1 } { T } \sum _ { t = 1 } ^ { T }"
    assert mathocr.join_spaced_latex(crudo) == r"\lim_{T\rightarrow\infty}\frac{1}{T}\sum_{t=1}^{T}"


def test_palabras_y_ruido_de_pix2text_mfr():
    crudo = r"\i h _ { t } = 1 \mathrm { ~ a n d ~ } \hat { X } _ { t } = 0"
    assert mathocr.join_spaced_latex(crudo) == r"h_{t}=1\text{ and }\hat{X}_{t}=0"


def test_un_espacio_solo_tras_un_comando():
    assert mathocr.join_spaced_latex(r"\alpha x \beta _ { i }") == r"\alpha x\beta_{i}"


def test_operatorname_seguido_de_letra_conserva_el_espacio():
    assert mathocr.join_spaced_latex(r"\operatorname { l o g } A") == r"\log A"
    assert mathocr.join_spaced_latex(r"\operatorname { l o g } ( A )") == r"\log(A)"


@pytest.mark.parametrize("latex", [
    r"b_{j}:=\left|x\right|",
    r"\big|x\big|",
    r"\left\|x\right\|",
    r"|x|",
    r"\left. f\right|",
])
def test_la_limpieza_no_se_come_los_delimitadores(latex):
    assert mathocr.clean_latex(latex) == latex


@pytest.mark.parametrize("sucio, limpio", [
    (r"x+y,\;", "x+y"),
    (r"x+y.", "x+y"),
    (r"\quad x+y|", "x+y"),
    (r"\left. x+y", "x+y"),
    (r"x+y\right.", "x+y"),
    (r"x+y,\hspace{2cm}", "x+y"),
    (r"x+y.\tag*{(14)}", "x+y"),
    (r"\tag*{(2.3)}x+y", "x+y"),
])
def test_la_limpieza_quita_el_ruido(sucio, limpio):
    assert mathocr.clean_latex(sucio) == limpio


@pytest.mark.parametrize("latex", [
    r"\frac{a}{b}^2",
    r"x^{a}_{b}+y_{c}^{d}",
    r"x'^{2}",
    r"\sum\limits_{i=1}^{n}a_{i}",
    r"\sqrt[3]{x}",
    r"\left\langle\psi|H|\psi\right\rangle",
    r"\left.f\right|_{0}^{1}",
    r"\big|x\big|",
    r"\begin{aligned}a&=b\\c&=d\end{aligned}",
    r"\begin{array}{cc}a&b\\c&d\end{array}",
    r"\begin{cases}a&b\\c&d\end{cases}",
    r"\operatorname*{arg\,max}_{x}f(x)",
    r"\text{ and }\mathbb{R}^{n}",
    r"\log A",
    r"\{a,b\}\,\|x\|",
])
def test_formulas_que_compilan(latex):
    assert mathocr.structure_error(latex) is None


@pytest.mark.parametrize("latex", [
    r"\logA+1",                                                    # comando inexistente
    r"\atopwithdelims{a}=b",                                       # infijo y sin delimitadores
    r"\left\langle\beta|\,,",                                      # \left sin \right
    r"\left\||\psi(t)\right\rangle\right\|^{2}",                   # \right de más
    r"a=\left|x\right",                                            # \right sin delimitador
    r"\big|x\big",                                                 # \big sin delimitador
    r"\begin{aligned}a&=b\\c&=d",                                  # entorno cortado
    r"\begin{aligned}a&=b\end{cases}",                             # cierra otro
    r"\begin{align}a&=b\end{align}",                               # no vale dentro de \[ \]
    r"\left(\begin{matrix}a\right)\end{matrix}",                   # cruzados
    r"a&b",                                                        # & fuera de una tabla
    r"x^{a}^{b}",
    r"x_{a}_{b}",
    r"x^{2}'",
    r"x^",
    r"\frac{a}",
    r"\frac{a}}{b",
    r"\text{a_b}",
    r"\text{\alpha}",
    r"50%",
])
def test_formulas_que_no_compilan(latex):
    assert mathocr.structure_error(latex) is not None


def test_una_lectura_que_no_compila_no_se_usa():
    assert mathocr.looks_usable(r"\frac{a}{b}")
    assert not mathocr.looks_usable(r"\left(\frac{a}{b}")


def test_acuerdo_entre_glifos():
    geometria = r"\lim_{T\rightarrow\infty}\;\frac{1}{T}\;\sum_{t=1}^{T}\;\mathbb{E}[\Delta(X_{t})]"
    ocr = r"\lim_{T\to\infty}\frac{1}{T}\sum_{t=1}^{T}\mathbb{E}\left[\Delta(X_{t})\right]"
    assert pdfmath.agreement(ocr, geometria) == 1.0
    # Un glifo inventado baja el acuerdo.
    assert pdfmath.agreement(r"9x+2y=7", r"3x+2y=7") < 1.0
