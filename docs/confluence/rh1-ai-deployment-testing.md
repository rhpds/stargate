# RH1 — AI deployment testing from a clean dev snapshot
# Confluence ID: 503780477
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/503780477

RH1 — Run deployment testing from a clean dev snapshot
 Minimal snapshot rules for AI and reviewers
 test.yaml contains only dev overrides beyond inherited common/account/include settings, necessary snapshot pins, and approved test identity, access, routing and placement exceptions. Do not flatten merged dev output into test files. Keep merged output private as comparison evidence.
 Reuse existing per-CI tags when their resolved commits match the required dev source. Create a new tag only for changed source or a missing required snapshot. Never move existing tags or create replacements just to rename/date them.

 Pin the shared component that executes automation. Do not add redundant deployer pins to wrappers that only delegate to that component.

 Leave unchanged common settings inherited. For catalog parameters, include only changed named entries, retaining the complete schema and metadata of each changed entry. Check real merge behavior: inherited AAP instance groups can be appended twice.

 Run AgnosticV merge/schema validation and compare effective dev/test values with reviewed exceptions and equivalent reference pins. Inspect every added setting: it must be a dev delta, a necessary pin, or an approved test exception. Review large diffs for copied common data.

 Update only existing test files. Keep operational guides local and in Confluence, outside AgnosticV configuration PRs unless explicitly requested. Common and other shared dependencies remain inherited; do not claim every transitive dependency is frozen.

 Validate live Babylon reconciliation after merge before ordering. Configuration validation does not prove a deployment or a Showroom fix.

 Description of entry point
 Use this runbook to start a new RH1 deployment test run using AI. The test measures whether the approved snapshot deploys successfully through Babylon. It does not certify completion of the lab exercises.
 The historical October 2026 test run exposed stale runtime versions, incorrect physical-cluster selectors, unintended tenant placement, and differing controller routes. Its results are historical evidence; they must not silently become the baseline for a new run.
 Start condition: every selected existing test CI has been refreshed and validated using Create and refresh test snapshots from dev , all required PRs are merged, and Babylon has reconciled their effective configuration. If this condition is not met, prepare the snapshot PRs and report the blocker before ordering.
 Prerequisites and inputs
 Input
 Current RH1 value or rule

 Tracker
 Example: Deployment Testing sheet 

 Catalog items
 Column C; resolve the current test CI and store its plain name in E. Verify the header and row identity before every write.

 Jira tickets
 Column D; read the ticket before testing to capture lab-specific requirements. Do not assume comment permission.

 Order endpoint
 https://babylon-catalog.apps.ocp-us-west-2.infra.open.redhat.com/ ; do not order through catalog.demo.redhat.com .

 Babylon API access
 Explicit --kubeconfig=$HOME/secrets/babylon-west.kubeconfig , or another verified authorized west kubeconfig. Never rely on the default context.

 Ordering
 Official Babylon CLI ; inspect installed help/authentication and verify the connected account before using it. Never print credentials.

 Spreadsheet access
 gws ; inspect current headers and use API-supported hyperlinks/rich text for URLs.

 Scope
 Existing test YAMLs for the sheet's selected RH1 CIs and their actual shared dependencies. Do not invent missing test CIs. Inventory may change; do not hardcode the previous count as an ordering list.

 Users per order
 One user; two only when the CI requires it. Inspect the live catalog parameter schema.

 Retry limit
 Three total attempts per CI per configuration cycle.

 Durable state
 A private persistent directory supplied for this run, outside Git and outside /tmp . Back it up.

 Babylon CLI setup and execution engine
 Commands below were checked against Babylon CLI v0.44.11. Record the version used for each run and inspect help when upgrading. The CLI performs catalog/service operations; the AI runner owns the durable ledger, dependency gates, retry decisions, reporting, and cleanup verification. Do not create ResourceClaims directly to bypass the CLI.
 Install or verify the CLI
 If Babylon is already installed, run babylon version and babylon service order --help . Otherwise install a reviewed release asset for your platform. This example pins the verified release rather than silently selecting a newer version.

 set -e
BABYLON_VERSION=v0.44.11
case "$(uname -s)/$(uname -m)" in
 Darwin/arm64) BABYLON_ASSET=babylon-darwin-arm64 ;;
 Darwin/x86_64) BABYLON_ASSET=babylon-darwin-amd64 ;;
 Linux/aarch64|Linux/arm64) BABYLON_ASSET=babylon-linux-arm64 ;;
 Linux/x86_64) BABYLON_ASSET=babylon-linux-amd64 ;;
 *) printf 'Select the correct release asset manually.\n'; exit 1 ;;
esac
BABYLON_DOWNLOAD="$(mktemp -d)"
gh release download "$BABYLON_VERSION" --repo redhat-cop/babylon \
 --pattern "$BABYLON_ASSET" --pattern sha256sums.txt --dir "$BABYLON_DOWNLOAD"

# Verify just the downloaded binary against the release checksum manifest.
python3 - "$BABYLON_DOWNLOAD" "$BABYLON_ASSET" <<'PY'
import hashlib, pathlib, sys
directory, asset = pathlib.Path(sys.argv[1]), sys.argv[2]
expected = None
for line in (directory / "sha256sums.txt").read_text().splitlines():
 digest, name = line.split(maxsplit=1)
 if name.lstrip("*").removeprefix("./") == asset:
 expected = digest.lower()
if expected is None:
 raise SystemExit("Asset absent from checksum manifest")
actual = hashlib.sha256((directory / asset).read_bytes()).hexdigest()
if actual != expected:
 raise SystemExit("Checksum mismatch: do not install")
print("Checksum verified")
PY
# Run installation only after checksum verification succeeds.
mkdir -p "$HOME/.local/bin"
install -m 0755 "$BABYLON_DOWNLOAD/$BABYLON_ASSET" "$HOME/.local/bin/babylon"
export PATH="$HOME/.local/bin:$PATH"
babylon version

 Expected output: checksum verification succeeds and the binary reports the selected version. Add $HOME/.local/bin to your shell PATH if needed. Windows has a separate babylon-windows-amd64.exe asset.
 Configure west authentication
 Babylon CLI authentication is separate from Kubernetes authentication. The CLI does not consume a kubeconfig from ~/secrets . In this release it requires both its Babylon session token and OAuth proxy cookies, obtained by browser login. Use the catalog web URL, not the Kubernetes API URL or an invented API endpoint.

 BABYLON_SERVER_URL='https://babylon-catalog.apps.ocp-us-west-2.infra.open.redhat.com'
BABYLON_CONFIG="$HOME/.config/babylon/west.yaml"
mkdir -p "$HOME/.config/babylon"
chmod 700 "$HOME/.config/babylon"
babylon --config "$BABYLON_CONFIG" login "$BABYLON_SERVER_URL"
chmod 600 "$BABYLON_CONFIG"

 Run login on the workstation where the browser and CLI can reach each other. Authenticate to west using the intended test account.

 The CLI starts a local callback listener, opens the browser, and waits up to five minutes. If the browser does not open, use the exact URL printed by the running command. For an AI agent, pause for the human to complete SSO; never request their password.

 Wait for the terminal to report Logged in as ... and for login to exit successfully. The browser's confirmation alone does not prove the credentials were saved.

 Reuse this same config path on every command. The default, if omitted, is $XDG_CONFIG_HOME/babylon/config.yaml or ~/.config/babylon/config.yaml . A dedicated west file avoids unintentionally reusing another cluster's session. In v0.44.11 the printed “Config saved” path may show the default even with a custom path; verify that your specified file exists without printing its contents.

 The generated config contains server and auth.user , plus sensitive auth.token and auth.cookies . Optional fields include namespace , output , and insecure . Let login populate credentials; do not paste tokens, copy the file into the ledger, or commit it. Normal west login uses TLS verification; do not add --insecure as a default.
 Validate account, catalog, and namespace before ordering

 # Use the namespace verified for the logged-in account.
BABYLON_NAMESPACE='user-<verified-account>'
babylon --config "$BABYLON_CONFIG" --server "$BABYLON_SERVER_URL" \
 --namespace "$BABYLON_NAMESPACE" service list
babylon --config "$BABYLON_CONFIG" --server "$BABYLON_SERVER_URL" \
 catalog list
babylon --config "$BABYLON_CONFIG" --server "$BABYLON_SERVER_URL" \
 catalog describe '<account>.<catalog-item>.test'

 Confirm login identifies the intended owner, the namespace matches that owner's catalog account, and the exact test CI is visible. An empty service list is valid and does not by itself prove ownership. Without an explicit namespace the CLI uses the session's user namespace; flags override environment/config values. For this historical run the namespace was user-prutledg-redhat-com ; do not reuse it for another user. Specifying a namespace does not grant access to it.
 Inspect the live parameter schema. Use one user, or two only if required. The parameter name is CI-specific; do not assume every CI accepts num_users or num_users_param . The order --purpose QA is an order/business-purpose value, not a change to the Sandbox API cloud_selector.purpose .
 CLI command contract for the runner
 Operation
 Command after shared --config/--server/--namespace flags
 Expected result / runner responsibility

 Discover
 catalog list -o json
 Inventory visible items; select the exact approved .test item.

 Inspect
 catalog describe <ci> -o json
 Inspect parameter schema and current catalog definition before ordering.

 Order
 service order <ci> --purpose QA --param <name>=<value> -o json
 Returns a claim object. Save metadata.name, metadata.namespace and metadata.uid; successful submission is not deployment success.

 Observe
 service status <exact-service-name> -o json
 Inspect status.summary.state and component evidence. Anarchy active action/run checks remain necessary.

 Reconcile ambiguous response
 service list -o json
 Match ownership, creation time, exact CI and recorded intent; never blindly issue another order.

 Retire
 service retire <exact-service-name>
 Sets lifespan end to now. Record retirement intent/outcome and verify eventual claim/subject deletion separately.

 # Examples only: invoke after snapshot/dependency and ownership gates pass.
babylon --config "$BABYLON_CONFIG" --server "$BABYLON_SERVER_URL" \
 --namespace "$BABYLON_NAMESPACE" service order '<exact-test-ci>' \
 --purpose QA --param '<schema-parameter>=<value>' -o json

babylon --config "$BABYLON_CONFIG" --server "$BABYLON_SERVER_URL" \
 --namespace "$BABYLON_NAMESPACE" service status '<returned-service-name>' -o json

# After results are captured and cleanup is authorized:
babylon --config "$BABYLON_CONFIG" --server "$BABYLON_SERVER_URL" \
 --namespace "$BABYLON_NAMESPACE" service retire '<exact-recorded-service-name>'

 JSON responses can contain credentials and provision data. An AI runner must capture them privately in memory, extract an explicit allowlist of metadata/evidence, and avoid logging raw stdout, stderr, or command arguments containing secret parameter values. Do not run delete-all . A retry is a new order tracked as a new attempt; there is no CLI command in this release that safely manages the test retry policy for you.
 Python engine adapter pattern
 This illustrative adapter supplies transport only. The caller must hold the ledger lock, save order intent before calling order, and persist the returned identity atomically. It is not a complete unattended test runner.

 import json
import subprocess

class BabylonCommandError(RuntimeError):
 pass

def call_babylon(config_path, server, namespace, arguments):
 command = ["babylon", "--config", config_path, "--server", server,
 "--namespace", namespace, *arguments, "-o", "json"]
 try:
 result = subprocess.run(
 command, capture_output=True, text=True, timeout=90, check=False
 )
 except subprocess.TimeoutExpired:
 # An order may already exist. Caller must mark order-unknown and reconcile.
 raise BabylonCommandError("timeout; reconcile before any retry") from None
 if result.returncode:
 # Inspect details privately; never log raw responses or secret arguments.
 raise BabylonCommandError("CLI failed; reconcile order outcome")
 try:
 return json.loads(result.stdout)
 except json.JSONDecodeError:
 raise BabylonCommandError("invalid response; reconcile order outcome") from None

def returned_identity(claim):
 metadata = claim["metadata"]
 return {key: metadata[key] for key in ("name", "namespace", "uid")}

# Under the run lock:
# 1. Write durable order intent with state=order-unknown.
# 2. call_babylon(..., ["service", "order", ci, "--purpose", "QA", ...]).
# 3. Persist returned_identity(response); set state=provisioning.
# 4. On any exception, preserve intent and reconcile before another order.
# 5. Refresh live state; only retry a terminal failure with no active action/run.

 Separate Kubernetes checks and authentication failures

 oc --kubeconfig="$HOME/secrets/babylon-west.kubeconfig" \
 get tenantclusterpools -n shared-clusters
oc --kubeconfig="$HOME/secrets/babylon-west.kubeconfig" \
 get resourceclaim '<exact-claim>' -n "$BABYLON_NAMESPACE" \
 -o jsonpath='{.metadata.name}{"\t"}{.status.summary.state}{"\n"}'

 Use oc for live configuration, pool readiness, subject/action/run evidence and automatic deletion verification that the CLI does not fully expose. A working kubeconfig does not refresh an expired CLI session. On not logged in or an actual session expiry, repeat browser login with the same west config and then perform read-only checks. On DNS/VPN/connectivity failure, restore connectivity first: the CLI may wrap a network failure in “session expired.” Never re-order simply because authentication or a status read failed. Headless agents need a valid existing session or a human-assisted login; this release does not expose a kubeconfig-login flag.
 Source: Babylon v0.44.11 CLI , including browser login , configuration , and release binaries .
 Procedure
 1. Establish the scope and start a new ledger
 Read this runbook, the snapshot procedure, the current spreadsheet, and referenced Jira tickets. Resolve each URL to the actual live test catalog item. Correct catalog URLs and store the plain CI name. Deduplicate repeated references. Record unavailable items as blocked; do not substitute dev.
 Use a new UTC run ID and new ledger. Do not overwrite the prior run's results or inherit its retries. Preserve a read-only export of the tracker and a sanitized summary of the previous run before changing testing statuses. If the existing sheet lacks a run-ID column, add one or create a new run tab and record the mapping.
 Minimum durable ledger fields:

 {
 "run_id": "<UTC timestamp>",
 "snapshot_manifest": "<approved manifest path or URL>",
 "items": [{
 "ci": "<account>.<item>.test",
 "sheet_row": 0,
 "jira_key": "<ticket>",
 "cycle_id": "<unique snapshot revision>",
 "state": "pending",
 "attempts": [],
 "dependencies": [],
 "previous_cycles": []
 }]
}

 For each attempt, persist order intent, UTC timestamp, account/namespace, snapshot identity, exact parameter values excluding secrets, claim name/UID, subject names/UIDs, controller/job IDs and URLs, final state, placement cluster, runtime, and cleanup evidence. Record order intent before sending the request. Save the returned claim immediately. Serialize mutations with a lock and use atomic ledger writes.
 If ordering times out or the response is ambiguous, inspect actual services for that intent before doing anything else. Never assume failure means no service was created. If the ledger is missing or corrupt, stop ordering and recover it; do not reconstruct attempt counts from guesses.
 2. Prove the configuration is clean and reconciled
 For every root and child component, verify the approved source commit, SCM tag target, EE digest, collection/content/GitOps refs, and relevant flags against the snapshot manifest. Compare effective dev/test settings, not only raw stage files. Retain documented test exceptions.
 Verify live Babylon definitions match the merged snapshot. Record the check time and relevant revisions. If a dependency still uses an older configuration, mark the root blocked and wait. Do not begin a new cycle with a mixture of old and new dependencies.
 Do not deploy the prior run's historical test configuration simply because its catalog item still exists. Do not replace only the SCM ref and leave old Showroom, EE, collection, or GitOps settings behind.
 3. Prepare dependencies before ordering tenants
 Classify items as standalone labs, binders, dedicated cluster/tenant pairs, or ordered pairs such as Ansible Island. Inspect actual configuration rather than guessing from the name.
 For each dedicated cluster/tenant pair:
 Verify the backing cluster registration and tenant matching both use the approved purpose: test and matching lab. Physical CNV placement is separately configured for an existing valid physical cluster, normally purpose: prod for this RH1 run.

 Find the matching test TenantClusterPool in shared-clusters . If not already configured, enable exactly one backing cluster ( enabled: true , minClusters: 1 , maxClusters: 1 ), preserving all other fields. Do not modify dev pools or manually rewrite selectors.

 Follow backing ResourceClaims from pool status. Wait for started and sandboxApiState: enabled ; either condition alone is insufficient.

 Verify the tenant's live effective selector or tenant_cluster.item binding again. Order the tenant once after its prerequisite is ready. Do not separately order the direct cluster catalog item.

 Track pool provisioning success, elapsed time, and AAP job duration independently from the tenant outcome.

 For Ansible Island, deploy the leaderboard first, verify success, then use its required linkage when ordering the student. Keep the leaderboard until its dependent student test and cleanup no longer need it. Never expose provision data while extracting linkage.
 4. Order and monitor each CI
 Use Babylon CLI against the approved west catalog, in the verified user's account, with parameters from the live catalog schema. Persist intent before ordering, then record the returned service/claim. Start at attempt 1 for this new cycle.
 Monitor ResourceClaims, AnarchySubjects, active actions/runs, and AAP jobs. A successful CLI submission is not a successful deployment. Record the actual AAP controller and all relevant deploy jobs; shared components may execute on a different controller from the root. Search prod0/prod1 as well as event controllers when the service evidence points there.
 For CNV, record the actual OCPV placement cluster. For dedicated tenant infrastructure, also record the backing cluster and its Babylon/owner when available. An unexpected dev placement blocks further testing of that configuration until corrected.
 5. Apply the retry state machine
 Current observation
 Action

 Provisioning or active action/run
 Continue monitoring; do not retry.

 Ambiguous order, missing claim, or API/auth error
 Block and reconcile evidence; do not retry.

 Confirmed terminal failure, fewer than three attempts
 Preserve job/error evidence, confirm no active action/run, then order one retry.

 Success on attempt 1
 Mark successful.

 Success on attempt 2 or 3
 Mark successful with one or two retries, respectively. Record observed failure causes without assuming they were infrastructure.

 Three terminal failures
 Mark un-deployable for this snapshot and stop.

 There is no universal fixed retry delay. Readiness for retry depends on confirmed terminal state and absence of active actions/runs. A periodic monitor may check every few minutes, but elapsed time alone never authorizes another order.
 For an approved configuration correction, archive all current attempts as a previous cycle, retain evidence and classification, wait for merge and live reconciliation, and start a new cycle once. Use a durable correction marker so automation cannot reset the same cycle repeatedly. Do not mix configuration-placement failures with lab defects.
 6. Capture developer evidence and update the tracker
 Use concise current statuses without repeating the CI name. Use color coding: green successful, blue provisioning, yellow waiting/queued, orange failed/blocked, red un-deployable. Verify headers before relying on column letters; the October 2026 tracker used:
 Field
 Column at original run

 Current testing status
 F

 Successful AAP deploy duration — time only
 G

 Pool outcome / elapsed / AAP durations
 H / I / J

 Failed AAP job links after three failures
 K

 Infrastructure findings
 L

 Automatic deletion check
 M

 Prior-cycle job evidence
 N

 Time to verified deletion
 O

 Developer synopsis
 P

 Make every URL clickable, including multiple failed job links in one cell. For successful deployment duration, record the actual AAP elapsed time, not order-to-ready wall time. When there are multiple component jobs, label them clearly in the supporting evidence rather than silently adding unrelated jobs.
 For every un-deployable CI, inspect all failed AAP deploy jobs and compare the failed task, module, normalized error, host, and infrastructure placement. Explain whether all attempts failed at the same point or at different points. Include the configured snapshot and direct job links. If failure occurred during Sandbox API placement before AAP started, state that explicitly; do not invent an AAP job.
 Read the linked Jira issue's acceptance criteria and prepare an evidence-based update. If Jira comment access is available and authorized, post the result. If not, preserve the update in the tracker and report the permission blocker. Never imply a Jira update was posted when it was only prepared.
 Keep operational setup mistakes in the private run ledger, distinct from lab findings. Escalate observed recurring OCPV instability with concrete cluster/job evidence rather than a blanket unsupported claim.
 7. Clean up and verify automatic deletion
 After recording successful results, retire only the approved services owned by the test account that are no longer needed. Retain prerequisites while dependents still need them. Before every deletion, refresh ownership, claim UID, dependency, and active-action/run evidence. Do not touch unrelated services or other users' clusters.
 Preserve failed-job evidence before cleaning up superseded attempts. Never delete a replacement service by matching only a CI prefix. Use the exact recorded claim and UID.
 Record the deletion request timestamp and follow automatic AnarchySubject teardown. Only confirmed NotFound proves absence; API/auth errors do not. Do not remove finalizers or force-delete subjects to make the check pass. Record destroy failures as cleanup failures.
 Record actual destroy-job runtime separately from elapsed time to observed deletion. If absence is first observed on a later poll, report the elapsed time as an upper bound. Update the successful deletion check and time columns once absence is confirmed.
 8. Finish or resume safely
 The run is complete when each in-scope item is successful, un-deployable for the current snapshot, or explicitly blocked with an owner/action; all required results and job evidence are recorded; and authorized cleanup has been verified or recorded as a separate outstanding task.
 When resuming, load the durable ledger under its lock and refresh live state first. Do not re-order previously successful, provisioning, ambiguous, or terminal three-failure items. Stay quiet on unchanged monitor progress; notify on success, final failure, prerequisite readiness, or a blocker needing human action. Disable recurring monitors when their tracked scope is complete.
 Deployment Testing sheet schema and examples
 The following headers were read from the live Deployment Testing tab on 15 Oct 2026 . Spreadsheet ID: 1svoO4gqdVZ3bL3flBOvTLLQoVLTsQHHnzpNZmqgRQJM ; tab name: Deployment Testing ; numeric sheet ID (gid): 1155849629 . These are different identifiers: values calls use the spreadsheet ID and A1 tab range; formatting requests also use the numeric sheet ID.
 Row 1 contains headers; data starts at row 2. Read headers each run and map by exact header text rather than assuming fixed positions forever. Identify a CI by its full name in E, never by a cached row number alone. Preserve human input and unrelated cells. The durable ledger remains the source of attempt identities and history; the sheet is the readable report.
 Column / exact header
 Value and write rule
 Example (illustrative unless noted)

 A — Lab ID (RH)
 Text; parent RH lab ID. Preserve the input value; may describe a multi-asset lab.
 LB2075 (multi-asset)

 B — PH Lab ID
 Text; individual lab/asset ID from the source tracker. Preserve it.
 LB2075d

 C — us-west test catalog URL(s)
 One clickable west test-order URL per CI, in the same order as E. Verify the CI exists.
 https://babylon-catalog.apps.ocp-us-west-2.infra.open.redhat.com/catalog/babylon-catalog-test/order/rh1-2027.lb2075d-sat-lightspeed-ansible.test

 D — Jira Ticket (testing)
 Clickable issue URL(s). Read the issue before testing; keep the actual linked testing ticket.
 https://redhat.atlassian.net/browse/RHDPCD-1540

 E — Test catalog item(s)
 Full plain catalog item name, no URL. One line per CI if an existing tracker row combines components.
 rh1-2027.lb2075d-sat-lightspeed-ansible.test

 F — Current testing status
 Concise current-cycle status; do not repeat the CI name. Include attempt/retry counts. Apply conditional color formatting.
 Successful — attempt 2/3; 1 retry

 G — Successful AAP2 deploy job duration
 Time only, derived from successful AAP job elapsed. Blank until success. Do not use order-to-ready time or add concurrent jobs.
 16m 32s

 H — Backing cluster pool status
 Pool prerequisite status for a cluster/tenant CI. Include registration readiness; blank for standalone CIs.
 Cluster started; waiting for Sandbox API registration

 I — Backing cluster deployment time
 Elapsed backing-claim creation to successful completion, distinct from AAP job elapsed. Blank until measurable; preserve raw timestamps in ledger.
 1h 12m 8s

 J — Backing cluster AAP2 deploy job durations
 Durations for each successful backing-cluster component job; identify component where multiple jobs exist. Do not silently sum them.
 openshift: 52m 10s; workloads: 18m 4s

 K — Failed AAP2 job links (3 failed attempts)
 Clickable deploy job URL(s) for all three terminal attempts in the current failed cycle. Keep attempt-to-job mapping. If no job started, explain that in P rather than invent a URL.
 Attempt 1: <job URL>; Attempt 2: <job URL>; Attempt 3: <job URL>

 L — Infrastructure reliability findings
 Evidence-based infrastructure observations with actual placement cluster and affected attempts. Keep operational setup mistakes in the private ledger.
 Attempts 1 and 2: VM provisioning errors on OCPV08; attempt 3 succeeded on OCPV01.

 M — AnarchySubject cleanup status
 Automatic cleanup verification plus UTC check time. Verify every recorded subject; distinguish pending, failed, and confirmed absent.
 Verified deleted automatically — all recorded subjects absent; checked <UTC timestamp>

 N — Previous test cycle failed job links
 Clickable archived job links, labeled with prior cycle and classification. Retain after an approved cycle reset.
 Previous cycle: CI configuration; attempt 1 <job URL>

 O — Time to verified deletion (upper bound)
 Time only: deletion request to first observation that all tracked subjects are absent. Upper bound due to polling; blank while unverified.
 2m 26s

 P — Developer failure synopsis / attempt comparison
 Compare all attempts: failing task/module/error, same versus differing failures, snapshot identity, and concrete developer action. Explain pre-AAP placement errors and missing jobs explicitly.
 All three attempts failed in Showroom pod readiness with the same setup error. Compare pinned content layout and Showroom/Nookbag runtime. See K for each job.

 Blank values, multiple CIs, and run identity
 Blank means not applicable or not yet observed, never success or zero seconds. F/H/M/P provide the context. Do not populate a deployment duration for a failed deployment.

 Existing rows can represent multiple CIs, such as leaderboard and student. Preserve the mapping in E and the ledger. Use short role labels such as “Leaderboard:” and “Student:” in F rather than repeating full CI names. Keep per-CI outcomes and attempt counts separate; one component succeeding does not make the entire row successful.

 For several successful deploy jobs in G, use time-only lines in the same documented component order, and retain the component/job mapping in the ledger. J may explicitly label pool component durations. Never use a sum as end-to-end elapsed time unless clearly specified elsewhere.

 The current sheet has no run-ID or snapshot-ID column beyond P. For a new run, use a new run tab or explicitly add Run ID and Snapshot ID columns before filling them. Record that choice in the ledger; do not silently reinterpret an existing column.

 Keep C/D/K/N URLs clickable. A single URL can use a HYPERLINK formula with USER_ENTERED input. Multiple links in one cell require individually linked text runs; a newline-separated plain string is not sufficient proof that every URL is clickable.

 Status vocabulary and colors
 Situation
 F value
 Color

 Not yet ordered
 Queued
 Yellow

 Tenant prerequisite incomplete
 Waiting for test backing cluster — not yet tested
 Yellow

 Order accepted; work active
 Provisioning — attempt 1/3
 Blue

 Terminal failure with retry remaining
 Failed attempt 1/3 — retry pending
 Orange

 Unknown order outcome
 Order response unknown — checking before retry
 Orange

 Configuration/access blocker
 Blocked — <specific blocker>
 Orange

 First-attempt success
 Successful — attempt 1/3; 0 retries
 Green

 Success on second attempt
 Successful — attempt 2/3; 1 retry
 Green

 Success on third attempt
 Successful — attempt 3/3; 2 retries
 Green

 Three terminal failures
 Un-deployable — failed 3/3 attempts
 Red

 Use conditional formatting driven by status text. Give an un-deployable or blocked sub-result precedence when a multi-CI cell contains mixed outcomes, so “Successful” in another line cannot incorrectly turn the whole cell green.
 Example result records
 These are synthetic examples, not additional observations or results for the current labs. Placeholder job URLs must be replaced with actual recorded URLs. Columns A–E remain the row's identity fields.
 Scenario
 F / G
 Other fields to populate

 First attempt succeeds
 F: Successful — attempt 1/3; 0 retries
G: 16m 32s
 H–J blank for a standalone CI. K blank. M pending until cleanup is requested and verified.

 Third attempt succeeds
 F: Successful — attempt 3/3; 2 retries
G: 12m 7s
 L: observed infrastructure cause and actual OCPV cluster, if supported. Preserve first two failed jobs in ledger; K remains reserved for three-failure cycles.

 All three fail at the same task
 F: Un-deployable — failed 3/3 attempts
G: blank
 K: three attempts' clickable deploy jobs. P: same task/module/error in all attempts, exact snapshot, developer action. Do not label it flaky solely because it was retried.

 Attempts fail in different places
 F: Un-deployable — failed 3/3 attempts
G: blank
 P: attempt 1 VM readiness on <cluster>; attempts 2/3 Showroom setup. K: all available deploy jobs. L: only the infrastructure evidence.

 Placement fails before AAP
 F: Failed attempt 1/3 — retry pending (only if eligible)
G: blank
 K: blank. P: Sandbox API placement error; no AAP deploy job was created. At three terminal failures use un-deployable; preserve placement evidence even when K has no jobs.

 Pool started but not registered
 F: Waiting for test backing cluster — not yet tested
G: blank
 H: Cluster started; sandboxApiState pending. I/J: record completed backing-cluster timings. No tenant attempt exists yet.

 Deletion verified
 F: keep successful deployment result
G: keep successful runtime
 M: Verified deleted automatically — all recorded subjects absent; checked 2026-10-15T18:00:00Z. O: 2m 26s. This is an observation upper bound, not the destroy-job duration.

 Configuration correction starts a new cycle
 F: Provisioning — attempt 1/3 (after approved reset/order)
G: blank for new cycle
 N: old cycle's labeled job links. P: old configuration/placement classification retained; new cycle result pending. Ledger stores the durable reset marker.

 Read and write examples with gws
 Read the current header and target identity before writing. Example below reads the real header; the write payload is illustrative and must be adjusted to a verified target row.

 gws sheets spreadsheets values get --params \
 '{"spreadsheetId":"1svoO4gqdVZ3bL3flBOvTLLQoVLTsQHHnzpNZmqgRQJM","range":"\u0027Deployment Testing\u0027!A1:P1"}'
# Before a write, read the target row's A:E and compare E to your ledger CI.

 Example values.batchUpdate body for F/G only (do not send until row identity and outcome are verified):

 {
 "valueInputOption": "RAW",
 "data": [
 {
 "range": "'Deployment Testing'!F2:G2",
 "values": [
 [
 "Successful — attempt 2/3; 1 retry",
 "12m 7s"
 ]
 ]
 }
 ]
}

 Single-link example for a URL cell, using USER_ENTERED so Sheets evaluates the formula:

 {
 "valueInputOption": "USER_ENTERED",
 "data": [
 {
 "range": "'Deployment Testing'!D2",
 "values": [
 [
 "=HYPERLINK(\"https://redhat.atlassian.net/browse/RHDPCD-1540\",\"RHDPCD-1540\")"
 ]
 ]
 }
 ]
}

 For multiple jobs in K/N, use spreadsheets.batchUpdate with updateCells and textFormatRuns. Each run's format.link.uri must reference the exact job for that attempt. Read the cell back and verify every link. Use narrow update ranges/field masks; never clear an entire tab to update a status.
 AI execution prompt

 Run RH1 deployment testing using docs/rh1-deployment-testing-runbook.md and
docs/test-snapshots.md. Use the specified Deployment Testing sheet as the scope
source, and read each linked Jira issue. First verify that all selected existing
test YAMLs and shared dependencies represent the approved effective-dev snapshot,
all snapshot PRs are merged, and Babylon's live configuration matches the manifest.
Do not order until these gates pass. Report missing inputs or configuration drift.

Create a new run ID and a private durable ledger at <RUN_STATE_DIRECTORY>. Preserve
the historical run separately. Do not use old /tmp helpers or inherit attempt counts.
Use the west Babylon CLI endpoint and explicit kubeconfig flags. Order one user
(two if required). Prepare one backing cluster per approved test tenant pool and
wait for started plus sandboxApiState enabled before ordering its tenant. Order
Ansible Island leaderboard before student and link them correctly.

Persist intent and evidence before/after each action. Retry only confirmed terminal
failures with no active action/run, at most three total attempts per configuration
cycle. Stop on ambiguous orders, missing claims, ownership errors, or missing state.
Record actual AAP controller/job links, successful durations, CNV placement, pool
outcomes, and an all-attempt failure comparison for developers. Use clickable URLs
and concise color-coded statuses in the sheet. Preserve evidence when Jira writes
are unavailable. Never expose credentials or provision data.

Clean up only explicitly authorized, no-longer-needed services after recording
results and checking ownership/dependencies. Verify automatic AnarchySubject
deletion and elapsed time. Keep configuration/setup mistakes separate from lab
findings. Do not change selectors, reset cycles, expand scope, or delete unrelated
resources without applicable authorization. Finish with outcomes, blockers, evidence
links, and cleanup status.

 Troubleshooting and reference
 Use the troubleshooting table in test-snapshots.md for stale runtime, Showroom compatibility, and Sandbox API placement failures.

 Do not reuse the historical /tmp/deployment_testing_run.py or its plan as a dependency of this procedure. Implement or locate a reviewed runner that enforces the ledger and state-machine contract above; this document does not ship an executable runner.

 Babylon CLI source and usage 

 Approved west catalog 

 Required Showroom snapshot tags
 Never use a raw commit SHA in ocp4_workload_showroom_content_git_repo_ref , including nested component parameters. Use a named tag in the Showroom content repository.
 Resolve the effective dev content repository and ref to its exact commit; retain that commit as private snapshot evidence.

 Inspect existing remote tags and reuse a suitable tag only if it resolves to that exact commit. Peel annotated tags before comparing.

 If no matching tag exists, create a per-CI snapshot tag at that commit. Never overwrite existing tags. When correcting a SHA snapshot, preserve the original captured commit rather than updating to a moving main branch.

 Write the tag name in the existing test override. Verify its target with gh api repos/OWNER/REPO/commits/TAG --jq .sha , run the real AgnosticV merge, and reject raw SHA values in effective Showroom refs.

 After merge, verify the live Babylon tag before ordering. Static validation is not deployment success.

 Git-cloner v1.1.5 checks out raw SHAs before configuring safe.directory, which can cause fatal: detected dubious ownership in repository at '/showroom/repo' . Dev's branch clone does not exercise that path. The SHA belongs in tag-creation API arguments and audit evidence, not the Showroom ref.
 Failures introduced by our snapshot conversion are test-configuration mistakes. Preserve history in the private ledger; column P contains only clear, confirmed outstanding developer fixes and evidence links.
 See Create and refresh test snapshots from dev for the tag creation and verification commands.
 Catalog version parameters and snapshot pins
 Before copying dev parameters into test, inspect the corresponding common.yaml and inherited account/includes with the real AgnosticV merger.
 - Remove version/ref/revision/tag catalog parameters introduced only by dev/test when they are absent from common. Keep the required pinned values in test variables or collection definitions. Preserve repository URL parameters and scenario inputs such as user count and leaderboard linkage.
 - If a version parameter is inherited from common, keep it and override its default in test to the same snapshot value as the test variable. Retain the complete parameter schema and metadata when overriding a named entry. Showroom content refs must use verified named tags, never raw SHAs.
 - Do not change the schema to support parameter removal. parameters: null clears the merged list but is rejected by the current catalog schema. parameters: [] does not remove inherited parameters. An individual default: [] supplies a list value; it does not remove a parameter and is invalid for a string ref.
 - Shared components can serve multiple labs with different content repositories. Do not put one lab's tag into a generic shared-component default. Verify each parent's __meta__.components[].parameter_values explicitly supplies that lab's named tag, then verify the resulting child job variables.
 - Compare aliases as well as exact variable names (for example showroom_repo_revision and ocp4_workload_showroom_content_git_repo_ref ). A matching raw YAML variable is insufficient proof of what an order executes.
 Before ordering, require all of the following:
 1. AgnosticV merge and schema validation succeed; removed parameters are absent and retained defaults match the intended snapshot.
 2. Live AgnosticVComponent, CatalogItem parameter defaults, and ResourceProvider parameter schema/template agree with the approved configuration.
 3. The new ResourceClaim parameter values and resulting AnarchySubject/AAP job variables use the expected refs. Inspect privately and report only non-secret evidence.
 4. If a default still supplies an old SHA, branch, or tag, hold the order until reconciliation completes. A merged PR and a correct top-level variable alone are insufficient.
 LB2111 illustrated this failure: the top-level Showroom ref used a named tag while the catalog default still supplied the old SHA. Treat snapshot-conversion errors as our test configuration issues, not developer findings.
