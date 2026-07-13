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


def _fontfiles(data):
    n = 0
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for o in pdf.objects:
            try:
                n += sum(1 for k in o.keys()
                         if str(k) in ("/FontFile", "/FontFile2", "/FontFile3"))
            except Exception:
                pass
    return n


# ------------------------- hallazgos de la revision -------------------------
def test_annotation_font_falls_back():
    """Texto/fuente en el appearance stream de una anotacion -> fallback (el
    render no lo detecta porque pinta igual; la fuente sobreviviria al outline)."""
    import sys
    sys.path.insert(0, "backend/tests/outline_engine")
    import gen_corpus
    from pikepdf import Name, Dictionary, Array
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(300, 150))
    font, _ = gen_corpus._embed_simple_font(pdf, gen_corpus.DEJAVU, "annot text", is_cff=False)
    ap = pikepdf.Stream(pdf, b"BT /F1 18 Tf 10 20 Td (annot text) Tj ET")
    ap.Type = Name("/XObject"); ap.Subtype = Name("/Form")
    ap.BBox = Array([0, 0, 120, 30]); ap.Resources = Dictionary(Font=Dictionary(F1=font))
    annot = pdf.make_indirect(Dictionary(
        Type=Name("/Annot"), Subtype=Name("/FreeText"), Rect=Array([10, 100, 130, 130]),
        AP=Dictionary(N=pdf.make_indirect(ap))))
    page.Annots = Array([annot])
    page.Contents = pdf.make_stream(b"")
    out = io.BytesIO(); pdf.save(out); pdf.close()
    result = outline_pdf(out.getvalue(), OutlineOpts())
    assert result.report.pages[0].fallback == "raster"
    assert _fontfiles(result.pdf_bytes) == 0


def test_shared_resources_both_pages_outlined():
    """Dos paginas que comparten un /Resources indirecto: outlinear una no debe
    corromper la otra (copy-on-write). Salida sin fuentes."""
    import sys
    sys.path.insert(0, "backend/tests/outline_engine")
    import gen_corpus
    from pikepdf import Dictionary, Array
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        gen_corpus._embed_simple_font(pdf, gen_corpus.DEJAVU, "Shared AB", is_cff=False)[0])
    shared_res = pdf.make_indirect(Dictionary(Font=Dictionary(F1=font)))
    for txt in (b"BT /F1 24 Tf 20 60 Td (Pagina A) Tj ET",
                b"BT /F1 24 Tf 20 60 Td (Pagina B) Tj ET"):
        pg = pdf.add_blank_page(page_size=(200, 100))
        pg.Resources = shared_res
        pg.Contents = pdf.make_stream(txt)
    out = io.BytesIO(); pdf.save(out); pdf.close()
    result = outline_pdf(out.getvalue(), OutlineOpts())
    assert all(p.outlined for p in result.report.pages)
    assert _fontfiles(result.pdf_bytes) == 0


def _build_cid_rotated_no_tounicode():
    """CID Identity-H SIN ToUnicode y ROTADO: el self-check por-glifo se salta
    (rotacion) -> solo la verificacion por render puede pillar la corrupcion."""
    import math
    import sys
    sys.path.insert(0, "backend/tests/outline_engine")
    from fontTools.ttLib import TTFont as FT
    from fontTools.subset import Subsetter, Options
    from pikepdf import Name, Dictionary, Array
    import gen_corpus
    text = "CID sin unicode 456"  # texto que corrompe de forma fiable
    f = FT(gen_corpus.DEJAVU, recalcTimestamp=False)
    upm = f["head"].unitsPerEm
    o = Options(); o.notdef_outline = True; o.glyph_names = True
    ss = Subsetter(options=o); ss.populate(unicodes=[ord(c) for c in sorted(set(text))]); ss.subset(f)
    cmap = f.getBestCmap(); scale = 1000.0 / upm
    gid = {c: (f.getGlyphID(cmap[ord(c)]) if ord(c) in cmap else 0) for c in sorted(set(text))}
    buf = io.BytesIO(); f.save(buf); prog = buf.getvalue(); head = f["head"]; f.close()
    pdf = pikepdf.new(); page = pdf.add_blank_page(page_size=(360, 200))
    ff = pdf.make_stream(prog); ff.Length1 = len(prog)
    fd = pdf.make_indirect(Dictionary(
        Type=Name("/FontDescriptor"), FontName=Name("/DejaVuSans"), Flags=4,
        FontBBox=Array([round(v * scale) for v in (head.xMin, head.yMin, head.xMax, head.yMax)]),
        ItalicAngle=0, Ascent=759, Descent=-240, CapHeight=729, StemV=80))
    fd[Name("/FontFile2")] = pdf.make_indirect(ff)
    cidf = pdf.make_indirect(Dictionary(
        Type=Name("/Font"), Subtype=Name("/CIDFontType2"), BaseFont=Name("/DejaVuSans"),
        CIDSystemInfo=Dictionary(Registry=pikepdf.String("Adobe"),
                                 Ordering=pikepdf.String("Identity"), Supplement=0),
        FontDescriptor=fd, CIDToGIDMap=Name("/Identity"), DW=600))
    font = pdf.make_indirect(Dictionary(
        Type=Name("/Font"), Subtype=Name("/Type0"), BaseFont=Name("/DejaVuSans"),
        Encoding=Name("/Identity-H"), DescendantFonts=Array([cidf])))
    page.Resources = Dictionary(Font=Dictionary(F1=font))
    hexs = "".join("%04X" % gid[c] for c in text)
    a, b = math.cos(math.radians(20)), math.sin(math.radians(20))
    page.Contents = pdf.make_stream(
        ("q %.5f %.5f %.5f %.5f 40 60 cm BT /F1 22 Tf 0 0 Td <%s> Tj ET Q"
         % (a, b, -b, a, hexs)).encode("latin-1"))
    out = io.BytesIO(); pdf.save(out); pdf.close()
    return out.getvalue()


def test_rotated_cid_no_unicode_falls_back_not_corrupts():
    """CID Identity-H rotado sin ToUnicode: NO debe outlinearse con glifos
    equivocados. Alguna red lo pilla (codepoint 0 / self-check / verificacion por
    render) -> fallback seguro, cero fuentes. Nunca corrupcion silenciosa."""
    data = _build_cid_rotated_no_tounicode()
    result = outline_pdf(data, OutlineOpts())
    pr = result.report.pages[0]
    assert pr.fallback == "raster", "deberia caer a fallback, no outlinear glifos erroneos"
    assert not pr.outlined
    assert _fontfiles(result.pdf_bytes) == 0


def test_render_verification_no_false_fallback_on_correct_pages():
    """La red de verificacion por render NO debe rasterizar paginas correctas
    (a 300 dpi las diferencias legitimas de hinting son ~0)."""
    data = _text_pdf([["Texto normal que se outlinea perfecto 123"]])
    with_verify = outline_pdf(data, OutlineOpts(verify_render=True))
    assert with_verify.report.pages[0].outlined is True
    assert with_verify.report.pages[0].fallback == ""


# ------------------------- hallazgos de la revision FINAL -------------------------
def test_color_set_inside_bt_persists():
    """strip_text solo quita operadores de TEXTO; el color fijado dentro de BT..ET
    (que en PDF persiste tras ET) debe conservarse -> el rectangulo sigue rojo."""
    import sys
    sys.path.insert(0, "backend/tests/outline_engine")
    import gen_corpus
    from pikepdf import Dictionary
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(200, 120))
    font, _ = gen_corpus._embed_simple_font(pdf, gen_corpus.DEJAVU, "Hi", is_cff=False)
    page.Resources = Dictionary(Font=Dictionary(F1=font))
    page.Contents = pdf.make_stream(
        b"q BT 1 0 0 rg /F1 20 Tf 10 90 Td (Hi) Tj ET 10 20 180 30 re f Q")
    out = io.BytesIO(); pdf.save(out); pdf.close()
    result = outline_pdf(out.getvalue(), OutlineOpts())
    doc = pdfium.PdfDocument(result.pdf_bytes)
    arr = np.asarray(doc[0].render(scale=2).to_pil().convert("RGB"))
    doc.close()
    r, g, b = arr[180, 200]  # centro del rectangulo
    assert (int(r), int(g), int(b)) == (255, 0, 0), "el rectangulo perdio el color rojo"


def test_verify_failure_skip_reverts_not_raster():
    """fallback='skip' + fallo de verificacion -> revertir al original, NO rasterizar."""
    data = _build_cid_rotated_no_tounicode()
    result = outline_pdf(data, OutlineOpts(fallback="skip"))
    pr = result.report.pages[0]
    assert pr.fallback == "skip", "skip no debe rasterizar aunque falle la verificacion"
    assert not pr.outlined


def test_annotation_dr_font_removed():
    """Fuente de anotacion resuelta del AcroForm /DR: fallback + AcroForm eliminado
    -> cero fuentes incrustadas en la salida."""
    import sys
    sys.path.insert(0, "backend/tests/outline_engine")
    import gen_corpus
    from pikepdf import Name, Dictionary, Array
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(300, 150))
    drfont, _ = gen_corpus._embed_simple_font(pdf, gen_corpus.DEJAVU, "field value", is_cff=False)
    pdf.Root.AcroForm = Dictionary(Fields=Array([]),
                                   DR=pdf.make_indirect(Dictionary(Font=Dictionary(Helv=drfont))))
    ap = pikepdf.Stream(pdf, b"BT /Helv 12 Tf 2 12 Td (field value) Tj ET")
    ap.Type = Name("/XObject"); ap.Subtype = Name("/Form")
    ap.BBox = Array([0, 0, 100, 20]); ap.Resources = Dictionary()
    annot = pdf.make_indirect(Dictionary(
        Type=Name("/Annot"), Subtype=Name("/Widget"), FT=Name("/Tx"),
        Rect=Array([10, 100, 110, 120]), AP=Dictionary(N=pdf.make_indirect(ap))))
    page.Annots = Array([annot]); page.Contents = pdf.make_stream(b"")
    out = io.BytesIO(); pdf.save(out); pdf.close()
    result = outline_pdf(out.getvalue(), OutlineOpts())
    assert result.report.pages[0].fallback == "raster"
    assert _fontfiles(result.pdf_bytes) == 0


def test_pattern_text_falls_back():
    """Texto dentro de un tiling Pattern -> deteccion -> fallback."""
    import sys
    sys.path.insert(0, "backend/tests/outline_engine")
    import gen_corpus
    from pikepdf import Name, Dictionary, Array
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(200, 120))
    pfont, _ = gen_corpus._embed_simple_font(pdf, gen_corpus.DEJAVU, "Ptext", is_cff=False)
    pat = pikepdf.Stream(pdf, b"BT /PF 10 Tf 2 2 Td (Ptext) Tj ET")
    pat.Type = Name("/Pattern"); pat.PatternType = 1; pat.PaintType = 1; pat.TilingType = 1
    pat.BBox = Array([0, 0, 50, 20]); pat.XStep = 50; pat.YStep = 20
    pat.Resources = Dictionary(Font=Dictionary(PF=pfont))
    page.Resources = Dictionary(Pattern=Dictionary(P1=pdf.make_indirect(pat)))
    page.Contents = pdf.make_stream(b"/Pattern cs /P1 scn 10 10 180 100 re f")
    out = io.BytesIO(); pdf.save(out); pdf.close()
    result = outline_pdf(out.getvalue(), OutlineOpts())
    assert result.report.pages[0].fallback == "raster"
    assert "Pattern" in result.report.pages[0].reason


def test_huge_page_verify_does_not_crash():
    """Pagina enorme (verify OOM): NO debe convertir un outline valido en crash;
    se entrega con warning de 'no verificado'."""
    import sys
    sys.path.insert(0, "backend/tests/outline_engine")
    import gen_corpus
    from pikepdf import Dictionary
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(14400, 14400))
    font, _ = gen_corpus._embed_simple_font(pdf, gen_corpus.DEJAVU, "big", is_cff=False)
    page.Resources = Dictionary(Font=Dictionary(F1=font))
    page.Contents = pdf.make_stream(b"BT /F1 400 Tf 200 200 Td (big page) Tj ET")
    out = io.BytesIO(); pdf.save(out); pdf.close()
    result = outline_pdf(out.getvalue(), OutlineOpts())  # no debe lanzar
    pr = result.report.pages[0]
    assert pr.outlined is True
    assert any("no se pudo verificar" in w for w in pr.warnings)
