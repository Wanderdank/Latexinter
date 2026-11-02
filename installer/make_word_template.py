"""
make_word_template.py - Genera assets/word-plantilla.docx.

Parte de la plantilla de pandoc y le cambia los estilos para que un documento
convertido parezca escrito a mano: serifa, títulos en negro y sin el azul de
serie, poco aire entre párrafos y márgenes de A4. Hay que volver a ejecutarlo
solo si se quieren cambiar esos estilos (necesita python-docx):

    python installer/make_word_template.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "assets" / "word-plantilla.docx"

TEXTO = "Cambria"
CODIGO = "Consolas"
TINTA = RGBColor(0x1A, 0x1A, 0x1A)
ENLACE = RGBColor(0x1F, 0x4E, 0x79)


def fijar_fuente(estilo, nombre: str) -> None:
    """Fija la fuente de verdad: los atributos de tema de pandoc ganan a font.name."""
    estilo.font.name = nombre
    fuentes = estilo.element.get_or_add_rPr().get_or_add_rFonts()
    for atributo in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        clave = qn(f"w:{atributo}")
        if clave in fuentes.attrib:
            del fuentes.attrib[clave]
    for atributo in ("ascii", "hAnsi", "eastAsia", "cs"):
        fuentes.set(qn(f"w:{atributo}"), nombre)


def parrafo(estilos, nombre: str, *, antes=0.0, despues=6.0, interlineado=1.1, alineado=None) -> None:
    if nombre not in [e.name for e in estilos]:
        return
    formato = estilos[nombre].paragraph_format
    formato.space_before = Pt(antes)
    formato.space_after = Pt(despues)
    formato.line_spacing = interlineado
    if alineado is not None:
        formato.alignment = alineado


def titulo(estilos, nombre: str, tamano: float, *, antes: float, despues: float, negrita=True) -> None:
    if nombre not in [e.name for e in estilos]:
        return
    estilo = estilos[nombre]
    fijar_fuente(estilo, TEXTO)
    estilo.font.size = Pt(tamano)
    estilo.font.bold = negrita
    estilo.font.italic = False
    estilo.font.color.rgb = TINTA
    parrafo(estilos, nombre, antes=antes, despues=despues, interlineado=1.05)
    estilo.paragraph_format.keep_with_next = True


def main() -> None:
    with tempfile.TemporaryDirectory() as temporal:
        base = Path(temporal) / "base.docx"
        with base.open("wb") as salida:
            subprocess.run(
                ["pandoc", "--print-default-data-file", "reference.docx"],
                stdout=salida, check=True,
            )
        documento = Document(base)

    seccion = documento.sections[0]
    seccion.page_width, seccion.page_height = Cm(21.0), Cm(29.7)
    seccion.left_margin = seccion.right_margin = Cm(2.5)
    seccion.top_margin = seccion.bottom_margin = Cm(2.5)

    estilos = documento.styles
    for nombre in ("Normal", "Body Text", "First Paragraph", "Compact", "Block Text",
                   "Abstract", "Bibliography", "Date", "Author", "Subtitle",
                   "Table Caption", "Image Caption", "Footnote Text"):
        if nombre in [e.name for e in estilos]:
            fijar_fuente(estilos[nombre], TEXTO)
            estilos[nombre].font.color.rgb = TINTA
    estilos["Normal"].font.size = Pt(11)

    for nombre in ("Body Text", "First Paragraph"):
        parrafo(estilos, nombre, despues=6, alineado=WD_ALIGN_PARAGRAPH.JUSTIFY)
    parrafo(estilos, "Compact", despues=2)
    parrafo(estilos, "Bibliography", despues=4)

    cita = estilos["Block Text"]
    cita.font.size = Pt(10.5)
    cita.font.italic = False
    parrafo(estilos, "Block Text", antes=2, despues=6)
    cita.paragraph_format.left_indent = Cm(0.8)
    cita.paragraph_format.right_indent = Cm(0.8)

    titulo(estilos, "Title", 18, antes=0, despues=8)
    estilos["Title"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    titulo(estilos, "Subtitle", 13, antes=0, despues=6, negrita=False)
    titulo(estilos, "Heading 1", 15, antes=16, despues=6)
    titulo(estilos, "Heading 2", 12.5, antes=12, despues=4)
    titulo(estilos, "Heading 3", 11, antes=10, despues=3)
    titulo(estilos, "Heading 4", 11, antes=8, despues=2, negrita=False)
    estilos["Heading 4"].font.italic = True

    for nombre in ("Author", "Date"):
        parrafo(estilos, nombre, despues=2, alineado=WD_ALIGN_PARAGRAPH.CENTER)
    for nombre in ("Table Caption", "Image Caption"):
        estilos[nombre].font.size = Pt(9.5)
        estilos[nombre].font.italic = False
        parrafo(estilos, nombre, antes=4, despues=8, alineado=WD_ALIGN_PARAGRAPH.CENTER)

    for nombre in ("Hyperlink", "Verbatim Char", "Source Code"):
        if nombre not in [e.name for e in estilos]:
            continue
        if nombre == "Hyperlink":
            estilos[nombre].font.color.rgb = ENLACE
        else:
            fijar_fuente(estilos[nombre], CODIGO)
            estilos[nombre].font.size = Pt(9.5)

    documento.save(DESTINO)
    print(f"{DESTINO} ({DESTINO.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
