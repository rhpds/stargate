# StarGate: Go-to-Market Strategy

## Bring Your Own Infrastructure. Bring Your Own Policy. Bring Your Own Model.

---

## What StarGate Is

StarGate is an AI-driven operational intelligence platform for OpenShift. It continuously monitors cluster health, evaluates workload readiness against configurable rubrics, generates evidence-based recommendations, and executes remediation actions through a gated approval pipeline.

It is not a product tied to one team's infrastructure. It is a repeatable pattern that any OpenShift operator can deploy into their environment with their own policies and their own models.

---

## The Problem

Every OpenShift operations team builds the same thing differently:
- Custom monitoring scripts that break when someone leaves
- Spreadsheets tracking lab/workload readiness that go stale
- Tribal knowledge about which cluster is overloaded and why
- Manual remediation runbooks that nobody follows consistently
- No feedback loop between what was recommended and what actually worked

The result: incidents that could have been predicted, actions that should have been automated, and knowledge that walks out the door.

---

## The Pattern

StarGate establishes a repeatable operational pattern:

```
OBSERVE → EVALUATE → RECOMMEND → EXECUTE → VERIFY → LEARN
```

Each step is pluggable:

| Step | What It Does | What You Bring |
|---|---|---|
| **Observe** | Collect cluster state (nodes, pods, VMs, pools, telemetry) | Your OpenShift clusters |
| **Evaluate** | Score evidence against rubrics (pass/fail/warn per criterion) | Your rubric definitions |
| **Recommend** | Generate prioritized actions with confidence scores | Your policy engine rules |
| **Execute** | Run remediation with dry-run, confidence gate, approval queue | Your approval workflow |
| **Verify** | Re-evaluate after action to confirm resolution | Your acceptance criteria |
| **Learn** | Feed outcomes back to improve future recommendations | Your operational history |

---

## Three Pillars

### 1. Bring Your Own Infrastructure

StarGate deploys on any OpenShift 4.x cluster. It needs:
- One namespace for the platform (API + scanner + database)
- Read-only service accounts on target clusters
- Optional: write service accounts for execution (Phase D)

**What you configure:**
- `STARGATE_CLUSTERS` — which clusters to scan
- Kubeconfig per cluster with appropriate SA tokens
- Scan tier intervals (how often to check nodes, pods, namespaces)

**What you don't change:**
- The scanner architecture (tiered, staggered, delta-based)
- The evidence collection pipeline
- The evaluation framework

StarGate has been proven on 8 production clusters simultaneously, scanning 5000+ VMs, 1700+ sandboxes, 185 nodes, with sub-second API response times.

### 2. Bring Your Own Policy

Policies are YAML files that define what "healthy" means for your environment.

**Rubrics** define per-stage pass/fail criteria:
```yaml
id: deployment-ready
version: v1.0.0
stage: Deployment Readiness
exit_criteria:
  - name: namespace_exists
    required: true
  - name: deployment_exists
    required: true
  - name: desired_replicas_ready
    required: true
  - name: no_crashloop_pods
    required: true
failure_classes:
  pods_not_ready:
    when:
      - desired_replicas_ready == false
    recommended_action: inspect_pod_status
  pods_crashlooping:
    when:
      - no_crashloop_pods == false
    recommended_action: inspect_pod_logs
```

**Policy rules** define what actions to recommend:
```python
# If sessions scheduled but no provisioning → critical
if lab.sessions > 0 and lab.instances_started == 0:
    recommend("provision_blocked_lab", urgency="critical")

# If CPU > 70% on any cluster → medium
if cluster.avg_cpu > 70:
    recommend("cluster_capacity", urgency="medium")
```

**Remediation catalog** maps failure classes to diagnostic commands:
```yaml
- id: inspect_pod_logs
  risk: low
  mode: recommend_only
  allowed_when:
    - failure_class == pods_crashlooping
  commands:
    - "oc logs -n {namespace} --previous {pod}"
    - "oc get events -n {namespace} --sort-by=.lastTimestamp"
```

Teams write their own rubrics, policies, and remediation entries. StarGate evaluates them.

### 3. Bring Your Own Model

StarGate's LLM integration is model-agnostic. It uses a standard OpenAI-compatible chat completions API.

**What you configure:**
```bash
STARGATE_LITELLM_URL=https://your-llm-endpoint/v1/chat/completions
STARGATE_LLM_MODEL=your-model-name
STARGATE_LITELLM_API_KEY=your-api-key
```

**What works today:**
- Granite 3.2 8B Instruct on Intel Gaudi via LiteLLM
- Any model behind a LiteLLM proxy (Llama, Mistral, Claude, GPT)
- Self-hosted models on Gaudi, Xeon, GPU, or CPU

**What the model does:**
- Classifies unrecognized failure patterns
- Generates remediation analysis with evidence context
- Produces executive readiness summaries
- All calls instrumented with token/cost/latency metrics
- Prompt versioning for A/B comparison between models

**What the model does NOT do:**
- Make execution decisions (policy engine does that)
- Bypass the confidence gate
- Execute without audit trail

The model advises. The policy decides. The gate approves. The executor acts.

---

## Deployment Model

### Minimal (monitoring only)
```
1 namespace, 1 pod (API + scanner), 1 Postgres PVC
Scanner SA with cluster-reader on target clusters
No LLM required — rubric evaluation is deterministic
```

### Standard (monitoring + AI analysis)
```
+ LLM endpoint (LiteLLM, vLLM, or any OpenAI-compatible API)
+ Prometheus metrics scraping
+ Dashboard for operations team
```

### Full (monitoring + AI + execution)
```
+ Executor SA with namespace-scoped write permissions
+ Approval queue with HITL gate
+ Slack/webhook notifications for pending approvals
+ Synthetic emulator for pre-production validation
+ Mock cluster for command validation
```

### Enterprise (multi-cluster, multi-team)
```
+ Per-team rubric configurations
+ Per-cluster execution policies
+ Federated scanning across environments
+ Centralized LLM with per-team prompt versioning
+ Role-based access control on approval queue
```

---

## Gated Execution: The Trust Ladder

StarGate doesn't ask for write access on day one. It earns trust through a gated progression:

```
Phase A: Shadow Mode (emulator)
  Prove: LLM recommendations are correct against synthetic scenarios
  Gate: 100% of scenarios resolve after simulated action
  Evidence: test-receipts/ with before/after outcomes

Phase B: Mock Cluster
  Prove: Generated oc commands are valid and safe
  Gate: 100% of commands validate against mock API
  Evidence: Command audit log, state diffs

Phase C: Test Namespace
  Prove: Real execution works with rollback safety net
  Gate: Create/scale/delete succeed, rollback restores state
  Evidence: Real oc command output, before/after snapshots

Phase D: Production with Approval Gate
  Prove: Human-approved actions execute correctly at scale
  Gate: Confidence > threshold, human approval, audit complete
  Evidence: AuditLog entries, approval records, resolution tracking
```

Each gate must pass before advancing. Receipts from each gate are the evidence for the next.

---

## Repeatable Process: The Red Hat Way

### For any new environment:

**Week 1: Deploy + Observe**
```bash
# Deploy StarGate
helm install stargate deploy/helm/stargate/ -n stargate \
  --set scanner.clusters=cluster1,cluster2,cluster3

# Create read-only scanner SA on each target cluster  
oc create serviceaccount stargate-scanner -n default
oc adm policy add-cluster-role-to-user cluster-reader -z stargate-scanner

# Start scanning
curl -X POST /admin/scheduler/start
```

**Week 2: Customize + Evaluate**
```bash
# Write your rubrics
vim rubrics/platform/my-app-ready.yaml

# Write your policy rules
vim engine/policy.py  # or load from configurable YAML (future)

# Connect your LLM
export STARGATE_LITELLM_URL=https://my-llm/v1/chat/completions
export STARGATE_LLM_MODEL=my-preferred-model
```

**Week 3: Validate + Gate**
```bash
# Run synthetic scenarios against your rubrics
curl -X POST /admin/validate

# Run feedback loop to prove recommendations work
python -m emulator.cli run-all --dry-run

# Generate receipts as evidence
python scripts/generate-receipts.py
```

**Week 4: Execute + Learn**
```bash
# Create executor SA (test namespace first)
oc new-project stargate-test
oc create serviceaccount stargate-executor -n stargate-test

# Enable execution against test namespace
export STARGATE_EXECUTION_TARGET=test

# Monitor, approve, learn
# Dashboard → Admin → Approval Queue
```

This 4-week onboarding is documented, scripted, and tested. Any team can follow it.

---

## Transition to Agentic

### Where We Are Today

StarGate is a **tool-augmented pipeline** — human-designed policies trigger LLM analysis, which produces recommendations that a human approves.

```
Human designs policy → Policy triggers on evidence → LLM advises → Human approves → Executor acts
```

### Where We're Going

StarGate becomes an **agentic system** — autonomous agents observe, reason, plan, and act within defined safety boundaries.

### The Agentic Architecture

```
┌─────────────────────────────────────────────────────┐
│                   AGENT SUPERVISOR                    │
│  Orchestrates agent lifecycle, enforces boundaries   │
├─────────────────────────────────────────────────────┤
│                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Observer  │  │ Analyst  │  │ Executor │           │
│  │  Agent    │  │  Agent   │  │  Agent   │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │              │              │                 │
│  Watches cluster  Reasons over   Plans + executes    │
│  state changes    evidence       remediation         │
│  continuously     with LLM       with rollback       │
│                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Learner  │  │ Planner  │  │ Router   │           │
│  │  Agent   │  │  Agent   │  │  Agent   │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │              │              │                 │
│  Analyzes feedback  Sequences     Routes workloads   │
│  adjusts confidence multi-step    Gaudi vs Xeon6     │
│  recalibrates       actions       vs CPU vs GPU      │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### Agent Types

**Observer Agent**
- Today: Tiered scanner runs on fixed intervals
- Agentic: Agent decides what to scan based on anomaly signals. If CPU is spiking, increase scan frequency. If cluster is stable, reduce to save API calls. Watches for state changes and triggers analysis only when something meaningful shifts.

**Analyst Agent**
- Today: Rubric evaluation is deterministic, LLM provides supplementary analysis
- Agentic: Agent reasons over evidence holistically. Correlates across clusters, identifies root causes spanning multiple failure classes, generates multi-step remediation plans. Uses chain-of-thought reasoning to explain its analysis. Can request additional evidence collection if it needs more data to be confident.

**Executor Agent**
- Today: Single action execution with rollback
- Agentic: Agent plans multi-step remediation sequences. "First scale the pool, then restart the failed pods, then verify the showroom is healthy, then check the deployment replicas." Each step verified before proceeding to the next. Can abort and rollback the entire sequence if any step fails.

**Learner Agent**
- Today: Feedback stored, calibration calculated
- Agentic: Agent continuously monitors its own performance. Detects when confidence calibration drifts. Proposes prompt modifications when classification accuracy drops. Identifies failure patterns that rubrics don't cover and proposes new rubric criteria. Learns from every human correction.

**Planner Agent**
- Today: Policy engine generates independent recommendations
- Agentic: Agent considers resource constraints, scheduling conflicts, and blast radius before proposing actions. "If I scale this pool, it will consume capacity from that pool. If I restart these pods, the VMs on that node will be affected." Plans actions that don't create new problems.

**Router Agent**
- Today: Substrate router decides Gaudi vs Xeon6
- Agentic: Agent monitors real-time utilization across all compute substrates. Proactively migrates workloads before saturation. Predicts demand based on session schedule and historical patterns. Balances cost, latency, and availability across heterogeneous hardware.

### The Transition Path

**Phase 1: Tool-Using Agents (near-term)**
Current architecture with agents that use StarGate's existing tools (scanners, evaluators, executors) as callable functions. The agent decides WHEN to call each tool, not just responding to triggers.

```python
class AnalystAgent:
    tools = [evaluate_rubric, call_llm, query_evaluations, get_blast_radius]
    
    def analyze(self, event):
        # Agent decides which tools to invoke and in what order
        evidence = self.tools.query_evaluations(lab_code=event.lab_code)
        if len(evidence) < 5:
            self.tools.evaluate_rubric(...)  # Request more data
        analysis = self.tools.call_llm(context=evidence)
        return analysis
```

**Phase 2: Collaborative Agents (mid-term)**
Multiple agents communicate through the event bus. Observer detects anomaly → notifies Analyst → Analyst requests more data from Observer → produces recommendation → Executor plans sequence → Learner tracks outcome.

```python
class AgentSupervisor:
    agents = [ObserverAgent, AnalystAgent, ExecutorAgent, LearnerAgent]
    
    def run(self):
        while True:
            events = self.event_bus.get_pending()
            for event in events:
                agent = self.route_to_agent(event)
                result = agent.process(event)
                if result.requires_action:
                    self.event_bus.emit(result.as_event())
```

**Phase 3: Autonomous Agents (long-term)**
Agents operate continuously with minimal human intervention. The supervisor enforces safety boundaries — maximum actions per hour, mandatory approval for destructive operations, automatic rollback on verification failure. Humans set policy; agents execute within policy.

```python
class SafetyBoundary:
    max_actions_per_hour = 10
    require_approval_for = ["delete", "scale_down", "pool_resize"]
    auto_rollback_on_failure = True
    confidence_floor = 0.7  # Never auto-execute below this
    
    def check(self, proposed_action):
        if proposed_action.type in self.require_approval_for:
            return ApprovalRequired(reason="destructive action")
        if proposed_action.confidence < self.confidence_floor:
            return ApprovalRequired(reason="low confidence")
        if self.actions_this_hour >= self.max_actions_per_hour:
            return RateLimited(reason="hourly limit reached")
        return Approved()
```

### What Changes, What Doesn't

| Component | Today | Agentic | Changes? |
|---|---|---|---|
| Evidence collection | Tiered scanner | Observer agent with adaptive frequency | Behavior changes, infrastructure same |
| Rubric evaluation | Deterministic | Deterministic (agents don't change rubrics) | No change |
| Policy engine | Rule-based | Planner agent with constraint reasoning | Logic moves to agent |
| LLM integration | 3 fixed call patterns | Analyst agent with dynamic tool selection | More flexible, same API |
| Execution | Single action + rollback | Executor agent with multi-step planning | Sequences, same primitives |
| Feedback | Manual calibration | Learner agent with continuous adaptation | Automated, same data |
| Safety gates | Confidence threshold + approval | Safety boundary with rate limits + blast radius | Stronger, same principle |
| Audit trail | Every action logged | Every agent decision logged | More granular, same DB |

### The Key Insight

The agentic transition doesn't require rebuilding StarGate. It requires **promoting existing components to agent status**:

- The scanner becomes the Observer Agent's body
- The rubric evaluator becomes the Analyst Agent's tool
- The action executor becomes the Executor Agent's hands
- The feedback loop becomes the Learner Agent's memory
- The event bus becomes the agent communication channel
- The audit log becomes the agent decision record

The infrastructure, the safety gates, and the evidence pipeline stay the same. What changes is who decides when to invoke them — from static schedules and human triggers to autonomous agents operating within defined boundaries.

---

## Summary

StarGate is:
- **Deployable** on any OpenShift cluster in 4 weeks
- **Configurable** with your rubrics, policies, and models
- **Provable** through gated execution with receipts at every stage
- **Extensible** from monitoring → AI analysis → gated execution → autonomous agents

The Red Hat way: open, repeatable, and trust-earned — not trust-assumed.
