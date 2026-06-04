#!/usr/bin/env python3
"""Resolve summit namespace names to human-readable lab names."""
import json
from collections import defaultdict
from pathlib import Path

NS_TO_LAB = {
    "zt-ansiblebu": "Ansible Automation Platform (ZeroTouch)",
    "zt-rhelbu": "RHEL Hands-On Lab (ZeroTouch)",
    "ocp4-cluster": "OpenShift 4 Cluster Sandbox",
    "sandbox-assignment-api": "Sandbox Assignment Service",
}


def resolve_lab_name(ns):
    if not ns or ns == r"\N" or ns == "\\N" or ns == "None":
        return "Unattributed (no namespace)"
    for pattern, name in NS_TO_LAB.items():
        if pattern in ns:
            return name
    if ns.startswith("sandbox-"):
        return "Other Sandbox"
    return ns


report_path = Path(__file__).parent.parent / "receipts" / "summit-report.json"
report = json.loads(report_path.read_text())
labs = report.get("labs", {}).get("labs", [])

by_lab = defaultdict(lambda: {"total_evals": 0, "passed": 0, "failed": 0, "warned": 0, "namespaces": []})
for lab in labs:
    name = resolve_lab_name(lab["lab_code"])
    by_lab[name]["total_evals"] += lab["total_evals"]
    by_lab[name]["passed"] += lab["passed"]
    by_lab[name]["failed"] += lab["failed"]
    by_lab[name]["warned"] += lab.get("warned", 0)
    by_lab[name]["namespaces"].append(lab["lab_code"])

new_labs = []
for name, stats in sorted(by_lab.items(), key=lambda x: -x[1]["total_evals"]):
    total = stats["total_evals"]
    new_labs.append({
        "lab_name": name,
        "lab_code": name,
        "total_evals": total,
        "passed": stats["passed"],
        "failed": stats["failed"],
        "warned": stats["warned"],
        "pass_rate": round(stats["passed"] / max(total, 1) * 100, 1),
        "namespace_count": len(stats["namespaces"]),
    })

report["labs"]["labs"] = new_labs
report["labs"]["total"] = len(new_labs)
report["labs"]["top_failing"] = [l for l in new_labs if l["failed"] > 0]

report_path.write_text(json.dumps(report, indent=2))
print(f"Updated {len(new_labs)} labs:")
for l in new_labs:
    print(f"  {l['lab_name']}: {l['total_evals']} evals, {l['pass_rate']}% pass ({l['namespace_count']} ns)")
