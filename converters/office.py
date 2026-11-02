"""
office.py - Word o LibreOffice, si están instalados, para exportar a PDF.

Nadie pagina un .docx como Word: pasarlo por LaTeX pierde la maquetación. Por
eso, si hay un procesador de textos en el equipo, se le pide a él el PDF. Sirve
para Word → PDF y para enseñar en la ventana cómo queda un .docx convertido.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

from .common import ConversionError, run_command, tail

WORD = "Microsoft Word"
LIBREOFFICE = "LibreOffice"

# Las rutas van por variables de entorno: dentro del script habría que escapar
# comillas, y PowerShell también trata las tipográficas (’) como comillas.
_SCRIPT_WORD = r"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
try {
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($env:LATEXINTER_ENTRADA, $false, $true, $false)
    try { $doc.ExportAsFixedFormat($env:LATEXINTER_SALIDA, 17) }
    finally { $doc.Close(0) }
} finally {
    $word.Quit()
}
"""


def _word_installed() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CurVer"):
            return True
    except OSError:
        return False


def _find_soffice() -> Optional[str]:
    for nombre in ("soffice", "libreoffice"):
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    if sys.platform == "win32":
        for raiz in (r"C:\Program Files", r"C:\Program Files (x86)"):
            candidato = Path(raiz) / "LibreOffice" / "program" / "soffice.exe"
            if candidato.exists():
                return str(candidato)
    return None


def office_name() -> Optional[str]:
    """El procesador de textos que se usará para exportar, o None si no hay."""
    if _word_installed():
        return WORD
    if _find_soffice():
        return LIBREOFFICE
    return None


def export_pdf(docx: Path, pdf: Path) -> str:
    """Exporta el .docx a ese PDF. Devuelve qué programa lo hizo."""
    docx, pdf = Path(docx).resolve(), Path(pdf).resolve()
    nombre = office_name()
    if nombre is None:
        raise ConversionError("No hay Word ni LibreOffice instalados.")

    if nombre == WORD:
        resultado = run_command(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT_WORD],
            timeout=300,
            env={"LATEXINTER_ENTRADA": str(docx), "LATEXINTER_SALIDA": str(pdf)},
        )
    else:
        # LibreOffice elige el nombre: el del .docx, en la carpeta indicada.
        pdf.parent.mkdir(parents=True, exist_ok=True)
        resultado = run_command(
            [_find_soffice(), "--headless", "--convert-to", "pdf", "--outdir", str(pdf.parent), str(docx)],
            timeout=300,
        )
        generado = pdf.parent / (docx.stem + ".pdf")
        if resultado.returncode == 0 and generado.exists() and generado != pdf:
            generado.replace(pdf)

    if resultado.returncode != 0 or not pdf.exists():
        raise ConversionError(
            f"{nombre} no pudo exportar el documento a PDF:\n"
            + tail(resultado.stderr or resultado.stdout)
        )
    return nombre
