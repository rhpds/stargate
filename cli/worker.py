"""StarGate cluster worker — per-cluster evidence collection with tiered scheduling.

Each worker manages one cluster. Workers run independently with staggered offsets
so they never hit the API server simultaneously.

Tiers:
  Tier 1 (every 5 min):  Node metrics only — 1 API call, 300ms
  Tier 2 (every 15 min): Pod delta scan — 1 API call, detect new failures
  Tier 3 (every hour):   Namespace evidence — 5 namespaces at a time, rotated

Usage:
  # Single worker for one cluster
  python3 -m cli.worker --cluster ocpv06

  # All workers managed by the scheduler
  python3 -m cli.scheduler
"""

from __future__ import annotations

import logging
import json
import os
import subprocess
import sys
import tempfile
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from cli.kubeconfigs import SECRETS_DIR, resolve_kubeconfig
from db.lab_identity import is_lab_namespace

logger = logging.getLogger(__name__)


def _pick_showroom_host(stdout: str) -> str:
    """The `showroom-*` route host, or "" when the namespace has none.

    A namespace can expose adminer, console, containerview and showroom routes.
    Taking "the first route" measured the wrong thing: 16 Nov failures probed
    containerview and adminer while the showroom was healthy.
    """
    for line in (stdout or "").splitlines():
        name, _, host = line.partition("=")
        if host and "showroom" in name.strip().lower():
            return host.strip()
    return ""


VM_STAGES = "namespace-ready,storage-clone-ready,vm-runtime-ready"
CONTAINER_VM_STAGES = "namespace-ready,deployment-ready,route-ready,storage-clone-ready,vm-runtime-ready,showroom-healthy"
CONTAINER_STAGES = "namespace-ready,deployment-ready,route-ready,showroom-healthy"

TENANT_STAGES = "namespace-ready,deployment-ready,route-ready,showroom-healthy"

KNOWN_DEMO_TYPES: Dict[str, tuple] = {
    "ocp4-cluster": ("ocp4-cluster", VM_STAGES),
    "zt-ansiblebu": ("zt-ansible", CONTAINER_VM_STAGES),
    "zt-rhelbu": ("zt-rhel", CONTAINER_VM_STAGES),
    "zt-hpbu": ("zt-hp", CONTAINER_VM_STAGES),
    "agd-v2": ("agd-v2", CONTAINER_STAGES),
    "openshift-cnv": ("openshift-cnv", VM_STAGES),
    "ai-quickstarts": ("ai-quickstarts", CONTAINER_STAGES),
    "ai-qs": ("ai-quickstarts", CONTAINER_STAGES),
    "empty-config": ("empty-config", CONTAINER_STAGES),
    # Platform product, not a showroom lab (first human-reviewed
    # diagnosis, investigation 2609, Nov 13 2026): troshka has no
    # showroom component, so the showroom-healthy criterion was a
    # false positive by construction — 185 investigations of a
    # misconfiguration.
    "troshka": ("troshka", "namespace-ready,deployment-ready,route-ready"),
}


def _detect_demo_type(namespace: str) -> tuple:
    """Extract demo_id and stages from a namespace name.

    Supports:
      sandbox-{random}-{catalog_base}  → sandbox labs
      showroom-{hash}                  → showroom tenant
      user-{name}-{slug}               → user tenant namespace
    """
    ns = namespace

    if ns.startswith("showroom-"):
        return ("showroom", TENANT_STAGES)

    if ns.startswith("sandbox-"):
        parts = ns.split("-", 2)
        if len(parts) >= 3:
            suffix = parts[2]
        else:
            suffix = ns
    else:
        suffix = ns

    # Strip leading number prefixes (1-, 2-, etc.)
    while suffix and suffix[0].isdigit() and "-" in suffix:
        suffix = suffix.split("-", 1)[1]

    for pattern, (demo_id, stages) in KNOWN_DEMO_TYPES.items():
        if pattern in suffix:
            return (demo_id, stages)

    # Unknown type — use container stages as safe default
    return (suffix, CONTAINER_STAGES)


@dataclass
class ClusterState:
    """Cached state for a cluster to enable delta detection."""
    name: str
    kubeconfig: str
    last_node_scan: float = 0
    last_pod_scan: float = 0
    last_ns_scan: float = 0
    node_data: Dict = field(default_factory=dict)
    pod_status: Dict[str, str] = field(default_factory=dict)
    failing_namespaces: Set[str] = field(default_factory=set)
    scanned_namespaces: Set[str] = field(default_factory=set)
    all_sandbox_namespaces: List[str] = field(default_factory=list)
    # ns -> epoch of the last *attempted* collection. This is what tier 3
    # orders by; it replaces the rotation indices, which were positions in a
    # list that is re-sorted under them every tier-2 tick. See
    # `select_namespace_batch`.
    last_scanned_at: Dict[str, float] = field(default_factory=dict)
    scan_count: int = 0
    ns_outcomes: Dict[str, str] = field(default_factory=dict)
    storage_catalog_data: Optional[Dict] = None


def select_namespace_batch(
    failing: Iterable[str],
    healthy: Iterable[str],
    batch_size: int,
    last_scanned: Optional[Dict[str, float]] = None,
) -> List[str]:
    """Choose the namespaces for one tier-3 batch: oldest attempt first.

    Selection used to be an index into a *sorted* list, advanced by however
    many names were taken each tick. That is stable only while the list is.
    It is not: ``all_sandbox_namespaces`` is rebuilt from the pods collector
    every tier-2 tick while labs are created and destroyed, so the item at
    index *i* changes between ticks. A lab unlucky enough to keep landing on
    the wrong side of the cursor is skipped indefinitely, and nothing in the
    aggregate scan rate shows it — measured 2026-11-23 22:45Z, nine live
    namespaces were 5–6 h old on clusters whose throughput implied a one-hour
    sweep (docs/cluster-fleet.md).

    Ordering by the attempt timestamp instead of by position removes the
    whole class: the next batch is the least recently attempted namespaces,
    whatever the list did in between. Namespaces never attempted sort first
    (``0.0``), so a newly provisioned lab is picked up on the next tick.

    Failing namespaces still take up to half the batch — they are the ones
    worth watching more often — and the rest go to the oldest of the
    remainder. The caller is responsible for stamping every attempted
    namespace into ``last_scanned``, including attempts that failed: the
    rotation is over attempts, not successes, or a permanently broken lab
    would be retried every tick and crowd out everything else.

    Returns the batch. Invariants, which the tests pin:

    - a namespace attempted longer ago is always selected first;
    - a batch is ``batch_size`` long whenever the two lists together hold that
      many namespaces — a cluster that is entirely failing still fills it;
    - the selection does not depend on list order or on set iteration order.
    """
    if batch_size <= 0:
        return []

    last = last_scanned or {}
    failing_set = set(failing)
    failing_ordered = sorted(failing_set, key=lambda ns: (last.get(ns, 0.0), ns))
    healthy_ordered = sorted(
        (ns for ns in healthy if ns not in failing_set),
        key=lambda ns: (last.get(ns, 0.0), ns),
    )

    # Up to half the batch is reserved for the failing set; the rest goes to
    # the oldest of everything else. Never reserve more than there is.
    cap = max(1, batch_size // 2) if failing_ordered else 0
    batch = failing_ordered[:cap]
    batch += healthy_ordered[: batch_size - len(batch)]

    # Fewer healthy namespaces than slots (or none at all): keep taking the
    # oldest of the failing set instead of emitting a short batch.
    if len(batch) < batch_size:
        taken = set(batch)
        for ns in failing_ordered + healthy_ordered:
            if len(batch) >= batch_size:
                break
            if ns not in taken:
                batch.append(ns)
                taken.add(ns)

    return batch


class ClusterWorker:
    """Manages evidence collection for a single cluster."""

    TIER1_INTERVAL = 300    # 5 minutes
    TIER2_INTERVAL = 300    # 5 minutes
    TIER3_INTERVAL = 300    # 5 minutes
    TIER3_BATCH_SIZE = 150  # namespaces per tier 3 cycle
    # When set, tier 3 is not run inside `tick()`; the scheduler drives it from
    # its own thread (`WorkerThread._run_tier3`). Off by default, which
    # reproduces the old behaviour exactly. See `run_tier3_batch` for why it
    # exists: inside the tick, a batch's cadence is `tick_duration +
    # TIER1_INTERVAL`, and that sleep was 40% of the cycle on the live
    # scheduler (measured 2026-11-23).
    TIER3_INDEPENDENT = False
    # One namespace's collection is a batch of `oc get`s plus the probe run.
    # Without a ceiling a single hung namespace blocks the whole cycle.
    NS_COLLECT_TIMEOUT = int(os.environ.get("STARGATE_NS_COLLECT_TIMEOUT", "300"))

    def __init__(self, name: str, kubeconfig: str, api_url: Optional[str] = None):
        self.state = ClusterState(name=name, kubeconfig=kubeconfig)
        self.api_url = api_url
        self._kc_path = str(resolve_kubeconfig(name, kubeconfig))
        self._env = {**os.environ, "KUBECONFIG": self._kc_path}
        self._api_key = os.environ.get("STARGATE_ADMIN_API_KEY", "")
        # Last tier-3 result from the independent thread, so the scheduler can
        # still report `namespaces` in the tick result and on the dashboard.
        self.last_tier3_result: Optional[Dict] = None

    def _api_headers(self, content_type: str = "application/json") -> dict:
        headers = {"Content-Type": content_type}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    def is_available(self) -> bool:
        if not os.path.exists(self._kc_path):
            return False
        try:
            r = subprocess.run(
                ["oc", "whoami"], capture_output=True, text=True,
                timeout=10, env=self._env,
            )
            return bool(r.stdout.strip())
        except Exception as e:
            logger.warning("Cluster availability check failed: %s", e)
            return False

    def tick(self) -> Dict:
        """Run one scan cycle. Returns results dict."""
        now = time.time()
        result = {
            "cluster": self.state.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tiers_run": [],
        }

        # Tier 1: Node metrics + cluster-health evaluation
        if now - self.state.last_node_scan >= self.TIER1_INTERVAL:
            t1 = self._tier1_nodes()
            result["nodes"] = t1
            result["tiers_run"].append(1)
            self.state.last_node_scan = now
            self._tier1_storage_catalog()
            self.persist_cluster_health()
            self.persist_storage_catalog_health()

        # Tier 2: Pod delta
        if now - self.state.last_pod_scan >= self.TIER2_INTERVAL:
            t2 = self._tier2_pods()
            result["pods"] = t2
            self._last_pod_result = t2
            result["tiers_run"].append(2)
            self.state.last_pod_scan = now
        elif hasattr(self, '_last_pod_result') and self._last_pod_result:
            result["pods"] = self._last_pod_result

        # Tier 3: Namespace evidence (persisted)
        if not self.TIER3_INDEPENDENT and now - self.state.last_ns_scan >= self.TIER3_INTERVAL:
            t3 = self._tier3_namespaces()
            result["namespaces"] = t3
            result["tiers_run"].append(3)
            self.state.last_ns_scan = now

        self.state.scan_count += 1
        return result

    def _tier1_nodes(self) -> Dict:
        """Tier 1: Node CPU/memory — 1 API call."""
        try:
            r = subprocess.run(
                ["oc", "adm", "top", "nodes", "--no-headers"],
                capture_output=True, text=True, timeout=15, env=self._env,
            )
            nodes = []
            compute_count = 0
            total_cpu = 0
            hot = 0

            for line in r.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                name = parts[0]
                cpu_pct = int(parts[2].replace("%", ""))
                mem_pct = int(parts[4].replace("%", ""))
                nodes.append({"name": name, "cpu": cpu_pct, "mem": mem_pct})

                is_compute = "ceph" not in name and not name.endswith(("-cp", "-cp2", "-cp3"))
                if is_compute:
                    compute_count += 1
                    total_cpu += cpu_pct
                    if cpu_pct > 80:
                        hot += 1

            avg_cpu = round(total_cpu / compute_count, 1) if compute_count else 0

            result = {
                "total_nodes": len(nodes),
                "compute_nodes": compute_count,
                "avg_cpu": avg_cpu,
                "hot_nodes": hot,
                "status": "critical" if avg_cpu > 80 else "warning" if hot > 0 or avg_cpu > 70 else "healthy",
            }

            # Detect change from previous scan
            prev = self.state.node_data
            if prev:
                cpu_delta = avg_cpu - prev.get("avg_cpu", 0)
                result["cpu_delta"] = round(cpu_delta, 1)
                if abs(cpu_delta) > 10:
                    result["cpu_change"] = "spike" if cpu_delta > 0 else "drop"

            self.state.node_data = result
            return result

        except Exception as e:
            return {"error": str(e)}

    def _tier2_pods(self) -> Dict:
        """Tier 2: Pod status delta — 1 API call."""
        try:
            r = subprocess.run(
                ["oc", "get", "pods", "-A", "--no-headers"],
                capture_output=True, text=True, timeout=30, env=self._env,
            )

            current_status: Dict[str, str] = {}
            sandbox_ns = set()
            failing_ns = set()
            crashloops = 0
            total_vms = 0
            ocp4_labs = set()

            for line in r.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                ns, pod, _, status = parts[0], parts[1], parts[2], parts[3]
                key = f"{ns}/{pod}"
                current_status[key] = status

                is_lab_ns = (
                    is_lab_namespace(ns)
                    or ns.startswith("showroom-")
                    or ns.startswith("ocp4-cluster-")
                    or (ns.startswith("user-") and "showroom" in pod)
                )
                if is_lab_ns:
                    sandbox_ns.add(ns)
                    if status not in ("Running", "Completed", "Succeeded", "Terminating"):
                        failing_ns.add(ns)
                        if "CrashLoopBackOff" in status:
                            crashloops += 1
                    if "virt-launcher" in pod and status == "Running":
                        total_vms += 1
                    if "ocp4-cluster" in ns and status == "Running":
                        ocp4_labs.add(ns)

            # Detect changes from previous scan
            prev = self.state.pod_status
            new_failures = []
            recovered = []

            if prev:
                for key, status in current_status.items():
                    prev_status = prev.get(key)
                    if prev_status and prev_status == "Running" and status not in ("Running", "Completed", "Succeeded"):
                        new_failures.append({"pod": key, "status": status})
                    elif prev_status and prev_status not in ("Running", "Completed", "Succeeded") and status == "Running":
                        recovered.append({"pod": key})

            self.state.pod_status = current_status
            self.state.failing_namespaces = failing_ns
            self.state.all_sandbox_namespaces = sorted(sandbox_ns)
            # Drop attempt stamps for namespaces that no longer exist. Without
            # this the dict grows with every lab the fleet has ever run; the
            # set is rebuilt here from the pods collector, so this is the one
            # place that knows what is live.
            self.state.last_scanned_at = {
                ns: stamp
                for ns, stamp in self.state.last_scanned_at.items()
                if ns in sandbox_ns
            }

            compute_nodes = self.state.node_data.get("compute_nodes", 1) or 1

            return {
                "sandbox_active": len(sandbox_ns),
                "sandbox_failing": len(failing_ns),
                "crashloops": crashloops,
                "total_vms": total_vms,
                "ocp4_labs": len(ocp4_labs),
                "vms_per_node": round(total_vms / compute_nodes, 1),
                "new_failures": new_failures[:10],
                "recovered": recovered[:10],
                "delta": len(new_failures) > 0 or len(recovered) > 0,
            }

        except Exception as e:
            return {"error": str(e)}

    def run_tier3_batch(self) -> Dict:
        """Collect one tier-3 batch on its own clock, outside the tick loop.

        Inside `tick()` a batch's cadence is `tick_duration + TIER1_INTERVAL`:
        the loop ticks, then sleeps, and the tier-3 gate rides on top. Measured
        on the live scheduler on 2026-11-23, an ocpv07 batch cost 444 s and the
        following 300 s sleep was 40% of the 744 s cycle — so making the batch
        cheaper (a CPU limit change that halved per-namespace cost) bought only
        1.46x throughput, because the sleep is a fixed term.

        Called from its own thread, the cadence is the batch itself:
        `max(TIER3_INTERVAL, batch_duration)`. Nothing here is new work; it is
        `_tier3_namespaces` with the bookkeeping the tick used to do.
        """
        started = time.time()
        try:
            result = self._tier3_namespaces()
        except Exception as e:
            logger.exception("Tier 3 batch failed on %s: %s", self.state.name, e)
            return {"error": str(e)}
        # `last_ns_scan` is stamped from the start of the batch, matching what
        # tick() does with `now`, so a slow batch does not add its own duration
        # to the next interval as well.
        self.state.last_ns_scan = started
        self.last_tier3_result = result
        return result

    def _tier3_namespaces(self) -> Dict:
        """Tier 3: Namespace evidence collection — rotated batch, persisted."""
        if not self.api_url:
            return {"skipped": "no api_url configured"}

        # Priority: scan failing namespaces first, then the namespaces that
        # have waited longest. Ordering is by attempt time, not by an index
        # into the list — see select_namespace_batch for the starvation this
        # replaced.
        batch = select_namespace_batch(
            self.state.failing_namespaces,
            self.state.all_sandbox_namespaces,
            self.TIER3_BATCH_SIZE,
            self.state.last_scanned_at,
        )

        persisted = 0
        dropped = 0
        rejected_evidence = 0
        rejected_namespaces = 0
        passed = 0
        failed = 0
        failure_classes: Dict[str, int] = {}

        outcome_changes = []
        uuid_map: Dict[str, str] = {}  # serviceUuid -> namespace
        for ns in batch:
            # The lab identity IS the namespace — that is the key `live_labs`,
            # `EvaluationRecord.lab_code` and every report group on.
            #
            # This used to be resolved through LabMapping, which holds one row
            # per namespace that has ever existed, each carrying a *wildcard*
            # pattern (`sandbox-*-zt-rhelbu`) and its own namespace as lab_code.
            # `match_namespace_to_lab` returns the first pattern that matches,
            # so every member of a family resolved to one arbitrary sibling.
            # Measured against the live table: all 621 sandbox namespaces
            # resolved to just 6 lab codes, with 444 of them writing into the
            # single stale namespace `sandbox-5vpl6-ocp4-cluster`. The lab that
            # was actually collected never received the evaluation, so it aged
            # out of `live_labs` while a dead namespace kept looking healthy.
            #
            # LabMapping is for *enrichment* (owner, catalog item); it must not
            # decide who the evidence belongs to.
            result = self._collect_namespace(ns, lab_code=ns)
            # Stamp the attempt, success or failure. The rotation orders by
            # this, so a namespace whose collection keeps failing is retried
            # when it is the oldest — not every tick, which would crowd out
            # everything else.
            self.state.last_scanned_at[ns] = time.time()
            if result:
                if result.get("service_uuid"):
                    uuid_map[result["service_uuid"]] = ns
                if result.get("persisted") is False:
                    # The collection succeeded and the stages were evaluated;
                    # only the write was lost. Counting this as "persisted"
                    # is how a lab goes dark while the cycle looks clean.
                    dropped += 1
                    logger.warning(
                        "Namespace %s evaluated but not persisted: %s",
                        ns, result.get("persist_error") or "no run_id returned",
                    )
                else:
                    persisted += 1
                    # A stored run is not the same as stored evidence. The
                    # rubric read what was collected, so a refusal here means
                    # the report and the record disagree about the lab.
                    rejected = result.get("evidence_rejected") or 0
                    if rejected:
                        rejected_evidence += rejected
                        rejected_namespaces += 1
                stage_outcomes = [r.get("outcome") for r in result.get("results", [])]
                ns_outcome = "pass" if stage_outcomes and all(
                    outcome == "pass" for outcome in stage_outcomes
                ) else "indeterminate"
                for r in result.get("results", []):
                    if r["outcome"] == "pass":
                        passed += 1
                    elif r["outcome"] == "fail":
                        failed += 1
                        ns_outcome = "fail"
                        fc = r.get("failure_class", "unclassified")
                        failure_classes[fc] = failure_classes.get(fc, 0) + 1

                prev = self.state.ns_outcomes.get(ns)
                if prev and prev != ns_outcome and ns_outcome in ("pass", "fail"):
                    outcome_changes.append({
                        "namespace": ns,
                        "previous": prev,
                        "current": ns_outcome,
                        "direction": "degraded" if ns_outcome == "fail" else "recovered",
                    })
                self.state.ns_outcomes[ns] = ns_outcome

        self.state.scanned_namespaces.update(batch)

        if rejected_evidence:
            logger.warning(
                "Tier 3: the API rejected %d evidence rows across %d of %d namespaces; "
                "those runs are stored but under-evidenced",
                rejected_evidence, rejected_namespaces, len(batch),
            )

        # Resolve lab names from serviceUuids via Sandbox API
        if uuid_map and self.api_url:
            self._resolve_lab_names(uuid_map)

        return {
            "batch_size": len(batch),
            "persisted": persisted,
            "persist_failures": dropped,
            "evidence_rejected": rejected_evidence,
            "passed": passed,
            "failed": failed,
            "failure_classes": failure_classes,
            "total_scanned": len(self.state.scanned_namespaces),
            "total_available": len(self.state.all_sandbox_namespaces),
            "outcome_changes": outcome_changes,
        }

    def _collect_namespace(self, namespace: str, lab_code: Optional[str] = None) -> Optional[Dict]:
        """Collect evidence from a single namespace and persist via API."""
        tmpdir = tempfile.mkdtemp(prefix=f"sg-{self.state.name}-")

        resources = {
            "namespace": ["oc", "get", "namespace", namespace, "-o", "json"],
            "pods": ["oc", "get", "pods", "-n", namespace, "-o", "json"],
            "service": ["oc", "get", "services", "-n", namespace, "-o", "json"],
            "endpoints": ["oc", "get", "endpoints", "-n", namespace, "-o", "json"],
            "route": ["oc", "get", "routes", "-n", namespace, "-o", "json"],
            "deployment": ["oc", "get", "deployments", "-n", namespace, "-o", "json"],
            "vm": ["oc", "get", "vm", "-n", namespace, "-o", "json"],
            "vmi": ["oc", "get", "vmi", "-n", namespace, "-o", "json"],
            "dv": ["oc", "get", "dv", "-n", namespace, "-o", "json"],
            "pvc": ["oc", "get", "pvc", "-n", namespace, "-o", "json"],
        }

        for res, cmd in resources.items():
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=self._env)
                if r.returncode == 0 and r.stdout.strip():
                    with open(f"{tmpdir}/{res}.json", "w") as f:
                        f.write(r.stdout)
            except Exception as e:
                logger.debug("Resource collection failed: %s", e)

        # Extract serviceUuid from namespace labels for lab name resolution
        service_uuid = None
        catalog_item = ""
        try:
            ns_file = f"{tmpdir}/namespace.json"
            if os.path.exists(ns_file):
                with open(ns_file) as f:
                    ns_data = json.load(f)
                service_uuid = ns_data.get("metadata", {}).get("labels", {}).get("serviceUuid")
                # env_type is the catalog item slug (e.g. zt-rhel-bu-lab-developer-cnv);
                # a namespace suffix is shared by a whole catalog.
                catalog_item = (
                    ns_data.get("metadata", {}).get("annotations", {}).get("env_type", "")
                )
        except Exception:
            pass

        # HTTP health checks for showroom
        self._check_showroom_health(namespace, tmpdir, catalog_item=catalog_item)

        demo_id, stages = _detect_demo_type(namespace)

        try:
            r = subprocess.run(
                [sys.executable, "-m", "cli.stargate", "collect-dir", tmpdir,
                 "--stages", stages,
                 "--api-url", self.api_url,
                 "--demo-id", demo_id,
                 "--namespace", namespace,
                 "--lab-code", lab_code or namespace,
                 "--cluster-name", self.state.name,
                 "--format", "json"],
                capture_output=True, text=True, timeout=self.NS_COLLECT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            # A batch is 25 namespaces every 10 minutes, and route probes add
            # up to STARGATE_ROUTE_PROBE_TIMEOUT per route inside this call.
            shutil.rmtree(tmpdir, ignore_errors=True)
            logger.warning(
                "Namespace collection timed out for %s after %ss",
                namespace, self.NS_COLLECT_TIMEOUT,
            )
            return None

        shutil.rmtree(tmpdir, ignore_errors=True)

        try:
            result = json.loads(r.stdout)
            if service_uuid:
                result["service_uuid"] = service_uuid
            return result
        except Exception as e:
            stderr = (r.stderr or "").strip()
            logger.warning(
                "Namespace collection parse failed for %s: %s%s",
                namespace,
                e,
                f"; stderr={stderr[-1000:]}" if stderr else "",
            )
            return None

    def _resolve_lab_names(self, uuid_map: Dict[str, str]):
        """Batch-resolve serviceUuids to lab names via Sandbox API and persist to LabMapping."""
        import urllib.request
        import re

        sandbox_api = os.environ.get("STARGATE_SANDBOX_API_URL", "")
        sandbox_token = os.environ.get("STARGATE_SANDBOX_API_TOKEN", "")
        if not sandbox_api or not sandbox_token:
            return

        resolved = 0
        for service_uuid, namespace in uuid_map.items():
            try:
                req = urllib.request.Request(
                    f"{sandbox_api}/api/v1/placements?service_uuid={service_uuid}",
                    headers={"Authorization": f"Bearer {sandbox_token}"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    if isinstance(data, list) and data:
                        placement = data[0]
                    elif isinstance(data, dict) and data.get("items"):
                        placement = data["items"][0]
                    else:
                        continue

                    annotations = placement.get("annotations", {})
                    lab_name = (
                        placement.get("service_display_name")
                        or placement.get("catalog_item_display_name")
                        or annotations.get("catalog_item")
                        or placement.get("service_name")
                        or ""
                    )
                    owner = annotations.get("owner") or annotations.get("owner_email") or ""

                    from engine.namespace import strip_sandbox_prefix
                    ci_base = strip_sandbox_prefix(namespace)

                    # Persist to LabMapping via API
                    payload = json.dumps({
                        "lab_code": namespace,
                        "ci_name": lab_name or None,
                        "ci_base": ci_base,
                        "ci_slug": annotations.get("env_type", ""),
                        "namespace_pattern": f"sandbox-*-{ci_base}",
                        "cloud": annotations.get("comment", "")[:50] if annotations.get("comment") else None,
                        "clusters": [self.state.name],
                        "owner": owner,
                    }).encode()
                    post_req = urllib.request.Request(
                        f"{self.api_url}/labs/mappings",
                        data=payload,
                        headers=self._api_headers(),
                        method="PUT",
                    )
                    urllib.request.urlopen(post_req, timeout=5)
                    resolved += 1
            except Exception:
                continue

        if resolved:
            logger.info("Resolved %d lab names from Sandbox API", resolved)

    def _check_showroom_health(self, namespace: str, tmpdir: str, catalog_item: str = ""):
        """Check showroom readiness via route URL."""
        import ssl
        import urllib.request as urllib_req

        try:
            # A namespace can carry several routes; prefer the showroom one
            # rather than "whichever is first in the list".
            r = subprocess.run(
                ["oc", "get", "routes", "-n", namespace, "-o",
                 'jsonpath={range .items[*]}{.metadata.name}={.spec.host}{"\\n"}{end}'],
                capture_output=True, text=True, timeout=10, env=self._env,
            )
            host = _pick_showroom_host(r.stdout)
            if not host:
                # No showroom route: the lab may have none. Report it as
                # unobserved (indeterminate), not as a failure of a route we
                # never should have probed.
                showroom_data = {
                    "kind": "ShowroomHealth",
                    "metadata": {"name": "showroom", "namespace": namespace},
                    "status": {
                        "pod_running": True,
                        "route_reachable": None,
                        "readyz_status": None,
                        "content_loaded": None,
                        "response_time_ms": 0,
                        "route_url": "",
                        "http_status": 0,
                        "error": "no route with 'showroom' in the name",
                        "catalog_item": catalog_item,
                    },
                }
                with open(f"{tmpdir}/showroom_health.json", "w") as f:
                    json.dump(showroom_data, f)
                return

            ctx = ssl.create_default_context()
            if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

            showroom_reachable = False
            response_time = 99999
            readyz_status = 0
            error = ""
            import time as _t
            start = _t.time()
            try:
                req = urllib_req.Request(f"https://{host}")
                resp = urllib_req.urlopen(req, timeout=5, context=ctx)
                response_time = int((_t.time() - start) * 1000)
                showroom_reachable = resp.status == 200
                readyz_status = resp.status
            except urllib_req.HTTPError as exc:
                # A 503 here is the difference between "no endpoints" and
                # "upstream refused" — swallowing it made failures unreproducible.
                response_time = int((_t.time() - start) * 1000)
                readyz_status = exc.code
                error = f"HTTP {exc.code}"
            except Exception as exc:
                response_time = int((_t.time() - start) * 1000)
                error = f"{type(exc).__name__}: {str(exc)[:120]}"

            showroom_data = {
                "kind": "ShowroomHealth",
                "metadata": {"name": "showroom", "namespace": namespace},
                "status": {
                    "pod_running": True,
                    "route_reachable": showroom_reachable,
                    "readyz_status": readyz_status,
                    "content_loaded": showroom_reachable,
                    "response_time_ms": response_time,
                    # Reproducibility: the URL and status travel with the failure.
                    "route_url": f"https://{host}",
                    "http_status": readyz_status,
                    "error": error,
                    "catalog_item": catalog_item,
                },
            }
            with open(f"{tmpdir}/showroom_health.json", "w") as f:
                json.dump(showroom_data, f)

        except Exception:
            pass

    def _tier1_storage_catalog(self) -> Dict:
        """Tier 1b: storage headroom + OLM catalog freshness.

        The team's own gap table (Confluence 501907733, issues 5-6): Ceph
        alerts fire only when already near-full (wanted: 70% headroom
        alerts), and OLM catalog snapshots go stale silently. Validated
        signatures: RHDPOPS-24130 (blockpool near-full, Blocker),
        GPTEINFRA-17674 (24 image PVCs stuck Pending 8 days),
        RHDPOPS-24487/24480 (date-pinned catalog snapshots going stale).

        Three signals, each None when not applicable (non-ODF clusters).
        """
        data: Dict = {}
        prev = self.state.storage_catalog_data or {}

        # --- Ceph headroom: .status.ceph.capacity on the CephCluster ---
        try:
            r = subprocess.run(
                ["oc", "get", "cephcluster", "-n", "openshift-storage", "-o", "json"],
                capture_output=True, text=True, timeout=20, env=self._env,
            )
            if r.returncode == 0:
                items = json.loads(r.stdout or "{}").get("items", [])
                if items:
                    cap = (items[0].get("status") or {}).get("ceph", {}).get("capacity", {})
                    total = cap.get("bytesTotal") or 0
                    used = cap.get("bytesUsed") or 0
                    if total > 0:
                        data["ceph"] = {
                            "utilization_pct": round(100.0 * used / total, 1),
                            "bytes_total": total,
                            "bytes_used": used,
                            "phase": (items[0].get("status") or {}).get("phase"),
                            "last_updated": cap.get("lastUpdated"),
                        }
                    else:
                        data["ceph"] = prev.get("ceph")  # capacity not reported yet
                else:
                    # Definitively no ODF on this cluster: vacuously healthy.
                    data["ceph"] = {"not_installed": True, "utilization_pct": None}
            else:
                data["ceph"] = prev.get("ceph")  # transient failure — keep last good
        except Exception as e:
            data["ceph"] = prev.get("ceph")
            logger.debug("%s: ceph capacity check failed: %s", self.state.name, e)

        # --- Pending PVCs: the documented 'stuck for 8 days' signature ---
        # (status.phase is not a valid PVC field selector — filter client-side)
        try:
            r = subprocess.run(
                ["oc", "get", "pvc", "-A", "-o", "json"],
                capture_output=True, text=True, timeout=30, env=self._env,
            )
            if r.returncode == 0:
                all_pvcs = json.loads(r.stdout or "{}").get("items", [])
                items = [
                    p for p in all_pvcs
                    if (p.get("status") or {}).get("phase") == "Pending"
                ]
                now = time.time()
                max_age = 0
                for pvc in items:
                    created = (pvc.get("metadata") or {}).get("creationTimestamp", "")
                    try:
                        ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        age = now - ts.timestamp()
                        max_age = max(max_age, age)
                    except (ValueError, AttributeError):
                        pass
                data["pending_pvcs"] = {
                    "count": len(items),
                    "max_age_seconds": round(max_age),
                }
            else:
                data["pending_pvcs"] = prev.get("pending_pvcs")
        except Exception as e:
            data["pending_pvcs"] = prev.get("pending_pvcs")
            logger.debug("%s: pending PVC check failed: %s", self.state.name, e)

        # --- CatalogSource readiness + freshness ---
        try:
            r = subprocess.run(
                ["oc", "get", "catalogsource", "-A", "-o", "json"],
                capture_output=True, text=True, timeout=20, env=self._env,
            )
            if r.returncode == 0:
                items = json.loads(r.stdout or "{}").get("items", [])
                now = time.time()
                not_ready, stale = [], []
                for src in items:
                    name = (src.get("metadata") or {}).get("name", "?")
                    ns = (src.get("metadata") or {}).get("namespace", "?")
                    conn = ((src.get("status") or {}).get("connectionState") or {})
                    if conn.get("lastObservedState") != "READY":
                        not_ready.append(f"{ns}/{name}")
                    # Non-marketplace sources are custom snapshots (the
                    # documented staleness case) — flag beyond 45 days.
                    if ns != "openshift-marketplace":
                        created = (src.get("metadata") or {}).get("creationTimestamp", "")
                        try:
                            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            if now - ts.timestamp() > 45 * 86400:
                                stale.append(f"{ns}/{name}")
                        except (ValueError, AttributeError):
                            pass
                data["catalogs"] = {
                    "total": len(items),
                    "not_ready": not_ready,
                    "stale_custom": stale,
                }
            else:
                data["catalogs"] = prev.get("catalogs")
        except Exception as e:
            data["catalogs"] = prev.get("catalogs")
            logger.debug("%s: catalog source check failed: %s", self.state.name, e)

        self.state.storage_catalog_data = data
        return data

    def _cluster_health_evidence(self) -> Dict:
        """Build the cluster-health evidence dict (v0.1.0 criteria only)."""
        n = self.state.node_data
        return {
            "cluster_reachable": True,
            "cpu_usage_acceptable": (n.get("avg_cpu", 0) or 0) < 80,
            "memory_usage_acceptable": True,
            "no_critical_alerts": n.get("status") != "critical",
            "nodes_healthy": n.get("hot_nodes", 0) == 0,
        }

    def _storage_catalog_evidence(self) -> Dict:
        """Build storage-catalog-health evidence (tri-state).

        - ceph not installed on the cluster → vacuously True (nothing to
          fill); collection never succeeded yet → None (criterion
          unobserved, stage indeterminate — honest "don't know")
        - False = the condition the ops gap table asked to catch: Ceph
          at 70%+ (wanted: alerts at 70, not near-full), PVCs Pending
          beyond 1h, catalog sources not READY or stale custom snapshots
        """
        sc = self.state.storage_catalog_data or {}
        evidence: Dict = {}
        ceph = sc.get("ceph")
        if ceph is None:
            evidence["ceph_headroom_ok"] = None  # never collected — unobserved
        elif ceph.get("not_installed"):
            evidence["ceph_headroom_ok"] = True  # no ODF → vacuously fine
        else:
            evidence["ceph_headroom_ok"] = ceph.get("utilization_pct", 0) < 70
        pvcs = sc.get("pending_pvcs")
        evidence["pvc_pending_ok"] = (
            (pvcs.get("count", 0) == 0 or pvcs.get("max_age_seconds", 0) < 3600)
            if pvcs is not None else None
        )
        cats = sc.get("catalogs")
        evidence["olm_catalogs_ready"] = (
            (not cats.get("not_ready") and not cats.get("stale_custom"))
            if cats is not None else None
        )
        return evidence

    def _persist_stage_evaluation(self, stage_id: str, demo_id: str, evidence: Dict,
                                  run_prefix: str) -> None:
        """Post a run + stage + evidence + evaluate to the API.

        Shared plumbing for the Tier 1 stage evaluations (cluster-health,
        storage-catalog-health). Evidence values of None are not posted as
        individual evidence items (not-applicable criteria are not
        'fail') but are carried in the evaluate body for the rubric's
        None-skip semantics.
        """
        if not self.api_url:
            return

        import urllib.error as urllib_error
        import urllib.request as urllib_req

        def send(req, *, attempts: int = 3):
            """Retry transient API failures without duplicating a scan run."""
            for attempt in range(attempts):
                try:
                    return urllib_req.urlopen(req, timeout=10)
                except urllib_error.HTTPError as exc:
                    if exc.code < 500 or attempt == attempts - 1:
                        raise
                except (TimeoutError, urllib_error.URLError):
                    if attempt == attempts - 1:
                        raise
                time.sleep(0.25 * (2 ** attempt))

        created = False
        try:
            run_id = f"{run_prefix}-{self.state.name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"
            body = json.dumps({
                "run_id": run_id,
                "demo_id": demo_id,
                "namespace": self.state.name,
                "requested_by": "scheduler",
                "lab_code": self.state.name,
                "cluster_name": self.state.name,
            }).encode()
            req = urllib_req.Request(
                f"{self.api_url}/runs",
                data=body,
                headers=self._api_headers(),
            )
            send(req)
            created = True

            req = urllib_req.Request(
                f"{self.api_url}/runs/{run_id}/stages/{stage_id}/start",
                method="POST",
                headers=self._api_headers(),
            )
            send(req)

            for key, val in evidence.items():
                if val is None:
                    continue  # not-applicable criteria: record nothing, not "fail"
                ev_body = json.dumps({
                    "type": "cluster_metric",
                    "source": "scheduler",
                    "observed": {key: val},
                    "result": "pass" if val else "fail",
                }).encode()
                req = urllib_req.Request(
                    f"{self.api_url}/runs/{run_id}/stages/{stage_id}/evidence",
                    data=ev_body,
                    headers=self._api_headers(),
                )
                send(req)

            body = json.dumps({"evidence": evidence}).encode()
            req = urllib_req.Request(
                f"{self.api_url}/runs/{run_id}/stages/{stage_id}/evaluate",
                data=body,
                headers=self._api_headers(),
            )
            resp = send(req)
            outcome = ""
            try:
                outcome = json.loads(resp.read()).get("outcome", "") if resp else ""
            except Exception:
                outcome = ""

            # Close the run: tier-1 scans created a run every cycle and never
            # completed it (98% of production runs were stuck in `running`).
            req = urllib_req.Request(
                f"{self.api_url}/runs/{run_id}/complete",
                data=json.dumps(
                    {"status": "failed" if outcome == "fail" else "completed"}
                ).encode(),
                headers=self._api_headers(),
            )
            send(req)
        except Exception as e:
            logger.warning("Failed to persist %s evaluation: %s", stage_id, e)
            if created:
                # The run exists and will never be evaluated. Leaving it
                # `running` is worse than closing it wrongly: an open run is
                # indistinguishable from a scan in flight, and it poisons MTTR
                # and duration queries — the exact failure `/complete` was added
                # to fix (541,317 of 551,765 production runs were open). The API
                # accepts only `completed` or `failed`, so this says `failed`
                # and the log line above keeps the distinction a human needs.
                #
                # One attempt, no retry: this is already the failure path, and a
                # second slow call here would block the cluster loop again.
                try:
                    req = urllib_req.Request(
                        f"{self.api_url}/runs/{run_id}/complete",
                        data=json.dumps({"status": "failed"}).encode(),
                        headers=self._api_headers(),
                    )
                    urllib_req.urlopen(req, timeout=10)
                except Exception as close_exc:
                    logger.warning(
                        "Could not close run %s after a failed persist: %s",
                        run_id, close_exc,
                    )

    def persist_cluster_health(self):
        """Persist cluster-health evaluation from Tier 1 node data."""
        if not self.api_url or not self.state.node_data:
            return
        self._persist_stage_evaluation(
            "cluster-health", "cluster-health",
            self._cluster_health_evidence(), "cluster-health",
        )

    def persist_storage_catalog_health(self):
        """Persist storage-catalog-health evaluation from Tier 1b data.

        Separate stage from cluster-health by design: the storage/catalog
        criteria are new and must not change cluster-health semantics for
        evidence recorded before them (replay, synthetic pipelines).
        """
        if not self.api_url or not self.state.storage_catalog_data:
            return
        self._persist_stage_evaluation(
            "storage-catalog-health", "storage-catalog-health",
            self._storage_catalog_evidence(), "storage-catalog-health",
        )


    def format_status(self) -> str:
        """One-line status for this cluster."""
        n = self.state.node_data
        p = self.state.pod_status
        s = self.state

        if not n:
            return f"{s.name}: not scanned yet"

        status = n.get("status", "?")
        icon = "🔴" if status == "critical" else "🟡" if status == "warning" else "🟢"

        parts = [
            f"{icon} {s.name}",
            f"{n.get('avg_cpu', 0):.0f}% CPU",
            f"{n.get('hot_nodes', 0)} hot",
        ]

        if hasattr(self, '_last_pod_result') and self._last_pod_result:
            pr = self._last_pod_result
            parts.append(f"{pr.get('total_vms', 0)} VMs")
            parts.append(f"{pr.get('vms_per_node', 0):.0f}/node")
            parts.append(f"{pr.get('crashloops', 0)} crash")

        return " | ".join(parts)


def run_worker(name: str, kubeconfig: str, api_url: Optional[str] = None, once: bool = False):
    """Run a single cluster worker."""
    worker = ClusterWorker(name, kubeconfig, api_url)

    if not worker.is_available():
        print(f"{name}: not available (kubeconfig missing or token expired)")
        return

    print(f"Worker started: {name}")
    if api_url:
        print(f"  Persisting to: {api_url}")
    print()

    # First run: do all tiers immediately
    worker.state.last_node_scan = 0
    worker.state.last_pod_scan = 0
    worker.state.last_ns_scan = 0

    while True:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        result = worker.tick()
        tiers = result.get("tiers_run", [])

        print(f"[{ts}] {name}: tiers {tiers}")

        if "nodes" in result:
            n = result["nodes"]
            print(f"  Nodes: {n.get('avg_cpu', 0):.0f}% avg CPU, {n.get('hot_nodes', 0)} hot")
            if n.get("cpu_change"):
                print(f"  CPU {n['cpu_change']}: {n.get('cpu_delta', 0):+.1f}%")

        if "pods" in result:
            p = result["pods"]
            print(f"  Pods: {p.get('sandbox_active', 0)} active, {p.get('sandbox_failing', 0)} failing, {p.get('crashloops', 0)} crashloop")
            print(f"  VMs: {p.get('total_vms', 0)} ({p.get('vms_per_node', 0):.0f}/node)")
            if p.get("new_failures"):
                print(f"  NEW FAILURES:")
                for f in p["new_failures"][:5]:
                    print(f"    {f['pod']}: {f['status']}")
            if p.get("recovered"):
                print(f"  RECOVERED:")
                for r in p["recovered"][:5]:
                    print(f"    {r['pod']}")

        if "namespaces" in result:
            ns = result["namespaces"]
            if ns.get("skipped"):
                print(f"  Namespaces: {ns['skipped']}")
            else:
                print(f"  Namespaces: {ns.get('persisted', 0)} persisted ({ns.get('passed', 0)} passed, {ns.get('failed', 0)} failed)")
                if ns.get("evidence_rejected"):
                    print(f"    Evidence: {ns['evidence_rejected']} rows rejected by the API")
                if ns.get("failure_classes"):
                    for fc, count in sorted(ns["failure_classes"].items(), key=lambda x: -x[1]):
                        print(f"    {fc}: {count}")
                print(f"  Coverage: {ns.get('total_scanned', 0)}/{ns.get('total_available', 0)} namespaces scanned")

        print()

        if once:
            break

        # Sleep until next tier 1 interval
        time.sleep(worker.TIER1_INTERVAL)


def main():
    import argparse

    parser = argparse.ArgumentParser(prog="stargate-worker", description="StarGate per-cluster worker")
    parser.add_argument("--cluster", required=True, help="Cluster name")
    parser.add_argument("--api-url", help="StarGate API URL for persistence")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    from cli.scan import CLUSTERS
    if args.cluster not in CLUSTERS:
        print(f"Unknown cluster: {args.cluster}", file=sys.stderr)
        print(f"Available: {', '.join(CLUSTERS.keys())}", file=sys.stderr)
        return 1

    run_worker(args.cluster, CLUSTERS[args.cluster], args.api_url, args.once)


if __name__ == "__main__":
    sys.exit(main() or 0)

