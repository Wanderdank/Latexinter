"""
arxiv.py - Bajar un paper de arXiv con su código LaTeX original.

arXiv guarda el .tex que escribieron los autores y el PDF que sale de él. El
.tex es la respuesta correcta con la que se compara lo que saca Latexinter
del PDF. Todo se guarda en bench/cache/, que no se sube al repositorio: los
papers son de sus autores.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
import time
import urllib.request
from pathlib import Path

USER_AGENT = "Latexinter-bench (+https://github.com/Wanderdank/Latexinter)"
PAUSA = 3.0                       # arXiv pide no más de una petición cada 3 s
_ultima_peticion = 0.0


class SinFuente(Exception):
    """El paper no tiene el .tex disponible (solo se subió el PDF)."""


def _bajar(url: str) -> bytes:
    global _ultima_peticion
    espera = PAUSA - (time.monotonic() - _ultima_peticion)
    if espera > 0:
        time.sleep(espera)
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(peticion, timeout=120) as respuesta:
            return respuesta.read()
    finally:
        _ultima_peticion = time.monotonic()


def carpeta(cache: Path, arxiv_id: str) -> Path:
    return cache / arxiv_id.replace("/", "_")


def descargar(arxiv_id: str, cache: Path) -> tuple[Path, Path]:
    """
    Deja en la caché el PDF y el .tex original con todo dentro (los \\input
    sustituidos). Devuelve sus rutas. Si ya estaban, no baja nada.
    """
    destino = carpeta(cache, arxiv_id)
    pdf = destino / "paper.pdf"
    original = destino / "original.tex"
    if pdf.exists() and original.exists():
        return pdf, original

    destino.mkdir(parents=True, exist_ok=True)
    fuente = destino / "fuente"
    if not original.exists():
        datos = _bajar(f"https://arxiv.org/e-print/{arxiv_id}")
        _desempaquetar(datos, fuente)
        original.write_text(aplanar(_principal(fuente)), encoding="utf-8")
    if not pdf.exists():
        pdf.write_bytes(_bajar(f"https://arxiv.org/pdf/{arxiv_id}"))
    return pdf, original


def _desempaquetar(datos: bytes, fuente: Path) -> None:
    if datos.startswith(b"%PDF"):
        raise SinFuente("arXiv solo tiene el PDF")
    try:
        datos = gzip.decompress(datos)
    except OSError:
        pass
    fuente.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(datos)) as tar:
            tar.extractall(fuente, filter="data")
    except tarfile.ReadError:
        # Un solo archivo comprimido, sin tar: es el .tex.
        (fuente / "main.tex").write_bytes(datos)


def _principal(fuente: Path) -> Path:
    """El .tex que tiene el \\documentclass y el \\begin{document}."""
    candidatos = []
    for tex in fuente.rglob("*.tex"):
        texto = tex.read_text(encoding="utf-8", errors="replace")
        if "\\documentclass" in texto and "\\begin{document}" in texto:
            candidatos.append((len(texto), tex))
    if not candidatos:
        raise SinFuente("no hay ningún .tex con \\documentclass")
    return max(candidatos)[1]


_RE_INPUT = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")


def aplanar(archivo: Path, raiz: Path | None = None, profundidad: int = 0) -> str:
    """
    El documento con los \\input e \\include sustituidos por su contenido.
    Como en LaTeX, las rutas son relativas a la carpeta del documento
    principal, no a la del archivo que hace el \\input.
    """
    texto = archivo.read_text(encoding="utf-8", errors="replace")
    if profundidad > 8:
        return texto
    raiz = raiz or archivo.parent

    def sustituir(m: re.Match) -> str:
        nombre = m.group(1).strip()
        for candidato in (raiz / nombre, raiz / f"{nombre}.tex"):
            if candidato.is_file():
                return aplanar(candidato, raiz, profundidad + 1)
        return ""

    return _RE_INPUT.sub(sustituir, texto)
