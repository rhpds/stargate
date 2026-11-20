# Readiness evidence: observed versus unobserved

Readiness evaluations must distinguish an observed result from a check that
has not been performed. These rules apply to the local collector/evaluator
changes; they do not enable probes, deployment, or remediation.

## Observation contract

- `true` supports a passed criterion; `false` records an observed negative result.
- An explicitly present `null` records an unobserved or ambiguous result. It
  remains `null` in evaluation criteria and does not match a false-valued
  failure-class condition.
- Existing behavior for entirely absent criterion keys is unchanged. Producers
  must explicitly emit `null` when they know a check was not observed.
- Required observed failures still fail the stage. Otherwise an unobserved
  criterion, including an optional one, makes the evaluation `indeterminate`.
  It cannot silently certify the stage.

Known required failures take precedence over unknown entry criteria as well as
unknown exit criteria. An unknown entry does not stop inspection of the supplied
evidence; it remains indeterminate only when no required failure was observed.

The evaluation API keeps an indeterminate stage pending and emits
`evaluation.indeterminate`, not a passed/failed/warned event. Scanner namespace
aggregation requires a nonempty set of all-passed stage results before reporting
recovery. A known failed stage still takes precedence over unobserved stages.

The local pipeline simulator likewise promotes only pass/warn gate outcomes.
An indeterminate gate leaves the simulated pipeline `blocked`, retains its
indeterminate outcome, and skips downstream stages. This does not modify any
deployed pipeline definition.

CLI evaluation/collection commands return exit code `2` when a check is
indeterminate and no stage failed, rather than silently returning success.
They show `[?]` and include the indeterminate count in text summaries. Observed
stage failures retain exit code `1`; fully observed pass/warn runs retain `0`.

## Corrected evidence boundaries

Route admission and ready endpoints do not prove an HTTP response. The route
normalizer leaves `health_endpoint_returns_200` unobserved unless it is handed a
probe result, and it performs no network call itself. The generic smoke
normalizer likewise leaves its functional response and latency checks
unobserved.

`collectors/openshift/probe_route_health.py` is the approved probe collector for
that key. It issues one GET per Route, records the status line only, and carries
the same tri-state discipline as every other evidence key:

| Observation              | `health_endpoint_returns_200` | Why |
|--------------------------|-------------------------------|-----|
| 2xx or 3xx               | `true`                        | Something answered |
| 4xx/5xx                  | `false`                       | Something answered with an error |
| connection refused       | `false`                       | Nothing is listening |
| timeout                  | `null` (unobserved)           | The probe learned nothing |
| no Route host            | no probe emitted              | Nothing to request |

Redirects are not followed: an OAuth-protected route returning 302 is up, and
chasing it would leave the lab's host. No response body is read or retained.

A lab serves several routes (showroom, control, vscode, node02, bastion...), so
per-route results are combined existentially, not by taking the worst one:

| Probes for one namespace        | `health_endpoint_returns_200` |
|---------------------------------|-------------------------------|
| at least one 2xx/3xx            | `true`                        |
| none 2xx/3xx, at least one 4xx/5xx/refused | `false`            |
| only timeouts / DNS failures    | `null`                        |

The required criteria in `route-ready` are satisfied by ANY service or Route in
the namespace (`service_exists`, `route_exists`, `ready_endpoint_count > 0`), so
requiring every route to answer would hold the optional criterion to a stricter
test than the required ones. Measured on 48 live lab namespaces: "every route
answers" failed 25 of 48 — almost entirely routes whose backends the student is
meant to create (`app-`, `app-secure-`, `clab-report`, `bastion-443`) — while
"at least one route answers" passed 39 and failed the 9 where nothing answered
at all. A timeout does not drag down a namespace that already answered.

The probe is off by default. `cli/stargate.py collect-dir` runs it only when
`STARGATE_ROUTE_PROBE` is set (`1`/`true`/`yes`/`on`), and only for namespaces
whose Endpoints already report a ready address — a lab with nothing serving
already fails as `service_has_no_endpoints`, so spending the timeout there buys
no observation. `STARGATE_ROUTE_PROBE_TIMEOUT` (default 10s) bounds each
request. With the flag unset, collection remains read-only topology and
route-ready stays indeterminate, exactly as before.


An Anarchy job's `completeTimestamp` establishes termination, not success.
Explicit `successful` status supports success; explicit failed/error/canceled
status supports failure. Timestamp-only, running, malformed, or conflicting
attempt histories remain unverified. List histories do not guarantee chronology,
so mixed results are not resolved by arbitrarily picking a successful attempt.
An absent job history retains the existing negative result.

These checks establish automation evidence only. Handover data generation,
portal delivery, and successful user access require separate evidence. No
credentials, private infrastructure identities, or deployment configuration are
needed in these contracts or tests.

## Verification

Run the focused regression suite:

```bash
pytest tests/test_readiness_evidence_semantics.py tests/test_anarchy_provision.py tests/test_rubric_evaluator.py tests/test_api.py
```

The regressions cover failed-but-completed jobs, ambiguous histories, unrun
probes, observed success/failure, nullable API criteria, pending stage status,
non-failure events, and prevention of false scanner recovery. They use synthetic
local evidence and a local test database; no live cluster or model is required.

## Test isolation

The shared test configuration blocks unmocked Python subprocess execution,
socket connections, datagram sends, and DNS resolution. The guard remains active
through client and worker-thread teardown. An attempted external effect fails
test teardown even if application code caught the blocking exception. This is
a test-harness safeguard, not an operating-system security sandbox.

Tests must supply explicit transport/runner mocks. Chaos endpoint tests use
deterministic synthetic scenario results, including a failed scenario to check
receipt counts. They do not invoke the real deploy/classify/fix runner. Corpus,
GitHub, health, and delivery-error contract tests likewise supply their own
source results or synthetic transport errors.

The `external_block_expected` marker is only for tests asserting that the guard
blocks an operation; it never permits the operation. The workflow-matrix
meta-runner is marked `integration` because it launches child test processes
and is excluded from the in-process unit run. An integration marker does not
disable these guards. Live integration or chaos experiments require a separately
approved harness; this change provides no live-access bypass.

The cluster fallback test checks the mapping/copy contract using a synthetic
default mapping. It no longer assumes an arbitrary number of deployed clusters;
the scanner's configured cluster list is unchanged.

## Failure-catalog evidence contracts

Source-scoped failure lookup preserves each source's definition when two
catalogs use the same class name. Global lookup keeps its existing canonical
precedence and returns a deduplicated list. Source-specific views can therefore
overlap; their counts are not additive totals of unique classes. Reloading
clears both indexes so removed definitions do not survive as stale evidence.

Corpus statistics consume that list contract directly. The API regression
checks an actual corpus response rather than relying on router-file layout.
Subclass rules are validated as ordered pattern rules, separately from the
top-level failure-class catalog schema.

Approval tests retain the distinction between test-namespace proposals (hidden
from the operator queue) and visible proposals. Approving a visible proposal
still must respect recommend-only execution policy. GeoLux tests likewise
verify both eligible lab events and rejection of non-lab namespaces. These
test corrections do not broaden either approval or namespace permissions.

Configuration documentation checks runtime source directories, multiline reads,
and variable names containing digits. Commented optional assignments in
`.env.example` document settings without enabling them or supplying credentials.

## Image packaging

Historical operational files under `receipts/` are excluded from the container
build context and are not copied into either API image. Local files are retained;
this is not a deletion or a claim that already tracked history has been scrubbed.
The Summit report can still use its existing database snapshot fallback. Without
file assets or a database report it returns no historical report data, rather than
shipping old infrastructure evidence as application content. Regression tests use
an empty asset directory and mocked readers to check both fallback states.

Release verification must use the selected main-based candidate, not the entire
dirty checkout. Emulator-dependent tests also require an explicit pinned emulator
source; unrelated sibling-checkout edits are not part of a verified candidate.
