"""Motor interno texto-a-curvas (sustituto permisivo de Ghostscript).

Paquete del core de PrintHub. API publica:

    from app.core.outline_engine import outline_pdf, OutlineOpts
    result = outline_pdf(pdf_bytes, OutlineOpts())
    result.pdf_bytes   # PDF con el texto convertido a curvas, sin fuentes
    result.report      # informe por pagina (outlined / fallback / warnings)

Todo acceso a pdfium va serializado por PDFIUM_LOCK (no thread-safe).
Ver docs/PLAN_MOTOR_OUTLINER.md para el plan por fases.
"""

from ._lock import PDFIUM_LOCK
from .engine import (
    FALLBACK_ERROR,
    FALLBACK_RASTER,
    FALLBACK_SKIP,
    OutlineOpts,
    OutlineResult,
    outline_pdf,
)
from .errors import (
    CorruptPdfError,
    EncryptedPdfError,
    OutlineError,
    UnsupportedContentError,
)
from .report import OutlineReport, PageReport

__all__ = [
    "outline_pdf",
    "OutlineOpts",
    "OutlineResult",
    "OutlineReport",
    "PageReport",
    "OutlineError",
    "EncryptedPdfError",
    "CorruptPdfError",
    "UnsupportedContentError",
    "FALLBACK_RASTER",
    "FALLBACK_SKIP",
    "FALLBACK_ERROR",
    "PDFIUM_LOCK",
]
