"""AAP2 failure ingestion — parse, classify, and store provisioning failures.

Takes AAP job failure data (from Grafana or AAP API) and converts it into
StarGate's failure classification format. Builds the corpus of known failure
patterns for LLM training and remediation lookup.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.aap_ingestion")

AAP_FAILURE_CLASSES = {
    "vm_provisioning_timeout": {
        "pattern": r"(Wait till VM is running|VMI does not exist|printableStatus.*Provisioning|attempts.*30)",
        "description": "VirtualMachine stuck in Provisioning — VMI never created or started",
        "severity": "high",
        "remediation": [
            "Check DataVolume status in the sandbox namespace",
            "Verify storage class has available capacity (ocs-storagecluster-ceph-rbd)",
            "Check node scheduling constraints and resource availability",
            "Verify Assisted Installer pods are running",
            "oc get datavolume -n {namespace}",
            "oc get vm -n {namespace} -o yaml | grep -A5 status",
        ],
        "team": "platform-ops",
    },
    "ec2_capacity_exhausted": {
        "pattern": r"(InsufficientInstanceCapacity|Unable to start instances)",
        "description": "AWS EC2 capacity exhausted — cannot start instances in region",
        "severity": "high",
        "remediation": [
            "Retry in a different availability zone",
            "Use a different instance type",
            "Contact AWS support for capacity increase",
            "Check AWS Service Health Dashboard for region issues",
        ],
        "team": "infra",
    },
    "ssh_connection_failed": {
        "pattern": r"(Shared connection to .* closed|ssh.*connection refused|Connection reset by peer)",
        "description": "SSH connection to bastion or target host failed",
        "severity": "medium",
        "remediation": [
            "Verify bastion host is running and accessible",
            "Check SSH key configuration and permissions",
            "Verify network connectivity to target host",
            "Retry provisioning — may be transient network issue",
        ],
        "team": "platform-ops",
    },
    "service_unavailable": {
        "pattern": r"(503.*Service Unavailable|Status code was 503|HTTP Error 503)",
        "description": "Application returned 503 — service not ready during provisioning",
        "severity": "medium",
        "remediation": [
            "Wait for application pods to become ready",
            "Check pod readiness probes and startup time",
            "Verify route and service configuration",
            "oc get pods -n {namespace} | grep -v Running",
        ],
        "team": "lab-developer",
    },
    "vault_decryption_failed": {
        "pattern": r"(Decryption failed|no vault secrets were found|AnsibleVaultError)",
        "description": "Ansible Vault decryption failed — missing or wrong vault password",
        "severity": "critical",
        "remediation": [
            "Verify vault password file is accessible to the execution environment",
            "Check that the correct vault ID is configured",
            "Verify secret injection from external secrets manager",
            "Contact platform-ops to check vault configuration",
        ],
        "team": "platform-ops",
    },
    "eda_config_error": {
        "pattern": r"(rulebook_id.*required|Failed to create.*rulebook)",
        "description": "Event-Driven Ansible configuration error — missing required fields",
        "severity": "medium",
        "remediation": [
            "Update the ansible playbook to include the required rulebook_id field",
            "Check EDA controller API for required request fields",
            "Verify rulebook exists in the EDA controller",
        ],
        "team": "lab-developer",
    },
    "api_resolution_error": {
        "pattern": r"(error resolving resource|Internal error occurred.*resolving)",
        "description": "Kubernetes API internal error — CRD or resource resolution failed",
        "severity": "high",
        "remediation": [
            "Verify the CRD is installed on the target cluster",
            "Check API server health and connectivity",
            "oc get crd | grep <resource>",
            "Retry provisioning — API server may recover",
        ],
        "team": "platform-ops",
    },
    "assisted_installer_failed": {
        "pattern": r"(Assisted Installer|installer Pods in Error|Start cluster installation.*Timeout)",
        "description": "OpenShift Assisted Installer failed — cluster installation did not complete",
        "severity": "high",
        "remediation": [
            "Check assisted-installer pod logs",
            "Verify host discovery and validation passed",
            "Check network connectivity between hosts",
            "oc logs -n assisted-installer -l app=assisted-installer",
        ],
        "team": "platform-ops",
    },
    "job_cancelled": {
        "pattern": r"(canceled due to receiving a shutdown signal|Task was canceled)",
        "description": "Job was cancelled due to platform shutdown — not a real failure",
        "severity": "low",
        "remediation": [
            "No action needed — job was cancelled by platform shutdown",
            "Retry the job after platform restart",
        ],
        "team": "platform-ops",
    },
    "vm_creation_failed": {
        "pattern": r"(Create VMs.*FAILED|virt_roadshow_vmware)",
        "description": "Virtual machine creation failed in VMware/CNV workload",
        "severity": "high",
        "remediation": [
            "Check VMware/CNV resource availability",
            "Verify storage and network configuration for VMs",
            "Check workload role configuration",
        ],
        "team": "lab-developer",
    },
    "connection_refused": {
        "pattern": r"(Connection refused|Failed to establish a new connection|Max retries exceeded)",
        "description": "Connection to cluster API or service refused — cluster may be down",
        "severity": "high",
        "remediation": [
            "Verify the target cluster is running and API is accessible",
            "Check certificate validity and renewal status",
            "oc get nodes on the target cluster",
            "Check cluster-bot or monitoring for cluster health",
        ],
        "team": "platform-ops",
    },
}


def parse_aap_failure(raw: Dict) -> Dict:
    """Parse a raw AAP2 failure record into StarGate's classified format."""
    error_msg = raw.get("error_msg", "")
    task = raw.get("task", "")
    role = raw.get("role", "")
    combined = f"{error_msg} {task} {role}"

    failure_class = "unclassified"
    matched_data = {}

    for cls_name, cls_data in AAP_FAILURE_CLASSES.items():
        if re.search(cls_data["pattern"], combined, re.IGNORECASE):
            failure_class = cls_name
            matched_data = cls_data
            break

    return {
        "failure_class": failure_class,
        "guid": raw.get("guid", ""),
        "job_title": raw.get("job_title", ""),
        "job_type": raw.get("type", ""),
        "error_msg": error_msg[:500],
        "task": task,
        "play": raw.get("play", ""),
        "role": role,
        "cluster": raw.get("cluster", ""),
        "status": raw.get("status", ""),
        "severity": matched_data.get("severity", "medium"),
        "description": matched_data.get("description", "Unclassified AAP failure"),
        "remediation": matched_data.get("remediation", []),
        "team": matched_data.get("team", "platform-ops"),
        "source": "aap2_grafana",
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }


def batch_ingest(failures: List[Dict], db=None) -> Dict:
    """Batch ingest and classify multiple AAP failures."""
    results = []
    classified = 0
    unclassified = 0

    for raw in failures:
        parsed = parse_aap_failure(raw)
        results.append(parsed)
        if parsed["failure_class"] != "unclassified":
            classified += 1
        else:
            unclassified += 1

    if db:
        try:
            from db import repository
            for parsed in results:
                repository.create_evaluation(
                    db,
                    run_id=f"aap-{parsed['guid']}",
                    stage_id="aap-provisioning",
                    outcome="fail",
                    failure_class=parsed["failure_class"],
                    message=parsed["error_msg"][:200],
                    criteria_results=[],
                    lab_code=parsed["job_title"],
                    cluster_name=parsed["cluster"],
                )
        except Exception as e:
            logger.warning("Failed to persist AAP failures to DB: %s", e)

    return {
        "total": len(failures),
        "classified": classified,
        "unclassified": unclassified,
        "by_class": _count_by_class(results),
        "results": results,
    }


def _count_by_class(results: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in results:
        fc = r["failure_class"]
        counts[fc] = counts.get(fc, 0) + 1
    return counts
