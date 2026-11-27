# StarGate Documentation

## Operating the platform

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System design, component interactions, data flow |
| [Reference Architecture](reference-architecture.md) | What is running in production today (as-is, dated) |
| [Diagrams](diagrams.md) | Architecture, event workflow, identity/joins, deployment topology |
| [Configuration](configuration.md) | Environment variables, tuning, deployment options |
| [Config Management](config-management.md) | The lighter path for config changes that are not releases |
| [Config Log](config-log.md) | Record of every config change, with why and how to revert |
| [Helm Reconciliation](helm-reconciliation.md) | Why the production Helm release is not the source of truth, and what closing that gap would cost |
| [Runbook](runbook.md) | Operational procedures, troubleshooting, common tasks |
| [Cluster Fleet](cluster-fleet.md) | The measured provisioning fleet, the scan gap, and the method |
| [Workflows](workflows.md) | Step-through event flow diagrams (scan → evaluate → investigate → review) |
| [Investigation Workflow](investigation-workflow.md) | The durable investigation lifecycle, budgets, and claim semantics |
| [Production Plan](stargate-production-plan.md) | Deployment architecture, scaling, monitoring |

## Intelligence surfaces

| Document | Description |
|----------|-------------|
| [Capacity Forecaster Plan](capacity-forecaster-plan.md) | The advisory forecaster: demand projection, supply evidence, and the authority gate's scope declaration |
| [Proof Lab Ecosystem](proof-lab-ecosystem.md) | Detection-to-proven auto-remediation pipeline |
| [Functional Alignment](functional-alignment-coverage.md) | Gate-by-gate implementation, test, deployment, and promotion status |
| [Frontend Redesign Plan](frontend-redesign-plan.md) | The question-first IA: six pages, drawers, verdict banners |

## Agent access (MCP)

| Document | Description |
|----------|-------------|
| [MCP Agent Guide](stargate-mcp-agent-guide.md) | Connecting an MCP-compatible agent: auth, tools, semantics, limits |
| [MCP Tool Cookbook](mcp-tool-cookbook.md) | Per-tool examples — what to ask, what each returns, worked sessions |

## Cascade (decision pending)

| Document | Description |
|----------|-------------|
| [Cascade Integration Design](cascade-integration-design.md) | The OSS/proof 2×2 integration design (status note: deepfield references are historical) |
| [Cascade Shadow Validation Plan](cascade-shadow-validation-plan.md) | Shadow-subject validation plan |
| [Cascade Phase 0 Backtest](cascade-backtest-2026-11.md) | The empirical results: hard gate PASS ×6, compression 46.8–84.7% |

## Integration & strategy

| Document | Description |
|----------|-------------|
| [GTM Strategy](gtm-strategy.md) | Go-to-market positioning, target users, rollout |
| [Pitch Kit](pitch-kit.md) | The 5-minute demo narrative and the numbers behind it |
| [Babylon Integration](post-summit-babylon-integration.md) | Babylon/Poolboy control plane integration |
| [Integration Findings](integration-findings.md) | Data source join reliability, gap analysis |
| [Evidence Observation Semantics](evidence-observation-semantics.md) | The tri-state evidence contract: observed / unobserved / indeterminate |
| [Taxonomy Registry Gap](taxonomy-registry-gap.md) | Proposed: one generated failure-class registry, enforced in CI (proposal) |

## Rotation page

| Document | Description |
|----------|-------------|
| [Rotation Contract](rotation-page/CONTRACT.md) | What the rotation page promises and what it refuses to claim |
| [Rotation Method](rotation-page/METHOD.md) | How rotation state is derived |
| [Rotation Rubric](rotation-page/RUBRIC.md) | Scoring rules for rotation credentials and tickets |
| [Rotation Daily Audit](rotation-page/DAILY-AUDIT.md) | The daily rotation check |
| [Rotation Evidence](rotation-page/EVIDENCE.md) | Evidence requirements for rotation claims |

## Point-in-time reports

| Document | Description |
|----------|-------------|
| [Incident Validation (Oct 2026)](incident-validation-2026-10.md) | Retrospective accuracy audit: detection 4/4, attribution gaps quantified |
| [Status Update (Nov 2026)](status-update-2026-11.md) | The November platform status |
| [Summary Refresh Release](summary-refresh-release.md) | The summary-refresh release procedure and writer handoff |
| [Handoff (19 Nov 2026)](handoff-2026-11-19.md) | One page of context for whoever picks the platform up next |
