# Outliner — motor interno texto-a-curvas (sustituto de Ghostscript)

Motor 100% permisivo (sin GPL/AGPL) que convierte el texto de un PDF en curvas
vectoriales, para reemplazar el uso de **Ghostscript (AGPL-3.0)** en el módulo
`outliner` de PrintHub/ImprintiaSuite. Se apoya en **PDFium glyph paths** (vía
`pypdfium2.raw`, Apache-2.0/BSD-3) + **pikepdf** (MPL-2.0).

- Plan por fases: [`docs/PLAN_MOTOR_OUTLINER.md`](docs/PLAN_MOTOR_OUTLINER.md)
- Contexto del proyecto: [`docs/PROYECTO.md`](docs/PROYECTO.md)

## Estado: Fase 0 (verificación empírica + corpus) — COMPLETA

- `pypdfium2==5.11.0` fijado → empaqueta **pdfium 151.0.7920.0**.
- Smoke-test de los 13 símbolos de la API experimental de glyph paths.
- Experimento del espacio de coordenadas concluyente; conclusión documentada en
  la cabecera de `backend/app/core/outline_engine/glyphs.py`.
- Corpus de 8 PDFs de prueba en `backend/tests/outline_engine/corpus/`.

## Estructura

```
backend/app/core/outline_engine/   # el motor (Fase 0: lock + conclusión coords)
backend/tests/outline_engine/      # smoke, experimento de coords, corpus y tests
docs/                              # plan por fases y contexto
```

## Desarrollo

```
pip install -r requirements-dev.txt
python -m pytest backend/tests/outline_engine -q      # suite de Fase 0
python backend/tests/outline_engine/gen_corpus.py     # regenerar corpus
```

### Reglas del proyecto (resumen)
- **Sin dependencias GPL/AGPL** (Ghostscript, PyMuPDF/fitz, Poppler, cpdf, Inkscape).
- **PDFium no es thread-safe**: todo acceso va bajo `PDFIUM_LOCK`
  (`backend/app/core/outline_engine/_lock.py`).
- Consola Windows cp1252: sin Unicode en prints/logs (usar `->`).
