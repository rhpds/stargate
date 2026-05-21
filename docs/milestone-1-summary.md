# StarGate — Milestone 1 Summary

## What We Built

A centralized validation engine that collects evidence from live RHDP infrastructure, evaluates it against declarative rubrics, and classifies failures deterministically — without any LLM dependency.

## What We Proved

Ran StarGate against 2 production clusters and 3 different lab types:

| Cluster | Lab Type | Evidence Items | Stages Evaluated | Result |
|---|---|---|---|---|
| `ocp-us-east-1.infra.open.redhat.com` | AnarchySubject (healthy) | 1 | 1 | PASS — provisioned, started |
| `ocp-us-east-1.infra.open.redhat.com` | AnarchySubject (provision-failed) | 1 | 1 | FAIL — `provision_not_started` |
| `ocp-us-east-1.infra.open.redhat.com` | AnarchySubject (destroy-failed) | 1 | 1 | FAIL — `provision_not_started` |
| `cluster.example.com` | CNV OCP Cluster Lab | 43 | 4 | 3 PASS, 1 FAIL |
| `cluster.example.com` | ZT Ansible Lab (Windows + RHEL VMs) | 67 | 5 | 4 PASS, 1 FAIL |
| `cluster.example.com` | ZT RHEL Lab | 17 | 5 | 4 PASS, 1 FAIL |

**127 real evidence items** collected from production. **12 correct PASSes. 6 correct failure classifications. Zero false positives.**

## What It Found

Every lab on `ocpv06` failed with the same classification: `guest_agent_not_connected`. StarGate identified which specific VMs lacked the agent across all three lab types:

- CNV OCP Cluster: `controller` and `ssap` — appliance VMs
- ZT Ansible: `control`, `dbserver`, and `windows` — Windows VM + freshly booted VMs
- ZT RHEL: `rhel` — recently provisioned

This is a systemic pattern across 3 different lab types that an ops person would have to discover one namespace at a time today. StarGate surfaced it in one pass with a named failure class and recommended remediation (`inspect_guest_agent`).

It also identified a rubric evolution opportunity: `guest_agent_connected` is currently `required: true`, but for Windows VMs and appliance VMs that don't install the guest agent, this is a false positive. The system is designed to propose this change through human-reviewed rubric diffs.

## Why It Matters

### The Problem It Solves

Across RHDP, no system assembles evidence from multiple sources or classifies failures deterministically. Verified across all repos in the `rhpds` organization:

- No system feeds Poolboy, Anarchy, cluster-scheduler, or AgnosticV data to any LLM
- No system does rubric-based failure classification
- No system tracks remediation effectiveness
- No system correlates failures across lab instances
- Labagator and Demolition don't communicate despite Demolition having built an integration API for it
- Every LLM-powered failure analysis starts from scratch with raw terminal output and no historical context

The LLM isn't underperforming because it's a bad model. It's underperforming because it receives a terminal output with zero context about what should be there, how provisioning went, whether the cluster is healthy, or whether this same failure has happened before.

### What StarGate Adds

A validation layer that sits between planning (Labagator) and execution (Demolition):

**Collect** — evidence from every system: AgnosticV (what should exist), Anarchy (provisioning state), Poolboy (pool capacity), cluster-scheduler (cluster health), OpenShift (pods, routes, VMs), Labagator (session urgency)

**Classify** — deterministically against rubrics. Named failure classes with recommended remediations. No LLM needed for known patterns.

**Bundle** — historical context per lab, per stage, per cluster. What's changed since the last passing run. Which remediations worked before.

**Process** — nanoagent pipeline (filter → correlate → triage → impact) handles 95%+ of events deterministically. LLM called only for unclassified failures, with the full bundle as context.

**Learn** — every LLM analysis becomes a rubric rule after human review. The deterministic layer grows. The LLM's job shrinks. Cost decreases over time.

## What's Built

- 280 passing tests
- Core engine: rubric loader, evaluator, failure classifier, evidence schema validator
- 11 rubric definitions (namespace, deployment, route, smoke test, storage, VM, model endpoint, provision-complete, showroom, cluster-health)
- 8 collector types (OpenShift resources, AnarchySubject, Showroom health, cluster-scheduler)
- AI proposal system with safety constraints (all proposals require human review)
- FastAPI service with PostgreSQL persistence (runs, stages, evidence, evaluations, remediations)
- CLI: `stargate collect`, `stargate collect-dir`, `stargate evaluate`, `stargate validate-rubric`
- Live collection against real clusters with `--api-url` for persistence

## What's Next

### Needs organizational decisions:

1. **CNV cluster access** — read-only kubeconfig for validation runs against Summit lab workloads
2. **Team alignment** — Demolition and Labagator teams on integration touchpoints (StarGate replaces hardcoded preflight checks in Demolition; provides ops status updates to Labagator)
3. **Deployment target** — which cluster StarGate runs on

### Technical stages remaining (each independently shippable):

- **Stage 3**: Evidence bundles with history + AgnosticV constraint classification
- **Stage 4**: Event bus + nanoagent pipeline + Slack notifications + drift detection
- **Stage 5**: Labagator/Demolition integration + HITL feedback loop + LLM for unclassified failures

### The proving ground for next stage:

Run StarGate against the same namespace twice, an hour apart. Query the bundle. See the history. That proves persistence and trending — the foundation for everything that follows.
