# PLAN — Motor interno de texto-a-curvas (sustituto de Ghostscript)

> **Documento de instrucciones para Claude Code.** Proyecto: PrintHub/ImprintiaSuite.
> Objetivo: construir un motor propio 100% permisivo (sin AGPL/GPL) que convierta
> el texto de un PDF en curvas vectoriales, reemplazando el uso de Ghostscript en
> el módulo `outliner` (`backend/app/modules/outliner/`). Esto elimina la última
> dependencia AGPL del backend y desbloquea la venta del SaaS de código cerrado.
> Última actualización: 2026-07-12.

---

## 0. Contexto y decisión de arquitectura (LEER PRIMERO)

### Por qué existe este plan
- PrintHub usa **Ghostscript (AGPL-3.0)** para "texto a curvas". Artifex sostiene
  que el uso de Ghostscript en SaaS obliga a AGPL o licencia comercial, y ha
  litigado (Artifex v. Hancom, 2017). Hay que eliminarlo del path de producción.
- **No existe ninguna herramienta permisiva llave-en-mano** que haga outline de
  texto en un PDF (mutool = AGPL, pdftocairo/Poppler = GPL, Inkscape = GPL,
  cpdf = AGPL). Por eso construimos el motor nosotros.

### Arquitectura elegida: **PDFium glyph paths** (Arquitectura 1)
PDFium (el motor PDF de Chrome, licencia Apache-2.0/BSD-3) expone una API
experimental que devuelve **los contornos vectoriales de cada glifo ya
resueltos** — con la fuente incrustada, el subset, el encoding y el CID ya
descodificados internamente por PDFium:

- `FPDFFont_GetGlyphPath(font, glyph_index, font_size)` → handle de glyph path
- `FPDFGlyphPath_CountGlyphSegments(path)` → nº de segmentos
- `FPDFGlyphPath_GetGlyphPathSegment(path, i)` → segmento i
- `FPDFPathSegment_GetPoint(seg, &x, &y)` / `FPDFPathSegment_GetType(seg)` /
  `FPDFPathSegment_GetClose(seg)`
- Tipos de segmento: `FPDF_SEGMENT_MOVETO=2`, `FPDF_SEGMENT_LINETO=0`,
  `FPDF_SEGMENT_BEZIERTO=1` (cúbicas: vienen en grupos de 3 puntos)

Todo esto es accesible desde Python vía **`pypdfium2.raw`** (bindings ctypes
autogenerados). Esto nos ahorra reimplementar a mano el parseo de fuentes
Type1/CFF/TrueType/CID y sus encodings — el punto más duro del problema.

### Stack (todo permisivo — verificar que NO entra nada GPL/AGPL)
| Librería | Licencia | Rol en el motor |
|---|---|---|
| `pypdfium2` (>=5, **versión FIJADA**) | Apache-2.0 / BSD-3 | enumerar objetos de texto, extraer glyph paths, render de verificación |
| `pikepdf` (>=10.9) | MPL-2.0 | reescritura del PDF final, content streams, copiar recursos no-texto |
| `Pillow` | HPND/MIT-CMU | comparación visual (tests de fidelidad) |
| `numpy` | BSD | diff de píxeles en tests |
| `freetype-py` | FTL (BSD-style) | **fallback opcional fase 3** (fuentes del sistema no incrustadas) |
| `fontTools` | MIT | **fallback opcional fase 3** (inspección de fuentes) |

**PROHIBIDO** añadir: Ghostscript, MuPDF/PyMuPDF/fitz, Poppler, Inkscape, cpdf,
o cualquier dependencia GPL/AGPL. Si una solución requiere una de estas, parar
y proponer alternativa.

### Advertencias críticas (no saltarse)
1. **API experimental**: las funciones `FPDFFont_GetGlyphPath` / `FPDFGlyphPath_*`
   están marcadas "Experimental API" en pdfium. **Fijar la versión exacta de
   pypdfium2 en `requirements.txt` (== , no >=)** y añadir un smoke-test que
   falle ruidosamente si la API cambia tras un upgrade.
2. **Espacio de coordenadas NO documentado**: pdfium no documenta oficialmente
   en qué espacio devuelve los puntos del glyph path. La Fase 0 incluye un
   experimento OBLIGATORIO para verificarlo empíricamente antes de escribir el
   motor. Hipótesis de partida (a verificar): text space escalado por
   `font_size` (es decir, si pasamos `font_size=1.0`, los puntos están en
   unidades de em normalizadas; si pasamos el tamaño real, ya vienen escalados).
3. **PDFium NO es thread-safe**: todas las llamadas a pypdfium2 (helpers o raw)
   deben ir protegidas por el lock global ya usado en el proyecto para render,
   o ejecutarse en el process pool. NUNCA llamar a pdfium desde dos hilos.
4. **ctypes y vida de objetos**: no liberar (`close()`) un documento/página
   mientras se conservan handles de sus fuentes o paths. Orden de liberación:
   paths → textpage → page → document.

---

## 1. Estructura de archivos a crear

```
backend/app/core/outline_engine/
├─ __init__.py           # API pública: outline_pdf(in_bytes|path, opts) -> bytes
├─ engine.py             # orquestador: por página, decide texto→curvas o fallback
├─ glyphs.py             # extracción de glyph paths vía pypdfium2.raw (ctypes)
├─ geometry.py           # matrices 2D, composición, mm/pt, transformación de puntos
├─ rebuild.py            # reconstrucción del PDF con pikepdf (paths en vez de texto)
├─ fallback.py           # rasterizado de página/zona con pypdfium2 (casos duros)
├─ report.py             # informe de conversión (qué se outlineó, qué se rasterizó)
└─ errors.py             # excepciones tipadas del motor

backend/tests/outline_engine/
├─ conftest.py           # fixtures: corpus de PDFs de prueba, lock pdfium
├─ test_coordinate_space.py   # FASE 0: experimento del espacio de coordenadas
├─ test_glyphs.py
├─ test_geometry.py
├─ test_rebuild.py
├─ test_engine_e2e.py    # fidelidad visual render-antes vs render-después
└─ corpus/               # PDFs de prueba (ver §2 Fase 0)
```

El módulo `backend/app/modules/outliner/` pasará a llamar a
`core.outline_engine.outline_pdf()` en lugar de invocar Ghostscript. **No borrar
el código de Ghostscript hasta la Fase 4** — se mantiene como rama muerta tras
un flag de entorno `OUTLINER_ENGINE=internal|ghostscript` (default `internal`
al terminar la Fase 2) para poder comparar en desarrollo.

---

## 2. Plan por fases con checklist

### FASE 0 — Verificación empírica y corpus (bloqueante, ~1 sesión)
Objetivo: confirmar que la API de glyph paths funciona en nuestra versión de
pypdfium2 y descubrir el espacio de coordenadas real.

- [x] Fijar versión: `pip install pypdfium2==<última estable>` y anotar en
      `requirements.txt` con `==`. Anotar también la versión de pdfium que
      empaqueta (`python -c "import pypdfium2; print(pypdfium2.V_PDFIUM)"` o
      equivalente en la versión instalada).
      > HECHO: `pypdfium2==5.11.0` fijado en `requirements.txt`. Empaqueta
      > **pdfium 151.0.7920.0** (`pypdfium2.version.PDFIUM_INFO`). En 5.x la
      > versión de pdfium se lee de `pypdfium2.version.PDFIUM_INFO`
      > (no existe `pypdfium2.V_PDFIUM`).
- [x] Smoke-test de existencia de símbolos: comprobar que `pypdfium2.raw`
      expone `FPDFFont_GetGlyphPath`, `FPDFGlyphPath_CountGlyphSegments`,
      `FPDFGlyphPath_GetGlyphPathSegment`, `FPDFPathSegment_GetPoint`,
      `FPDFPathSegment_GetType`, `FPDFPathSegment_GetClose`,
      `FPDFPageObj_GetMatrix`, `FPDFTextObj_GetFont`, `FPDFTextObj_GetFontSize`,
      `FPDFPageObj_GetFillColor`, `FPDFPage_CountObjects`, `FPDFPage_GetObject`,
      `FPDFPageObj_GetType`. Si falta alguno → PARAR e informar.
      > HECHO: los 13 símbolos existen + constantes verificadas
      > (`FPDF_PAGEOBJ_TEXT=1`, `MOVETO=2`, `LINETO=0`, `BEZIERTO=1`).
      > Test: `backend/tests/outline_engine/test_symbols_smoke.py` (verde).
- [x] **Experimento del espacio de coordenadas** (test_coordinate_space.py):
      1. Generar con reportlab un PDF de 1 página con una sola "H" en Helvetica
         48pt en posición conocida (p.ej. x=100pt, y=200pt).
      2. Extraer el glyph path con `font_size=1.0` y con `font_size=48.0`.
      3. Comprobar: con 1.0, ¿el bounding box de los puntos cae en ~[0,1]
         (unidades em)? Con 48.0, ¿escala ×48?
      4. Transformar los puntos con la matriz del objeto de texto
         (`FPDFPageObj_GetMatrix`) y comprobar que el bbox resultante coincide
         (±1pt) con el bbox del carácter según
         `FPDFText_GetCharBox`/helpers de textpage.
      5. **Documentar la conclusión en un comentario de cabecera de glyphs.py.**
         Todo el motor depende de esto.
      > HECHO. CONCLUSION (corrige la hipotesis del paso 3):
      > - El arg `glyph` de `FPDFFont_GetGlyphPath` es el **CHARCODE**, no el GID.
      > - Los puntos vienen en **em normalizado (1.0 == 1 em)** y **NO dependen
      >   del `font_size`**: con 1.0 y con 48.0 el bbox es IDENTICO
      >   `(0.0769, 0.0, 0.646, 0.718)` (0.718 == cap-height de la 'H'). O sea,
      >   NO escala ×48; el motor llama con `font_size=1.0` y escala por su cuenta.
      > - Composicion verificada (±0.005 pt vs `FPDFText_GetCharBox`, umbral 1 pt):
      >   `page = ObjMatrix . (font_size * em_point)`.
      > - Documentado en la cabecera de
      >   `backend/app/core/outline_engine/glyphs.py`. Test:
      >   `backend/tests/outline_engine/test_coordinate_space.py` (verde).
- [x] Montar el corpus de prueba en `tests/outline_engine/corpus/` (generarlos
      con reportlab dentro del propio test o como script de setup):
      - `latino_ttf.pdf` — texto latino, fuente TrueType incrustada
      - `latino_cff.pdf` — fuente CFF/OpenType incrustada
      - `subset.pdf` — fuente subsetada (prefijo ABCDEF+)
      - `multipos.pdf` — texto rotado, escalado y con kerning (operadores TJ)
      - `color_cmyk.pdf` — texto en color CMYK y en gris
      - `mixto.pdf` — texto + imágenes + vectores (verificar que lo no-texto
        queda intacto)
      - `no_embebida.pdf` — fuente NO incrustada (caso duro, para fallback)
      - Si es posible conseguir uno: `type3.pdf` (caso duro, para fallback)
      > HECHO: los **8** PDFs generados en
      > `backend/tests/outline_engine/corpus/` por `gen_corpus.py` (incluido
      > `type3.pdf`). Fuentes vendorizadas permisivas: DejaVu (Bitstream Vera) y
      > Source Sans 3 (OFL-1.1) en `corpus/_fonts/`. OJO: reportlab NO incrusta
      > CFF, asi que `latino_cff.pdf` y `multipos.pdf` se construyen con un
      > incrustador propio (pikepdf + fontTools). Validacion estructural en
      > `backend/tests/outline_engine/test_corpus.py` (verde). Ver
      > `corpus/README.md`.
- [x] Criterio de salida: experimento de coordenadas concluyente + corpus listo.
      > HECHO: experimento concluyente (arriba) + corpus completo. Suite de
      > Fase 0: **14 tests en verde**.

### FASE 1 — Núcleo de extracción (glyphs.py + geometry.py)
Objetivo: dado un PDF, producir por página una lista de "glifos posicionados":
`(lista de subpaths con puntos en coords de página, color de relleno, regla de relleno)`.

- [ ] `geometry.py`: clase/funciones de matriz 2D `(a,b,c,d,e,f)`:
      multiplicación, aplicar a punto, identidad, escala, conversión mm↔pt
      (1 mm = 72/25.4 pt). Tests unitarios puros (sin pdfium).
- [ ] `glyphs.py`:
      - `iter_text_objects(page) -> Iterator[TextObjectInfo]`: recorre
        `FPDFPage_CountObjects`/`FPDFPage_GetObject`, filtra
        `FPDF_PAGEOBJ_TEXT`, y devuelve fuente (handle), tamaño, matriz,
        color de relleno (RGBA de `FPDFPageObj_GetFillColor`), y modo de
        render de texto si está accesible (fill/stroke/invisible).
        **Importante**: si el objeto de texto está dentro de un Form XObject,
        la matriz devuelta es relativa al contenedor — en Fase 1 tratar solo
        objetos a nivel de página y marcar los XObjects anidados para
        fallback; en Fase 3 componer matrices contenedor×objeto.
      - `get_glyph_outline(font, glyph_index, font_size) -> list[Subpath]`:
        envuelve la secuencia GetGlyphPath → CountSegments → por segmento
        (tipo, punto, close). Agrupar: MOVETO abre subpath; los BEZIERTO
        llegan como puntos sueltos consecutivos — **acumular de 3 en 3** para
        formar cúbicas (control1, control2, destino). Manejar ctypes:
        `ctypes.c_float()` + `ctypes.byref()` para GetPoint.
      - Enumerar los glifos del objeto de texto: obtener nº de
        caracteres/glifos del objeto (vía textpage acotada al objeto o
        `FPDFTextObj_*`), y por cada uno su glyph index y su matriz de
        posición. Si la única vía estable para posiciones por-glifo es la
        textpage (`FPDFText_GetCharIndexAtPos`/`GetCharBox`/`GetMatrix` de
        char), usarla y documentarlo.
      - Los glifos con render mode "invisible" (modo 3, típico de OCR):
        **omitirlos** del outline (opción `keep_invisible=False` por defecto).
- [ ] Todas las funciones que tocan pdfium reciben/usan el lock global.
- [ ] Test (test_glyphs.py): sobre `latino_ttf.pdf`, extraer la "H" y verificar
      nº de subpaths > 0, puntos finitos, bbox coherente con Fase 0.

### FASE 2 — Reconstrucción del PDF (rebuild.py + engine.py) → MVP
Objetivo: PDF de salida idéntico visualmente, con el texto convertido a paths.

- [ ] `rebuild.py` con **pikepdf**:
      - Abrir el PDF original con pikepdf (el mismo archivo que pdfium tiene
        abierto en lectura — trabajar sobre bytes/copia para evitar locks de
        Windows).
      - Por página: generar un content stream NUEVO que contenga:
        1. Todo el contenido original EXCEPTO los operadores de texto
           (BT...ET) que hemos outlineado. Estrategia MVP más segura: en vez
           de editar quirúrgicamente el stream original, **reconstruir**:
           mantener el stream original pero neutralizar el texto haciendo los
           glifos invisibles NO es aceptable (el texto seguiría siendo
           seleccionable y las fuentes seguirían incrustadas). Estrategia
           elegida: usar `pikepdf.parse_content_stream` para partir el stream
           en tokens, eliminar los bloques BT...ET completos, y conservar el
           resto tal cual con `unparse_content_stream`. Los bloques BT...ET
           eliminados se sustituyen por los paths generados. ATENCIÓN: dentro
           de un BT...ET puede haber operadores de estado gráfico (gs, cm no,
           pero sí Tz/Ts...) — al eliminar el bloque entero no se pierden
           porque solo afectan a texto.
        2. Por cada glifo posicionado: emitir
           `q` + color (`rg`/`g`/`k` según el color original; si el color
           original venía de un colorspace complejo /sc /scn con pattern →
           marcar página para fallback) + secuencia de subpaths con `m`, `l`,
           `c`, `h` + `f` (nonzero) o `f*` si procede + `Q`.
           Los puntos ya llegan en coordenadas de página desde glyphs.py
           (matriz compuesta aplicada), con 3-4 decimales.
      - Limpiar: eliminar del diccionario `/Resources/Font` de la página las
        fuentes que ya no se referencian; ejecutar
        `pdf.remove_unreferenced_resources()` al final. Verificar que las
        fuentes incrustadas desaparecen del PDF de salida (ese es el objetivo
        de negocio del outliner).
      - Conservar intactos: imágenes, vectores existentes, anotaciones,
        OCG/capas, boxes (Media/Crop/Trim/Bleed), rotación de página.
- [ ] `engine.py`:
      - `outline_pdf(pdf_bytes, opts) -> OutlineResult(bytes, report)`.
      - Flujo por página: extraer glifos (Fase 1) → si TODOS los objetos de
        texto de la página son outlineables → reconstruir (rebuild) → si
        alguno no lo es (Type3, colorspace raro, XObject anidado en Fase 2)
        → según `opts.fallback`: `raster` (Fase 3) o `skip_page` (dejar la
        página como está y anotarlo en el report) o `error`.
      - `report.py`: por página: nº de objetos outlineados, nº en fallback,
        motivo, fuentes eliminadas. El endpoint lo devolverá como JSON junto
        al PDF para que la UI muestre "Página 3 rasterizada: fuente Type3".
- [ ] **Test de fidelidad visual (test_engine_e2e.py) — el test que manda**:
      1. Render del PDF original a 150 dpi con pypdfium2 → PIL.
      2. Render del PDF outlineado a 150 dpi → PIL.
      3. Diff con numpy: porcentaje de píxeles con diferencia > 8/255.
      4. Umbral de aceptación: **≤ 0,5% de píxeles distintos por página**
         (el antialiasing de hinting de fuente vs path puro produce
         micro-diferencias legítimas en los bordes; no exigir 0%).
      5. Además: assert de que el PDF de salida **no contiene ninguna fuente
         incrustada** (recorrer /Font en pikepdf) y de que el texto ya no es
         extraíble (textpage de pdfium devuelve vacío o casi).
      Ejecutar sobre TODO el corpus salvo los casos duros marcados.
- [ ] Integrar en `modules/outliner/`: flag `OUTLINER_ENGINE`, endpoint
      responde igual que antes + campo `report`. Registrar salida en
      `core/history` como hasta ahora.
- [ ] Criterio de salida (MVP hecho): corpus latino TTF/CFF/subset/multipos/
      color/mixto en verde con ≤0,5% diff y sin fuentes incrustadas.

### FASE 3 — Casos duros y robustez
- [ ] **Form XObjects anidados**: componer matriz del contenedor × matriz del
      objeto de texto y outlinear también el texto dentro de XObjects
      (recorrer recursivamente). Hasta entonces esas páginas van a fallback.
- [ ] **fallback.py (rasterizado)**: para páginas/zonas no convertibles:
      render de la página a 600 dpi (configurable, mínimo 300) con pypdfium2
      → JPEG/PNG → página nueva con pikepdf/reportlab con la imagen a página
      completa respetando MediaBox. Marcar SIEMPRE en el report. Es pérdida
      de vectorial: el usuario debe saberlo.
- [ ] **Fuentes no incrustadas**: pdfium sustituye por una fuente del sistema
      y SÍ devuelve glyph paths de la sustituta → el outline "funciona" pero
      puede no ser fiel al original. Política: outlinear con la sustituta y
      añadir warning al report ("fuente X no incrustada: contornos generados
      con fuente de sustitución"). Alternativa futura: freetype-py + fuente
      elegida por el usuario.
- [ ] **Type3**: detectar (tipo de fuente vía pdfium o /Subtype /Type3 en
      pikepdf) → fallback raster de esa página. No intentar convertir Type3
      en la v1.
- [ ] **Texto con stroke** (render modes 1/2): emitir también `S`/`B` con el
      color de stroke y el ancho de línea del estado gráfico. Si el ancho no
      es recuperable de forma fiable → fallback de esa página.
- [ ] **Clipping por texto** (render modes 4-7, texto como máscara de
      recorte): caso raro y complejo → fallback raster.
- [ ] Endurecer errores: PDF encriptado (pedir password o rechazar), PDF
      corrupto, páginas de 0 objetos, streams enormes (límite de memoria:
      procesar página a página, nunca todo el doc en RAM).

### FASE 4 — Retirada de Ghostscript y cierre
- [ ] `OUTLINER_ENGINE=internal` por defecto en producción.
- [ ] Quitar Ghostscript de: requirements/instalador, `start.ps1`, docs de
      despliegue, y del código del módulo outliner (borrar la rama muerta).
- [ ] Grep de seguridad: `grep -ri "ghostscript\|gswin\|\bgs\b" backend/` sin
      resultados en código de producción.
- [ ] Actualizar avisos legales in-app (§13/about): quitar Ghostscript,
      añadir atribuciones de pdfium (incluir `LicenseRef-PdfiumThirdParty`),
      pikepdf (MPL-2.0), y si se usa freetype-py: crédito FTL
      ("Portions of this software are copyright © <año> The FreeType
      Project (www.freetype.org). All rights reserved.").
- [ ] Nota para el research de licencias existente: con esto, el único AGPL
      restante del proyecto es PyMuPDF (migración aparte, ya investigada).

---

## 3. Esqueleto de código de referencia

> Verificar nombres exactos de símbolos contra la versión instalada de
> pypdfium2 — la API raw es autogenerada y puede variar ligeramente. Si un
> símbolo no existe, buscar el equivalente en `dir(pypdfium2.raw)` antes de
> cambiar de estrategia.

### 3.1 Extracción de glyph paths (glyphs.py, núcleo)

```python
import ctypes
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

FPDF_SEGMENT_LINETO = 0
FPDF_SEGMENT_BEZIERTO = 1
FPDF_SEGMENT_MOVETO = 2

def get_glyph_subpaths(font_handle, glyph_index: int, font_size: float):
    """Devuelve lista de subpaths; cada subpath es lista de comandos:
    ('m',(x,y)) | ('l',(x,y)) | ('c',(x1,y1),(x2,y2),(x3,y3)) | ('h',)
    Coordenadas en el espacio verificado en Fase 0 (documentar aquí)."""
    gpath = pdfium_c.FPDFFont_GetGlyphPath(font_handle, glyph_index,
                                           ctypes.c_float(font_size))
    if not gpath:
        return []  # glifo sin contorno (espacio, etc.)
    n = pdfium_c.FPDFGlyphPath_CountGlyphSegments(gpath)
    subpaths, current, bezier_buf = [], [], []
    for i in range(n):
        seg = pdfium_c.FPDFGlyphPath_GetGlyphPathSegment(gpath, i)
        x, y = ctypes.c_float(), ctypes.c_float()
        pdfium_c.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
        seg_type = pdfium_c.FPDFPathSegment_GetType(seg)
        pt = (x.value, y.value)
        if seg_type == FPDF_SEGMENT_MOVETO:
            if current:
                subpaths.append(current)
            current, bezier_buf = [('m', pt)], []
        elif seg_type == FPDF_SEGMENT_LINETO:
            current.append(('l', pt))
        elif seg_type == FPDF_SEGMENT_BEZIERTO:
            bezier_buf.append(pt)
            if len(bezier_buf) == 3:          # cúbica completa
                current.append(('c', *bezier_buf))
                bezier_buf = []
        if pdfium_c.FPDFPathSegment_GetClose(seg):
            current.append(('h',))
    if current:
        subpaths.append(current)
    return subpaths
```

### 3.2 Enumeración de objetos de texto de una página

```python
def iter_text_objects(page_handle):
    n = pdfium_c.FPDFPage_CountObjects(page_handle)
    for i in range(n):
        obj = pdfium_c.FPDFPage_GetObject(page_handle, i)
        if pdfium_c.FPDFPageObj_GetType(obj) != pdfium_c.FPDF_PAGEOBJ_TEXT:
            continue
        font = pdfium_c.FPDFTextObj_GetFont(obj)
        size = ctypes.c_float()
        pdfium_c.FPDFTextObj_GetFontSize(obj, ctypes.byref(size))
        mat = pdfium_c.FS_MATRIX()
        pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(mat))
        r, g, b, a = (ctypes.c_uint() for _ in range(4))
        pdfium_c.FPDFPageObj_GetFillColor(obj, *(ctypes.byref(v) for v in (r, g, b, a)))
        yield obj, font, size.value, (mat.a, mat.b, mat.c, mat.d, mat.e, mat.f), \
              (r.value, g.value, b.value, a.value)
```

### 3.3 Emisión de operadores de path (rebuild.py)

```python
def glyph_to_content_ops(subpaths, page_matrix, fill_rgb):
    """subpaths ya en coords locales del glifo; page_matrix los lleva a
    coords de página. fill_rgb en 0-255 (color original del objeto)."""
    def T(pt):
        x, y = pt
        a, b, c, d, e, f = page_matrix
        return (a * x + c * y + e, b * x + d * y + f)
    ops = [b"q"]
    r, g, b_ = (v / 255 for v in fill_rgb)
    ops.append(f"{r:.4f} {g:.4f} {b_:.4f} rg".encode())
    for sp in subpaths:
        for cmd in sp:
            if cmd[0] == 'm':
                x, y = T(cmd[1]); ops.append(f"{x:.3f} {y:.3f} m".encode())
            elif cmd[0] == 'l':
                x, y = T(cmd[1]); ops.append(f"{x:.3f} {y:.3f} l".encode())
            elif cmd[0] == 'c':
                pts = [T(p) for p in cmd[1:]]
                flat = " ".join(f"{x:.3f} {y:.3f}" for x, y in pts)
                ops.append(f"{flat} c".encode())
            elif cmd[0] == 'h':
                ops.append(b"h")
    ops += [b"f", b"Q"]   # f* si la fuente usa even-odd (raro; ver Fase 3)
    return b"\n".join(ops)
```

### 3.4 Eliminación de bloques BT...ET y ensamblado (rebuild.py, pikepdf)

```python
import pikepdf

def strip_text_and_append_paths(pdf: pikepdf.Pdf, page: pikepdf.Page,
                                path_ops: bytes):
    instrucciones = pikepdf.parse_content_stream(page)
    out, in_text = [], False
    for operands, operator in instrucciones:
        op = str(operator)
        if op == "BT":
            in_text = True
            continue
        if op == "ET":
            in_text = False
            continue
        if not in_text:
            out.append((operands, operator))
    nuevo = pikepdf.unparse_content_stream(out) + b"\n" + path_ops
    page.Contents = pdf.make_stream(nuevo)
```

> Nota: esta versión MVP elimina TODOS los bloques de texto de la página, lo
> cual es correcto solo si TODOS se han podido outlinear (así lo garantiza
> engine.py en Fase 2). La granularidad por-objeto llega con los casos mixtos
> de Fase 3.

### 3.5 Lock global (obligatorio en todo acceso a pdfium)

```python
import threading
PDFIUM_LOCK = threading.Lock()   # reutilizar el que ya exista en core/render

def outline_pdf(pdf_bytes: bytes, opts) -> "OutlineResult":
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_bytes)
        try:
            ...  # fases 1-2 por página
        finally:
            doc.close()
    # la parte pikepdf (rebuild) NO necesita el lock de pdfium
```

### 3.6 Test de fidelidad (test_engine_e2e.py)

```python
import numpy as np, pypdfium2 as pdfium

def pixel_diff_ratio(pdf_a: bytes, pdf_b: bytes, page_index=0, dpi=150):
    def render(data):
        doc = pdfium.PdfDocument(data)
        try:
            return np.asarray(doc[page_index].render(scale=dpi / 72).to_pil()
                              .convert("L"), dtype=np.int16)
        finally:
            doc.close()
    a, b = render(pdf_a), render(pdf_b)
    assert a.shape == b.shape, "las páginas cambiaron de tamaño"
    return float(np.mean(np.abs(a - b) > 8))

def test_latino_ttf_fidelidad(corpus):
    original = corpus["latino_ttf.pdf"]
    result = outline_pdf(original, OutlineOpts())
    assert pixel_diff_ratio(original, result.pdf_bytes) <= 0.005
    # y sin fuentes incrustadas:
    with pikepdf.open(io.BytesIO(result.pdf_bytes)) as pdf:
        for page in pdf.pages:
            fonts = page.get("/Resources", {}).get("/Font", {})
            assert len(dict(fonts)) == 0
```

---

## 4. Convenciones del proyecto que Claude Code debe respetar

- **Windows/cp1252**: nada de caracteres Unicode en prints/logs del backend
  (usar `->` no flechas). Ver §7 de PROYECTO.md.
- **Ritual de reinicio**: tras cambios de backend, parar la tarea PrintHub,
  matar el PID del puerto 8000, arrancar, verificar con
  `curl.exe -k https://localhost:8000/api/...`.
- **Estructura**: el motor va en `core/` (compartido), el endpoint en
  `modules/outliner/router.py`. Salidas registradas con `core/history.record`.
- **Sin créditos**: el outliner no consume créditos de IA (es maquetación,
  como card-sheet).
- **Trabajar por fases**: no avanzar a la fase N+1 con tests de la fase N en
  rojo. El experimento de coordenadas de Fase 0 es bloqueante y su conclusión
  debe quedar documentada en el código.
- **Cada sesión de Claude Code**: empezar leyendo este documento y el estado
  del checklist; marcar los ítems completados editando este mismo archivo.

## 5. Definición de "hecho"

El motor está terminado cuando: (1) todo el corpus pasa fidelidad ≤0,5% y
cero fuentes incrustadas; (2) los casos duros producen fallback raster con
report claro, nunca errores silenciosos; (3) Ghostscript eliminado del código,
del instalador y de los avisos legales; (4) `grep -ri ghostscript backend/`
limpio; (5) atribuciones pdfium/pikepdf/FTL añadidas al about legal.
