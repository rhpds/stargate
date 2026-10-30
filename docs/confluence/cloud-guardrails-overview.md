# Cloud Guardrails — Cloud Automations & Cloud Slack Alerts (Overview)
# Confluence ID: 451674124
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/451674124

Purpose: A plain-language introduction to the two automated systems that keep the Red Hat Demo Platform's cloud fleet safe, compliant, and cost-controlled.
 Audience: Anyone outside the ops team — other RHDP teams, security, leadership, and partners — who wants to understand what these systems do and why , without the operational detail.

 Why these systems exist
 The Red Hat Demo Platform (RHDP) runs thousands of short-lived "sandbox" cloud accounts and subscriptions across AWS and Azure so that people can run demos, workshops, and labs. That scale creates three constant risks:
 Abuse & compromise — exposed sandboxes get hijacked for crypto mining, botnets, and other attacks.

 Runaway cost — a single mistake or attack can spin up hundreds of expensive VMs in minutes.

 Blind spots — no human can watch thousands of accounts 24/7.

 Cloud Slack Alerts and Cloud Automations are the two automated systems that close those gaps. Together they act as the platform's cloud guardrails: they watch everything, warn a human in real time, and — when needed — act automatically.
 The two systems at a glance
 Cloud Slack Alerts
 Cloud Automations

 Role 
 The eyes — detection & notification
 The hands — enforcement & response

 What it does 
 Watches cloud activity and posts real-time alerts to Slack
 Stops abusive VMs, contains compromised instances, and opens tickets

 Does it change anything? 
 NO — READ-ONLY 
 YES — IT CAN STOP VMS 

 Clouds 
 AWS
 AWS and Azure

 They are intentionally separate: monitoring is safe and always-on, while enforcement is a deliberate, carefully-guarded action.
 Cloud Slack Alerts — the early-warning system
 Cloud Slack Alerts continuously reviews what's happening across the AWS fleet and posts a Slack message the moment it sees something that deserves a human's attention. Examples of what it flags:
 🚨 Root console logins — someone signed in as the all-powerful "root" user (should be rare).

 ⚠️ Bulk VM launches — 10+ servers started at once in one account (a classic sign of crypto mining or abuse).

 🔑 New access keys — creation of long-lived credentials, a common path to account compromise.

 💰 Marketplace purchases — new paid cloud subscriptions, with cost details.

 ⬆️ Service limit increase requests — often a precursor to large-scale resource usage.

 It only observes and notifies — it never changes anything. Its job is to make sure nothing important happens silently.
 Cloud Automations — the responder
 Where Cloud Slack Alerts warns, Cloud Automations acts. It has three main jobs:
 VM limit enforcement (AWS + Azure). It checks running VMs against the expected limits for each account and automatically stops (AWS) or deallocates (Azure) anything over the line. It's smart about context — it knows how many VMs a given lab is supposed to have — and it instantly kills instances matching known-bad patterns (e.g., the crypto-miner name Web-Created-VM ).

 AWS abuse auto-responder. When Amazon sends an abuse report about a hijacked instance, this system automatically investigates it (network traffic, logins, malware scan), contains it , captures forensic evidence, and responds to Amazon, the account owner, and the security team — a process that used to require manual investigation.

 Incident ticketing. For every enforcement action it opens (and de-duplicates) a Jira Service Management incident, so there's always an auditable record and a human can follow up.

 Built-in safety: Cloud Automations always posts to Slack before it acts , only stops VMs (never deletes them, so they can be recovered), removes the newest VMs first, and ships in a "dry-run" mode that must be explicitly turned off.

 How they work together

 Something happens in the cloud
 |
 +---------+---------+
 | |
Cloud Slack Alerts Cloud Automations
(sees it, posts (evaluates it, and if it
 to Slack) breaks the rules...)
 |
 1. Posts to Slack <- human sees it in real time
 2. Opens a Jira incident <- auditable record
 3. Stops / contains the VM <- the actual fix

 Both systems post to the same Slack channel and share a common "already handled this" memory, so the team sees one coherent story rather than duplicate noise.
 System architecture diagram
 The diagram below shows the full flow: a cloud event feeds both systems; Cloud Slack Alerts (blue) observes and posts; Cloud Automations (red) detects, applies rules, and acts; and both converge on a common set of shared services (grey) — Slack, the shared dedup table, Jira, and Babylon.

 Cloud Guardrails end-to-end architecture: observe (blue), enforce and respond (red), and shared services (grey). 
   draw.io source (to edit: Insert → draw.io, then Extras → Edit Diagram, paste this) 

 <mxGraphModel dx="1000" dy="760" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1100" pageHeight="760" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Cloud activity across the AWS + Azure fleet (thousands of sandbox accounts)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#666666;fontStyle=1;fontSize=13;" vertex="1" parent="1"><mxGeometry x="300" y="20" width="500" height="40" as="geometry"/></mxCell><mxCell id="10" value="Cloud Slack Alerts — observe (read-only)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E6F2FF;strokeColor=#4C9AFF;verticalAlign=top;align=center;fontStyle=1;fontSize=13;spacingTop=8;" vertex="1" parent="1"><mxGeometry x="40" y="90" width="440" height="400" as="geometry"/></mxCell><mxCell id="11" value="Cloud Automations — enforce and respond" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF0EE;strokeColor=#FF5630;verticalAlign=top;align=center;fontStyle=1;fontSize=13;spacingTop=8;" vertex="1" parent="1"><mxGeometry x="520" y="90" width="460" height="400" as="geometry"/></mxCell><mxCell id="20" value="EventBridge (every ~5 min)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#4C9AFF;" vertex="1" parent="1"><mxGeometry x="70" y="140" width="180" height="40" as="geometry"/></mxCell><mxCell id="21" value="EventBridge (daily cache)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#4C9AFF;" vertex="1" parent="1"><mxGeometry x="280" y="140" width="170" height="40" as="geometry"/></mxCell><mxCell id="22" value="6 alert Lambdas + 1 cache Lambda" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#4C9AFF;" vertex="1" parent="1"><mxGeometry x="70" y="210" width="180" height="50" as="geometry"/></mxCell><mxCell id="23" value="CloudTrail Lake" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#4C9AFF;boundedLbl=1;" vertex="1" parent="1"><mxGeometry x="290" y="205" width="150" height="60" as="geometry"/></mxCell><mxCell id="24" value="DynamoDB caches (accounts, marketplace)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#4C9AFF;" vertex="1" parent="1"><mxGeometry x="70" y="300" width="180" height="50" as="geometry"/></mxCell><mxCell id="25" value="Parsec (alert enrichment)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#4C9AFF;" vertex="1" parent="1"><mxGeometry x="290" y="300" width="150" height="50" as="geometry"/></mxCell><mxCell id="30" value="EventBridge (5 min, AWS)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#FF5630;fontSize=10;" vertex="1" parent="1"><mxGeometry x="540" y="140" width="135" height="40" as="geometry"/></mxCell><mxCell id="31" value="Timer (5 min, Azure)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#FF5630;fontSize=10;" vertex="1" parent="1"><mxGeometry x="685" y="140" width="130" height="40" as="geometry"/></mxCell><mxCell id="32" value="Abuse email → SES → SNS" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#FF5630;fontSize=10;" vertex="1" parent="1"><mxGeometry x="825" y="140" width="140" height="40" as="geometry"/></mxCell><mxCell id="33" value="Enforcement compute: EC2 Lambda · Azure VM Function · abuse-responder Lambda" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#FF5630;" vertex="1" parent="1"><mxGeometry x="540" y="210" width="425" height="50" as="geometry"/></mxCell><mxCell id="34" value="Detect: CloudTrail Lake (AWS) · Resource Graph (Azure)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#FF5630;" vertex="1" parent="1"><mxGeometry x="540" y="290" width="205" height="50" as="geometry"/></mxCell><mxCell id="35" value="DynamoDB enforcement_rules (+ S3 fallback)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#FF5630;" vertex="1" parent="1"><mxGeometry x="760" y="290" width="205" height="50" as="geometry"/></mxCell><mxCell id="36" value="Act: stop (AWS) / deallocate (Azure) / contain + forensics" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#FF5630;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="540" y="380" width="425" height="50" as="geometry"/></mxCell><mxCell id="40" value="Shared services" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F4F5F7;strokeColor=#8993A4;verticalAlign=top;align=center;fontStyle=1;fontSize=13;spacingTop=8;" vertex="1" parent="1"><mxGeometry x="40" y="520" width="940" height="170" as="geometry"/></mxCell><mxCell id="41" value="Slack channel" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#36B37E;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="80" y="585" width="180" height="55" as="geometry"/></mxCell><mxCell id="42" value="DynamoDB dedup: cloud-slack-alerts-seen-events" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#8993A4;boundedLbl=1;" vertex="1" parent="1"><mxGeometry x="310" y="580" width="210" height="65" as="geometry"/></mxCell><mxCell id="43" value="Jira Service Management incidents" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#8993A4;" vertex="1" parent="1"><mxGeometry x="570" y="585" width="180" height="55" as="geometry"/></mxCell><mxCell id="44" value="Babylon multi-cluster lookup (6 clusters)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#8993A4;" vertex="1" parent="1"><mxGeometry x="790" y="585" width="170" height="55" as="geometry"/></mxCell><mxCell id="e1" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="10"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e2" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="11"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e3" value="trigger" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="20" target="22"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e4" value="query" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="22" target="23"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e5" value="enrich" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="22" target="24"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e6" value="investigate" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="22" target="25"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e7" value="refresh" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="21" target="24"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e8" value="post" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="22" target="41"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e9" style="endArrow=classic;html=1;" edge="1" parent="1" source="30" target="33"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e10" style="endArrow=classic;html=1;" edge="1" parent="1" source="31" target="33"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e11" style="endArrow=classic;html=1;" edge="1" parent="1" source="32" target="33"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e12" value="detect" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="33" target="34"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e13" value="load rules" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="33" target="35"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e14" value="then" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="34" target="36"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e15" value="1. notify" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="36" target="41"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e16" value="2. ticket" style="endArrow=classic;html=1;fontSize=9;" edge="1" parent="1" source="36" target="43"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e17" value="owner lookup" style="endArrow=classic;html=1;dashed=1;fontSize=9;" edge="1" parent="1" source="33" target="44"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e18" value="dedup" style="endArrow=classic;html=1;dashed=1;fontSize=9;" edge="1" parent="1" source="22" target="42"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="e19" value="dedup" style="endArrow=classic;html=1;dashed=1;fontSize=9;" edge="1" parent="1" source="33" target="42"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel>

 Technical architecture (deep dive)

 This section is for engineers and reviewers who want the internals. Each subsystem is collapsed below — expand only what you need. Everything here is summarized from the dedicated repo/ops pages linked at the bottom.

 Both systems are serverless, event-driven, and deployed entirely via Ansible . There are no long-running servers to patch — compute exists only for the few seconds each cycle runs. Configuration is data (JSON in DynamoDB), not code, so behavior can change without a redeploy.
   Cloud Slack Alerts — internals 
 Compute model. Five alert Lambda functions (one per alert type) plus one cache Lambda, all packaged in a single shared zip with different handler entry points. Running each alert as its own function lets them execute in parallel — important because each CloudTrail Lake query takes ~30 seconds, and a single serial function would time out.
 Triggering. Amazon EventBridge fires all alert Lambdas on a schedule (default: every 5 minutes, configurable). A second daily EventBridge rule drives the cache-refresh Lambda.
 Data & enrichment. Each alert Lambda queries a CloudTrail Lake event data store for recent events, then enriches the raw rows with human-friendly context — account names from a DynamoDB table, and AWS Marketplace product names from a DynamoDB cache that the daily Lambda rebuilds by querying the Cost & Usage Report (CUR) via Athena.

 EventBridge (every N minutes)
 |
 +--> quota-increase-alert Lambda
 +--> root-login-alert Lambda
 +--> marketplace-purchase-alert Lambda
 +--> bulk-ec2-launches-alert Lambda
 +--> iam-access-key-alert Lambda
 |
 Each Lambda: query CloudTrail Lake -> enrich from DynamoDB -> post to Slack webhook

EventBridge (daily)
 +--> marketplace-cache-refresh Lambda (CUR via Athena -> DynamoDB)

 Key design decisions. Parallel execution avoids the ~30s query timeout; all Lambdas share one zip with different handlers; no dependencies beyond the boto3 already in the Lambda runtime; and two IAM roles separate alert permissions (CloudTrail, Organizations, STS, DynamoDB, ServiceQuotas, Cost Explorer) from cache permissions (Athena, S3, Glue, DynamoDB).
 Component
 Purpose

 5 alert Lambdas
 One per alert type, same zip, different handler

 1 cache Lambda
 Daily refresh of marketplace product-name cache

 2 EventBridge rules
 Alert schedule (every N min) + cache schedule (daily)

 1 DynamoDB table
 Marketplace product-name cache

 2 IAM roles
 Alert role + cache role (least-privilege split)

   Cloud Automations — AWS enforcement path 
 An EventBridge rule triggers the ec2-instance-limit-enforcement Lambda (512 MB, Python 3.12) every 5 minutes:

 EventBridge (every 5 minutes)
 +--> ec2-instance-limit-enforcement Lambda
 1. Load enforcement rules from DynamoDB
 2. Query CloudTrail Lake (RunInstances, last 2h)
 3. Filter to accounts in configured OUs or groups
 4. AssumeRole into matched accounts -> DescribeInstances
 5. Check per-class thresholds + banned instance names
 6. Slack notification -> stop excess instances (newest first)

 Targeting. Rules apply either to an entire Organizations OU (e.g. restricted , covering 1000+ accounts, with per-instance-class thresholds and wildcard match patterns like g4dn.* ) or to a dynamic group of sandbox accounts identified by a DynamoDB comment field.
 Access. Cross-account reach is via STS AssumeRole into each matched account, per region. Owner attribution comes from a DynamoDB accounts table. Enforcement uses stop_instances() (recoverable), newest-first.

   Cloud Automations — Azure enforcement path 
 A timer-triggered Azure Function ( azure_vm_limit , Python 3.12, consumption plan) runs every 5 minutes:

 Timer Trigger (every 5 minutes)
 +--> azure_vm_limit Azure Function
 1. Load enforcement rules from DynamoDB (cross-cloud)
 2. Resource Graph query (all running VMs, single query, ~2s)
 3. Filter to subscriptions in management groups
 4. Pool Handler API -> Babylon ResourceClaim -> catalog item
 5. Compare against expected VM count (catalog expectations cache)
 6. Slack notification -> deallocate excess VMs (newest first)

 Why deallocate, not stop? In Azure, a merely "stopped" VM still bills; only deallocate releases the compute and stops charges.
 Targeting & access. Scope is by management group ( rhpds-pool-00 ~31 subs, rhpds-pool-01 ~401 subs). A single service principal with custom RBAC roles (VM read + deallocate) reaches all subscriptions — no per-account role assumption. Owner/catalog lookup goes through the Pool Handler API to a Babylon ResourceClaim.
 Aspect
 AWS
 Azure

 Detection
 CloudTrail Lake (event-based, 2h lookback)
 Resource Graph (live state, single query)

 Targeting
 OU + DynamoDB group
 Management group

 Cross-account auth
 STS AssumeRole per account
 Single service principal via RBAC

 Enforcement
 stop_instances() 
 deallocate (to stop billing)

 Region handling
 Per-region API calls
 Global query

 Owner lookup
 DynamoDB accounts table
 Pool Handler API -> Babylon

   Catalog-item-aware thresholds (how it knows the "right" VM count) 
 For managed catalog items (not blank "open environment" sandboxes), a flat VM limit would be wrong — an ARO lab legitimately runs many VMs. The system therefore derives an expected VM count per catalog item from two sources, plus a buffer:
 Labagator resource discovery — infrastructure VMs (bastion, workers, control plane) read from AgnosticV CRDs.

 LLM adoc parsing — user-created VMs inferred from Showroom lab instructions, parsed with Vertex AI / Claude Sonnet.

 Overage buffer — +2 VMs above expected to absorb provisioning-timing variations.

 The result is cached in DynamoDB ( catalog_resource_expectations ), built by scripts/build_catalog_expectations.py . GUID → catalog-item resolution walks 6 Babylon clusters (east first).

   Cloud Automations — AWS abuse auto-responder pipeline 
 Triggered not on a schedule but by an actual AWS abuse email. The mail path uses a Postfix sender_bcc_maps rule on mx02/mx03.opentlc.com to BCC a copy of anything from ec2-abuse@amazon.com to an SES intake address:

 AWS Abuse Email -> opentlc mailbox
 -> mx02/mx03 Postfix sender_bcc_maps (BCC copy)
 -> abuse-intake@ses.rhdp.net
 -> SES receiving rule -> S3 bucket
 -> SNS topic -> Lambda (abuse-responder)
 1. Parse email (account_id, region, instance_id, case_number)
 2. Resolve sandbox name + owner from DynamoDB accounts table
 3. STS AssumeRole -> OrganizationAccountAccessRole in sandbox
 4. Investigate: CloudTrail, CloudWatch metrics, security groups, IP geolocation
 5. Contain: stop instance, attach deny-start IAM policy
 6. Forensic snapshots: create, tag, share with infosec account
 7. Disk forensics via SSM on a temporary forensic instance:
 SSH config, password cracking, auth-log brute-force detection,
 bash history, crontab persistence, YARA-X scan (13 malware rules)
 8. Clean up all forensic resources
 9. Reply to ec2-abuse@amazon.com (preserves subject for threading)
 10. Email sandbox owner (CC infosec-aws-abuse@redhat.com)
 11. Post to Slack with findings, snapshots, owner
 12. Dedup via DynamoDB (30-day TTL per account+instance)

 The Lambda runs with a 15-minute timeout, 1 GB memory, and concurrency limited to 1 (no parallel runs). Every step is idempotent — a re-run skips an already-stopped instance, an already-attached deny policy, or existing tagged snapshots. Risk is scored HIGH on sustained traffic >100 MB/hr for 6+ hours. The same investigation logic ships as a standalone CLI ( rhpds/breach_response ) for manual use.

   Shared services & cross-cutting integration 
 Shared component
 Role across systems

 DynamoDB enforcement_rules 
 Single source of enforcement config; both clouds read it (with an S3 JSON fallback for AWS)

 DynamoDB catalog_resource_expectations 
 Per-catalog-item expected VM counts

 DynamoDB cloud-slack-alerts-seen-events 
 Shared dedup table — the abuse responder and Cloud Slack Alerts both use it (30-day TTL) so nothing is double-reported

 Babylon multi-cluster lookup
 6 clusters (east first); GUID → catalog item + owner resolution

 Parsec
 Cloud Slack Alerts calls Parsec's POST /api/alert/investigate to enrich an alert before it posts

 Slack webhook
 Shared notification channel for both systems

 Jira Service Management
 Incidents created via Jira REST API v3 over urllib (no SDK); dedup by composite labels ( cloud-enforcement , acct-{id} , violation-{type} , cloud); tickets are never auto-closed

 Configuration & safety model. Rule changes take effect on the next cycle (~5 min) with no redeploy. Enforcement ships DRY_RUN=true by default and can be toggled per-function at runtime. Jira ticketing has a two-layer kill switch — a deploy-time env var ( JIRA_ENABLED ) and a runtime config flag in the rules JSON — and every Jira call is wrapped non-fatally so an API hiccup never blocks enforcement or the Slack post.
 Layer
 Cloud Slack Alerts
 Cloud Automations

 AWS compute
 Lambda × 6 (Python 3.12)
 Lambda (512 MB) + abuse-responder Lambda (1 GB)

 Azure compute
 —
 Function App (consumption plan, Python 3.12)

 Trigger
 EventBridge schedule
 EventBridge / Timer / SES→SNS (abuse)

 State & config
 DynamoDB caches
 DynamoDB rules + S3 fallback; Secrets Manager / Key Vault for kubeconfigs

 Deploy
 Ansible
 Ansible (+ Azure Functions Core Tools)

 What this means for you
 Security: Compromised and abusive workloads are caught and contained in minutes, often before a human is even aware.

 Cost control: Runaway and over-limit VMs are stopped automatically, protecting the platform budget.

 Compliance & auditability: Every enforcement action leaves a Slack message and a Jira incident behind.

 Peace of mind: The platform is watched 24/7 without anyone having to stare at dashboards.

 Learn more (detailed / ops documentation)
 Cloud Slack Alerts — architecture, alert types, deployment

 Cloud Automations — VM Enforcement 

 Cloud Automations — AWS Abuse Report Auto-Responder 

 Guide: Automating JSM Incident Ticket Creation 

 Parsec — Cloud Cost, Security & Automation Investigator (the tool that enriches alerts before they post)

 Infrastructure - Applications (the full app catalog)
