"""FASE 0 - Validacion estructural del corpus.

No prueba el motor (aun no existe): comprueba que cada PDF de prueba tiene la
propiedad que lo hace util como fixture (fuente TTF/CFF incrustada, subset, TJ,
CMYK, mixto, no incrustada, Type3). Asi la regeneracion del corpus no rompe
silenciosamente las suposiciones de las fases siguientes.

Todo acceso a pdfium va bajo pdfium_lock. cp1252: ASCII, usar '->'.
"""

import io

import numpy as np
import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as raw

EXPECTED = [
    "latino_ttf.pdf", "latino_cff.pdf", "subset.pdf", "multipos.pdf",
    "color_cmyk.pdf", "mixto.pdf", "no_embebida.pdf", "type3.pdf",
]


# ------------------------- helpers -------------------------
def _iter_fonts(data):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            fonts = dict(pg.get("/Resources", {}).get("/Font", {}))
            for _, fo in fonts.items():
                yield fo


def _embed_keys(fo):
    fd = fo.get("/FontDescriptor")
    dfs = fo.get("/DescendantFonts")
    if dfs is not None:
        fd = dfs[0].get("/FontDescriptor")
    if fd is None:
        return []
    return [k for k in ("/FontFile", "/FontFile2", "/FontFile3") if k in fd]


def _content_bytes(data):
    chunks = []
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            c = pg.Contents
            streams = c if isinstance(c, pikepdf.Array) else [c]
            for s in streams:
                chunks.append(s.read_bytes())
    return b"\n".join(chunks)


def _object_type_counts(data, lock):
    with lock:
        doc = pdfium.PdfDocument(data)
        try:
            ph = doc[0].raw
            counts = {}
            for i in range(raw.FPDFPage_CountObjects(ph)):
                obj = raw.FPDFPage_GetObject(ph, i)
                t = raw.FPDFPageObj_GetType(obj)
                counts[t] = counts.get(t, 0) + 1
            return counts
        finally:
            doc.close()


def _nonblank_pixels(data, lock):
    with lock:
        doc = pdfium.PdfDocument(data)
        try:
            arr = np.asarray(doc[0].render(scale=1.0).to_pil().convert("L"))
            return int((arr < 250).sum())
        finally:
            doc.close()


# ------------------------- tests -------------------------
def test_all_present_and_render(corpus, pdfium_lock):
    for name in EXPECTED:
        assert name in corpus, "falta en el corpus: " + name
        assert _nonblank_pixels(corpus[name], pdfium_lock) > 100, (
            "render en blanco: " + name)


def test_latino_ttf_has_embedded_truetype(corpus):
    keys = [k for fo in _iter_fonts(corpus["latino_ttf.pdf"]) for k in _embed_keys(fo)]
    assert "/FontFile2" in keys, "latino_ttf no incrusta TrueType (FontFile2)"


def test_latino_cff_has_embedded_cff_with_curves(corpus, pdfium_lock):
    keys = [k for fo in _iter_fonts(corpus["latino_cff.pdf"]) for k in _embed_keys(fo)]
    assert "/FontFile3" in keys, "latino_cff no incrusta CFF (FontFile3)"
    with pdfium_lock:
        doc = pdfium.PdfDocument(corpus["latino_cff.pdf"])
        try:
            ph = doc[0].raw
            beziers = -1
            for i in range(raw.FPDFPage_CountObjects(ph)):
                obj = raw.FPDFPage_GetObject(ph, i)
                if raw.FPDFPageObj_GetType(obj) == raw.FPDF_PAGEOBJ_TEXT:
                    font = raw.FPDFTextObj_GetFont(obj)
                    gp = raw.FPDFFont_GetGlyphPath(font, ord("o"), 1.0)
                    n = raw.FPDFGlyphPath_CountGlyphSegments(gp)
                    beziers = sum(
                        1 for k in range(n)
                        if raw.FPDFPathSegment_GetType(
                            raw.FPDFGlyphPath_GetGlyphPathSegment(gp, k)) == 1)
                    break
            assert beziers > 0, "la 'o' CFF no tiene curvas -> revisar extraccion"
        finally:
            doc.close()


def test_subset_has_subset_prefix(corpus):
    bfs = [str(fo.get("/BaseFont")) for fo in _iter_fonts(corpus["subset.pdf"])]
    assert any("+" in bf for bf in bfs), "subset.pdf no muestra prefijo de subset"


def test_multipos_has_tj_and_rotation(corpus, pdfium_lock):
    body = _content_bytes(corpus["multipos.pdf"])
    assert b"TJ" in body, "multipos no usa el operador TJ (kerning)"
    assert b" cm" in body, "multipos no aplica matriz (cm)"
    # algun objeto de texto con matriz no identidad (rotacion/escala)
    with pdfium_lock:
        doc = pdfium.PdfDocument(corpus["multipos.pdf"])
        try:
            import ctypes
            ph = doc[0].raw
            rotated = False
            for i in range(raw.FPDFPage_CountObjects(ph)):
                obj = raw.FPDFPage_GetObject(ph, i)
                if raw.FPDFPageObj_GetType(obj) == raw.FPDF_PAGEOBJ_TEXT:
                    m = raw.FS_MATRIX()
                    raw.FPDFPageObj_GetMatrix(obj, ctypes.byref(m))
                    if abs(m.b) > 1e-3 or abs(m.c) > 1e-3:
                        rotated = True
            assert rotated, "ningun objeto de texto rotado/inclinado en multipos"
        finally:
            doc.close()


def test_color_cmyk_has_nonblack_text(corpus, pdfium_lock):
    import ctypes
    with pdfium_lock:
        doc = pdfium.PdfDocument(corpus["color_cmyk.pdf"])
        try:
            ph = doc[0].raw
            nonblack = False
            for i in range(raw.FPDFPage_CountObjects(ph)):
                obj = raw.FPDFPage_GetObject(ph, i)
                if raw.FPDFPageObj_GetType(obj) == raw.FPDF_PAGEOBJ_TEXT:
                    r, g, b, a = (ctypes.c_uint() for _ in range(4))
                    raw.FPDFPageObj_GetFillColor(
                        obj, ctypes.byref(r), ctypes.byref(g),
                        ctypes.byref(b), ctypes.byref(a))
                    if (r.value, g.value, b.value) != (0, 0, 0):
                        nonblack = True
            assert nonblack, "color_cmyk no tiene texto con color no-negro"
        finally:
            doc.close()


def test_mixto_has_text_image_and_vectors(corpus, pdfium_lock):
    counts = _object_type_counts(corpus["mixto.pdf"], pdfium_lock)
    assert counts.get(raw.FPDF_PAGEOBJ_TEXT, 0) >= 1, "mixto sin texto"
    assert counts.get(raw.FPDF_PAGEOBJ_IMAGE, 0) >= 1, "mixto sin imagen"
    assert counts.get(raw.FPDF_PAGEOBJ_PATH, 0) >= 1, "mixto sin vectores"


def test_no_embebida_has_no_fontfile(corpus):
    keys = [k for fo in _iter_fonts(corpus["no_embebida.pdf"]) for k in _embed_keys(fo)]
    assert keys == [], "no_embebida NO deberia incrustar ninguna fuente: %r" % keys


def test_type3_is_type3(corpus):
    subtypes = [str(fo.get("/Subtype")) for fo in _iter_fonts(corpus["type3.pdf"])]
    assert "/Type3" in subtypes, "type3.pdf no contiene una fuente Type3"
