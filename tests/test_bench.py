"""La medición de fórmulas: extraer, normalizar y comparar."""

from bench import formulas as f


def _tokens(texto: str) -> list[str]:
    return f.normalize(texto)


# ── Normalizar ──────────────────────────────────────────────

def test_lo_que_se_ve_igual_cuenta_igual():
    assert _tokens(r"x^{2}") == _tokens(r"x^2")
    assert _tokens(r"a \le b") == _tokens(r"a\leq b")
    assert _tokens(r"\left( x \right)") == _tokens(r"(x)")
    assert _tokens(r"f^{\prime}(x)") == _tokens(r"f'(x)")
    assert _tokens(r"\mathrm{d}x") == _tokens(r"dx")
    assert _tokens(r"E = mc^2 \label{eq:e}") == _tokens(r"E=mc^{2},")
    assert _tokens(r"\dfrac{1}{2}") == _tokens(r"\frac12")
    assert _tokens(r"x^{\ast}") == _tokens(r"x^*")


def test_lo_que_se_ve_distinto_no():
    assert _tokens(r"x^{ab}") != _tokens(r"x^a b")
    assert _tokens(r"x_2") != _tokens(r"x2")
    assert _tokens(r"\frac{a}{b}") != _tokens(r"a/b")


# ── Extraer ─────────────────────────────────────────────────

def test_extrae_todos_los_tipos_de_formula():
    tex = r"""
\documentclass{article}
\begin{document}
Texto con $a+b$ y \(c\) y precio \$5.
\[ x = 1 \]
\begin{align}
  y &= 2 \\
  z &= \begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}
\end{align}
% $comentado$
\begin{verbatim} $no$ \end{verbatim}
\end{document}
"""
    encontradas = f.extract(tex)
    textos = [x.text for x in encontradas]
    assert textos[:3] == ["a+b", "c", "x = 1"]
    assert len(encontradas) == 5                 # la matriz no se parte en filas
    assert [x.display for x in encontradas] == [False, False, True, True, True]
    assert "matrices" in f.kinds(encontradas[4])


def test_expande_las_macros_del_autor():
    tex = r"""
\newcommand{\R}{\mathbb{R}}
\newcommand{\norm}[1]{\left\| #1 \right\|}
\DeclareMathOperator{\tr}{tr}
\begin{document}
$\norm{x} \in \R$ y $\tr A$
\end{document}
"""
    macros = f.find_macros(tex)
    tex = f.expand_macros(tex, macros)
    textos = [x.tokens for x in f.extract(tex)]
    assert textos[0] == _tokens(r"\| x \| \in \mathbb{R}")
    assert textos[1] == _tokens(r"\operatorname{tr} A")


# ── Comparar ────────────────────────────────────────────────

def test_parecido():
    assert f.similarity(["a"], ["a"]) == 1.0
    assert f.similarity(["a", "b"], ["a", "c"]) == 0.5
    assert f.similarity([], ["a"]) == 0.0


def test_empareja_cada_original_con_la_mas_parecida():
    originales = f.extract(r"$x^2$ y $\frac{a}{b}$ y $y_1$")
    encontradas = f.extract(r"$x^2$ y $y1$ y $a b$")
    notas = {m.original.text: round(m.score, 2) for m in f.match(originales, encontradas)}
    assert notas["x^2"] == 1.0
    assert 0 < notas["y_1"] < 1
    assert notas[r"\frac{a}{b}"] < 1
