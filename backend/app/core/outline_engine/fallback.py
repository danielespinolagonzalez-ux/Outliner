"""Fallback por rasterizado: paginas/zonas no convertibles -> imagen.

Es PERDIDA de vectorial (el usuario debe saberlo: siempre se marca en el report).
Render con pypdfium2 (bajo PDFIUM_LOCK) -> JPEG -> pagina nueva con la imagen a
pagina completa. Robusto a rotacion: la dimension visual se deriva del propio
render (px / escala), y se resetea /Rotate.

cp1252: ASCII, usar '->'.
"""

import io
from typing import Tuple

import pikepdf
from pikepdf import Dictionary, Name
import pypdfium2 as pdfium

from ._lock import PDFIUM_LOCK

MIN_DPI = 300
DEFAULT_DPI = 600


def render_page_jpeg(pdf_bytes: bytes, page_index: int, dpi: int
                     ) -> Tuple[bytes, int, int]:
    """Renderiza una pagina a JPEG. Devuelve (jpeg, px_w, px_h). Toma el lock."""
    dpi = max(MIN_DPI, int(dpi))
    scale = dpi / 72.0
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_bytes)
        try:
            page = doc[page_index]
            pil = page.render(scale=scale, draw_annots=True).to_pil().convert("RGB")
        finally:
            doc.close()
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=95)
    return buf.getvalue(), pil.width, pil.height


def _visual_size(page: pikepdf.Page) -> Tuple[float, float]:
    """Tamano VISUAL de la pagina en puntos (caja visible + rotacion aplicada).

    pdfium renderiza la CropBox (o MediaBox); se usa la misma para que el raster
    encaje exactamente y el PDF de salida tenga el mismo tamano que el original.
    """
    box = page.get("/CropBox") or page.MediaBox
    x0, y0, x1, y1 = (float(v) for v in box)
    w, h = abs(x1 - x0), abs(y1 - y0)
    rot = int(page.get("/Rotate", 0) or 0) % 360
    return (h, w) if rot in (90, 270) else (w, h)


def rasterize_page(pdf: pikepdf.Pdf, page: pikepdf.Page,
                   pdf_bytes: bytes, page_index: int, dpi: int) -> None:
    """Sustituye la pagina por su render raster (imagen a pagina completa).

    El tamano de salida es el VISUAL del original (misma caja) para no cambiar
    dimensiones. Deja la pagina SIN texto ni fuentes ni anotaciones interactivas
    (las anotaciones con apariencia quedan pintadas en la imagen).
    """
    pt_w, pt_h = _visual_size(page)
    jpeg, px_w, px_h = render_page_jpeg(pdf_bytes, page_index, dpi)

    img = pikepdf.Stream(pdf, jpeg)
    img.Type = Name("/XObject")
    img.Subtype = Name("/Image")
    img.Width = px_w
    img.Height = px_h
    img.ColorSpace = Name("/DeviceRGB")
    img.BitsPerComponent = 8
    img.Filter = Name("/DCTDecode")  # los bytes ya son JPEG

    page.MediaBox = pikepdf.Array([0, 0, round(pt_w, 4), round(pt_h, 4)])
    for extra in ("/CropBox", "/BleedBox", "/TrimBox", "/ArtBox", "/Rotate", "/Annots"):
        if extra in page:
            del page[extra]

    content = ("q %.4f 0 0 %.4f 0 0 cm /OutlinerImg Do Q"
               % (pt_w, pt_h)).encode("latin-1")
    page.Contents = pdf.make_stream(content)
    page.Resources = Dictionary(XObject=Dictionary(OutlinerImg=img))
