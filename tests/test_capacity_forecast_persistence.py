"""Capacity forecast persistence — the authority gate's evidence base.

TDD: written before the model/repository functions exist. Pins the
A-track foundation: every forecast cycle is persisted so accuracy
becomes measurable, and the record carries the contract's honesty
(supply unobserved = None, coverage counts, risk, authority state).
"""

from datetime import datetime, timezone

import pytest

from db.models import CapacityForecastRecord


class TestCapacityForecastRecord:
    """Schema shape — the migration must match the model."""

    def test_table_and_columns(self):
        assert CapacityForecastRecord.__tablename__ == "capacity_forecasts"
        cols = {c.name for c in CapacityForecastRecord.__table__.columns}
        assert {"id", "generated_at", "window_hours", "risk", "authority",
                "supply_vm_slots", "supply_basis", "sessions_total",
                "sessions_with_profiles", "sessions_fallback",
                "peak_hour", "hourly"} <= cols


class TestSaveAndQueryForecast:
    def test_save_and_latest(self, db):
        from db import repository
        now = datetime.now(timezone.utc)
        saved = repository.save_capacity_forecast(
            db,
            generated_at=now, window_hours=24, risk="green", authority="advisory",
            supply_vm_slots=3687.0, supply_basis="observed_peak_density",
            sessions_total=3, sessions_with_profiles=1, sessions_fallback=2,
            peak_hour={"hour": "2026-11-13T15:00", "vm_slots": 30},
            hourly=[{"hour": "2026-11-13T15:00", "vm_slots": 30}],
        )
        assert saved.id is not None

        latest = repository.latest_capacity_forecasts(db, limit=5)
        assert len(latest) >= 1
        row = latest[0]
        assert row.risk == "green"
        assert row.authority == "advisory"
        assert row.supply_vm_slots == 3687.0
        assert row.sessions_fallback == 2

    def test_unobserved_supply_persists_as_none(self, db):
        """Supply unobserved is None in the record — never zero."""
        from db import repository
        repository.save_capacity_forecast(
            db,
            generated_at=datetime.now(timezone.utc), window_hours=24,
            risk="amber", authority="advisory",
            supply_vm_slots=None, supply_basis=None,
            sessions_total=0, sessions_with_profiles=0, sessions_fallback=0,
            peak_hour=None, hourly=[],
        )
        row = repository.latest_capacity_forecasts(db, limit=1)[0]
        assert row.supply_vm_slots is None
        assert row.supply_basis is None

    def test_forecasts_ordered_newest_first(self, db):
        from db import repository
        base = datetime.now(timezone.utc)
        for i in range(3):
            repository.save_capacity_forecast(
                db,
                generated_at=base.replace(minute=i), window_hours=24,
                risk="amber", authority="advisory",
                supply_vm_slots=None, supply_basis=None,
                sessions_total=0, sessions_with_profiles=0, sessions_fallback=0,
                peak_hour=None, hourly=[],
            )
        rows = repository.latest_capacity_forecasts(db, limit=3)
        assert rows[0].generated_at >= rows[-1].generated_at
