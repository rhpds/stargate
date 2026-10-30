# Self-Paced &amp; Multi-Asset Labs — Operations Guide
# Confluence ID: 510329345
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/510329345

Reusable operations guide for self-paced & multi-asset labs at booth events — the evergreen background, constraints, and procedures split out of the per-event runbooks so they can be referenced from any event. Event-specific schedules, sessions, and live status live in each event runbook (e.g. the IBM Tech Exchange runbook).

 Key Constraints & Background
 Constraint
 Detail

 6-hour auto-stop — instances CANNOT be restarted 
 Agnostic B enforces a hardcoded 6-hour auto-stop on instances. Once an instance is stopped by this limit, it cannot be restarted — it is unrecoverable without reprovisioning. Root cause location under investigation by Aleix. First surfaced on the Ansible Event-Driven Architecture lab during booth testing.

 Rebuild vs Stop — the critical distinction 
 If an instance's lifespan expires naturally (via assigned/unassigned lifespan config), it rebuilds (reprovisions fresh). If it hits the 6-hour Agnostic B auto-stop instead, it stops and cannot be restarted . The lifespan workaround below ensures instances always expire naturally — never via the auto-stop.

 Pool size decrease does NOT remove instances 
 Decreasing the pool size in Admin Ops Control does not automatically remove existing instances. You must manually delete them. Increasing the pool size does spin up new instances automatically.

 UI minimum pool size is 1 
 The pool size field in Admin Ops Control has a minimum value of 1 — it is not possible to set pool size to 0 via the UI. To fully deprovision overnight, set pool size to 1 and manually delete all remaining instances.

 Lab types on tenant clusters 
 Some labs use regular instances; others use cluster tenants. Self-paced currently supports OpenShift labs and AI labs on tenant clusters. Tenant labs require separate pool management (see Procedure 3).

 Tenant pool isolation 
 Each catalog item requires its own separate tenant pool . Sharing pools across items results in too many clusters per item — a waste of resources.

 Seat availability feature 
 Developed by Aleix Casanovas. Released: TO CONFIRM. Shows number of available seats per self-paced lab in the UI.

 Procedure 1 — Configure Instance Lifespan (Booth Events)
 The 6-hour Agnostic B auto-stop cannot be overridden directly. The workaround is to set instance lifespans to expire at or before the 6-hour limit is reached, so instances rebuild naturally rather than stop unrecoverably.
 Critical: If an instance hits the 6-hour auto-stop, it cannot be restarted . An attendee arriving at a stopped instance gets no lab. Setting lifespans at or below 6 hours ensures instances always rebuild on their own — never stop permanently.

 Lifespan Rules
 Setting
 Hard Constraint
 Recommended Value
 Effect

 Unassigned Lifespan 
 Must not exceed 6 hours (Agnostic B auto-stop fires at 6h)
 6 hours
 Idle, unclaimed instances rebuild at or before 6 hours, preventing the auto-stop from firing. Instances remain available throughout the event day.

 Assigned Lifespan 
 No hard constraint — any duration
 6 hours
 Instances assigned to an attendee expire after 6 hours, giving them the full available session time before the auto-stop could fire.

 Steps
 Navigate to the catalog item in Admin Ops Control .

 Set Unassigned Lifespan to 6 hours (must not exceed 6 hours — do not leave at default).

 Set Assigned Lifespan to 6 hours (or the full intended session duration, up to 6 hours).

 Set the pool size to the desired number of ready instances.

 Save and verify settings are applied.

 Pool size change behaviour: Increasing pool size spins up new instances automatically. Decreasing pool size does NOT remove existing instances — you must manually delete them from the services view. The UI minimum pool size is 1; setting pool size to 0 is not permitted. 

 When Aleix identifies the Agnostic B config source, it may become possible to disable the 6-hour auto-stop directly — which would remove the need for this lifespan workaround. Check back after that investigation closes.

 Procedure 2 — Scale Instances Outside Booth Hours
 To control cloud costs when the booth is closed, assign someone each day to execute the scale-down at close and scale-up before open. This must be explicitly assigned — it will be missed if left to chance.
 Cost control: AI inference labs incur active cloud costs even when idle. Scale these to the minimum (1) overnight and manually delete all remaining instances . Note: the UI does not permit setting pool size to 0 — the lowest value permitted is 1. Standard OCP and non-inference labs can remain at minimum (1 or 3 per event configuration).

 End of Day — Scale Down
 In Admin Ops Control, navigate to the event namespace services view.

 Scale AI inference labs to the minimum (1) — the UI does not permit 0.

 Scale all remaining labs down to minimum (1).

 Set pool size to 1 (the minimum permitted by the UI) for each lab.

 Manually delete all remaining instances — setting pool size alone does not remove them. Stopped instances still hold reserved cluster capacity.

 Confirm the services view shows no running or stopped instances outside the intended minimum.

 Start of Day — Scale Up
 At least 15–20 minutes before the booth opens , increase pool size to booth minimum for all labs.

 Scale AI inference labs first — they take the longest to become ready and must be up before doors open.

 Verify all instances are in a running state before doors open.

 Lab Type
 Overnight Setting
 Booth Minimum

 AI inference labs (AI Factory, Word Swarm, Voice Agents, etc.)
 1 (UI minimum; manually delete remaining instances after scaling)
 5 (or as configured per event)

 OCP and standard labs
 Minimum (1)
 3 (or as configured per event)

 Procedure 3 — Tenant Cluster Pool Management
 Applies to labs using tenant clusters (currently: OpenShift labs and AI labs). Regular instance labs do not require this procedure.
 Key rules: 
1. Never share a tenant pool across catalog items — each item gets its own dedicated pool.
2. Self-service clusters must fully deploy before tenant instances begin provisioning.

 Setting Up a New Tenant-Based Self-Paced Lab
 Confirm a dedicated tenant pool exists for the catalog item at Admin → Tenant Cluster Pools . Create one if not present.

 Deploy self-service clusters first and wait for running state before provisioning tenant instances.

 Set pool count to at least 2 for self-service clusters to handle concurrent deployments.

 Set the tenant instance lifespan to 30 minutes . This ensures instances are deleted regularly, freeing space on the cluster. With 30-minute lifetimes, a single cluster per item is typically sufficient — instances turn over before the cluster fills.

 Monitor pool status — if a cluster fails, delete all failed tenants and the cluster before redeploying. Do not redeploy onto a failed state.

 Self-Service vs Tenant Deploy Order
 Step
 Action
 Notes

 1
 Deploy self-service clusters
 Must reach running state first — tenant deploys fail if self-service is not ready

 2
 Verify pool counts
 Start with 2 per pool; increase based on demand during the event

 3
 Begin tenant instance provisioning
 Max placement per cluster is typically 10–15; monitor for failures

 4
 Delete failed tenants and clusters before redeploying
 Never redeploy on top of a failed state
