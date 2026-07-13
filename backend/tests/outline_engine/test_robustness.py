"""FASE 3 - Robustez: rotacion, multipagina, cifrado, corrupto, OCR invisible,
stroke. PDFs construidos al vuelo. cp1252: ASCII, usar '->'.
"""

import io

import numpy as np
import pikepdf
import pypdfium2 as pdfium
import pytest
from reportlab import rl_config
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.core.outline_engine import (
    CorruptPdfError,
    EncryptedPdfError,
    OutlineOpts,
    outline_pdf,
)

rl_config.invariant = 1
_DV = "backend/tests/outline_engine/corpus/_fonts/DejaVuSans.ttf"


@pytest.fixture(scope="module", autouse=True)
def _register_font():
    if "DVrobust" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DVrobust", _DV))


def _text_pdf(lines_per_page, pagesize=(300, 200), size=24, mode=0):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    for lines in lines_per_page:
        t = c.beginText(30, pagesize[1] - 60)
        t.setFont("DVrobust", size)
        t.setTextRenderMode(mode)
        if mode in (1, 2):
            c.setStrokeColorRGB(0, 0, 0)
            c.setLineWidth(0.8)
        for ln in lines:
            t.textLine(ln)
        c.drawText(t)
        c.showPage()
    c.save()
    return buf.getvalue()


def _fonts(data, page=0):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return len(dict(pdf.pages[page].get("/Resources", {}).get("/Font", {})))


def _text(data, page=0):
    doc = pdfium.PdfDocument(data)
    try:
        return doc[page].get_textpage().get_text_range().strip()
    finally:
        doc.close()


def _diff(a, b, page=0, dpi=300):
    def r(d):
        doc = pdfium.PdfDocument(d)
        try:
            return np.asarray(doc[page].render(scale=dpi / 72).to_pil().convert("L"),
                              dtype=np.int16)
        finally:
            doc.close()
    ra, rb = r(a), r(b)
    assert ra.shape == rb.shape, "%s vs %s" % (ra.shape, rb.shape)
    return float(np.mean(np.abs(ra - rb) > 8))


# ------------------------- rotacion / multipagina -------------------------
def test_rotated_page_outlines():
    base = _text_pdf([["Rotated page test"]], pagesize=(400, 300), size=30)
    pdf = pikepdf.open(io.BytesIO(base))
    pdf.pages[0].Rotate = 90
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    rotated = out.getvalue()
    result = outline_pdf(rotated, OutlineOpts())
    assert result.report.pages[0].outlined is True
    assert _fonts(result.pdf_bytes) == 0
    assert _diff(rotated, result.pdf_bytes) <= 0.005


def test_multipage_all_outlined():
    data = _text_pdf([["Pagina UNO"], ["Pagina DOS"], ["Pagina TRES"]])
    result = outline_pdf(data, OutlineOpts())
    assert len(result.report.pages) == 3
    for i in range(3):
        assert result.report.pages[i].outlined is True
        assert _fonts(result.pdf_bytes, i) == 0
        assert _diff(data, result.pdf_bytes, i) <= 0.005


# ------------------------- cifrado / corrupto -------------------------
def _encrypt(data, user="u", owner="o"):
    pdf = pikepdf.open(io.BytesIO(data))
    out = io.BytesIO()
    pdf.save(out, encryption=pikepdf.Encryption(owner=owner, user=user, R=4))
    pdf.close()
    return out.getvalue()


def test_encrypted_without_password_raises():
    enc = _encrypt(_text_pdf([["secreto"]]))
    with pytest.raises(EncryptedPdfError):
        outline_pdf(enc, OutlineOpts())


def test_encrypted_with_password_outlines():
    enc = _encrypt(_text_pdf([["secreto"]]))
    result = outline_pdf(enc, OutlineOpts(password="u"))
    assert result.report.pages[0].outlined is True
    assert _fonts(result.pdf_bytes) == 0


def test_corrupt_pdf_raises():
    with pytest.raises(CorruptPdfError):
        outline_pdf(b"%PDF-1.7 esto no es un pdf valido", OutlineOpts())


# ------------------------- OCR invisible / stroke -------------------------
def test_invisible_ocr_text_removed_image_kept():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 80), (200, 220, 255))
    ImageDraw.Draw(img).rectangle([10, 10, 60, 60], fill=(180, 60, 60))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(220, 100))
    c.drawImage(ImageReader(img), 10, 10, 200, 80)
    t = c.beginText(20, 50)
    t.setFont("DVrobust", 20)
    t.setTextRenderMode(3)  # invisible (OCR)
    t.textOut("hidden ocr layer")
    c.drawText(t)
    c.showPage()
    c.save()
    ocr = buf.getvalue()
    assert _text(ocr) != ""  # el original tiene texto invisible
    result = outline_pdf(ocr, OutlineOpts())
    assert _text(result.pdf_bytes) == ""      # texto invisible eliminado
    assert _fonts(result.pdf_bytes) == 0
    assert _diff(ocr, result.pdf_bytes) <= 0.005  # imagen intacta


def test_stroke_text_falls_back():
    strk = _text_pdf([["Stroke"]], pagesize=(300, 120), size=30, mode=1)
    result = outline_pdf(strk, OutlineOpts(fallback="raster"))
    pr = result.report.pages[0]
    assert pr.fallback == "raster"
    assert "no-fill" in pr.reason
    assert _fonts(result.pdf_bytes) == 0


# ------------------------- casos borde -------------------------
def test_blank_page_passthrough():
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    result = outline_pdf(out.getvalue(), OutlineOpts())
    assert result.report.pages[0].outlined is False
    assert not result.report.pages[0].fallback


def test_path_input(tmp_path):
    src = _text_pdf([["desde fichero"]])
    p = tmp_path / "in.pdf"
    p.write_bytes(src)
    result = outline_pdf(str(p), OutlineOpts())
    assert result.report.pages[0].outlined is True
    assert _fonts(result.pdf_bytes) == 0


def test_report_json_serializable():
    import json
    result = outline_pdf(_text_pdf([["hola"]]), OutlineOpts())
    # el report debe serializar a JSON (lo que devuelve el endpoint)
    json.dumps(result.report.to_dict())
