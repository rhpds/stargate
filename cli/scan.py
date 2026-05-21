"""StarGate cluster scanner — collect evidence from live clusters on a schedule.

Usage:
  # Single scan of all configured clusters
  python3 -m cli.scan

  # Continuous scan every 5 minutes
  python3 -m cli.scan --interval 300

  # Single cluster
  python3 -m cli.scan --cluster ocpv06

  # With Slack notification on failures
  python3 -m cli.scan --slack-webhook https://hooks.slack.com/services/xxx
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

SECRETS_DIR = Path(__file__).parent.parent / "secrets"

_DEFAULT_CLUSTERS = {
    "ocpv05": "kubeconfig-ocpv05",
    "ocpv06": "kubeconfig-cnv",
    "ocpv07": "kubeconfig-ocpv07",
    "ocpv08": "kubeconfig-ocpv08",
    "ocpv09": "kubeconfig-ocpv09",
    "ocpv-infra01": "kubeconfig-infra01",
    "ocpv-infra02": "kubeconfig-infra02",
    "ocp-us-east-1": "kubeconfig",
}


def load_clusters() -> Dict[str, str]:
    """Load cluster → kubeconfig mapping from env vars or default.

    Priority:
      1. STARGATE_CLUSTERS env var (JSON dict or comma-separated names)
      2. STARGATE_CLUSTERS_FILE env var (path to YAML file)
      3. Built-in default cluster list
    """
    env_clusters = os.environ.get("STARGATE_CLUSTERS")
    if env_clusters:
        try:
            parsed = json.loads(env_clusters)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        names = [n.strip() for n in env_clusters.split(",") if n.strip()]
        if names:
            return {name: f"kubeconfig-{name}" for name in names}

    env_file = os.environ.get("STARGATE_CLUSTERS_FILE")
    if env_file:
        import yaml
        with open(env_file) as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data

    return dict(_DEFAULT_CLUSTERS)


CLUSTERS = load_clusters()


def scan_cluster(name: str, kubeconfig: str) -> Optional[Dict]:
    """Scan a single cluster and return health data."""
    kc = str(SECRETS_DIR / kubeconfig)
    if not os.path.exists(kc):
        return None

    env = {**os.environ, "KUBECONFIG": kc}

    try:
        user = subprocess.run(
            ["oc", "whoami"], capture_output=True, text=True, timeout=10, env=env
        ).stdout.strip()
        if not user:
            return {"cluster": name, "error": "token_expired"}
    except Exception:
        return {"cluster": name, "error": "unreachable"}

    result = {"cluster": name, "timestamp": datetime.now(timezone.utc).isoformat()}

    # Node health
    try:
        nodes_out = subprocess.run(
            ["oc", "adm", "top", "nodes", "--no-headers"],
            capture_output=True, text=True, timeout=15, env=env
        ).stdout
        nodes = []
        hot = 0
        total_cpu_pct = 0
        node_count = 0
        for line in nodes_out.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                node_name = parts[0]
                cpu_pct = int(parts[2].replace("%", ""))
                mem_pct = int(parts[4].replace("%", ""))
                nodes.append({"name": node_name, "cpu_pct": cpu_pct, "mem_pct": mem_pct})
                if "ceph" not in node_name and "cp" not in node_name.split("-")[-1]:
                    total_cpu_pct += cpu_pct
                    node_count += 1
                    if cpu_pct > 80:
                        hot += 1

        result["nodes"] = len(nodes)
        result["compute_nodes"] = node_count
        result["avg_cpu_pct"] = round(total_cpu_pct / node_count, 1) if node_count > 0 else 0
        result["hot_nodes"] = hot
    except Exception as e:
        result["node_error"] = str(e)

    # Pod health
    try:
        pods_out = subprocess.run(
            ["oc", "get", "pods", "-A", "--no-headers"],
            capture_output=True, text=True, timeout=30, env=env
        ).stdout

        sandbox_active = set()
        sandbox_failing = set()
        sandbox_crashloop = 0
        total_vms = 0
        ocp4_labs = set()

        for line in pods_out.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            ns, pod, ready, status = parts[0], parts[1], parts[2], parts[3]

            if ns.startswith("sandbox-"):
                if status == "Running":
                    sandbox_active.add(ns)
                elif status not in ("Completed", "Succeeded", "Terminating"):
                    sandbox_failing.add(ns)
                    if "CrashLoopBackOff" in status:
                        sandbox_crashloop += 1

                if "virt-launcher" in pod and status == "Running":
                    total_vms += 1

                if "ocp4-cluster" in ns and status == "Running":
                    ocp4_labs.add(ns)

        result["sandbox_active"] = len(sandbox_active)
        result["sandbox_failing"] = len(sandbox_failing)
        result["sandbox_crashloop"] = sandbox_crashloop
        result["total_vms"] = total_vms
        result["ocp4_cluster_labs"] = len(ocp4_labs)
        if node_count > 0:
            result["vms_per_node"] = round(total_vms / node_count, 1)

        health_rate = 0
        if sandbox_active:
            health_rate = round((len(sandbox_active) - len(sandbox_failing)) / len(sandbox_active) * 100, 1)
        result["health_rate"] = health_rate
    except Exception as e:
        result["pod_error"] = str(e)

    # DNS warnings
    try:
        dns_out = subprocess.run(
            ["oc", "get", "events", "-n", "openshift-dns",
             "--field-selector", "type=Warning", "--no-headers"],
            capture_output=True, text=True, timeout=10, env=env
        ).stdout
        result["dns_warnings"] = len([l for l in dns_out.strip().split("\n") if l])
    except Exception:
        result["dns_warnings"] = -1

    # Classify
    result["status"] = "healthy"
    issues = []

    if result.get("avg_cpu_pct", 0) > 80:
        result["status"] = "critical"
        issues.append(f"avg CPU {result['avg_cpu_pct']}%")
    elif result.get("avg_cpu_pct", 0) > 70:
        result["status"] = "warning"
        issues.append(f"avg CPU {result['avg_cpu_pct']}%")

    if result.get("hot_nodes", 0) > 0:
        if result["status"] == "healthy":
            result["status"] = "warning"
        issues.append(f"{result['hot_nodes']} nodes >80% CPU")

    if result.get("dns_warnings", 0) > 0:
        result["status"] = "critical"
        issues.append(f"{result['dns_warnings']} DNS probe failures")

    if result.get("vms_per_node", 0) > 50:
        if result["status"] != "critical":
            result["status"] = "warning"
        issues.append(f"{result['vms_per_node']} VMs/node (threshold: 30)")

    if result.get("sandbox_crashloop", 0) > 0:
        issues.append(f"{result['sandbox_crashloop']} showroom CrashLoopBackOff")

    result["issues"] = issues

    return result


def format_text(results: List[Dict]) -> str:
    """Format scan results as text."""
    lines = [
        f"StarGate Scan — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"{'Cluster':<14} {'Status':<10} {'Labs':>5} {'VMs':>5} {'VM/Node':>8} {'CPU':>6} {'Hot':>4} {'DNS':>4} {'Crash':>6} Issues",
        "-" * 100,
    ]

    for r in results:
        if "error" in r:
            lines.append(f"{r['cluster']:<14} {'ERROR':<10} {r['error']}")
            continue

        lines.append(
            f"{r['cluster']:<14} {r['status']:<10} "
            f"{r.get('sandbox_active', 0):>5} "
            f"{r.get('total_vms', 0):>5} "
            f"{r.get('vms_per_node', 0):>8.1f} "
            f"{r.get('avg_cpu_pct', 0):>5.0f}% "
            f"{r.get('hot_nodes', 0):>4} "
            f"{r.get('dns_warnings', 0):>4} "
            f"{r.get('sandbox_crashloop', 0):>6} "
            f"{', '.join(r.get('issues', []))}"
        )

    return "\n".join(lines)


def format_slack(results: List[Dict]) -> Dict:
    """Format scan results as Slack blocks."""
    critical = [r for r in results if r.get("status") == "critical"]
    warning = [r for r in results if r.get("status") == "warning"]

    if not critical and not warning:
        return None

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{'🔴' if critical else '🟡'} StarGate Platform Scan"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Critical:* {len(critical)}"},
                {"type": "mrkdwn", "text": f"*Warning:* {len(warning)}"},
            ],
        },
    ]

    for r in critical + warning:
        emoji = "🔴" if r["status"] == "critical" else "🟡"
        issues_text = "\n".join(f"  • {i}" for i in r.get("issues", []))
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji} *{r['cluster']}* — {r.get('avg_cpu_pct', 0):.0f}% CPU, "
                    f"{r.get('total_vms', 0)} VMs, "
                    f"{r.get('vms_per_node', 0):.0f} VMs/node\n{issues_text}"
                ),
            },
        })

    return {"blocks": blocks}


def send_slack(webhook_url: str, payload: Dict) -> None:
    """POST to Slack webhook."""
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  Slack error: {e}", file=sys.stderr)


def collect_namespace_evidence(cluster: str, kubeconfig: str, namespace: str, api_url: str) -> Optional[Dict]:
    """Collect evidence from a namespace and persist through the API."""
    import tempfile
    import shutil

    kc = str(SECRETS_DIR / kubeconfig)
    env = {**os.environ, "KUBECONFIG": kc}
    tmpdir = tempfile.mkdtemp(prefix=f"sg-{cluster}-")

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
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
            if r.returncode == 0 and r.stdout.strip():
                with open(f"{tmpdir}/{res}.json", "w") as f:
                    f.write(r.stdout)
        except Exception:
            pass

    if "ocp4-cluster" in namespace:
        demo_id = "ocp4-cluster"
        stages = "namespace-ready,route-ready,storage-clone-ready,vm-runtime-ready"
    elif "zt-ansiblebu" in namespace:
        demo_id = "zt-ansible"
        stages = "namespace-ready,deployment-ready,route-ready,storage-clone-ready,vm-runtime-ready"
    else:
        demo_id = "zt-rhel"
        stages = "namespace-ready,deployment-ready,route-ready,storage-clone-ready,vm-runtime-ready"

    r = subprocess.run(
        [sys.executable, "-m", "cli.stargate", "collect-dir", tmpdir,
         "--stages", stages,
         "--api-url", api_url,
         "--demo-id", demo_id,
         "--lab-code", namespace,
         "--cluster-name", cluster,
         "--format", "json"],
        capture_output=True, text=True,
    )

    shutil.rmtree(tmpdir, ignore_errors=True)

    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def run_scan(
    clusters: Dict[str, str],
    slack_webhook: Optional[str] = None,
    api_url: Optional[str] = None,
    namespaces_per_cluster: int = 0,
) -> List[Dict]:
    """Run a scan across all clusters."""
    results = []
    for name, kc in clusters.items():
        result = scan_cluster(name, kc)
        if result:
            results.append(result)

    # Print cluster health
    print(format_text(results))
    print()

    # Namespace evidence collection
    if api_url and namespaces_per_cluster > 0:
        import random

        print(f"=== Collecting namespace evidence (up to {namespaces_per_cluster} per cluster) ===")
        print(f"    Persisting to {api_url}")
        print()

        total_persisted = 0
        total_passed = 0
        total_failed = 0
        failure_classes: Dict[str, int] = {}

        for cluster_result in results:
            name = cluster_result.get("cluster")
            if "error" in cluster_result or not name or name not in clusters:
                continue

            kc_file = clusters[name]
            kc = str(SECRETS_DIR / kc_file)
            if not os.path.exists(kc):
                continue

            env = {**os.environ, "KUBECONFIG": kc}

            # Get active sandbox namespaces
            try:
                r = subprocess.run(
                    ["oc", "get", "pods", "-A", "--no-headers"],
                    capture_output=True, text=True, timeout=30, env=env,
                )
                ns_set = set()
                for line in r.stdout.split("\n"):
                    parts = line.split()
                    if len(parts) >= 4 and parts[0].startswith("sandbox-") and parts[3] == "Running":
                        ns_set.add(parts[0])
            except Exception:
                continue

            ns_list = sorted(ns_set)
            sample = random.sample(ns_list, min(namespaces_per_cluster, len(ns_list)))

            cluster_passed = 0
            cluster_failed = 0

            for ns in sample:
                data = collect_namespace_evidence(name, kc_file, ns, api_url)
                if data:
                    for r_item in data.get("results", []):
                        if r_item["outcome"] == "pass":
                            cluster_passed += 1
                            total_passed += 1
                        elif r_item["outcome"] == "fail":
                            cluster_failed += 1
                            total_failed += 1
                            fc = r_item.get("failure_class", "unclassified")
                            failure_classes[fc] = failure_classes.get(fc, 0) + 1
                    total_persisted += 1

            print(f"  {name}: {len(sample)} namespaces → {cluster_passed} stages passed, {cluster_failed} failed")

        print()
        print(f"  Total: {total_persisted} namespaces persisted, {total_passed} passed, {total_failed} failed")
        if failure_classes:
            print(f"  Failure classes:")
            for fc, count in sorted(failure_classes.items(), key=lambda x: -x[1]):
                print(f"    {fc}: {count}")
        print()

    # Slack notification if issues found
    if slack_webhook:
        payload = format_slack(results)
        if payload:
            send_slack(slack_webhook, payload)
            print("  Slack notification sent.")

    # Save to scan history
    history_dir = Path(__file__).parent.parent / "scan-history"
    history_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    history_file = history_dir / f"scan-{ts}.json"
    history_file.write_text(json.dumps(results, indent=2))

    return results


def main():
    parser = argparse.ArgumentParser(
        prog="stargate-scan",
        description="StarGate continuous cluster scanner",
    )
    parser.add_argument("--cluster", help="Scan a single cluster")
    parser.add_argument("--interval", type=int, help="Repeat scan every N seconds")
    parser.add_argument("--slack-webhook", help="Slack webhook URL for alerts")
    parser.add_argument("--api-url", help="StarGate API URL for evidence persistence (e.g. http://localhost:8090)")
    parser.add_argument("--namespaces", type=int, default=0,
                        help="Number of namespaces to scan per cluster (0 = cluster health only)")
    args = parser.parse_args()

    clusters = CLUSTERS
    if args.cluster:
        if args.cluster not in CLUSTERS:
            print(f"Unknown cluster: {args.cluster}", file=sys.stderr)
            print(f"Available: {', '.join(CLUSTERS.keys())}", file=sys.stderr)
            return 1
        clusters = {args.cluster: CLUSTERS[args.cluster]}

    if args.interval:
        print(f"Starting continuous scan every {args.interval}s...")
        print(f"Clusters: {', '.join(clusters.keys())}")
        if args.api_url:
            print(f"Persisting to: {args.api_url}")
            print(f"Namespaces per cluster: {args.namespaces}")
        print()
        while True:
            run_scan(clusters, args.slack_webhook, args.api_url, args.namespaces)
            print(f"\nNext scan in {args.interval}s...\n")
            time.sleep(args.interval)
    else:
        results = run_scan(clusters, args.slack_webhook, args.api_url, args.namespaces)
        has_critical = any(r.get("status") == "critical" for r in results)
        return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
