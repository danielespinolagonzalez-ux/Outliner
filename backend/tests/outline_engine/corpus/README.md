# Corpus de prueba del motor outliner (Fase 0)

PDFs deterministas generados por `../gen_corpus.py`. Se regeneran con:

```
python backend/tests/outline_engine/gen_corpus.py      # sobreescribe todos
```

Cada fixture aisla una propiedad que el motor texto-a-curvas debe manejar. La
validacion estructural esta en `../test_corpus.py`.

| PDF | Que ejercita |
|---|---|
| `latino_ttf.pdf` | Texto latino (con acentos) + TrueType (DejaVu) incrustada, `/FontFile2`. Subset por reportlab. |
| `latino_cff.pdf` | CFF/OpenType (Source Sans 3) incrustada, `/FontFile3` `/Type1C`. Glifos con curvas cubicas. |
| `subset.pdf` | Fuente subsetada -> prefijo de subset en `/BaseFont` (p.ej. `AAAAAA+DejaVuSans`). |
| `multipos.pdf` | Texto rotado + escalado (matriz no identidad) y kerning real (operador `TJ`). |
| `color_cmyk.pdf` | Texto en color CMYK (naranja, azul) y en gris. |
| `mixto.pdf` | Texto + imagen (bitmap) + vectores (rect/linea/circulo). Lo no-texto debe quedar intacto. |
| `no_embebida.pdf` | Fuente NO incrustada (Helvetica base-14). Caso duro -> fallback (fase 3). |
| `type3.pdf` | Fuente Type3 (glifos dibujados con operadores). Caso duro -> fallback (fase 3). |
| `remapped.pdf` | TrueType con `/Encoding /Differences` que remapea bytes 0x01..0x04 -> H,o,l,a: **charcode != unicode**. Prueba que la extraccion por unicode (`FPDFText_GetUnicode` -> `get_glyph_outline`) es robusta (el arg de `FPDFFont_GetGlyphPath` es el unicode, no el charcode). |
| `xobject_text.pdf` | Texto DENTRO de un Form XObject (via `Do`). El motor lo aplana (textpage), neutraliza el texto del XObject y lo outlinea a nivel de pagina. |
| `cid.pdf` | Fuente CID Type0 Identity-H (CIDFontType2) CON ToUnicode -> se outlinea por unicode. |
| `cid_no_unicode.pdf` | CID Type0 Identity-H SIN ToUnicode: el "unicode" del textpage es el GID (no fiable). El self-check por-glifo detecta el desajuste -> **fallback** (evita corrupcion silenciosa). |

## Fuentes vendorizadas (`_fonts/`)

Se incluyen para que la generacion sea reproducible en cualquier plataforma
(incluido Windows, donde no existe `/usr/share/fonts`). Ambas son **permisivas**
(sin GPL/AGPL, acorde a la restriccion del proyecto):

- **DejaVuSans.ttf** -> licencia Bitstream Vera (permisiva, tipo MIT) + los
  cambios de DejaVu son de dominio publico. Ver `_fonts/DejaVuSans-LICENSE.txt`.
- **SourceSans3-Regular.otf** -> (c) 2023 Adobe, SIL Open Font License 1.1
  (Reserved Font Name 'Source'). Ver `_fonts/SourceSans3-OFL.txt`.

> Nota: reportlab NO incrusta contornos PostScript/CFF ("postscript outlines are
> not supported"), asi que `latino_cff.pdf` y `multipos.pdf` se construyen con un
> incrustador de fuente simple propio (pikepdf + fontTools, WinAnsiEncoding) en
> `gen_corpus.py::_embed_simple_font`.
