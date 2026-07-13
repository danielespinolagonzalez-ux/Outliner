"""FASE 2 - Test de fidelidad e2e: render antes vs despues del outline.

El validador que manda. Se renderiza a 300 dpi (no 150): a 150 dpi el hinting
TrueType del texto pequeno mete 1-4% de diff legitimo que desaparece al subir
resolucion (ver cabecera de glyphs.py). Umbral: <= 0.5% de pixeles distintos.

Ademas: el PDF de salida no debe tener NINGUNA fuente incrustada ni texto
extraible. cp1252: ASCII, usar '->'.
"""

import io

import numpy as np
import pikepdf
import pypdfium2 as pdfium
import pytest

from app.core.outline_engine import (
    FALLBACK_ERROR,
    FALLBACK_SKIP,
    OutlineOpts,
    UnsupportedContentError,
    outline_pdf,
)

FIDELITY_DPI = 300
DIFF_THRESHOLD = 0.005       # 0.5% para outline vectorial
FALLBACK_DIFF_THRESHOLD = 0.015  # raster (JPEG) es con perdida -> mas holgado

# Todo el corpus salvo casos duros de fallback.
OUTLINEABLE = [
    "latino_ttf.pdf", "latino_cff.pdf", "subset.pdf", "multipos.pdf",
    "color_cmyk.pdf", "mixto.pdf", "no_embebida.pdf", "remapped.pdf",
    "cid.pdf",
]
FALLBACK_CASES = ["type3.pdf", "cid_no_unicode.pdf"]


# ----------------------------- helpers -----------------------------
def _render_gray(data, page_index=0, dpi=FIDELITY_DPI):
    doc = pdfium.PdfDocument(data)
    try:
        pil = doc[page_index].render(scale=dpi / 72).to_pil().convert("L")
        return np.asarray(pil, dtype=np.int16)
    finally:
        doc.close()


def _pixel_diff_ratio(pdf_a, pdf_b, page_index=0, dpi=FIDELITY_DPI):
    a = _render_gray(pdf_a, page_index, dpi)
    b = _render_gray(pdf_b, page_index, dpi)
    assert a.shape == b.shape, "la pagina cambio de tamano: %s vs %s" % (a.shape, b.shape)
    return float(np.mean(np.abs(a - b) > 8))


def _embedded_font_files(data):
    """Cuenta streams FontFile/FontFile2/FontFile3 en TODO el PDF."""
    count = 0
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for obj in pdf.objects:
            try:
                keys = [str(k) for k in obj.keys()]
            except Exception:
                continue
            count += sum(1 for k in keys if k in ("/FontFile", "/FontFile2", "/FontFile3"))
    return count


def _page_fonts(data):
    total = 0
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            total += len(dict(pg.get("/Resources", {}).get("/Font", {})))
    return total


def _extractable_text(data, page_index=0):
    doc = pdfium.PdfDocument(data)
    try:
        return doc[page_index].get_textpage().get_text_range().strip()
    finally:
        doc.close()


# ----------------------------- fidelidad -----------------------------
@pytest.mark.parametrize("name", OUTLINEABLE)
def test_outlined_fidelity_and_no_fonts(name, corpus):
    original = corpus[name]
    result = outline_pdf(original, OutlineOpts())
    out = result.pdf_bytes

    ratio = _pixel_diff_ratio(original, out)
    assert ratio <= DIFF_THRESHOLD, "%s diff=%.4f%% > %.2f%%" % (
        name, ratio * 100, DIFF_THRESHOLD * 100)

    assert _page_fonts(out) == 0, "%s deja fuentes en /Resources" % name
    assert _embedded_font_files(out) == 0, "%s deja programas de fuente incrustados" % name
    assert result.report.pages[0].outlined is True
    assert result.report.pages[0].outlined_glyphs > 0


@pytest.mark.parametrize("name", OUTLINEABLE)
def test_outlined_text_not_extractable(name, corpus):
    result = outline_pdf(corpus[name], OutlineOpts())
    assert _extractable_text(result.pdf_bytes) == "", (
        "%s: el texto sigue siendo extraible tras el outline" % name)


def test_no_embebida_warns_about_substitution(corpus):
    result = outline_pdf(corpus["no_embebida.pdf"], OutlineOpts())
    warns = result.report.pages[0].warnings
    assert warns and any("no incrustada" in w for w in warns)
    assert result.report.pages[0].outlined is True


# ----------------------------- fallback -----------------------------
@pytest.mark.parametrize("name", FALLBACK_CASES)
def test_fallback_raster(name, corpus):
    original = corpus[name]
    result = outline_pdf(original, OutlineOpts(fallback="raster", raster_dpi=600))
    out = result.pdf_bytes
    pr = result.report.pages[0]
    assert pr.fallback == "raster" and pr.reason
    assert _page_fonts(out) == 0 and _embedded_font_files(out) == 0
    # el raster debe parecerse al original (perdida de vectorial, no de contenido)
    assert _pixel_diff_ratio(original, out) <= FALLBACK_DIFF_THRESHOLD
    assert result.report.any_fallback is True
    assert 0 in result.report.fallback_pages


def test_fallback_error_raises(corpus):
    with pytest.raises(UnsupportedContentError) as exc:
        outline_pdf(corpus["type3.pdf"], OutlineOpts(fallback=FALLBACK_ERROR))
    assert exc.value.page_index == 0
    assert "Type3" in exc.value.reason


def test_fallback_skip_leaves_page(corpus):
    result = outline_pdf(corpus["type3.pdf"], OutlineOpts(fallback=FALLBACK_SKIP))
    pr = result.report.pages[0]
    assert pr.fallback == "skip" and not pr.outlined
    # skip deja la pagina como estaba (documentado: puede conservar la fuente)


# ----------------------------- report -----------------------------
def test_report_to_dict(corpus):
    result = outline_pdf(corpus["mixto.pdf"], OutlineOpts())
    d = result.report.to_dict()
    assert d["engine"] == "internal"
    assert d["pages"][0]["outlined"] is True
    assert d["total_outlined_glyphs"] > 0
    assert d["any_fallback"] is False
