"""Unicode → LaTeX matemático, agrupando la fórmula entera."""

from converters import mathfix


def test_agrupa_el_tramo_matematico():
    md = "si α ≤ β entonces x ∈ ℝ"
    assert mathfix.latexify_markdown(md) == (
        r"si $\alpha \leq \beta$ entonces $x \in \mathbb{R}$"
    )


def test_la_tipografia_no_activa_el_modo_matematico():
    assert mathfix.latexify_markdown("El precio subió — mucho") == "El precio subió --- mucho"


def test_latexify_tex_respeta_los_comentarios():
    tex = "La temperatura es 30 °C y α ≤ β.\n% α comentario\n"
    assert mathfix.latexify_tex(tex) == (
        "La temperatura es 30 \\textdegree{}C y $\\alpha \\leq \\beta$.\n% α comentario\n"
    )


def test_count_math():
    assert mathfix.count_math(r"$a$ y $$b$$ y \(c\)") == 3


def test_une_los_indices_partidos_glifo_a_glifo():
    assert mathfix.merge_double_scripts(r"e^{(}^{x}^{-}^{c}^{)}") == r"e^{(x-c)}"
    assert mathfix.merge_double_scripts(r"a^{\beta}^{x}") == r"a^{\beta x}"
    assert mathfix.merge_double_scripts(r"x_{i}^{2}") == r"x_{i}^{2}"


def test_escapa_las_llaves_sin_pareja():
    assert mathfix.balance_braces(r"\(x \leq 1}\)") == r"\(x \leq 1\}\)"
    assert mathfix.balance_braces(r"\left\{ x^{2} \right\}") == r"\left\{ x^{2} \right\}"


def test_recupera_letras_matematicas_recortadas():
    # 𝑥 y 𝛽 extraídos como sílabas coreanas (U+D465, U+D6FD)
    assert mathfix.repair_truncated_alphanumerics("sea 푥 y 훽") == "sea \U0001D465 y \U0001D6FD"
    # Un texto que de verdad está en coreano no se toca.
    assert mathfix.repair_truncated_alphanumerics("한국어 푥") == "한국어 푥"


def test_acentos_combinados_dentro_de_una_formula():
    assert mathfix.latexify_tex("\\(x\u20d7 + \\alpha\u0302\\)") == r"\(\vec{x} + \hat{\alpha}\)"


def test_griegas_y_simbolos_poco_comunes():
    assert mathfix.latexify_tex("\U0001D703 y ∆ y ℓ") == r"$\theta$ y $\Delta$ y $\ell$"


def test_comando_matematico_suelto_en_el_texto():
    assert mathfix.latexify_tex(r"Sea \sigma y \(\alpha\)") == r"Sea $\sigma$ y \(\alpha\)"
    # Un salto de línea seguido de una palabra no es un comando.
    assert mathfix.latexify_tex("a \\\\" + "sigma") == "a \\\\" + "sigma"


def test_indices_alternados():
    assert mathfix.merge_double_scripts(r"\gamma_{1}^{s}_{,b}") == r"\gamma_{1,b}^{s}"


def test_prima_detras_de_un_superindice():
    assert mathfix.merge_double_scripts("S_{r}^{z}'(0)") == r"S_{r}^{z\prime}(0)"
    assert mathfix.merge_double_scripts("x_{i}'") == "x_{i}'"


def test_raiz_de_una_fraccion():
    assert mathfix._tidy_math(r"\surd\frac{1}{N}") == r"\sqrt{\frac{1}{N}}"


def test_prima_entre_indices_y_acento_en_un_indice():
    assert mathfix.merge_double_scripts("x_{a}'_{b}") == r"x_{ab}^{\prime}"
    assert mathfix.latexify_tex("\(d^3\u20d7\)") == r"\(d^{\vec{3}}\)"
