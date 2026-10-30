# Workflow: Failed Item Triage
# Confluence ID: 436537517
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/436537517

Workflow: Failed Item Triage
 When to use: A catalog item is failing provisions or destroys for end users.

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
 RAISE STATUS 
 →
 DISABLE 
 →
 INVESTIGATE 
 →
 FIX/ESCALATE 
 →
 RE-ENABLE 
 →
 FOLLOW UP 

 Step Details
   1. Detect 
 Check monitoring dashboards, user reports, or Icinga alerts for failing provisions or destroys. Look for patterns — is it one item or multiple? One region or all?

   2. Raise Status 
 Update the catalog item status page to reflect the known issue. This prevents duplicate reports and sets expectations for users.

   3. Disable 
 Disable the catalog item in production to prevent more users from hitting the failure. This is a protective measure — do it quickly.

   4. Investigate 
 Check provision and destroy logs for error details. Review recent changes — AgnosticV merges, EE updates, cloud quota changes, infrastructure changes. Identify whether this is a content issue, infra issue, or cloud provider issue.

   5. Fix or Escalate 
 If the root cause is clear and fixable by ops, apply the fix. If it requires content changes, escalate to the content owner. If it is an infrastructure issue, escalate to the infra team. Document what you found either way.

   6. Re-enable 
 After the fix is applied, verify it works in integration first. Run a full provision and destroy cycle. Once confirmed, re-enable in production.

   7. Follow Up 
 Update the Jira ticket with root cause and resolution. Notify affected users that the item is back online. Document the incident for future reference.

 Checklist
 Status page updated 
 Item disabled in production 
 Logs reviewed 
 Root cause identified 
 Fix applied 
 Tested in integration 
 Re-enabled in production 
 Jira ticket updated 
 Users notified 
 Escalation
 Escalation Path: Content owner first → infra team → management if customer-impacting for more than 24 hours.

 Relevant Jira Links
 https://issues.redhat.com/issues/?jql=project%20%3D%20RHDPOPS%20AND%20labels%20%3D%20failed_item 

 https://issues.redhat.com/issues/?jql=project%20%3D%20GPTEINFRA%20AND%20labels%20%3D%20catalog_issue
