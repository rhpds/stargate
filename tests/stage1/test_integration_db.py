"""Integration tests requiring a running PostgreSQL instance via podman-compose.

Run with: pytest -m integration
Requires: make podman-up (or podman-compose up -d)
Skipped automatically when PostgreSQL is not available.
"""

import os

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://sdf:REDACTED@localhost:5432/summit_demo_factory",
)


def _try_connect():
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        return None


@pytest.fixture
def pg_engine():
    engine = _try_connect()
    if engine is None:
        pytest.skip("PostgreSQL not available — run 'make podman-db' first")
    yield engine
    engine.dispose()


class TestPostgresIntegration:
    def test_can_connect(self, pg_engine):
        with pg_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_create_tables(self, pg_engine):
        from api.app.database import Base, set_engine
        from api.app import db_models  # noqa: F401
        set_engine(pg_engine)
        Base.metadata.create_all(bind=pg_engine)
        from sqlalchemy import inspect
        inspector = inspect(pg_engine)
        tables = inspector.get_table_names()
        assert "runs" in tables
        assert "stages" in tables
        assert "evidence" in tables
