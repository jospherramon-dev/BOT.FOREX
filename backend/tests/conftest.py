"""
Configuración global de pytest.

IMPORTANTE: las variables de entorno se fijan ANTES de importar cualquier
módulo de `app`, porque `app.core.config` lee el entorno al importarse.
"""

import os
from pathlib import Path

TEST_DB_PATH = Path(__file__).parent / "test_botforex.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def clean_test_database():
    """Elimina la BD de prueba antes y después de la sesión de tests."""
    TEST_DB_PATH.unlink(missing_ok=True)
    yield
    TEST_DB_PATH.unlink(missing_ok=True)
