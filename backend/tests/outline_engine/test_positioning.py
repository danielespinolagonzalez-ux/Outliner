"""FASE 1 - Tests de extraccion POSICIONADA (iter_positioned_glyphs).

La colocacion se valida contra FPDFText_GetCharBox SOLO para glifos sin
rotacion/cizalla (para los rotados pdfium devuelve una caja mas holgada; el
validador definitivo es el render de Fase 2, que da ~0% a 300 dpi). Ademas se
prueba la robustez a charcode != unicode con remapped.pdf.

Todo bajo pdfium_lock y con la page viva. cp1252: ASCII, '->'.
"""

import contextlib
import math

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from app.core.outline_engine import glyphs
from app.core.outline_engine.geometry import Matrix


@contextlib.contextmanager
def _open(data, lock):
    with lock:
        doc = pdfium.PdfDocument(data)
        page = doc[0]                     # mantener vivo (si se GC-a cierra la page)
        textpage = raw.FPDFText_LoadPage(page.raw)
        try:
            yield page.raw, textpage
        finally:
            raw.FPDFText_ClosePage(textpage)
            doc.close()


def _is_axis_aligned(m: Matrix) -> bool:
    return abs(m.b) < 1e-6 and abs(m.c) < 1e-6


AXIS_ALIGNED_FILES = [
    "latino_ttf.pdf", "latino_cff.pdf", "subset.pdf", "color_cmyk.pdf",
    "mixto.pdf", "remapped.pdf",
]


def test_axis_aligned_glyphs_land_in_charbox(corpus, pdfium_lock):
    """Cada glifo sin rotacion cae en su GetCharBox dentro de 1 pt."""
    for name in AXIS_ALIGNED_FILES:
        with _open(corpus[name], pdfium_lock) as (ph, tp):
            checked = 0
            for g in glyphs.iter_positioned_glyphs(ph, tp):
                if not _is_axis_aligned(g.placement):
                    continue
                cb = glyphs.char_box(tp, g.text_index)
                bb = glyphs.placement_bbox(g)
                diff = max(abs(bb[j] - cb[j]) for j in range(4))
                assert diff <= 1.0, "%s %r diff=%.3f" % (name, g.char, diff)
                checked += 1
            assert checked > 0, "sin glifos axis-aligned en " + name


def test_multipos_rotated_glyphs_extracted(corpus, pdfium_lock):
    """Rotado + escalado + TJ: se extraen glifos finitos y hay orientacion no-id.

    No se valida el bbox contra GetCharBox (no fiable con rotacion); la fidelidad
    real (render) se cubre en Fase 2.
    """
    with _open(corpus["multipos.pdf"], pdfium_lock) as (ph, tp):
        gs = list(glyphs.iter_positioned_glyphs(ph, tp))
        assert len(gs) > 20
        assert any(not _is_axis_aligned(g.placement) for g in gs), "no hay rotacion"
        for g in gs:
            bb = glyphs.placement_bbox(g)
            assert all(math.isfinite(v) for v in bb)


def test_remapped_font_extracts_correct_glyphs_via_unicode(corpus, pdfium_lock):
    """charcode != unicode: la extraccion por unicode da los glifos correctos."""
    with _open(corpus["remapped.pdf"], pdfium_lock) as (ph, tp):
        gs = list(glyphs.iter_positioned_glyphs(ph, tp))
        assert "".join(g.char for g in gs) == "Hola"
        assert all(g.subpaths for g in gs)


def test_getglyphpath_needs_unicode_not_charcode(corpus, pdfium_lock):
    """Hallazgo clave: en remapped.pdf el charcode del content stream es 0x01
    para 'H'; GetGlyphPath necesita el UNICODE (0x48), no el charcode."""
    with _open(corpus["remapped.pdf"], pdfium_lock) as (ph, _tp):
        info = next(glyphs.iter_text_objects(ph))
        assert glyphs.get_glyph_outline(info.font, 0x01, 1.0) == []
        assert len(glyphs.get_glyph_outline(info.font, ord("H"), 1.0)) >= 1


def test_generated_and_space_skipped(corpus, pdfium_lock):
    """No se emiten espacios ni separadores generados (\\r\\n); todos con contorno."""
    with _open(corpus["latino_ttf.pdf"], pdfium_lock) as (ph, tp):
        gs = list(glyphs.iter_positioned_glyphs(ph, tp))
        assert gs
        assert all(g.char not in (" ", "\r", "\n") for g in gs)
        assert all(g.subpaths for g in gs)


def test_positioned_glyph_fill_color(corpus, pdfium_lock):
    """El color de relleno del glifo refleja el del objeto (CMYK/gris -> RGB)."""
    with _open(corpus["color_cmyk.pdf"], pdfium_lock) as (ph, tp):
        fills = {g.fill_rgb for g in glyphs.iter_positioned_glyphs(ph, tp)}
        assert any(rgb != (0, 0, 0) for rgb in fills)
        assert len(fills) >= 2
