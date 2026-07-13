# Third-party notices — motor outliner

El motor interno texto-a-curvas (`backend/app/core/outline_engine/`) depende
UNICAMENTE de componentes con licencia permisiva. **No incluye Ghostscript,
PyMuPDF/MuPDF, Poppler, cpdf ni Inkscape** (dependencias GPL/AGPL): eliminarlas
del path de "texto a curvas" es el objetivo de este motor.

Al integrar en PrintHub, incorporar estas atribuciones en los avisos legales
in-app (about / oferta de codigo fuente).

## Dependencias de runtime

### PDFium — via `pypdfium2` 5.11.0 (empaqueta pdfium 151.0.7920.0)
- pypdfium2: Apache-2.0 / BSD-3-Clause.
- PDFium: BSD-3-Clause, con componentes de terceros agregados bajo el
  identificador SPDX `LicenseRef-PdfiumThirdParty` (todos permisivos):
  FreeType, libpng, zlib, libjpeg-turbo, libopenjpeg, libtiff, lcms2, ICU,
  Abseil, AGG 2.3, entre otros. Los textos completos vienen en la distribucion
  de pypdfium2 (`pypdfium2-*.dist-info/licenses/`).
- **FreeType (FTL)** — pdfium incrusta FreeType, por lo que aplica su credito:

  > Portions of this software are copyright (c) 2024 The FreeType Project
  > (www.freetype.org). All rights reserved.

### pikepdf 10.x — MPL-2.0
Reescritura del PDF de salida (content streams, recursos). El texto de la
Mozilla Public License 2.0 debe acompanar la distribucion.

### Pillow — HPND (MIT-CMU)
Comparacion visual / render auxiliar.

### numpy — BSD-3-Clause (y componentes permisivos: 0BSD, MIT, Zlib, CC0-1.0)
Diff de pixeles en tests de fidelidad.

## Dependencias de desarrollo/test (no van en el runtime de produccion)
- **reportlab** — BSD. Generacion del corpus de PDFs de prueba.
- **fontTools** — MIT. Subsetting/inspeccion de fuentes para el corpus.

## Fuentes del corpus de prueba (`backend/tests/outline_engine/corpus/_fonts/`)
- **DejaVu Sans** — licencia Bitstream Vera (permisiva) + cambios de DejaVu en
  dominio publico. Ver `_fonts/DejaVuSans-LICENSE.txt`.
- **Source Sans 3** — (c) 2023 Adobe, SIL Open Font License 1.1
  (Reserved Font Name 'Source'). Ver `_fonts/SourceSans3-OFL.txt`.

## Verificacion
`grep -ri "ghostscript\|gswin\|mupdf\|\bfitz\b\|poppler\|pdftocairo" backend/`
no debe devolver resultados en codigo de produccion.
