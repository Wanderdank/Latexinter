"""
textfiles.py - Leer y guardar los archivos del usuario sin estropearlos.

Tres cosas que un editor no puede hacer mal:

  · respetar la codificación: un .tex antiguo en Latin-1 debe volver al disco
    en Latin-1, con sus eñes intactas, y no convertido en «�»;
  · respetar los finales de línea (LF o CRLF), para que guardar no cambie
    todas las líneas del archivo;
  · no dejar nunca el archivo a medias: se escribe en un temporal y se
    sustituye de una vez.

Además guarda copias de recuperación de lo que no se ha guardado, para no
perderlo si la aplicación se cierra de golpe.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Optional

# ────────────────────────────────────────────────────────────
# Codificación y finales de línea
# ────────────────────────────────────────────────────────────

# Opciones de inputenc → códec de Python.
_INPUTENC = {
    "utf8": "utf-8",
    "latin1": "latin-1",
    "latin9": "iso8859-15",
    "ansinew": "cp1252",
    "cp1252": "cp1252",
    "cp850": "cp850",
    "applemac": "mac_roman",
}
_RE_INPUTENC = re.compile(r"\\usepackage\s*\[([^\]]*)\]\s*\{inputenc\}")

NOMBRES_CODIFICACION = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 con BOM",
    "latin-1": "Latin-1",
    "iso8859-15": "Latin-9",
    "cp1252": "Windows-1252",
    "cp850": "DOS (cp850)",
    "mac_roman": "Mac Roman",
}


@dataclass(frozen=True)
class TextFormat:
    """Cómo estaba escrito el archivo en el disco."""

    encoding: str = "utf-8"
    newline: str = "\n"

    @property
    def label(self) -> str:
        return NOMBRES_CODIFICACION.get(self.encoding, self.encoding)


def _declared_encoding(data: bytes) -> Optional[str]:
    """La codificación que declara el propio documento con inputenc."""
    match = _RE_INPUTENC.search(data.decode("latin-1"))
    if not match:
        return None
    for opcion in reversed(match.group(1).split(",")):
        codec = _INPUTENC.get(opcion.strip().lower())
        if codec:
            return codec
    return None


def decode_source(data: bytes) -> tuple[str, TextFormat]:
    """
    Decodifica un archivo de texto sin perder nada. Se prueba UTF-8; si no lo
    es, se usa lo que declare inputenc, y si no declara nada, Windows-1252, que
    es lo que suelen tener los .tex antiguos escritos en Windows. Latin-1 es el
    último recurso: decodifica cualquier byte y al guardar lo deja igual.
    """
    newline = "\r\n" if b"\r\n" in data else "\n"

    if data.startswith(b"\xef\xbb\xbf"):
        candidatos = ["utf-8-sig"]
    else:
        candidatos = ["utf-8", _declared_encoding(data) or "cp1252", "latin-1"]

    for encoding in dict.fromkeys(candidatos):
        try:
            texto = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        return texto, TextFormat(encoding, newline)

    raise AssertionError("latin-1 decodifica cualquier secuencia de bytes")


def read_source(path: Path | str) -> tuple[str, TextFormat]:
    return decode_source(Path(path).read_bytes())


def encode_source(text: str, fmt: TextFormat = TextFormat()) -> bytes:
    """
    Lanza UnicodeEncodeError si el texto tiene caracteres que la codificación
    del archivo no admite (una flecha «→» en un archivo Latin-1, por ejemplo).
    """
    return text.replace("\n", fmt.newline).encode(fmt.encoding)


def write_atomic(path: Path | str, data: bytes) -> None:
    """
    Escribe el archivo entero o no lo toca: primero en un temporal de la misma
    carpeta y después se sustituye el original de una sola vez.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as archivo:
            archivo.write(data)
            archivo.flush()
            os.fsync(archivo.fileno())
        if path.exists():
            with contextlib.suppress(OSError):
                shutil.copymode(path, temporal)
        _replace(temporal, path, data)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporal)


def _replace(temporal: str, path: Path, data: bytes) -> None:
    for intento in range(5):
        try:
            os.replace(temporal, path)
            return
        except PermissionError:
            if sys.platform != "win32":
                raise
            time.sleep(0.05 * (intento + 1))
    # En Windows no se puede sustituir un archivo que otro programa tiene
    # abierto, y pdflatex mantiene abierto el .tex mientras compila. El
    # contenido ya se escribió bien una vez, así que se escribe encima.
    with open(path, "wb") as archivo:
        archivo.write(data)
        archivo.flush()
        os.fsync(archivo.fileno())


def write_source(path: Path | str, text: str, fmt: TextFormat = TextFormat()) -> None:
    # Se codifica antes de abrir nada: si falla, el archivo queda intacto.
    write_atomic(path, encode_source(text, fmt))


# ────────────────────────────────────────────────────────────
# Copias de recuperación
# ────────────────────────────────────────────────────────────

@dataclass
class Recovered:
    """Un documento sin guardar que dejó una sesión que acabó de golpe."""

    path: Optional[Path]
    text: str
    format: TextFormat
    saved_at: float
    file: Path


def _try_lock(path: Path) -> Optional[IO[bytes]]:
    """
    Bloquea el archivo para este proceso. El sistema lo libera solo cuando el
    proceso muere, así que un bloqueo que se puede coger es de una sesión que
    ya no existe.
    """
    archivo = open(path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            archivo.seek(0)
            msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        archivo.close()
        return None
    return archivo


def _unlock(archivo: IO[bytes]) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt

            archivo.seek(0)
            msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
    archivo.close()


class RecoveryStore:
    """
    Una carpeta por sesión abierta, con un .json por documento sin guardar.
    Al cerrar bien se borra la carpeta; si queda alguna de una sesión muerta,
    lo que contiene es lo que se perdió y se puede recuperar.
    """

    PREFIJO = "sesion-"

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.folder = self.root / f"{self.PREFIJO}{uuid.uuid4().hex}"
        self.folder.mkdir(parents=True, exist_ok=True)
        self._lock = _try_lock(self.folder / ".lock")
        # Sesiones muertas cuyo bloqueo se ha cogido: así otra ventana que
        # arranque a la vez no ofrece recuperar lo mismo.
        self._ajenas: dict[Path, IO[bytes]] = {}

    def _file(self, doc_id: str) -> Path:
        return self.folder / f"{doc_id}.json"

    def save(self, doc_id: str, path: Optional[Path], text: str,
             fmt: TextFormat = TextFormat()) -> None:
        datos = {
            "path": str(path) if path else None,
            "encoding": fmt.encoding,
            "newline": fmt.newline,
            "saved_at": time.time(),
            "text": text,
        }
        write_atomic(self._file(doc_id), json.dumps(datos, ensure_ascii=False).encode("utf-8"))

    def discard(self, doc_id: str) -> None:
        with contextlib.suppress(OSError):
            self._file(doc_id).unlink()

    def orphans(self) -> list[Recovered]:
        """Lo que dejaron sin guardar las sesiones que ya no están abiertas."""
        encontrados: list[Recovered] = []
        for carpeta in sorted(self.root.glob(f"{self.PREFIJO}*")):
            if carpeta == self.folder or carpeta in self._ajenas or not carpeta.is_dir():
                continue
            bloqueo = _try_lock(carpeta / ".lock")
            if bloqueo is None:
                continue                      # sesión viva, en otra ventana
            self._ajenas[carpeta] = bloqueo

            documentos = [d for d in map(self._load, sorted(carpeta.glob("*.json"))) if d]
            if documentos:
                encontrados.extend(documentos)
            else:
                self._drop_session(carpeta)
        encontrados.sort(key=lambda d: d.saved_at)
        return encontrados

    @staticmethod
    def _load(archivo: Path) -> Optional[Recovered]:
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
            return Recovered(
                path=Path(datos["path"]) if datos.get("path") else None,
                text=datos["text"],
                format=TextFormat(datos.get("encoding", "utf-8"), datos.get("newline", "\n")),
                saved_at=float(datos.get("saved_at", 0)),
                file=archivo,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def forget(self, documentos: list[Recovered]) -> None:
        """Borra las copias ya recuperadas o descartadas."""
        carpetas = set()
        for documento in documentos:
            with contextlib.suppress(OSError):
                documento.file.unlink()
            carpetas.add(documento.file.parent)
        for carpeta in carpetas:
            if not any(carpeta.glob("*.json")):
                self._drop_session(carpeta)

    def _drop_session(self, carpeta: Path) -> None:
        bloqueo = self._ajenas.pop(carpeta, None)
        if bloqueo is not None:
            _unlock(bloqueo)
        shutil.rmtree(carpeta, ignore_errors=True)

    def close(self) -> None:
        """Cierre normal: ya no queda nada que recuperar de esta sesión."""
        for bloqueo in self._ajenas.values():
            _unlock(bloqueo)
        self._ajenas.clear()
        if self._lock is not None:
            _unlock(self._lock)
            self._lock = None
        shutil.rmtree(self.folder, ignore_errors=True)
