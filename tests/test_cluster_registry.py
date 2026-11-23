"""The cluster registry has two sources of truth, and they drifted.

`STARGATE_CLUSTERS` is documented as the priority-1 registry, but the
scheduler Deployment also hardcodes `--clusters`, which is intersected with it.
Names that appear in only one of the two were dropped without a word.

Measured live on 2026-11-21:

    STARGATE_CLUSTERS   ocpv05, ocpv06, ocpv07, ocpv08, ocpv09
    --clusters          ocpv05, ocpv06, ocpv07, ocpv08, ocpv09
    started             ocpv06, ocpv07, ocpv08, ocpv09

`ocpv05` had no DNS record (`api.ocpv05.dal10.infra.demo.redhat.com: no such
host`) and had not been scanned since 2026-10-21. `ocpv03` was alive with 162
namespaces, 47 of them live `sandbox-*` labs, and had not been scanned since
2026-11-02. The scheduler reported `Clusters: 4` and a healthy cycle the whole
time, because "four of the five names you asked for matched" is not an error.
"""

from __future__ import annotations

from cli import scan
from cli.scheduler import select_clusters


def test_every_matching_name_is_started():
    registry = {"ocpv03": "kubeconfig-ocpv03", "ocpv06": "kubeconfig-ocpv06"}

    selected, unknown = select_clusters(registry, "ocpv03,ocpv06")

    assert selected == registry
    assert unknown == []


def test_a_name_missing_from_the_registry_is_started_not_silently_dropped():
    """The dead cluster, and the shape of the fix.

    Requesting a cluster the registry does not carry used to intersect it away.
    Now it is attempted with its canonical kubeconfig name — so a credential
    request for a new cluster is one env change, not two in lockstep — and
    reported so the operator can see the two sources disagree.
    """
    registry = {"ocpv03": "kubeconfig-ocpv03", "ocpv06": "kubeconfig-ocpv06"}

    selected, unknown = select_clusters(registry, "ocpv05,ocpv06")

    assert selected == {
        "ocpv05": "kubeconfig-ocpv05",
        "ocpv06": "kubeconfig-ocpv06",
    }
    assert unknown == ["ocpv05"], "the operator has to see that ocpv05 is not in the registry"


def test_requesting_only_the_registry_cluster_still_starts_the_other_one():
    """The 18-day bug: registry and --clusters agreed on nothing but ocpv06."""
    registry = {"ocpv06": "kubeconfig-ocpv06"}

    selected, unknown = select_clusters(registry, "ocpv03,ocpv06")

    assert set(selected) == {"ocpv03", "ocpv06"}
    assert unknown == ["ocpv03"]


def test_a_registry_filename_is_preferred_over_the_canonical_one():
    registry = {"ocpv06": "custom-ocpv06"}

    selected, _ = select_clusters(registry, "ocpv06")

    assert selected == {"ocpv06": "custom-ocpv06"}


def test_no_request_means_the_whole_registry():
    registry = {"ocpv03": "kubeconfig-ocpv03"}

    selected, unknown = select_clusters(registry, "")

    assert selected == registry
    assert unknown == []
    assert selected is not registry, "callers must not mutate the module-level registry"


def test_whitespace_and_empty_names_are_tolerated():
    registry = {"ocpv03": "kubeconfig-ocpv03"}

    selected, unknown = select_clusters(registry, " ocpv03 , , ")

    assert selected == registry
    assert unknown == []


def test_default_registry_names_the_live_clusters(monkeypatch):
    """The built-in default is what a deployment without STARGATE_CLUSTERS
    starts. It listed a cluster whose host has not resolved for a month and
    omitted one that is alive."""
    for key in ("STARGATE_CLUSTERS", "STARGATE_CLUSTERS_FILE"):
        monkeypatch.delenv(key, raising=False)

    clusters = scan.load_clusters()

    assert "ocpv05" not in clusters, "ocpv05's API host does not resolve"
    assert "ocpv03" in clusters
    assert clusters["ocpv03"] == "kubeconfig-ocpv03"
