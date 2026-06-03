# StarGate Platform — TODO & Next Steps

## What StarGate Is

StarGate is the continuous operations platform for RHDP. It monitors OpenShift clusters, evaluates lab/demo readiness against rubrics, classifies failures using AI (Granite LLM via MAAS/LiteLLM), and auto-remediates with a gradual per-lab rollout model.

It works **with** the RHDP ecosystem — not around it:
- **Tier 1 (Kubernetes-native):** Pod restarts, deployment rollouts — safe, direct execution
- **Tier 2 (RHDP-managed):** AnarchySubject lifecycle, pool scaling, Sandbox API actions — routed through Anarchy/Poolboy/Sandbox API controllers

## Current State

| Component | Status |
|---|---|
| Dashboard (React + PatternFly 6) | Deployed on infra01 with Red Hat SSO |
| Cluster scanning (6 clusters) | Working, tokens need refresh |
| Rubric evaluation pipeline | Working (11 stages) |
| LLM classification (Granite via MAAS) | Working, proposals pending review |
| Auto-remediation engine | Built, per-lab gradual rollout ready, 5-gate execution model |
| Security hardening | Complete — auth, SSRF, TLS, prompt injection, credential hygiene |
| RHDP-aware execution (Anarchy/Poolboy/Sandbox API) | Built, untested against real labs |
| AgnosticV Catalog Item | Created, needs CI review |
| AgnosticD Ansible role | Created, needs integration testing |
| Git-SHA image tagging | Ready (`scripts/build-and-tag.sh`) |

## What Needs Team Input

### 1. AgnosticV CI Review (Ashok / Tony)

StarGate is packaged as a proper CI at `deploy/agnosticv/stargate-platform/`:
- `common.yaml` — base definition with Babylon metadata
- `dev.yaml` — CNV clusters, mock execution
- `integration.yaml` — staging, real scanners (3 clusters)
- `prod.yaml` — full production, all scanners + collectors

**Questions for the team:**
- Which AgnosticV repo should this CI be registered in?
- Is the execution environment image correct? (`quay.io/agnosticd/ee-multicloud:chained-2026-02-23`)
- Which cluster for the integration stage?
- Should the Ansible role live in a separate collection or in agnosticd-v2?

### 2. MAAS / LiteLLM Access

StarGate uses MAAS for all LLM inference (Granite 3.2 8B). Currently configured with a LiteLLM API key.

**Questions:**
- Should StarGate get its own LiteLLM virtual key via the standard provisioning flow?
- Is the current model (`granite-3-2-8b-instruct`) available through MAAS?

### 3. Launchpad CI Alignment

Launchpad has 13 AgnosticV CIs but needs alignment:
- Default inference should be MAAS, not direct Gaudi deployment
- `dev.yaml` / `event.yaml` overrides are stubs — need proper staging
- Need `integration.yaml` and `prod.yaml` per CI

**This should be coordinated with Ashok before changing**, since it affects how demos are provisioned.

## Actionable TODOs

### Immediate (Can Do Now)

- [x] AgnosticV CI structure for StarGate (common + dev/integration/prod)
- [x] AgnosticD Ansible role (`deploy/ansible/roles/stargate_deploy/`)
- [x] Git-SHA image tagging (`scripts/build-and-tag.sh`)
- [x] Security hardening (auth, SSL, input validation, secrets sanitized)
- [x] Repo public-ready (no secrets, no internal URLs in source, no PII)
- [x] RHDP-aware remediation (two-tier execution model)
- [ ] Refresh cluster scanner SA tokens (run `scripts/refresh-kubeconfigs.sh` per cluster — needs console login for each)

### Needs Team (This Week)

- [ ] Schedule CI review with Ashok/Tony — show them the AgnosticV structure and Ansible role
- [ ] Get MAAS/LiteLLM virtual key for StarGate via standard provisioning
- [ ] Confirm integration cluster target
- [ ] Discuss Launchpad inference defaults (MAAS vs direct Gaudi)
- [ ] Register StarGate CI in the proper AgnosticV repo

### After CI Review (Next Sprint)

- [ ] Deploy StarGate dev instance on CNV cluster via AgnosticV/Babylon
- [ ] Test devel → integration promotion
- [ ] Deploy Launchpad on same CNV cluster — verify StarGate monitors it
- [ ] Test auto-remediation E2E: Launchpad lab fails → StarGate detects → recommends → (manual approve) → RHDP action → verify
- [ ] Close LLM feedback loop (review pending proposals, promote to deterministic rules)

### Longer Term

- [ ] Watch mode with Slack/PagerDuty alerting (PASS→FAIL state transitions)
- [ ] Remediation effectiveness tracking dashboard
- [ ] Multi-tenant RBAC (team leads see only their labs)
- [ ] Prometheus /metrics endpoint for Grafana
- [ ] Capacity planning (weekly/monthly trends, pool exhaustion prediction)

## Key Files for Review

| File | Purpose |
|---|---|
| `deploy/agnosticv/stargate-platform/common.yaml` | AgnosticV Catalog Item definition |
| `deploy/agnosticv/stargate-platform/dev.yaml` | Dev stage overrides |
| `deploy/ansible/roles/stargate_deploy/tasks/main.yaml` | Ansible role for deployment |
| `deploy/ansible/deploy-dev.yaml` | Quick test playbook |
| `engine/rhdp_client.py` | RHDP API client (Anarchy, Poolboy, Sandbox API) |
| `remediations/catalog.yaml` | All remediation actions with `execution_method` |
| `scripts/build-and-tag.sh` | Image build with git-SHA tagging |
| `scripts/refresh-kubeconfigs.sh` | SA token generation for cluster scanning |

## Architecture Reference

```
Launchpad provisions labs via Sandbox API → AgnosticD → ArgoCD
                    ↓
StarGate monitors via cluster scanner (oc CLI with kubeconfigs)
                    ↓
Rubric evaluation: 11 stages per namespace
                    ↓
Failure → LLM classification (Granite via MAAS/LiteLLM)
                    ↓
Recommendation → Per-lab execution mode gate
                    ↓
    ┌─── Tier 1: Kubernetes-native (pod restart, rollout)
    └─── Tier 2: RHDP API (Anarchy retry, Poolboy scale, Sandbox API action)
                    ↓
Audit log → Effectiveness tracking → Feedback loop
```

## Links

- **Repo:** https://github.com/rhpds/stargate
- **Dashboard:** https://stargate.apps.ocpv-infra01.dal12.infra.demo.redhat.com
- **Launchpad:** https://github.com/rhpds/launchpad
