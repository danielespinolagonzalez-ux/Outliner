"""Extraccion de glyph paths de PDFium via pypdfium2.raw (ctypes).

En Fase 0 este archivo SOLO documenta la conclusion del experimento del
espacio de coordenadas (abajo). Las funciones de extraccion
(iter_text_objects, get_glyph_outline, ...) llegan en Fase 1.

cp1252: comentarios/prints en ASCII, usar '->' en vez de flechas.
"""

# ===========================================================================
# CONCLUSION DEL EXPERIMENTO DE COORDENADAS (Fase 0) -- LEER ANTES DE TOCAR
# ===========================================================================
# Todo el motor depende de esto. Verificado EMPIRICAMENTE con:
#     pypdfium2 == 5.11.0   ->   pdfium 151.0.7920.0
# Test que lo reproduce y lo blinda:
#     backend/tests/outline_engine/test_coordinate_space.py
#
# Caso de prueba: una "H" en Helvetica 48pt colocada en (x=100, y=200) pt.
#
# 1) EL ARGUMENTO 'glyph' DE FPDFFont_GetGlyphPath ES EL CHARCODE (no el GID).
#    Pasar el codigo de caracter que la fuente ve en el content stream (para la
#    'H' ASCII simple -> 72) devuelve el contorno correcto (1 subpath con forma
#    de H). pdfium resuelve charcode -> glyph-index internamente usando el
#    encoding / CIDToGIDMap de la fuente. Pasar un GID crudo daria otro glifo.
#    (Para fuentes CID el "charcode" es el codigo propio de la fuente; se
#     re-valida en Fase 1 al enumerar los glifos por objeto de texto.)
#
# 2) EL ESPACIO DE COORDENADAS ES 'em' NORMALIZADO (1.0 == 1 em).
#    Los puntos devueltos NO dependen del argumento font_size en esta version:
#    font_size=1.0 y font_size=48.0 devuelven EXACTAMENTE el mismo bbox
#        (l, b, r, t) = (0.0769, 0.0, 0.6460, 0.7180)
#    y 0.718 == cap-height de la 'H' de Helvetica (718/1000 unidades de fuente).
#    => El motor llama SIEMPRE con font_size=1.0 y escala por el tamano real por
#       su cuenta. Esto es robusto: tanto si una futura version ignora el
#       parametro como si lo respeta, con arg=1.0 la salida queda en 'em'.
#
# 3) COMPOSICION punto_glifo(em) -> punto_pagina(pt):
#        page_point = ObjMatrix . ( font_size * em_point )
#    donde:
#        ObjMatrix = FPDFPageObj_GetMatrix(text_obj)   -> (a, b, c, d, e, f)
#        font_size = FPDFTextObj_GetFontSize(text_obj)
#    O sea: escalar el punto 'em' por font_size y despues aplicar la matriz del
#    objeto de texto (que lleva posicion/rotacion/escala del objeto, pero NO el
#    font_size). En forma de matriz:  GlyphToPage = ObjMatrix x Scale(font_size).
#    Verificado: el bbox transformado casa con FPDFText_GetCharBox dentro de
#    0.005 pt (el test exige <= 1 pt). La composicion alternativa
#    "ObjMatrix . em_point" (sin escalar por font_size) se desvia ~34 pt: MAL.
#
# 4) NO-THREAD-SAFE: toda llamada de arriba va bajo app.core.outline_engine.
#    _lock.PDFIUM_LOCK. Orden de liberacion de handles: paths -> textpage ->
#    page -> document.
# ===========================================================================
