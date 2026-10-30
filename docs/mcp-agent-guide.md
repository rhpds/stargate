# StarGate MCP Agent Guide

**Talk to the platform from any agent.** StarGate exposes its intelligence
surfaces through the Model Context Protocol (MCP) — any MCP-compatible agent
(Claude, Cursor, or your own) can query live lifecycle outcomes, causal
chains, the failure taxonomy, and the proof lab, or just ask questions in
plain English.

- **Endpoint:** `https://YOUR-STARGATE-API-ROUTE/mcp`
- **Protocol:** MCP Streamable HTTP (stateless, JSON responses)
- **Auth:** platform API key (`X-API-Key` header) — request one from the
  StarGate owners; never commit it to a repo or paste it in shared channels
- **Mode:** strictly read-only. No tool mutates anything, nothing executes,
  no remediation authority of any kind.

---

## Connecting your agent

Most MCP clients accept a server config like:

```json
{
  "mcpServers": {
    "stargate": {
      "url": "https://YOUR-STARGATE-API-ROUTE/mcp",
      "headers": {
        "X-API-Key": "YOUR-STARGATE-API-KEY"
      }
    }
  }
}
```

For clients that need a command instead of a URL, wrap it with `mcp-remote`
or any Streamable-HTTP client shim; the endpoint speaks standard MCP
(initialize → tools/list → tools/call).

## The tools

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

## Example questions (via `ask` or your agent's tool use)

- "Did sandbox-abc123 get reclaimed, and did anything leak?"
- "What does teardown_stuck mean and how is it fixed?"
- "Show me the causal chain for the last investigation of sandbox-xyz"
- "Which failure classes are proven in the proof lab, and which are only detection-proven?"
- "What provisioning failures happened in the last day?"

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

## Security model

1. **API key required** — constant-time comparison, per-key rate limit
   (60 requests/minute), 401/429 otherwise. The key is the same admin key
   used for the REST API; treat it as a credential: store it in your
   agent's secret store, rotate via the StarGate owners, and never log it.
2. **Read-only by construction** — every tool is a query. There is no
   write, execute, or remediation tool on this server. Agents cannot
   change anything on any cluster.
3. **Audited** — every MCP request is logged (method, tool, hashed key id)
   in the platform logs; abuse is traceable.
4. **Transport** — TLS via the OpenShift route; the `/mcp` path bypasses
   the browser OAuth flow (agents have no cookies) and relies solely on
   the API key. Request bodies are capped at 4 MiB.
5. **Data exposure** — tools return operational data (namespaces, failure
   classes, messages). oc-based outputs pass the platform's redaction
   layer. Do not paste answers containing sandbox names into public
   channels if your event's naming is sensitive.

## Limitations (honest)

- `ask` synthesis uses the platform's production LLM (metered under
  `mcp-ask`); if the LLM is unreachable, you still get the retrieved
  context without synthesis.
- The knowledge corpus is the taxonomy plus key docs — it does not include
  every historical investigation; ask `get_causal_chain` for those.
- Rate limits are per-key and shared across your agent's sessions.
- MCP sessions are stateless: every call is independent; there is no
  conversation memory server-side (your agent holds the conversation).

## Getting a key

Ask the StarGate owners for a platform API key. Keys are rotated by
re-deploying the `stargate-secrets` Secret; if you suspect a key has
leaked, report it immediately — the rate limit bounds scraping but does
not prevent data reads with a valid key.
