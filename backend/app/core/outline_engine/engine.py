"""Orquestador del motor outliner: outline_pdf(bytes|path, opts) -> OutlineResult.

Flujo (dos pasadas, para no mantener el PDFIUM_LOCK durante la reescritura pikepdf):
  1. pdfium (bajo lock): por pagina, analizar el texto (glifos posicionados +
     senales de outlineabilidad). Los resultados son Python puro (sin handles),
     asi que sobreviven al cierre del documento pdfium.
  2. pikepdf (sin lock; el render de fallback toma el lock internamente): por
     pagina, si es outlineable -> reescribir (texto a paths, quitar fuentes); si
     no -> fallback (raster / skip / error) segun opts.

cp1252: ASCII, usar '->'.
"""

import io
import os
from dataclasses import dataclass, field
from typing import List, Optional, Union

import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from ._lock import PDFIUM_LOCK
from .errors import CorruptPdfError, EncryptedPdfError, UnsupportedContentError
from .glyphs import PageGlyphAnalysis, analyze_page_glyphs
from .fallback import DEFAULT_DPI, rasterize_page
from .rebuild import (
    page_has_xobject_text,
    page_type3_font_names,
    rebuild_page,
)
from .report import OutlineReport, PageReport

FALLBACK_RASTER = "raster"
FALLBACK_SKIP = "skip"
FALLBACK_ERROR = "error"


@dataclass
class OutlineOpts:
    fallback: str = FALLBACK_RASTER      # "raster" | "skip" | "error"
    raster_dpi: int = DEFAULT_DPI
    keep_invisible: bool = False
    password: Optional[str] = None


@dataclass
class OutlineResult:
    pdf_bytes: bytes
    report: OutlineReport


def _read_bytes(data: Union[bytes, bytearray, str, os.PathLike]) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    with open(data, "rb") as fh:
        return fh.read()


def _open_pdfium(pdf_bytes: bytes, password: Optional[str]) -> "pdfium.PdfDocument":
    try:
        return pdfium.PdfDocument(pdf_bytes, password=password)
    except pdfium.PdfiumError as exc:
        msg = str(exc).lower()
        if "password" in msg or "encrypt" in msg:
            raise EncryptedPdfError(str(exc)) from exc
        raise CorruptPdfError(str(exc)) from exc


def _analyze_all_pages(pdf_bytes: bytes, opts: OutlineOpts) -> List[PageGlyphAnalysis]:
    analyses: List[PageGlyphAnalysis] = []
    with PDFIUM_LOCK:
        doc = _open_pdfium(pdf_bytes, opts.password)
        try:
            for i in range(len(doc)):
                page = doc[i]  # mantener vivo hasta cerrar la textpage
                textpage = pdfium_c.FPDFText_LoadPage(page.raw)
                try:
                    analyses.append(
                        analyze_page_glyphs(page.raw, textpage, opts.keep_invisible))
                finally:
                    pdfium_c.FPDFText_ClosePage(textpage)
        finally:
            doc.close()
    return analyses


def _page_reasons(analysis: PageGlyphAnalysis, page: pikepdf.Page) -> List[str]:
    """Motivos por los que una pagina NO es outlineable en Fase 2 (-> fallback)."""
    reasons: List[str] = []
    if analysis.unoutlineable_inked:
        reasons.append("%d glifo(s) con tinta no convertible: sin contorno o con "
                       "contorno que no casa con su posicion (Type3, o CID/fuente "
                       "sin unicode fiable)" % analysis.unoutlineable_inked)
    if analysis.non_fill_visible:
        reasons.append("%d glifo(s) con render mode no-fill (stroke/clip)"
                       % analysis.non_fill_visible)
    type3 = page_type3_font_names(page)
    if type3:
        reasons.append("fuente Type3: " + ", ".join(type3))
    if page_has_xobject_text(page):
        reasons.append("texto dentro de Form XObject (anidado)")
    return reasons


def outline_pdf(data: Union[bytes, bytearray, str, os.PathLike],
                opts: Optional[OutlineOpts] = None) -> OutlineResult:
    """Convierte a curvas el texto del PDF. Devuelve OutlineResult(bytes, report)."""
    opts = opts or OutlineOpts()
    pdf_bytes = _read_bytes(data)

    analyses = _analyze_all_pages(pdf_bytes, opts)

    report = OutlineReport(engine="internal")
    try:
        pdf = pikepdf.open(io.BytesIO(pdf_bytes), password=opts.password or "")
    except pikepdf.PasswordError as exc:
        raise EncryptedPdfError(str(exc)) from exc
    except Exception as exc:  # pikepdf.PdfError y afines
        raise CorruptPdfError(str(exc)) from exc

    try:
        for i, page in enumerate(pdf.pages):
            analysis = analyses[i]
            reasons = _page_reasons(analysis, page)

            if not reasons:
                if analysis.real_chars == 0:
                    # sin texto: pagina intacta (fuentes no usadas se limpian al final)
                    report.add(PageReport(index=i, outlined=False))
                    continue
                removed = rebuild_page(pdf, page, analysis.glyphs)
                page_report = PageReport(
                    index=i, outlined=True,
                    outlined_glyphs=len(analysis.glyphs), removed_fonts=removed)
                for fname in analysis.non_embedded_fonts:
                    page_report.warnings.append(
                        "fuente no incrustada '%s': contornos generados con fuente "
                        "de sustitucion (puede no ser fiel al original)" % fname)
                report.add(page_report)
                continue

            reason = "; ".join(reasons)
            if opts.fallback == FALLBACK_ERROR:
                raise UnsupportedContentError(i, reason)
            if opts.fallback == FALLBACK_SKIP:
                report.add(PageReport(index=i, outlined=False,
                                      fallback="skip", reason=reason))
                continue
            # raster
            rasterize_page(pdf, page, pdf_bytes, i, opts.raster_dpi)
            report.add(PageReport(index=i, outlined=False,
                                  fallback="raster", reason=reason))

        pdf.remove_unreferenced_resources()
        out = io.BytesIO()
        pdf.save(out)
    finally:
        pdf.close()

    return OutlineResult(pdf_bytes=out.getvalue(), report=report)
