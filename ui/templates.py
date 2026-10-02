"""
templates.py - Documentos de partida.

Cada plantilla es un .tex que compila tal cual, con los paquetes en español ya
puestos, para no empezar nunca desde una página en blanco.
"""

from __future__ import annotations

from dataclasses import dataclass

PREAMBULO_BASE = r"""\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[spanish,es-nodecimaldot]{babel}
\usepackage{lmodern}
\usepackage{microtype}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}
\hypersetup{colorlinks=true, linkcolor=black, urlcolor=blue, citecolor=black}
"""


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    filename: str
    content: str


ARTICULO = r"""\documentclass[11pt,a4paper]{article}
""" + PREAMBULO_BASE + r"""\usepackage[margin=2.5cm]{geometry}

\title{Título del artículo}
\author{Tu nombre}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
Un resumen breve de lo que trata el artículo: el problema, cómo se ha
abordado y a qué conclusión se llega.
\end{abstract}

\section{Introducción}
Escribe aquí la introducción. Puedes citar una fórmula en línea, como
$E = mc^{2}$, o destacarla:

\begin{equation}
    \int_{-\infty}^{\infty} e^{-x^{2}} \, dx = \sqrt{\pi}
    \label{eq:gauss}
\end{equation}

La ecuación~\eqref{eq:gauss} es la integral de Gauss.

\section{Método}
\begin{itemize}
    \item Primer punto.
    \item Segundo punto.
\end{itemize}

\section{Resultados}
\begin{table}[htbp]
    \centering
    \caption{Resultados del experimento}
    \label{tab:resultados}
    \begin{tabular}{lcc}
        \toprule
        Caso & Medida & Error \\
        \midrule
        A & 1{,}23 & 0{,}01 \\
        B & 4{,}56 & 0{,}02 \\
        \bottomrule
    \end{tabular}
\end{table}

\section{Conclusiones}
Lo que se deduce de todo lo anterior.

\end{document}
"""

INFORME = r"""\documentclass[11pt,a4paper]{report}
""" + PREAMBULO_BASE + r"""\usepackage[margin=2.5cm]{geometry}
\usepackage{fancyhdr}

\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{Informe}
\fancyhead[R]{\thepage}

\title{\Huge Título del informe \\[0.5cm] \Large Subtítulo}
\author{Tu nombre \\ Organización}
\date{\today}

\begin{document}
\maketitle
\tableofcontents
\newpage

\chapter{Introducción}
Contexto y objetivo del informe.

\section{Alcance}
Qué entra y qué no.

\chapter{Desarrollo}
\section{Primera parte}
Contenido.

\section{Segunda parte}
Contenido.

\chapter{Conclusiones}
Resumen de los hallazgos y recomendaciones.

\end{document}
"""

CARTA = r"""\documentclass[11pt,a4paper]{letter}
""" + PREAMBULO_BASE + r"""\usepackage[margin=3cm]{geometry}

\signature{Tu nombre}
\address{Tu dirección \\ Ciudad, código postal \\ correo@ejemplo.com}

\begin{document}

\begin{letter}{Nombre del destinatario \\ Su dirección \\ Ciudad}

\opening{Estimado/a señor/a:}

Escribe aquí el cuerpo de la carta. Un párrafo por idea, y al final la
petición o la conclusión que quieres que quede clara.

Quedo a la espera de su respuesta.

\closing{Atentamente,}

\end{letter}
\end{document}
"""

PRESENTACION = r"""\documentclass[aspectratio=169]{beamer}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[spanish]{babel}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}

\usetheme{Madrid}
\usecolortheme{dolphin}
\setbeamertemplate{navigation symbols}{}

\title{Título de la presentación}
\subtitle{Subtítulo}
\author{Tu nombre}
\institute{Organización}
\date{\today}

\begin{document}

\frame{\titlepage}

\begin{frame}{Índice}
    \tableofcontents
\end{frame}

\section{Introducción}

\begin{frame}{Planteamiento}
    \begin{itemize}
        \item Primer punto.
        \item Segundo punto.
        \item Tercer punto.
    \end{itemize}
\end{frame}

\begin{frame}{Una fórmula}
    \begin{equation*}
        f(x) = \sum_{n=0}^{\infty} \frac{f^{(n)}(a)}{n!}(x-a)^{n}
    \end{equation*}
\end{frame}

\section{Conclusiones}

\begin{frame}{Conclusiones}
    Lo que hay que recordar de esta charla.
\end{frame}

\end{document}
"""

TESIS = r"""\documentclass[12pt,a4paper,oneside]{book}
""" + PREAMBULO_BASE + r"""\usepackage[margin=3cm]{geometry}
\usepackage{setspace}
\onehalfspacing

\title{Título de la tesis}
\author{Tu nombre}
\date{\today}

\begin{document}

\frontmatter
\maketitle

\chapter*{Agradecimientos}
A quien corresponda.

\tableofcontents
\listoffigures
\listoftables

\mainmatter

\chapter{Introducción}
\section{Motivación}
\section{Objetivos}

\chapter{Estado del arte}

\chapter{Metodología}

\chapter{Resultados}

\chapter{Conclusiones}

\appendix
\chapter{Material adicional}

\backmatter
% \bibliographystyle{plain}
% \bibliography{referencias}

\end{document}
"""

CURRICULUM = r"""\documentclass[11pt,a4paper]{article}
""" + PREAMBULO_BASE + r"""\usepackage[margin=2cm]{geometry}
\usepackage{enumitem}
\usepackage{titlesec}

\titleformat{\section}{\large\bfseries}{}{0pt}{}[\titlerule]
\titlespacing{\section}{0pt}{12pt}{6pt}
\setlist[itemize]{leftmargin=*, itemsep=2pt, topsep=2pt}
\pagestyle{empty}

\begin{document}

\begin{center}
    {\LARGE \textbf{Tu nombre}} \\[4pt]
    Ciudad · correo@ejemplo.com · teléfono
\end{center}

\section{Formación}
\textbf{Título de la carrera} \hfill 2020 -- 2024 \\
Universidad
\begin{itemize}
    \item Mención o proyecto destacado.
\end{itemize}

\section{Experiencia}
\textbf{Puesto} \hfill 2024 -- actualidad \\
\textit{Empresa}
\begin{itemize}
    \item Qué hiciste y qué resultado tuvo.
\end{itemize}

\section{Conocimientos}
\begin{itemize}
    \item \textbf{Idiomas:} español (nativo), inglés (B2).
    \item \textbf{Herramientas:} \LaTeX{}, Python, Git.
\end{itemize}

\end{document}
"""

EXAMEN = r"""\documentclass[11pt,a4paper]{article}
""" + PREAMBULO_BASE + r"""\usepackage[margin=2.5cm]{geometry}
\usepackage{enumitem}

\newcommand{\punto}[1]{\hfill\textit{(#1 puntos)}}

\begin{document}

\begin{center}
    {\Large \textbf{Título de la asignatura}} \\[4pt]
    {\large Examen --- \today} \\[10pt]
    Nombre: \rule{7cm}{0.4pt} \qquad Grupo: \rule{2cm}{0.4pt}
\end{center}

\vspace{6pt}
\hrule
\vspace{12pt}

\begin{enumerate}[leftmargin=*, itemsep=14pt]

    \item Enunciado de la primera pregunta. \punto{2}

    \item Resuelve la ecuación siguiente: \punto{3}
    \begin{equation*}
        x^{2} - 5x + 6 = 0
    \end{equation*}

    \item Pregunta con apartados: \punto{5}
    \begin{enumerate}[label=(\alph*)]
        \item Primer apartado.
        \item Segundo apartado.
    \end{enumerate}

\end{enumerate}

\end{document}
"""

TEMPLATES: list[Template] = [
    Template("articulo", "Artículo",
             "Artículo académico con resumen, secciones y bibliografía.",
             "articulo.tex", ARTICULO),
    Template("informe", "Informe",
             "Informe por capítulos, con índice y encabezados.",
             "informe.tex", INFORME),
    Template("presentacion", "Presentación (Beamer)",
             "Diapositivas con tema, índice y transparencias de ejemplo.",
             "presentacion.tex", PRESENTACION),
    Template("tesis", "Tesis o libro",
             "Estructura larga: portada, índices, capítulos y apéndices.",
             "tesis.tex", TESIS),
    Template("carta", "Carta",
             "Carta formal con remitente, destinatario y despedida.",
             "carta.tex", CARTA),
    Template("curriculum", "Currículum",
             "Currículum de una página, sobrio y sin paquetes raros.",
             "curriculum.tex", CURRICULUM),
    Template("examen", "Examen",
             "Hoja de examen con preguntas numeradas y puntuación.",
             "examen.tex", EXAMEN),
]

TEMPLATES_POR_CLAVE = {t.key: t for t in TEMPLATES}

DOCUMENTO_VACIO = r"""\documentclass[11pt,a4paper]{article}
""" + PREAMBULO_BASE + r"""\usepackage[margin=2.5cm]{geometry}

\begin{document}

Escribe aquí.

\end{document}
"""
