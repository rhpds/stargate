import io
import urllib.error

from cli.worker import ClusterWorker, ClusterState


def test_cluster_health_retries_transient_api_failure(monkeypatch):
    worker = ClusterWorker.__new__(ClusterWorker)
    worker.api_url = "http://stargate-api:8090"
    worker.state = ClusterState(name="ocpv09", kubeconfig="kubeconfig-ocpv09")
    worker.state.node_data = {"avg_cpu": 20, "status": "healthy", "hot_nodes": 0}
    worker._api_headers = lambda: {"X-API-Key": "test"}

    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 500, "temporary", {}, io.BytesIO())
        return io.BytesIO(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("cli.worker.time.sleep", lambda _: None)

    worker.persist_cluster_health()

    assert calls[0] == calls[1] == "http://stargate-api:8090/runs"
    assert len(calls) == 10  # one retry plus eight successful requests
    assert calls[-1].endswith("/complete")  # the run is closed, not left running


def test_cluster_health_run_ids_include_subsecond_uniqueness(monkeypatch):
    worker = ClusterWorker.__new__(ClusterWorker)
    worker.api_url = "http://stargate-api:8090"
    worker.state = ClusterState(name="ocpv09", kubeconfig="kubeconfig-ocpv09")
    worker.state.node_data = {"avg_cpu": 20, "status": "healthy", "hot_nodes": 0}
    worker._api_headers = lambda: {"X-API-Key": "test"}
    requests = []

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: requests.append(req) or io.BytesIO(b"{}"))

    worker.persist_cluster_health()
    worker.persist_cluster_health()

    create_urls = [req.data.decode() for req in requests if req.full_url.endswith("/runs")]
    assert len(create_urls) == 2
    assert create_urls[0] != create_urls[1]


def _worker():
    worker = ClusterWorker.__new__(ClusterWorker)
    worker.api_url = "http://stargate-api:8090"
    worker.state = ClusterState(name="ocpv09", kubeconfig="kubeconfig-ocpv09")
    worker.state.node_data = {"avg_cpu": 20, "status": "healthy", "hot_nodes": 0}
    worker._api_headers = lambda: {"X-API-Key": "test"}
    return worker


def test_a_run_that_could_not_be_evaluated_is_closed_not_left_running(monkeypatch):
    """Found in production 2026-11-23: one persist cycle logged `timed out` and
    left its run `running` forever — 6 of 8 open runs since the restart were
    abandoned this way. /evaluate has a 1-in-~3000 tail above the client's 10 s
    timeout, so this is the expected shape of failure, not an exotic one."""
    worker = _worker()
    calls = []

    def urlopen(req, timeout):
        calls.append(req)
        if req.full_url.endswith("/evaluate"):
            raise TimeoutError("timed out")
        return io.BytesIO(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("cli.worker.time.sleep", lambda _: None)

    worker.persist_cluster_health()

    assert len([c for c in calls if c.full_url.endswith("/evaluate")]) == 3  # retried
    closes = [c for c in calls if c.full_url.endswith("/complete")]
    assert len(closes) == 1
    assert closes[0].data == b'{"status": "failed"}', (
        "the API accepts only completed/failed; an abandoned run must not stay "
        "indistinguishable from a scan in flight"
    )


def test_no_close_is_attempted_when_the_run_was_never_created(monkeypatch):
    worker = _worker()
    calls = []

    def urlopen(req, timeout):
        calls.append(req)
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("cli.worker.time.sleep", lambda _: None)

    worker.persist_cluster_health()

    assert not [c for c in calls if c.full_url.endswith("/complete")]


def test_a_failing_close_does_not_escape_the_persist_path(monkeypatch):
    """The close is best-effort: the API being unreachable for /evaluate usually
    means it is unreachable for /complete too, and that must not raise out of a
    tier-1 scan."""
    worker = _worker()
    calls = []

    def urlopen(req, timeout):
        calls.append(req)
        if req.full_url.endswith("/complete"):
            raise urllib.error.URLError("connection reset")
        if req.full_url.endswith("/evaluate"):
            raise TimeoutError("timed out")
        return io.BytesIO(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("cli.worker.time.sleep", lambda _: None)

    worker.persist_cluster_health()  # must not raise

    assert [c for c in calls if c.full_url.endswith("/complete")], (
        "the close was attempted and failed — that is the path under test"
    )

