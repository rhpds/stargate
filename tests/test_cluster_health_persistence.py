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
    assert len(calls) == 9  # one retry plus seven successful requests


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
