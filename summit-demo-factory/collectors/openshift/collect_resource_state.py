"""OpenShift resource state collectors — parse oc get JSON into normalized evidence.

All collectors are read-only. No mutation. No write verbs.
Collectors work with JSON data (from oc get -o json or from fixture files).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional



@dataclass
class CollectedEvidence:
    """Normalized evidence from an OpenShift resource."""
    resource_kind: str
    resource_name: str
    namespace: str
    observed: Dict[str, Any]
    source: str = "oc"


def collect_namespace(data: Dict) -> CollectedEvidence:
    phase = data.get("status", {}).get("phase", "Unknown")
    name = data.get("metadata", {}).get("name", "unknown")
    return CollectedEvidence(
        resource_kind="Namespace",
        resource_name=name,
        namespace=name,
        observed={
            "namespace_exists": phase == "Active",
            "phase": phase,
        },
    )


def collect_deployment(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})
    status = data.get("status", {})

    desired = spec.get("replicas", 0)
    ready = status.get("readyReplicas", 0) or 0
    available = status.get("availableReplicas", 0) or 0
    unavailable = status.get("unavailableReplicas", 0) or 0

    conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}

    return CollectedEvidence(
        resource_kind="Deployment",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "deployment_exists": True,
            "desired_replicas": desired,
            "ready_replicas": ready,
            "available_replicas": available,
            "unavailable_replicas": unavailable,
            "desired_replicas_ready": ready >= desired and desired > 0,
            "available": conditions.get("Available") == "True",
        },
    )


def collect_pods(data: Dict) -> CollectedEvidence:
    items = data.get("items", [])
    if not items:
        namespace = "unknown"
    else:
        namespace = items[0].get("metadata", {}).get("namespace", "unknown")

    total = len(items)
    ready_count = 0
    crashloop_count = 0
    pod_details: List[Dict] = []

    for pod in items:
        pod_meta = pod.get("metadata", {})
        pod_status = pod.get("status", {})
        phase = pod_status.get("phase", "Unknown")

        container_statuses = pod_status.get("containerStatuses", [])
        pod_ready = all(cs.get("ready", False) for cs in container_statuses) if container_statuses else False
        total_restarts = sum(cs.get("restartCount", 0) for cs in container_statuses)

        is_crashloop = False
        for cs in container_statuses:
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting.get("reason") == "CrashLoopBackOff":
                is_crashloop = True

        if pod_ready:
            ready_count += 1
        if is_crashloop:
            crashloop_count += 1

        pod_details.append({
            "name": pod_meta.get("name"),
            "phase": phase,
            "ready": pod_ready,
            "restarts": total_restarts,
            "crashloop": is_crashloop,
        })

    return CollectedEvidence(
        resource_kind="PodList",
        resource_name="pods",
        namespace=namespace,
        observed={
            "total_pods": total,
            "ready_pods": ready_count,
            "crashloop_pods": crashloop_count,
            "no_crashloop_pods": crashloop_count == 0,
            "all_pods_ready": ready_count == total and total > 0,
            "pod_details": pod_details,
        },
    )


def collect_service(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})
    return CollectedEvidence(
        resource_kind="Service",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "service_exists": True,
            "selector": spec.get("selector", {}),
            "ports": spec.get("ports", []),
            "type": spec.get("type", "ClusterIP"),
        },
    )


def collect_endpoints(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    subsets = data.get("subsets", [])

    ready_count = 0
    not_ready_count = 0
    for subset in subsets:
        ready_count += len(subset.get("addresses", []))
        not_ready_count += len(subset.get("notReadyAddresses", []))

    return CollectedEvidence(
        resource_kind="Endpoints",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "ready_endpoint_count": ready_count,
            "not_ready_endpoint_count": not_ready_count,
            "service_has_ready_endpoints": ready_count > 0,
        },
    )


def collect_route(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})
    status = data.get("status", {})

    host = spec.get("host", "")
    ingress_list = status.get("ingress", [])
    admitted = False
    for ingress in ingress_list:
        for cond in ingress.get("conditions", []):
            if cond.get("type") == "Admitted" and cond.get("status") == "True":
                admitted = True

    return CollectedEvidence(
        resource_kind="Route",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "route_exists": True,
            "host": host,
            "admitted": admitted,
            "tls_termination": spec.get("tls", {}).get("termination"),
        },
    )


def collect_events(data: Dict) -> CollectedEvidence:
    items = data.get("items", [])
    if not items:
        namespace = "unknown"
    else:
        namespace = items[0].get("metadata", {}).get("namespace", "unknown")

    warnings = []
    normals = []
    for event in items:
        entry = {
            "reason": event.get("reason"),
            "message": event.get("message"),
            "type": event.get("type"),
            "count": event.get("count", 1),
            "involved_object": event.get("involvedObject", {}).get("name"),
            "last_timestamp": event.get("lastTimestamp"),
        }
        if event.get("type") == "Warning":
            warnings.append(entry)
        else:
            normals.append(entry)

    return CollectedEvidence(
        resource_kind="EventList",
        resource_name="events",
        namespace=namespace,
        observed={
            "total_events": len(items),
            "warning_events": len(warnings),
            "normal_events": len(normals),
            "warnings": warnings,
            "has_warnings": len(warnings) > 0,
        },
    )


# --- OpenShift Virtualization collectors ---

def collect_datavolume(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    status = data.get("status", {})
    phase = status.get("phase", "Unknown")
    progress = status.get("progress", "0%")

    conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}

    return CollectedEvidence(
        resource_kind="DataVolume",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "datavolume_exists": True,
            "datavolume_phase": phase,
            "datavolume_succeeded": phase == "Succeeded",
            "datavolume_progress": progress,
            "pvc_bound": conditions.get("Bound") == "True",
        },
    )


def collect_pvc(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    status = data.get("status", {})
    phase = status.get("phase", "Unknown")

    return CollectedEvidence(
        resource_kind="PersistentVolumeClaim",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "pvc_exists": True,
            "pvc_phase": phase,
            "pvc_bound": phase == "Bound",
            "pvc_capacity": status.get("capacity", {}).get("storage"),
        },
    )


def collect_vm(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    status = data.get("status", {})

    ready = status.get("ready", False)
    printable = status.get("printableStatus", "Unknown")
    conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}

    return CollectedEvidence(
        resource_kind="VirtualMachine",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "vm_exists": True,
            "vm_ready": ready,
            "vm_printable_status": printable,
            "vm_condition_ready": conditions.get("Ready") == "True",
        },
    )


def collect_vmi(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    status = data.get("status", {})
    phase = status.get("phase", "Unknown")

    conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}

    guest_os = status.get("guestOSInfo", {})
    interfaces = status.get("interfaces", [])
    ip_address = interfaces[0].get("ipAddress") if interfaces else None

    return CollectedEvidence(
        resource_kind="VirtualMachineInstance",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "vmi_exists": True,
            "vmi_phase": phase,
            "vmi_running": phase == "Running",
            "vmi_ready": conditions.get("Ready") == "True",
            "guest_agent_connected": conditions.get("AgentConnected") == "True",
            "guest_os_name": guest_os.get("name"),
            "guest_os_ready": bool(guest_os.get("name")),
            "ip_address": ip_address,
        },
    )


# --- KServe / OpenShift AI collectors ---

def collect_inferenceservice(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    status = data.get("status", {})

    conditions = {c["type"]: c for c in status.get("conditions", [])}
    ready_cond = conditions.get("Ready", {})
    predictor_cond = conditions.get("PredictorReady", {})

    model_status = status.get("modelStatus", {})
    states = model_status.get("states", {})
    failure_info = model_status.get("lastFailureInfo")

    return CollectedEvidence(
        resource_kind="InferenceService",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "inferenceservice_exists": True,
            "inferenceservice_ready": ready_cond.get("status") == "True",
            "predictor_ready": predictor_cond.get("status") == "True",
            "model_state": states.get("activeModelState"),
            "model_loaded": states.get("activeModelState") == "Loaded",
            "inference_url": status.get("url"),
            "failure_reason": failure_info.get("reason") if failure_info else None,
            "failure_message": failure_info.get("message") if failure_info else None,
        },
    )


def collect_servingruntime(data: Dict) -> CollectedEvidence:
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})

    formats = [f.get("name") for f in spec.get("supportedModelFormats", [])]

    return CollectedEvidence(
        resource_kind="ServingRuntime",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "servingruntime_exists": True,
            "supported_formats": formats,
        },
    )


# --- File-based collection (fixtures or saved oc output) ---

def collect_from_file(path: Path) -> CollectedEvidence:
    data = json.loads(path.read_text())
    kind = data.get("kind", "")

    collectors = {
        "Namespace": collect_namespace,
        "Deployment": collect_deployment,
        "PodList": collect_pods,
        "Service": collect_service,
        "Endpoints": collect_endpoints,
        "Route": collect_route,
        "EventList": collect_events,
        "DataVolume": collect_datavolume,
        "PersistentVolumeClaim": collect_pvc,
        "VirtualMachine": collect_vm,
        "VirtualMachineInstance": collect_vmi,
        "InferenceService": collect_inferenceservice,
        "ServingRuntime": collect_servingruntime,
    }
    collector = collectors.get(kind)
    if not collector:
        collector = _get_extension_collector(kind)
    if not collector:
        raise ValueError(f"Unsupported resource kind: {kind}")

    result = collect_from_data(data)
    result.source = f"file:{path.name}"
    return result


def collect_from_data(data: Dict) -> CollectedEvidence:
    kind = data.get("kind", "")
    collectors = {
        "Namespace": collect_namespace,
        "Deployment": collect_deployment,
        "PodList": collect_pods,
        "Service": collect_service,
        "Endpoints": collect_endpoints,
        "Route": collect_route,
        "EventList": collect_events,
        "DataVolume": collect_datavolume,
        "PersistentVolumeClaim": collect_pvc,
        "VirtualMachine": collect_vm,
        "VirtualMachineInstance": collect_vmi,
        "InferenceService": collect_inferenceservice,
        "ServingRuntime": collect_servingruntime,
    }
    collector = collectors.get(kind)
    if not collector:
        collector = _get_extension_collector(kind)
    if not collector:
        raise ValueError(f"Unsupported resource kind: {kind}")
    return collector(data)


def _get_extension_collector(kind: str):
    """Lazy-load collectors from extension modules to avoid circular imports."""
    if kind == "AnarchySubject":
        from collectors.babylon.collect_anarchy_state import collect_anarchysubject
        return collect_anarchysubject
    if kind == "ShowroomHealth":
        from collectors.showroom.collect_showroom_health import collect_showroom_health
        return collect_showroom_health
    if kind == "ClusterHealth":
        from collectors.cluster_scheduler.collect_cluster_health import collect_cluster_health
        return collect_cluster_health
    return None


def collect_namespace_state(fixture_dir: Path) -> List[CollectedEvidence]:
    """Collect all resource state from a directory of oc JSON files."""
    results = []
    for path in sorted(fixture_dir.glob("*.json")):
        try:
            results.append(collect_from_file(path))
        except (ValueError, json.JSONDecodeError):
            continue
    return results
