"""Tests for fleet-level known-issue detection, persistence, and endpoint.

Ten investigations of ten namespaces that all trace to one Helm chart bug
are ONE issue. These tests pin the grouping precedence (artifact over
cluster), bucketing (platform_self / platform / lab_family), signature
stability, representative selection, the upsert/retire lifecycle, and the
read-only /dashboard/known-issues endpoint.
"""

from datetime import datetime, timedelta, timezone

from db.models import InvestigationRecord, KnownIssue
from engine.known_issues import detect_known_issues, upsert_known_issues

NOW = datetime.now(timezone.utc)
AUTH = {"X-API-Key": "test-key-for-ci"}

_seq = 0


def make_inv(db, ns, cluster, fc, root_cause, verdict="ACTIONABLE", confidence=0.7,
             remediation="fix it", created_at=None, tool_calls=None, status="complete"):
    """Seed one investigation — the unit detect_known_issues groups."""
    global _seq
    _seq += 1
    row = InvestigationRecord(
        job_id=f"inv-ki-{_seq}",
        lab_code=ns,
        namespace=ns,
        cluster=cluster,
        failure_class=fc,
        trigger_type="auto",
        status=status,
        root_cause=root_cause,
        remediation_suggestion=remediation,
        trust_dimensions={"verdict": verdict, "confidence": confidence},
        tool_calls=tool_calls if tool_calls is not None else [{"tool": "oc_read", "iteration": 1}],
        created_at=created_at or (NOW - timedelta(minutes=5)),
        completed_at=created_at or NOW,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


CHART_TEXTS = [
    "Helm chart `zerotouch-1.10.2` ships an nginx misconfig; the showroom deployment never becomes ready",
    "The `zerotouch-1.10.2` chart template sets a wrong nginx port so the showroom stays not ready",
    "Chart `zerotouch-1.10.2` misconfigures the nginx readiness probe and pods never pass it",
    "Root cause is the `zerotouch-1.10.2` helm chart applying a broken nginx config to the showroom",
]


# ---------------------------------------------------------------------------
# Detection: grouping + bucketing
# ---------------------------------------------------------------------------

def test_chart_bug_groups_into_one_lab_family_issue(db):
    clusters = ["ocpv07", "ocpv07", "ocpv08", "ocpv08"]
    for ns, cluster, rc in zip(["ns-a", "ns-b", "ns-c", "ns-d"], clusters, CHART_TEXTS):
        make_inv(db, ns, cluster, "showroom_not_ready", rc)

    report = detect_known_issues(db)

    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["signature"] == "showroom_not_ready|artifact:zerotouch-1.10.2"
    assert issue["bucket"] == "lab_family"
    assert issue["failure_class"] == "showroom_not_ready"
    assert issue["cluster"] is None  # spans two clusters -> the artifact's fault
    assert issue["namespace_count"] == 4
    assert issue["investigation_count"] == 4
    assert issue["artifact_refs"] == ["zerotouch-1.10.2"]
    assert issue["representative_investigation_id"] in issue["investigation_ids"]
    assert issue["first_seen"] and issue["last_seen"]
    assert issue["verdict_counts"] == {"ACTIONABLE": 4, "TRANSIENT": 0, "other": 0}
    assert report["summary"]["issues"] == 1
    assert report["summary"]["lab_family"] == 1
    assert report["summary"]["investigations_covered"] == 4
    assert report["summary"]["namespaces_covered"] == 4


def test_router_instability_groups_as_platform_artifact_issue(db):
    texts = [
        "The ingress router `router-ingress-rhdp-net` on ocpv07 restarted 114 times; routes flap",
        "`router-ingress-rhdp-net` is unstable — 114 restarts cause showroom route failures",
        "Ingress router `router-ingress-rhdp-net` keeps crashlooping and breaks the showroom route",
        "Pod `router-ingress-rhdp-net-9fdb7676-7ksfx` has restarted 114 times, ingress unavailable",
    ]
    for ns, rc in zip(["ns-r1", "ns-r2", "ns-r3", "ns-r4"], texts):
        make_inv(db, ns, "ocpv07", "showroom_not_ready", rc)

    report = detect_known_issues(db)

    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    # the pod hash suffix was stripped so all four land in the same group
    assert issue["signature"] == "showroom_not_ready|artifact:router-ingress-rhdp-net"
    assert issue["bucket"] == "platform"  # router ref -> infra side
    assert issue["cluster"] == "ocpv07"
    assert issue["investigation_count"] == 4
    assert issue["namespace_count"] == 4
    # no double-counting: the same investigations did not also form a cluster group
    assert all(not i["signature"].endswith("|cluster:ocpv07") for i in report["issues"])


def test_cluster_group_without_shared_artifact(db):
    texts = [
        "Node memory exhaustion on the ocpv06 workers evicted the showroom pods",
        "Cluster capacity is exhausted; new showroom pods stay Pending and unschedulable",
        "Hypervisor contention on a worker node starved the showroom workload of memory",
    ]
    for ns, rc in zip(["ns-c1", "ns-c2", "ns-c3"], texts):
        make_inv(db, ns, "ocpv06", "showroom_not_ready", rc)

    report = detect_known_issues(db)

    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["signature"] == "showroom_not_ready|cluster:ocpv06"
    assert issue["bucket"] == "platform"
    assert issue["cluster"] == "ocpv06"
    assert issue["investigation_count"] == 3
    assert issue["namespace_count"] == 3
    assert report["summary"]["platform"] == 1


def test_platform_self_issues_sort_first(db):
    self_texts = [
        "StarGate evaluation race: the `stargate-evaluator` flagged the showroom during teardown — false positive",
        "The `stargate-evaluator` returned a false negative; the rubric was misapplied to this lab",
        "A scanner race in `stargate-evaluator` produced a spurious failure during namespace teardown",
    ]
    # Self-diagnosed issues group cross-cluster: our evaluator misbehaving
    # is not cluster-specific.
    for ns, rc, cluster in zip(
        ["ns-s1", "ns-s2", "ns-s3"], self_texts, ["ocpv09", "ocpv06", "ocpv08"]
    ):
        make_inv(db, ns, cluster, "showroom_not_ready", rc)
    for ns in ["ns-x1", "ns-x2", "ns-x3"]:
        make_inv(db, ns, "ocpv07", "showroom_not_ready", CHART_TEXTS[0])

    report = detect_known_issues(db)

    assert len(report["issues"]) == 2
    first, second = report["issues"]
    assert first["bucket"] == "platform_self"
    assert first["signature"] == "showroom_not_ready|self"
    assert first["title"].startswith("StarGate self-issue: ")
    assert second["bucket"] == "lab_family"
    assert report["summary"]["platform_self"] == 1
    assert report["summary"]["lab_family"] == 1


def test_self_group_claims_members_before_artifact_groups(db):
    """A root cause that blames our evaluator is our bug even when it
    names a chart — the chart group must not absorb it."""
    for ns in ["ns-m1", "ns-m2", "ns-m3"]:
        make_inv(
            db, ns, "ocpv06", "showroom_not_ready",
            f"Evaluation race in `zerotouch-1.10.2` window — {CHART_TEXTS[0]}",
        )
    for ns in ["ns-y1", "ns-y2", "ns-y3"]:
        make_inv(db, ns, "ocpv06", "showroom_not_ready", CHART_TEXTS[0])

    report = detect_known_issues(db)

    buckets = [i["bucket"] for i in report["issues"]]
    assert "platform_self" in buckets and "lab_family" in buckets
    self_issue = next(i for i in report["issues"] if i["bucket"] == "platform_self")
    chart_issue = next(i for i in report["issues"] if i["bucket"] == "lab_family")
    assert self_issue["signature"] == "showroom_not_ready|self"
    assert self_issue["namespace_count"] == 3
    assert chart_issue["namespace_count"] == 3  # chart group got only its own 3


def test_below_threshold_pair_is_not_an_issue(db):
    for ns in ["ns-t1", "ns-t2"]:
        make_inv(db, ns, "ocpv07", "showroom_not_ready", CHART_TEXTS[0])

    report = detect_known_issues(db)

    assert report["issues"] == []
    assert report["summary"]["issues"] == 0
    assert report["summary"]["investigations_covered"] == 0


def test_artifact_group_absorbs_investigations_before_cluster_grouping(db):
    # three namespaces share the router artifact on one cluster...
    for ns in ["ns-d1", "ns-d2", "ns-d3"]:
        make_inv(db, ns, "ocpv06", "showroom_not_ready",
                 "Ingress router `router-ingress-rhdp-net` restarted; route flapping")
    # ...two more namespaces on the same cluster without the artifact
    make_inv(db, "ns-d4", "ocpv06", "showroom_not_ready", "Node memory exhaustion evicted the pods")
    make_inv(db, "ns-d5", "ocpv06", "showroom_not_ready", "Cluster capacity exhausted; pods stay pending")

    report = detect_known_issues(db)

    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["signature"] == "showroom_not_ready|artifact:router-ingress-rhdp-net"
    assert issue["investigation_count"] == 3  # only the artifact members
    # the leftovers cannot form a cluster group below the namespace threshold
    assert all("|cluster:" not in i["signature"] for i in report["issues"])


def test_transient_majority_group_is_still_reported(db):
    # detection is about grouping, not gating on verdict
    for ns in ["ns-tr1", "ns-tr2", "ns-tr3"]:
        make_inv(db, ns, "ocpv07", "showroom_not_ready", CHART_TEXTS[0],
                 verdict="TRANSIENT", confidence=0.4)

    report = detect_known_issues(db)

    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["investigation_count"] == 3
    assert issue["verdict_counts"] == {"ACTIONABLE": 0, "TRANSIENT": 3, "other": 0}


def test_comma_joined_failure_class_uses_primary(db):
    for ns in ["ns-f1", "ns-f2", "ns-f3"]:
        make_inv(db, ns, "ocpv07", "showroom_not_ready,service_has_no_endpoints", CHART_TEXTS[0])

    report = detect_known_issues(db)

    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["failure_class"] == "showroom_not_ready"
    assert issue["signature"] == "showroom_not_ready|artifact:zerotouch-1.10.2"


def test_investigation_ids_capped_at_ten_newest(db):
    rows = []
    for i in range(12):
        rows.append(make_inv(db, f"ns-cap{i}", "ocpv07", "showroom_not_ready",
                             CHART_TEXTS[0], created_at=NOW - timedelta(minutes=30 - i)))

    report = detect_known_issues(db)

    issue = report["issues"][0]
    assert issue["investigation_count"] == 12
    assert len(issue["investigation_ids"]) == 10
    expected = [r.id for r in sorted(rows, key=lambda r: r.id, reverse=True)][:10]
    assert issue["investigation_ids"] == expected


def test_window_hours_filters_old_investigations(db):
    for ns in ["ns-o1", "ns-o2", "ns-o3"]:
        make_inv(db, ns, "ocpv07", "showroom_not_ready", CHART_TEXTS[0],
                 created_at=NOW - timedelta(hours=100))

    assert detect_known_issues(db)["issues"] == []  # default 24h window misses them
    assert len(detect_known_issues(db, window_hours=200)["issues"]) == 1


def test_incomplete_or_empty_cause_investigations_are_ignored(db):
    make_inv(db, "ns-i1", "ocpv07", "showroom_not_ready", CHART_TEXTS[0], status="running")
    make_inv(db, "ns-i2", "ocpv07", "showroom_not_ready", CHART_TEXTS[0], status="error")
    make_inv(db, "ns-i3", "ocpv07", "showroom_not_ready", None, status="complete")

    assert detect_known_issues(db)["issues"] == []


def test_empty_database_returns_empty_report(db):
    report = detect_known_issues(db)

    assert report["issues"] == []
    assert report["window_hours"] == 24
    assert report["generated_at"] is not None
    assert report["summary"] == {
        "issues": 0,
        "platform": 0,
        "platform_self": 0,
        "lab_family": 0,
        "unknown": 0,
        "investigations_covered": 0,
        "namespaces_covered": 0,
    }


# ---------------------------------------------------------------------------
# Representative selection
# ---------------------------------------------------------------------------

def test_representative_is_highest_confidence(db):
    make_inv(db, "ns-p1", "ocpv07", "showroom_not_ready", CHART_TEXTS[1], confidence=0.7)
    best = make_inv(db, "ns-p2", "ocpv08", "showroom_not_ready", CHART_TEXTS[2], confidence=0.95)
    make_inv(db, "ns-p3", "ocpv07", "showroom_not_ready", CHART_TEXTS[3], confidence=0.5)

    report = detect_known_issues(db)

    issue = report["issues"][0]
    assert issue["representative_investigation_id"] == best.id
    assert issue["top_root_cause_excerpt"].startswith("Chart `zerotouch-1.10.2`")
    assert issue["remediation_excerpt"] == "fix it"


def test_representative_tiebreak_prefers_more_tool_calls(db):
    make_inv(db, "ns-q1", "ocpv07", "showroom_not_ready", CHART_TEXTS[0],
             confidence=0.8, tool_calls=[{"tool": "x"}])
    many = make_inv(db, "ns-q2", "ocpv08", "showroom_not_ready", CHART_TEXTS[0],
                    confidence=0.8, tool_calls=[{"tool": "x"}, {"tool": "y"}, {"tool": "z"}])
    make_inv(db, "ns-q3", "ocpv07", "showroom_not_ready", CHART_TEXTS[0],
             confidence=0.8, tool_calls=[{"tool": "x"}])

    report = detect_known_issues(db)

    assert report["issues"][0]["representative_investigation_id"] == many.id


def test_representative_tiebreak_prefers_newest(db):
    make_inv(db, "ns-n1", "ocpv07", "showroom_not_ready", CHART_TEXTS[0],
             confidence=0.8, created_at=NOW - timedelta(hours=2))
    newer = make_inv(db, "ns-n2", "ocpv08", "showroom_not_ready", CHART_TEXTS[0],
                     confidence=0.8, created_at=NOW - timedelta(minutes=1))
    make_inv(db, "ns-n3", "ocpv07", "showroom_not_ready", CHART_TEXTS[0],
             confidence=0.8, created_at=NOW - timedelta(hours=1))

    report = detect_known_issues(db)

    assert report["issues"][0]["representative_investigation_id"] == newer.id


# ---------------------------------------------------------------------------
# Persistence: upsert / retire / re-open
# ---------------------------------------------------------------------------

def test_upsert_inserts_refreshes_and_retires(db):
    for i in range(1, 4):
        make_inv(db, f"ns-u{i}", "ocpv07" if i % 2 else "ocpv08", "showroom_not_ready",
                 CHART_TEXTS[0], created_at=NOW - timedelta(hours=3))

    report = detect_known_issues(db)
    assert upsert_known_issues(db, report) == {"upserted": 1, "retired": 0}

    rows = db.query(KnownIssue).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.signature == "showroom_not_ready|artifact:zerotouch-1.10.2"
    assert row.status == "open"
    assert row.bucket == "lab_family"
    assert row.investigation_count == 3
    assert row.namespace_count == 3
    first_seen_before = row.first_seen
    created_at_before = row.created_at

    # a fourth namespace joins the issue -> refresh, not duplicate
    make_inv(db, "ns-u4", "ocpv07", "showroom_not_ready", CHART_TEXTS[0],
             created_at=NOW - timedelta(minutes=5))
    report2 = detect_known_issues(db)
    assert upsert_known_issues(db, report2) == {"upserted": 1, "retired": 0}

    assert db.query(KnownIssue).count() == 1
    assert row.investigation_count == 4
    assert row.investigation_ids and len(row.investigation_ids) == 4
    assert row.first_seen == first_seen_before  # original first_seen preserved
    assert row.created_at == created_at_before
    assert row.last_seen >= row.first_seen

    # an open issue absent from the report and stale beyond RETIRE_AFTER_HOURS -> retired
    stale = KnownIssue(
        signature="showroom_not_ready|artifact:ghost-chart-9.9.9",
        bucket="lab_family",
        title="ghost issue",
        status="open",
        created_at=NOW - timedelta(hours=96),
        first_seen=NOW - timedelta(hours=96),
        last_seen=NOW - timedelta(hours=72),
    )
    db.add(stale)
    db.commit()
    assert upsert_known_issues(db, report2) == {"upserted": 1, "retired": 1}
    assert stale.status == "retired"

    # a retired issue that reappears in the report is re-opened
    ghost_report = {
        "issues": [
            {
                "signature": "showroom_not_ready|artifact:ghost-chart-9.9.9",
                "bucket": "lab_family",
                "title": "ghost issue again",
                "failure_class": "showroom_not_ready",
                "cluster": None,
                "artifact_refs": ["ghost-chart-9.9.9"],
                "namespace_count": 3,
                "investigation_count": 3,
                "investigation_ids": [1, 2, 3],
                "representative_investigation_id": 1,
                "top_root_cause_excerpt": "ghost",
                "remediation_excerpt": "fix",
                "first_seen": (NOW - timedelta(hours=1)).isoformat(),
                "last_seen": NOW.isoformat(),
                "verdict_counts": {"ACTIONABLE": 3, "TRANSIENT": 0, "other": 0},
            }
        ]
    }
    assert upsert_known_issues(db, ghost_report) == {"upserted": 1, "retired": 0}
    assert stale.status == "open"
    assert stale.investigation_count == 3

    # a manually-mitigated issue is never reset to open
    row.status = "mitigated"
    db.commit()
    assert upsert_known_issues(db, report2) == {"upserted": 1, "retired": 0}
    assert row.status == "mitigated"


# ---------------------------------------------------------------------------
# Dashboard endpoint (read-only, merges persisted status)
# ---------------------------------------------------------------------------

def test_dashboard_known_issues_endpoint(db, client):
    clusters = ["ocpv07", "ocpv07", "ocpv08", "ocpv08"]
    for ns, cluster, rc in zip(["ns-e1", "ns-e2", "ns-e3", "ns-e4"], clusters, CHART_TEXTS):
        make_inv(db, ns, cluster, "showroom_not_ready", rc)

    resp = client.get("/dashboard/known-issues", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_hours"] == 24
    assert len(body["issues"]) == 1
    issue = body["issues"][0]
    assert issue["signature"] == "showroom_not_ready|artifact:zerotouch-1.10.2"
    assert issue["bucket"] == "lab_family"
    assert issue["cluster"] is None
    assert issue["namespace_count"] == 4
    assert issue["persisted_status"] is None  # not upserted yet
    assert body["summary"]["issues"] == 1

    # bucket filter
    resp = client.get("/dashboard/known-issues", params={"bucket": "platform"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["issues"] == []

    resp = client.get("/dashboard/known-issues", params={"bucket": "lab_family"}, headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()["issues"]) == 1

    # invalid bucket is rejected
    resp = client.get("/dashboard/known-issues", params={"bucket": "bogus"}, headers=AUTH)
    assert resp.status_code == 400

    # window_hours is clamped into 1..168, not rejected
    resp = client.get("/dashboard/known-issues", params={"window_hours": 0}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["window_hours"] == 1
    assert len(resp.json()["issues"]) == 1  # seeds are five minutes old


def test_dashboard_known_issues_merges_persisted_status(db, client):
    for ns in ["ns-m1", "ns-m2", "ns-m3"]:
        make_inv(db, ns, "ocpv07", "showroom_not_ready", CHART_TEXTS[0])

    upsert_known_issues(db, detect_known_issues(db))
    row = db.query(KnownIssue).one()
    assert row.status == "open"

    resp = client.get("/dashboard/known-issues", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["issues"][0]["persisted_status"] == "open"

    # a retired issue is hidden unless include_retired is set
    row.status = "retired"
    db.commit()
    resp = client.get("/dashboard/known-issues", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["issues"] == []

    resp = client.get("/dashboard/known-issues", params={"include_retired": True}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["persisted_status"] == "retired"

    # mitigated stays visible — only retired is dropped by default
    row.status = "mitigated"
    db.commit()
    resp = client.get("/dashboard/known-issues", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["issues"][0]["persisted_status"] == "mitigated"
