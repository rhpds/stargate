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

## How fast tier 3 re-checks a lab

Tier 3 scans one namespace at a time, `--batch 25` per cycle, inside the same
tick loop as tiers 1 and 2. Measured 2026-11-23 15:30–17:34Z on post-`#161`
data, recoverable from `runs` alone (a new batch starts when the gap between
consecutive rows exceeds 90 s):

| Cluster | `sandbox-*` namespaces | Cost per namespace | Batch span | Inter-batch gap | Full sweep |
|---|---|---|---|---|---|
| ocpv03 | 62 | 15.9 s | 349 s | 314 s | 0.5 h |
| ocpv06 | 320 | 23.5 s | 584 s | 327 s | 3.3 h |
| ocpv07 | 370 | 27.1 s | 680 s | 337 s | 4.2 h |
| ocpv08 | 329 | 26.9 s | 684 s | 330 s | 3.7 h |
| ocpv09 | 249 | 22.9 s | 585 s | 327 s | 2.5 h |

Namespace counts move with the lab lifecycle: these were sampled at 17:33Z,
which is why ocpv03 reads 62 here and 64 where this document measured the
subject field earlier.

The sweep period is `(N/B)·(B·c + g)`, which reduces to `N·c + N·g/B`: total
per-namespace work `N·c` plus the idle gap amortised over however large a batch
is. That has two consequences worth stating plainly, because both intuitive
fixes disappoint in different ways.

**Batch size is a weak lever.** Doubling `--batch` from 25 to 50 buys 16–22%,
not the halving it looks like it should. `N·c` is 56–67% of the period and does
not move at all with batch size; only the gap term shrinks. Anyone reaching for
`--batch 50` to fix freshness will be disappointed and will have lengthened
individual ticks while doing it.

**Per-namespace cost is the lever — but a smaller one than it looks.** `c`
decomposes into ten `oc get` calls, an in-namespace evaluation, and showroom
probes. Measured from inside the scheduler pod with no competing load: the ten
gets cost 10.4–13.6 s on ocpv03/06/09 but only 4.5–6.5 s on ocpv07; the
evaluation is 0.5–2.8 s. Production `c` is 16–27 s, so the remainder is probe
time plus contention — five workers share one pod and one Python interpreter.

Running those ten gets at 5-way is worth **1.4× on ocpv03, 1.8× on ocpv09,
2.2× on ocpv06, and nothing measurable on ocpv07**, where the API server rather
than the client's sequencing is the bottleneck. End to end that is roughly 20%
off a sweep — the same order as doubling the batch, from a change that touches
every namespace's hot path.

This section previously claimed 45–54%, which is what the arithmetic says if
the gets were the whole of `c` and the API server had spare capacity. Neither
is true, and the measurement is what caught it; the number is recorded wrong
here on purpose rather than quietly dropped.

Two caveats. A 20% gain puts the worst cluster at ~3.3 h against a 2 h window,
so it narrows the gap without closing it. And the largest term — the 16–27 s of
production `c` that is neither the gets nor the evaluation — is unexplained,
which makes it the thing to measure next rather than a thing to optimise.

Separately, the denominator is every `sandbox-*` namespace, so on ocpv07 about
30% of the work (111 of 370) is spent on namespaces with no pods to observe. A
lab mid-provision looks identical to a dead namespace until its pods appear,
which is why this is a cost to reduce carefully rather than an obvious saving.

Measured coverage of the namespaces that do have pods: 703 of 994 within a 2 h
window, 71%. This is a *different* 71% from the three-quarters figure below,
and the coincidence is worth flagging so the two are not read as one number.
This one is temporal: of the clusters we scan, how much of the fleet is inside
the window at any moment. The other is membership: of the clusters that run
labs, how many we scan at all. They are independent, and a lab can be missed
by either or by both — so the honest combined statement is lower than either
number alone.

## What closing the gap requires

1. **Credentials**: `cluster-reader` kubeconfigs for `ocpv01`, `ocpv02`,
   `ocpv04`, held in `stargate-kubeconfigs` under the canonical names. Same
   service-account model as the existing five; read-only.
2. **One registry, not two**: `--clusters` was *intersected* with
   `STARGATE_CLUSTERS`, so a name in only one was dropped without a word. PR
   `#168` collapses this to a single source with `--clusters` authoritative, and
   removes the legacy alias fallback that resolves `ocpv06` to a revoked token.
   Do not add clusters by editing one of the two lists.
3. **Capacity**: this is not free. Tier 1 was measured at 760–950 s median
   against a 300 s target on the five-cluster fleet (`#165` records overruns).
   Adding three clusters and ~330 labs, two of them CNV-heavy, makes that worse.
   Tier 3 already re-checks the busiest cluster only every 4.2 h ("How fast
   tier 3 re-checks a lab"), so a new cluster joins a rotation that is behind,
   not a spare one. Adding clusters and fixing cadence are the same job.

Until 1–3 are done, treat any fleet-wide statement from StarGate as covering
roughly three quarters of running labs — and note that the temporal gap
compounds it rather than overlapping with it.
