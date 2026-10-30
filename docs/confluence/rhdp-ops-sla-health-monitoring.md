# RHDP Operations — SLA Health & Monitoring
# Confluence ID: 504726329
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/504726329

Living SLA dashboard for the RHDP Operations service desk (project RHDPSPPT ). The queues below are live Jira macros — they refresh when this page loads. Based on a 180-day review of 673 resolved tickets (2026-04-20 → 2026-10-16).
 Health at a glance
 Metric
 Value
 Status

 Acknowledge SLA (MTTA) breach rate
 30.4% 
 GOAL 8H — WORST METRIC, TRENDING UP 

 Resolution SLA (MTTR) breach rate
 20.2% 
 GOAL 48H FOR MOST TYPES 

 Resolved with no assignee
 19.6% 
 NO OWNERSHIP TRAIL 

 Tickets with no request type
 54 
 UNCATEGORISED / MIS-SLA'D 

 Median wall-clock resolution
 28.5h 
 HALF OF TICKETS CLOSE WITHIN A DAY 

 Source mix (Slack vs JSM portal vs email)
 TBD 
 COLLECTION IN PROGRESS — SEE PLAN 

 The verdict
 The service desk works, but flies blind. Half of all tickets close within a day, yet there is no priority-based SLA, no breach alerting, and no routine reporting — so misses surface only when someone complains. Three structural problems:
 1 · Flat SLAs. Targets are keyed to request type, not urgency — a Blocker gets the same 48h resolution goal as a routine Medium. 88% of tickets are "Medium", so priority is doing no work.
 2 · Acknowledge gap. 30.4% miss the 8h acknowledge goal (45.1% this month). Median ack is fine (2.9h) — the pain is a long tail of ignored tickets, exactly what alerting would catch.
 3 · Blind spots. 19.6% close unassigned and 54 have no request type, so workload and demand reporting are unreliable at the source.
 SLA performance & demand — 180-day analysis
 The charts below render natively from the same 673-ticket dataset (2026-04-20 → 2026-10-16). Bar length is proportional within each table; hover values are shown inline.
 SLA breach rate over time
 Acknowledge (MTTA) is consistently the weaker metric, and both spiked in May (onboarding surge) and again this month. Bars scale to the series maximum.
 Month
 Resolved
 MTTA breach
 MTTR breach

 2026-04 
 ███ 40
 ████████████████ 40.0%
 ███ 7.5%

 2026-05 
 ████████ 101
 ██████████████████ 44.6%
 ████████████████ 39.6%

 2026-06 
 ██████████ 120
 ████████ 20.0%
 ██████ 14.2%

 2026-07 
 ████████ 96
 ███████ 16.7%
 █████████ 21.9%

 2026-08 
 ██████████ 122
 ███████████ 26.4%
 ███████ 16.4%

 2026-09 
 ██████████ 123
 █████████████ 31.7%
 ██████ 14.6%

 2026-10 
 ██████ 71
 ██████████████████ 45.1%
 ██████████ 23.9%

 Time to acknowledge (MTTA)
 Median 2.9h is healthy — the problem is the long tail. Goal = 8h; everything slower is a breach.
 Bucket
 Tickets

 <1h
 ██████████████████ 246

 1-4h
 █████████ 124

 4-8h
 ███████ 98

 8-24h BREACH 
 ██████████ 143

 1-3d BREACH 
 █ 12

 3d+ BREACH 
 ████ 49

 Wall-clock time to resolve
 Created → resolved, real elapsed time. Median 28.5h — half of all tickets close within a day.
 Bucket
 Tickets

 <4h
 ██████████████████ 200

 4-24h
 ███████████ 121

 1-3d
 ██████████ 116

 3-7d
 ████████████ 138

 1-4w
 ████████ 94

 1mo+
 █ 4

 Demand — what the queue is made of
 Technical Support and White Glove Workshops are two-thirds of volume. MaaS Support and the uncategorised bucket carry the highest acknowledge-breach rates.
 Request type
 Tickets (180d)
 MTTA breach
 MTTR breach
 Median resolve (SLA h)

 Technical Support
 ████████████ 279
 28.1%
 23.7%
 8.8

 White Glove Workshops
 ████████ 190
 36.3%
 22.1%
 14.7

 MaaS Support
 ███ 61
 39.3%
 26.2%
 19.6

 Developer Support - Asset Onboarding
 ██ 54
 0.0%
 0.0%
 —

 (no request type)
 ██ 54
 59.3%
 20.4%
 11.5

 Submit Feedback/Feature Request
 █ 32
 3.1%
 3.1%
 —

 ZT Onboarding Request
 █ 2
 0.0%
 0.0%
 40.8

 Source of tickets — Slack vs JSM queue vs email
 Planned metric — data collection in progress. We want full visibility into where tickets originate. Slack-originated tickets may surface faster but get less-structured intake; portal submissions go through the form but can stall in the queue unnoticed.

 Source
 Expected share
 Notes

 JSM portal (customer submits directly)
 TBD
 Structured intake, has request type — should have lowest no-type rate

 Slack integration (Atlassian Assist / bot)
 TBD
 Higher volume, faster creation, less structured — likely higher breach rate

 Email handler
 TBD
 Often arrives with no request type or priority set

 API / automation
 TBD
 System-generated; should be excluded from SLA reporting

 To populate: query JSM channel field or reporter pattern for the Slack-Google-Jira bot. Track source as a permanent column in all live queue views. 
 Priority mix — the SLA design flaw
 Priority
 Tickets
 Share

 Medium 
 ██████████████ 590
 87.7%

 Minor 
 █ 54
 8.0%

 High 
 █ 15
 2.2%

 Blocker 
 █ 9
 1.3%

 Low 
 █ 5
 0.7%

 87.7% of tickets are "Medium". Because the SLA goal is keyed to request type and not priority, that label does no work — and the genuinely urgent 3.5% (High/Blocker) get no faster target than routine work.
 Team workload — resolved by assignee (top 12)
 Load is concentrated in a handful of people. Separately, 132 tickets (19.6%) closed with no assignee — roughly one in five resolutions has no owner on record.
 Assignee
 Resolved tickets

 Harsh Arora
 ██████████████ 104

 Billy Bethell
 ████████████ 86

 Victor Aguilera
 ██████████ 78

 Chandrabose Bomman
 ██████████ 75

 Ashok Jammula
 ███████ 53

 Perry Rivera
 ████ 32

 Kadeem Lewis
 ████ 31

 Ahsen Shah
 ████ 28

 Josh Disraeli
 ████ 26

 John Apple II
 █ 9

 Dibyendu Jana
 █ 9

 slack-google-jira bot
 █ 4

 Live SLA queues
 Breaching now
 Open tickets that have already missed an SLA — work these first.
 Error rendering macro 'jira' : Macro params are invalid
 At risk
 Open, not yet breached, <24h resolution or <2h acknowledge left.
 Error rendering macro 'jira' : Macro params are invalid
 Unassigned open
 Open tickets with no owner.

 type 
 key 
 summary 
 assignee 
 reporter 
 priority 
 status 
 resolution 
 created 
 updated 
 due 

 Loading... 

 Refresh 

 <ac:parameter ac:name="showSummary">true</ac:parameter><ac:parameter ac:name="jqlQuery">project = RHDPSPPT AND statusCategory != Done AND assignee is EMPTY ORDER BY created ASC</ac:parameter><ac:parameter ac:name=": = | RAW | = :">showSummary=true|jqlQuery=project = RHDPSPPT AND statusCategory != Done AND assignee is EMPTY ORDER BY created ASC</ac:parameter><ac:parameter ac:name=": = | TOKEN_TYPE | = :">BLOCK</ac:parameter></ac:structured-macro>" data-pageid="504726329" />

 No request type (open)
 Uncategorised & on the default SLA.
 Error rendering macro 'jira' : Macro params are invalid
 SLA breaches (last 30d)
 Monthly reporting view of what breached.
 Error rendering macro 'jira' : Macro params are invalid
 Proposed priority-based SLA policy
 Layer priority on top of the existing request-type routing: keep the long 320h goal for onboarding, but let urgency compress targets for everything else. Set an explicit 24×5 business calendar so goals mean the same thing to everyone.
 Priority
 Response (MTTA)
 Resolution (MTTR)
 Applies to

 Blocker 
 1 hour
 4 business hours
 Production-down / event-blocking

 High 
 2 hours
 1 business day
 Customer-facing, time-sensitive

 Medium 
 8 business hours
 3 business days (72h)
 Standard support / workshop prep

 Low / Minor 
 1 business day
 5 business days
 Non-urgent requests

 Onboarding 
 1 business day
 15 business days (320h)
 Asset / ZT onboarding (keep long)

 Recommendations
 Fix the SLAs (JSM admin)
 Ensure each request type has a JSM type
 Each type needs a unique (hidden) label field in order to have a unique SLA

 Add priority-differentiated targets per the table above.

 Add a distinct Time-to-first-response SLA — only internal acknowledge is tracked today; the customer-facing response is what requesters feel and that's what "MTTA measures"

 Make request type mandatory & auto-route the 54 without one — they're uncategorised and fall to the default SLA.
 RHDP Whiteglove SLAs come in without a type - they're just blank, meaning they get a default SLA of 8h A and 48h R.

 Monitoring & tracking (Jira)
 Breach-imminent alerting — automation rule pings the ops channel at 75% of target with no response.
 With Atlassian Assist finally enabled, this may finally be natively possible!

 This dashboard + saved filters — the queues above, saved and shared with the team.

 Automated weekly SLA digest — scheduled summary posted here / to Slack.

 Capture resolution category — recurring provision-failed / access themes become an upstream backlog, not just closed tickets.

 Require an assignee before Resolved and promote dominant themes (Workshops, MaaS, Provisioning, Access) to components.

 Surface ticket source in all reporting views — add source (Slack vs JSM portal vs email) as a visible column and filter in every live queue and the weekly digest. Slack-originated tickets, JSM portal submissions, and email-handler tickets have different intake quality and likely different breach patterns. To populate: query the JSM channel field or reporter pattern for the Slack-Google-Jira bot. Treat as a required metric alongside request type in all SLA reporting views.

 Ticket types clearly visible in all queue views — request type AND priority must be always-on columns in every queue view (no click-through required). Triage decisions happen in seconds; if the type isn't visible at a glance, it doesn't get used. This is a JSM queue configuration change, not a data change.

 Source: redhat.atlassian.net · 673 resolved RHDPSPPT tickets, last 180 days. Charts rendered natively above from the same dataset. Generated 16 Oct 2026 .
