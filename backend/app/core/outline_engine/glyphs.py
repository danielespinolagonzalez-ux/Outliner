"""Extraccion de glyph paths de PDFium via pypdfium2.raw (ctypes).

La cabecera documenta la conclusion del experimento de coordenadas (Fase 0);
todo el motor depende de ella. Debajo estan las primitivas de extraccion de
Fase 1 (metadatos de objetos de texto + contornos de glifo en espacio 'em').

IMPORTANTE (thread-safety): NINGUNA funcion de este modulo toma el
PDFIUM_LOCK por su cuenta. El llamador DEBE mantener el lock mientras use estas
funciones y mientras vivan los handles de pdfium (doc/page/textpage/font). Ver
_lock.PDFIUM_LOCK y el orden de liberacion en el punto (4) de la cabecera.

cp1252: comentarios/prints en ASCII, usar '->' en vez de flechas.
"""

# ===========================================================================
# CONCLUSION DEL EXPERIMENTO DE COORDENADAS (Fase 0) -- LEER ANTES DE TOCAR
# ===========================================================================
# Todo el motor depende de esto. Verificado EMPIRICAMENTE con:
#     pypdfium2 == 5.11.0   ->   pdfium 151.0.7920.0
# Test que lo reproduce y lo blinda:
#     backend/tests/outline_engine/test_coordinate_space.py
#
# Caso de prueba: una "H" en Helvetica 48pt colocada en (x=100, y=200) pt.
#
# 1) EL ARGUMENTO 'glyph' DE FPDFFont_GetGlyphPath ES EL CHARCODE (no el GID).
#    Pasar el codigo de caracter que la fuente ve en el content stream (para la
#    'H' ASCII simple -> 72) devuelve el contorno correcto (1 subpath con forma
#    de H). pdfium resuelve charcode -> glyph-index internamente usando el
#    encoding / CIDToGIDMap de la fuente. Pasar un GID crudo daria otro glifo.
#    (Para fuentes CID el "charcode" es el codigo propio de la fuente; se
#     re-valida en Fase 1 al enumerar los glifos por objeto de texto.)
#
# 2) EL ESPACIO DE COORDENADAS ES 'em' NORMALIZADO (1.0 == 1 em).
#    Los puntos devueltos NO dependen del argumento font_size en esta version:
#    font_size=1.0 y font_size=48.0 devuelven EXACTAMENTE el mismo bbox
#        (l, b, r, t) = (0.0769, 0.0, 0.6460, 0.7180)
#    y 0.718 == cap-height de la 'H' de Helvetica (718/1000 unidades de fuente).
#    => El motor llama SIEMPRE con font_size=1.0 y escala por el tamano real por
#       su cuenta. Esto es robusto: tanto si una futura version ignora el
#       parametro como si lo respeta, con arg=1.0 la salida queda en 'em'.
#
# 3) COMPOSICION punto_glifo(em) -> punto_pagina(pt):
#        page_point = ObjMatrix . ( font_size * em_point )
#    donde:
#        ObjMatrix = FPDFPageObj_GetMatrix(text_obj)   -> (a, b, c, d, e, f)
#        font_size = FPDFTextObj_GetFontSize(text_obj)
#    O sea: escalar el punto 'em' por font_size y despues aplicar la matriz del
#    objeto de texto (que lleva posicion/rotacion/escala del objeto, pero NO el
#    font_size). En forma de matriz:  GlyphToPage = ObjMatrix x Scale(font_size).
#    Verificado: el bbox transformado casa con FPDFText_GetCharBox dentro de
#    0.005 pt (el test exige <= 1 pt). La composicion alternativa
#    "ObjMatrix . em_point" (sin escalar por font_size) se desvia ~34 pt: MAL.
#
# 4) NO-THREAD-SAFE: toda llamada de arriba va bajo app.core.outline_engine.
#    _lock.PDFIUM_LOCK. Orden de liberacion de handles: paths -> textpage ->
#    page -> document.
# ===========================================================================

import ctypes
from typing import Iterator, List, NamedTuple, Optional, Tuple

import pypdfium2.raw as pdfium_c

from .geometry import Matrix

# Tipos de segmento de glyph path (verificados en el smoke-test de Fase 0).
SEG_LINETO = 0
SEG_BEZIERTO = 1
SEG_MOVETO = 2

# Un subpath es una lista de comandos, en el mismo formato que consume rebuild.py
# (ver PLAN seccion 3.1/3.3). Coordenadas en espacio 'em' (Fase 0):
#   ('m', (x, y))                          -> moveto (abre subpath)
#   ('l', (x, y))                          -> lineto
#   ('c', (x1, y1), (x2, y2), (x3, y3))    -> curva cubica
#   ('h',)                                 -> closepath
Point = Tuple[float, float]
Command = tuple
Subpath = List[Command]


def get_glyph_outline(font_handle, charcode: int,
                      font_size: float = 1.0) -> List[Subpath]:
    """Contorno de un glifo como lista de subpaths en espacio 'em'.

    `charcode` es el codigo de caracter de la fuente (ver Fase 0: el arg `glyph`
    de FPDFFont_GetGlyphPath es el charcode, no el GID). `font_size` se deja en
    1.0: la salida viene en 'em' con independencia de este valor (Fase 0), y el
    escalado real lo aplica geometry.glyph_to_page.

    Devuelve [] para glifos sin contorno (espacio, etc.). El llamador mantiene
    el PDFIUM_LOCK.
    """
    gpath = pdfium_c.FPDFFont_GetGlyphPath(
        font_handle, charcode, ctypes.c_float(font_size))
    if not gpath:
        return []
    n = pdfium_c.FPDFGlyphPath_CountGlyphSegments(gpath)
    subpaths: List[Subpath] = []
    current: Subpath = []
    bezier_buf: List[Point] = []
    for i in range(n):
        seg = pdfium_c.FPDFGlyphPath_GetGlyphPathSegment(gpath, i)
        fx, fy = ctypes.c_float(), ctypes.c_float()
        pdfium_c.FPDFPathSegment_GetPoint(seg, ctypes.byref(fx), ctypes.byref(fy))
        seg_type = pdfium_c.FPDFPathSegment_GetType(seg)
        pt = (fx.value, fy.value)
        if seg_type == SEG_MOVETO:
            if current:
                subpaths.append(current)
            current, bezier_buf = [("m", pt)], []
        elif seg_type == SEG_LINETO:
            current.append(("l", pt))
        elif seg_type == SEG_BEZIERTO:
            bezier_buf.append(pt)
            if len(bezier_buf) == 3:  # cubica completa (control1, control2, destino)
                current.append(("c",) + tuple(bezier_buf))
                bezier_buf = []
        if pdfium_c.FPDFPathSegment_GetClose(seg):
            current.append(("h",))
    if current:
        subpaths.append(current)
    return subpaths


def is_invisible(render_mode: int) -> bool:
    """True si el modo de render de texto es invisible (modo 3, tipico de OCR).

    Estos glifos se omiten del outline por defecto (keep_invisible=False)."""
    return render_mode == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE


class TextObjectInfo(NamedTuple):
    """Metadatos de un objeto de texto a nivel de pagina.

    Los handles (obj, font) son propiedad de la page/document abiertos: solo
    validos mientras vivan y bajo PDFIUM_LOCK.
    """

    index: int
    obj: object            # FPDF_PAGEOBJECT
    font: object           # FPDF_FONT
    font_size: float
    matrix: Matrix         # matriz del objeto (a,b,c,d,e,f); NO incluye font_size
    fill_rgba: Tuple[int, int, int, int]
    render_mode: int       # FPDF_TEXTRENDERMODE_*
    is_embedded: bool
    base_font_name: str


def _font_base_name(font_handle) -> str:
    length = pdfium_c.FPDFFont_GetBaseFontName(font_handle, None, 0)
    if length <= 0:
        return ""
    buf = ctypes.create_string_buffer(length)
    pdfium_c.FPDFFont_GetBaseFontName(font_handle, buf, length)
    return buf.value.decode("latin-1", "replace")


def iter_text_objects(page_handle) -> Iterator[TextObjectInfo]:
    """Recorre los objetos de la pagina y devuelve info de los de texto.

    Solo objetos a NIVEL DE PAGINA (los anidados en Form XObjects llegan en
    Fase 3). El llamador mantiene el PDFIUM_LOCK.
    """
    count = pdfium_c.FPDFPage_CountObjects(page_handle)
    for i in range(count):
        obj = pdfium_c.FPDFPage_GetObject(page_handle, i)
        if pdfium_c.FPDFPageObj_GetType(obj) != pdfium_c.FPDF_PAGEOBJ_TEXT:
            continue

        font = pdfium_c.FPDFTextObj_GetFont(obj)

        size = ctypes.c_float()
        pdfium_c.FPDFTextObj_GetFontSize(obj, ctypes.byref(size))

        mat = pdfium_c.FS_MATRIX()
        pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(mat))

        r, g, b, a = (ctypes.c_uint() for _ in range(4))
        pdfium_c.FPDFPageObj_GetFillColor(
            obj, ctypes.byref(r), ctypes.byref(g),
            ctypes.byref(b), ctypes.byref(a))

        render_mode = pdfium_c.FPDFTextObj_GetTextRenderMode(obj)
        is_embedded = bool(pdfium_c.FPDFFont_GetIsEmbedded(font))

        yield TextObjectInfo(
            index=i,
            obj=obj,
            font=font,
            font_size=size.value,
            matrix=Matrix(mat.a, mat.b, mat.c, mat.d, mat.e, mat.f),
            fill_rgba=(r.value, g.value, b.value, a.value),
            render_mode=render_mode,
            is_embedded=is_embedded,
            base_font_name=_font_base_name(font),
        )


def object_unicode_text(obj, textpage) -> str:
    """Texto Unicode de un objeto de texto (via FPDFTextObj_GetText).

    Requiere una textpage abierta de la misma pagina. Devuelve la cadena sin el
    terminador nulo. El llamador mantiene el PDFIUM_LOCK.
    """
    n_bytes = pdfium_c.FPDFTextObj_GetText(obj, textpage, None, 0)
    if n_bytes <= 2:  # <=2 -> solo el terminador NUL (UTF-16LE) o vacio
        return ""
    buf = ctypes.create_string_buffer(n_bytes)  # UTF-16LE, incluye NUL final
    pdfium_c.FPDFTextObj_GetText(
        obj, textpage,
        ctypes.cast(buf, ctypes.POINTER(pdfium_c.FPDF_WCHAR)), n_bytes)
    return buf.raw[:n_bytes - 2].decode("utf-16-le", "replace")


# NOTA DE ALCANCE (siguiente paso de Fase 1):
# El posicionamiento por-glifo de objetos multi-caracter y el manejo robusto de
# charcode != unicode (subsets remapeados, CID) NO estan aqui todavia. pdfium no
# expone un getter publico del charcode por caracter (solo FPDFText_SetCharcodes;
# hay FPDFText_GetUnicode a nivel de textpage). Para el corpus actual (ASCII/
# latino) charcode == unicode, verificado empiricamente. La colocacion definitiva
# se hara con validacion self-checking (outline transformado vs FPDFText_GetCharBox,
# como en Fase 0) al construir rebuild.py.
