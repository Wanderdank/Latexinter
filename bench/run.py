"""
run.py - Mide qué tan bien rearma Latexinter las fórmulas de un PDF.

    python -m bench.run                 todos los papers de bench/papers.txt
    python -m bench.run --ocr           lo mismo, con el OCR de fórmulas
    python -m bench.run 2101.00001      solo ese paper
    python -m bench.run --referencia    guarda el resultado como referencia

Para cada paper se baja de arXiv el PDF y el .tex original (bench/cache/), se
convierte el PDF con Latexinter y se compara cada fórmula con la original.

  exactas   fórmulas que salieron idénticas a la original
  parecido  cuánto se parecen de media (100 % = idénticas)
  errores   errores de pdflatex al compilar el .tex convertido

Al final se comparan los totales con bench/referencia.json, para ver si un
cambio en el conversor mejoró o empeoró las cosas.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from bench import arxiv  # noqa: E402
from bench import formulas as fm  # noqa: E402
from converters import ConversionError  # noqa: E402
from converters.pdf_to_latex import pdf_to_latex  # noqa: E402

BENCH = Path(__file__).resolve().parent
CACHE = BENCH / "cache"
PAPERS = BENCH / "papers.txt"
REFERENCIA = BENCH / "referencia.json"
ULTIMO = CACHE / "ultimo.json"

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def leer_papers() -> list[str]:
    ids = []
    for linea in PAPERS.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if linea:
            ids.append(linea)
    return ids


def formulas_de(tex: Path) -> list[fm.Formula]:
    texto = tex.read_text(encoding="utf-8", errors="replace")
    sin_comentarios = fm.strip_comments(texto)
    return fm.extract(fm.expand_macros(sin_comentarios, fm.find_macros(sin_comentarios)))


def convertir(pdf: Path, ocr: bool, reutilizar: bool) -> Path:
    salida = pdf.parent / ("salida-ocr" if ocr else "salida")
    tex = salida / "paper.tex"
    if reutilizar and tex.exists():
        return tex
    if tex.exists():
        tex.unlink()
    # Sin OCR, el conversor deja por defecto las ecuaciones destacadas como
    # imagen y su LaTeX en un comentario: aquí se pide que lo ponga en su
    # sitio, que es lo que se quiere medir.
    pdf_to_latex(pdf, output=tex, math_ocr=ocr, display_equations="latex")
    return tex


def errores_al_compilar(tex: Path) -> tuple[int, str]:
    """
    Cuántos errores da pdflatex con el .tex convertido, y el primero. Un .tex
    con errores suele dar PDF igualmente, pero el usuario tiene que
    arreglarlo a mano.
    """
    try:
        subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex.name],
            cwd=tex.parent, capture_output=True, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)
    registro = tex.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    errores = re.findall(r"^! (.+)$", registro, re.M)
    return len(errores), (errores[0] if errores else "")


def medir_paper(arxiv_id: str, ocr: bool, reutilizar: bool, compilar: bool) -> dict | None:
    try:
        pdf, original = arxiv.descargar(arxiv_id, CACHE)
    except arxiv.SinFuente as exc:
        print(f"  {arxiv_id:<14} se salta: {exc}")
        return None

    inicio = time.monotonic()
    try:
        tex = convertir(pdf, ocr, reutilizar)
    except ConversionError as exc:
        print(f"  {arxiv_id:<14} no se pudo convertir: {exc}")
        return None
    segundos = time.monotonic() - inicio

    originales = formulas_de(original)
    encontradas = formulas_de(tex)
    parejas = fm.match(originales, encontradas)

    por_tipo: dict[str, list[float]] = defaultdict(list)
    for pareja in parejas:
        for tipo in fm.kinds(pareja.original):
            por_tipo[tipo].append(pareja.score)

    errores, primer_error = errores_al_compilar(tex) if compilar else (None, "")

    return {
        "errores_latex": errores,
        "primer_error": primer_error,
        "id": arxiv_id,
        "originales": len(originales),
        "encontradas": len(encontradas),
        "notas": [round(p.score, 4) for p in parejas],
        "por_tipo": {t: notas for t, notas in por_tipo.items()},
        "segundos": round(segundos, 1),
        # Los peores casos, para ver qué falla.
        "peores": [
            {"original": p.original.text, "salio": p.found.text if p.found else None,
             "nota": round(p.score, 3)}
            for p in sorted(parejas, key=lambda p: p.score)[:15]
            if len(p.original.tokens) >= 5
        ],
    }


def _resumen(notas: list[float]) -> tuple[float, float]:
    if not notas:
        return 0.0, 0.0
    exactas = sum(1 for n in notas if n >= 1.0) / len(notas)
    return 100 * exactas, 100 * sum(notas) / len(notas)


def imprimir(resultados: list[dict], referencia: dict | None) -> dict:
    print()
    print(f"  {'paper':<14} {'originales':>10} {'encontradas':>11} {'exactas':>8} "
          f"{'parecido':>9} {'errores':>8} {'tiempo':>7}")
    todas: list[float] = []
    por_tipo: dict[str, list[float]] = defaultdict(list)
    errores = [r["errores_latex"] for r in resultados if r["errores_latex"] is not None]
    for r in resultados:
        exactas, parecido = _resumen(r["notas"])
        error = "—" if r["errores_latex"] is None else r["errores_latex"]
        print(f"  {r['id']:<14} {r['originales']:>10} {r['encontradas']:>11} "
              f"{exactas:>7.1f}% {parecido:>8.1f}% {error:>8} {r['segundos']:>6.0f}s")
        todas.extend(r["notas"])
        for tipo, notas in r["por_tipo"].items():
            por_tipo[tipo].extend(notas)

    exactas, parecido = _resumen(todas)
    totales = {"total": {"formulas": len(todas), "exactas": exactas, "parecido": parecido}}
    if errores:
        totales["total"]["errores_latex"] = sum(errores)
        totales["total"]["papers_sin_errores"] = sum(1 for e in errores if e == 0)
    print(f"  {'TOTAL':<14} {len(todas):>10} {'':>11} {exactas:>7.1f}% {parecido:>8.1f}% "
          f"{sum(errores) if errores else '—':>8}")
    if errores:
        print(f"\n  Compilan sin errores: {totales['total']['papers_sin_errores']} de {len(errores)} papers.")

    print()
    print(f"  {'por tipo':<20} {'fórmulas':>9} {'exactas':>8} {'parecido':>9}")
    for tipo in sorted(por_tipo, key=lambda t: -len(por_tipo[t])):
        notas = por_tipo[tipo]
        exactas, parecido = _resumen(notas)
        totales[tipo] = {"formulas": len(notas), "exactas": exactas, "parecido": parecido}
        cambio = ""
        if referencia and tipo in referencia:
            delta = exactas - referencia[tipo]["exactas"]
            cambio = f"   {delta:+.1f} vs. referencia" if abs(delta) >= 0.05 else "   igual"
        print(f"  {tipo:<20} {len(notas):>9} {exactas:>7.1f}% {parecido:>8.1f}%{cambio}")

    if referencia and "total" in referencia:
        anterior = referencia["total"]
        delta = totales["total"]["exactas"] - anterior["exactas"]
        print(f"\n  Exactas en total: {delta:+.1f} puntos respecto a la referencia.")
        if "errores_latex" in anterior and "errores_latex" in totales["total"]:
            print(f"  Errores de compilación: {anterior['errores_latex']} → "
                  f"{totales['total']['errores_latex']}.")
    return totales


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mide la reconstrucción de fórmulas con papers de arXiv.")
    parser.add_argument("ids", nargs="*", help="IDs de arXiv (por defecto, los de bench/papers.txt)")
    parser.add_argument("--ocr", action="store_true", help="usar el OCR de fórmulas (pix2tex)")
    parser.add_argument("--reutilizar", action="store_true",
                        help="no volver a convertir los PDF ya convertidos")
    parser.add_argument("--referencia", action="store_true",
                        help="guardar este resultado como la nueva referencia")
    parser.add_argument("--sin-compilar", action="store_true",
                        help="no compilar los .tex convertidos (más rápido)")
    args = parser.parse_args(argv)

    ids = args.ids or leer_papers()
    modo = "con OCR" if args.ocr else "sin OCR"
    print(f"Midiendo {len(ids)} papers ({modo})…")

    resultados = []
    for arxiv_id in ids:
        print(f"  {arxiv_id}…", flush=True)
        r = medir_paper(arxiv_id, args.ocr, args.reutilizar, not args.sin_compilar)
        if r:
            resultados.append(r)
    if not resultados:
        print("No se pudo medir ningún paper.")
        return 1

    clave = "ocr" if args.ocr else "sin_ocr"
    referencia = None
    if REFERENCIA.exists() and not args.ids:
        referencia = json.loads(REFERENCIA.read_text(encoding="utf-8")).get(clave)
    totales = imprimir(resultados, referencia)

    CACHE.mkdir(exist_ok=True)
    ULTIMO.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  Detalle (con los peores casos de cada paper): {ULTIMO}")

    if args.referencia:
        guardado = json.loads(REFERENCIA.read_text(encoding="utf-8")) if REFERENCIA.exists() else {}
        guardado[clave] = {t: {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
                           for t, d in totales.items()}
        REFERENCIA.write_text(json.dumps(guardado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  Guardado como referencia: {REFERENCIA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
