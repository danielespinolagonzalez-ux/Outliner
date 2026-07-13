"""FASE 0 - Smoke-test de simbolos de la API experimental de PDFium.

Las funciones FPDFFont_GetGlyphPath / FPDFGlyphPath_* estan marcadas
"Experimental API" en pdfium y pueden cambiar entre versiones. Este test
falla RUIDOSAMENTE (listando lo que falte) si un upgrade de pypdfium2 rompe
la superficie de API de la que depende todo el motor.

Version verificada: pypdfium2 == 5.11.0 -> pdfium 151.0.7920.0.

Si este test falla tras un cambio de version -> PARAR: revisar la nueva API
antes de tocar el motor (glyphs.py / rebuild.py).
"""

import pypdfium2.raw as raw

# Funciones que el motor usa directamente (PLAN seccion 2, Fase 0).
REQUIRED_FUNCTIONS = [
    "FPDFFont_GetGlyphPath",
    "FPDFGlyphPath_CountGlyphSegments",
    "FPDFGlyphPath_GetGlyphPathSegment",
    "FPDFPathSegment_GetPoint",
    "FPDFPathSegment_GetType",
    "FPDFPathSegment_GetClose",
    "FPDFPageObj_GetMatrix",
    "FPDFTextObj_GetFont",
    "FPDFTextObj_GetFontSize",
    "FPDFPageObj_GetFillColor",
    "FPDFPage_CountObjects",
    "FPDFPage_GetObject",
    "FPDFPageObj_GetType",
]

# Constantes con su valor esperado (PLAN seccion 0).
REQUIRED_CONSTANTS = {
    "FPDF_PAGEOBJ_TEXT": 1,
    "FPDF_SEGMENT_MOVETO": 2,
    "FPDF_SEGMENT_LINETO": 0,
    "FPDF_SEGMENT_BEZIERTO": 1,
}


def test_required_functions_exist():
    missing = [name for name in REQUIRED_FUNCTIONS if not hasattr(raw, name)]
    assert not missing, (
        "Simbolos de pdfium ausentes en pypdfium2.raw -> PARAR y revisar API: "
        + ", ".join(missing)
    )


def test_required_constants_exist_and_match():
    problems = []
    for name, expected in REQUIRED_CONSTANTS.items():
        if not hasattr(raw, name):
            problems.append(name + " ausente")
            continue
        actual = getattr(raw, name)
        if actual != expected:
            problems.append("{0} = {1} (esperado {2})".format(name, actual, expected))
    assert not problems, (
        "Constantes de segmento/objeto cambiaron -> revisar el agrupado de "
        "beziers y el filtro de objetos de texto: " + "; ".join(problems)
    )
