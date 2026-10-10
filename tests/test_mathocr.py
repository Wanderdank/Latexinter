"""OCR de fórmulas: lo que no necesita el modelo descargado."""

from converters import mathocr, pdfmath


def test_junta_la_salida_de_pix2text_mfr():
    crudo = r"\operatorname* { l i m } _ { T \rightarrow \infty } \frac { 1 } { T } \sum _ { t = 1 } ^ { T }"
    assert mathocr.join_spaced_latex(crudo) == r"\lim_{T\rightarrow\infty}\frac{1}{T}\sum_{t=1}^{T}"


def test_palabras_y_ruido_de_pix2text_mfr():
    crudo = r"\i h _ { t } = 1 \mathrm { ~ a n d ~ } \hat { X } _ { t } = 0"
    assert mathocr.join_spaced_latex(crudo) == r"h_{t}=1\text{ and }\hat{X}_{t}=0"


def test_un_espacio_solo_tras_un_comando():
    assert mathocr.join_spaced_latex(r"\alpha x \beta _ { i }") == r"\alpha x\beta_{i}"


def test_acuerdo_entre_glifos():
    geometria = r"\lim_{T\rightarrow\infty}\;\frac{1}{T}\;\sum_{t=1}^{T}\;\mathbb{E}[\Delta(X_{t})]"
    ocr = r"\lim_{T\to\infty}\frac{1}{T}\sum_{t=1}^{T}\mathbb{E}\left[\Delta(X_{t})\right]"
    assert pdfmath.agreement(ocr, geometria) == 1.0
    # Un glifo inventado baja el acuerdo.
    assert pdfmath.agreement(r"9x+2y=7", r"3x+2y=7") < 1.0
