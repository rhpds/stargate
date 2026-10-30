# Fix: Missing environment_level annotation on event clusters causes tenant provisioning failure
# Confluence ID: 463437924
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/463437924

Summary
 Tenant provisioning fails immediately when an OcpSharedCluster is missing the environment_level: production annotation. The cloud_selector in event tenant catalog items requires this annotation to find valid cluster targets. If it's absent, no cluster matches and provisioning exits before it starts.
 Slack thread: APAC event cluster provisioning failure — Aug 2026 

 Jira: RHDPOPS-24198 (Closed)

 Symptoms
 Tenant CI provisioning fails immediately with no meaningful error

 Clusters show as valid and healthy in sandbox-cli cluster list 

 No AAP job is ever triggered — failure is pre-flight

 Root Cause
 Clusters onboarded for events are registered with purpose: events but without environment_level: production . The tenant catalog items use a cloud_selector that requires both annotations to be present. Onboarding steps don't currently include adding environment_level , so it has to be added manually after onboarding.
 Diagnosis
 SSH to the bastion and check the cluster's annotations:

 . ~/.sandbox-api-admin-token.rc
sandbox-cli cluster get <cluster-name> --server $route | jq '.annotations'

 If environment_level is absent from the output, this is the issue.
 Fix
 On bastion-infra-us-east-1 , source the admin token and run the update script for each affected cluster. The update script reads the Bitwarden-stored cluster token and handles auth correctly — do not skip it or try to use curl directly.

 . ~/.sandbox-api-admin-token.rc

# For each cluster — reads current annotations and adds environment_level: production
annotations=$(sandbox-cli cluster get <cluster-name> --server $route | jq '.annotations + {"environment_level": "production"}')
echo "{\"annotations\": $annotations}" > /tmp/<cluster-name>.update.json
~/bin/sandbox_api_update_shared_cluster.sh <cluster-name> /tmp/<cluster-name>.update.json

 To fix multiple clusters in a loop:

 for cluster in cluster-aaa cluster-bbb cluster-ccc; do
 echo "=== $cluster ==="
 annotations=$(sandbox-cli cluster get $cluster --server $route | jq '.annotations + {"environment_level": "production"}')
 echo "{\"annotations\": $annotations}" > /tmp/${cluster}.update.json
 ~/bin/sandbox_api_update_shared_cluster.sh $cluster /tmp/${cluster}.update.json
done

 Do not change purpose: events . Only add environment_level: production as a new annotation key alongside the existing ones.

 Verification

 for cluster in cluster-aaa cluster-bbb cluster-ccc; do
 sandbox-cli cluster get $cluster --server $route | jq -r '"'$cluster': purpose=" + .annotations.purpose + " | environment_level=" + (.annotations.environment_level // "MISSING")'
done

 All clusters should show environment_level=production .
 Auth Gotcha: sandbox-cli 401 with valid token

 sandbox-cli cluster set <name> environment_level production returns HTTP 401 even with a valid admin token. This is not an auth failure — it is a variable naming mismatch between the bastion rc file and what sandbox-cli reads:

 Setting
 sandbox-cli env var
 rc file export

 Server URL
 SANDBOX_API_ROUTE 
 route 

 Login token
 SANDBOX_LOGIN_TOKEN 
 admintoken 

 Sourcing ~/.sandbox-api-admin-token.rc sets route and admintoken . sandbox-cli ignores those and treats the request as unauthenticated. The hurl-based scripts ( sandbox_api_update_shared_cluster.sh ) read $route and $admintoken directly, so they work. Use those scripts rather than sandbox-cli for writes.
 If you need to use sandbox-cli for writes, bridge the names manually: 

 . ~/.sandbox-api-admin-token.rc
export SANDBOX_API_ROUTE=$route
export SANDBOX_LOGIN_TOKEN=$admintoken
sandbox-cli cluster list # now works

 Or persist credentials so you don't need env vars at all:

 . ~/.sandbox-api-admin-token.rc
sandbox-cli login --server $route --token $admintoken
# credentials saved to ~/.local/sandbox-cli/config.json

 Upstream Bug Report & Fixes
 This naming mismatch has been reported upstream with two fix options for the sandbox maintainer to choose from:
 GitHub issue: rhpds/sandbox#311 — full description of the bug and both proposed fixes
 PR #312 (Option B — docs): rhpds/sandbox#312 

Adds a "Bastion rc file compatibility" section to docs/cli.md explaining the mismatch and manual workarounds. No code change.
 PR #313 (Option A — code fix, preferred): rhpds/sandbox#313 

Exports SANDBOX_API_ROUTE and SANDBOX_LOGIN_TOKEN after sourcing the rc file in both sandbox_api_update_shared_cluster.sh and its dev variant. sandbox-cli works transparently in the same session — no manual steps. Backwards compatible.

 Both PRs are drafts pending maintainer review. Once merged, the code fix (PR #313) will mean sourcing the rc is sufficient and the manual bridge step above will no longer be needed.
 Prevention
 When onboarding new event clusters, add environment_level: production to the annotations block at creation time. Add this to the cluster onboarding checklist so it doesn't need to be applied manually after the fact.
 August 2026 Incident
 6 clusters onboarded for an APAC event (week of 2026-09-01) were all missing this annotation. Reported by Harsh Arora, diagnosed by Andrew Jones, fixed by Billy Bethell.
 Cluster
 Lab
 Fixed

 cluster-5t85c
 ai-lightning-lab-cluster
 DONE 

 cluster-ffmlp
 ai-lightning-lab-cluster
 DONE 

 cluster-p6htm
 ai-lightning-lab-cluster
 DONE 

 cluster-nt8k7
 ocp4-getting-started
 DONE 

 cluster-pp9cf
 ocp4-getting-started
 DONE 

 cluster-dbb57
 ocp4-getting-started
 DONE
