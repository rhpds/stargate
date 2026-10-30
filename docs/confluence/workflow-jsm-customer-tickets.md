# Workflow: JSM Customer Tickets
# Confluence ID: 436504695
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/436504695

Workflow: JSM Customer Tickets
 When to use: Customer submits a support request through the JSM portal.

 Flowchart
 Stage 1
 Stage 2
 Stage 3
 Stage 4
 Stage 5

 INTAKE 
 →
 TRIAGE 
 →
 INVESTIGATE 
 →
 RESOLVE 
 →
 CLOSE 

 Step Details
   1. Intake 
 Acknowledge the customer ticket within 4 business hours. Confirm receipt and set expectations for resolution timeline. Assign to the appropriate team member.

   2. Triage 
 Categorize the request:
 Workshop support: Active workshop needs assistance

 Provision failure: User cannot provision a catalog item

 Access issue: User cannot access their environment

 Feature request: Enhancement or new capability

 Set priority based on category and customer impact.

   3. Investigate 
 Reproduce the issue if possible. Check provision logs, user permissions, and recent changes. Identify the root cause type — is this a content bug, infra issue, user error, or cloud provider problem?

   4. Resolve 
 Apply the fix directly if possible. Provide a workaround if a permanent fix requires more time. Redirect to the appropriate team if the issue is outside ops scope. Communicate clearly with the customer throughout.

   5. Close 
 Confirm with the customer that their issue is resolved. Close the ticket. Log the resolution for knowledge base articles to help with future similar issues.

 Checklist
 Ticket acknowledged within 4 business hours 
 Category assigned 
 Issue investigated 
 Customer responded to 
 Resolution applied 
 Customer confirmed resolution 
 Ticket closed 
 Escalation
 Escalation Path: Unresolved after 24 hours → senior ops team member. Customer-critical or executive-visible → tag management immediately.

 Relevant Jira Links
 https://issues.redhat.com/issues/?jql=project%20%3D%20RHDPOPS%20AND%20labels%20%3D%20jsm_customer 

 https://issues.redhat.com/issues/?jql=project%20%3D%20RHDPOPS%20AND%20labels%20%3D%20customer_escalation
