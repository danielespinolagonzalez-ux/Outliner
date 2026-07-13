"""FASE 1 - Tests puros de geometry.py (sin pdfium). cp1252: ASCII, '->'."""

import math

import pytest

from app.core.outline_engine.geometry import (
    MM_PER_PT,
    PT_PER_MM,
    Matrix,
    compose,
    glyph_to_page,
    mm_to_pt,
    pt_to_mm,
)


def _approx_pt(p, q, tol=1e-9):
    assert p[0] == pytest.approx(q[0], abs=tol)
    assert p[1] == pytest.approx(q[1], abs=tol)


# ---------------- constructores y apply ----------------
def test_identity_apply():
    m = Matrix.identity()
    assert m == (1, 0, 0, 1, 0, 0)
    _approx_pt(m.apply((3.5, -2.0)), (3.5, -2.0))


def test_translation():
    m = Matrix.translation(10, -5)
    _approx_pt(m.apply((1, 1)), (11, -4))


def test_scaling_uniform_and_nonuniform():
    _approx_pt(Matrix.scaling(2).apply((3, 4)), (6, 8))
    _approx_pt(Matrix.scaling(2, 0.5).apply((3, 4)), (6, 2))


def test_rotation_90():
    m = Matrix.rotation(90)
    _approx_pt(m.apply((1, 0)), (0, 1))
    _approx_pt(m.apply((0, 1)), (-1, 0))


def test_apply_formula():
    m = Matrix(2, 3, 4, 5, 6, 7)  # a,b,c,d,e,f
    x, y = 1.5, -2.0
    expected = (2 * x + 4 * y + 6, 3 * x + 5 * y + 7)
    _approx_pt(m.apply((x, y)), expected)


# ---------------- composicion ----------------
def test_multiply_is_apply_first_then_second():
    m1 = Matrix.translation(10, 20)
    m2 = Matrix.scaling(2, 3)
    p = (1.0, 1.0)
    # self.multiply(other).apply(p) == other.apply(self.apply(p))
    _approx_pt(m1.multiply(m2).apply(p), m2.apply(m1.apply(p)))
    # traslacion y luego escala -> (22, 63); escala y luego traslacion -> (12, 23)
    _approx_pt(m1.multiply(m2).apply(p), (22, 63))
    _approx_pt(m2.multiply(m1).apply(p), (12, 23))


def test_multiply_identity_is_noop():
    m = Matrix(2, 3, 4, 5, 6, 7)
    assert m.multiply(Matrix.identity()) == m
    assert Matrix.identity().multiply(m) == m


def test_compose_chains_in_application_order():
    seq = [Matrix.translation(1, 0), Matrix.scaling(2), Matrix.translation(0, 3)]
    p = (5.0, 5.0)
    manual = seq[0].multiply(seq[1]).multiply(seq[2])
    _approx_pt(compose(*seq).apply(p), manual.apply(p))
    # aplicar a mano: +1x -> (6,5); *2 -> (12,10); +3y -> (12,13)
    _approx_pt(compose(*seq).apply(p), (12, 13))


def test_rotation_composition_matches_double_angle():
    a = Matrix.rotation(25).multiply(Matrix.rotation(20))
    b = Matrix.rotation(45)
    for pt in [(1, 0), (0, 1), (3, -2)]:
        _approx_pt(a.apply(pt), b.apply(pt), tol=1e-9)


# ---------------- unidades ----------------
def test_mm_pt_constants_and_roundtrip():
    assert mm_to_pt(25.4) == pytest.approx(72.0)
    assert pt_to_mm(72.0) == pytest.approx(25.4)
    assert mm_to_pt(1.0) == pytest.approx(72.0 / 25.4)
    assert PT_PER_MM * MM_PER_PT == pytest.approx(1.0)
    for v in (0.0, 1.0, 210.0, 3.175):
        assert pt_to_mm(mm_to_pt(v)) == pytest.approx(v)


# ---------------- glyph_to_page (contrato Fase 0) ----------------
def test_glyph_to_page_matches_scale_then_objmatrix():
    # obj_matrix con rotacion+traslacion (como un objeto de texto rotado)
    obj = Matrix.rotation(30).multiply(Matrix.translation(100, 200))
    fs = 48.0
    em_point = (0.5, 0.7)
    g2p = glyph_to_page(obj, fs)
    # debe equivaler a: escalar por font_size y luego aplicar la matriz del objeto
    expected = obj.apply((em_point[0] * fs, em_point[1] * fs))
    _approx_pt(g2p.apply(em_point), expected)


def test_glyph_to_page_accepts_plain_tuple():
    obj_tuple = (1.0, 0.0, 0.0, 1.0, 100.0, 200.0)  # como devuelve pdfium
    g2p = glyph_to_page(obj_tuple, 48.0)
    # 'H' em bbox top ~0.718 -> en pagina y ~ 200 + 0.718*48 ~ 234.46 (Fase 0)
    _approx_pt(g2p.apply((0.0, 0.718)), (100.0, 200.0 + 0.718 * 48.0))


# ---------------- utilidades ----------------
def test_determinant_and_is_finite():
    assert Matrix.scaling(2, 3).determinant() == pytest.approx(6.0)
    assert Matrix.identity().is_finite()
    assert not Matrix(float("nan"), 0, 0, 1, 0, 0).is_finite()
    assert not Matrix(float("inf"), 0, 0, 1, 0, 0).is_finite()
