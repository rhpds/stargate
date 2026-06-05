"""Shared fixtures for workflow tests."""

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("STARGATE_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("STARGATE_ADMIN_API_KEY", "test-key")


@pytest.fixture
def mock_db():
    """In-memory SQLite DB with all StarGate tables created."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db.database import Base
    import db.models  # noqa: F401 — registers all models

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def mock_oc():
    """Patches subprocess.run to return canned oc output. Returns the mock for assertion."""
    with patch("subprocess.run") as mock:
        mock.return_value = MagicMock(
            returncode=0,
            stdout="resource configured\n",
            stderr="",
        )
        yield mock


@pytest.fixture
def mock_http():
    """Patches urllib.request.urlopen for external API mocking. Returns the mock."""
    with patch("urllib.request.urlopen") as mock:
        response = MagicMock()
        response.read.return_value = b'{"results": []}'
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        mock.return_value = response
        yield mock


@pytest.fixture
def event_bus():
    """Fresh EventBus with default nanoagent pipeline."""
    from events.bus import EventBus
    from events.nanoagents import create_default_pipeline

    bus = EventBus()
    bus._db_persist = False
    for agent in create_default_pipeline():
        bus.register_nanoagent(agent)
    return bus


@pytest.fixture
def sample_event():
    """Standard evaluation.failed event for testing."""
    from events.models import Event
    return Event(
        event_type="evaluation.failed",
        run_id="test-run-001",
        stage_id="deployment-ready",
        lab_code="launchpad-test-lab",
        cluster_name="ocpv05",
        outcome="fail",
        failure_class="pods_crashlooping",
        message="Pod test-pod-1 in CrashLoopBackOff",
    )


@pytest.fixture
def sample_passing_event():
    """Standard evaluation.passed event."""
    from events.models import Event
    return Event(
        event_type="evaluation.passed",
        run_id="test-run-002",
        stage_id="deployment-ready",
        lab_code="launchpad-test-lab",
        cluster_name="ocpv05",
        outcome="pass",
    )


@pytest.fixture
def sample_evidence():
    """Standard evidence dict for a failing namespace."""
    return {
        "namespace_exists": True,
        "namespace_phase": "Active",
        "deployments_exist": True,
        "deployments_ready": False,
        "pods_total": 5,
        "pods_ready": 2,
        "pods_crashlooping": 2,
        "services_exist": True,
        "routes_exist": True,
        "route_admitted": True,
    }


@pytest.fixture
def sample_rubric():
    """Standard rubric for testing evaluation."""
    from engine.models import Rubric, Criterion, CriterionType
    return Rubric(
        id="deployment-ready",
        name="Deployment Ready",
        entry_criteria=[
            Criterion(name="namespace_exists", type=CriterionType.REQUIRED, expected=True),
        ],
        exit_criteria=[
            Criterion(name="deployments_ready", type=CriterionType.REQUIRED, expected=True),
        ],
        failure_classes={
            "deployment_missing": ["deployments_exist == False"],
            "pods_crashlooping": ["pods_crashlooping > 0"],
        },
    )
