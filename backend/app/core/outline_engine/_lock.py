"""Lock global de PDFium.

PDFium NO es thread-safe: TODAS las llamadas a pypdfium2 (helpers o .raw)
deben ir serializadas por este lock, o ejecutarse en un process pool.
NUNCA llamar a pdfium desde dos hilos a la vez.

En Fase 0 este es un lock local del motor. Al integrar en PrintHub debe
UNIFICARSE con el lock que ya usa core/render para no tener dos locks
distintos protegiendo la misma libreria nativa.
"""

import threading

# Reentrante para permitir que un helper que ya tiene el lock llame a otro
# helper que tambien lo toma sin auto-bloquearse.
PDFIUM_LOCK = threading.RLock()
