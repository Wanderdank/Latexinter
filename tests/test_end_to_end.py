"""
Conversión completa de ejemplo.pdf a LaTeX. Necesita PyMuPDF, pymupdf4llm y
pandoc; si falta alguno, se salta.
"""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("pymupdf4llm")
if not shutil.which("pandoc"):
    pytest.skip("pandoc no está instalado", allow_module_level=True)

from converters import convert  # noqa: E402

EJEMPLO = Path(__file__).resolve().parent.parent / "ejemplo.pdf"


def test_pdf_a_latex(tmp_path):
    pdf = tmp_path / "ejemplo.pdf"
    shutil.copy(EJEMPLO, pdf)

    result = convert("pdf2tex", str(pdf))
    tex = Path(result.output).read_text(encoding="utf-8")

    assert r"Documento de Ejemplo en \LaTeX{}" in tex
    assert r"\section{Referencias y Enlaces}" in tex
    assert r"\tableofcontents" in tex
    assert "mc^{2}" in tex
