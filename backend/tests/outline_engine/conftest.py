"""Fixtures compartidas de los tests del motor outliner (Fase 0).

- Anade backend/ al sys.path para poder importar `app.core.outline_engine.*`.
- Expone el lock global de pdfium (`pdfium_lock`).
- Expone el corpus de PDFs de prueba (`corpus`), regenerandolo si falta.

cp1252: nada de Unicode en prints/logs (usar '->').
"""

import sys
from pathlib import Path

import pytest

# backend/tests/outline_engine/conftest.py -> parents[2] == backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
THIS_DIR = Path(__file__).resolve().parent
for _p in (str(BACKEND_DIR), str(THIS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CORPUS_DIR = THIS_DIR / "corpus"


@pytest.fixture(scope="session")
def pdfium_lock():
    """Lock global de pdfium. Todo acceso a pdfium en los tests lo usa."""
    from app.core.outline_engine._lock import PDFIUM_LOCK
    return PDFIUM_LOCK


@pytest.fixture(scope="session")
def corpus():
    """Devuelve {nombre_fichero: bytes} del corpus, generandolo si falta.

    Los PDFs se versionan en corpus/; si alguno no existe (checkout limpio o
    borrado) se regenera con reportlab via gen_corpus.py.
    """
    from gen_corpus import ensure_corpus  # noqa: WPS433 (import diferido)
    paths = ensure_corpus(CORPUS_DIR)
    return {name: path.read_bytes() for name, path in paths.items()}
