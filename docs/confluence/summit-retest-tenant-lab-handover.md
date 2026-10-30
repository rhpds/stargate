# Summit Retest — tenant-lab handover (LB1758 / LB2645 / LB2863)
# Confluence ID: 492931206
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/492931206

Handover — three Summit Retest tenant labs provision and bind correctly (land on ocpv09 , own pool) but fail in the Ansible workload stage. These are per-lab content / infra bugs, not pool/pin or sandbox-binding issues ( agnosticv#28347 already fixed binding). A plain redeploy will re-hit the same error. Verified live on ocp-us-west-2 , 01 Oct 2026 . Parent: Summit 2026 Retest tracker .

 Labs
 Lab
 Jira
 Status
 AAP2 job
 Root cause
 Recommended fix / owner

 LB1758 
Showroom AI Assistant
 GPTEINFRA-18139 
 OPEN 
 99638
 Image pull denied. ImagePullBackOff on docker.io/llamastack/distribution-starter:0.3.2 → "requested access to the resource is denied"; showroom-ai-assistant pod never Ready. + role bug: r_route_info.resources | length > 0 → "'dict object' has no attribute 'resources'" at deploy_showroom_ai_assistant.yaml:137 .
 Public/working llamastack image ref or a docker.io pull secret; guard the route lookup (default to empty list). Role PR against agnosticd.showroom_ai_assistant . Owner: lab/content.

 LB2645 
 GPTEINFRA-18140 
 OPEN 
 100409
 Nested AAP2 Controller unreachable. "Inject AAP2 Controller manifest" retries 60× then fails: Failed to get token: <urlopen error [Errno 111] Connection refused> . The in-lab Controller endpoint never comes up / isn't listening.
 Investigate controller startup live — likely sizing / ordering / readiness timing. Add a health gate before manifest injection or give the nested controller more resources. Owner: lab/content.

 LB2863 
 GPTEINFRA-18141 
 OPEN 
 75771
 DevSpaces operator never installs. app-of-apps wait loop fails (45 attempts); 11/12 Applications Healthy+Synced. devspaces stuck OutOfSync — failing task Job/devspaces-wait-for-operator → "Job was active longer than specified deadline". CheCluster/devspaces + ExternalSecrets continue-llm-credentials / gitlab-oauth-config stay Missing. Source: rhpds/summit-2026-app-platform-roi-helm-charts @ bad0869 .
 Raise the devspaces-wait-for-operator deadline, or fix the DevSpaces operator subscription so it installs within the window. Owner: app-platform helm charts.

 Context for whoever picks this up
 The Retest 100%-fail on these was because binding fix agnosticv#28347 merged after the deploys ran (~05:04 UTC 30 Sep; deploys 20:30 Sep 29 – 01:37 Sep 30 UTC). Post-fix, 2 of 5 (LB2596, LB2391) now deploy clean.

 All 3 bind to a correctly-pinned ocpv09 sandbox (sandbox-API HTTP 200, sandbox_openshift_* injected) — confirmed via live claims. The failure is entirely in-workload.

 Evidence is the AAP2 deployer job stdout (event0 / event1 Controllers) cited per row.
