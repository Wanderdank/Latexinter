"""PDF → Word y Word → PDF, y lo que los dos necesitan de LaTeX → Word."""

import importlib
import shutil
import zipfile
from pathlib import Path

import pytest

import cli
import converters
from converters.common import CancelToken, Cancelled, cancellable, check_cancelled

# `from converters import latex_to_docx` daría la función, que tapa al módulo.
l2d = importlib.import_module("converters.latex_to_docx")

RAIZ = Path(__file__).resolve().parent.parent
EJEMPLO = RAIZ / "ejemplos" / "ejemplo.pdf"


def test_un_lote_solo_ofrece_lo_que_todos_admiten():
    assert converters.common_targets(["a.pdf", "b.pdf"]) == [".docx", ".tex"]
    assert converters.common_targets(["a.pdf", "b.tex"]) == [".docx"]
    assert converters.common_targets(["a.pdf", "b.tex", "c.docx"]) == []
    assert converters.common_targets([]) == []


def test_las_seis_direcciones_estan_registradas():
    assert set(converters.CONVERSIONS) == {
        "pdf2docx", "pdf2tex", "tex2pdf", "tex2docx", "docx2tex", "docx2pdf",
    }


def test_un_pdf_ofrece_word_primero():
    assert [c.key for c in converters.conversions_for("a.pdf")] == ["pdf2docx", "pdf2tex"]
    assert [c.key for c in converters.conversions_for("a.docx")] == ["docx2tex", "docx2pdf"]


def test_pandocbounded_no_se_come_las_imagenes():
    fuente = r"\pandocbounded{\includegraphics[keepaspectratio]{fig.png}}"
    assert l2d.word_friendly_source(fuente) == r"{\includegraphics[keepaspectratio]{fig.png}}"


def test_separa_las_formulas_del_resto_de_avisos():
    stderr = (
        "[WARNING] Could not convert TeX math x\\\\y, rendering as TeX:\n"
        "  x\\\\y\n    ^\n  unexpected control sequence\n"
        "[WARNING] Could not convert TeX math a\\\\b, rendering as TeX:\n  a\\\\b\n"
        "[WARNING] Could not fetch resource fig.png\n"
    )
    formulas, otros = l2d.split_pandoc_warnings(stderr)
    assert formulas == 2
    assert otros == ["[WARNING] Could not fetch resource fig.png"]


def test_sin_avisos():
    assert l2d.split_pandoc_warnings("") == (0, [])


def test_cuenta_lo_que_hay_dentro_de_un_docx(tmp_path):
    docx = tmp_path / "a.docx"
    with zipfile.ZipFile(docx, "w") as paquete:
        paquete.writestr(
            "word/document.xml",
            "<m:oMathPara><m:oMathParaPr/><m:oMath>x</m:oMath></m:oMathPara><m:oMath>y</m:oMath>",
        )
        paquete.writestr("word/media/a.png", b"")
    assert l2d.count_word_content(docx) == {"ecuaciones_word": 2, "imagenes": 1}


def test_cancelar_interrumpe_el_trabajo_en_python():
    token = CancelToken()
    with cancellable(token):
        check_cancelled()                # sin cancelar, no pasa nada
        token.cancel()
        with pytest.raises(Cancelled):
            check_cancelled()


def test_la_linea_de_comandos_admite_varios_archivos():
    args = cli.build_parser().parse_args(["pdf2docx", "a.pdf", "b.pdf", "-d", "salida", "--ocr"])
    assert args.archivos == ["a.pdf", "b.pdf"]
    opciones = cli.options_from(args)
    assert opciones["math_ocr"] is True and opciones["toc"] is False


def test_output_no_vale_con_varios_archivos(capsys):
    assert cli.main(["pdf2docx", "a.pdf", "b.pdf", "-o", "x.docx"]) == 2


def test_plantilla_de_word_incluida():
    assert l2d.WORD_TEMPLATE.exists()


def test_pdf_a_word_de_verdad(tmp_path):
    pytest.importorskip("fitz")
    pytest.importorskip("pymupdf4llm")
    if not shutil.which("pandoc"):
        pytest.skip("hace falta pandoc")

    resultado = converters.convert("pdf2docx", EJEMPLO, output_dir=tmp_path, logger=lambda _: None)

    assert resultado.output.suffix == ".docx" and resultado.output.exists()
    assert resultado.stats["ecuaciones_word"] >= 5
    # El .tex intermedio no se queda por ahí.
    assert list(tmp_path.glob("*.tex")) == []


def test_latex_a_word_no_pisa_un_docx_existente(tmp_path):
    if not shutil.which("pandoc"):
        pytest.skip("hace falta pandoc")

    tex = tmp_path / "doc.tex"
    tex.write_text("\\documentclass{article}\\begin{document}Hola\\end{document}", encoding="utf-8")
    retocado = tmp_path / "doc.docx"
    retocado.write_bytes(b"retoques hechos en Word")

    resultado = converters.convert("tex2docx", tex, logger=lambda _: None)

    assert resultado.output.name == "doc_1.docx"
    assert retocado.read_bytes() == b"retoques hechos en Word"


def test_pdf_a_word_no_pisa_un_docx_existente(tmp_path):
    pytest.importorskip("fitz")
    pytest.importorskip("pymupdf4llm")
    if not shutil.which("pandoc"):
        pytest.skip("hace falta pandoc")

    existente = tmp_path / "ejemplo.docx"
    existente.write_bytes(b"retocado a mano")
    resultado = converters.convert("pdf2docx", EJEMPLO, output_dir=tmp_path, logger=lambda _: None)

    assert resultado.output != existente
    assert existente.read_bytes() == b"retocado a mano"
