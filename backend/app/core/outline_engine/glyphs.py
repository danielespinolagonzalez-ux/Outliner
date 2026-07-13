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
# 1) EL ARGUMENTO 'glyph' DE FPDFFont_GetGlyphPath ES EL CODEPOINT UNICODE
#    (no el charcode del content stream ni el GID). pdfium lo resuelve via el
#    cmap Unicode del PROGRAMA de fuente embebido -> GID -> contorno.
#    - En Fase 0 parecia "charcode" porque para la 'H' con encoding estandar
#      charcode == unicode == 72.
#    - Verificado con corpus/remapped.pdf (fuente con /Encoding /Differences que
#      remapea el byte 0x01 -> 'H'): GetGlyphPath(0x01) -> VACIO;
#      GetGlyphPath(0x48 = unicode 'H') -> contorno correcto. O sea, NO usa el
#      Encoding del PDF: usa el unicode contra el cmap del programa de fuente.
#    => El motor pasa SIEMPRE el unicode de FPDFText_GetUnicode(textpage, i).
#       Robusto a subsets remapeados. Caso duro (-> Fase 3): fuentes cuyo
#       programa NO tiene cmap Unicode (algunas CID/simbolicas) -> GetGlyphPath
#       devuelve [] y ese glifo va a fallback (detectable).
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
from typing import Iterator, List, NamedTuple, Tuple

import pypdfium2.raw as pdfium_c

from .geometry import Matrix, glyph_to_page

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


def get_glyph_outline(font_handle, codepoint: int,
                      font_size: float = 1.0) -> List[Subpath]:
    """Contorno de un glifo como lista de subpaths en espacio 'em'.

    `codepoint` es el CODEPOINT UNICODE del caracter (ver punto (1) de la
    cabecera: el arg `glyph` de FPDFFont_GetGlyphPath es el unicode, resuelto por
    el cmap del programa de fuente; NO el charcode del content stream ni el GID).
    Usar FPDFText_GetUnicode(textpage, i). `font_size` se deja en 1.0: la salida
    viene en 'em' con independencia de este valor (Fase 0), y el escalado real lo
    aplica geometry.glyph_to_page.

    Devuelve [] para glifos sin contorno (espacio, o unicode sin cmap -> fallback).
    El llamador mantiene el PDFIUM_LOCK.
    """
    gpath = pdfium_c.FPDFFont_GetGlyphPath(
        font_handle, codepoint, ctypes.c_float(font_size))
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


# ===========================================================================
# EXTRACCION POSICIONADA (textpage-driven) -- Fase 1
# ===========================================================================
# Verificado empiricamente (ver scratchpad/proto_rebuild): reconstruyendo cada
# pagina con estos glifos posicionados y renderizando, el diff de pixeles vs el
# original es ~0.000% a 300 dpi en TODO el corpus (a 150 dpi hay ~1-4% SOLO por
# el hinting TrueType del texto pequeno: pdfium ajusta a rejilla el original y el
# relleno de paths puro no; desaparece al subir dpi). O sea: colocacion y
# contorno son exactos.
#
# Claves del posicionamiento por-glifo (via textpage):
#   - Recorrer indices de char [0, FPDFText_CountChars).
#   - FPDFText_IsGenerated(tp, i) == 1  -> char inyectado por pdfium (p.ej. el
#     '\r\n' entre lineas/objetos): OMITIR (no esta en el content).
#   - FPDFText_GetTextObject(tp, i)     -> objeto de texto due#o (da el font).
#   - unicode = FPDFText_GetUnicode(tp, i)  -> arg de get_glyph_outline.
#   - font_size = FPDFText_GetFontSize(tp, i).
#   - FPDFText_GetMatrix(tp, i) da la orientacion/escala PERO su traslacion (e,f)
#     es el ORIGEN DEL OBJETO (constante dentro del objeto), NO la del glifo.
#     El origen por-glifo (con kerning/TJ ya aplicado) viene de
#     FPDFText_GetCharOrigin(tp, i). Colocacion:
#         placement = glyph_to_page(Matrix(a, b, c, d, ox, oy), font_size)
#   - OJO: FPDFText_GetCharBox es fiable como validador SOLO para texto sin
#     rotacion/cizalla; para glifos rotados pdfium devuelve una caja mas holgada
#     y en otro marco. El validador definitivo es el render (Fase 2), no el bbox.
# ===========================================================================


class PositionedGlyph(NamedTuple):
    """Un glifo posicionado: contorno en 'em' + matriz que lo lleva a pagina."""

    text_index: int                 # indice de char en la textpage
    codepoint: int                  # unicode (FPDFText_GetUnicode)
    char: str
    subpaths: List[Subpath]         # contorno en espacio 'em'
    placement: Matrix               # em -> pagina (incluye font_size)
    fill_rgb: Tuple[int, int, int]
    font_size: float
    render_mode: int


def _char_origin(textpage, i) -> Point:
    x, y = ctypes.c_double(), ctypes.c_double()
    pdfium_c.FPDFText_GetCharOrigin(textpage, i, ctypes.byref(x), ctypes.byref(y))
    return (x.value, y.value)


def _char_matrix(textpage, i) -> Matrix:
    m = pdfium_c.FS_MATRIX()
    pdfium_c.FPDFText_GetMatrix(textpage, i, ctypes.byref(m))
    return Matrix(m.a, m.b, m.c, m.d, m.e, m.f)


def char_box(textpage, i) -> Tuple[float, float, float, float]:
    """Caja del char en coords de pagina (minx, miny, maxx, maxy).

    Fiable como validador solo para texto sin rotacion/cizalla (ver cabecera)."""
    l, r = ctypes.c_double(), ctypes.c_double()
    b, t = ctypes.c_double(), ctypes.c_double()
    pdfium_c.FPDFText_GetCharBox(textpage, i, ctypes.byref(l), ctypes.byref(r),
                                 ctypes.byref(b), ctypes.byref(t))
    return (l.value, b.value, r.value, t.value)


def _is_axis_aligned(m: Matrix) -> bool:
    """True si la matriz no tiene rotacion/cizalla (solo escala+traslacion)."""
    return abs(m.b) < 1e-6 and abs(m.c) < 1e-6


def _safe_chr(codepoint: int) -> str:
    """chr() defensivo: FPDFText_GetUnicode puede devolver 0 (sin unicode) o un
    valor > 0x10FFFF (ToUnicode malformado) que romperia chr()."""
    return chr(codepoint) if 0 < codepoint <= 0x10FFFF else ""


def placement_bbox(glyph: "PositionedGlyph") -> Tuple[float, float, float, float]:
    """BBox en pagina del glifo ya colocado (minx, miny, maxx, maxy)."""
    pts: List[Point] = []
    for sp in glyph.subpaths:
        for cmd in sp:
            if cmd[0] in ("m", "l"):
                pts.append(glyph.placement.apply(cmd[1]))
            elif cmd[0] == "c":
                pts.extend(glyph.placement.apply(p) for p in cmd[1:])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _build_positioned_glyph(textpage, i, obj, font, codepoint, render_mode,
                            subpaths) -> "PositionedGlyph":
    font_size = pdfium_c.FPDFText_GetFontSize(textpage, i)
    ox, oy = _char_origin(textpage, i)
    m = _char_matrix(textpage, i)
    placement = glyph_to_page(Matrix(m.a, m.b, m.c, m.d, ox, oy), font_size)
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    pdfium_c.FPDFPageObj_GetFillColor(
        obj, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a))
    return PositionedGlyph(
        text_index=i,
        codepoint=codepoint,
        char=_safe_chr(codepoint),
        subpaths=subpaths,
        placement=placement,
        fill_rgb=(r.value, g.value, b.value),
        font_size=font_size,
        render_mode=render_mode,
    )


def iter_positioned_glyphs(page_handle, textpage,
                           keep_invisible: bool = False
                           ) -> Iterator["PositionedGlyph"]:
    """Recorre la textpage y devuelve glifos posicionados a nivel de pagina.

    Omite: chars generados por pdfium (\\r\\n entre objetos), texto invisible
    (modo 3, salvo keep_invisible), y glifos sin contorno (espacio, o unicode
    sin cmap -> esos ultimos deben ir a fallback, se detectan aparte con
    analyze_page_glyphs). El llamador mantiene el PDFIUM_LOCK y la page/doc
    vivas (no dejar que el helper PdfPage se recolecte: cierra la page nativa).
    """
    n = pdfium_c.FPDFText_CountChars(textpage)
    for i in range(n):
        if pdfium_c.FPDFText_IsGenerated(textpage, i) == 1:
            continue
        obj = pdfium_c.FPDFText_GetTextObject(textpage, i)
        if not obj:
            continue
        render_mode = pdfium_c.FPDFTextObj_GetTextRenderMode(obj)
        if not keep_invisible and is_invisible(render_mode):
            continue
        codepoint = pdfium_c.FPDFText_GetUnicode(textpage, i)
        font = pdfium_c.FPDFTextObj_GetFont(obj)
        subpaths = get_glyph_outline(font, codepoint, 1.0)
        if not subpaths:
            continue
        yield _build_positioned_glyph(
            textpage, i, obj, font, codepoint, render_mode, subpaths)


class PageGlyphAnalysis(NamedTuple):
    """Resultado de analizar el texto de una pagina para decidir outlineabilidad."""

    glyphs: List["PositionedGlyph"]   # emitibles (fill, con contorno)
    unoutlineable_inked: int          # fill + con ink box pero GetGlyphPath vacio
                                      # (Type3, CID sin cmap...) -> senal de fallback
    non_fill_visible: int             # glifos visibles NO en modo fill (stroke/clip)
    real_chars: int                   # chars no-generados considerados
    non_embedded_fonts: List[str]     # fuentes no incrustadas usadas (-> warning)


def _char_ink_dims(textpage, i) -> Tuple[float, float]:
    box = char_box(textpage, i)  # (minx, miny, maxx, maxy)
    return (box[2] - box[0], box[3] - box[1])


def analyze_page_glyphs(page_handle, textpage,
                        keep_invisible: bool = False) -> "PageGlyphAnalysis":
    """Analiza el texto de la pagina: glifos emitibles + senales de fallback.

    Un glifo cuenta como `unoutlineable_inked` si esta en modo fill, tiene caja de
    tinta no trivial (ancho y alto > 0.1 pt) pero GetGlyphPath devuelve vacio: es
    texto real que NO podemos convertir (Type3, fuente sin cmap Unicode) -> la
    pagina debe ir a fallback. Los espacios (caja degenerada) NO cuentan.
    El llamador mantiene el PDFIUM_LOCK y la page viva.
    """
    glyphs: List["PositionedGlyph"] = []
    unoutlineable = 0
    non_fill = 0
    real = 0
    non_embedded = set()
    n = pdfium_c.FPDFText_CountChars(textpage)
    for i in range(n):
        if pdfium_c.FPDFText_IsGenerated(textpage, i) == 1:
            continue
        obj = pdfium_c.FPDFText_GetTextObject(textpage, i)
        if not obj:
            continue
        real += 1
        render_mode = pdfium_c.FPDFTextObj_GetTextRenderMode(obj)
        invisible = is_invisible(render_mode)
        if invisible and not keep_invisible:
            continue
        if not invisible and render_mode != pdfium_c.FPDF_TEXTRENDERMODE_FILL:
            non_fill += 1  # stroke/fill+stroke/clip visible: no lo sabemos outlinear
            continue
        codepoint = pdfium_c.FPDFText_GetUnicode(textpage, i)
        font = pdfium_c.FPDFTextObj_GetFont(obj)
        subpaths = get_glyph_outline(font, codepoint, 1.0)
        if not subpaths:
            # OJO codepoint==0: sin unicode (CID/simbolica sin cmap). NO es
            # whitespace -> si tiene tinta cuenta como no convertible (antes se
            # colaba en silencio -> perdida de texto). El espacio legitimo se
            # excluye por isspace; la caja de un espacio ROTADO tiene alto no-nulo,
            # por eso se filtra por isspace y no por el tamano de la caja.
            char = _safe_chr(codepoint)
            is_whitespace = bool(char) and char.isspace()
            if not is_whitespace:
                w, h = _char_ink_dims(textpage, i)
                if w > 0.1 and h > 0.1:
                    unoutlineable += 1  # tinta real que no pudimos convertir
            continue
        glyph = _build_positioned_glyph(
            textpage, i, obj, font, codepoint, render_mode, subpaths)
        # Matriz no finita/degenerada (NaN/inf): las comparaciones del self-check
        # con NaN dan False y el glifo se colaria sin validar -> tratarlo como no
        # convertible (defensa; el trigger es raro pero verify_render no siempre
        # cubre un glifo aislado).
        if not glyph.placement.is_finite() or abs(glyph.placement.determinant()) < 1e-9:
            unoutlineable += 1
            continue
        # SELF-CHECK: para texto SIN rotacion/cizalla, el bbox del glifo colocado
        # debe casar con FPDFText_GetCharBox. Si no, el glifo extraido no es el que
        # pdfium dibuja (p.ej. CID Identity-H sin ToUnicode: el unicode del textpage
        # no es el correcto) -> lo tratamos como no convertible para NO corromper en
        # silencio. Los glifos rotados no se validan aqui (GetCharBox no es fiable);
        # el render de fidelidad es el ultimo juez.
        if _is_axis_aligned(glyph.placement):
            bb = placement_bbox(glyph)
            cb = char_box(textpage, i)
            tol = max(1.0, 0.08 * glyph.font_size)
            if max(abs(bb[j] - cb[j]) for j in range(4)) > tol:
                unoutlineable += 1
                continue
        if not pdfium_c.FPDFFont_GetIsEmbedded(font):
            non_embedded.add(_font_base_name(font) or "(sin nombre)")
        glyphs.append(glyph)
    return PageGlyphAnalysis(glyphs, unoutlineable, non_fill, real,
                             sorted(non_embedded))
