"""Provisioning policy engine — generates allocation recommendations (display only, no execution).

Analyzes lab constraints, pool state, session schedule, and cluster capacity
to recommend optimal resource allocation. Each recommendation includes
targeted evidence from the specific data sources that informed it.

Policy rules (thresholds, confidence scores, urgency) are loaded from
policies/rules.yaml. Evidence-gathering logic stays in Python.
All output is advisory — no writes to any external system.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from engine.policy_loader import load_policy_rules


def _rules_by_id():
    """Load rules and index by ID."""
    ruleset = load_policy_rules()
    return {r.id: r for r in ruleset.rules}


def _constraint_to_stage():
    return load_policy_rules().constraint_to_stage


CONSTRAINT_TO_STAGE = property(lambda self: _constraint_to_stage())


class _ConstraintStageProxy(dict):
    """Dict proxy that stays in sync with YAML-loaded constraint_to_stage."""
    def __init__(self):
        super().__init__(_constraint_to_stage())


CONSTRAINT_TO_STAGE = _constraint_to_stage()


def generate_recommendations(
    labs: List[Dict],
    pools: Dict,
    cluster_states: List[Dict],
    sessions: List[Dict],
    evaluations: Optional[List[Dict]] = None,
    constraint_violations: Optional[Dict[str, List[Dict]]] = None,
) -> Dict:
    """Generate provisioning recommendations based on current state.

    Returns recommendations sorted by urgency. Does NOT execute anything.
    evaluations: list of EvaluationRecord dicts (from repository.list_evaluations)
    constraint_violations: dict of lab_code → list of violation dicts
    """
    recommendations = []
    rules = _rules_by_id()

    evals_by_lab: Dict[str, List[Dict]] = {}
    evals_by_demo_type: Dict[str, List[Dict]] = {}
    if evaluations:
        for ev in evaluations:
            lc = ev.get("lab_code") or ""
            if lc:
                evals_by_lab.setdefault(lc, []).append(ev)
                parts = lc.split("-")
                if len(parts) >= 3:
                    demo_type = "-".join(parts[2:])
                    evals_by_demo_type.setdefault(demo_type, []).append(ev)

    cv_by_lab = constraint_violations or {}

    sessions_by_lab: Dict[str, List[Dict]] = {}
    for s in sessions:
        code = s.get("lab_code", "")
        if code:
            sessions_by_lab.setdefault(code, []).append(s)

    summit_pools = pools.get("summit_pools", [])
    pools_by_name = {p.get("name", ""): p for p in summit_pools}
    exhausted_pools = pools.get("exhausted_pools", [])
    low_pools = pools.get("low", []) if isinstance(pools.get("low"), list) else []
    prov_state = pools.get("provisioning", {}) if "provisioning" in pools else {}

    # --- Rule: provision_blocked_lab ---
    rule = rules.get("provision_blocked_lab")
    if rule:
        for lab in labs:
            if lab.get("sessions", 0) == 0:
                continue
            has_prov = (
                lab.get("instances_started", 0) > 0
                or lab.get("provisioned", 0) > 0
                or lab.get("capacity", 0) > 0
            )
            if has_prov:
                continue

            ci_name = lab.get("ci_name", "")
            cloud = lab.get("cloud", "")
            pool_match = _find_pool_match(ci_name, cloud, pools)
            matched_pool = pools_by_name.get(pool_match, {}) if pool_match and pool_match in pools_by_name else {}
            lab_sessions = sessions_by_lab.get(lab["lab_code"], [])

            recommendations.append({
                "type": rule.id,
                "urgency": rule.get_urgency(),
                "lab_code": lab["lab_code"],
                "title": lab.get("title", ""),
                "sessions": lab["sessions"],
                "summit_days": lab.get("summit_days", []),
                "attendees": lab.get("total_attendees", 0),
                "recommendation": f"Allocate pool for {lab['lab_code']} — {lab['sessions']} session(s) scheduled, no provisioning",
                "suggested_pool": pool_match,
                "cloud": cloud,
                "ci_name": ci_name,
                "confidence_score": rule.get_confidence(),
                "confidence_reason": rule.confidence_reason or "Sessions confirmed, zero provisioning detected",
                "evidence": {
                    "source_labagator": {
                        "sessions_scheduled": lab["sessions"],
                        "session_details": [{"date": s.get("session_date"), "room": s.get("room"), "attendees": s.get("attendees")} for s in lab_sessions[:5]],
                        "lab_status": lab.get("labagator_status"),
                        "total_attendees": lab.get("total_attendees", 0),
                        "summit_days": lab.get("summit_days", []),
                    },
                    "source_babylon": {
                        "instances_started": lab.get("instances_started", 0),
                        "instances_failed": lab.get("instances_failed", 0),
                        "instances_total": lab.get("instances_total", 0),
                        "instances_destroying": lab.get("instances_destroying", 0),
                        "provisioned_count": lab.get("provisioned", 0),
                    },
                    "source_poolboy": {
                        "suggested_pool": pool_match,
                        "pool_available": matched_pool.get("available") if matched_pool else None,
                        "pool_ready": matched_pool.get("ready") if matched_pool else None,
                        "pool_min": matched_pool.get("min") if matched_pool else None,
                        "exhausted_pools_on_platform": len(exhausted_pools),
                    },
                    "source_agnosticv": {
                        "ci_name": ci_name,
                        "cloud": cloud,
                        "deploy_mode": lab.get("deploy_mode"),
                    },
                },
                "decision_logic": rule.condition,
            })

    # --- Rule: cleanup_stuck ---
    rule = rules.get("cleanup_stuck")
    if rule:
        for lab in labs:
            failed = lab.get("instances_failed", 0)
            if failed == 0:
                continue

            lab_sessions = sessions_by_lab.get(lab["lab_code"], [])
            instances = lab.get("instances", [])

            reason_tpl = rule.confidence_reason_template or "{failed} instances in failed state"
            confidence_reason = reason_tpl.format(failed=failed)

            recommendations.append({
                "type": rule.id,
                "urgency": rule.get_urgency(),
                "lab_code": lab["lab_code"],
                "title": lab.get("title", ""),
                "stuck_count": failed,
                "total_instances": lab.get("instances_total", 0),
                "recommendation": f"Clean up {failed} stuck instances for {lab['lab_code']} — consuming resources without serving attendees",
                "action": f"Delete destroy-failed AnarchySubjects for {lab['lab_code']}",
                "confidence_score": rule.get_confidence(),
                "confidence_reason": confidence_reason,
                "evidence": {
                    "source_babylon": {
                        "instances_failed": failed,
                        "instances_total": lab.get("instances_total", 0),
                        "instances_started": lab.get("instances_started", 0),
                        "instances_destroying": lab.get("instances_destroying", 0),
                        "failed_instances": [
                            {"name": i.get("anarchy_name", "?"), "state": i.get("state", "?"), "cluster": i.get("cluster", "?")}
                            for i in instances if "failed" in (i.get("state") or "")
                        ][:10],
                    },
                    "source_labagator": {
                        "sessions_scheduled": lab.get("sessions", 0),
                        "has_upcoming_sessions": len(lab_sessions) > 0,
                    },
                    "source_cluster": {
                        "cloud": lab.get("cloud", ""),
                        "deploy_clusters": list(set(i.get("cluster", "") for i in instances if i.get("cluster")))[:5],
                    },
                },
                "decision_logic": rule.condition,
            })

    # --- Rule: pool_exhaustion ---
    rule = rules.get("pool_exhaustion")
    if rule:
        available_max = (rule.thresholds or {}).get("available_max", 1)
        for pool in summit_pools:
            available = pool.get("available", 0)
            min_required = pool.get("min", 0)
            if min_required > 0 and available <= available_max:
                pool_name = pool.get("name", "")

                recommendations.append({
                    "type": rule.id,
                    "urgency": rule.get_urgency(),
                    "pool_name": pool_name,
                    "available": available,
                    "min_required": min_required,
                    "recommendation": f"Pool {pool_name} nearly exhausted — {available} available of {min_required} required",
                    "action": "Scale pool or reduce lab allocation",
                    "confidence_score": rule.get_confidence(available=available),
                    "confidence_reason": f"Pool capacity: {available}/{min_required} from Poolboy ResourcePool CRD",
                    "evidence": {
                        "source_poolboy": {
                            "pool_name": pool_name,
                            "available": available,
                            "ready": pool.get("ready", 0),
                            "min_required": min_required,
                            "status": pool.get("status", "unknown"),
                        },
                        "source_babylon": {
                            "platform_provisioning_started": prov_state.get("started", 0),
                            "platform_provisioning_failed": prov_state.get("failed", 0),
                            "platform_failure_rate": prov_state.get("failure_rate", 0),
                            "provisioning_by_state": prov_state.get("by_state", {}),
                        },
                        "source_platform": {
                            "total_exhausted_pools": len(exhausted_pools),
                            "total_low_pools": len(low_pools) if isinstance(low_pools, list) else 0,
                            "exhausted_pool_names": exhausted_pools[:5] if isinstance(exhausted_pools, list) else [],
                        },
                    },
                    "decision_logic": rule.condition,
                })

    # --- Rule: cluster_capacity ---
    rule = rules.get("cluster_capacity")
    if rule:
        thresholds = rule.thresholds or {}
        cpu_warn = thresholds.get("avg_cpu_warn", 70)
        vms_warn = thresholds.get("vms_per_node_warn", 80)

        for cluster in cluster_states:
            cpu = cluster.get("avg_cpu", 0)
            vms_per_node = cluster.get("vms_per_node", 0)
            if cpu > cpu_warn or vms_per_node > vms_warn:
                cluster_name = cluster.get("cluster", "")
                labs_on_cluster = [l for l in labs if any(
                    i.get("cluster") == cluster_name for i in l.get("instances", [])
                )]

                recommendations.append({
                    "type": rule.id,
                    "urgency": rule.get_urgency(avg_cpu=cpu),
                    "cluster": cluster_name,
                    "cpu": cpu,
                    "vms_per_node": vms_per_node,
                    "recommendation": f"Cluster {cluster_name} approaching capacity — CPU {cpu:.0f}%, {vms_per_node:.0f} VMs/node",
                    "action": "Consider migrating labs to less loaded cluster or scaling nodes",
                    "confidence_score": rule.get_confidence(avg_cpu=cpu),
                    "confidence_reason": f"CPU {cpu:.0f}% from live node metrics (oc adm top nodes), VMs/node from pod scan",
                    "evidence": {
                        "source_cluster_scanner": {
                            "cluster": cluster_name,
                            "avg_cpu": cpu,
                            "vms_per_node": vms_per_node,
                            "sandbox_active": cluster.get("sandbox_active", 0),
                            "hot_nodes": cluster.get("hot_nodes", 0) if "hot_nodes" in cluster else None,
                        },
                        "source_node_metrics": {
                            "total_vms": cluster.get("total_vms", 0) if "total_vms" in cluster else None,
                            "compute_nodes": cluster.get("compute_nodes", 0) if "compute_nodes" in cluster else None,
                        },
                        "source_labs": {
                            "labs_on_this_cluster": len(labs_on_cluster),
                            "lab_codes": [l["lab_code"] for l in labs_on_cluster[:10]],
                        },
                        "source_comparison": {
                            "all_cluster_cpus": {c.get("cluster", ""): c.get("avg_cpu", 0) for c in cluster_states},
                        },
                    },
                    "decision_logic": rule.condition,
                })

    # --- Rule: smoke_test_failing ---
    rule = rules.get("smoke_test_failing")
    if rule:
        for lab in labs:
            if lab.get("demolition_status") != "fail":
                continue
            if lab.get("sessions", 0) == 0:
                continue
            days = lab.get("summit_days", [])

            failed_ct = lab.get("demolition_failed", 0)
            total_ct = lab.get("demolition_total", 0)
            completed_ct = lab.get("demolition_completed", 0)
            lab_sessions = sessions_by_lab.get(lab["lab_code"], [])
            instances = lab.get("instances", [])
            instance_clusters = list(set(i.get("cluster", "") for i in instances if i.get("cluster")))

            recommendations.append({
                "type": rule.id,
                "urgency": rule.get_urgency(has_summit_days=bool(days)),
                "lab_code": lab["lab_code"],
                "title": lab.get("title", ""),
                "sessions": lab["sessions"],
                "summit_days": days,
                "failed_count": failed_ct,
                "total_count": total_ct,
                "recommendation": f"{lab['lab_code']} failing smoke test ({failed_ct}/{total_ct}) — has {lab['sessions']} session(s) on {', '.join(days)}",
                "confidence_score": rule.get_confidence(total_count=total_ct),
                "confidence_reason": f"Demolition results: {failed_ct}/{total_ct} failures" + (" (small sample)" if total_ct < 10 else ""),
                "evidence": {
                    "source_demolition": {
                        "status": lab.get("demolition_status"),
                        "failed": failed_ct,
                        "completed": completed_ct,
                        "total": total_ct,
                        "pass_rate": round(completed_ct / max(total_ct, 1) * 100, 1) if total_ct > 0 else None,
                    },
                    "source_labagator": {
                        "sessions": lab["sessions"],
                        "summit_days": days,
                        "next_session": lab_sessions[0] if lab_sessions else None,
                        "total_attendees": lab.get("total_attendees", 0),
                    },
                    "source_babylon": {
                        "instances_started": lab.get("instances_started", 0),
                        "instances_failed": lab.get("instances_failed", 0),
                        "deploy_clusters": instance_clusters[:5],
                    },
                    "source_agnosticv": {
                        "cloud": lab.get("cloud", ""),
                        "ci_name": lab.get("ci_name", ""),
                    },
                },
                "decision_logic": rule.condition,
            })

    # --- Rule: substrate_routing ---
    rule = rules.get("substrate_routing")
    if rule:
        try:
            from engine.substrate_router import route_workload
            for cluster in cluster_states:
                routing = route_workload({"nodes": cluster, "pods": {}})
                if routing.routing in ("xeon6_fallback", "rebalance_to_xeon6"):
                    recommendations.append({
                        "type": rule.id,
                        "urgency": rule.get_urgency(),
                        "cluster": cluster.get("cluster", ""),
                        "recommendation": routing.reason,
                        "action": f"Route {routing.inference_target} for inference, {routing.compute_target} for compute",
                        "confidence_score": rule.get_confidence(),
                        "confidence_reason": f"Gaudi at {routing.gaudi_util:.0f}%, Xeon6 at {routing.xeon6_util:.0f}%",
                        "evidence": {
                            "source_substrate_router": {
                                "routing_decision": routing.routing,
                                "inference_target": routing.inference_target,
                                "compute_target": routing.compute_target,
                                "gaudi_utilization": routing.gaudi_util,
                                "xeon6_utilization": routing.xeon6_util,
                            },
                        },
                        "decision_logic": rule.condition,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    })
        except ImportError:
            pass

    # --- Rule: aap_provision_failing ---
    rule = rules.get("aap_provision_failing")
    if rule:
        for lab in labs:
            aap_failures = lab.get("aap_provision_failures", 0)
            if aap_failures > 0:
                recommendations.append({
                    "type": rule.id,
                    "urgency": rule.get_urgency(),
                    "lab_code": lab["lab_code"],
                    "title": lab.get("title", ""),
                    "recommendation": f"{lab['lab_code']} has {aap_failures} AAP provisioning failures: {lab.get('aap_top_error', 'check Tower')}",
                    "action": "Check AAP Tower job logs for failing task details",
                    "confidence_score": rule.get_confidence(),
                    "confidence_reason": f"{aap_failures} AAP job failures with task-level error detail",
                    "evidence": {
                        "source_aap": {
                            "provision_failures": aap_failures,
                            "top_error": lab.get("aap_top_error", ""),
                        },
                        "source_babylon": {
                            "instances_started": lab.get("instances_started", 0),
                            "instances_failed": lab.get("instances_failed", 0),
                            "instances_total": lab.get("instances_total", 0),
                        },
                    },
                    "decision_logic": rule.condition,
                })

    # --- Rule: aap_sli_breach ---
    rule = rules.get("aap_sli_breach")
    if rule and any(l.get("aap_provision_failures", 0) > 0 for l in labs):
        try:
            from collectors.aap.collect_aap import collect_aap_jobs
            aap_data = collect_aap_jobs()
            sli_summary = aap_data.get("summary", {})
            if not sli_summary.get("sli_met", True):
                recommendations.append({
                    "type": rule.id,
                    "urgency": rule.get_urgency(),
                    "recommendation": f"Platform provision SLI at {sli_summary.get('provision_sli', 0)}% — below {sli_summary.get('provision_sli_target', 93)}% target. {sli_summary.get('failed_24h', 0)} failures in 24h.",
                    "action": "Review top AAP errors and address systemic issues",
                    "confidence_score": rule.get_confidence(),
                    "confidence_reason": f"AAP provision success rate {sli_summary.get('provision_sli', 0)}% below {sli_summary.get('provision_sli_target', 93)}% SLI target",
                    "evidence": {
                        "source_aap": {
                            "provision_sli": sli_summary.get("provision_sli", 0),
                            "sli_target": sli_summary.get("provision_sli_target", 93),
                            "total_jobs": sli_summary.get("total_jobs", 0),
                            "failed_24h": sli_summary.get("failed_24h", 0),
                            "success_rate": sli_summary.get("success_rate", 0),
                        },
                    },
                    "decision_logic": rule.condition,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            pass

    # Augment each recommendation with rubric context and constraint violations
    for r in recommendations:
        lab = r.get("lab_code")
        if not lab:
            continue

        lab_evals = evals_by_lab.get(lab, [])
        if not lab_evals:
            ci = r.get("ci_name", "")
            pool = r.get("pool_name", "") or r.get("suggested_pool", "") or ""
            for demo_type, demo_evals in evals_by_demo_type.items():
                if (ci and demo_type in ci.lower()) or (pool and demo_type in pool.lower()) or (lab.lower().replace("lb", "") in demo_type):
                    lab_evals = demo_evals
                    break

        if lab_evals:
            r["rubric_context"] = _build_rubric_context(lab_evals)
        if lab in cv_by_lab:
            r["constraint_violations"] = _correlate_constraints(cv_by_lab[lab], lab_evals)

    now = datetime.now(timezone.utc).isoformat()
    for r in recommendations:
        r["generated_at"] = now
    urgency_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recommendations.sort(key=lambda r: urgency_order.get(r["urgency"], 99))

    return {
        "recommendations": recommendations,
        "total": len(recommendations),
        "critical": sum(1 for r in recommendations if r["urgency"] == "critical"),
        "high": sum(1 for r in recommendations if r["urgency"] == "high"),
        "medium": sum(1 for r in recommendations if r["urgency"] == "medium"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_rubric_context(evaluations: List[Dict]) -> Dict:
    """Build rubric context from evaluation records for a lab."""
    stages_seen: Dict[str, Dict] = {}
    for ev in evaluations:
        sid = ev.get("stage_id", "")
        if not sid:
            continue
        existing = stages_seen.get(sid)
        if existing and existing.get("evaluated_at", "") >= (ev.get("evaluated_at") or ""):
            continue
        stages_seen[sid] = ev

    failures = []
    passing = 0
    failing = 0
    for sid, ev in sorted(stages_seen.items()):
        outcome = (ev.get("outcome") or "").lower()
        if outcome == "pass":
            passing += 1
        elif outcome in ("fail", "warn"):
            failing += 1
            criteria = ev.get("criteria_results") or []
            criteria_failed = [c["name"] for c in criteria if isinstance(c, dict) and not c.get("passed", True)]
            criteria_passed = [c["name"] for c in criteria if isinstance(c, dict) and c.get("passed", True)]
            failures.append({
                "stage_id": sid,
                "outcome": outcome,
                "failure_class": ev.get("failure_class"),
                "criteria_failed": criteria_failed,
                "criteria_passed": criteria_passed,
                "evaluated_at": ev.get("evaluated_at"),
            })

    return {
        "stages_evaluated": len(stages_seen),
        "stages_passing": passing,
        "stages_failing": failing,
        "failures": failures,
    }


def _correlate_constraints(violations: List[Dict], evaluations: List[Dict]) -> List[Dict]:
    """Correlate constraint violations with rubric failure classes."""
    c2s = _constraint_to_stage()
    eval_by_stage: Dict[str, Dict] = {}
    for ev in evaluations:
        sid = ev.get("stage_id", "")
        if sid and (ev.get("outcome") or "").lower() in ("fail", "warn"):
            if sid not in eval_by_stage or (ev.get("evaluated_at") or "") > (eval_by_stage[sid].get("evaluated_at") or ""):
                eval_by_stage[sid] = ev

    result = []
    for v in violations:
        vtype = v.get("violation_type", "")
        corr_stage = c2s.get(vtype)
        corr_eval = eval_by_stage.get(corr_stage, {}) if corr_stage else {}
        result.append({
            "type": vtype,
            "expected": v.get("expected", ""),
            "actual": v.get("actual", ""),
            "severity": v.get("severity", "warning"),
            "detail": v.get("detail", ""),
            "correlated_rubric_stage": corr_stage,
            "correlated_failure_class": corr_eval.get("failure_class") if corr_eval else None,
        })
    return result


def _find_pool_match(ci_name: str, cloud: str, pools: Dict) -> Optional[str]:
    """Find a matching pool for a lab based on ci_name and cloud."""
    if not ci_name:
        return None

    summit_pools = pools.get("summit_pools", [])
    slug = ci_name.split(".", 1)[1] if "." in ci_name else ci_name
    lb_part = slug.split("-")[0] if slug else ""

    for pool in summit_pools:
        name = pool.get("name", "")
        if lb_part and lb_part in name:
            return name

    CLOUD_TO_POOL = {
        "CNV": "ocp4-cluster or zt-rhel pool",
        "AWS": "aws-based pool",
        "Tenant Namespace": "tenant namespace (no dedicated pool needed)",
    }
    return CLOUD_TO_POOL.get(cloud)
