"""FASE 1 - Tests de glyphs.py (extraccion via pdfium).

Todo acceso a pdfium va bajo pdfium_lock y con orden de liberacion correcto
(textpage -> page -> document). cp1252: ASCII, usar '->'.
"""

import contextlib
import math

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from app.core.outline_engine import glyphs
from app.core.outline_engine.geometry import Matrix


@contextlib.contextmanager
def _open(data, lock):
    """Abre doc + page + textpage y los cierra en orden. Bajo lock."""
    with lock:
        doc = pdfium.PdfDocument(data)
        page = doc[0]
        textpage = raw.FPDFText_LoadPage(page.raw)
        try:
            yield doc, page.raw, textpage
        finally:
            raw.FPDFText_ClosePage(textpage)
            doc.close()


def _all_points(subpaths):
    pts = []
    for sp in subpaths:
        for cmd in sp:
            if cmd[0] in ("m", "l"):
                pts.append(cmd[1])
            elif cmd[0] == "c":
                pts.extend(cmd[1:])
    return pts


def _bbox(subpaths):
    pts = _all_points(subpaths)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _find_object_with_char(page_handle, textpage, char):
    for info in glyphs.iter_text_objects(page_handle):
        if char in glyphs.object_unicode_text(info.obj, textpage):
            return info
    return None


# ------------------------- metadatos -------------------------
def test_iter_text_objects_metadata_latino_ttf(corpus, pdfium_lock):
    with _open(corpus["latino_ttf.pdf"], pdfium_lock) as (_doc, ph, tp):
        infos = list(glyphs.iter_text_objects(ph))
        assert infos, "no se detecto ningun objeto de texto"
        for info in infos:
            assert info.is_embedded is True
            assert "DejaVuSans" in info.base_font_name
            assert info.render_mode == raw.FPDF_TEXTRENDERMODE_FILL
            assert info.font_size > 0
            assert isinstance(info.matrix, Matrix) and info.matrix.is_finite()
            assert info.fill_rgba == (0, 0, 0, 255)  # negro opaco
        assert glyphs.object_unicode_text(infos[0].obj, tp).startswith("Outliner")


def test_embedded_flag_distinguishes_no_embebida(corpus, pdfium_lock):
    with _open(corpus["no_embebida.pdf"], pdfium_lock) as (_doc, ph, _tp):
        infos = list(glyphs.iter_text_objects(ph))
        assert infos and all(info.is_embedded is False for info in infos)
        assert any("Helvetica" in info.base_font_name for info in infos)


# ------------------------- extraccion de contorno -------------------------
def test_extract_H_coherent_with_fase0(corpus, pdfium_lock):
    # 'H' de Helvetica (no incrustada) -> mismo espacio 'em' que Fase 0.
    with _open(corpus["no_embebida.pdf"], pdfium_lock) as (_doc, ph, tp):
        info = _find_object_with_char(ph, tp, "H")
        assert info is not None
        subs = glyphs.get_glyph_outline(info.font, ord("H"), 1.0)
        assert len(subs) >= 1
        pts = _all_points(subs)
        assert pts and all(math.isfinite(x) and math.isfinite(y) for x, y in pts)
        minx, miny, maxx, maxy = _bbox(subs)
        # espacio 'em' (Fase 0): cap-height de la H ~0.72, todo dentro de [-0.1, 1.2]
        assert -0.1 <= minx and maxx <= 1.2
        assert -0.1 <= miny and maxy <= 1.2
        assert 0.6 <= maxy <= 0.8


def test_extract_embedded_ttf_glyph(corpus, pdfium_lock):
    # 'O' de DejaVu incrustada (presente en "Outliner").
    with _open(corpus["latino_ttf.pdf"], pdfium_lock) as (_doc, ph, tp):
        info = _find_object_with_char(ph, tp, "O")
        assert info is not None
        subs = glyphs.get_glyph_outline(info.font, ord("O"), 1.0)
        assert len(subs) >= 1
        assert all(math.isfinite(v) for v in _bbox(subs))


def test_cff_glyph_has_curves_and_counter(corpus, pdfium_lock):
    # 'o' de Source Sans (CFF) -> 2 subpaths (contorno + hueco) con curvas.
    with _open(corpus["latino_cff.pdf"], pdfium_lock) as (_doc, ph, tp):
        info = _find_object_with_char(ph, tp, "o")
        assert info is not None
        subs = glyphs.get_glyph_outline(info.font, ord("o"), 1.0)
        assert len(subs) >= 2, "la 'o' deberia tener contorno + contra-forma"
        beziers = sum(1 for sp in subs for cmd in sp if cmd[0] == "c")
        assert beziers > 0, "la 'o' CFF no tiene curvas cubicas"


def test_space_has_no_outline(corpus, pdfium_lock):
    with _open(corpus["latino_ttf.pdf"], pdfium_lock) as (_doc, ph, _tp):
        info = next(glyphs.iter_text_objects(ph))
        assert glyphs.get_glyph_outline(info.font, ord(" "), 1.0) == []


# ------------------------- color y modo de render -------------------------
def test_fill_color_reflects_cmyk_and_gray(corpus, pdfium_lock):
    with _open(corpus["color_cmyk.pdf"], pdfium_lock) as (_doc, ph, _tp):
        fills = [info.fill_rgba for info in glyphs.iter_text_objects(ph)]
        assert len(fills) >= 2
        # al menos un texto no-negro (CMYK/gris convertido a RGB por pdfium)
        assert any(rgba[:3] != (0, 0, 0) for rgba in fills)
        # los colores no son todos iguales
        assert len({rgba[:3] for rgba in fills}) >= 2


def test_is_invisible_helper():
    assert glyphs.is_invisible(raw.FPDF_TEXTRENDERMODE_INVISIBLE) is True
    assert glyphs.is_invisible(raw.FPDF_TEXTRENDERMODE_FILL) is False


def test_object_unicode_text_roundtrip(corpus, pdfium_lock):
    with _open(corpus["latino_ttf.pdf"], pdfium_lock) as (_doc, ph, tp):
        texts = [glyphs.object_unicode_text(i.obj, tp)
                 for i in glyphs.iter_text_objects(ph)]
        assert any("quick brown fox" in t for t in texts)
