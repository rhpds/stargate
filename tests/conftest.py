"""Shared test fixtures — SQLite-backed test database and FastAPI test client."""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("STARGATE_ADMIN_API_KEY", "test-key-for-ci")

from db.database import Base, get_db, set_engine

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
set_engine(test_engine)

TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


collect_ignore = ["stage1"]


@pytest.fixture(autouse=True)
def _reset_shared_flags():
    """Reset shared state flags between tests to prevent pollution."""
    from api.routers import _shared
    _shared._dry_run_enabled = False
    _shared._evidence_source = "real"
    _shared._synthetic_scenario = None
    yield
    _shared._dry_run_enabled = False
    _shared._evidence_source = "real"
    _shared._synthetic_scenario = None


@pytest.fixture
def db():
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=test_engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from api.app import app
    from db import models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, headers={"X-API-Key": "test-key-for-ci"}) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
