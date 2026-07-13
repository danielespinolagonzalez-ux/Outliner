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
from dataclasses import dataclass
from typing import List, Optional, Union

import numpy as np
import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from ._lock import PDFIUM_LOCK
from .errors import CorruptPdfError, EncryptedPdfError, UnsupportedContentError
from .glyphs import PageGlyphAnalysis, analyze_page_glyphs
from .fallback import DEFAULT_DPI, rasterize_page
from .rebuild import (
    neutralize_xobject_text,
    page_has_annotation_text_fonts,
    page_has_xobject_text,
    page_type3_font_names,
    privatize_resources,
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
    # Red de seguridad: tras outlinear, render de cada pagina outlineada vs
    # original; si difieren mas de verify_threshold -> esa pagina va a fallback
    # (captura CUALQUIER corrupcion visual: glifo erroneo, color perdido dentro de
    # BT..ET, CTM desbalanceada, capa OCG horneada, transparencia, etc.). A 300
    # dpi las paginas correctas dan ~0%. Desactivable para lotes grandes.
    verify_render: bool = True
    verify_dpi: int = 300
    verify_threshold: float = 0.02


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
    if page_has_annotation_text_fonts(page):
        reasons.append("fuentes en apariencias de anotaciones (form/FreeText/stamp)")
    # OJO: el texto en Form XObject NO es motivo de fallback: la textpage lo aplana
    # y analyze_page_glyphs ya valida sus glifos; se neutraliza en el rebuild. Si su
    # texto fuese no convertible (Type3/CID en XObject), ya lo captan las senales de
    # arriba (unoutlineable_inked / non_fill_visible sobre el texto aplanado).
    return reasons


def _save_pdf(pdf: pikepdf.Pdf) -> bytes:
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def _render_gray(doc, index, dpi):
    page = doc[index]  # mantener vivo durante el render
    pil = page.render(scale=dpi / 72.0).to_pil().convert("L")
    return np.asarray(pil, dtype=np.int16)


def _verify_outlined_pages(orig_bytes, out_bytes, report, opts) -> List[int]:
    """Devuelve los indices de paginas OUTLINEADAS cuyo render difiere del original
    por encima de verify_threshold (o cambiaron de tamano). Bajo PDFIUM_LOCK."""
    failed: List[int] = []
    with PDFIUM_LOCK:
        odoc = pdfium.PdfDocument(orig_bytes, password=opts.password)
        ndoc = pdfium.PdfDocument(out_bytes)
        try:
            for pr in report.pages:
                if not pr.outlined:
                    continue
                a = _render_gray(odoc, pr.index, opts.verify_dpi)
                b = _render_gray(ndoc, pr.index, opts.verify_dpi)
                if a.shape != b.shape or float(np.mean(np.abs(a - b) > 8)) > opts.verify_threshold:
                    failed.append(pr.index)
        finally:
            odoc.close()
            ndoc.close()
    return failed


def _fallback_page(pdf, page, pdf_bytes, index, opts, report, reason):
    """Aplica el fallback elegido a una pagina y anota el report."""
    if opts.fallback == FALLBACK_ERROR:
        raise UnsupportedContentError(index, reason)
    if opts.fallback == FALLBACK_SKIP:
        report.add(PageReport(index=index, outlined=False,
                              fallback="skip", reason=reason))
        return
    rasterize_page(pdf, page, pdf_bytes, index, opts.raster_dpi,
                   password=opts.password)
    report.add(PageReport(index=index, outlined=False,
                          fallback="raster", reason=reason))


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
        if len(pdf.pages) != len(analyses):
            # pdfium y pikepdf discrepan en el numero de paginas (arbol /Pages roto
            # o reparado distinto) -> alinear analyses[i] con pdf.pages[i] no es
            # fiable. Se rechaza en vez de arriesgar corromper/mal-reportar.
            raise CorruptPdfError(
                "discrepancia de paginas pdfium(%d) vs pikepdf(%d)"
                % (len(analyses), len(pdf.pages)))
        for i, page in enumerate(pdf.pages):
            analysis = analyses[i]
            reasons = _page_reasons(analysis, page)

            if not reasons:
                if analysis.real_chars == 0:
                    # sin texto: pagina intacta (fuentes no usadas se limpian al final)
                    report.add(PageReport(index=i, outlined=False))
                    continue
                # copia privada de /Resources para no mutar recursos compartidos
                privatize_resources(page)
                # neutralizar texto en Form XObjects (si lo hay) antes de emitir
                xobj_removed = []
                if page_has_xobject_text(page):
                    try:
                        xobj_removed = neutralize_xobject_text(pdf, page)
                    except Exception as exc:  # no neutralizable -> fallback seguro
                        _fallback_page(pdf, page, pdf_bytes, i, opts, report,
                                       "texto en Form XObject no neutralizable: %s" % exc)
                        continue
                removed = rebuild_page(pdf, page, analysis.glyphs) + xobj_removed
                page_report = PageReport(
                    index=i, outlined=True,
                    outlined_glyphs=len(analysis.glyphs), removed_fonts=removed)
                for fname in analysis.non_embedded_fonts:
                    page_report.warnings.append(
                        "fuente no incrustada '%s': contornos generados con fuente "
                        "de sustitucion (puede no ser fiel al original)" % fname)
                report.add(page_report)
                continue

            _fallback_page(pdf, page, pdf_bytes, i, opts, report, "; ".join(reasons))

        pdf.remove_unreferenced_resources()
        out_bytes = _save_pdf(pdf)

        # Red de seguridad: verificar por render y rasterizar las paginas que no casen.
        if opts.verify_render and any(p.outlined for p in report.pages):
            failed = set(_verify_outlined_pages(pdf_bytes, out_bytes, report, opts))
            if failed:
                if opts.fallback == FALLBACK_ERROR:
                    raise UnsupportedContentError(
                        sorted(failed)[0], "verificacion de render fallida")
                for pr in report.pages:
                    if pr.index not in failed:
                        continue
                    rasterize_page(pdf, pdf.pages[pr.index], pdf_bytes, pr.index,
                                   opts.raster_dpi, password=opts.password)
                    pr.outlined = False
                    pr.outlined_glyphs = 0
                    pr.removed_fonts = []
                    pr.warnings = []
                    pr.fallback = "raster"
                    pr.reason = ("verificacion de render fallida (diff > %.1f%%): "
                                 "rasterizado para no arriesgar corrupcion"
                                 % (opts.verify_threshold * 100))
                pdf.remove_unreferenced_resources()
                out_bytes = _save_pdf(pdf)
    finally:
        pdf.close()

    return OutlineResult(pdf_bytes=out_bytes, report=report)
