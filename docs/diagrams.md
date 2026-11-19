# StarGate — diagrams

Canonical, renderable diagrams (Mermaid, supported by GitHub and the Confluence
Mermaid macro). `docs/architecture.md` and `docs/workflows.md` embed the first
two; this file holds the full set, including the identity model.

---

## 1. Architecture

```mermaid
flowchart TB
  subgraph Sources["Sources — read-only"]
    C["5 OpenShift clusters<br/>ocpv05–ocpv09"]
    A["4 AAP controllers<br/>prod0, prod1, event0, event1"]
    J["Jira<br/>epic + tickets"]
    G["GitHub<br/>PRs, charts, catalog"]
    L["Labagator<br/>catalog, schedule, seats"]
    B["Babylon / Anarchy<br/>placement, state"]
    S["Sandbox API<br/>requests, assignments"]
  end

  subgraph Collect["Collection"]
    SCH["Scheduler + per-cluster workers<br/>5–15 min"]
    BAB["Babylon worker<br/>180 s"]
    ROT["Rotation sync<br/>30 min"]
    CRED["Credential / showroom probes"]
  end

  API["FastAPI ingestion<br/>runs · stages · evidence · evaluations"]
  DB[("PostgreSQL<br/>runs, evidence, evaluations,<br/>investigations, snapshots, mappings")]

  subgraph Engine["Evaluation and reasoning"]
    RUB["Rubric evaluator<br/>deterministic"]
    CLS["Failure classifier<br/>taxonomy + LLM, quality-gated"]
    INV["Investigation agent<br/>15 tools, causal chain"]
    ADJ["Adjudication<br/>blind review"]
    CAP["Capacity, demand, concentration"]
    KB["Knowledge base<br/>human-confirmed"]
  end

  subgraph Surfaces["Surfaces"]
    REST["REST API"]
    MCP["MCP server<br/>28 tools"]
    UI["React dashboard<br/>incl. Rotation"]
  end

  subgraph Consumers["Consumers"]
    ENG["Engineers / reviewers"]
    AG["External agents and skills"]
    EXT["Jira, Slack, tickets"]
  end

  Sources --> Collect --> API --> DB
  DB --> Engine
  Engine --> DB
  DB --> Surfaces
  MCP --> AG
  REST --> ENG
  UI --> ENG
  REST --> EXT

  classDef boundary fill:#fff3cd,stroke:#b8860b,color:#000
  class C,A,J,G,L,B,S boundary
```

**Boundary:** StarGate holds a read-only `cluster-reader` credential and never
reads Secrets. Credential verification is an external, time-boxed audit that
posts counts and hashes only.

---

## 2. Event workflow — detect → classify → investigate → verify

```mermaid
flowchart LR
  P["Provision request"] --> AN["AnarchySubject<br/>placement + lifecycle state"]
  AN --> SC["Scheduled scan"]
  SC --> EV["Evidence<br/>namespace, pods, deployments,<br/>routes, endpoints, VMs"]
  EV --> RE{"Rubric evaluation"}

  RE -->|pass| OK["Stage pass<br/>run completed"]
  RE -->|fail| FC["Failure class<br/>e.g. showroom_not_ready"]

  FC --> TR{"Transient?"}
  TR -->|yes| AR["Auto-resolve<br/>shadow mode, no action"]
  TR -->|no| INV["Investigation agent<br/>causal chain"]

  INV --> DX["Diagnosis<br/>root cause + remediation"]
  DX --> AD["Adjudication<br/>blind second opinion"]
  AD --> PA["Pending action<br/>queued for a human"]
  PA --> HU{"Human approves?"}
  HU -->|no| CL["Closed, rejected"]
  HU -->|yes| EX["Gated executor<br/>5 safety gates"]
  EX --> VE{"Verification eval"}
  VE -->|pass| KB["Knowledge base + receipt<br/>the fix is proven"]
  VE -->|fail| INV
```

---

## 3. Identity and joins

The three identifiers that make cross-source questions possible — and the
reason lab-level features need `lab_code` rather than run namespace.

```mermaid
flowchart LR
  GID["guid"] --> NS["sandbox namespace<br/>lab_code"]
  NS --> RUN["runs<br/>one per scan"]
  RUN --> EVI["evidence<br/>per resource"]
  RUN --> EVAL["evaluations<br/>per stage"]

  NS --> MAP["LabMapping<br/>catalog item, owner"]
  EVAL --> INV["investigations"]
  EVAL --> JIRA["Jira ticket<br/>rotation epic"]
  NS --> SHOW["showroom route<br/>URL + status"]
  EVAL --> MET["precision · recovery ·<br/>divergence · coverage"]
  EVI --> CTX["reproduction context<br/>URL, status, catalog"]
```

**Join keys:** `lab_code` (property), `run_id` (scan), `evidence.run_id`
(observations), `credential sha256[:16]` (values, never stored), `guid`
(provisioning identity).

---

## 4. Deployment topology

```mermaid
flowchart TB
  subgraph NS["namespace: stargate (infra01)"]
    FE["stargate-frontend<br/>nginx + SPA"]
    AP["stargate-api<br/>2 replicas"]
    PG[("stargate-postgres")]
    SCHD["stargate-scheduler<br/>scanner image"]
    BW["stargate-babylon-worker<br/>scanner image"]
  end
  REG["internal image registry<br/>api · frontend · scanner"]
  ROUTE["OpenShift Route + oauth-proxy"]
  CL["monitored clusters<br/>ocpv05–ocpv09"]

  ROUTE --> FE
  ROUTE --> AP
  FE --> AP
  AP --> PG
  SCHD --> AP
  BW --> AP
  SCHD --> CL
  REG -.images.-> AP
  REG -.images.-> SCHD
```
