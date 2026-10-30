# RHDP Event Ops — Runbook Master Plan
# Confluence ID: 485195854
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/485195854

RHDP Event Ops — Runbook Master Plan
 This document sets the standard for all event runbooks (Tech Day + Summit Connect). 
Every event runbook must follow this structure. It evolves based on lessons learned — update it when a new issue is found and fixed.
 Last updated: September 24, 2026 — Labagator Ops hub (Runbooks + signal board) shipped; Flow + Admin Ops pane of glass.
 Trackers: GPTEINFRA-18020 · RHDPOPS-24389 · tooling epic RHDPOPS-24380 
 What this covers
 This master plan applies to all hands-on workshop events run by the RHDP Ops team:
 Tech Days — city-based full-day events (4 workshops, TD01–TD04 codes)

 Summit Connects — venue-based events with pool-based deployment (LB codes)

 Where operators work (Labagator Ops)
 Labagator → Operations is the single pane of glass for a selected event :
 Surface
 What you get
 Business value

 Signal board 
 Event-scoped Flow job rollup + Admin Ops session attention
 Managers see in-flight / failed / attention without opening three UIs

 Deploy Monitor 
 Existing deploy visibility for the event
 Day-of deploy tracking stays in one place

 Event Runbooks 
 Day stubs from schedule/handoff; deep-links to Flow + Admin Ops; download MD; push OPS Sheets
 Prep starts from Labagator schedule truth before Confluence publish

 Tool map (do not merge jobs): 
 Tool
 Job

 Labagator 
 Event schedule truth + runbook draft + Ops signal board

 Flow 
 Deploy + QA (catalog → setup → deploy)

 Admin Ops 
 Day-2 lifecycle (lock / extend / scale / redeploy + status)

 Confluence 
 Published runbook read surface (master plan + per-event pages)

 Shipped (Sept 2026): Labagator PRs #56 (Runbooks hub), #57 (signal board), #58 (Ops UI = Flow + Admin Ops only).
 Still Phase 2: Generate per-day Confluence pages under the OPS folder + live-status auto-patch ( Live deploy status (auto-updated) ). Labagator drafts and Sheets push are live; Confluence publish from Labagator is next.
 Required Phases
 Every event runbook must include these phases in order. No phase may be skipped.
 Phase
 Name
 Gate to next phase

 Phase 1 
 Schedule Workshops
 All workshops scheduled, CSV PR merged

 Phase 1b 
 Provisioning QA — Sign-off Required
 Named owner signs off all parameter checks

 Phase 2 
 Landing Page Testing
 All workshops visible and redirect correctly

 Phase 3 
 Seat Testing + Showroom Check
 Named testers passed; showroom check complete

 Phase 4 
 Final Verification
 All above complete, team confirmed ready

 Phase 1: Schedule Workshops
 All workshops must be scheduled with correct namespaces and capacity

 Landing page CSV must be updated and PR merged before Phase 2

 Owner field: Must be a named person in the runbook — not "TBD". Responsibility in Jira tickets is supplementary, not a substitute.
 Labagator: Use Event Runbooks → day stub (labs / NS / seats from deploy handoff) as the draft source of truth for the schedule table.
 Phase 1b: Provisioning QA — Sign-off Required
 This phase was introduced after the Detroit Tech Day incident (Sept 23 2026) where TD01 had instances set to 1 instead of 82, and auto-stop was misconfigured. These issues were not caught until day-of, causing disruption for 3 separate workshops on the same day.
 Owner: A named person responsible for verifying every workshop.
 Sign-off: A written sign-off (name + datetime) in the runbook. Phase 2 cannot begin without it.
 Checks for every workshop: 
 Instance count — Open the service link. Verify the number of instances matches what's expected. Do not assume it is correct just because the workshop was scheduled.

 Auto-stop — Verify the auto-stop time is set correctly (typically event end + buffer). Do not leave it unset or at the default.

 Password — Verify the password matches what will be shared with the presenter.

 Namespace — Verify the workshop is in the correct namespace.

 Status — Verify the workshop is in Scheduled or Running state, not Failed.

 Tool: Use Admin Ops Control (also linked from Labagator Ops → Event Runbooks) to monitor and verify provision status across all workshops at a glance. Reference it in both Phase 1b and day-of monitoring.
 Phase 2: Landing Page Testing
 Visit the landing page and verify each workshop is visible

 Click through and verify redirect and password flow work

 Do this in a browser where you are not already logged in as admin

 Phase 3: Seat Testing + Showroom Check
 Seat Testing
 2–3 ops team members each provision and test a different workshop

 Testers must be named in the runbook (not "TBD")

 A lab counts as "tested" when: ordered, deployed, accessed, and confirmed working

 Showroom / Environment Check
 This applies to all events — not just Summit or RH1 events.
 Actually open the workshop environment (not just verify it's "Running" in the catalog)

 Verify the workshop password works

 Verify attendees can navigate to the first step

 This catches issues that seat testing misses (broken content, missing assets, session timeouts)

 Responsible: A named person in the runbook.
 Phase 4: Final Verification
 A final checklist confirming all phases are complete. Must explicitly include a check that Phase 1b (Provisioning QA) has been signed off before marking the event as ready.
 Assignments in the Runbook
 Responsibility must be named in the runbook itself , not only in Jira.
 Jira tickets are useful for tracking overall delivery status. The runbook is the live operational document — it should answer "who is doing this?" directly.
 Each phase header should include: 
 Owner: [NAME] — a specific person

 Sign-off line where required (Phase 1b mandatory)

 Monitoring: Admin Ops + Labagator signal board
 Admin Ops Control remains the primary day-2 monitoring tool for workshop provision status.
 Labagator Ops signal board (same event in the masthead) adds Flow deploy/QA job rollups and Admin Ops session attention so managers see risk early without tab-hopping.
 Use Admin Ops to:
 Verify instance counts are correct after scheduling

 Monitor provision progress in the hours before the event

 Quickly identify Failed or Stuck provisions without clicking through individual service links

 Reference it explicitly in Phase 1b and in any day-of monitoring guidance.
 Lessons Learned
 Event
 Issue
 Fix incorporated

 Summit Connect New York (Sep 2026)
 Image mode workshop environment broken — not caught pre-event
 Showroom check added to Phase 3 for all events

 Tech Day Detroit (Sep 23 2026)
 TD01 instances set to 1 instead of 82 — caught day-of
 Phase 1b Provisioning QA mandatory gate added

 Tech Day Detroit (Sep 23 2026)
 Auto-stop not configured correctly
 Auto-stop check added to Phase 1b

 Tech Day Detroit (Sep 23 2026)
 No named owners on phases or Jira tickets
 Inline Owner + sign-off fields added to all phases

 Platform (Sep 24 2026)
 Ops context scattered across Sheets / Flow / Admin
 Labagator Ops hub: Runbooks + Flow/Admin Ops signal board

 Templates
 Tech Days: Red Hat Tech Days 2026 - Ops Runbook Template 

 Summit Connect: Summit Connect 2026 - Ops Runbook Template 

 Update this document each time a new issue is found and resolved. The lessons learned table is the most important part. 
 Owner: Billy Bethell
