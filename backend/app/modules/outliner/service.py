"""Servicio del modulo outliner: envuelve el motor con el flag OUTLINER_ENGINE.

En PrintHub el router llama a este servicio y registra la salida en core/history.
El flag permite comparar en desarrollo:
  OUTLINER_ENGINE=internal    -> motor propio permisivo (default)
  OUTLINER_ENGINE=ghostscript -> NO disponible en este repo (es la dependencia
                                 AGPL que este proyecto elimina).

cp1252: ASCII, usar '->'.
"""

import os
from typing import Dict, Optional, Tuple

from ...core.outline_engine import OutlineOpts, outline_pdf

ENGINE_ENV = "OUTLINER_ENGINE"
DEFAULT_ENGINE = "internal"


def get_engine() -> str:
    return os.environ.get(ENGINE_ENV, DEFAULT_ENGINE).strip().lower() or DEFAULT_ENGINE


def outline_pdf_service(pdf_bytes: bytes, *, fallback: str = "raster",
                        raster_dpi: int = 600, keep_invisible: bool = False,
                        password: Optional[str] = None) -> Tuple[bytes, Dict]:
    """Convierte texto a curvas. Devuelve (pdf_bytes, report_dict).

    La salida (bytes + report JSON-able) es la que el endpoint devuelve y la que
    se registra en core/history al integrar en PrintHub.
    """
    if fallback not in ("raster", "skip", "error"):
        raise ValueError("fallback desconocido: %r (usar 'raster'|'skip'|'error')" % fallback)
    engine = get_engine()
    if engine == "ghostscript":
        raise NotImplementedError(
            "OUTLINER_ENGINE=ghostscript no esta disponible en este repo: el motor "
            "Ghostscript (AGPL-3.0) es justo la dependencia que se elimina. "
            "Usar OUTLINER_ENGINE=internal (default).")
    if engine != DEFAULT_ENGINE:
        raise ValueError("OUTLINER_ENGINE desconocido: %r (usar 'internal')" % engine)

    result = outline_pdf(pdf_bytes, OutlineOpts(
        fallback=fallback, raster_dpi=raster_dpi,
        keep_invisible=keep_invisible, password=password))
    return result.pdf_bytes, result.report.to_dict()
