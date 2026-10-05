"""
make_icon.py - Dibuja el ícono de Latexinter (assets/latexinter.ico).

    python installer/make_icon.py

Una «L» con una «x» de superíndice sobre un cuadrado morado: lo que mejor
hace el programa es devolver los índices a las fórmulas de un PDF.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "assets" / "latexinter.ico"
LADO = 1024                                  # se dibuja grande y se reduce

MORADO_OSCURO = (76, 46, 214)                # theme.ACENTO, algo más oscuro
MORADO = (109, 74, 255)                      # theme.ACENTO
CIAN = (56, 189, 248)                        # theme.CIAN


def _fuente(tamano: int) -> ImageFont.FreeTypeFont:
    for nombre in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            continue
    raise SystemExit("No hay ninguna fuente en negrita para dibujar el ícono.")


def dibujar() -> Image.Image:
    # Degradado diagonal dentro de un cuadrado de esquinas redondeadas.
    degradado = Image.new("RGB", (LADO, LADO))
    pixeles = degradado.load()
    for y in range(LADO):
        for x in range(LADO):
            t = (x + y) / (2 * LADO - 2)
            pixeles[x, y] = tuple(
                round(a + (b - a) * t) for a, b in zip(MORADO, MORADO_OSCURO)
            )
    mascara = Image.new("L", (LADO, LADO), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        (0, 0, LADO - 1, LADO - 1), radius=LADO * 0.22, fill=255
    )
    icono = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    icono.paste(degradado, mask=mascara)

    lapiz = ImageDraw.Draw(icono)
    lapiz.text((LADO * 0.42, LADO * 0.76), "L", font=_fuente(int(LADO * 0.70)),
               fill="white", anchor="ms")
    lapiz.text((LADO * 0.72, LADO * 0.50), "x", font=_fuente(int(LADO * 0.42)),
               fill=CIAN, anchor="ms")
    return icono


def main() -> None:
    DESTINO.parent.mkdir(exist_ok=True)
    dibujar().save(DESTINO, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    print(f"Listo: {DESTINO}")


if __name__ == "__main__":
    main()
