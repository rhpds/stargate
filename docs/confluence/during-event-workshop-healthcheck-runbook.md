# During-Event Workshop Healthcheck Runbook
# Confluence ID: 505348239
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/505348239

Owner: Andrew Jones (planning) / Ops (execution)  |  When: Event week, Jan 18, 2027+  |  Scope: Workshop health checking only.
 Out of scope: general event monitoring, follow-the-sun staffing, incident escalation ownership, post-session cleanup. Those live in the ops-owned event-day runbook, not here.
 1. Healthcheck Sweep Procedure
 Covers two different kinds of running workshops -- don't skip the second one, it's most of what's live during the event.
 1a. Self-paced pools -- same tooling as pre-event (see the Pre-Event Pool Healthcheck Runbook ):

 /check?pool=<pool-name>

 1b. Scheduled, instructor-led room sessions -- each room's workshop is a one-off instance, not a pool. Check by workshop GUID instead:

 /check?workshop=<GUID>

 Both support the same direct healthcheck fallback:

 curl -sk -N "$SHOWROOM/stream/qa/healthcheck"

 Cadence: hourly for pools during event hours (vs. daily pre-event); for scheduled sessions, check once shortly after each room's session starts.
 2. Failure Handling
 Result
 Action

 Healthcheck fails
 Reprovision the instance (via Demo Platform: Admin Ops Control or Workshop Instances page); re-run healthcheck

 Soundcheck degraded (tabs fail, content OK)
 Log; does not block unless on critical path

 Repeated failures across a pool (>10%)
 Hand off to ops incident process immediately -- do not wait for next sweep

 3. Handoff
 Log sweep results the same way as pre-event (Confluence). Anything beyond a failed healthcheck -- staffing, SLAs, cleanup, broader incident response -- is the ops event-day runbook's responsibility, not this doc's.
