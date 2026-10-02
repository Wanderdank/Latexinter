"""
app.py - Latexinter.

    python app.py                 abre la aplicación
    python app.py tesis.tex       abre ese documento en el editor
    python app.py articulo.pdf    lo carga en el conversor

Un entorno de LaTeX de escritorio: editor con autocompletado, compilación en
vivo, vista del PDF sincronizada con el código, panel de errores y conversión
entre PDF, LaTeX y Word.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Importar ui carga PyMuPDF antes que PyQt5, que es como tiene que ser: si Qt
# entra primero, PyMuPDF extrae los PDF de otra manera. Está explicado en
# ui/__init__.py.
from ui import run  # noqa: E402


def main() -> int:
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
