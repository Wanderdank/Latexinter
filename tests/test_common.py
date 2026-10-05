"""Procesos externos: que se puedan detener y que no queden vivos."""

import sys
import threading
import time
from pathlib import Path

import pytest

from converters.common import (
    Cancelled,
    CancelToken,
    ConversionError,
    cancellable,
    resolve_output,
    run_command,
)

DORMIR = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_run_command_devuelve_la_salida():
    resultado = run_command([sys.executable, "-c", "print('hola')"])
    assert resultado.returncode == 0
    assert resultado.stdout.strip() == "hola"


def test_cancelar_mata_el_proceso_en_marcha():
    token = CancelToken()
    resultado: dict = {}

    def trabajo():
        inicio = time.monotonic()
        try:
            with cancellable(token):
                run_command(DORMIR)
        except Cancelled:
            resultado["cancelado"] = True
        resultado["segundos"] = time.monotonic() - inicio

    hilo = threading.Thread(target=trabajo)
    hilo.start()
    limite = time.monotonic() + 10
    while not token._procesos and time.monotonic() < limite:
        time.sleep(0.02)
    proceso = next(iter(token._procesos))

    token.cancel()
    hilo.join(15)

    assert not hilo.is_alive()
    assert resultado.get("cancelado")
    assert resultado["segundos"] < 30
    assert proceso.poll() is not None           # el proceso ya no existe


def test_cancelado_antes_de_empezar_no_arranca_el_proceso():
    token = CancelToken()
    token.cancel()
    with cancellable(token), pytest.raises(Cancelled):
        run_command(DORMIR)


def test_sin_token_no_cambia_nada_fuera_del_bloque():
    token = CancelToken()
    with cancellable(token):
        pass
    token.cancel()
    # Fuera del bloque el token ya no afecta a este hilo.
    assert run_command([sys.executable, "-c", "pass"]).returncode == 0


def test_carpeta_de_salida_relativa_se_vuelve_absoluta(tmp_path, monkeypatch):
    # pandoc corre dentro de la carpeta de salida: con una ruta relativa el
    # resultado acababa en «out/out/doc.tex» y la conversión fallaba.
    monkeypatch.chdir(tmp_path)
    destino = resolve_output(Path("doc.pdf"), ".tex", output_dir="out")
    assert destino == tmp_path.resolve() / "out" / "doc.tex"


def test_tiempo_agotado():
    with pytest.raises(ConversionError, match="tardó más de 1 s"):
        run_command(DORMIR, timeout=1)
