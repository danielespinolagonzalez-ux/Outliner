"""Geometria 2D del motor outliner: matrices afines estilo PDF y unidades.

Una matriz PDF es la tupla (a, b, c, d, e, f) que representa la afin

    [ a  b  0 ]
    [ c  d  0 ]      con puntos como vectores fila:  [x' y' 1] = [x y 1] . M
    [ e  f  1 ]

es decir:  x' = a*x + c*y + e ,  y' = b*x + d*y + f.

Composicion (convencion de vector fila): aplicar M1 y despues M2 equivale a la
matriz  M1.multiply(M2)  (producto M1 x M2). Esto coincide con la concatenacion
de matrices de PDF (el operador `cm`).

Conclusion de Fase 0 (ver glyphs.py): para llevar un punto de glifo en 'em' a
coordenadas de pagina se usa  Scale(font_size).multiply(ObjMatrix)  -> ver
`glyph_to_page`.

Modulo PURO: no depende de pdfium. cp1252: ASCII, usar '->'.
"""

from __future__ import annotations

import math
from typing import Iterable, NamedTuple, Tuple

Point = Tuple[float, float]

# Unidades: 1 pulgada = 25.4 mm = 72 pt.
MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
PT_PER_MM = PT_PER_INCH / MM_PER_INCH  # 72/25.4 ~ 2.834645...
MM_PER_PT = MM_PER_INCH / PT_PER_INCH  # 25.4/72 ~ 0.352777...


def mm_to_pt(mm: float) -> float:
    return mm * PT_PER_MM


def pt_to_mm(pt: float) -> float:
    return pt * MM_PER_PT


class Matrix(NamedTuple):
    """Matriz afin 2D estilo PDF (a, b, c, d, e, f).

    Es una NamedTuple -> se comporta como la tupla (a, b, c, d, e, f) que usan
    los helpers de pdfium (FPDFPageObj_GetMatrix), asi que interopera sin
    conversiones.
    """

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    # ---- constructores ----
    @classmethod
    def identity(cls) -> "Matrix":
        return cls(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    @classmethod
    def translation(cls, tx: float, ty: float) -> "Matrix":
        return cls(1.0, 0.0, 0.0, 1.0, float(tx), float(ty))

    @classmethod
    def scaling(cls, sx: float, sy: float = None) -> "Matrix":
        if sy is None:
            sy = sx
        return cls(float(sx), 0.0, 0.0, float(sy), 0.0, 0.0)

    @classmethod
    def rotation(cls, degrees: float) -> "Matrix":
        rad = math.radians(degrees)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return cls(cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)

    # ---- operaciones ----
    def apply(self, point: Point) -> Point:
        """Transforma un punto (vector fila): [x y 1] . self."""
        x, y = point
        return (self.a * x + self.c * y + self.e,
                self.b * x + self.d * y + self.f)

    def multiply(self, other: "Matrix") -> "Matrix":
        """Composicion: aplicar `self` y DESPUES `other` (producto self x other).

        Cumple:  self.multiply(other).apply(p) == other.apply(self.apply(p)).
        """
        a1, b1, c1, d1, e1, f1 = self
        a2, b2, c2, d2, e2, f2 = other
        return Matrix(
            a1 * a2 + b1 * c2,
            a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2,
            c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2,
            e1 * b2 + f1 * d2 + f2,
        )

    def then(self, other: "Matrix") -> "Matrix":
        """Alias legible de multiply: self.then(other) = self y luego other."""
        return self.multiply(other)

    def is_finite(self) -> bool:
        return all(math.isfinite(v) for v in self)

    def determinant(self) -> float:
        return self.a * self.d - self.b * self.c


def compose(*matrices: "Matrix") -> "Matrix":
    """Compone en ORDEN DE APLICACION: compose(m1, m2, m3) aplica m1, luego m2,
    luego m3. Equivale a m1.multiply(m2).multiply(m3)."""
    result = Matrix.identity()
    for m in matrices:
        result = result.multiply(m)
    return result


def glyph_to_page(obj_matrix: Iterable[float], font_size: float) -> "Matrix":
    """Matriz que lleva un punto de glifo en 'em' a coordenadas de pagina.

    Conclusion de Fase 0:  page = ObjMatrix . (font_size * em_point).
    En convencion de vector fila eso es aplicar Scale(font_size) y luego
    ObjMatrix -> Scale(font_size).multiply(ObjMatrix).

    `obj_matrix` es la (a, b, c, d, e, f) de FPDFPageObj_GetMatrix.
    """
    obj = obj_matrix if isinstance(obj_matrix, Matrix) else Matrix(*obj_matrix)
    return Matrix.scaling(font_size).multiply(obj)
