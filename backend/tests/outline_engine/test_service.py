"""FASE 2 - Test del servicio del modulo (flag OUTLINER_ENGINE). ASCII, '->'."""

import io

import pikepdf
import pytest

from app.modules.outliner.service import outline_pdf_service


def test_service_internal_default(corpus, monkeypatch):
    monkeypatch.delenv("OUTLINER_ENGINE", raising=False)
    out, report = outline_pdf_service(corpus["latino_ttf.pdf"])
    assert isinstance(out, bytes) and out[:4] == b"%PDF"
    assert report["engine"] == "internal"
    assert report["pages"][0]["outlined"] is True
    with pikepdf.open(io.BytesIO(out)) as pdf:
        assert len(dict(pdf.pages[0].get("/Resources", {}).get("/Font", {}))) == 0


def test_service_ghostscript_not_available(corpus, monkeypatch):
    monkeypatch.setenv("OUTLINER_ENGINE", "ghostscript")
    with pytest.raises(NotImplementedError):
        outline_pdf_service(corpus["latino_ttf.pdf"])


def test_service_unknown_engine(corpus, monkeypatch):
    monkeypatch.setenv("OUTLINER_ENGINE", "banana")
    with pytest.raises(ValueError):
        outline_pdf_service(corpus["latino_ttf.pdf"])


def test_service_invalid_fallback(corpus, monkeypatch):
    monkeypatch.delenv("OUTLINER_ENGINE", raising=False)
    with pytest.raises(ValueError):
        outline_pdf_service(corpus["latino_ttf.pdf"], fallback="bogus")
