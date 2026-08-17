"""Tests for attention classification and auto-investigation gating."""

import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock


class TestExtractCatalogItem:
    def test_sandbox_namespace(self):
        from engine.attention_classifier import extract_catalog_item
        assert extract_catalog_item("sandbox-ab12c-ocp4-cluster") == "ocp4-cluster"

    def test_sandbox_simple(self):
        from engine.attention_classifier import extract_catalog_item
        assert extract_catalog_item("sandbox-xy99z-zt-rhel") == "zt-rhel"

    def test_non_sandbox(self):
        from engine.attention_classifier import extract_catalog_item
        assert extract_catalog_item("my-namespace") == "my-namespace"


class TestClassifyNamespace:
    def _baselines(self, catalog_item="ocp4", fc="pods_crashlooping", rate=0.15, p95=45.0, total_evals=100):
        return {
            catalog_item: {
                "total_evals": total_evals,
                "namespace_count": 10,
                "failure_profiles": {
                    fc: {"rate": rate, "count": int(rate * total_evals), "p95_ttr_minutes": p95},
                },
            }
        }

    def test_provisioning_young_namespace(self):
        from engine.attention_classifier import classify_namespace
        first_eval = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = classify_namespace(
            "sandbox-ab12c-ocp4", "ocp4",
            {"pods_crashlooping": 3}, first_eval,
            self._baselines(),
        )
        assert result["attention"] == "provisioning"

    def test_stuck_exceeds_p95(self):
        from engine.attention_classifier import classify_namespace
        first_eval = datetime.now(timezone.utc) - timedelta(minutes=90)
        result = classify_namespace(
            "sandbox-ab12c-ocp4", "ocp4",
            {"pods_crashlooping": 3}, first_eval,
            self._baselines(p95=45.0),
        )
        assert result["attention"] == "stuck"

    def test_anomalous_rare_failure(self):
        from engine.attention_classifier import classify_namespace
        first_eval = datetime.now(timezone.utc) - timedelta(minutes=25)
        result = classify_namespace(
            "sandbox-ab12c-ocp4", "ocp4",
            {"weird_failure": 1}, first_eval,
            self._baselines(total_evals=100),
        )
        assert result["attention"] == "anomalous"

    def test_expected_normal_failure(self):
        from engine.attention_classifier import classify_namespace
        first_eval = datetime.now(timezone.utc) - timedelta(minutes=25)
        result = classify_namespace(
            "sandbox-ab12c-ocp4", "ocp4",
            {"pods_crashlooping": 3}, first_eval,
            self._baselines(rate=0.15, p95=120.0),
        )
        assert result["attention"] == "expected"

    def test_stuck_no_baseline_ttr(self):
        from engine.attention_classifier import classify_namespace
        first_eval = datetime.now(timezone.utc) - timedelta(minutes=90)
        baselines = self._baselines(p95=None)
        baselines["ocp4"]["failure_profiles"]["pods_crashlooping"]["p95_ttr_minutes"] = None
        result = classify_namespace(
            "sandbox-ab12c-ocp4", "ocp4",
            {"pods_crashlooping": 3}, first_eval,
            baselines,
        )
        assert result["attention"] == "stuck"


class TestShouldAutoInvestigate:
    def test_skips_expected(self, db):
        from engine.attention_classifier import should_auto_investigate
        with patch("engine.attention_classifier.get_cached_baselines", return_value={}):
            should, reason, _att = should_auto_investigate(db, "sandbox-ab12c-ocp4", "pods_crashlooping", "east")
        assert not should
        assert "expected" in reason or "attention=" in reason

    def test_skips_dedup(self, db):
        from db.repository import create_investigation, complete_investigation
        create_investigation(db, job_id="inv-dedup01", lab_code="sandbox-ab12c-ocp4", cluster="east", failure_class="pods_crashlooping")
        complete_investigation(db, "inv-dedup01", analysis="done")

        baselines = {
            "ocp4": {
                "total_evals": 100,
                "failure_profiles": {
                    "pods_crashlooping": {"rate": 0.01, "count": 1, "p95_ttr_minutes": None},
                },
            }
        }

        from engine.attention_classifier import should_auto_investigate
        with patch("engine.attention_classifier.get_cached_baselines", return_value=baselines):
            should, reason, _att = should_auto_investigate(db, "sandbox-ab12c-ocp4", "pods_crashlooping", "east")
        assert not should
        assert "already investigated" in reason

    def test_skips_rate_limit(self, db):
        from db.repository import create_investigation
        for i in range(5):
            create_investigation(db, job_id=f"inv-rate{i}", lab_code=f"sandbox-ab{i:02d}c-ocp4", cluster="east", failure_class="fc1")

        baselines = {
            "ocp4": {
                "total_evals": 100,
                "failure_profiles": {
                    "new_failure": {"rate": 0.01, "count": 1, "p95_ttr_minutes": None},
                },
            }
        }

        from engine.attention_classifier import should_auto_investigate
        with patch("engine.attention_classifier.get_cached_baselines", return_value=baselines), \
             patch.dict(os.environ, {"STARGATE_INVESTIGATE_MAX_PER_CATALOG_HOUR": "3"}):
            should, reason, _att = should_auto_investigate(db, "sandbox-zz99z-ocp4", "new_failure", "east")
        assert not should
        assert "rate limit" in reason
