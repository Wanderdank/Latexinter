"""
icons.py - Los iconos de la aplicación, dibujados aquí mismo.

Todos comparten trazo y rejilla (16 × 16), así que se ven de la misma familia
y siguen el color del tema. Se pintan con QPainter y no con SVG para no depender
del complemento de imágenes de Qt en la versión empaquetada.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme

_Dibujo = Callable[[QPainter], None]


def _ruta(*tramos: tuple) -> QPainterPath:
    """Una línea por tramos: el primer punto mueve, los demás trazan."""
    camino = QPainterPath()
    for tramo in tramos:
        camino.moveTo(*tramo[0])
        for punto in tramo[1:]:
            camino.lineTo(*punto)
    return camino


def _linea(*tramos: tuple) -> _Dibujo:
    return lambda p: p.drawPath(_ruta(*tramos))


def _hoja(p: QPainter) -> None:
    p.drawPath(_ruta(((9.5, 2), (4, 2), (4, 14), (12, 14), (12, 4.5), (9.5, 2), (9.5, 4.5), (12, 4.5))))


def _nuevo(p: QPainter) -> None:
    _hoja(p)
    p.drawPath(_ruta(((8, 7), (8, 11)), ((6, 9), (10, 9))))


def _carpeta(p: QPainter) -> None:
    p.drawPath(_ruta(((2, 12.5), (2, 3.5), (6.5, 3.5), (8, 5.5), (14, 5.5), (14, 12.5), (2, 12.5))))


def _guardar(p: QPainter) -> None:
    p.drawPath(_ruta(((8, 2.5), (8, 10)), ((5, 7), (8, 10), (11, 7)),
                     ((2.5, 10.5), (2.5, 13.5), (13.5, 13.5), (13.5, 10.5))))


def _compilar(p: QPainter) -> None:
    p.drawPath(_ruta(((5, 3), (12.5, 8), (5, 13), (5, 3))))


def _detener(p: QPainter) -> None:
    p.drawRect(QRectF(4, 4, 8, 8))


def _buscar(p: QPainter) -> None:
    p.drawEllipse(QRectF(2.5, 2.5, 8, 8))
    p.drawPath(_ruta(((9.5, 9.5), (13.5, 13.5))))


def _objetivo(p: QPainter) -> None:
    p.drawEllipse(QRectF(3.5, 3.5, 9, 9))
    p.drawPath(_ruta(((8, 1.5), (8, 5)), ((8, 11), (8, 14.5)), ((1.5, 8), (5, 8)), ((11, 8), (14.5, 8))))


def _externo(p: QPainter) -> None:
    p.drawPath(_ruta(((7, 3), (3, 3), (3, 13), (13, 13), (13, 9)),
                     ((9, 3), (13, 3), (13, 7)), ((13, 3), (7.5, 8.5))))


def _editar(p: QPainter) -> None:
    p.drawPath(_ruta(((3, 13), (3.5, 10), (10.5, 3), (13, 5.5), (6, 12.5), (3, 13)), ((9, 4.5), (11.5, 7))))


def _sol(p: QPainter) -> None:
    p.drawEllipse(QRectF(5, 5, 6, 6))
    p.drawPath(_ruta(((8, 1.5), (8, 3)), ((8, 13), (8, 14.5)), ((1.5, 8), (3, 8)), ((13, 8), (14.5, 8)),
                     ((3.4, 3.4), (4.5, 4.5)), ((11.5, 11.5), (12.6, 12.6)),
                     ((3.4, 12.6), (4.5, 11.5)), ((11.5, 4.5), (12.6, 3.4))))


def _luna(p: QPainter) -> None:
    camino = QPainterPath()
    camino.moveTo(13, 9.5)
    camino.cubicTo(11.5, 13.5, 6.5, 14.5, 3.8, 11.8)
    camino.cubicTo(1, 9, 2.2, 4.2, 6.5, 3)
    camino.cubicTo(5.5, 7, 9, 10.5, 13, 9.5)
    p.drawPath(camino)


def _estrella(p: QPainter) -> None:
    p.drawPath(_ruta(((8, 2), (9.8, 5.9), (14, 6.4), (10.9, 9.3), (11.7, 13.5),
                      (8, 11.4), (4.3, 13.5), (5.1, 9.3), (2, 6.4), (6.2, 5.9), (8, 2))))


def _aviso(p: QPainter) -> None:
    p.drawPath(_ruta(((8, 2.5), (14, 13), (2, 13), (8, 2.5)), ((8, 6.5), (8, 9.5)), ((8, 11), (8, 11.2))))


def _error(p: QPainter) -> None:
    p.drawEllipse(QRectF(2, 2, 12, 12))
    p.drawPath(_ruta(((5.8, 5.8), (10.2, 10.2)), ((10.2, 5.8), (5.8, 10.2))))


def _correcto(p: QPainter) -> None:
    p.drawEllipse(QRectF(2, 2, 12, 12))
    p.drawPath(_ruta(((5, 8.2), (7.2, 10.3), (11, 6))))


def _reloj(p: QPainter) -> None:
    p.drawEllipse(QRectF(2, 2, 12, 12))
    p.drawPath(_ruta(((8, 4.8), (8, 8), (10.2, 9.4))))


_DIBUJOS: dict[str, _Dibujo] = {
    "archivo": _hoja,
    "nuevo": _nuevo,
    "carpeta": _carpeta,
    "guardar": _guardar,
    "compilar": _compilar,
    "detener": _detener,
    "buscar": _buscar,
    "objetivo": _objetivo,
    "externo": _externo,
    "editar": _editar,
    "sol": _sol,
    "luna": _luna,
    "estrella": _estrella,
    "aviso": _aviso,
    "error": _error,
    "correcto": _correcto,
    "reloj": _reloj,
    "cerrar": _linea(((4, 4), (12, 12)), ((12, 4), (4, 12))),
    "marca": _linea(((3.5, 8.5), (6.5, 11.5), (12.5, 4.5))),
    "mas": _linea(((8, 3), (8, 13)), ((3, 8), (13, 8))),
    "menos": _linea(((3, 8), (13, 8))),
    "chevron_abajo": _linea(((4, 6), (8, 10), (12, 6))),
    "chevron_arriba": _linea(((4, 10), (8, 6), (12, 10))),
    "chevron_derecha": _linea(((6, 4), (10, 8), (6, 12))),
}


def _pixmap(nombre: str, color: str, lado: int, escala: float) -> QPixmap:
    pixmap = QPixmap(round(lado * escala), round(lado * escala))
    pixmap.fill(Qt.transparent)
    pincel = QPainter(pixmap)
    pincel.setRenderHint(QPainter.Antialiasing)
    pincel.scale(pixmap.width() / 16, pixmap.height() / 16)
    pincel.setPen(QPen(QColor(color), 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pincel.setBrush(Qt.NoBrush)
    _DIBUJOS[nombre](pincel)
    pincel.end()
    return pixmap


def icono(nombre: str, color: Optional[str] = None, lado: int = 16) -> QIcon:
    color = color or theme.TEXTO_SUAVE
    resultado = QIcon()
    for escala in (1.0, 2.0):
        pixmap = _pixmap(nombre, color, lado, escala)
        pixmap.setDevicePixelRatio(escala)
        resultado.addPixmap(pixmap)
    return resultado


def vacio(lado: int = 16) -> QPixmap:
    """Un hueco del tamaño de un icono, para no mover lo que tiene al lado."""
    pixmap = QPixmap(lado, lado)
    pixmap.fill(Qt.transparent)
    return pixmap


def exportar(nombre: str, color: str, carpeta: Path, lado: int = 16) -> Path:
    """Lo guarda como PNG: la hoja de estilos de Qt solo admite imágenes de archivo."""
    destino = Path(carpeta) / f"{nombre}-{color.lstrip('#')}.png"
    if not destino.exists():
        _pixmap(nombre, color, lado, 2.0).save(str(destino), "PNG")
    return destino
