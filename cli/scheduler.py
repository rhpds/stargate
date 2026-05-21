"""StarGate scheduler — manages distributed cluster workers with staggered offsets.

Spawns one worker per cluster in separate threads. Each worker runs on its own
schedule with a time offset so they never hit the API server simultaneously.

Usage:
  # Run all workers with default settings
  python3 -m cli.scheduler

  # With API persistence
  python3 -m cli.scheduler --api-url http://localhost:8090

  # Custom intervals
  python3 -m cli.scheduler --api-url http://localhost:8090 --tier1 300 --tier2 900 --tier3 3600

  # Subset of clusters
  python3 -m cli.scheduler --api-url http://localhost:8090 --clusters ocpv06,ocpv07,ocpv08
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from cli.worker import ClusterWorker
from cli.scan import CLUSTERS, SECRETS_DIR


class WorkerThread:
    """Wraps a ClusterWorker in a thread with offset scheduling."""

    def __init__(self, worker: ClusterWorker, offset_seconds: float):
        self.worker = worker
        self.offset = offset_seconds
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.last_result: Optional[Dict] = None
        self.error_count = 0
        self.tick_count = 0

    def start(self):
        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            name=f"worker-{self.worker.state.name}",
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        self.running = False

    def _run(self):
        # Initial offset — stagger startup
        if self.offset > 0:
            time.sleep(self.offset)

        # First tick: run all tiers immediately
        self.worker.state.last_node_scan = 0
        self.worker.state.last_pod_scan = 0
        self.worker.state.last_ns_scan = 0

        while self.running:
            try:
                self.last_result = self.worker.tick()
                self.tick_count += 1
                self.error_count = 0
            except Exception as e:
                self.error_count += 1
                self.last_result = {
                    "cluster": self.worker.state.name,
                    "error": str(e),
                    "error_count": self.error_count,
                }
                # Exponential backoff on errors: 30s, 60s, 120s, max 300s
                backoff = min(30 * (2 ** (self.error_count - 1)), 300)
                time.sleep(backoff)
                continue

            # Sleep until next tier 1 interval
            time.sleep(self.worker.TIER1_INTERVAL)


class Scheduler:
    """Manages multiple cluster workers with staggered scheduling."""

    STAGGER_SECONDS = 30  # offset between cluster scans
    SCAN_SAVE_INTERVAL = 300  # write scan-history file every 5 minutes

    def __init__(
        self,
        clusters: Dict[str, str],
        api_url: Optional[str] = None,
        tier1: int = 300,
        tier2: int = 300,
        tier3: int = 300,
        tier3_batch: int = 150,
    ):
        self.workers: List[WorkerThread] = []
        self._shutdown = threading.Event()

        for i, (name, kubeconfig) in enumerate(clusters.items()):
            kc_path = str(SECRETS_DIR / kubeconfig)
            if not Path(kc_path).exists():
                continue

            worker = ClusterWorker(name, kubeconfig, api_url)
            worker.TIER1_INTERVAL = tier1
            worker.TIER2_INTERVAL = tier2
            worker.TIER3_INTERVAL = tier3
            worker.TIER3_BATCH_SIZE = tier3_batch

            offset = i * self.STAGGER_SECONDS
            self.workers.append(WorkerThread(worker, offset))

    def start(self):
        """Start all workers including Babylon control plane."""
        available = []
        unavailable = []

        for wt in self.workers:
            if wt.worker.is_available():
                wt.start()
                available.append(wt.worker.state.name)
            else:
                unavailable.append(wt.worker.state.name)

        # Start Babylon control plane worker
        self._babylon_thread = threading.Thread(
            target=self._run_babylon_worker,
            name="worker-babylon",
            daemon=True,
        )
        self._babylon_running = True
        self._babylon_result = None
        self._babylon_thread.start()
        available.append("babylon-control-plane")

        # Start scan-history writer
        self._history_thread = threading.Thread(
            target=self._run_history_writer,
            name="worker-history",
            daemon=True,
        )
        self._history_thread.start()

        return available, unavailable

    def _run_babylon_worker(self):
        """Run Babylon control plane collection on its own schedule."""
        import os
        kc = str(SECRETS_DIR / "kubeconfig")
        if not os.path.exists(kc):
            return

        # Initial offset — let cluster workers start first
        time.sleep(self.STAGGER_SECONDS * len(self.workers))

        from cli.babylon_worker import run_collection
        while self._babylon_running:
            try:
                self._babylon_result = run_collection()
            except Exception as e:
                self._babylon_result = {"error": str(e)}
            # Run every 3 minutes
            time.sleep(180)

    def _run_history_writer(self):
        """Periodically write scan-history files from live worker data."""
        time.sleep(60)  # wait for first ticks to complete

        history_dir = Path(__file__).parent.parent / "scan-history"
        history_dir.mkdir(exist_ok=True)

        while not self._shutdown.is_set():
            scan_data = []
            for wt in self.workers:
                if wt.tick_count == 0 or not wt.last_result:
                    continue
                r = wt.last_result
                nodes = r.get("nodes", {})
                pods = r.get("pods", {})

                compute_nodes = nodes.get("compute_nodes", 1) or 1
                total_vms = pods.get("total_vms", 0)
                sandbox_active = pods.get("sandbox_active", 0)
                sandbox_failing = pods.get("sandbox_failing", 0)
                crashloops = pods.get("crashloops", 0)
                avg_cpu = nodes.get("avg_cpu", 0)
                hot_nodes = nodes.get("hot_nodes", 0)
                vms_per_node = round(total_vms / compute_nodes, 1) if compute_nodes else 0

                status = "healthy"
                issues = []
                if avg_cpu and avg_cpu > 80:
                    status = "critical"
                    issues.append(f"avg CPU {avg_cpu}%")
                elif avg_cpu and avg_cpu > 70:
                    status = "warning"
                if hot_nodes > 0:
                    if status == "healthy":
                        status = "warning"
                    issues.append(f"{hot_nodes} nodes >80% CPU")
                if vms_per_node > 50:
                    if status != "critical":
                        status = "warning"
                    issues.append(f"{vms_per_node} VMs/node (threshold: 30)")
                if crashloops > 0:
                    issues.append(f"{crashloops} showroom CrashLoopBackOff")

                health_rate = 0
                if sandbox_active > 0:
                    health_rate = round((sandbox_active - sandbox_failing) / sandbox_active * 100, 1)

                scan_data.append({
                    "cluster": wt.worker.state.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "nodes": nodes.get("total_nodes", 0),
                    "compute_nodes": compute_nodes,
                    "avg_cpu_pct": avg_cpu,
                    "hot_nodes": hot_nodes,
                    "sandbox_active": sandbox_active,
                    "sandbox_failing": sandbox_failing,
                    "sandbox_crashloop": crashloops,
                    "total_vms": total_vms,
                    "ocp4_cluster_labs": pods.get("ocp4_labs", 0),
                    "vms_per_node": vms_per_node,
                    "health_rate": health_rate,
                    "dns_warnings": 0,
                    "status": status,
                    "issues": issues,
                    "new_failures": pods.get("new_failures", [])[:10],
                    "recovered": pods.get("recovered", [])[:10],
                    "all_sandbox_namespaces": list(getattr(wt.worker.state, 'all_sandbox_namespaces', [])),
                })

            if scan_data:
                ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                scan_file = history_dir / f"scan-{ts}.json"
                scan_file.write_text(json.dumps(scan_data, indent=2))

                # Persist to database
                try:
                    from db.database import get_db
                    from db import repository
                    db = next(get_db())
                    repository.save_scan_snapshot(db, "cluster_scan", scan_data)
                    db.close()
                except Exception:
                    pass

            self._shutdown.wait(self.SCAN_SAVE_INTERVAL)

    def stop(self):
        """Stop all workers."""
        for wt in self.workers:
            wt.stop()
        self._babylon_running = False
        self._shutdown.set()

    def wait(self):
        """Block until shutdown signal."""
        self._shutdown.wait()

    def status(self) -> List[Dict]:
        """Get current status of all workers."""
        results = []
        for wt in self.workers:
            status = {
                "cluster": wt.worker.state.name,
                "ticks": wt.tick_count,
                "errors": wt.error_count,
                "offset": wt.offset,
                "running": wt.running,
            }

            if wt.last_result:
                nodes = wt.last_result.get("nodes", {})
                pods = wt.last_result.get("pods", {})
                ns = wt.last_result.get("namespaces", {})

                status["avg_cpu"] = nodes.get("avg_cpu", 0)
                status["hot_nodes"] = nodes.get("hot_nodes", 0)
                status["node_status"] = nodes.get("status", "unknown")
                status["vms"] = pods.get("total_vms", 0)
                status["vms_per_node"] = pods.get("vms_per_node", 0)
                status["crashloops"] = pods.get("crashloops", 0)
                status["new_failures"] = len(pods.get("new_failures", []))
                status["recovered"] = len(pods.get("recovered", []))
                status["ns_scanned"] = ns.get("total_scanned", 0)
                status["ns_total"] = ns.get("total_available", 0)

            results.append(status)
        return results

    def format_dashboard(self) -> str:
        """Format a dashboard view of all workers."""
        lines = [
            f"StarGate Scheduler — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            f"{'Cluster':<14} {'Status':<10} {'Ticks':>5} {'CPU':>5} {'Hot':>4} {'VMs':>5} {'VM/N':>5} {'Crash':>5} {'New':>4} {'Rec':>4} {'NS':>8}",
            "-" * 85,
        ]

        for s in self.status():
            if s.get("errors", 0) > 0:
                status_str = "ERROR"
            elif not s.get("running"):
                status_str = "STOPPED"
            else:
                status_str = s.get("node_status", "?")

            icon = "🔴" if status_str == "critical" else "🟡" if status_str in ("warning", "ERROR") else "🟢" if status_str == "healthy" else "⚪"

            ns_str = f"{s.get('ns_scanned', 0)}/{s.get('ns_total', 0)}"

            lines.append(
                f"{icon} {s['cluster']:<12} {status_str:<10} "
                f"{s.get('ticks', 0):>5} "
                f"{s.get('avg_cpu', 0):>4.0f}% "
                f"{s.get('hot_nodes', 0):>4} "
                f"{s.get('vms', 0):>5} "
                f"{s.get('vms_per_node', 0):>5.0f} "
                f"{s.get('crashloops', 0):>5} "
                f"{s.get('new_failures', 0):>4} "
                f"{s.get('recovered', 0):>4} "
                f"{ns_str:>8}"
            )

        # Babylon control plane status
        if hasattr(self, '_babylon_result') and self._babylon_result:
            br = self._babylon_result
            if "error" not in br:
                pools = br.get("pools", {})
                prov = br.get("provisioning", {})
                summit = prov.get("summit_2026", {})
                lines.append("")
                lines.append("Babylon Control Plane:")
                lines.append(
                    f"  Pools: {pools.get('total_pools', 0)} total, "
                    f"{len(pools.get('exhausted', []))} exhausted, "
                    f"{len(pools.get('low', []))} low"
                )
                lines.append(
                    f"  Provisioning: {prov.get('total', 0)} subjects, "
                    f"{prov.get('started', 0)} started, "
                    f"{prov.get('failed', 0)} failed ({prov.get('failure_rate', 0)}%)"
                )
                if summit.get("total", 0) > 0:
                    lines.append(
                        f"  Summit 2026: {summit['total']} subjects, "
                        f"{summit['started']} started, "
                        f"{summit['failed']} failed"
                    )

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        prog="stargate-scheduler",
        description="StarGate distributed cluster scanner",
    )
    parser.add_argument("--api-url", help="StarGate API URL for persistence")
    parser.add_argument("--clusters", help="Comma-separated cluster names (default: all)")
    parser.add_argument("--tier1", type=int, default=300, help="Tier 1 interval (node metrics, default 300s)")
    parser.add_argument("--tier2", type=int, default=900, help="Tier 2 interval (pod delta, default 900s)")
    parser.add_argument("--tier3", type=int, default=3600, help="Tier 3 interval (namespace evidence, default 3600s)")
    parser.add_argument("--batch", type=int, default=5, help="Tier 3 namespace batch size (default 5)")
    parser.add_argument("--dashboard", type=int, default=60, help="Dashboard refresh interval in seconds (default 60)")
    args = parser.parse_args()

    clusters = CLUSTERS
    if args.clusters:
        requested = set(args.clusters.split(","))
        clusters = {k: v for k, v in CLUSTERS.items() if k in requested}
        if not clusters:
            print(f"No matching clusters. Available: {', '.join(CLUSTERS.keys())}", file=sys.stderr)
            return 1

    scheduler = Scheduler(
        clusters=clusters,
        api_url=args.api_url,
        tier1=args.tier1,
        tier2=args.tier2,
        tier3=args.tier3,
        tier3_batch=args.batch,
    )

    # Handle Ctrl+C
    def handle_signal(sig, frame):
        print("\nShutting down workers...")
        scheduler.stop()

    signal.signal(signal.SIGINT, handle_signal)

    print("StarGate Scheduler")
    print(f"  Clusters: {len(clusters)}")
    print(f"  Tier 1 (nodes): every {args.tier1}s")
    print(f"  Tier 2 (pods): every {args.tier2}s")
    print(f"  Tier 3 (namespaces): every {args.tier3}s, {args.batch}/batch")
    print(f"  Stagger: {Scheduler.STAGGER_SECONDS}s between clusters")
    if args.api_url:
        print(f"  Persisting to: {args.api_url}")
    print()

    available, unavailable = scheduler.start()
    print(f"  Started: {', '.join(available)}")
    if unavailable:
        print(f"  Unavailable: {', '.join(unavailable)}")
    print()

    # Dashboard loop
    try:
        while not scheduler._shutdown.is_set():
            time.sleep(args.dashboard)
            print("\033[2J\033[H")  # clear screen
            print(scheduler.format_dashboard())
            print(f"\nPress Ctrl+C to stop. Dashboard refreshes every {args.dashboard}s.")
    except KeyboardInterrupt:
        pass

    scheduler.stop()
    print("\nAll workers stopped.")

    # Final summary
    print()
    print(scheduler.format_dashboard())

    # Save final state
    history_dir = Path(__file__).parent.parent / "scan-history"
    history_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    final_state = history_dir / f"scheduler-{ts}.json"
    final_state.write_text(json.dumps(scheduler.status(), indent=2))
    print(f"\nFinal state saved to {final_state}")


if __name__ == "__main__":
    sys.exit(main() or 0)
