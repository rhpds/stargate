# StarGate — Summit 2026 Event Controller Status

**Scanned**: 2026-05-06
**Source**: `ocp-us-east-1.infra.example.com` (Babylon control plane)

## Event Controller Health

| Namespace | Pods | Status |
|---|---|---|
| babylon-anarchy-events | 14 running | Healthy |
| babylon-anarchy-events-a | 25 running | Healthy |
| babylon-anarchy-events-b | 14 running | Healthy |
| babylon-anarchy-events-c | 14 running | Healthy |

All event controllers are running. No pod failures.

## Summit 2026 AnarchySubjects — Current State

**146 total subjects** in `babylon-anarchy-events`. Of these, **49 are in a failed/destroyed state**.

### Summit Labs Currently Running (started)

| Lab | Instances | Age |
|---|---|---|
| lb2862 AI App Dev (tenant) | 20 | 5-6h |
| lb2236 Ansible Dev Tools (tenant) | 6 | 4h |
| lb1912 Infoscale (pool) | 6 | 9min-2d |
| lb2131 AI Data Flows | 3 | 9h-38h |
| lb2759 Agentic AIOps AAP | 3 | 5h-2d |
| lb1161 Sovereign Cloud (CNV+SNO) | 5 | 2d-4d |
| lb2865 Hummingbird (cluster+tenant) | 2 | 8h-4d |
| lb2391 Modernize OCP Virt (tenant) | 2 | 2d |
| lb2645 Agentic DevOps (tenant) | 1 | 3d |
| lb1464 Unified DevSecOps (AWS) | 2 | 23h-4d |
| lb1347 Advanced AAP (CNV) | 1 | 39h |
| lb1305 AI Powered RHEL Mgmt | 2 | 30-33h |
| lb1237 HOL RHEL10 (CNV) | 2 | 13-20h |
| lb1088 Code Red Breach Challenge | 1 | 37h |
| lb2863 OCP App Platform ROI | 2 | 3h-23h |
| lb2862 AI App Dev (cluster) | 1 | 7h |
| lb2860 Private MaaS (cluster+tenant) | 2 | 2h-13h |
| lb2236 Ansible Dev Tools (cluster) | 1 | 5h |
| lb1839 Balance Virt | 3 | 8-9h |
| lb1912 Infoscale | 1 | 4h |
| lb1401 Guardrails (tenant) | 2 | 16-27h |
| lb2144 AgentOps (CNV) | 2 | 5-7h |

### Summit Labs That Failed (destroy-failed)

| Lab | Failed Instances | Age | Pattern |
|---|---|---|---|
| **lb2865 Hummingbird (tenant)** | 10 | 8-9d | Bulk failure — all instances failed around same time |
| **AI Lightning FFT (tenant)** | 9 | 2-5d | Bulk failure in two waves (2d and 5d ago) |
| **AI Lightning Wordswarm** | 6 | 2-5d | Same pattern as FFT |
| **AI Lightning Voice Agents** | 6 | 2-5d | Same pattern |
| **AI Lightning Private MaaS** | 3 | 5d | Same wave |
| **lb2144 AgentOps (CNV)** | 5 | 2d | Bulk failure 2 days ago |
| **lb2596 Quarkus OpenShift (tenant)** | 4 | 6-21d | Older failures |
| **lb1401 Guardrails (tenant+cluster)** | 4 | 42h-22d | Mixed ages |
| **lb1305 AI Powered RHEL** | 2 | 7d | |
| **lb2010 RHADS OLS Modernize** | 1 | 7d | |
| **lb1237 HOL RHEL10** | 1 | 7d | |
| **lb1464 Unified DevSecOps (CNV)** | 1 | 9d | |
| **lb1839 Balance Virt** | 1 | 5d | |

**Key pattern**: The AI Lightning labs (FFT, Wordswarm, Voice Agents, Private MaaS) all failed in the same 5-day window — 24 instances destroyed. This is a systemic failure of the AI Lightning tenant provisioning, not individual lab issues.

## Platform-Wide Failure Breakdown

Across all Anarchy namespaces (not just Summit):

| Failure Type | Count |
|---|---|
| destroy-failed | 127 |
| provision-failed | 67 |
| start-failed | 2 |
| stop-failed | 1 |
| **Total** | **197** |

### Top Failing Catalog Items

| Catalog Item | Failures | Type |
|---|---|---|
| zt-rhelbu.zt-rhel-bu-lab-developer-cnv.prod | 36 | RHEL ZT labs |
| ai-quickstarts.ai-qs-ppe-comp-tenant.event | 25 | AI Quickstarts |
| ai-quickstarts.ai-qs-data-gov-tenant.event | 19 | AI Quickstarts |
| openshift-cnv.osp-on-ocp-cnv.prod | 18 | OSP on OCP |
| summit-2026.lb2865-hummingbird-cnv-tenant.event | 10 | Hummingbird |
| ai-quickstarts.ai-qs-it-self-service-tenant.event | 10 | AI Quickstarts |
| summit-2026.ai-lightning-fft-tenant.event | 9 | AI Lightning |
| summit-2026.ai-lightning-wordswarm-tenant.event | 6 | AI Lightning |
| summit-2026.ai-lightning-voice-agents-tenant.event | 6 | AI Lightning |

**AI Quickstarts** and **AI Lightning** are the most problematic catalog item families. The RHEL ZT lab is the single worst individual item with 36 failures.

## Summit Readiness — Event Controller View

**What's working**: 67+ Summit lab instances currently running (`started`) across 22 different lab types. Event controllers are healthy. Provisioning is active.

**What's concerning**:
- 49 Summit subjects in failed/destroyed state (vs 71 started) — a **40.8% failure rate** over the provisioning period
- AI Lightning labs have a near-100% failure rate — 24 failed, needs investigation
- Hummingbird tenant: 10 bulk failures 8-9 days ago
- destroy-failed is the dominant failure mode (127 of 197 total) — environments can't be cleaned up, which wastes resources

**Immediate questions**:
1. Are the destroy-failed environments consuming cluster resources? If so, they're competing with active labs.
2. Why did all AI Lightning tenant provisioning fail? Same root cause across 4 lab types.
3. Is the 40.8% historical failure rate expected (test iterations) or a problem?
