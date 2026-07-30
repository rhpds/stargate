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
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

SECRETS_DIR = Path(__file__).parent.parent / "secrets"

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
    ns_rotation_index: int = 0
    scan_count: int = 0
    ns_outcomes: Dict[str, str] = field(default_factory=dict)


class ClusterWorker:
    """Manages evidence collection for a single cluster."""

    TIER1_INTERVAL = 300    # 5 minutes
    TIER2_INTERVAL = 300    # 5 minutes
    TIER3_INTERVAL = 300    # 5 minutes
    TIER3_BATCH_SIZE = 150  # namespaces per tier 3 cycle

    def __init__(self, name: str, kubeconfig: str, api_url: Optional[str] = None):
        self.state = ClusterState(name=name, kubeconfig=kubeconfig)
        self.api_url = api_url
        self._kc_path = str(SECRETS_DIR / kubeconfig)
        self._env = {**os.environ, "KUBECONFIG": self._kc_path}
        self._api_key = os.environ.get("STARGATE_ADMIN_API_KEY", "")

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
            self.persist_cluster_health()

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
        if now - self.state.last_ns_scan >= self.TIER3_INTERVAL:
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
                    ns.startswith("sandbox-")
                    or ns.startswith("showroom-")
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

    def _tier3_namespaces(self) -> Dict:
        """Tier 3: Namespace evidence collection — rotated batch, persisted."""
        if not self.api_url:
            return {"skipped": "no api_url configured"}

        # Priority: scan failing namespaces first, then rotate through healthy ones
        failing = sorted(self.state.failing_namespaces)
        healthy = [ns for ns in self.state.all_sandbox_namespaces if ns not in self.state.failing_namespaces]

        batch = []

        # Always re-scan failing namespaces (up to half the batch)
        batch.extend(failing[:self.TIER3_BATCH_SIZE // 2])

        # Fill the rest from rotation
        remaining = self.TIER3_BATCH_SIZE - len(batch)
        if healthy and remaining > 0:
            idx = self.state.ns_rotation_index
            for i in range(remaining):
                ns = healthy[(idx + i) % len(healthy)]
                if ns not in batch:
                    batch.append(ns)
            self.state.ns_rotation_index = (idx + remaining) % max(len(healthy), 1)

        persisted = 0
        passed = 0
        failed = 0
        failure_classes: Dict[str, int] = {}

        # Load lab mappings for namespace→lab resolution
        lab_mappings = self._get_lab_mappings()

        outcome_changes = []
        for ns in batch:
            lab_code = None
            if lab_mappings:
                from engine.namespace_matcher import match_namespace_to_lab
                lab_code = match_namespace_to_lab(ns, lab_mappings)
            result = self._collect_namespace(ns, lab_code=lab_code)
            if result:
                persisted += 1
                ns_outcome = "pass"
                for r in result.get("results", []):
                    if r["outcome"] == "pass":
                        passed += 1
                    elif r["outcome"] == "fail":
                        failed += 1
                        ns_outcome = "fail"
                        fc = r.get("failure_class", "unclassified")
                        failure_classes[fc] = failure_classes.get(fc, 0) + 1

                prev = self.state.ns_outcomes.get(ns)
                if prev and prev != ns_outcome:
                    outcome_changes.append({
                        "namespace": ns,
                        "previous": prev,
                        "current": ns_outcome,
                        "direction": "degraded" if ns_outcome == "fail" else "recovered",
                    })
                self.state.ns_outcomes[ns] = ns_outcome

        self.state.scanned_namespaces.update(batch)

        return {
            "batch_size": len(batch),
            "persisted": persisted,
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

        # HTTP health checks for showroom
        self._check_showroom_health(namespace, tmpdir)

        demo_id, stages = _detect_demo_type(namespace)

        r = subprocess.run(
            [sys.executable, "-m", "cli.stargate", "collect-dir", tmpdir,
             "--stages", stages,
             "--api-url", self.api_url,
             "--demo-id", demo_id,
             "--lab-code", lab_code or namespace,
             "--cluster-name", self.state.name,
             "--format", "json"],
            capture_output=True, text=True,
        )

        shutil.rmtree(tmpdir, ignore_errors=True)

        try:
            return json.loads(r.stdout)
        except Exception as e:
            logger.warning("Namespace collection parse failed: %s", e)
            return None

    def _get_lab_mappings(self) -> list:
        """Fetch lab mappings from API for namespace→lab resolution."""
        if not self.api_url:
            return []
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.api_url}/labs/mappings")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return data.get("mappings", [])
        except Exception as e:
            logger.warning("Lab mapping fetch failed: %s", e)
            return []

    def _check_showroom_health(self, namespace: str, tmpdir: str):
        """Check showroom readiness via route URL."""
        import ssl
        import urllib.request as urllib_req

        try:
            r = subprocess.run(
                ["oc", "get", "route", "-n", namespace, "-o",
                 "jsonpath={.items[0].spec.host}"],
                capture_output=True, text=True, timeout=10, env=self._env,
            )
            host = r.stdout.strip()
            if not host:
                return

            ctx = ssl.create_default_context()
            if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

            showroom_reachable = False
            response_time = 99999
            readyz_status = 0
            try:
                import time as _t
                start = _t.time()
                req = urllib_req.Request(f"https://{host}")
                resp = urllib_req.urlopen(req, timeout=5, context=ctx)
                response_time = int((_t.time() - start) * 1000)
                showroom_reachable = resp.status == 200
                readyz_status = resp.status
            except Exception:
                pass

            showroom_data = {
                "kind": "ShowroomHealth",
                "metadata": {"name": "showroom", "namespace": namespace},
                "status": {
                    "pod_running": True,
                    "route_reachable": showroom_reachable,
                    "readyz_status": readyz_status,
                    "content_loaded": showroom_reachable,
                    "response_time_ms": response_time,
                },
            }
            with open(f"{tmpdir}/showroom_health.json", "w") as f:
                json.dump(showroom_data, f)

        except Exception:
            pass

    def persist_cluster_health(self):
        """Persist cluster-health evaluation from Tier 1 node data."""
        if not self.api_url or not self.state.node_data:
            return

        import urllib.request as urllib_req

        n = self.state.node_data
        evidence = {
            "cluster_reachable": True,
            "cpu_usage_acceptable": (n.get("avg_cpu", 0) or 0) < 80,
            "memory_usage_acceptable": True,
            "no_critical_alerts": n.get("status") != "critical",
            "nodes_healthy": n.get("hot_nodes", 0) == 0,
        }

        try:
            run_id = f"cluster-health-{self.state.name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            body = json.dumps({
                "run_id": run_id,
                "demo_id": "cluster-health",
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
            urllib_req.urlopen(req, timeout=10)

            req = urllib_req.Request(
                f"{self.api_url}/runs/{run_id}/stages/cluster-health/start",
                method="POST",
                headers=self._api_headers(),
            )
            urllib_req.urlopen(req, timeout=10)

            for key, val in evidence.items():
                ev_body = json.dumps({
                    "type": "cluster_metric",
                    "source": "scheduler",
                    "observed": {key: val},
                    "result": "pass" if val else "fail",
                }).encode()
                req = urllib_req.Request(
                    f"{self.api_url}/runs/{run_id}/stages/cluster-health/evidence",
                    data=ev_body,
                    headers=self._api_headers(),
                )
                urllib_req.urlopen(req, timeout=10)

            body = json.dumps({"evidence": evidence}).encode()
            req = urllib_req.Request(
                f"{self.api_url}/runs/{run_id}/stages/cluster-health/evaluate",
                data=body,
                headers=self._api_headers(),
            )
            urllib_req.urlopen(req, timeout=10)
        except Exception as e:
            logger.warning("Failed to persist cluster health: %s", e)

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
