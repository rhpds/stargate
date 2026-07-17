"""AgnosticV constraint loader — extract declared specs from common.yaml.

Reads a lab's common.yaml and extracts:
  - workloads (ordered list of Ansible collections to deploy)
  - operator channels and pinned versions
  - resource constraints (CPU, memory, instance counts)
  - timeout values
  - showroom configuration
  - deployer metadata (scm_url, scm_ref, execution_environment)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class _VaultLoader(yaml.SafeLoader):
    pass

_VaultLoader.add_constructor("!vault", lambda loader, node: loader.construct_scalar(node))


def load_lab_constraints(common_yaml_path: Path) -> Dict[str, Any]:
    """Load and parse a lab's common.yaml into structured constraints."""
    text = common_yaml_path.read_text()

    # Strip #include directives before parsing (they're not valid YAML)
    lines = [l for l in text.split("\n") if not l.strip().startswith("#include")]
    data = yaml.load("\n".join(lines), Loader=_VaultLoader)

    if not data:
        return {"error": "empty or unparseable YAML"}

    constraints: Dict[str, Any] = {}

    # Workloads
    workloads = data.get("workloads", [])
    if workloads:
        constraints["workloads"] = workloads
        constraints["workload_count"] = len(workloads)

    # Requirements (collection versions)
    req = data.get("requirements_content", {})
    if req:
        collections = req.get("collections", [])
        pinned = []
        for c in collections:
            name = c.get("name", "")
            version = c.get("version", "")
            ctype = c.get("type", "galaxy")
            if name and version:
                pinned.append({
                    "name": name,
                    "version": str(version),
                    "type": ctype,
                })
        constraints["collections"] = pinned

    # OCP version
    ocp_ver = data.get("ocp4_installer_version")
    if ocp_ver:
        constraints["ocp_version"] = str(ocp_ver)

    # Resource constraints
    worker_count = data.get("worker_instance_count")
    if worker_count:
        constraints["worker_instance_count"] = str(worker_count)

    for key in ("ai_workers_cores", "ai_workers_memory"):
        val = data.get(key)
        if val:
            constraints[key] = str(val)

    # Cloud provider
    cloud = data.get("cloud_provider")
    if cloud:
        constraints["cloud_provider"] = cloud

    # Config type
    config = data.get("config")
    if config:
        constraints["config"] = config

    # Showroom
    showroom_repo = data.get("ocp4_workload_showroom_content_git_repo")
    showroom_ref = data.get("ocp4_workload_showroom_content_git_repo_ref")
    if showroom_repo:
        constraints["showroom_repo"] = showroom_repo
    if showroom_ref:
        constraints["showroom_ref"] = str(showroom_ref)

    # __meta__ section
    meta = data.get("__meta__", {})
    if meta:
        # Asset UUID
        uuid = meta.get("asset_uuid")
        if uuid:
            constraints["asset_uuid"] = str(uuid)

        # Deployer
        deployer = meta.get("deployer", {})
        if deployer:
            constraints["deployer_scm_url"] = deployer.get("scm_url", "")
            constraints["deployer_scm_ref"] = deployer.get("scm_ref", "")
            ee = deployer.get("execution_environment", {})
            if ee:
                constraints["execution_environment_image"] = ee.get("image", "")

        # Catalog display name
        catalog = meta.get("catalog", {})
        if catalog:
            constraints["display_name"] = catalog.get("display_name", "")
            constraints["keywords"] = catalog.get("keywords", [])

        # Timeout
        tower = meta.get("tower", {})
        if tower:
            constraints["timeout_seconds"] = tower.get("timeout")

        # Components
        components = meta.get("components", [])
        if components:
            constraints["components"] = [
                {
                    "name": c.get("name", ""),
                    "display_name": c.get("display_name", ""),
                    "item": c.get("item", ""),
                }
                for c in components
            ]

    # Operator channels (scan for known patterns)
    operator_channels = {}
    for key, val in data.items():
        if "_channel" in key and isinstance(val, str) and not val.startswith("{{"):
            operator_name = key.replace("_channel", "").replace("ocp4_workload_", "")
            operator_channels[operator_name] = val
    if operator_channels:
        constraints["operator_channels"] = operator_channels

    return constraints


def load_all_constraints(agnosticv_dir: Path) -> Dict[str, Dict]:
    """Load constraints for all labs across all AgnosticV directories."""
    labs = {}

    SCAN_DIRS = [
        "summit-2026",
        "zt_rhel",
        "ansiblebu",
        "agd_v2",
        "ai-quickstarts",
        "openshift_cnv",
        "published",
        "rhdp",
        "sandboxes-gpte",
    ]

    for dir_name in SCAN_DIRS:
        scan_dir = agnosticv_dir / dir_name
        if not scan_dir.is_dir():
            continue
        for lab_dir in sorted(scan_dir.iterdir()):
            if not lab_dir.is_dir():
                continue
            common = lab_dir / "common.yaml"
            if common.exists():
                try:
                    labs[lab_dir.name] = load_lab_constraints(common)
                except Exception:
                    pass

    return labs
