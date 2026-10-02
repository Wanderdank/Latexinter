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
