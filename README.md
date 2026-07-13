# Outliner — motor interno texto-a-curvas (sustituto de Ghostscript)

Motor 100% permisivo (sin GPL/AGPL) que convierte el texto de un PDF en curvas
vectoriales, para reemplazar el uso de **Ghostscript (AGPL-3.0)** en el módulo
`outliner` de PrintHub/ImprintiaSuite. Se apoya en **PDFium glyph paths** (vía
`pypdfium2.raw`, Apache-2.0/BSD-3) + **pikepdf** (MPL-2.0).

- Plan por fases: [`docs/PLAN_MOTOR_OUTLINER.md`](docs/PLAN_MOTOR_OUTLINER.md)
- Contexto del proyecto: [`docs/PROYECTO.md`](docs/PROYECTO.md)

## Estado: motor completo (Fases 0-4) — en verde

- `pypdfium2==5.11.0` → **pdfium 151.0.7920.0** (fijado con `==` + smoke-test de símbolos).
- **API pública**: `outline_pdf(pdf_bytes|path, OutlineOpts()) -> OutlineResult(pdf_bytes, report)`.
- Fidelidad **~0% a 300 dpi** en todo el corpus outlineable, **cero fuentes
  incrustadas**, texto no extraíble. Casos duros → **fallback raster** con report.
- **91 tests** en `backend/tests/outline_engine/`.

Uso:

```python
from app.core.outline_engine import outline_pdf, OutlineOpts
res = outline_pdf(pdf_bytes, OutlineOpts())      # fallback: raster | skip | error
res.pdf_bytes          # PDF con texto -> curvas, sin fuentes
res.report.to_dict()   # informe por página (outlined/fallback/warnings)
```

CLI: `python -m app.modules.outliner in.pdf out.pdf [--fallback raster|skip|error]`

## Estructura

```
backend/app/core/outline_engine/   # motor: engine, glyphs, geometry, rebuild, fallback, report, errors
backend/app/modules/outliner/      # service (flag OUTLINER_ENGINE) + CLI
backend/tests/outline_engine/      # tests + corpus (12 fixtures) + gen_corpus.py
docs/                              # plan por fases y contexto
THIRD_PARTY_NOTICES.md             # atribuciones (todo permisivo, sin GPL/AGPL)
```

## Desarrollo

```
pip install -r requirements-dev.txt
python -m pytest backend/tests/outline_engine -q      # suite completa
python backend/tests/outline_engine/gen_corpus.py     # regenerar corpus (determinista)
```

Cómo funciona (resumen): dos pasadas — (1) pdfium bajo `PDFIUM_LOCK` analiza cada
página (glifos posicionados en coords de página + señales de outlineabilidad,
todo Python puro); (2) pikepdf reescribe: quita bloques `BT..ET`, emite los
glifos como paths de relleno y elimina las fuentes. El arg de
`FPDFFont_GetGlyphPath` es el **codepoint Unicode**; la colocación por-glifo usa
`FPDFText_GetCharOrigin` + la orientación de `FPDFText_GetMatrix`. Un **self-check**
por-glifo (bbox vs `GetCharBox` en texto no rotado) evita corrupción silenciosa
→ esas páginas van a fallback.

### Reglas del proyecto (resumen)
- **Sin dependencias GPL/AGPL** (Ghostscript, PyMuPDF/fitz, Poppler, cpdf, Inkscape).
- **PDFium no es thread-safe**: todo acceso va bajo `PDFIUM_LOCK`
  (`backend/app/core/outline_engine/_lock.py`).
- Consola Windows cp1252: sin Unicode en prints/logs (usar `->`).
