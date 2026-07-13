# Integración del motor outliner en PrintHub/ImprintiaSuite

> **Handoff para Claude Code.** Este repositorio (`Outliner`) contiene el motor
> interno texto-a-curvas ya **terminado, auditado y en verde** (Fases 0-4 +
> auditoría profunda). Esta guía lo integra en el monorepo PrintHub reemplazando
> **Ghostscript (AGPL-3.0)** en el módulo `outliner`. El motor está diseñado como
> **espejo del layout de PrintHub** (`backend/app/core/…`, `backend/app/modules/…`),
> así que la integración es sobre todo copiar el paquete y hacer tres conexiones:
> **unificar el lock**, **cablear el router** y **retirar Ghostscript**.

---

## 0. Prompt listo para pegar

Copia esto en la sesión de Claude Code que trabaje sobre el monorepo PrintHub:

```
Lee docs/INTEGRACION_PRINTHUB.md (viene del repo del motor) e integra el motor
interno texto-a-curvas en el modulo outliner de PrintHub, sustituyendo Ghostscript.

Restricciones duras (NO negociables):
- PROHIBIDO añadir dependencias GPL/AGPL (Ghostscript, PyMuPDF/fitz, Poppler,
  cpdf, Inkscape). Si algo las requiere, para y propon alternativa.
- Todo acceso a pdfium va bajo el lock global unico del proyecto (core/render):
  pdfium NO es thread-safe. Unifica PDFIUM_LOCK, no crees un segundo lock.
- Consola Windows cp1252: sin Unicode en prints/logs ni en comentarios de codigo;
  usa '->' en vez de flechas. Los .md pueden llevar acentos.
- El endpoint debe responder igual que antes + un campo `report`. No rompas el
  contrato de /outliner ni el registro en core/history.
- Desarrolla en una rama, commitea con mensajes claros, y NO abras PR salvo que
  te lo pida.

Sigue los pasos de la seccion 4. Al terminar: grep de Ghostscript limpio, la
suite backend/tests/outline_engine en verde, y un smoke del endpoint /outliner.
```

---

## 1. Qué se entrega (estado del motor)

- **API pública** (estable): `outline_pdf(pdf_bytes|path, OutlineOpts()) -> OutlineResult(pdf_bytes, report)`.
- **Servicio del módulo**: `outline_pdf_service(pdf_bytes, *, fallback, raster_dpi, keep_invisible, password) -> (bytes, report_dict)` con el flag `OUTLINER_ENGINE`.
- **Fidelidad ~0% a 300 dpi** en todo el corpus outlineable, **cero fuentes
  incrustadas** en la salida, texto ya no extraíble.
- **Casos duros → fallback raster** con report claro. **Nunca corrupción silenciosa**
  (tres redes: señales de outlineabilidad → self-check por glifo → verificación por render).
- **96 tests** en verde (`backend/tests/outline_engine/`), suite ~15 s.
- **Dependencias 100% permisivas**: `pypdfium2==5.11.0` (Apache-2.0/BSD-3, empaqueta
  pdfium 151.0.7920.0), `pikepdf>=10.9` (MPL-2.0), `numpy>=1.24` (BSD).
  Dev/test: `reportlab`, `pytest`, `fonttools`.

---

## 2. Restricciones duras (se mantienen en la integración)

1. **Sin GPL/AGPL.** Ghostscript, PyMuPDF/fitz, Poppler, cpdf, Inkscape: prohibidos.
   Si un requisito los pide, **parar y proponer alternativa**.
2. **Lock global único de pdfium.** pdfium no es thread-safe. El motor trae un
   `PDFIUM_LOCK` propio (`_lock.py`) que **debe unificarse** con el lock que ya usa
   `core/render`. Ver paso 4.3.
3. **cp1252 (consola Windows).** Sin Unicode en prints/logs ni en comentarios de
   código del backend. Usar `->`. (Los `.md` sí llevan acentos.)
4. **Contrato del endpoint.** `/outliner` responde igual que antes + campo `report`;
   la salida se sigue registrando en `core/history`.
5. **Git.** Rama de trabajo, commits claros; **no abrir PR** salvo petición explícita.

---

## 3. Inventario: qué copiar y a dónde

El layout ya es el de PrintHub, así que las rutas coinciden 1:1 (drop-in).

| En este repo (`Outliner/`) | Destino en PrintHub | Acción |
|---|---|---|
| `backend/app/core/outline_engine/` (paquete completo: `__init__`, `_lock`, `engine`, `glyphs`, `geometry`, `rebuild`, `fallback`, `report`, `errors`) | `backend/app/core/outline_engine/` | **Copiar** tal cual |
| `backend/app/modules/outliner/service.py` | `backend/app/modules/outliner/service.py` | **Copiar** (nuevo servicio del motor) |
| `backend/app/modules/outliner/__main__.py` | `backend/app/modules/outliner/__main__.py` | Copiar (CLI de verificación, opcional) |
| `backend/tests/outline_engine/` (tests + `corpus/` + `gen_corpus.py` + `conftest.py`) | `backend/tests/outline_engine/` | **Copiar** tal cual |
| `THIRD_PARTY_NOTICES.md` | fusionar en avisos legales del proyecto / about in-app | Fusionar |
| `requirements.txt` (3 líneas de runtime) | `requirements.txt` de PrintHub | Añadir deps |
| `requirements-dev.txt` (reportlab/pytest/fonttools) | dev de PrintHub | Añadir deps |

**No copiar**: `docs/` (son del motor; este documento es la referencia),
`README.md`, `.gitignore` (usa el del monorepo).

El módulo `modules/outliner/` **ya existe** en PrintHub con su `router.py` (hoy
llama a Ghostscript). Aquí solo aportas `service.py` (+ `__main__.py`) y **cableas
el router** (paso 4.4). El `router.py` de PrintHub **no** está en este repo.

---

## 4. Pasos de integración

### 4.1 Copiar el paquete del motor y los tests
Copia las carpetas de la tabla anterior. Como el layout es idéntico, no hay que
remapear imports: el motor usa imports relativos (`from ...core.outline_engine
import …` en el servicio; `from ._lock import PDFIUM_LOCK` dentro del paquete).

### 4.2 Dependencias
Añade a `requirements.txt` de PrintHub (si no están ya):

```
pypdfium2==5.11.0        # Apache-2.0 / BSD-3 : glyph paths + render de verificacion
pikepdf>=10.9            # MPL-2.0 : reescritura del PDF final
numpy>=1.24              # BSD : diff de pixeles de la red de verificacion
```

> `pypdfium2` se fija con `==` **a propósito**: expone la API experimental de
> glyph-paths de pdfium, que puede cambiar entre versiones. Si alguna vez se sube
> la versión, correr antes `test_symbols_smoke.py` y `test_coordinate_space.py`
> (fallan ruidosamente si pdfium rompe el contrato de símbolos/coordenadas).

Dev: `reportlab`, `pytest`, `fonttools` (solo para regenerar corpus y correr tests).

### 4.3 Unificar el lock de pdfium (CRÍTICO)
El motor trae `backend/app/core/outline_engine/_lock.py` con un
`PDFIUM_LOCK = threading.RLock()` **local**. PrintHub ya tiene un lock de pdfium en
`core/render`. **Debe haber un único lock** para toda la librería nativa, o dos
locks distintos “protegerán” la misma librería sin serializar de verdad.

Recomendado — que el motor reexporte el lock del proyecto:

```python
# backend/app/core/outline_engine/_lock.py  (tras integrar en PrintHub)
"""Lock global de PDFium: se reutiliza el unico del proyecto (core/render).
pdfium NO es thread-safe: todo acceso a pypdfium2 va serializado por este lock.
"""
from ..render import PDFIUM_LOCK   # <- el lock unico de pdfium del proyecto
```

**Requisito**: ese lock unificado **debe ser `threading.RLock()` (reentrante)**, no
`threading.Lock()`. El motor asume reentrancia (un helper que ya tiene el lock puede
llamar a otro que también lo toma). `RLock` es superconjunto seguro de `Lock`: si
`core/render` hoy usa `threading.Lock()`, **súbelo a `threading.RLock()`** (nada que
funcionara con `Lock` se rompe). Si prefieres no tocar `core/render`, la alternativa
es dejar el `_lock.py` del motor como la fuente única y que `core/render` importe de
él; lo importante es que **exista un solo objeto lock**.

Verifica que no queden dos definiciones:
`grep -rn "threading.Lock()\|threading.RLock()" backend/app/core/` — debe apuntar a
un único punto de verdad para pdfium.

### 4.4 Cablear el router del módulo outliner
En `backend/app/modules/outliner/router.py` de PrintHub, sustituye la llamada a
Ghostscript por el servicio del motor:

```python
from .service import outline_pdf_service  # motor permisivo (flag OUTLINER_ENGINE)

# ... dentro del handler del endpoint /outliner, con el PDF subido en `data`:
out_bytes, report = outline_pdf_service(
    data,
    fallback="raster",     # "raster" | "skip" | "error"  (default raster)
    raster_dpi=600,        # solo aplica a paginas que caen a fallback
    password=password,     # si el endpoint acepta PDFs protegidos
)
# Registrar en el historial IGUAL que antes:
core.history.record("outliner", nombre_salida, out_bytes, "pdf")
# Responder el PDF como hasta ahora + el report (nuevo):
#   - si el endpoint devuelve el fichero: adjunta `report` en una cabecera/campo
#     JSON aparte, o en el envelope que ya use PrintHub.
```

- **Firma del servicio**:
  `outline_pdf_service(pdf_bytes, *, fallback="raster", raster_dpi=600, keep_invisible=False, password=None) -> (bytes, dict)`.
- `report` es un `dict` JSON-able (ver sección 5). La UI puede mostrar, p.ej.,
  “Página 3 rasterizada: fuente Type3”.
- El flag `OUTLINER_ENGINE` (env) selecciona motor: `internal` (default) usa este
  motor; `ghostscript` **se rechaza por diseño** (lanza `NotImplementedError`) — es
  justo la dependencia AGPL que se elimina. No hace falta configurarlo en producción.

### 4.5 Retirar Ghostscript
Una vez el router usa el motor interno:
- Borra la rama muerta de Ghostscript del módulo `outliner` (el código que invocaba
  `gswin`/`gs`).
- Quítalo de `requirements`/instalador, `start.ps1` y docs de despliegue.
- **Grep de seguridad** (debe salir vacío en código de producción):
  `grep -rniE "ghostscript|gswin|pdftocairo|mupdf|\bfitz\b|poppler" backend/app/`
  (las únicas menciones admisibles son las que **rechazan/documentan** GS, como el
  `NotImplementedError` del servicio).

### 4.6 Atribuciones legales in-app
Incorpora `THIRD_PARTY_NOTICES.md` a los avisos legales (§13/about):
- **quitar** Ghostscript;
- **añadir** pdfium vía pypdfium2 (incluir el identificador SPDX
  `LicenseRef-PdfiumThirdParty` — FreeType/libpng/zlib/… todos permisivos) y el
  crédito FreeType (FTL), y **pikepdf (MPL-2.0)**.
- Nota para el research de licencias: con esto, el único AGPL restante del proyecto
  es PyMuPDF (migración aparte).

---

## 5. Contrato del endpoint / UI (el `report`)

`report` (de `report_dict = result.report.to_dict()`):

```jsonc
{
  "engine": "internal",
  "pages": [
    {
      "index": 0,                 // 0-based
      "outlined": true,           // texto convertido a curvas en esta pagina
      "outlined_glyphs": 142,     // glifos emitidos como paths
      "fallback": "",             // "" | "raster" | "skip"
      "reason": "",               // motivo si fallback/skip
      "removed_fonts": ["ABCDEF+DejaVuSans"],
      "warnings": []              // p.ej. fuente no incrustada, verificacion no posible
    }
  ],
  "total_outlined_glyphs": 142,
  "any_fallback": false,
  "fallback_pages": [],           // indices que cayeron a fallback
  "warnings": ["p2: ..."]         // warnings agregados con prefijo de pagina
}
```

**Semántica de `fallback`** (opción del servicio, default `raster`):
- `raster`: la página no convertible se **rasteriza** (imagen a página completa,
  `raster_dpi`, mín. 300). Se pierde vectorial pero el resultado es fiel. Siempre
  marcado en el report.
- `skip`: la página no convertible se **deja como el original** (texto intacto, con
  sus fuentes). Útil si prefieres “no tocar” a rasterizar.
- `error`: lanza `UnsupportedContentError` en cuanto una página no es convertible
  (útil para validación estricta previa).

**Qué mostrar al usuario**: si `any_fallback`, avisar qué páginas se rasterizaron y
por qué (`reason`); si hay `warnings` de “fuente no incrustada”, avisar que esos
contornos usan una fuente de sustitución (pueden no ser 100% fieles al original).

---

## 6. Verificación (checklist de cierre)

1. `pip install -r requirements.txt -r requirements-dev.txt` sin errores.
2. `python -c "import pypdfium2 as p; print(p.version.PDFIUM_INFO)"` → `151.0.7920.0`.
3. `python -m pytest backend/tests/outline_engine -q` → **96 passed** (ajusta si el
   monorepo añade tests). Incluye el smoke de símbolos y el experimento de coordenadas.
4. Grep de Ghostscript/AGPL limpio (paso 4.5).
5. `grep` de un único lock de pdfium (paso 4.3).
6. **Ritual de reinicio** (backend): parar la tarea PrintHub, matar el PID del
   puerto 8000, arrancar, y smoke del endpoint:
   `curl.exe -k -F "file=@algo.pdf" https://localhost:8000/api/outliner...` → PDF de
   salida + `report` con `outlined: true` y sin fuentes.
7. Abrir un PDF de salida en un visor y confirmar: se ve igual, el texto **no se
   selecciona** (ya son curvas), y `/Font` está vacío.

---

## 7. Limitaciones conocidas (comunicar en la UI, no son bugs)

Van a **fallback raster** con `reason` claro (comportamiento por diseño, sin corrupción):
- **Texto con stroke / fill-stroke / clip** (render modes 1/2/4-7): hoy → fallback.
  Emitir `S`/`B` con color y ancho de línea es mejora futura.
- **Fuentes Type3**: → fallback (no se convierten en la v1).
- **Texto en apariencias de anotaciones** (form/FreeText/stamp) y **texto dentro de
  tiling Patterns**: → fallback.
- **Glifos sin unicode fiable** (CID sin ToUnicode, remapeos raros): el self-check
  por glifo los detecta → fallback (evita el glifo-erróneo silencioso).

Comportamiento correcto (no fallback):
- **Fuentes no incrustadas**: se outlinean con la fuente de sustitución de pdfium +
  **warning** (pueden no ser fieles). Si prefieres fallback aquí, es un cambio de
  política de una línea en `engine.py`.
- **Texto en Form XObjects**: se aplana y se outlinea.

**Coste de la verificación por render**: `verify_render=True` (default) hace un
render extra por página outlineada a 300 dpi. Es la red que garantiza “nunca
corrupción silenciosa”. Se puede desactivar/tunear vía `OutlineOpts(verify_render=…,
verify_dpi=…, verify_threshold=…)` si el volumen lo exige, pero **no se recomienda
desactivarla** en producción.

---

## 8. Riesgos y gotchas

- **No mantener vivo el `PdfPage`**: acceder a `page.raw` y dejar que el objeto
  Python se recolecte deja un handle colgando → segfault. El motor ya lo hace bien
  (mantiene `page = doc[i]` vivo); replícalo si añades código pdfium.
- **Dos locks**: el error más fácil de cometer. Un único `RLock` para pdfium (4.3).
- **Determinismo**: la salida es determinista (`deterministic_id=True`) — útil para
  cache/history; no lo cambies a `/ID` aleatorio sin motivo.
- **Fixtures del corpus**: se generan de forma determinista con `gen_corpus.py`
  (reportlab + fontTools con `recalcTimestamp=False`). Si un test de corpus falla
  tras copiar, regenera: `python backend/tests/outline_engine/gen_corpus.py`.
- **cp1252**: cualquier `print`/log nuevo del backend en ASCII con `->`.

---

## 9. Referencias del repo del motor

- `docs/PLAN_MOTOR_OUTLINER.md` — plan por fases + ESTADO FINAL + criterios de salida.
- `docs/PROYECTO.md` — contexto de PrintHub/ImprintiaSuite.
- `THIRD_PARTY_NOTICES.md` — atribuciones a incorporar al about in-app.
- `backend/app/core/outline_engine/glyphs.py` (cabecera) — conclusión del experimento
  de coordenadas (arg de `FPDFFont_GetGlyphPath` = **codepoint Unicode**; regla de
  colocación glifo→página). Todo el motor depende de eso.
