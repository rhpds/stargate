"""Shared test fixtures — SQLite-backed test database and FastAPI test client."""

import os
import socket
import subprocess
import traceback
from pathlib import Path
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


@pytest.fixture(scope="session")
def _external_effects_guard():
    """Keep unmocked Python network/process calls out of local tests.

    Session lifetime keeps the boundary active during client/thread teardown.
    This is a test safety guard, not an operating-system sandbox.
    """
    patcher = pytest.MonkeyPatch()
    attempts = []
    origins = []

    def record(kind):
        attempts.append(kind)
        root = str(Path(__file__).resolve().parents[1]) + os.sep
        frames = [frame for frame in traceback.extract_stack()
                  if frame.filename.startswith(root) and frame.filename != __file__]
        if frames:
            frame = frames[-1]
            origins.append(f"{Path(frame.filename).relative_to(root)}:{frame.lineno}")

    def deny_process(*args, **kwargs):
        record("subprocess")
        raise RuntimeError("Unit tests must mock subprocess execution")

    def deny_network(*args, **kwargs):
        record("network")
        raise RuntimeError("Unit tests must mock network access")

    deny_process._stargate_test_guard = True
    deny_network._stargate_test_guard = True
    patcher.setattr(subprocess, "Popen", deny_process)
    patcher.setattr(socket.socket, "connect", deny_network)
    patcher.setattr(socket.socket, "connect_ex", deny_network)
    patcher.setattr(socket.socket, "sendto", deny_network)
    patcher.setattr(socket, "getaddrinfo", deny_network)
    try:
        yield attempts, origins
    finally:
        patcher.undo()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "external_block_expected: explicitly test that external effects are blocked"
    )


@pytest.fixture(autouse=True)
def unit_external_effects_guard(_external_effects_guard, request):
    """Tests may install explicit mocks, never invoke ambient external clients."""
    attempts, origins = _external_effects_guard
    attempts.clear()
    origins.clear()
    yield attempts
    if attempts and not request.node.get_closest_marker("external_block_expected"):
        pytest.fail("Unmocked external effects blocked: " + ", ".join(attempts)
                    + "; callers: " + ", ".join(origins))


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
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import app
    from api.routers import health
    from db import models  # noqa: F401

    monkeypatch.setattr(health, "_check_executor_kubeconfig", lambda: "not_configured")
    monkeypatch.setattr(health, "_check_sandbox_api", lambda: "not_configured")

    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, headers={"X-API-Key": "test-key-for-ci"}) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
