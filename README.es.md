# Latexinter

*[English](README.md) · Español*

[![tests](https://github.com/Wanderdank/Latexinter/actions/workflows/tests.yml/badge.svg)](https://github.com/Wanderdank/Latexinter/actions/workflows/tests.yml)
[![license: AGPL v3](https://img.shields.io/badge/license-AGPL%20v3-blue)](LICENSE)

Un entorno de LaTeX de escritorio. Editor con autocompletado, compilación en
vivo, vista del PDF sincronizada con el código, panel de errores navegable y
conversión entre PDF, LaTeX y Word. Sin navegador y sin subir nada a ningún
sitio: todo ocurre en tu equipo.

![El editor: código, esquema, problemas y el PDF sincronizado](docs/editor.png)

```bash
python app.py
```

## Instalación

**Windows:** baja `Latexinter-…-instalador.exe` de
[la última versión](https://github.com/Wanderdank/Latexinter/releases/latest)
y ábrelo. No pide permisos de administrador y, si faltan MiKTeX o pandoc, los
instala solo. El instalador todavía no está firmado, así que Windows puede
avisar con «Windows protegió su PC»: *Más información* → *Ejecutar de todas
formas*.

**Desde el código:** dos programas externos y tres paquetes de Python:

```bash
winget install --id JohnMacFarlane.Pandoc
```

```bash
winget install --id MiKTeX.MiKTeX
```

```bash
pip install -r requirements.txt
```

Para comprobar que está todo:

```bash
python cli.py deps
```

## El editor

Es la pestaña principal. A la izquierda el esquema y los archivos, en el centro
el código y abajo los problemas; a la derecha, el PDF.

**Escribir**

- Autocompletado de comandos y entornos según escribes (o con `Ctrl+Espacio`).
  `\begin{...}` inserta el entorno con su cierre y la sangría puesta.
- Fragmentos que se insertan enteros: `\figura`, `\tabla`, `\ecuacion`,
  `\align`, `\matriz`, `\casos`, `\codigo`, `\subfigura`…
- Las llaves, los corchetes y los `$` se cierran solos; al pulsar Intro dentro
  de un `\begin{}` aparece el `\end{}`, y dentro de una lista, el `\item`.
- Resaltado que distingue comandos, entornos, matemáticas y comentarios, con
  las fórmulas de varias líneas marcadas de principio a fin.
- `Ctrl+B` negrita, `Ctrl+I` cursiva, `Ctrl+M` modo matemático,
  `Ctrl+7` comentar, `Ctrl+D` duplicar la línea, `Tab` sangrar.
- Buscar y reemplazar con `Ctrl+F` y `Ctrl+H`, con expresiones regulares.
- Los archivos se guardan como estaban: un `.tex` antiguo en Latin-1 o
  Windows-1252 sigue en esa codificación, con sus finales de línea. El guardado
  es atómico (el archivo nunca queda a medias).
- **Recuperación:** lo que no está guardado se copia cada pocos segundos. Si
  Latexinter se cierra de golpe, al volver a abrirlo ofrece recuperarlo.

**Compilar**

- `F5` compila; con **Compilar al escribir** se recompila sola dos segundos
  después de dejar de teclear. `Mayús+F5` detiene la compilación (y mata a
  `pdflatex`, que no se queda colgado en segundo plano).
- El PDF conserva la posición del scroll entre compilaciones, así que el
  documento no salta al principio cada vez.
- Los errores del `.log` salen en el panel inferior con su archivo y su línea:
  al pincharlos, el cursor va allí. Se incluyen los avisos de estilo de
  `chktex` si está instalado.
- Motor elegible entre `pdflatex`, `xelatex` y `lualatex`. Si el documento
  tiene bibliografía, se ejecuta `bibtex` o `biber` y se repiten las pasadas.
- **Documento principal**: al editar un capítulo suelto se sigue compilando el
  maestro. Se marca desde el menú *Compilar*.

**Moverse**

- `F7` lleva del cursor al punto exacto del PDF; un **doble clic en el PDF**
  lleva a la línea del `.tex` que lo generó (SyncTeX en los dos sentidos).
- El esquema lista partes, capítulos, secciones y diapositivas de Beamer.
- Zoom, navegación por páginas y búsqueda de texto dentro del PDF.

**Empezar**

- `Ctrl+N` ofrece plantillas: artículo, informe, presentación (Beamer), tesis,
  carta, currículum y examen, todas con el preámbulo en español ya puesto.

`F1` enseña la lista completa de atajos.

## El conversor

La segunda pestaña.

![El conversor: un PDF convertido a LaTeX, con el código y el resultado compilado](docs/conversor.png)

| Desde | Hacia | Cómo |
|-------|-------|------|
| PDF   | LaTeX | pymupdf4llm extrae la estructura, y Latexinter reconstruye las fórmulas leyendo la maquetación |
| LaTeX | PDF   | pdflatex, con las pasadas necesarias para el índice y las referencias |
| LaTeX | Word  | pandoc, con las ecuaciones editables en el editor de Word |
| Word  | LaTeX | pandoc, con las imágenes y las ecuaciones OMML |

Por defecto el archivo generado se guarda junto al original; si ya existe uno
con ese nombre, se numera (`documento_1.tex`) para no pisar tu trabajo. También
se numera si ya hay un PDF con ese nombre, porque al compilar el `.tex` se
sobrescribiría (convertir `articulo.pdf` da `articulo_1.tex`).

**Vista previa.** Cuando el resultado es un `.tex` (desde Word o desde PDF), el
conversor lo compila al terminar y lo enseña ahí mismo: el código LaTeX a la
izquierda y el PDF a la derecha. Si no compila, el registro dice por qué, y
**Abrir en el editor** lo lleva al editor con el PDF ya cargado para
corregirlo. Se desactiva con la casilla *Compilar y enseñar el resultado*.

### Cómo se recuperan las fórmulas de un PDF

Un PDF no guarda fórmulas: guarda glifos. Un extractor normal devuelve `x2`
tanto para «x por 2» como para «x al cuadrado». Latexinter mira la geometría y
la tipografía para deducir lo que se perdió:

- **Superíndices y subíndices** (`converters/pdfmath.py`) — compara el cuerpo de
  letra y la línea base de cada fragmento con los del resto de la línea, y los
  anida por tamaño: `e⁻ˣ²` se reconstruye como `e^{-x^{2}}`, no como
  `e^{-}^{x}^{2}`.
- **Operadores grandes** — las fuentes matemáticas de TeX guardan la integral en
  la posición de la `Z` y el sumatorio en la de la `X`. Sin traducir esa
  codificación, una integral se extrae del PDF como la letra Z.
- **Ecuaciones destacadas** — el modelo de maquetación de pymupdf4llm marca
  dónde está cada una; es lo mismo que hacen MinerU o PP-Structure: primero
  localizar la región de la fórmula y luego leerla. Latexinter lee cada región
  entera: busca las rayas de fracción entre los gráficos de la página y apila
  lo de encima y lo de debajo en `\frac{…}{…}`. Si el PDF no guarda las rayas
  (los que pasan por Ghostscript, por ejemplo), deduce la fracción de lo que
  queda por encima y por debajo del renglón, como hacen los programas de
  reconocimiento por maquetación (Infty, MaxTract). También cuelga los límites
  de `∑` y `lim` (con `\substack` si son dos renglones), rehace las raíces con
  el `√` y su raya, y devuelve los acentos como `ˆ` a su letra.
- **Alfabetos de las fuentes** — una letra en fuente de pizarra se convierte en
  `\mathbb{E}`, y una caligráfica en `\mathcal{S}`. Se reconocen las fuentes de
  Computer Modern, STIX y newtx.
- **Símbolos Unicode** (`converters/mathfix.py`) — en vez de traducir símbolo a
  símbolo y producir `si $\alpha$ $\leq$ $\beta$`, detecta el tramo matemático
  completo y escribe `si $\alpha \leq \beta$`.

Además se limpian los residuos habituales de un PDF: encabezados repetidos en
cada página, números de página sueltos, el índice con puntos suspensivos (se
cambia por `\tableofcontents`), el logotipo de LaTeX descompuesto en letras y
los niveles de los títulos deducidos de su numeración. Los listados de código,
que el extractor aplasta en un solo párrafo, vuelven como bloques de código con
su sangría y sin los números de línea.

Con los papers del benchmark, el `.tex` que sale compila con pdflatex sin
errores. Los caracteres que el PDF
no asocia a ningún Unicode no se pueden recuperar: se quedan en el código y se
imprimen como `□`, para que sea fácil encontrarlos y corregirlos.

### El OCR, opcional

Con lo anterior, las tres ecuaciones del ejemplo salen bien sin OCR:
`\int_{-\infty}^{\infty}e^{-x^{2}}dx=\sqrt{\pi}`,
`f(x)=\sum_{n=0}^{\infty}\frac{f^{(n)}(a)}{n!}(x-a)^{n}` y el sistema de dos
ecuaciones.

Además se puede leer cada ecuación como imagen con
[Pix2Text-MFR](https://huggingface.co/breezedeus/pix2text-mfr-1.5) (licencia
MIT). Funciona con onnxruntime, que Latexinter ya trae, así que no hace falta
PyTorch; la primera vez descarga el modelo (120 MB) en
`%LOCALAPPDATA%\Latexinter\modelos`. Marca **Reconocer las fórmulas con OCR**
en el conversor, o usa `--ocr`:

```bash
python cli.py pdf2tex articulo.pdf --ocr
```

**Cada método donde gana.** La reconstrucción por maquetación lee los
caracteres exactos del PDF, aunque a veces no sepa colocarlos; el modelo los
coloca bien, pero de vez en cuando se inventa alguno (en las pruebas leyó
`9x+2y=7` donde ponía `3x`). Así que se hacen las dos lecturas y se comparan
sus glifos: la del OCR solo se queda si usa los mismos caracteres que hay en el
PDF. pix2tex y Texify siguen funcionando si están instalados
(`pip install pix2tex`, unos 1,5 GB con PyTorch).

**En el editor** hay además `Ctrl+Shift+V`: recorta una fórmula de donde sea,
cópiala, y se inserta ya convertida a LaTeX en el punto donde esté el cursor.

## Línea de comandos

```bash
python cli.py pdf2tex articulo.pdf --pages 1-6
```

```bash
python cli.py tex2pdf tesis.tex --engine xelatex
```

```bash
python cli.py tex2docx tesis.tex --toc
```

```bash
python cli.py docx2tex informe.docx
```

Y desde PowerShell:

```powershell
.\build.ps1 gui
```

```powershell
.\build.ps1 frompdf -File articulo -Pages "1-6"
```

## Herramientas opcionales

Funcionan sin configurar nada si están en el PATH, y la aplicación sigue
funcionando si no están:

- **synctex** (viene con MiKTeX) — saltar entre el código y el PDF.
- **chktex** (viene con MiKTeX) — avisos de estilo en el panel de problemas.
- **texcount** — recuento de palabras oficial de TeX. En Windows necesita Perl;
  sin él, Latexinter usa su propio contador, que descarta el preámbulo, los
  comentarios, las fórmulas y el código.
- **pix2tex** o **Texify** — otros motores de OCR de fórmulas, en lugar de
  Pix2Text-MFR, que ya viene incluido (`pip install pix2tex`, con PyTorch).

## Estructura

```
app.py                  lanzador
cli.py                  línea de comandos
build.ps1               envoltorio de PowerShell
ui/
    theme.py            colores, tipografías y hoja de estilos
    latex_syntax.py     resaltado, comandos para autocompletar y fragmentos
    latex_editor.py     el editor de código
    pdf_view.py         visor de PDF con zoom, búsqueda y SyncTeX
    panels.py           esquema, problemas, archivos y barra de búsqueda
    templates.py        documentos de partida
    editor_page.py      el entorno de edición completo
    converter_panel.py  el conversor entre formatos
    main_window.py      la ventana que junta todo
converters/
    __init__.py         registro de conversiones y función convert()
    common.py           dependencias, procesos externos, rutas de salida
    textfiles.py        leer y guardar sin estropear, copias de recuperación
    tools.py            synctex, chktex, recuento y análisis del .log
    mathfix.py          Unicode → LaTeX matemático agrupado
    pdfmath.py          reconstrucción de fórmulas desde la maquetación
    mathocr.py          reconocimiento de fórmulas en imagen
    texpost.py          retoques finales del .tex (paquetes, limpieza)
    pdf_to_latex.py     PDF   → LaTeX
    latex_to_pdf.py     LaTeX → PDF
    latex_to_docx.py    LaTeX → Word
    docx_to_latex.py    Word  → LaTeX
tests/                  pruebas (pytest)
ejemplos/               .tex, .pdf y .docx para probar el conversor
bench/                  medición de las fórmulas con papers de arXiv
installer/              instalador de Windows (PyInstaller + Inno Setup)
assets/                 ícono
docs/                   capturas del README
```

## Medir la reconstrucción de fórmulas

```bash
python -m bench.run          # sin OCR
python -m bench.run --ocr    # con el OCR de fórmulas
```

Baja de arXiv los papers de `bench/papers.txt` (PDF y `.tex` original, en
`bench/cache/`, que no se sube), los convierte, compara cada fórmula con la
original y compila el resultado. Saca, por paper y por tipo de fórmula
(índices, fracciones, sumas…), cuántas salieron idénticas, cuánto se parecen y
cuántos errores da pdflatex, y lo compara con `bench/referencia.json`. Con
`--referencia` el resultado pasa a ser la nueva referencia.

## Crear el instalador

Hace falta Python 3.12 y [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`):

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

Deja `dist\Latexinter-<versión>-instalador.exe` (unos 90 MB). Se instala sin
permisos de administrador y, si faltan MiKTeX o pandoc, ofrece instalarlos con
winget. La versión sale de `__version__` en `ui/__init__.py`.

## Pruebas

```bash
pip install pytest
python -m pytest tests -q
```

Las pruebas de la limpieza del texto y de las fórmulas solo necesitan Python.
La de conversión completa (`ejemplos/ejemplo.pdf` → LaTeX) se salta sola si no están
instalados pymupdf4llm y pandoc.

## Licencia

Latexinter se distribuye bajo la [GNU AGPL v3](LICENSE).

Licencias de las dependencias, por si vas a redistribuirlo: PyQt5 es GPL v3;
PyMuPDF y pymupdf4llm son AGPL v3; el modelo Pix2Text-MFR y pix2tex son MIT. Desde la versión 1.27,
pymupdf4llm instala además **pymupdf-layout**, que es *PolyForm
Noncommercial*: se puede usar gratis, pero no con fines comerciales sin una
licencia de Artifex.
