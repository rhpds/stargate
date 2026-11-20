"""Normalize collected OpenShift resource state into rubric-evaluable evidence.

Takes CollectedEvidence from multiple resources and merges into a flat
evidence dict that the rubric evaluator can evaluate per stage.
"""

from __future__ import annotations

from typing import Dict, List, Any

from collectors.openshift.collect_resource_state import CollectedEvidence


def normalize_for_namespace_ready(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {"namespace_exists": False}
    for ev in evidence_list:
        if ev.resource_kind == "Namespace":
            result["namespace_exists"] = ev.observed.get("namespace_exists", False)
    return result


def normalize_for_deployment_ready(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "namespace_exists": False,
        "deployment_exists": False,
        "desired_replicas_ready": False,
        "no_crashloop_pods": True,
    }
    deployment_flags = []
    deployment_young = []
    pods_all_ready = True
    pods_unready_young = False
    saw_pods = False

    for ev in evidence_list:
        if ev.resource_kind == "Namespace":
            result["namespace_exists"] = ev.observed.get("namespace_exists", False)
        elif ev.resource_kind == "Deployment":
            result["deployment_exists"] = result["deployment_exists"] or ev.observed.get("deployment_exists", False)
            deployment_flags.append(bool(ev.observed.get("desired_replicas_ready", False)))
            age = ev.observed.get("age_minutes")
            deployment_young.append(age is not None and age < 15)
        elif ev.resource_kind == "PodList":
            saw_pods = True
            result["no_crashloop_pods"] = result["no_crashloop_pods"] and ev.observed.get("no_crashloop_pods", True)
            pods_all_ready = pods_all_ready and ev.observed.get("all_pods_ready", True)
            pods_unready_young = ev.observed.get("unready_pods_are_young", False)

    if deployment_flags:
        if all(deployment_flags):
            result["desired_replicas_ready"] = True
        elif all(deployment_young) or (saw_pods and not pods_all_ready and pods_unready_young):
            # Still starting: the criterion is unobserved, not failed.
            result["desired_replicas_ready"] = None
        else:
            result["desired_replicas_ready"] = False
    return result


def normalize_for_route_ready(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "service_exists": False,
        "route_exists": False,
        "service_has_ready_endpoints": False,
        "health_endpoint_returns_200": None,
        "ready_endpoint_count": 0,
    }
    probes: List[CollectedEvidence] = []
    for ev in evidence_list:
        if ev.resource_kind == "Service":
            result["service_exists"] = ev.observed.get("service_exists", False)
        elif ev.resource_kind == "Route":
            result["route_exists"] = ev.observed.get("route_exists", False)
            host = ev.observed.get("host") or ""
            if host:
                scheme = "http" if ev.observed.get("tls_termination") in (None, "") else "https"
                result["route_url"] = f"{scheme}://{host}"
        elif ev.resource_kind == "Endpoints":
            result["service_has_ready_endpoints"] = ev.observed.get("service_has_ready_endpoints", False)
            result["ready_endpoint_count"] = ev.observed.get("ready_endpoint_count", 0)
        elif ev.resource_kind == "HttpProbe":
            # The only source for this key. Absent a probe the value stays
            # None and the stage resolves indeterminate — which is the point.
            probes.append(ev)

    if probes:
        # One lab serves several routes (showroom, control, vscode, node02...).
        # Last-one-wins would make health depend on `oc get` ordering, so
        # aggregate — existentially, matching the rubric this key completes.
        #
        # `service_exists`, `route_exists` and `service_has_ready_endpoints`
        # are all satisfied by ANY service or route in the namespace. So the
        # optional probe must not demand MORE than the required ones: on 48
        # live lab namespaces, "every route must answer 2xx/3xx" failed 25 of
        # 48, mostly because labs ship routes whose backends the student is
        # meant to create (`app-`, `app-secure-`, `clab-report`, `bastion-443`).
        # Those are healthy labs by the rubric's own definition. "At least one
        # route answers" passed 39 of 48 and failed the 9 where nothing
        # answered at all — the observation the criterion exists to make.
        #
        # Nulls do not drag down an answered lab, and are only reported when
        # nothing conclusive came back (a timeout roster stays indeterminate).
        observed = [ev.observed.get("health_endpoint_returns_200") for ev in probes]
        answered = [ev for ev in probes if ev.observed.get("health_endpoint_returns_200") is True]
        result["routes_probed"] = len(probes)
        if answered:
            result["health_endpoint_returns_200"] = True
            result["probed_url"] = answered[0].observed.get("probed_url")
        elif any(value is False for value in observed):
            # Prefer a 5xx to report: a refused connection explains itself,
            # a 503 means the router had no healthy backend at all.
            failed = [
                ev for ev in probes if ev.observed.get("health_endpoint_returns_200") is False
            ]
            failed.sort(key=lambda ev: -int(ev.observed.get("http_status") or 0))
            worst = failed[0]
            result["health_endpoint_returns_200"] = False
            result["probed_url"] = worst.observed.get("probed_url")
            if worst.observed.get("http_status") is not None:
                result["http_status"] = worst.observed["http_status"]
            if worst.observed.get("probe_error"):
                result["probe_error"] = worst.observed["probe_error"]
        else:
            result["health_endpoint_returns_200"] = None

    # Topology is not an HTTP observation: this normalizer still executes no
    # probe. It only consumes one, when the caller ran
    # collectors.openshift.probe_route_health first.
    return result


def normalize_for_smoke_test_ready(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    has_ready_endpoints = False
    route_admitted = False
    for ev in evidence_list:
        if ev.resource_kind == "Endpoints":
            has_ready_endpoints = ev.observed.get("service_has_ready_endpoints", False)
        elif ev.resource_kind == "Route":
            route_admitted = ev.observed.get("admitted", False)

    route_reachable = has_ready_endpoints and route_admitted
    return {
        "route_reachable": route_reachable,
        "smoke_test_passed": None,
        "expected_response_received": None,
        "response_time_acceptable": None,
    }


def normalize_for_run_created(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    return {
        "run_id_present": True,
        "demo_id_present": True,
        "namespace_present": True,
        "rubric_version_present": True,
    }


def normalize_for_storage_clone_ready(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "namespace_exists": False,
        "datavolume_exists": False,
        "datavolume_succeeded": False,
        "pvc_bound": False,
        "clone_duration_acceptable": True,
    }
    for ev in evidence_list:
        if ev.resource_kind == "Namespace":
            result["namespace_exists"] = ev.observed.get("namespace_exists", False)
        elif ev.resource_kind == "DataVolume":
            result["datavolume_exists"] = ev.observed.get("datavolume_exists", False)
            result["datavolume_succeeded"] = ev.observed.get("datavolume_succeeded", False)
            if not result["pvc_bound"]:
                result["pvc_bound"] = ev.observed.get("pvc_bound", False)
        elif ev.resource_kind == "PersistentVolumeClaim":
            result["pvc_bound"] = ev.observed.get("pvc_bound", False)
    return result


def normalize_for_vm_runtime_ready(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "datavolume_succeeded": False,
        "vm_exists": False,
        "vmi_running": False,
        "guest_agent_connected": False,
        "guest_os_ready": False,
    }
    for ev in evidence_list:
        if ev.resource_kind == "DataVolume":
            result["datavolume_succeeded"] = ev.observed.get("datavolume_succeeded", False)
        elif ev.resource_kind == "VirtualMachine":
            result["vm_exists"] = ev.observed.get("vm_exists", False)
        elif ev.resource_kind == "VirtualMachineInstance":
            result["vmi_running"] = ev.observed.get("vmi_running", False)
            result["guest_agent_connected"] = ev.observed.get("guest_agent_connected", False)
            result["guest_os_ready"] = ev.observed.get("guest_os_ready", False)
    return result


def normalize_for_model_endpoint_ready(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "namespace_exists": False,
        "inferenceservice_exists": False,
        "inferenceservice_ready": False,
        "test_inference_succeeded": False,
        "inference_latency_acceptable": True,
    }
    for ev in evidence_list:
        if ev.resource_kind == "Namespace":
            result["namespace_exists"] = ev.observed.get("namespace_exists", False)
        elif ev.resource_kind == "InferenceService":
            result["inferenceservice_exists"] = ev.observed.get("inferenceservice_exists", False)
            result["inferenceservice_ready"] = ev.observed.get("inferenceservice_ready", False)
            result["test_inference_succeeded"] = ev.observed.get("model_loaded", False)
    return result


def normalize_for_provision_complete(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "anarchysubject_exists": False,
        "provision_job_succeeded": False,
        "state_is_started": False,
        "no_error_conditions": True,
    }
    for ev in evidence_list:
        if ev.resource_kind == "AnarchySubject":
            result["anarchysubject_exists"] = ev.observed.get("anarchysubject_exists", False)
            result["provision_job_succeeded"] = ev.observed.get("provision_job_succeeded", False)
            result["state_is_started"] = ev.observed.get("state_is_started", False)
            result["no_error_conditions"] = ev.observed.get("no_error_conditions", True)
    return result


def normalize_for_showroom_healthy(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "showroom_pod_running": False,
        "showroom_route_reachable": False,
        "readyz_returns_200": False,
        "content_loaded": False,
        "response_time_acceptable": True,
        # Diagnostics carried through so the failure message can name the URL.
        "route_url": "",
        "http_status": 0,
        "ready_endpoint_count": None,
        "catalog_item": "",
    }
    for ev in evidence_list:
        if ev.resource_kind == "ShowroomHealth":
            result["showroom_pod_running"] = ev.observed.get("showroom_pod_running", False)
            result["showroom_route_reachable"] = ev.observed.get("showroom_route_reachable", False)
            result["readyz_returns_200"] = ev.observed.get("readyz_returns_200", False)
            result["content_loaded"] = ev.observed.get("content_loaded", False)
            result["response_time_acceptable"] = ev.observed.get("response_time_acceptable", True)
            result["route_url"] = ev.observed.get("route_url") or result["route_url"]
            result["http_status"] = ev.observed.get("http_status") or result["http_status"]
            result["catalog_item"] = ev.observed.get("catalog_item") or result["catalog_item"]
        elif ev.resource_kind == "Endpoints":
            count = ev.observed.get("ready_endpoint_count")
            if count is not None:
                result["ready_endpoint_count"] = (result["ready_endpoint_count"] or 0) + count
    return result


def normalize_for_cluster_health(evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    result = {
        "cluster_reachable": False,
        "cpu_usage_acceptable": False,
        "memory_usage_acceptable": False,
        "no_critical_alerts": True,
        "nodes_healthy": False,
    }
    for ev in evidence_list:
        if ev.resource_kind == "ClusterHealth":
            result["cluster_reachable"] = ev.observed.get("cluster_reachable", False)
            result["cpu_usage_acceptable"] = ev.observed.get("cpu_usage_acceptable", False)
            result["memory_usage_acceptable"] = ev.observed.get("memory_usage_acceptable", False)
            result["no_critical_alerts"] = ev.observed.get("no_critical_alerts", True)
            result["nodes_healthy"] = ev.observed.get("nodes_healthy", False)
    return result


STAGE_NORMALIZERS = {
    "run-created": normalize_for_run_created,
    "namespace-ready": normalize_for_namespace_ready,
    "deployment-ready": normalize_for_deployment_ready,
    "route-ready": normalize_for_route_ready,
    "smoke-test-ready": normalize_for_smoke_test_ready,
    "storage-clone-ready": normalize_for_storage_clone_ready,
    "vm-runtime-ready": normalize_for_vm_runtime_ready,
    "model-endpoint-ready": normalize_for_model_endpoint_ready,
    "provision-complete": normalize_for_provision_complete,
    "showroom-healthy": normalize_for_showroom_healthy,
    "cluster-health": normalize_for_cluster_health,
}


def normalize_evidence(stage_id: str, evidence_list: List[CollectedEvidence]) -> Dict[str, Any]:
    normalizer = STAGE_NORMALIZERS.get(stage_id)
    if not normalizer:
        merged = {}
        for ev in evidence_list:
            merged.update(ev.observed)
        return merged
    return normalizer(evidence_list)
