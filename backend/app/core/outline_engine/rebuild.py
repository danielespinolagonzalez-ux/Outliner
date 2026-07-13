"""Reconstruccion del PDF con pikepdf: texto -> paths, sin fuentes.

Estrategia MVP (ver PLAN 3.4): por pagina, se parte el/los content stream(s) en
tokens, se eliminan los bloques BT...ET completos (todo el texto) y se conserva
el resto tal cual; luego se anexan los glifos ya posicionados como paths de
relleno. Solo se aplica cuando engine.py garantiza que TODO el texto de la pagina
es outlineable. Se quitan las fuentes de /Resources y se limpian recursos.

NO usa pdfium -> no necesita PDFIUM_LOCK. cp1252: ASCII, usar '->'.

Limitaciones conocidas del MVP (documentadas para fases siguientes):
- Los paths se anexan al FINAL del contenido -> cambia el z-order del texto. Para
  el caso comun (texto por encima) es indistinguible; texto detras de elementos
  opacos podria variar.
- El relleno usa regla nonzero ('f') y color RGB opaco (se ignora alpha del texto).
"""

from typing import List

import pikepdf
from pikepdf import Name

from .glyphs import PositionedGlyph


def _num(v: float) -> str:
    # 3 decimales, compacto y estable
    return ("%.3f" % v)


def glyph_to_ops(glyph: PositionedGlyph) -> bytes:
    """Operadores de path (en coords de pagina) para un glifo posicionado."""
    place = glyph.placement
    r, g, b = (c / 255.0 for c in glyph.fill_rgb)
    ops: List[bytes] = [b"q", ("%.4f %.4f %.4f rg" % (r, g, b)).encode("latin-1")]
    for subpath in glyph.subpaths:
        for cmd in subpath:
            kind = cmd[0]
            if kind == "m":
                x, y = place.apply(cmd[1])
                ops.append(("%s %s m" % (_num(x), _num(y))).encode("latin-1"))
            elif kind == "l":
                x, y = place.apply(cmd[1])
                ops.append(("%s %s l" % (_num(x), _num(y))).encode("latin-1"))
            elif kind == "c":
                pts = [place.apply(p) for p in cmd[1:]]
                flat = " ".join("%s %s" % (_num(x), _num(y)) for x, y in pts)
                ops.append((flat + " c").encode("latin-1"))
            elif kind == "h":
                ops.append(b"h")
    ops.append(b"f")
    ops.append(b"Q")
    return b"\n".join(ops)


def glyphs_to_ops(glyphs: List[PositionedGlyph]) -> bytes:
    return b"\n".join(glyph_to_ops(g) for g in glyphs)


def strip_text(page: pikepdf.Page) -> bytes:
    """Devuelve el contenido de la pagina sin ningun bloque BT...ET."""
    kept = []
    depth = 0
    for operands, operator in pikepdf.parse_content_stream(page):
        op = str(operator)
        if op == "BT":
            depth += 1
            continue
        if op == "ET":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            kept.append((operands, operator))
    return pikepdf.unparse_content_stream(kept)


def remove_page_fonts(page: pikepdf.Page) -> List[str]:
    """Quita /Font de /Resources de la pagina. Devuelve nombres base quitados."""
    removed: List[str] = []
    res = page.get("/Resources")
    if res is None or "/Font" not in res:
        return removed
    fonts = res.Font
    for key in list(dict(fonts).keys()):
        try:
            fo = fonts[key]
            removed.append(str(fo.get("/BaseFont") or key))
        except Exception:
            removed.append(str(key))
    del res.Font
    return removed


def rebuild_page(pdf: pikepdf.Pdf, page: pikepdf.Page,
                 glyphs: List[PositionedGlyph]) -> List[str]:
    """Reescribe la pagina: quita texto, anexa glifos como paths, quita fuentes.

    Devuelve la lista de nombres de fuentes eliminadas.
    """
    body = strip_text(page)
    if glyphs:
        body = body + b"\n" + glyphs_to_ops(glyphs)
    page.Contents = pdf.make_stream(body)
    return remove_page_fonts(page)


# --------------------------------------------------------------------------
# Deteccion (nivel pikepdf) de contenido no outlineable en Fase 2
# --------------------------------------------------------------------------
def _content_has_text_op(source) -> bool:
    try:
        for _operands, operator in pikepdf.parse_content_stream(source):
            if str(operator) == "BT":
                return True
    except Exception:
        # fallback crudo si el stream no parsea
        try:
            return b"BT" in source.read_bytes()
        except Exception:
            return False
    return False


def _form_has_text(form, depth: int = 0) -> bool:
    if depth > 12:
        return False
    if _content_has_text_op(form):
        return True
    res = form.get("/Resources")
    if res is not None and "/XObject" in res:
        for _k, xo in dict(res.XObject).items():
            if xo.get("/Subtype") == Name("/Form") and _form_has_text(xo, depth + 1):
                return True
    return False


def page_has_xobject_text(page: pikepdf.Page) -> bool:
    """True si algun Form XObject (a cualquier anidamiento) contiene texto.

    Ese texto vive en el stream del XObject, NO en el de la pagina: strip_text no
    lo quitaria -> la pagina debe ir a fallback en Fase 2.
    """
    res = page.get("/Resources")
    if res is None or "/XObject" not in res:
        return False
    for _k, xo in dict(res.XObject).items():
        if xo.get("/Subtype") == Name("/Form") and _form_has_text(xo):
            return True
    return False


def _strip_text_bytes(source) -> bytes:
    """Contenido de un stream (page o form) sin bloques BT...ET."""
    kept = []
    depth = 0
    for operands, operator in pikepdf.parse_content_stream(source):
        op = str(operator)
        if op == "BT":
            depth += 1
            continue
        if op == "ET":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            kept.append((operands, operator))
    return pikepdf.unparse_content_stream(kept)


def _copy_form_stripped(pdf: pikepdf.Pdf, form, depth: int = 0):
    """COPIA privada de un Form XObject con el texto quitado (recursivo) y sin
    fuentes. No muta el original (que puede estar compartido)."""
    new_form = pdf.make_stream(_strip_text_bytes(form))
    for key in list(form.keys()):
        if key in ("/Length", "/Filter", "/DecodeParms"):
            continue
        new_form[key] = form[key]
    res = form.get("/Resources")
    if res is not None:
        new_res = pikepdf.Dictionary()
        for key in res.keys():
            new_res[key] = res[key]
        if "/Font" in new_res:
            del new_res.Font
        if "/XObject" in new_res:
            new_xo = pikepdf.Dictionary()
            for xk, xo in dict(new_res.XObject).items():
                if xo.get("/Subtype") == Name("/Form") and _form_has_text(xo, depth + 1):
                    new_xo[xk] = pdf.make_indirect(_copy_form_stripped(pdf, xo, depth + 1))
                else:
                    new_xo[xk] = xo
            new_res.XObject = new_xo
        new_form.Resources = new_res
    return new_form


def neutralize_xobject_text(pdf: pikepdf.Pdf, page: pikepdf.Page) -> List[str]:
    """Sustituye los Form XObjects con texto por copias privadas sin texto/fuentes.

    Permite outlinear paginas cuyo texto vive en XObjects: los glifos ya se emiten
    a nivel de pagina (la textpage los aplana en coords de pagina); esto elimina el
    texto original del XObject para que no se pinte doble ni queden fuentes.
    Devuelve nombres de fuentes eliminadas de los forms (best-effort). Lanza si algo
    va mal -> el llamador debe hacer fallback.
    """
    removed: List[str] = []
    res = page.get("/Resources")
    if res is None or "/XObject" not in res:
        return removed
    xobjs = res.XObject
    for key in list(dict(xobjs).keys()):
        xo = xobjs[key]
        if xo.get("/Subtype") == Name("/Form") and _form_has_text(xo):
            fr = xo.get("/Resources")
            if fr is not None and "/Font" in fr:
                for fk, fo in dict(fr.Font).items():
                    try:
                        removed.append(str(fo.get("/BaseFont") or fk))
                    except Exception:
                        removed.append(str(fk))
            xobjs[key] = pdf.make_indirect(_copy_form_stripped(pdf, xo))
    return removed


def page_type3_font_names(page: pikepdf.Page) -> List[str]:
    """Nombres de fuentes Type3 referenciadas a nivel de pagina (caso duro)."""
    out: List[str] = []
    res = page.get("/Resources")
    if res is None or "/Font" not in res:
        return out
    for key, fo in dict(res.Font).items():
        try:
            if fo.get("/Subtype") == Name("/Type3"):
                out.append(str(fo.get("/Name") or key))
        except Exception:
            continue
    return out


def page_font_names(page: pikepdf.Page) -> List[str]:
    """Nombres de fuentes referenciadas por la pagina (para asserts de test)."""
    res = page.get("/Resources")
    if res is None or "/Font" not in res:
        return []
    return [str(fo.get("/BaseFont") or key) for key, fo in dict(res.Font).items()]
