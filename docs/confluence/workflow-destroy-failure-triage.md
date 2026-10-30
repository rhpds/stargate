# Workflow: Destroy Failure Triage
# Confluence ID: 436537543
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/436537543

Workflow: Destroy Failure Triage
 When to use: Automated report or alert shows failed destroy jobs with leaked cloud resources.

 Flowchart
 Stage 1
 Stage 2
 Stage 3
 Stage 4
 Stage 5
 Stage 6
 Stage 7

 DETECT 
 →
 CREATE TICKET 
 →
 ASSESS COST 
 →
 ROOT CAUSE 
 →
 FIX & RETRY 
 →
 VERIFY 
 →
 PREVENT 

 Step Details
   1. Detect 
 Weekly destroy failure report or real-time alert flags orphaned cloud resources. Check for patterns across items or clouds.

   2. Create Ticket 
 Create an RHDPOPS ticket with the catalog item name, failure count, and estimated dollar amount leaked. Use the destroy-failure label.

   3. Assess Cost 
 Check AWS, GCP, and Azure consoles for orphaned VMs, VPCs, EBS volumes, load balancers, and other resources. Calculate the ongoing cost leak.

   4. Root Cause 
 Review destroy job logs. Common causes: missing variables, execution environment (EE) issues, timeouts, permission errors, cloud API rate limits, or stale credentials.

   5. Fix & Retry 
 Patch the config or playbook to address the root cause. Manually retry the destroy job for failed provisions. If retry is not possible, clean up resources directly in the cloud console.

   6. Verify 
 Confirm all orphaned resources have been terminated. Verify no remaining cost accrual in the cloud billing dashboard.

   7. Prevent 
 Update CI/config to prevent recurrence: pin EE versions, fix variable handling, add destroy retries, or improve error handling in playbooks.

 Checklist
 Ticket created with dollar amount 
 Cloud console checked 
 Orphaned resources identified 
 Destroy retried 
 Resources confirmed cleaned 
 Cost leak stopped 
 Prevention fix applied 
 Ticket closed 
 Escalation
 Escalation Path: If more than $1000 leaked or more than 20 failures, escalate immediately. For content owner changes, tag on the relevant PR.

 Relevant Jira Links
 https://issues.redhat.com/issues/?jql=project%20%3D%20RHDPOPS%20AND%20labels%20%3D%20destroy_failure 

 https://issues.redhat.com/issues/?jql=project%20%3D%20GPTEINFRA%20AND%20labels%20%3D%20resource_leak
