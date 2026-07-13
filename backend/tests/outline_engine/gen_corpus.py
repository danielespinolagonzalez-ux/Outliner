"""FASE 0 - Generador del corpus de PDFs de prueba del motor outliner.

Crea PDFs deterministas que cubren los casos que el motor debe manejar:
fuentes TTF/CFF incrustadas, subsets, texto posicionado (rotacion/escala/TJ),
color CMYK/gris, contenido mixto (texto+imagen+vectores), fuente no incrustada
y Type3 (caso duro para fallback).

Se puede usar como script (regenera todo) o desde conftest (regenera lo que
falte). Fuentes vendorizadas en corpus/_fonts/ (todas permisivas: DejaVu =
Bitstream Vera; Source Sans 3 = OFL-1.1). Ver corpus/_fonts/*LICENSE*/*OFL*.

Herramientas: reportlab (BSD), pikepdf (MPL-2.0), fontTools (MIT), Pillow (HPND).
Sin GPL/AGPL. cp1252: prints en ASCII, usar '->'.
"""

import io
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont as FTFont

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

THIS_DIR = Path(__file__).resolve().parent
CORPUS_DIR = THIS_DIR / "corpus"
FONTS_DIR = CORPUS_DIR / "_fonts"
DEJAVU = FONTS_DIR / "DejaVuSans.ttf"
SOURCESANS = FONTS_DIR / "SourceSans3-Regular.otf"

# Rango ASCII imprimible que se subsetea/mide en los embebidos manuales.
FIRST_CHAR, LAST_CHAR = 32, 126


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _pdf_escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _register_dejavu(name="DejaVu"):
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(DEJAVU)))
    return name


def _embed_simple_font(pdf, font_path, sample_text, is_cff):
    """Incrusta una fuente simple (Type1/CFF o TrueType) con WinAnsiEncoding.

    Devuelve (font_obj_indirecto, psname). Da control total del encoding para
    poder emitir operadores TJ con codigos ASCII conocidos (multipos, cff).
    """
    f = FTFont(str(font_path))
    upm = f["head"].unitsPerEm

    opts = Options()
    opts.notdef_outline = True
    opts.recalc_bounds = True
    if is_cff:
        opts.name_IDs = ["*"]
    subsetter = Subsetter(options=opts)
    wanted = set(sample_text) | {chr(c) for c in range(FIRST_CHAR, LAST_CHAR + 1)}
    subsetter.populate(unicodes=[ord(c) for c in wanted])
    subsetter.subset(f)

    cmap = f.getBestCmap()
    hmtx = f["hmtx"]
    scale = 1000.0 / upm
    widths = []
    for code in range(FIRST_CHAR, LAST_CHAR + 1):
        gname = cmap.get(code)
        adv = hmtx[gname][0] if gname and gname in hmtx.metrics else 0
        widths.append(round(adv * scale))

    head = f["head"]
    os2 = f.get("OS/2")
    post = f["post"]
    psname = f["name"].getDebugName(6) or "EmbeddedFont"
    bbox = [round(v * scale) for v in (head.xMin, head.yMin, head.xMax, head.yMax)]

    if is_cff:
        program = f.getTableData("CFF ")
        subtype, ff_key, ff_subtype = "/Type1", "/FontFile3", "/Type1C"
    else:
        buf = io.BytesIO()
        f.save(buf)
        program = buf.getvalue()
        subtype, ff_key, ff_subtype = "/TrueType", "/FontFile2", None
    f.close()

    fontfile = pdf.make_stream(program)
    if ff_subtype is not None:
        fontfile.Subtype = Name(ff_subtype)
    else:
        fontfile.Length1 = len(program)  # longitud del programa TrueType sin comprimir

    descriptor = pdf.make_indirect(Dictionary(
        Type=Name("/FontDescriptor"),
        FontName=Name("/" + psname),
        Flags=4,  # Symbolic=0, Nonsymbolic path via WinAnsi; 4 = Serif? usamos 32 abajo
        FontBBox=Array(bbox),
        ItalicAngle=post.italicAngle,
        Ascent=round(getattr(os2, "sTypoAscender", head.yMax) * scale),
        Descent=round(getattr(os2, "sTypoDescender", head.yMin) * scale),
        CapHeight=round(getattr(os2, "sCapHeight", 700) * scale),
        StemV=80,
    ))
    descriptor.Flags = 32  # Nonsymbolic
    descriptor[Name(ff_key)] = pdf.make_indirect(fontfile)

    font = pdf.make_indirect(Dictionary(
        Type=Name("/Font"),
        Subtype=Name(subtype),
        BaseFont=Name("/" + psname),
        FirstChar=FIRST_CHAR,
        LastChar=LAST_CHAR,
        Widths=Array(widths),
        Encoding=Name("/WinAnsiEncoding"),
        FontDescriptor=descriptor,
    ))
    return font, psname


# --------------------------------------------------------------------------
# Generadores (cada uno devuelve bytes de un PDF)
# --------------------------------------------------------------------------
def gen_latino_ttf():
    """Texto latino con TrueType (DejaVu) incrustada (subset por reportlab)."""
    name = _register_dejavu()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(420, 240))
    c.setFont(name, 22)
    c.drawString(30, 190, "Outliner motor de texto a curvas")
    c.setFont(name, 16)
    for i, line in enumerate([
        "Texto latino con acentos: Camión, niño, árbol, señal.",
        "The quick brown fox jumps over the lazy dog.",
        "0123456789 - punto, coma; dos puntos: guion.",
    ]):
        c.drawString(30, 150 - i * 26, line)
    c.showPage()
    c.save()
    return buf.getvalue()


def gen_latino_cff():
    """Texto latino con CFF/OpenType (Source Sans 3) incrustada (FontFile3/Type1C)."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(420, 200))
    text1 = "Source Sans 3 CFF outline"
    text2 = "Curvas cubicas: aeosgh 0123456789"
    font, _ = _embed_simple_font(pdf, SOURCESANS, text1 + text2, is_cff=True)
    page.Resources = Dictionary(Font=Dictionary(F1=font))
    body = "BT /F1 26 Tf 30 130 Td ({0}) Tj 0 -40 Td ({1}) Tj ET".format(
        _pdf_escape(text1), _pdf_escape(text2))
    page.Contents = pdf.make_stream(body.encode("latin-1"))
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


def gen_subset():
    """Fuente subsetada: pocos glifos distintos -> prefijo de subset (XXXXXX+)."""
    name = _register_dejavu("DejaVuSub")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 120))
    c.setFont(name, 40)
    c.drawString(30, 50, "ABCDEF")  # solo 6 glifos -> subset evidente
    c.showPage()
    c.save()
    return buf.getvalue()


def gen_multipos():
    """Texto rotado + escalado + con kerning real (operador TJ)."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(420, 320))
    kern_text = "AVWAToYaWeVoLTPfi"  # letras tipicas de pares de kerning
    font, _ = _embed_simple_font(pdf, DEJAVU, kern_text, is_cff=False)
    page.Resources = Dictionary(Font=Dictionary(F1=font))
    # cm rotado 25 grados y escalado no uniforme (1.4 x 0.9); TJ con ajustes.
    import math
    ang = math.radians(25.0)
    ca, sa = math.cos(ang), math.sin(ang)
    a, b = 1.4 * ca, 1.4 * sa
    c_, d = -0.9 * sa, 0.9 * ca
    cm = "{0:.6f} {1:.6f} {2:.6f} {3:.6f} 60 120 cm".format(a, b, c_, d)
    tj = "[ (AVA) -160 (To) 90 (Ya) -140 (We) ] TJ"
    body = (
        "q " + cm + "\n"
        "BT /F1 26 Tf 0 0 Td " + tj + " ET\n"
        "BT /F1 18 Tf 0 -34 Td (Rotado + escalado 1.4x0.9) Tj ET\n"
        "Q\n"
        "BT /F1 16 Tf 30 40 Td (Linea horizontal de control) Tj ET"
    )
    page.Contents = pdf.make_stream(body.encode("latin-1"))
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


def gen_color_cmyk():
    """Texto en CMYK y en gris (DejaVu incrustada)."""
    name = _register_dejavu()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(360, 180))
    c.setFont(name, 26)
    c.setFillColorCMYK(0.05, 0.80, 0.90, 0.00)
    c.drawString(30, 120, "Texto CMYK naranja")
    c.setFillColorCMYK(0.90, 0.60, 0.00, 0.10)
    c.drawString(30, 85, "Texto CMYK azul")
    c.setFillGray(0.45)
    c.drawString(30, 50, "Texto gris 45 por ciento")
    c.showPage()
    c.save()
    return buf.getvalue()


def gen_mixto():
    """Texto + imagen (PNG via Pillow) + vectores. Lo no-texto debe quedar intacto."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (120, 80), (240, 240, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 60, 70], fill=(220, 60, 60))
    d.ellipse([60, 20, 110, 70], fill=(60, 120, 220))

    name = _register_dejavu()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(420, 260))
    # vectores
    c.setStrokeColorRGB(0.1, 0.5, 0.2)
    c.setLineWidth(2)
    c.rect(30, 30, 360, 200, stroke=1, fill=0)
    c.line(30, 130, 390, 130)
    c.setFillColorRGB(0.9, 0.8, 0.2)
    c.circle(340, 190, 25, stroke=1, fill=1)
    # imagen
    c.drawImage(ImageReader(img), 40, 145, width=120, height=80)
    # texto
    c.setFillColorRGB(0, 0, 0)
    c.setFont(name, 20)
    c.drawString(180, 190, "Texto + imagen")
    c.setFont(name, 14)
    c.drawString(40, 95, "Vectores y bitmap deben permanecer intactos")
    c.showPage()
    c.save()
    return buf.getvalue()


def gen_no_embebida():
    """Fuente NO incrustada (Helvetica base-14). Caso duro -> fallback fase 3."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(360, 140))
    c.setFont("Helvetica", 24)
    c.drawString(30, 90, "Helvetica no incrustada")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(30, 55, "Sin FontFile -> fuente de sustitucion")
    c.showPage()
    c.save()
    return buf.getvalue()


def gen_type3():
    """Fuente Type3 minima (glifos dibujados con operadores). Caso duro -> fallback."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(320, 160))
    # Glifos en espacio de 1000 unidades (FontMatrix 0.001): triangulo y barras.
    proc_a = pdf.make_stream(b"1000 0 d0\n120 0 m 500 780 l 880 0 l h f")
    proc_b = pdf.make_stream(b"1000 0 d0\n150 0 200 780 re f\n500 300 250 200 re f")
    char_procs = Dictionary(
        gA=pdf.make_indirect(proc_a),
        gB=pdf.make_indirect(proc_b),
    )
    encoding = Dictionary(
        Type=Name("/Encoding"),
        Differences=Array([65, Name("/gA"), 66, Name("/gB")]),
    )
    font = pdf.make_indirect(Dictionary(
        Type=Name("/Font"),
        Subtype=Name("/Type3"),
        FontBBox=Array([0, 0, 1000, 800]),
        FontMatrix=Array([0.001, 0, 0, 0.001, 0, 0]),
        CharProcs=char_procs,
        Encoding=encoding,
        FirstChar=65,
        LastChar=66,
        Widths=Array([1000, 1000]),
        Resources=Dictionary(),
    ))
    page.Resources = Dictionary(Font=Dictionary(T3=font))
    page.Contents = pdf.make_stream(b"BT /T3 48 Tf 40 60 Td (ABABAB) Tj ET")
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


# nombre -> generador
GENERATORS = {
    "latino_ttf.pdf": gen_latino_ttf,
    "latino_cff.pdf": gen_latino_cff,
    "subset.pdf": gen_subset,
    "multipos.pdf": gen_multipos,
    "color_cmyk.pdf": gen_color_cmyk,
    "mixto.pdf": gen_mixto,
    "no_embebida.pdf": gen_no_embebida,
    "type3.pdf": gen_type3,
}


def ensure_corpus(corpus_dir=CORPUS_DIR):
    """Genera los PDFs que falten y devuelve {nombre: Path}."""
    corpus_dir = Path(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, gen in GENERATORS.items():
        path = corpus_dir / name
        if not path.exists():
            path.write_bytes(gen())
        paths[name] = path
    return paths


def generate_all(corpus_dir=CORPUS_DIR):
    """Regenera TODOS los PDFs (sobreescribe)."""
    corpus_dir = Path(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for name, gen in GENERATORS.items():
        data = gen()
        (corpus_dir / name).write_bytes(data)
        print("[corpus] {0} -> {1} bytes".format(name, len(data)))


if __name__ == "__main__":
    generate_all()
