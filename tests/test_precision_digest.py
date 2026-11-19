"""The weekly digest: a document about the numbers, safe to RAG."""

from datetime import datetime, timezone

from engine.precision_digest import build_digest


def _report(rows, evaluations=None):
    return {
        "classes": rows,
        "summary": {"classes": len(rows),
                    "evaluations": evaluations or sum(r["evaluations"] for r in rows)},
    }


def _row(name, evals, labs, pct):
    return {"failure_class": name, "evaluations": evals, "labs": labs,
            "clusters": 3, "self_resolved_labs": 0, "self_resolved_pct": pct}


class TestBuildDigest:
    def test_lists_classes_with_week_over_week_delta(self):
        current = _report([_row("showroom_not_ready", 900, 271, 20),
                           _row("pods_not_ready", 300, 120, 83)])
        previous = _report([_row("showroom_not_ready", 1200, 300, 34),
                            _row("pods_not_ready", 300, 120, 83)])
        md = build_digest(current, previous, datetime(2026, 11, 18, tzinfo=timezone.utc))

        assert "`showroom_not_ready` | 900 | 271 | 20% | -300 |" in md
        assert "self-resolution 34% → 20%" in md
        assert "## Reading it" in md
        assert "not ground truth" in md

    def test_names_new_and_silent_classes(self):
        current = _report([_row("new_class", 10, 3, 0)])
        previous = _report([_row("old_class", 5, 2, 0)])
        md = build_digest(current, previous, datetime(2026, 11, 18, tzinfo=timezone.utc))

        assert "New this week: `new_class`" in md
        assert "Silent this week: `old_class`" in md

    def test_handles_an_empty_week(self):
        md = build_digest(_report([]), _report([]), datetime(2026, 11, 18, tzinfo=timezone.utc))
        assert "0 failure evaluations" in md
        assert "No class moved" in md


class TestStoredDigest:
    def test_admin_endpoint_generates_and_stores(self, client, db):
        r = client.post("/admin/precision-digest")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["period"]

        from db.models import PrecisionDigest
        row = db.query(PrecisionDigest).filter_by(period=body["period"]).one()
        assert "Failure precision" in row.markdown

    def test_endpoint_requires_admin(self, client):
        r = client.post("/admin/precision-digest", headers={"X-API-Key": ""})
        assert r.status_code in (401, 403)

    def test_latest_digest_is_in_the_ask_corpus(self, db):
        from datetime import datetime, timezone
        from db.repository import save_precision_digest
        from engine.stargate_qa import _knowledge_corpus

        save_precision_digest(
            db, "2026-W47",
            "# Failure precision — week of 2026-11-16\n\n`pods_not_ready` self-resolved 83%.\n",
        )

        corpus = _knowledge_corpus()
        assert any(doc["source"].startswith("doc:precision-digest:2026-W47") for doc in corpus)
