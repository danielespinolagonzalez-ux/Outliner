"""FASE 0 - Experimento del espacio de coordenadas (BLOQUEANTE).

Descubre y BLINDA el contrato de coordenadas de FPDFFont_GetGlyphPath, del que
depende todo el motor. La conclusion esta documentada en la cabecera de
    backend/app/core/outline_engine/glyphs.py
y este test la reproduce con asserts para que un cambio de version de pdfium la
rompa ruidosamente.

Verificado con pypdfium2 == 5.11.0 -> pdfium 151.0.7920.0.
cp1252: ASCII only, usar '->'.
"""

import ctypes
import io
import math

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from reportlab.pdfgen import canvas

FPDF_SEGMENT_MOVETO = 2
FPDF_SEGMENT_LINETO = 0
FPDF_SEGMENT_BEZIERTO = 1

# Caso conocido: 'H' Helvetica 48pt en (100, 200) pt.
GLYPH_CHAR = "H"
CHARCODE = ord(GLYPH_CHAR)  # 72
POS_X, POS_Y = 100.0, 200.0
FONT_SIZE = 48.0
PLACEMENT_TOL_PT = 1.0  # umbral de casacion con GetCharBox


def _make_single_char_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 400))
    c.setFont("Helvetica", FONT_SIZE)
    c.drawString(POS_X, POS_Y, GLYPH_CHAR)
    c.showPage()
    c.save()
    return buf.getvalue()


def _get_glyph_subpaths(font, glyph, font_size):
    """Extrae subpaths del glifo. Devuelve lista de listas de comandos:
    ('m',(x,y)) | ('l',(x,y)) | ('c',(x1,y1),(x2,y2),(x3,y3)) | ('h',)."""
    gpath = raw.FPDFFont_GetGlyphPath(font, glyph, font_size)
    if not gpath:
        return []
    n = raw.FPDFGlyphPath_CountGlyphSegments(gpath)
    subpaths, current, bez = [], [], []
    for i in range(n):
        seg = raw.FPDFGlyphPath_GetGlyphPathSegment(gpath, i)
        fx, fy = ctypes.c_float(), ctypes.c_float()
        raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(fx), ctypes.byref(fy))
        seg_type = raw.FPDFPathSegment_GetType(seg)
        pt = (fx.value, fy.value)
        if seg_type == FPDF_SEGMENT_MOVETO:
            if current:
                subpaths.append(current)
            current, bez = [("m", pt)], []
        elif seg_type == FPDF_SEGMENT_LINETO:
            current.append(("l", pt))
        elif seg_type == FPDF_SEGMENT_BEZIERTO:
            bez.append(pt)
            if len(bez) == 3:
                current.append(("c",) + tuple(bez))
                bez = []
        if raw.FPDFPathSegment_GetClose(seg):
            current.append(("h",))
    if current:
        subpaths.append(current)
    return subpaths


def _all_points(subpaths):
    pts = []
    for sp in subpaths:
        for cmd in sp:
            if cmd[0] in ("m", "l"):
                pts.append(cmd[1])
            elif cmd[0] == "c":
                pts.extend(cmd[1:])
    return pts


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))  # (minx, miny, maxx, maxy)


def _probe(pdfium_lock):
    """Abre el PDF de la 'H' y devuelve todo lo que el experimento necesita."""
    with pdfium_lock:
        data = _make_single_char_pdf()
        doc = pdfium.PdfDocument(data)
        try:
            page = doc[0]
            page_handle = page.raw

            text_obj = None
            for i in range(raw.FPDFPage_CountObjects(page_handle)):
                obj = raw.FPDFPage_GetObject(page_handle, i)
                if raw.FPDFPageObj_GetType(obj) == raw.FPDF_PAGEOBJ_TEXT:
                    text_obj = obj
                    break
            assert text_obj is not None, "no se encontro objeto de texto"

            font = raw.FPDFTextObj_GetFont(text_obj)
            size = ctypes.c_float()
            raw.FPDFTextObj_GetFontSize(text_obj, ctypes.byref(size))

            mat = raw.FS_MATRIX()
            raw.FPDFPageObj_GetMatrix(text_obj, ctypes.byref(mat))
            obj_matrix = (mat.a, mat.b, mat.c, mat.d, mat.e, mat.f)

            textpage = raw.FPDFText_LoadPage(page_handle)
            unicode0 = raw.FPDFText_GetUnicode(textpage, 0)
            l = ctypes.c_double(); r = ctypes.c_double()
            b = ctypes.c_double(); t = ctypes.c_double()
            raw.FPDFText_GetCharBox(textpage, 0, ctypes.byref(l), ctypes.byref(r),
                                    ctypes.byref(b), ctypes.byref(t))
            char_box = (l.value, b.value, r.value, t.value)  # (minx,miny,maxx,maxy)

            subs_1 = _get_glyph_subpaths(font, CHARCODE, 1.0)
            subs_48 = _get_glyph_subpaths(font, CHARCODE, FONT_SIZE)
            return {
                "font_size": size.value,
                "obj_matrix": obj_matrix,
                "unicode0": unicode0,
                "char_box": char_box,
                "subs_1": subs_1,
                "subs_48": subs_48,
            }
        finally:
            doc.close()


def _apply(matrix, pt):
    a, b, c, d, e, f = matrix
    x, y = pt
    return (a * x + c * y + e, b * x + d * y + f)


def test_glyph_arg_is_charcode(pdfium_lock):
    """(1) FPDFFont_GetGlyphPath acepta el charcode y devuelve la 'H'."""
    data = _probe(pdfium_lock)
    assert data["unicode0"] == CHARCODE, "el textpage no devuelve 'H'"
    subs = data["subs_1"]
    assert len(subs) >= 1, "el charcode no produjo ningun subpath (glyph=charcode?)"
    pts = _all_points(subs)
    assert pts, "subpaths vacios"
    assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts), "puntos no finitos"


def test_coordinate_space_is_normalized_em(pdfium_lock):
    """(2) Los puntos estan en em normalizado y NO dependen del font_size."""
    data = _probe(pdfium_lock)
    bb1 = _bbox(_all_points(data["subs_1"]))
    bb48 = _bbox(_all_points(data["subs_48"]))

    # Estan en unidades em (1.0 == 1 em): cap-height de la 'H' ~0.7 em.
    minx, miny, maxx, maxy = bb1
    assert -0.1 <= minx and maxx <= 1.2, "bbox X fuera de rango em: %r" % (bb1,)
    assert -0.1 <= miny and maxy <= 1.2, "bbox Y fuera de rango em: %r" % (bb1,)
    assert 0.6 <= maxy <= 0.8, "alto de la H no parece cap-height em: %r" % (maxy,)

    # font_size NO escala la salida en esta version -> mismo bbox con 1.0 y 48.0.
    # Si esto falla, el contrato de coordenadas cambio: revisar glyphs.py.
    for a, b in zip(bb1, bb48):
        assert abs(a - b) < 1e-4, (
            "font_size afecta a la geometria devuelta -> el contrato de "
            "coordenadas cambio (bb1=%r bb48=%r)" % (bb1, bb48)
        )


def test_placement_matches_charbox(pdfium_lock):
    """(3) page = ObjMatrix . (font_size * em_point) casa con GetCharBox."""
    data = _probe(pdfium_lock)
    fs = data["font_size"]
    matrix = data["obj_matrix"]
    char_box = data["char_box"]
    em_pts = _all_points(data["subs_1"])

    # Candidato B (correcto): escalar por font_size y aplicar la matriz.
    page_pts_B = [_apply(matrix, (x * fs, y * fs)) for x, y in em_pts]
    bbB = _bbox(page_pts_B)
    diff_B = max(abs(bbB[i] - char_box[i]) for i in range(4))
    assert diff_B <= PLACEMENT_TOL_PT, (
        "composicion B no casa con GetCharBox: diff=%.4f pt bbox=%r charbox=%r"
        % (diff_B, tuple(round(v, 3) for v in bbB), char_box)
    )

    # Candidato A (incorrecto): sin escalar por font_size -> debe fallar claro.
    page_pts_A = [_apply(matrix, (x, y)) for x, y in em_pts]
    bbA = _bbox(page_pts_A)
    diff_A = max(abs(bbA[i] - char_box[i]) for i in range(4))
    assert diff_A > PLACEMENT_TOL_PT, (
        "la composicion sin escalar por font_size tambien casa: revisar hipotesis"
    )
