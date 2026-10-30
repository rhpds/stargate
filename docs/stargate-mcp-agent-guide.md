# StarGate MCP Agent Guide

**Talk to the platform from any agent.** StarGate exposes its intelligence
surfaces through the Model Context Protocol (MCP) — any MCP-compatible agent
(Claude, Cursor, or your own) can query live lifecycle outcomes, causal
chains, the failure taxonomy, and the proof lab; ask questions in plain
English; and review diagnoses to build the platform's knowledge base.

- **Endpoint:** `https://stargate-api.apps.ocpv-infra01.dal12.infra.demo.redhat.com/mcp`
- **Protocol:** MCP Streamable HTTP (stateless, JSON responses)
- **Auth:** platform API key (`X-API-Key` header) — request one from the
  StarGate owners; never commit it to a repo or paste it in shared channels
- **Mode:** read + review. Query everything, review diagnoses, comment on
  actions. **No execution** — nothing runs on any cluster, no remediation
  is triggered, no infrastructure is touched.

---

## Connecting your agent

Most MCP clients accept a server config like:

```json
{
  "mcpServers": {
    "stargate": {
      "url": "https://stargate-api.apps.ocpv-infra01.dal12.infra.demo.redhat.com/mcp",
      "headers": {
        "X-API-Key": "YOUR-STARGATE-API-KEY"
      }
    }
  }
}
```

For Claude Code:
```bash
claude mcp add stargate \
  --transport http \
  --url https://stargate-api.apps.ocpv-infra01.dal12.infra.demo.redhat.com/mcp \
  --header "X-API-Key: YOUR-STARGATE-API-KEY"
```

For clients that need a command instead of a URL, wrap it with `mcp-remote`
or any Streamable-HTTP client shim; the endpoint speaks standard MCP
(initialize → tools/list → tools/call).

## The tools (11 total)

### Query tools (read-only)

| Tool | What it answers |
|---|---|
| **ask** | Anything, in plain English — grounded answers with cited sources; says when it doesn't know |
| **query_lifecycle_outcomes** | Provision/reclamation episodes for a workload: succeeded, failed, stalled, leaked |
| **list_reclamation_artifacts** | What a dying workload left behind: namespace, leaked PVs, placement, reclamation targets |
| **get_causal_chain** | The full evidence chain for an investigation: symptom → evidence → diagnosis → action → remediation → verification |
| **query_evaluations** | Recent evaluation history for a workload |
| **get_failure_classes** | The failure taxonomy: classes, patterns, severity, remediation guidance |
| **get_proof_matrix** | Proof-lab state: which failure classes are proven (remediation vs detection), gates, cycles |
| **get_recent_episodes** | Recent lifecycle episodes across the fleet |
| **get_cluster_saturation** | Which clusters show the capacity-saturation signature (rate spike + diverse symptoms + labs failing here while passing elsewhere), with severity and remediation guidance |

### Review tools (opinions only — no execution)

| Tool | What it does |
|---|---|
| **review_diagnosis** | Record your agreement or disagreement with an investigation's diagnosis. Approved diagnoses are published to the versioned knowledge base so future investigations benefit from what you've confirmed. |
| **comment_action** | Add a comment to a pending remediation action for the approver to see. Does NOT approve, reject, or execute anything. |

## Reviewing diagnoses

When you see an investigation's diagnosis (via `get_causal_chain` or `ask`),
you can review it:

```
review_diagnosis(
    investigation_id=2114,
    approved=true,
    notes="Yes, this matches what I've seen on ocpv07 — the CNV pods
           were stuck because of the storage class mismatch."
)
```

**What happens when you approve:**
- Your review is attributed to you (hashed key ID)
- If the investigation has a root cause and remediation suggestion, it's
  published to the **knowledge base** (versioned, attributed)
- Future investigations for the same failure class will reference your
  confirmed diagnosis as prior knowledge

**What happens when you reject:**
- The diagnosis is marked for re-examination
- It will NOT be used as reference knowledge

**What does NOT happen (ever):**
- No remediation is executed
- No cluster is touched
- No infrastructure is changed
- No approval queue item is approved

## Commenting on pending actions

When you see a pending remediation (via `get_causal_chain`), you can add
context for whoever eventually approves it:

```
comment_action(
    action_id=42,
    comment="I've seen this pattern before — the fix works but needs
             the pod to be recreated first, not just restarted."
)
```

Your comment is visible to the approver in the dashboard. It does NOT
approve, reject, or execute anything.

## Performance

The `ask` tool has three response tiers:

| Question type | Response time |
|---------------|--------------|
| Simple taxonomy lookup ("what is X?") | **Instant** (no LLM — the retrieved entry is the answer) |
| Complex questions (first ask) | **~2 seconds** (qwen3-14b synthesis with cited sources) |
| Any question asked twice | **Instant** (5-minute cache) |

The synthesis model is configurable via `STARGATE_ASK_MODEL`
(default: `qwen3-14b`).

## Example sessions

### "What happened to my lab?"

> **You:** "Did sandbox-abc123 get reclaimed, and did anything leak?"
>
> **StarGate:** "Lifecycle outcomes for sandbox-abc123: destroy-complete |
> PASS | reclaimed | AAP destroy job 12345 succeeded. Reclamation
> artifacts: namespace gone, leaked PVs: none found. [source: gap-reclaim-...]"

### "Review a diagnosis"

> **You:** "Show me the causal chain for the latest investigation"
>
> **StarGate:** (returns the full chain with diagnosis and verdict)
>
> **You:** "review_diagnosis for that investigation — approved, this
>            matches what I've seen"
>
> **StarGate:** "Review recorded: APPROVED. Published to knowledge base
>                as sandbox-xyz:teardown_stuck v1. Future investigations
>                will reference this diagnosis."

### "What's the platform's health?"

> **You:** "What is the StarGate platform?"
>
> **StarGate:** "StarGate is a lifecycle intelligence platform for the
>                Red Hat Demo Platform (RHDP). It monitors lab environments
>                across multiple OpenShift clusters... [source: doc:platform-overview]"

## Answer semantics (what the platform guarantees)

- **Grounded answers**: the `ask` tool answers only from retrieved platform
  context and cites its sources (`[source: ...]`). When the context does not
  answer the question, it says what is missing — it does not guess.
- **Evidence discipline**: lifecycle outcomes distinguish *observed* from
  *unobserved*; a PASS reclamation outcome means an explicit destroy-job
  success or corroborated disappearance, never an inference. A FAILED
  destroy is a finding, not staleness.
- **Provenance**: causal chains are complete only when a verification eval
  proved resolution; `missing_legs` reports exactly what is not yet proven.
- **Review attribution**: your reviews are recorded with your hashed key ID;
  knowledge entries show who confirmed them.

## Security model

1. **API key required** — constant-time comparison, per-key rate limit
   (60 requests/minute), 401/429 otherwise. Per-user keys available via
   `STARGATE_ADDITIONAL_API_KEYS`. Store in your agent's secret store.
2. **Read + review, never execute** — query tools are read-only. Review
   tools write opinions to the feedback and knowledge tables only. There
   is NO tool that executes anything, touches a cluster, or triggers
   remediation. The execution boundary (dashboard approval + GeoLux
   precheck + gated executor) is unchanged.
3. **Audited** — every MCP request is logged (method, tool, hashed key id)
   in the platform logs; reviews are attributed; abuse is traceable.
4. **Transport** — TLS via the OpenShift route; the `/mcp` path bypasses
   the browser OAuth flow (agents have no cookies) and relies solely on
   the API key. Request bodies are capped at 4 MiB.
5. **Data exposure** — tools return operational data (namespaces, failure
   classes, messages). oc-based outputs pass the platform's redaction
   layer. Do not paste answers containing sandbox names into public
   channels if your event's naming is sensitive.

## Limitations (honest)

- `ask` synthesis uses the platform's production LLM (metered under
  `mcp-ask`, model: qwen3-14b); if the LLM is unreachable, you still get
  the retrieved context without synthesis.
- The knowledge corpus covers the taxonomy (91 classes), 9 doc files
  (workflows, architecture, runbook, etc. — 165+ sections), and a
  platform overview — it does not include every historical investigation;
  ask `get_causal_chain` for those.
- Rate limits are per-key and shared across your agent's sessions.
- MCP sessions are stateless: every call is independent; there is no
  conversation memory server-side (your agent holds the conversation).
- Review tools require the investigation to have a root_cause to publish
  to the knowledge base; investigations without a diagnosis are recorded
  but not published.

## Getting a key

Ask the StarGate owners for a platform API key. Keys are rotated by
re-deploying the `stargate-secrets` Secret; if you suspect a key has
leaked, report it immediately — the rate limit bounds scraping but does
not prevent data reads with a valid key.

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| 401 Unauthorized | Missing or wrong API key | Check the `X-API-Key` header |
| 405 Method Not Allowed | Wrong path (no trailing slash) | Use `/mcp/` not `/mcp` |
| 429 Too Many Requests | Rate limit (60/min) | Wait 60 seconds |
| Empty answer from `ask` | Question didn't match any context | Try naming a workload, failure class, or asking about provisioning/reclamation/proofs |
| Slow first answer | LLM synthesis in progress | Normal — ~2 seconds; cached on repeat |
| "already reviewed" | Investigation was previously approved | This is correct behavior — the review is already published |
| "no root_cause" on review | Investigation has no diagnosis | The review is recorded but nothing is published to the knowledge base |
