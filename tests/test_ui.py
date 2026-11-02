"""La interfaz sin pantalla: que se monte en los dos temas y que la cola decida bien."""

import os
from pathlib import Path

import pytest

pytest.importorskip("PyQt5")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ui  # noqa: E402,F401  (carga PyMuPDF antes que Qt)
from PyQt5.QtWidgets import QApplication  # noqa: E402

from ui import icons, theme  # noqa: E402
from ui.converter_panel import ConverterPanel, FALLO, LISTO  # noqa: E402
from ui.widgets import Segmented  # noqa: E402


@pytest.fixture(scope="module")
def app():
    aplicacion = QApplication.instance() or QApplication([])
    theme.aplicar(theme.CLARO)
    yield aplicacion
    theme.aplicar(theme.CLARO)


@pytest.fixture
def panel(app, tmp_path):
    vista = ConverterPanel(tmp_path)
    yield vista
    vista.stop()


def _archivo(carpeta: Path, nombre: str) -> Path:
    ruta = carpeta / nombre
    ruta.write_bytes(b"x")
    return ruta


@pytest.mark.parametrize("paleta", [theme.CLARO, theme.OSCURO])
def test_cada_paleta_se_aplica_entera(app, paleta):
    theme.aplicar(paleta)
    assert theme.actual == paleta
    assert theme.FONDO == theme._PALETAS[paleta]["FONDO"]
    assert "{" in theme.hoja_de_estilos()


def test_las_dos_paletas_tienen_los_mismos_colores():
    assert set(theme._PALETAS[theme.CLARO]) == set(theme._PALETAS[theme.OSCURO])


def test_una_preferencia_desconocida_sigue_al_sistema():
    assert theme.resolver(theme.OSCURO) == theme.OSCURO
    assert theme.resolver("cualquiera") in (theme.CLARO, theme.OSCURO)


@pytest.mark.parametrize("nombre", sorted(icons._DIBUJOS))
def test_todos_los_iconos_dibujan_algo(app, nombre):
    imagen = icons.icono(nombre, "#000000").pixmap(16, 16).toImage()
    assert any(
        imagen.pixelColor(x, y).alpha() > 0
        for x in range(imagen.width()) for y in range(imagen.height())
    )


def test_el_segmentado_recuerda_la_opcion_si_sigue_existiendo(app):
    selector = Segmented()
    selector.set_items([("a", "A"), ("b", "B")], "b")
    assert selector.value() == "b"
    selector.set_items([("b", "B"), ("c", "C")], selector.value())
    assert selector.value() == "b"
    selector.set_items([("c", "C")], selector.value())
    assert selector.value() == "c"


def test_sin_documentos_no_se_puede_convertir(panel):
    assert not panel.boton_convertir.isEnabled()


def test_un_pdf_se_convierte_a_word_o_latex(panel, tmp_path):
    panel.add_sources([_archivo(tmp_path, "a.pdf")])
    panel.destino.set_value(".docx")
    panel._refresh_options()
    assert panel.boton_convertir.isEnabled()
    assert panel.boton_convertir.text() == "Convertir a Word"
    assert panel.controles["pages"][0].isVisibleTo(panel)


def test_un_lote_no_ofrece_rango_de_paginas(panel, tmp_path):
    panel.add_sources([_archivo(tmp_path, "a.pdf"), _archivo(tmp_path, "b.pdf")])
    assert "2 documentos" in panel.boton_convertir.text()
    assert not panel.controles["pages"][0].isVisibleTo(panel)


def test_el_mismo_archivo_no_entra_dos_veces(panel, tmp_path):
    ruta = _archivo(tmp_path, "a.pdf")
    panel.add_sources([ruta, ruta])
    panel.add_sources([ruta])
    assert len(panel.trabajos) == 1


def test_sin_destino_comun_se_explica_y_no_se_convierte(panel, tmp_path):
    panel.add_sources([_archivo(tmp_path, n) for n in ("a.pdf", "b.tex", "c.docx")])
    assert panel.sin_destino.isVisibleTo(panel)
    assert not panel.boton_convertir.isEnabled()


def test_quitar_el_elegido_pasa_al_anterior(panel, tmp_path):
    panel.add_sources([_archivo(tmp_path, "a.pdf"), _archivo(tmp_path, "b.pdf")])
    ultimo = panel.trabajos[-1]
    assert panel.elegido is ultimo
    panel._quitar(ultimo)
    assert panel.elegido is panel.trabajos[0]
    panel._quitar(panel.trabajos[0])
    assert panel.elegido is None
    assert panel.derecha.currentIndex() == 0


def test_el_selector_de_paginas_da_el_rango_elegido(app):
    fitz = pytest.importorskip("fitz")
    from ui.page_picker import PagePickerDialog

    ruta = Path(__file__).resolve().parent.parent / "ejemplos" / "ejemplo.pdf"
    paginas = fitz.open(str(ruta)).page_count
    assert paginas == 4

    dialogo = PagePickerDialog(ruta, "1,3-4")
    assert dialogo.selection() == "1,3-4"
    assert dialogo.resumen.text() == "3 de 4 páginas"
    dialogo.lista.selectAll()
    assert dialogo.selection() == ""        # todas: no hace falta decir cuáles
    dialogo.lista.clearSelection()
    assert not dialogo.botones.button(dialogo.botones.Ok).isEnabled()
    dialogo.reject()


def test_un_fallo_no_para_la_cola(panel, tmp_path, monkeypatch):
    """El primero falla, el segundo sigue; ninguno se queda a medias."""
    import ui.converter_panel as modulo
    from converters import ConversionError

    def falla(*_args, **_kwargs):
        raise ConversionError("no se pudo")

    monkeypatch.setattr(modulo, "convert", falla)
    panel.opcion_vista_previa.setChecked(False)
    panel.add_sources([_archivo(tmp_path, "a.pdf"), _archivo(tmp_path, "b.pdf")])
    panel.destino.set_value(".tex")
    panel.start_conversion()

    from PyQt5.QtCore import QEventLoop, QTimer

    espera = QEventLoop()
    reloj = QTimer()
    reloj.timeout.connect(lambda: None if panel.is_converting() else espera.quit())
    reloj.start(20)
    QTimer.singleShot(10000, espera.quit)
    espera.exec_()

    assert not panel.is_converting()
    assert [t.estado for t in panel.trabajos] == [FALLO, FALLO]
    assert all("no se pudo" in t.error for t in panel.trabajos)
    assert LISTO not in [t.estado for t in panel.trabajos]
    assert panel.boton_convertir.isVisibleTo(panel)
