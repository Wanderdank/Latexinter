"""Leer y guardar sin estropear los archivos, y las copias de recuperación."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from converters.textfiles import (
    RecoveryStore,
    TextFormat,
    decode_source,
    read_source,
    write_source,
)

RAIZ = Path(__file__).resolve().parent.parent


def _ida_y_vuelta(tmp_path: Path, datos: bytes) -> tuple[str, TextFormat, bytes]:
    archivo = tmp_path / "doc.tex"
    archivo.write_bytes(datos)
    texto, formato = read_source(archivo)
    write_source(archivo, texto, formato)
    return texto, formato, archivo.read_bytes()


def test_utf8_con_lf_queda_igual(tmp_path):
    datos = "Año\nñandú\n".encode("utf-8")
    texto, formato, guardado = _ida_y_vuelta(tmp_path, datos)
    assert texto == "Año\nñandú\n"
    assert formato == TextFormat("utf-8", "\n")
    assert guardado == datos


def test_crlf_se_conserva(tmp_path):
    datos = "uno\r\ndos\r\n".encode("utf-8")
    texto, formato, guardado = _ida_y_vuelta(tmp_path, datos)
    assert texto == "uno\ndos\n"
    assert formato.newline == "\r\n"
    assert guardado == datos


def test_latin1_no_se_convierte_en_simbolos_raros(tmp_path):
    datos = "\\usepackage[latin1]{inputenc}\nAño y canción\n".encode("latin-1")
    texto, formato, guardado = _ida_y_vuelta(tmp_path, datos)
    assert "Año y canción" in texto
    assert formato.encoding == "latin-1"
    assert guardado == datos


def test_cp1252_sin_declarar(tmp_path):
    datos = "Precio: 5 € — “comillas”\n".encode("cp1252")
    texto, formato, guardado = _ida_y_vuelta(tmp_path, datos)
    assert texto == "Precio: 5 € — “comillas”\n"
    assert formato.encoding == "cp1252"
    assert guardado == datos


def test_bom_se_conserva(tmp_path):
    datos = "\ufeffHola\n".encode("utf-8")
    texto, formato, guardado = _ida_y_vuelta(tmp_path, datos)
    assert texto == "Hola\n"
    assert guardado == datos


def test_bytes_imposibles_no_se_pierden():
    # 0x81 no existe en Windows-1252: queda Latin-1, que guarda cualquier byte.
    texto, formato = decode_source(b"a\x81b")
    assert formato.encoding == "latin-1"
    assert texto.encode("latin-1") == b"a\x81b"


def test_caracter_que_no_cabe_no_toca_el_archivo(tmp_path):
    archivo = tmp_path / "doc.tex"
    archivo.write_bytes("Año\n".encode("latin-1"))
    with pytest.raises(UnicodeEncodeError):
        write_source(archivo, "Año → flecha\n", TextFormat("latin-1"))
    assert archivo.read_bytes() == "Año\n".encode("latin-1")
    assert [p.name for p in tmp_path.iterdir()] == ["doc.tex"]


def test_guardar_no_deja_temporales(tmp_path):
    archivo = tmp_path / "doc.tex"
    write_source(archivo, "uno\n")
    write_source(archivo, "dos\n")
    assert archivo.read_text(encoding="utf-8") == "dos\n"
    assert [p.name for p in tmp_path.iterdir()] == ["doc.tex"]


# ── Copias de recuperación ──────────────────────────────────

def test_una_sesion_abierta_no_se_ofrece_para_recuperar(tmp_path):
    viva = RecoveryStore(tmp_path)
    viva.save("a", tmp_path / "doc.tex", "sin guardar")
    otra = RecoveryStore(tmp_path)
    try:
        assert otra.orphans() == []
    finally:
        viva.close()
        otra.close()


def test_cierre_normal_no_deja_nada(tmp_path):
    sesion = RecoveryStore(tmp_path)
    sesion.save("a", None, "borrador")
    sesion.close()
    nueva = RecoveryStore(tmp_path)
    try:
        assert nueva.orphans() == []
    finally:
        nueva.close()
    assert list(tmp_path.iterdir()) == []


def test_lo_que_deja_una_sesion_que_muere_se_recupera(tmp_path):
    # Un proceso que guarda una copia y acaba sin cerrar la sesión: como un
    # cierre inesperado de la aplicación.
    codigo = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(RAIZ)!r})
        from pathlib import Path
        from converters.textfiles import RecoveryStore, TextFormat
        sesion = RecoveryStore(Path({str(tmp_path)!r}))
        sesion.save("a", Path({str(tmp_path / "tesis.tex")!r}), "Año\\n", TextFormat("latin-1", "\\r\\n"))
        sesion.save("b", None, "borrador")
    """)
    subprocess.run([sys.executable, "-c", codigo], check=True)

    sesion = RecoveryStore(tmp_path)
    try:
        documentos = sesion.orphans()
        assert sorted(d.text for d in documentos) == ["Año\n", "borrador"]
        tesis = next(d for d in documentos if d.path is not None)
        assert tesis.path == tmp_path / "tesis.tex"
        assert tesis.format == TextFormat("latin-1", "\r\n")

        # Otra ventana que arranque a la vez no ofrece lo mismo.
        otra = RecoveryStore(tmp_path)
        assert otra.orphans() == []
        otra.close()

        sesion.forget(documentos)
        assert sesion.orphans() == []
    finally:
        sesion.close()
    assert list(tmp_path.iterdir()) == []
