# Disabling / Enabling OCP Shared Cluster Scheduling
# Confluence ID: 501318889
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/501318889

When an OCP cluster (ocpv01–09) is saturated or needs maintenance, you can stop the Sandbox API from placing new orders on it without touching running workshops.

 Script: sandbox-audit/sandbox-shared-cluster.sh in rhpds/rhpds-utils 

 Shell aliases (if set up locally): ocpv06-disable , ocpv06-enable , etc.

 Commands

 Disable — stop new placements: 

 ./sandbox-shared-cluster.sh disable ocpv06

 Enable — resume placements: 

 ./sandbox-shared-cluster.sh enable ocpv06

 Check state of one cluster: 

 ./sandbox-shared-cluster.sh list ocpv06

 List all clusters: 

 ./sandbox-shared-cluster.sh list

 The cluster name accepts ocpvNN or just the number ( 06 → ocpv06 ).

 Prerequisites

 SSH access to bastion-infra-us-east-1.infra.demo.redhat.com (ec2-user)

 SSH key at ~/.ssh/backdoor-rsa.pem , or set SANDBOX_SSH_KEY=/path/to/key 

 The bastion must have sandbox_api_disable/enable_shared_cluster.sh in ~/bin/ and an admin token sourced at ~/.sandbox-api-admin-token.rc (ops leads have this)

 What this does / does not do

 Does 
 Flip the OcpSharedCluster scheduling flag in the Sandbox API 

 Does not 
 Drain, stop, or restart anything on existing running workshops 

 Does not 
 Affect AWS sandbox accounts 

 When to use

 Cluster is at or near capacity and new orders are failing

 Cluster requires maintenance (node replacement, upgrade)

 Incident: a cluster is degraded and traffic needs to be redirected

 After disabling, re-enable as soon as capacity or maintenance is resolved. Active workshops on the cluster continue unaffected.

 Local alias setup (~/.zshrc)

 alias ocpv06-disable='~/bin/sandbox-shared-cluster.sh disable ocpv06'
alias ocpv06-enable='~/bin/sandbox-shared-cluster.sh enable ocpv06'
# ocpv01–09 all have matching aliases

 Or use the generic form (works for any cluster):

 sandbox-disable ocpv06
sandbox-enable ocpv06
