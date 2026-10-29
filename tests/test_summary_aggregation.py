"""Summary equivalence and transport bounds without dropping history rows."""
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from db import repository
from db.models import EvaluationRecord, MVClusterSummary, MVPipelineStage, MVLabEvalSummary

NOW = datetime.now(timezone.utc)
REFRESHES = [
    (repository.refresh_cluster_summary, MVClusterSummary),
    (repository.refresh_pipeline_stages, MVPipelineStage),
    (repository.refresh_lab_eval_summary, MVLabEvalSummary),
]


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(repository, "datetime", Clock)


def seed(db, rows):
    values = []
    for row in rows:
        value = dict(run_id="synthetic-summary", stage_id="stage-a", outcome="fail",
                     failure_class="storage", lab_code="sandbox-a", cluster_name="cluster-a",
                     evaluated_at=NOW - timedelta(hours=1))
        value.update(row)
        values.append(value)
    db.bulk_insert_mappings(EvaluationRecord, values)
    db.commit()
    return values


def reference(rows):
    """Prior row-wise arithmetic, kept in tests only."""
    clusters, stages, labs = {}, {}, {}
    def empty():
        return {"pass":0,"fail":0,"warn":0,"fc":Counter(),"seen":set(),"failing":set(),"last":None}
    for row in rows:
        if row["evaluated_at"] < NOW-timedelta(hours=24) or row["run_id"].startswith(("k8s-mine-","alert-mine-","prom-mine-")):
            continue
        outcome = (row["outcome"] or "").lower()
        cluster, lab, fc = row["cluster_name"], row["lab_code"], row["failure_class"]
        groups = [stages.setdefault(row["stage_id"], empty())]
        if cluster is not None:
            groups.append(clusters.setdefault(cluster, empty()))
        if lab is not None:
            groups.append(labs.setdefault((lab, cluster or None), empty()))
        for group in groups:
            if outcome in ("pass","fail","warn"):
                group[outcome] += 1
            if outcome == "fail" and fc:
                group["fc"][fc] += 1
            if lab:
                group["seen"].add(lab)
                if outcome == "fail":
                    group["failing"].add(lab)
            group["last"] = max(group["last"] or row["evaluated_at"], row["evaluated_at"])
    def counts(group):
        p,f,w = (group[k] for k in ("pass","fail","warn"))
        total = p+f+w
        return p,f,w,total,round((p+w)/total*100,1) if total else 0
    return {
        "clusters": {key: (*counts(g),dict(g["fc"]),len(g["seen"]),len(g["failing"])) for key,g in clusters.items()},
        "stages": {key: counts(g) for key,g in stages.items()},
        "labs": {key: (*counts(g),max(g["fc"],key=g["fc"].get) if g["fc"] else None,g["last"].replace(tzinfo=None)) for key,g in labs.items()},
    }


def snapshot(db):
    return {
        "clusters": {r.cluster_name:(r.passed,r.failed,r.warned,r.total_evaluations,r.health_rate,r.failure_classes,r.labs_seen,r.labs_failing) for r in db.query(MVClusterSummary)},
        "stages": {r.stage_id:(r.pass_count,r.fail_count,r.warn_count,r.total,r.health_rate) for r in db.query(MVPipelineStage)},
        "labs": {(r.lab_code,r.cluster_name):(r.passed,r.failed,r.warned,r.total_evals,r.health_rate,r.top_failure_class,r.last_evaluated_at.replace(tzinfo=None)) for r in db.query(MVLabEvalSummary)},
    }


def test_grouped_summaries_match_prior_arithmetic_and_edge_cases(db):
    rows = seed(db, [
        {}, {}, {"failure_class":"pods"}, {"outcome":"PASS"}, {"outcome":"Warn"},
        {"outcome":"unknown","evaluated_at":NOW}, {"outcome":" fail","failure_class":"ignored"},
        {"lab_code":"sandbox-b","failure_class":None}, {"lab_code":"","failure_class":""},
        {"lab_code":None}, {"cluster_name":None}, {"cluster_name":"","failure_class":"pods"},
        {"cluster_name":None,"failure_class":"pods"},
        {"lab_code":"sandbox-tie","failure_class":"first","evaluated_at":NOW-timedelta(hours=2)},
        {"lab_code":"sandbox-tie","failure_class":"first","evaluated_at":NOW-timedelta(hours=2)},
        {"lab_code":"sandbox-tie","failure_class":"second","evaluated_at":NOW-timedelta(hours=3)},
        {"cluster_name":"only-unknown","lab_code":"sandbox-unknown","stage_id":"unknown-stage","outcome":"UNKNOWN"},
        {"run_id":"k8s-mine-synthetic","failure_class":"excluded"},
        {"run_id":"alert-mine-synthetic","failure_class":"excluded"},
        {"run_id":"prom-mine-synthetic","failure_class":"excluded"},
        {"run_id":"included-k8s-mine-synthetic","outcome":"pass"},
        {"evaluated_at":NOW-timedelta(hours=25),"failure_class":"expired"},
        {"stage_id":"stage-b","cluster_name":"cluster-b","lab_code":"sandbox-c","failure_class":"network"},
    ])
    for refresh, _ in REFRESHES:
        refresh(db)
    assert snapshot(db) == reference(rows)


def test_window_includes_exact_24_hour_boundary(db):
    rows=seed(db,[{"evaluated_at":NOW-timedelta(hours=24)},
                  {"evaluated_at":NOW-timedelta(hours=24,microseconds=1),"failure_class":"expired"}])
    for refresh,_ in REFRESHES:
        refresh(db)
    assert snapshot(db)==reference(rows)


@pytest.mark.parametrize("refresh,table",REFRESHES)
def test_empty_window_removes_previous_summary(db,refresh,table):
    seed(db,[{}])
    refresh(db)
    assert db.query(table).count()==1
    db.query(EvaluationRecord).delete()
    db.commit()
    refresh(db)
    assert db.query(table).count()==0


@pytest.mark.parametrize("refresh,table",REFRESHES)
def test_all_history_counts_beyond_diagnostic_cap_with_group_sized_transport(db,refresh,table):
    count=6007
    seed(db,[{} for _ in range(count)])
    transported=[]
    selects=[]
    def measure(state):
        result=state.invoke_statement()
        if state.is_select:
            frozen=result.freeze()
            transported.append(len(frozen.data))
            selects.append(str(state.statement))
            return frozen()
        return result
    event.listen(db,"do_orm_execute",measure,retval=True)
    try:
        refresh(db)
    finally:
        event.remove(db,"do_orm_execute",measure)
    row=db.query(table).one()
    assert getattr(row,"failed",getattr(row,"fail_count",None))==count
    assert sum(transported)<=4, "Only summary groups, not evaluation history, may enter Python"
    assert len(selects)==1, "Counts and failure-class details must share one statement snapshot"
    assert selects and all("GROUP BY" in sql.upper() for sql in selects)


@pytest.mark.parametrize("refresh,table",REFRESHES)
def test_aggregation_finishes_before_summary_delete(db,refresh,table):
    seed(db,[{}])
    statements=[]
    def capture(conn,cursor,sql,params,context,many):
        statements.append(sql.upper())
    event.listen(db.get_bind(),"before_cursor_execute",capture)
    try:
        refresh(db)
    finally:
        event.remove(db.get_bind(),"before_cursor_execute",capture)
    reads=[i for i,sql in enumerate(statements) if sql.lstrip().startswith("SELECT") and "FROM EVALUATIONS" in sql]
    deletes=[i for i,sql in enumerate(statements) if sql.lstrip().startswith("DELETE")]
    assert reads and deletes and max(reads)<min(deletes), "Do not hold summary write locks during history aggregation"


def test_equal_failure_counts_have_stable_first_id_tiebreak_not_timestamp_or_name(db):
    seed(db,[{"failure_class":"z-first-id","evaluated_at":NOW-timedelta(hours=1)},
             {"failure_class":"a-second-id","evaluated_at":NOW-timedelta(hours=2)}])
    repository.refresh_lab_eval_summary(db)
    row=db.query(MVLabEvalSummary).one()
    assert row.top_failure_class=="z-first-id"
    assert row.failed==2 and row.health_rate==0


def test_many_output_labs_are_all_published_in_bounded_pending_batches(db):
    count=1003
    seed(db,[{"lab_code":f"sandbox-{i}"} for i in range(count)])
    pending=[]
    def before_flush(session, context, instances):
        pending.append(len(session.new))
    event.listen(db,"before_flush",before_flush)
    try:
        repository.refresh_lab_eval_summary(db)
    finally:
        event.remove(db,"before_flush",before_flush)
    assert db.query(MVLabEvalSummary).count()==count
    assert pending and max(pending)<=500


@pytest.mark.parametrize("refresh,table",REFRESHES)
def test_failed_aggregation_does_not_delete_previous_summary(db,refresh,table):
    seed(db,[{}])
    refresh(db)
    deleted=[]
    def fail_aggregation(conn,cursor,sql,params,context,many):
        if sql.lstrip().upper().startswith("DELETE"):
            deleted.append(sql)
        if sql.lstrip().upper().startswith("SELECT") and "FROM EVALUATIONS" in sql.upper():
            raise RuntimeError("synthetic aggregate failure")
    event.listen(db.get_bind(),"before_cursor_execute",fail_aggregation)
    try:
        with pytest.raises(RuntimeError,match="synthetic aggregate failure"):
            refresh(db)
    finally:
        event.remove(db.get_bind(),"before_cursor_execute",fail_aggregation)
        db.rollback()
    assert deleted==[]
    assert db.query(table).count()==1


@pytest.mark.parametrize("sample_seed",[3,11,29])
def test_randomized_grouped_results_match_rowwise_reference(db,sample_seed):
    import random
    rng=random.Random(sample_seed)
    rows=seed(db,[{
        "run_id":rng.choice(["synthetic","synthetic","k8s-mine-excluded","alert-mine-excluded","prom-mine-excluded"]),
        "cluster_name":rng.choice([None,"","cluster-a","cluster-b"]),
        "lab_code":rng.choice([None,"","sandbox-a","sandbox-b","sandbox-c"]),
        "stage_id":rng.choice(["stage-a","stage-b","stage-c"]),
        "outcome":rng.choice(["pass","FAIL","Warn","unknown",""]),
        "failure_class":rng.choice([None,"","pods","storage"," "]),
        "evaluated_at":NOW-timedelta(hours=rng.randrange(-2,31)),
    } for _ in range(700)])
    for refresh,_ in REFRESHES:
        refresh(db)
    assert snapshot(db)==reference(rows)


def test_summary_freshness_uses_publication_time_not_window_start(db,monkeypatch):
    from db import summary_refresh
    published=NOW+timedelta(seconds=3)
    class PublishClock(datetime):
        @classmethod
        def now(cls,tz=None):
            return published
    monkeypatch.setattr(summary_refresh,"datetime",PublishClock)
    seed(db,[{}])
    for refresh,table in REFRESHES:
        refresh(db)
        assert db.query(table).one().updated_at.replace(tzinfo=timezone.utc)==published
