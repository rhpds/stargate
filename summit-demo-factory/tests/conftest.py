"""Shared test fixtures — in-memory storage and FastAPI test client."""

import pytest

from api.app.database import set_memory_mode
from api.app import repository

set_memory_mode()


@pytest.fixture(autouse=True)
def setup_test_db():
    repository.reset_memory()
    yield
    repository.reset_memory()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from api.app.main import app
    with TestClient(app) as c:
        yield c
