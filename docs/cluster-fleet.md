# The provisioning fleet, as measured

StarGate scans five clusters. The platform provisions labs on at least eight.
This file records how that was established, so the gap is a known quantity
rather than a rediscovery.

Measured 2026-11-23 against the live control plane. Read-only throughout.

## What we scan, and what we miss

Labs in state `started`, by the cluster that hosts them:

| Cluster | Site | Started labs | Monitored | API host resolves | TCP 6443 |
|---|---|---|---|---|---|
| **ocpv01** | dfw3 | **244** | **no** | yes | connect OK |
| ocpv08 | dal10 | 227 | yes | yes | connect OK |
| ocpv06 | dal10 | 222 | yes | yes | connect OK |
| ocpv07 | wdc06 | 220 | yes | yes | connect OK |
| ocpv09 | dal13 | 194 | yes | yes | connect OK |
| **ocpv02** | dfw3 | **77** | **no** | yes | connect OK |
| **ocpv04** | lon3 | **8** | **no** | yes | connect OK |
| ocpvdev01 | dal13 | 1 | no | yes | connect OK |

**863 started labs are visible; 330 are not — 28% of the 1,193 we can see, and
38% again on top of the covered set.** `ocpv01` is the busiest provisioning
cluster in the platform and StarGate has never scanned it, at any point: the
`runs` table contains no `cluster_name` of `ocpv01`, `ocpv02`, `ocpv04` or
`ocpvdev01` at any date.

## Why the obvious checks miss them

Both of these are traps worth knowing about, because each produced a confident
wrong answer first:

- **Site codes.** The hosting sites are not just `dal10`/`dal12`/`dal13`/
  `wdc06`/`wdc07`. `ocpv01` and `ocpv02` are in **dfw3**, `ocpv04` in **lon3**.
  A sweep restricted to the sites of the *known* clusters reports "no such
  host", which is a statement about the sweep, not the fleet.
- **Domains.** The scanned five are under `infra.demo.redhat.com`. `ocpv01` and
  `ocpv02` also serve `apps.ocpv01.rhdp.net` / `apps.ocpv02.rhdp.net`, so
  name-pattern guessing is not a substitute for reading where labs landed.

## Method

1. List `AnarchySubject`s on the Babylon control plane (`ocp-us-east-1`,
   `cluster-reader`): 3,479 objects, 1,584 carrying a placement.
2. Placement is `.spec.vars.job_vars.sandbox_openshift_cluster`; the API host is
   `.spec.vars.job_vars.sandbox_openshift_api_url`.
3. State is `.status.state`, **falling back to the `state` label** — `status.state`
   is empty on these objects, and reading only `status` makes every subject look
   unstarted. That mistake produced an empty table before it was caught.
4. Liveness is a DNS lookup plus a TCP connect to `:6443`, from a scanner pod,
   so it reflects the network path the collector would actually use.
5. History is `runs.cluster_name` in the StarGate database.

Only counts and cluster/host names were read out. `spec.vars` also contains lab
credentials; no values were printed at any point.

## Two caveats

- **The field undercounts.** `ocpv03` has 64 `sandbox-*` namespaces on the
  cluster itself but no subject carries it in `sandbox_openshift_cluster`, so
  the zerotouch catalog families evidently do not set the field. These numbers
  are directional, not a census. By the namespace-to-started ratio the scanned
  clusters show (~1.2–1.7), `ocpv01` more likely holds ~360 sandbox namespaces.
- **The same field also names lab-owned clusters.** Entries like
  `api.ocp.zpvt4.sandbox3574.opentlc.com` and `api.cluster-8kq6t.dyn.redhatworkshops.io`
  are clusters a lab provisioned *for itself*, not hosts. They are not fleet
  members and must not be added to the scanner's cluster list.

## Why they are not scanned today

Not a decision — an absence of credentials. `stargate-kubeconfigs` holds 13 keys
and none of them is `kubeconfig-ocpv01`, `-ocpv02` or `-ocpv04`.

The scanner also cannot discover them on its own: listing
`tenantclusterpools.babylon.gpte.redhat.com` returns `Forbidden` for
`system:serviceaccount:default:stargate-scanner`. The cluster list must come
from configuration, which is why a second, disagreeing source caused `ocpv03` to
be silently dropped for 18 days.

Dead and misleading entries in that same Secret, none of which will be fixed by
adding new ones:

| Key | State |
|---|---|
| `kubeconfig-ocpv05` | host is NXDOMAIN; cluster dark since 2026-10-21 |
| `kubeconfig-infra02` | token revoked — `the server has asked for the client to provide credentials` |
| `kubeconfig` | pre-rotation alias for `ocp-us-east-1`, revoked token |
| `kubeconfig-cnv` | pre-rotation alias for `ocpv06`, revoked token |

## What closing the gap requires

1. **Credentials**: `cluster-reader` kubeconfigs for `ocpv01`, `ocpv02`,
   `ocpv04`, held in `stargate-kubeconfigs` under the canonical names. Same
   service-account model as the existing five; read-only.
2. **One registry, not two**: `--clusters` is *intersected* with
   `STARGATE_CLUSTERS`, so a name in only one is dropped without a word. Collapse
   to a single source before adding clusters, and remove the legacy alias
   fallback that resolves `ocpv06` to a revoked token.
3. **Capacity**: this is not free. Tier 1 was measured at 760–950 s median
   against a 300 s target on the five-cluster fleet (`#165` records overruns).
   Adding three clusters and ~330 labs, two of them CNV-heavy, makes that worse.
   Coverage and cadence are in direct conflict until tier 3 stops sharing the
   tick loop.

Until 1–3 are done, treat any fleet-wide statement from StarGate as covering
roughly three quarters of running labs.
