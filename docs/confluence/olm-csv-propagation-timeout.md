# OLM CSV Propagation Timeout Causing Operator Deployment Failures on Slower Clusters
# Confluence ID: 512622803
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/512622803

Problem
 Workshop provisioning jobs fail at the Wait until CSV is installed task for DevWorkspace or similar operators, exhausting all retries and producing:

 fatal: [localhost]: FAILED! => {"api_found": true, "attempts": 30, "changed": false, "resources": []}

 This typically surfaces on slower clusters (e.g. ocpv-infra01 , ocpv-infra02 ) where OLM takes longer to propagate the CSV to target namespaces.
 Root Cause
 The jeffcpullen.agnosticp collection's install_operator.yml used retries: 30 with a short delay, providing roughly 15 minutes of wait time. On slower clusters, OLM propagation of a CSV to the devspaces namespace (or similar) can take 20–25+ minutes — well beyond the retry window.
 This is a latent bug in the collection that becomes visible under load or on resource-constrained clusters.
 Fix
 PR rhpds/jeffcpullen.agnosticp#6 extends the CSV wait to handle AllNamespaces operator propagation delays. Merged and confirmed passing in production.
 Symptoms to Look For
 Failure in jeffcpullen.agnosticp.agp_devspaces role

 Task name contains Wait until CSV is installed devworkspace-operator-fast-redhat-operators-openshift-marketplace 

 Job runtime at point of failure is 18–22 minutes

 api_found: true in the fatal output (operator exists, CSV just hasn't propagated yet)

 Affected Workshops
 Product Enablement: Ansible Automation Platform Operator Deployment

 Resolution
 If you see this failure, re-provision — the fix is live. If it recurs, check OLM health on the target cluster and whether the CSV has propagated with oc get csv -n <namespace> .
