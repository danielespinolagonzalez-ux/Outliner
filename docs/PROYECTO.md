# PrintHub / ImprintiaSuite — Visión global del proyecto

> Documento de contexto para IAs y para retomar el proyecto. Resume **qué es**,
> **para quién**, **cómo está montado** y **qué se ha construido**. Última
> actualización: 2026-07-08.

---

## 1. Qué es

**PrintHub** (marca de producto: **ImprintiaSuite**, "by debisual") es una **suite
web de preimpresión e imprenta** que unifica en una sola app muchas herramientas
del día a día de una **copistería / imprenta de barrio**: imposición, montaje,
talonarios, artes finales, DTF textil, fotos de carnet, collages, una suite
completa de edición de PDF e imagen, generadores (QR, códigos de barras) y un
**estudio de IA** para crear y preparar imágenes.

- **Origen:** nació unificando 5 proyectos independientes del mismo dominio
  (Montador de Cartas, montador de archivos, talonarios, Montador Talonarios,
  Collage Maker) en un único monorepo web. La base arquitectónica es el "Montador
  de Cartas" (React+FastAPI). Los proyectos originales **no se tocan**; PrintHub
  copió/adaptó su código.
- **Cliente objetivo:** pequeñas copisterías que quieren **ahorrar tiempo** y
  ofrecer servicios (carnets, tarjetas, textil, etc.) sin ser diseñadores.
- **Filosofía de UX:** "**modo fácil**" — asistentes guiados tipo *typeform* que
  traducen lo que quiere un usuario sin experiencia a un resultado profesional.
  Lenguaje sencillo, tú-a-tú. Junto a cada modo fácil suele haber un "modo
  avanzado" con todos los controles.

---

## 2. Stack y cómo arranca

- **Frontend:** React + TypeScript + Vite. Zustand para estado por módulo.
  Router (`react-router-dom`). Un solo `styles.css` con tokens de marca *debisual*
  (fuentes corporativas en `Z:\corporativo`, paleta, `--font-display/mono`).
- **Backend:** FastAPI (Python) + **PyMuPDF (`fitz`)** para todo lo de PDF/render,
  Pillow para imagen, numpy/rectpack para nesting, segno (QR), Ghostscript
  (texto a curvas). `requests` para APIs externas.
- **Servido en producción:** FastAPI sirve el build estático (`frontend/dist`) y
  la API en **un solo puerto (8000)** con fallback SPA. Corre siempre como
  **Tarea Programada de Windows "PrintHub"** en `https://localhost:8000`
  (certificado mkcert). Arranque: `start.ps1` (crea venv la 1ª vez, instala
  requirements, lanza uvicorn).
- **Ritual al cambiar backend (Windows):** parar la tarea → **matar el PID del
  puerto 8000** (uvicorn deja el socket huérfano) → arrancar la tarea → verificar
  con `curl.exe -k https://localhost:8000/...`. Si no, se sirve código viejo.
- **Dev:** Vite en `:5173` (proxya `/api` al backend). El backend en prod sirve
  `dist`, así que **hay que recompilar (`npm run build`) y reiniciar la tarea**
  para que el usuario vea cambios de frontend.

### Estructura del monorepo (resumen)
```
PrintHub/
├─ start.ps1
├─ backend/app/
│  ├─ main.py                 # monta todos los routers + static
│  ├─ core/                   # NÚCLEO COMPARTIDO: units, models, imposition,
│  │                          # bleed, color(ICC/CMYK), marks, numbering,
│  │                          # pdfbuild, render, fonts, presets, history
│  ├─ platform/               # credits.py (ledger IA), entitlements, plans
│  └─ modules/<x>/            # cada módulo: router.py (+ ops/service/schemas)
│     ├─ cards, impose, booklets, finals, collage, dtf, photo, idphoto
│     ├─ pdf, img, outliner, qr, resenas, barcode, preflight, calc
│     └─ ai/                  # estudio de IA (Recraft + Gemini/nano-banana)
└─ frontend/src/
   ├─ App.tsx / router        # rutas /<modulo>
   ├─ shared/                 # Dropzone, DownloadResult, ModuleHeader, toast,
   │                          # BackToHub, credits store, upload bus…
   ├─ platform/credits.ts     # store de saldo de créditos
   └─ modules/<x>/            # store Zustand + componentes por módulo
```
- **Datos de trabajo:** `backend/workdir/` (fuera de git): uploads, credits,
  history, tokens, proyectos DTF, etc.
- **Historial:** `core/history.record(module, name, bytes, ext)` guarda cada
  salida en `workdir/history/` (carpeta **compartida** por todos los módulos) y
  alimenta "Trabajos recientes" en la Home.

---

## 3. Módulos (por categoría de la barra lateral)

### IMPRIMIR Y MONTAR
- **Montaje avanzado** (`/cards`, módulo *cards*): imposición de cartas TCG y de
  impresión; CMYK/ICC, dúplex, capas OCG, dorso por archivo, nesting de medidas
  distintas (pliego/rollo, marcas, CMYK). Tiene un asistente "¿Qué quieres montar?"
  con presets.
- **Imposición de máquina** (`/impose`, *impose*): imposición de tarjetas/flyers,
  perfiles de máquina, corte-y-apila, multipágina.
- **Talonarios** (`/booklets`, *booklets*): numeración (formato/secuencias/orden
  guillotina), original+copias con etiqueta, N numeraciones × M posiciones,
  fuentes TTF/OTF subidas, drag-drop de posiciones (overlay SVG en mm).
- **Artes finales** (`/finals`, *finals*): imposición de revistas/libritos
  (folleto/cuadernillo unificados), preflight visual.
- **DTF para textil** (`/dtf`, *dtf*): montaje bajo demanda (botón "Optimizar"),
  nesting *true-shape* (silueta + skyline con numpy), pliego/rollo, cachés
  (silueta/recorte/layout/preview), proyectos guardables.
- **Impresión de fotos** (`/photo`, *photo*): tamaños, recorte cover/fit
  interactivo, N-up.
- **Fotos de carnet** (`/carnet`, *idphoto*): recorte a tamaño oficial (DNI 26×32,
  pasaporte 35×45, etc.), **plancha cabeza-con-cabeza** (filas pares giradas 180°),
  **presets "modo fácil"** (8 de carné que llenan el 10×15 / 1 de cartera 76×102
  + 4 de carné, todo pegado sin márgenes), **captura desde el móvil por QR**
  (sesión efímera + `/m/foto/:sid` desnudo), **quitar fondo con IA automático**
  (toggle), e **impresión directa** a impresora (SumatraPDF `-print-to noscale`).
- **Collage** (`/collage`, *collage*): layouts automáticos + editor interactivo
  (canvas), export PDF/imagen.

### PREPARAR ARCHIVO
- **Revisar arte final** (*preflight/review*): comprobaciones de arte.
- **Texto a curvas** (`/outliner`, *outliner*): Ghostscript.
- **Calculadoras** (`/calc`, *calc*): calculadoras de imprenta.
- **Herramientas PDF** (`/pdf`, *pdf*): suite estilo iLovePDF, ~15 herramientas
  nativas PyMuPDF (unir, dividir, organizar visual, rotar, marca de agua,
  comprimir, proteger/desbloquear, recortar, JPG↔PDF, extraer texto, quitar
  páginas en blanco…), **cola de trabajos**, drag global, pegar, "Crear PDF"
  (builder mezclando PDF+imágenes), página "Automatizar" (recetas encadenadas).
- **Herramientas de imagen** (`/imagen`, *img*): ops Pillow (rejilla + página de
  herramienta).

### CREAR / IA
- **Estudio de IA** (`/ia`, *ai*): ver sección 4 (el grueso del trabajo reciente).
- **Generador de QR** (`/qr`, *qr*): segno.
- **QR de reseñas Google** (`/resenas`): Google Places API (clave en su sitio).
- **Códigos de barras** (`/barcode`).

### MODO FÁCIL (`/facil`, *easy*)
Asistentes por pasos (shell `EasyShell`/`EasyNav`) para imposición, fotos, collage,
etc. Home de bienvenida orientada a tareas.

---

## 4. Estudio de IA (`/ia`) — el foco reciente

Hub de herramientas de IA de imagen. **Dos proveedores, con roles separados:**

### 4.1. Generación de imágenes → **SÓLO nano-banana (Google Gemini)**
- **Por qué no Recraft:** la **API** de Recraft NO expone nano-banana (solo su
  editor web); solo tiene sus 16 modelos propios. Se retiró Recraft de la
  generación por decisión del usuario.
- **Proveedor:** API directa de Google Gemini. `backend/app/modules/ai/gemini.py`,
  endpoint `…/v1beta/models/{model}:generateContent`, cabecera `x-goog-api-key`.
  **Clave: `GEMINI_API_KEY` (env) o `backend/workdir/gemini_token.txt`** (BYOK).
  Devuelve la imagen en `candidates[].content.parts[].inlineData.data` (base64).
  1 imagen por llamada → para `n` se llama `n` veces. Aspect ratio por
  `generationConfig.imageConfig.aspectRatio` (con **fallback**: si da 400 por ese
  campo, reintenta sin él).
- **Versiones (IDs verificados jul-2026):** en la UI se ofrecen **2**:
  - **Nano Banana 2** = `gemini-3.1-flash-image` — recomendada, `ia.generate.nano` = **4 cr**.
  - **Nano Banana Pro** = `gemini-3-pro-image` — máxima calidad y **mejor texto**,
    `ia.generate.nano.pro` = **12 cr** (el selector avisa de que gasta más).
  - (El backend `gemini.MODELS` también conoce `nano2_lite` y `nano1` legacy.)
- **Router:** `POST /api/ia/generate` y `/generate-ref` aceptan `engine:"gemini"`,
  `aspect_ratio`, `nano_version`; op de crédito por `_nano_op(version)`. `n>1`
  devuelve un **ZIP** que el frontend descomprime con **jszip** (fijando el MIME
  por extensión: un SVG/PNG mal etiquetado no renderiza en `<img>`).

### 4.2. Prompts ocultos optimizados (el "cerebro")
`frontend/src/modules/ai/wizard/planner.ts` traduce un *brief* (respuestas del
usuario) a un **prompt óptimo para nano-banana**, con reglas de una investigación
a fondo de la doc oficial de Google:
- Prompt **narrativo** (frases, no lista de keywords) e hiper-específico.
- **En positivo** ("fondo blanco liso sin más elementos", no "sin fondo").
- **Texto exacto entre comillas** + tipografía por atributos + "render exactly this
  text and nothing else" (evita erratas e inventos).
- **Resolución + proporción** al final (4K para poster/flyer/camiseta/mockup,
  2K resto).
- `HIDDEN_BY_JOB` (por tipo de pieza) y `STYLE_PROMPT` (glosario) con lenguaje
  fotográfico: cámara/luz de estudio y fondo blanco puro para producto, tinta
  plana/single-ink para logo, die-cut para sticker, seamless para patrón…

### 4.3. Asistentes guiados (modo fácil)
- **Crear imagen paso a paso** (`/ia/asistente`, `GenerateWizard.tsx`): typeform
  de 7 pasos (Qué·Formato·Contenido·Estilo·Color·Texto·Crear). Genera **4
  propuestas directas** (no hay paso "Pro final"; para más tamaño → upscaler).
  Selector de calidad Nano Banana 2 / Pro con créditos. **Imagen de referencia**
  opcional (edición con foto). Descarga la elegida.
- **Tarjeta de visita** (`/ia/tarjeta`, `BusinessCardWizard.tsx`): typeform de 5
  pasos (Negocio·Contacto·Estilo·Color·Crear) que "traduce" un formulario a un
  prompt de tarjeta (`buildCardPrompt`): texto exacto por bloques (nombre, eslogan,
  persona/cargo) + bloque de contacto (tel, WhatsApp, email, web, dirección,
  Instagram) con line-icons, estilo (8) + orientación (→ ratio 3:2/2:3), paleta
  (6 presets + personalizada), **logo opcional** (referencia). Por defecto **Pro**
  (mejor texto). Prompt **a sangre completa** (si no, nano dibuja la tarjeta
  flotando con sombra sobre fondo gris). Extras tras elegir: **reverso a juego**
  (usa la cara elegida como referencia para coherencia) y **montaje a tamaño real**.
- **Generador avanzado** (`/ia/generate`, `GeneratePage.tsx`): modo manual, solo
  nano-banana (se quitaron los controles de Recraft). Prompt libre + versión +
  formato + nº + referencia + texto exacto + "✨ Mejorar descripción".

### 4.4. Montaje de tarjetas a tamaño real
`backend/app/modules/ai/cardmontage.py` + `POST /api/ia/card-sheet`
(`CardSheetJob`). Compone un **PDF listo para imprenta**: N tarjetas por hoja
(auto-orienta la hoja; ~9 en A4) al **tamaño físico exacto** (85×55 o 90×50),
imagen en "cover" al **bleed box** (sangrado, sin borde blanco) + **marcas de
corte** por esquina; front pág.1, reverso pág.2. Solo maquetación (PyMuPDF), **no
cobra créditos**.

### 4.5. Otras herramientas de IA → **Recraft** (se mantienen)
Recraft (`service.py`, clave `RECRAFT_API_TOKEN` o `workdir/recraft_token.txt`)
sigue para: **quitar fondo**, **aumentar resolución** (crisp/creative),
**expandir/sangrado** (outpaint), **vectorizar** (raster→SVG), **reemplazar
fondo**, **borrar objeto / retocar** (máscara con editor de pincel). El upscale
con Replicate se retiró (todo con Recraft para esas ops).

---

## 5. Créditos de IA

`backend/app/platform/credits.py` — **ledger genérico**. Toda op de IA de coste
variable se cobra en *créditos* (`AI_OPERATIONS`, p. ej. `ia.removebg`=1,
`ia.generate.nano`=4, `ia.generate.nano.pro`=12…). Saldo por cuenta =
**cuota mensual del plan** (se resetea cada mes) **+ créditos comprados**.
Se cobra **solo en éxito** (pre-chequeo antes de gastar en la API). Frontend:
`platform/credits.ts` (saldo global en la barra lateral, coste previo por op,
bloqueo si no alcanza). En on-prem/BYOK el saldo es **ilimitado (∞)**.
**Pendiente:** pasarela de pago (#108) y precios reales de packs (#109); las cifras
de crédito son de arranque.

---

## 6. Comercialización, licencias, web

- **Licencia del software:** **AGPL-3.0** (por PyMuPDF). Avisos de terceros,
  oferta de código fuente in-app (§13), about. **Ojo legal:** PyMuPDF es AGPL →
  en SaaS la cláusula de red puede obligar a publicar el backend; para on-prem es
  distribución. Alternativa: licencia comercial de Artifex o migrar a
  PDFium/pypdfium2 (BSD) para ciertas funciones. (Hay un research sobre esto.)
- **Licenciamiento del producto:** licencia firmada Ed25519 (verify backend +
  keygen + generador), modo on-prem en `entitlements`, endpoints/UI de activación,
  empaquetado distribuible + instalador de cliente.
- **Web comercial (venta):** proyecto **Astro** aparte en `web/` (no toca
  `frontend/`): multipágina, SEO por página (sitemap, JSON-LD, canonical, OG),
  solo español, con Precios + Comparativas ("alternativa a…") + Blog + Legales.
  URL base configurable por `SITE_URL`/`APP_URL`. Copy en `docs/landings/*.md`.
  Plan SaaS modular en `docs/PLAN-COMERCIAL.md`.

---

## 7. Convenciones y gotchas técnicos (importantes)

- **Windows:** consola cp1252 no encodea Unicode (usar ASCII "->", no flechas en
  prints). Bash `/tmp` = AppData\Local\Temp; para curl usar rutas Windows en `-o`.
  El venv del backend está en `backend/.venv`.
- **Reinicio del socket 8000** (ver §2): imprescindible tras cambios de backend.
- **jszip + MIME:** al descomprimir el ZIP de n>1, fijar el MIME por extensión
  (SVG→`image/svg+xml`); un SVG servido como `image/png` no renderiza.
- **Recraft V4.1:** solo acepta 6 tamaños; Pro usa el mismo `size` que estándar;
  vector va por ratio; usar solo IDs de modelo documentados. (Relevante solo para
  las herramientas Recraft, ya no para generación.)
- **nano-banana:** RGB con SynthID invisible, **sin CMYK/sangrado/Pantone
  nativos** → generar a máxima resolución y reperfilar a CMYK + añadir sangrado
  aguas abajo (en PrintHub). El texto largo/crítico: mejor Pro, o dejar hueco y
  poner texto vectorial real en la maqueta.
- **Impresión directa:** SumatraPDF (`-print-to "impresora" -print-settings
  noscale`) imprime PDF al tamaño exacto sin diálogo; impresoras vía `Get-Printer`
  (PowerShell, sin pywin32).
- **Historial compartido:** `workdir/history/` mezcla salidas de todos los
  módulos; no asumir que el .jpg más reciente es de un módulo concreto.

---

## 8. Estado y pendientes

- **Hecho y verificado en vivo:** generación con nano-banana (2 y Pro), asistente
  de imagen, asistente de tarjeta de visita (+reverso +montaje a sangre con marcas),
  fotos de carnet (planchas + impresión directa), y el grueso de módulos de
  imprenta/PDF/imagen.
- **Pendiente:** pasarela de pago (#108), precios reales de créditos (#109),
  conversión CMYK estricta del arte generado por IA, y decisiones legales sobre
  PyMuPDF/AGPL antes de vender el SaaS.
- **Ideas de roadmap:** VDP (datos variables), más presets de tarjeta/carnet,
  enlazar el resultado de IA directo a impresión, guardar datos del cliente.

---

### Glosario rápido de rutas API relevantes (módulo IA)
- `GET /api/ia/status` → `{configured (Recraft), gemini_configured, operations, packs, balance}`
- `POST /api/ia/generate` → genera (engine gemini + nano_version + aspect_ratio); 1 img o ZIP
- `POST /api/ia/generate-ref` → genera a partir de imagen de referencia (asset_id)
- `POST /api/ia/card-sheet` → PDF de montaje de tarjetas (no cobra)
- `POST /api/ia/remove-bg | /upscale | /expand | /vectorize | /replace-bg | /erase | /inpaint` → Recraft
- `POST /api/ia/assets` → sube imagen y devuelve `asset_id`
