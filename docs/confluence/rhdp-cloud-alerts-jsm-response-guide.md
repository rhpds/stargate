# RHDP Cloud Alerts — OPS JSM Ticket Response Guide
# Confluence ID: 508067977
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/508067977

Description
 Use this procedure for RHDP Cloud Alerts incidents in RHDPSPPT , received through Slack or the JSM queue. Alerts cover AWS, Azure, and GCP costs, AWS activity and inventory, and Azure unassigned subscriptions.
 First determine whether the usage is legitimate. An alert is a reason to investigate, not proof of compromise. Use Parsec or manual checks. If the activity is expected and no issue remains, record the evidence and close the ticket. If it is unexplained, contact the sandbox owner, track the investigation, and escalate or contain as warranted.
 This is a decision-driven workflow: owner contact, investigation, evidence preservation, and incident escalation may run in parallel. Do not wait for an owner reply before addressing an active security incident through the established incident process.
 Quick decision guide
 Finding
 OPS response
 Ticket outcome

 Expected, authorized lab/demo/workshop usage; no unresolved concern
 Record the workload, owner or catalog evidence, and why the alert is legitimate
 Resolve/close using the available JSM workflow

 Legitimate workload but unintended spend, leftovers, or failed teardown
 Contact owner/platform team, agree cleanup, track actions and verify results
 Keep open until the issue is resolved

 Unclear ownership, unexplained activity, or conflicting evidence
 Continue investigation and contact owner; assign a next action and follow-up time
 Keep open; silence is not confirmation

 Suspected or confirmed compromise/abuse
 Follow the security incident procedure; coordinate evidence, containment, InfoSec, and recovery
 Keep open through verification and handoff/closure

 Prerequisites
 JSM access to view, assign, comment on, and resolve RHDPSPPT incidents.

 Access to current sandbox ownership/provisioning records and the relevant cloud account, subscription, or project.

 Parsec access, or cloud-console/CLI access for manual investigation.

 For containment: authorized response access and familiarity with the relevant tool's current instructions.

 Security Incident or Breach Procedure : the existing escalation and coordination process takes precedence during incidents.

 Recovery/Procedure Steps
 1. Take ownership and establish the target
 Assign an OPS responder. Read the description and latest comments ; later cost or event observations can update the same ticket. Record the cloud ID, sandbox name, GUID if present, alert type, event/billing date, observation time, and current owner.
 Confirm the sandbox's current assignment against the alert time. Sandbox names and accounts can be reused; an old owner or GUID is not sufficient authority to change the current environment. Check for related enforcement, abuse, or support tickets and link them.
 Success: a named responder, verified target, and an initial next action are recorded.
 2. Determine whether the usage is legitimate
 Use the ticket's Investigate in Parsec link when present, or start a manual investigation. A suggested Parsec prompt:
 Investigate this RHDP Cloud Alerts ticket using read-only checks. Verify the account/project/subscription and current sandbox owner/GUID. Explain the resources or events behind the alert, whether they match the expected lab or workload, and any suspicious indicators. Distinguish evidence from assumptions, include timestamps and sources, and recommend next steps. Do not change resources or contact anyone.
 Check the underlying evidence before accepting an AI conclusion. If Parsec is unavailable, continue manually:
 Compare the catalog item, workshop/demo purpose, expected regions, resource types, and scale with actual usage.

 For costs, inspect the billing date , services, regions, trend, and live resources. Yesterday's charges can persist after resources stop; delayed billing is not proof that cleanup failed.

 For activity, inspect the actor, event time, action, resource IDs, source IP where available, and expected provisioning or user workflow in CloudTrail, Azure Activity Log, or GCP Audit Logs.

 For inventory, confirm whether instances are expected cluster nodes or separate workloads. GPU usage, multiple regions, and non-OCP counts are investigation clues, not verdicts.

 For unassigned subscriptions, verify pool assignment and teardown state before treating leftover resources as abuse.

 Success: classify as legitimate, operational issue, or suspected security issue, with evidence and any remaining uncertainty.
 3. Close legitimate alerts with a reason
 When evidence supports expected usage and no action remains, add a resolution note and resolve/close the ticket. Example:
 Legitimate usage — resources and regions match the approved workshop/catalog deployment. Verified current owner and GUID against provisioning records and checked the reported billing period. Evidence: [links]. No unexplained activity or cleanup action remains.
 Owner confirmation is useful when purpose is unclear, but is not a substitute for investigating contradictory security evidence. Do not close solely because Parsec says “safe,” the owner has not replied, or the cost has dropped.
 4. Contact the owner and track unresolved work
 For suspected issues or unexplained usage, contact the verified sandbox owner through the normal support channel. Include the ticket, sandbox/GUID, cloud ID, observed activity or cost period, and specific questions:
 We are investigating [ticket] for [sandbox/GUID]. We observed [facts and time period]. Is this expected for your lab/demo? Please confirm the workload, regions/resources, and whether they are still needed. We are tracking investigation and any cleanup in the ticket.
 Record contact time, response, impact, assigned actions, and next follow-up. Keep one OPS responder accountable while waiting. Escalate through the OPS/incident process when the owner cannot be reached or the risk is increasing; do not treat no reply as authorization or legitimacy.
 Use internal notes for investigation details as appropriate, and do not copy credentials or sensitive forensic material into customer-visible comments. Link approved evidence storage instead.
 5. Escalate and contain when warranted
 Unexpected IAM/access changes, owner-denied activity, abuse reports, persistence/recreation, unauthorized workloads, or suspected credential/data exposure warrant security triage.
 Follow the Security Incident or Breach Procedure . It uses #team-rhdp-infosec for InfoSec coordination and #team-rhdp-troubleshooting for a swarm when needed. Involve the relevant Infra team and management as that procedure directs. Even a quickly handled security incident needs the notification specified there.
 Capture useful logs, actor/resource IDs, timestamps, and evidence before destructive cleanup when feasible. Coordinate evidence preservation with urgent containment rather than delaying response to ongoing harm. Record who authorized containment, scope, actions, and results.
 6. Use breach_response only when appropriate
 The breach_response repository provides AWS and Azure investigation/containment tools. A cost threshold alone does not justify account-wide lockdown. Full response can stop workloads, remove access, and delete resources.
 Read the current tool documentation, verify the target, review a dry run, and use the incident team's authorized scope. Run the commands below from a prepared checkout with the documented dependencies installed. Replace placeholders; do not assume the local default account is correct.
 AWS identity and read-only reconnaissance:

 aws sts get-caller-identity --profile <SANDBOX_PROFILE>
python3 aws_breach_response.py --profile <SANDBOX_PROFILE> --scan-only

 Expected: the Account matches the ticket, and scan reports describe inventory, access, and activity without modifying cloud resources.
 AWS containment preview:

 python3 aws_breach_response.py --profile <SANDBOX_PROFILE> --dry-run

 Azure target check and containment preview:

 az account show --subscription <SUBSCRIPTION_ID> --query '{id:id,name:name,tenantId:tenantId}' -o json
python3 azure_breach_response.py --subscription-id <SUBSCRIPTION_ID> --dry-run

 Expected: the target matches the incident and the preview lists intended changes. Review the scope before using the documented live mode; avoid bypassing confirmation with --force during manual triage.
 Scenario
 Tool or route

 AWS account inventory
 aws_breach_response.py --scan-only 

 A single EC2 instance in an abuse report
 Instance investigation guide ; this workflow can contain resources and is not merely a read-only query

 Authorized AWS account-wide containment
 AWS response guide 

 Authorized Azure subscription containment
 Repository overview and current Azure script/docs

 GCP incident
 Coordinate with Infra/InfoSec for GCP-specific response; this repository does not document a GCP containment tool

 Azure limitations: the current script targets Custom-Owner role assignments, not every role. It cannot provide tenant-wide user/token revocation, and forensic snapshot creation is not implemented. Some Azure quick-start wording differs from the current code; check the actual script and dry-run output. Arrange evidence capture and identity response separately with the responsible teams.
 Attach or link the tool report and review every reported error . Completion of the script alone does not prove complete containment.
 7. Clean up, verify, and close
 For operational issues, coordinate normal resource cleanup with the owner/platform team. For security incidents, preserve required evidence, remove unauthorized resources and persistence, and address compromised access before restoring service. Follow InfoSec/incident-owner guidance on recovery and evidence retention.
 Verify the live result: unwanted workloads stopped/removed, restart mechanisms addressed, affected access contained or replaced, legitimate service restored as agreed, and no observed recurrence during the agreed verification period. Billing may lag. Do not return a compromised sandbox to the pool until it meets the incident team's cleanup/reuse requirements.
 Before closure, record disposition, evidence, owner contact, actions, verification time/results, linked incidents, and any follow-up with a named owner. If work remains, keep the ticket open or explicitly link the accepted tracking handoff. Follow the existing procedure for post-mortem and final InfoSec communication.
 Ticket behavior and tracking
 One open ticket represents cloud + account/project/subscription ID + alert type . New eligible observations add comments to it, including across billing days. Different alert types on one account can create separate tickets; link related work rather than assuming a deduplication failure. Cloud Enforcement tickets are a separate source.
 After closure, a new eligible observation may create a new ticket. Closing does not disable alerts or create a permanent exception. Repeated legitimate alerts should be reviewed for a scoped filter improvement by the alert maintainers.
 Preserve the cloud-slack-alerts , provider, and correlation labels. Do not delete ticket state or labels to silence alerts.
 Queue JQL:

 project = RHDPSPPT AND labels = "cloud-slack-alerts" AND statusCategory != Done

 Suggested progress note:

 Disposition: legitimate / operational issue / suspected security issue
Target: cloud ID, sandbox, GUID, current owner
Evidence and time period:
Owner contact and response:
Actions taken / authorization:
Verification:
Next action, responsible person, follow-up time:
Related incident / InfoSec / evidence links:

 Examples by alert type
 These cover configured producer types; filters, thresholds, and disabled-alert settings decide whether an observation generates a ticket. Illustrative examples below are not claims of actual incidents. Real tickets show format only; their existence does not establish compromise or resolution.
 Cloud / alert type
 Example
 First checks

 AWS daily_cost 
 Real: RHDPSPPT-1165 , sandbox1440, $268.04 for 2026-10-20
 Workload purpose, billing date, regions, live inventory, non-OCP resource context

 Azure daily_cost 
 Illustrative: subscription exceeds its daily cost threshold
 Subscription owner, service/resource-group cost drivers, expected lab resources

 GCP daily_cost 
 Real: RHDPSPPT-1168 , openenv-w84n2
 Project ownership, billed services, expected workload, live resources

 Azure unassigned_subscription 
 Illustrative: unassigned subscription retains resources or persistent cost
 Current pool assignment, teardown progress, billing lag, cleanup responsibility

 AWS quota_increase 
 Illustrative: request to raise a service quota
 Requesting identity, service/region, planned lab requirement

 AWS marketplace_purchase 
 Illustrative: new paid Marketplace agreement
 Product/vendor, authorized purchaser, agreement terms and continuing charges

 AWS bulk_ec2_launches 
 Illustrative: launch burst exceeds the configured threshold
 Provisioning job, actor, instance types/count, legitimate cluster deployment

 AWS iam_access_key 
 Illustrative: new IAM access key
 User, creator, intended integration, unexplained access changes; never paste the secret

 AWS suspicious_instance_name 
 Illustrative: instance tagged Web-Created-VM
 Actor, launch history, workload/owner confirmation, related enforcement

 AWS bedrock_usage 
 Illustrative: Bedrock API activity
 Expected AI lab, requesting identity, service usage and cost

 AWS sagemaker_resource 
 Illustrative: SageMaker resource creation
 Approved ML workload, resource size, runtime and endpoint/notebook ownership

 AWS emr_cluster 
 Illustrative: EMR cluster creation
 Expected data workload, node count/types, lifecycle and owner

 AWS redshift_cluster 
 Illustrative: Redshift cluster creation
 Authorized database lab, size, region and shutdown plan

 AWS glue_job 
 Illustrative: Glue job run
 Expected ETL workflow, actor, workers/runtime and recurrence

 AWS rds_instance 
 Illustrative: RDS instance creation
 Expected database deployment, class, region and owner

 AWS gpu_instance 
 Illustrative: GPU instance launch
 Approved GPU workload, instance size, scale and expected duration

 AWS capacity_reservation 
 Illustrative: capacity reservation request
 Owner intent, instance type/count, region, usage and continuing reservation cost

 AWS rosa_out_of_scope 
 Illustrative: action denied by an SCP in the ROSA OU
 This reports an attempted action; confirm denial, actor and lab scope before assuming resources were created

 AWS high_instance_count 
 Illustrative: current instance inventory exceeds the threshold
 Expected cluster topology, current counts, owners and unexplained resources; four deployment shards are one alert type

 Troubleshooting
 Problem
 Response

 Missing owner or stale GUID
 Resolve current assignment through provisioning/pool records and Infra before changing the environment

 Parsec unavailable or inconclusive
 Use manual cloud evidence; keep uncertainty and the next action in the ticket

 Owner says legitimate but evidence conflicts
 Continue investigation and escalate according to risk

 Slack says ticket delivery pending
 Search the cloud-alert queue first; ask maintainers to reconcile delivery rather than creating duplicate incidents

 Similar tickets on one account
 Compare cloud, alert type, previous closure, and other automation sources; link related incidents

 Breach tool reports permission errors or resources reappear
 Treat containment as incomplete; review failures/restart mechanisms and escalate

 Cost remains after cleanup
 Compare billing period and fresh resource state; check remaining chargeable resources and delayed billing

 Reference
 Security Incident or Breach Procedure 

 Parsec — Cloud Cost, Security, and Automation Investigation Tool 

 Cloud Slack Alerts ticketing behavior 

 Configured AWS alert handlers 

 Breach Response Tools 

 Reviewed against the alert implementation and response-tool documentation on 2026-10-22 .
