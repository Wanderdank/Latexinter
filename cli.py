"""
cli.py - Latexinter desde la línea de comandos.

    python cli.py pdf2docx documento.pdf [--pages 1-5] [--ocr] [--toc]
    python cli.py pdf2tex  documento.pdf [--pages 1-5] [--twocolumn]
    python cli.py tex2pdf  documento.tex [--engine xelatex]
    python cli.py tex2docx documento.tex [--toc]
    python cli.py docx2tex documento.docx
    python cli.py docx2pdf documento.docx [--via-latex]
    python cli.py gui                      # abre la interfaz de escritorio
    python cli.py deps                     # comprueba las dependencias

Por defecto el resultado se guarda junto al archivo original. Se pueden pasar
varios archivos a la vez:  python cli.py pdf2docx *.pdf -d convertidos
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from converters import (  # noqa: E402
    CONVERSIONS,
    ConversionError,
    convert,
    dependency_report,
    human_size,
)
from converters import mathocr  # noqa: E402
from converters.common import refresh_path  # noqa: E402

# La consola de Windows no siempre habla UTF-8.
if sys.platform == "win32":
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")


def log(message: str) -> None:
    print(f"  {message}")


def banner(text: str) -> None:
    print()
    print("═" * 58)
    print(f"  {text}")
    print("═" * 58)
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="latexinter",
        description="Convierte entre PDF, LaTeX y Word.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("archivos", nargs="+", metavar="archivo", help="Archivos de entrada")
        p.add_argument("-o", "--output", help="Archivo de salida (solo con un archivo de entrada)")
        p.add_argument("-d", "--output-dir", help="Carpeta de salida")

    pdf2docx = sub.add_parser("pdf2docx", help="PDF → Word")
    common(pdf2docx)
    pdf2docx.add_argument("--pages", help='Páginas: "1-5" o "1,3,8-10"')
    pdf2docx.add_argument("--no-images", action="store_true", help="No extraer imágenes")
    pdf2docx.add_argument("--no-math", action="store_true", help="No reconstruir las fórmulas")
    pdf2docx.add_argument(
        "--ocr", action="store_true",
        help="Leer también las ecuaciones con un modelo de OCR (más lento)",
    )
    pdf2docx.add_argument(
        "--ocr-motor", choices=[backend.key for backend in mathocr.BACKENDS],
        help="Qué modelo de OCR usar (por defecto, Pix2Text-MFR)",
    )
    pdf2docx.add_argument("--toc", action="store_true", help="Incluir índice")
    pdf2docx.add_argument("--keep-tex", action="store_true", help="Conservar el .tex intermedio")
    pdf2docx.add_argument("--reference-doc", help="Plantilla .docx de estilos")

    docx2pdf = sub.add_parser("docx2pdf", help="Word → PDF")
    common(docx2pdf)
    docx2pdf.add_argument(
        "--via-latex", action="store_true",
        help="Compilar con LaTeX aunque haya Word o LibreOffice instalados",
    )
    docx2pdf.add_argument(
        "--engine", choices=["pdflatex", "xelatex", "lualatex"], default="pdflatex"
    )

    pdf2tex = sub.add_parser("pdf2tex", help="PDF → LaTeX")
    common(pdf2tex)
    pdf2tex.add_argument("--pages", help='Páginas: "1-5" o "1,3,8-10"')
    pdf2tex.add_argument("--twocolumn", action="store_true", help="Salida a dos columnas")
    pdf2tex.add_argument("--no-images", action="store_true", help="No extraer imágenes")
    pdf2tex.add_argument(
        "--no-math", action="store_true", help="No reconstruir las fórmulas"
    )
    pdf2tex.add_argument(
        "--ecuaciones",
        choices=["auto", "comentario", "latex", "imagen"],
        default="auto",
        help="Qué hacer con las ecuaciones destacadas. En 'auto', con --ocr se "
             "sustituyen por su LaTeX y sin él se conserva la imagen",
    )
    pdf2tex.add_argument(
        "--ocr",
        action="store_true",
        help="Leer también las ecuaciones con un modelo de OCR y quedarse con "
             "su lectura cuando cuadra con los glifos del PDF (más lento; la "
             "primera vez descarga el modelo, 120 MB)",
    )
    pdf2tex.add_argument(
        "--ocr-motor",
        choices=[backend.key for backend in mathocr.BACKENDS],
        help="Qué modelo de OCR usar (por defecto, Pix2Text-MFR)",
    )
    pdf2tex.add_argument(
        "--keep-md", action="store_true", help="Conservar el Markdown intermedio"
    )

    tex2pdf = sub.add_parser("tex2pdf", help="LaTeX → PDF")
    common(tex2pdf)
    tex2pdf.add_argument(
        "--engine", choices=["pdflatex", "xelatex", "lualatex"], default="pdflatex"
    )
    tex2pdf.add_argument(
        "--keep-aux", action="store_true", help="No borrar los archivos auxiliares"
    )

    tex2docx = sub.add_parser("tex2docx", help="LaTeX → Word")
    common(tex2docx)
    tex2docx.add_argument("--toc", action="store_true", help="Incluir índice")
    tex2docx.add_argument(
        "--no-numbers", action="store_true", help="No numerar las secciones"
    )
    tex2docx.add_argument("--reference-doc", help="Plantilla .docx de estilos")

    docx2tex = sub.add_parser("docx2tex", help="Word → LaTeX")
    common(docx2tex)
    docx2tex.add_argument("--twocolumn", action="store_true")
    docx2tex.add_argument("--no-images", action="store_true")

    sub.add_parser("gui", help="Abrir la interfaz de escritorio")
    sub.add_parser("deps", help="Comprobar las dependencias instaladas")
    return parser


def options_from(args: argparse.Namespace) -> dict:
    """Traduce los argumentos del comando a las opciones del conversor."""
    mapping = {
        "pdf2docx": lambda a: {
            "pages": a.pages,
            "extract_images": not a.no_images,
            "math_reconstruction": not a.no_math,
            "math_ocr": a.ocr,
            "ocr_backend": a.ocr_motor,
            "toc": a.toc,
            "keep_latex": a.keep_tex,
            "reference_doc": a.reference_doc,
        },
        "docx2pdf": lambda a: {
            "via_latex": a.via_latex,
            "engine": a.engine,
        },
        "pdf2tex": lambda a: {
            "pages": a.pages,
            "twocolumn": a.twocolumn,
            "extract_images": not a.no_images,
            "math_reconstruction": not a.no_math,
            "display_equations": None if a.ecuaciones == "auto" else a.ecuaciones,
            "math_ocr": a.ocr,
            "ocr_backend": a.ocr_motor,
            "keep_markdown": a.keep_md,
        },
        "tex2pdf": lambda a: {
            "engine": a.engine,
            "clean_aux": not a.keep_aux,
        },
        "tex2docx": lambda a: {
            "toc": a.toc,
            "number_sections": not a.no_numbers,
            "reference_doc": a.reference_doc,
        },
        "docx2tex": lambda a: {
            "twocolumn": a.twocolumn,
            "extract_images": not a.no_images,
        },
    }
    return mapping[args.comando](args)


def check_dependencies() -> int:
    banner("Dependencias de Latexinter")
    etiquetas = {
        "pandoc": "pandoc            (conversiones con Word y Markdown)",
        "pdflatex": "pdflatex          (compilar LaTeX a PDF)",
        "bibtex": "bibtex            (bibliografías)",
        "pymupdf4llm": "pymupdf4llm       (leer PDF)",
        "fitz": "PyMuPDF           (leer PDF)",
    }
    estado = dependency_report()
    faltan = 0
    for clave, descripcion in etiquetas.items():
        ruta = estado.get(clave)
        marca = "✓" if ruta else "✗"
        print(f"  {marca}  {descripcion}")
        if ruta:
            print(f"       {ruta}")
        else:
            faltan += 1

    # Opcionales: sin ellos la aplicación funciona, solo pierde una comodidad.
    from converters.common import find_tool

    for herramienta, descripcion in (
        ("synctex", "synctex           (saltar entre el código y el PDF)"),
        ("chktex", "chktex            (revisión de estilo del documento)"),
    ):
        ruta = find_tool(herramienta)
        print(f"  {'✓' if ruta else '·'}  {descripcion}{'' if ruta else '   [opcional]'}")

    for backend in mathocr.BACKENDS:
        marca = "✓" if backend.installed else "·"
        extra = "" if backend.installed else "   [opcional]"
        print(f"  {marca}  {backend.name:18}(OCR de fórmulas){extra}")
    if not mathocr.any_backend_installed():
        print()
        print("  Sin modelo de OCR se recuperan los índices y los símbolos,")
        print("  pero no las fracciones ni las matrices. Para instalarlo:")
        for backend in mathocr.BACKENDS:
            print(f"    {backend.install:26}# {backend.size}")
    print()
    if faltan:
        print("  Instala lo que falte:")
        print("    winget install --id JohnMacFarlane.Pandoc")
        print("    winget install --id MiKTeX.MiKTeX")
        print("    pip install -r requirements.txt")
        print()
    return 1 if faltan else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    refresh_path()

    if args.comando == "gui":
        from ui import run

        return run([sys.argv[0]])

    if args.comando == "deps":
        return check_dependencies()

    if args.output and len(args.archivos) > 1:
        print("\n  ✗ --output solo vale con un archivo de entrada; usa --output-dir.\n")
        return 2

    conversion = CONVERSIONS[args.comando]
    fallidos = 0
    for archivo in args.archivos:
        banner(f"{conversion.label}  ·  {Path(archivo).name}")
        try:
            resultado = convert(
                args.comando,
                archivo,
                args.output,
                args.output_dir,
                logger=log,
                **options_from(args),
            )
        except ConversionError as exc:
            print()
            print(f"  ✗ {exc}")
            print()
            fallidos += 1
            continue

        print()
        print(f"  ✓ {resultado.output}  ({human_size(resultado.output)})")
        for extra in resultado.extras:
            print(f"    + {extra.name}")
        for aviso in resultado.warnings:
            print(f"    ⚠ {aviso}")
        print()

    if len(args.archivos) > 1:
        print(f"  {len(args.archivos) - fallidos} de {len(args.archivos)} convertidos.\n")
    return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
