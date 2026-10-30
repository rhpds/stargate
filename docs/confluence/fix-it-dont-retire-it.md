# Fix It, Don't Retire It: We Need to Do Better
# Confluence ID: 467764417
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/467764417

TL;DR: We almost retired a perfectly fixable workshop because a deployment broke. The fix was two PRs. We need to stop defaulting to retirement when something breaks — investigate first, retire last.

 What Happened
 The Cloud-Native Integration with Red Hat build of Apache Camel workshop started failing in production. A retirement ticket was filed (

 GPTEINFRA-17464 
 -
 Getting issue details... 
 STATUS 

) with the recommendation to immediately retire the item and redirect users to a different Camel workshop.
 Instead of accepting retirement, we investigated the root cause. The issue was straightforward: the OpenShift Pipelines operator channel the workshop subscribed to had changed upstream, breaking the OLM subscription during deployment. This is not outdated content — it's a moving dependency.
 Two AGV pull requests fixed it:
 PR #27528 — Pinned the Pipelines operator channel to pipelines-1.17 

 PR #27529 — Variablized the operator channel for easier future updates

 Both PRs merged. Workshop back in service. Both Jira tickets closed as fixed — 

 GPTEINFRA-17464 
 -
 Getting issue details... 
 STATUS 

 and 

 RHDPOPS-23967 
 -
 Getting issue details... 
 STATUS 

.
 The Problem We Need to Address
 This is not an isolated case. We have a pattern of sending broken catalog items to retirement instead of investigating and fixing them. Retirement is becoming a shortcut, not a last resort.
 Broken ≠ Outdated. A deployment failure caused by an upstream operator channel change is not the same as content that is genuinely end-of-life. One is a fix, the other is a retirement. We need to tell the difference.

 Before filing a retirement ticket, ask:
 Is the content actually outdated? Or did an upstream dependency (operator channel, API version, EE image) change?

 Can we fix it? Operator channel pins, EE updates, and API version bumps are often a one-line change in AgV.

 Do users still need it? Check catalog metrics, provisioning data, and sales influence before pulling the plug.

 Who will maintain it going forward? If the developer has decided they no longer want to own the item and no one else will step up, retirement may be the responsible choice — but only after confirming the failure isn't a quick fix that removes the need for ongoing intervention.

 On maintenance ownership: When a developer says "it's old" and recommends retirement, sometimes that genuinely means they no longer wish to maintain the item. We cannot keep adding abandoned catalog items to the list of things our developers and ops teams manage — we already have enough RHDP-owned items. The key question isn't just "can we fix it?" but "who will own it going forward?" If no one will, retirement is the right call. The argument here is against reflexive retirement — not against considered retirement when there's no path to sustained ownership.

 What We Should Do Differently
 Instead of...
 Do this...

 Filing a retirement ticket for a broken item
 File a CI failure ticket and investigate the root cause

 Automatically retiring when a developer says "it's old"
 Ask why: is it a broken dependency (fix it), or has the developer decided they no longer want to maintain it? If no one will own it going forward, retirement may be right — but confirm it's not a quick fix first

 Redirecting to a replacement workshop
 Fix the original if the content is still valid and in demand

 Waiting for the developer to fix it
 Ops can fix common issues (operator channels, EE pins, API versions) ourselves

 The Cost of Unnecessary Retirement
 Every retired item is a gap in our catalog. Users who bookmarked it, training plans that reference it, and sales motions that depend on it all break. Fixing a broken deployment is almost always cheaper than the downstream impact of retirement.
 The Cloud-Native Camel fix took two PRs and less than a day. The retirement would have removed a workshop from the catalog permanently. Fix first. Retire last.

 Related

 GPTEINFRA-17464 
 -
 Getting issue details... 
 STATUS 

 — Retirement ticket (closed as fixed)

 RHDPOPS-23967 
 -
 Getting issue details... 
 STATUS 

 — CI failure ticket (closed as fixed)

 AGV PR #27528 — Pin Pipelines channel

 AGV PR #27529 — Variablize operator channel
