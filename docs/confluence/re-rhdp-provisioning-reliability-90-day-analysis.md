# Re: RHDP Provisioning Reliability — 90-Day Analysis (Oct 2026)
# Confluence ID: 511837217
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/511837217

Which EVENT items deploy their own tenant clusters vs. use the shared pool? That changes how the failure counts should be read. 
> again its better if you re-run this with better context… for example: *-tenant counts are placement/deploy failures for a specific lab only. They fail when their lab has no available Sandbox placements not because RAG’s pool is shared with Quarkus or others… And you have “downstream from RAG pool” for LB2863/LB2596, thats wrong.

 Can you share the timeline and rough scope of the Assisted Installer outage? It should be broken out separately so it doesn't get mixed into the structural failure picture.
> around oct 15, you can probably check slack, maybe we have pm

 Is the capacity issue (cluster full during events) a one-time thing or an ongoing constraint we should plan around?
> you should have the pm for it, it was 1-2-3 weeks we had with almost full clusters. and we also had that week we had all clusters disabled and only ocpv01 enabled

 For the PROD items at 30–53% — are content owners already engaged on any of them?
> thats a question for Billy Bethell
