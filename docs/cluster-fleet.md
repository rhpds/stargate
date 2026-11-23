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

**Batch size is a weak lever — while `c` is 16–27 s.** Doubling `--batch` from
25 to 50 buys 16–22%, not the halving it looks like it should. `N·c` is 56–67%
of the period and does not move at all with batch size; only the gap term
shrinks. Anyone reaching for `--batch 50` to fix freshness will be disappointed
and will have lengthened individual ticks while doing it.

This stops being true once `c` falls and the cycle is gated by the tier-3
interval instead of by collection cost — see "Measured: the ceiling was real,
and it was not the cadence", where the same change is worth ~1.37×. The
arithmetic did not change; the regime did. A conclusion about a lever is only
valid for the values it was computed at.

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
so it narrows the gap without closing it. And the gets are not where most of
the time goes, which is the subject of the next section.

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

### The real limit is CPU, not code

> **Tested.** This section is the state of knowledge *before* the limit was
> raised. The measurement that settled it is the next section; read this one for
> how the hypothesis was formed, not for what is true now.

Two facts, and then a hypothesis that was, at the time, untested.

**Fact one: the pod is out of CPU.** It runs with a **CPU limit of 1** while
hosting five cluster workers, the Babylon worker, and a
`python3 -m cli.stargate` subprocess for every namespace evaluated.

```
usage_usec 9585466659   nr_periods 118206   nr_throttled 89823
throttled_usec 88092818085              (76% of periods throttled)
```

It sits at 973m of a 1000m limit, on a 96-core node.

**Fact two: production `c` is several times the cost of the work.** Measured
one namespace at a time, `c` is about 6 s on ocpv07 — reads 4.5–6.5 s,
evaluation 0.5–2.8 s, showroom probe 0.7–2.2 s. Derived from `runs`, the same
cluster's production `c` is 27.1 s.

The hypothesis is that the gap is CPU starvation rather than API latency or
mine. It is *not* established, and the measurement is weaker than it looks: the
6 s figure was taken inside the same throttled pod, and the same namespace
measured 10.85 s on one run and 4.45 s on another. Variance of that size
exceeds the effect being claimed, so treat the attribution as a guess and the
gap itself as the finding. It would also explain concurrency being worthless on
ocpv07 — no spare CPU means overlapping reads only changes which one is
throttled first — and tier 1's 760–950 s median against a 300 s target (`#165`),
which has been treated as a scheduler bug.

**Where the fix lives.** `scanner.resources` is in
`deploy/helm/stargate/values.yaml`, so the change belongs in the chart; a live
`oc set resources` on its own would be reverted by the next `helm upgrade`.
No new image is needed — the limits are not baked into the scanner build — but
the pod does restart when they change, so it is a rollout rather than a no-op
and follows the release rules.

**How to tell if the guess is right.** The measurement is already available and
needs no instrumentation: compare `runs`-derived batch spans before and after
the change. If `c` does not fall, the hypothesis is wrong and the next thing to
measure is where a namespace's time actually goes — which is worth doing either
way, because the 6 s baseline is the only number here that was taken under
controlled conditions, and it disagrees with production by 4.5×.

### Measured: the ceiling was real, and it was not the cadence

The limit went from 1 CPU to 3 at **2026-11-23 18:55:50Z**, live, by
`oc set resources` on the running Deployment — no image change, same digest
`sha256:1b5a4b72…` (the row and its revert command are in
`docs/config-log.md`; `#169` is the chart half). The measurement that follows
is 35 minutes of `runs` after the restart, on five clusters.

**The CPU ceiling was real.** Throttling went from 76% of CFS periods to 22.7%
cumulative and **35% in a 60 s window taken mid-batch**. The in-burst number is
the one to keep; the 11.9% read in the first minutes was a quiet-phase sample.

**`c` roughly halved on every cluster** (`c = span/(n−1)` over tier-3 batches,
split at gaps > 120 s, `n ≥ 5`; windows 55 min before and 35 min after):

| Cluster | `c` before | `c` after | Batch span |
|---|---|---|---|
| ocpv03 | 19.7 s | 9.6 s | 467 s → 180 s |
| ocpv06 | 31.2 s | 13.7 s | 749 s → 305 s |
| ocpv07 | 33.8 s | 17.1 s | 783 s → 285 s |
| ocpv08 | 32.9 s | 15.6 s | 791 s → 275 s |
| ocpv09 | 31.2 s | 16.1 s | 748 s → 262 s |

**Tier 1 came with it.** Tier-3 tick start-to-start on ocpv07 went from
1,084 s to **744 s**. That is the overrun `#165` records, and CPU starvation was
most of it. It still is not 300 s, and cannot be while tier 3 shares the loop:
the loop is `tick(); sleep(300)`, so a tick's period is `tick_duration + 300`,
and a 25-namespace batch on ocpv07 now costs 444 s. The arithmetic floor for
tier 1 is therefore ~750 s on that cluster no matter how many CPUs it gets.

**Tier 3 gained less than `c` did, and the sleep is why.** Throughput went from
25 namespaces per 1,084 s (~83/h) to 25 per 744 s (~121/h) — a 1.46× gain from
a 2× gain in `c`, because the 300 s sleep is a fixed term in the cycle:

```
cadence = tick_duration + 300        (when tick_duration + 300 >= TIER3_INTERVAL)
```

On ocpv07, 300 of those 744 s — 40% of the cycle — is the loop asleep. ocpv07's
sweep is ~3.0 h against a 2 h window, down from 4.2 h.

The gate adds a second, non-obvious term: a tick only runs tier 3 once
`TIER3_INTERVAL` has elapsed, so for clusters whose tier-3 tick is shorter than
600 s the cadence is quantised to a whole number of ticks. ocpv03 is the
example: its tier-3 tick costs 255 s, so the tick period is 555 s, below the
600 s gate, and tier 3 skips the next tick and lands every 861 s. `--tier3 300`
would take ocpv03 to 555 s (1.55× more) and change nothing on ocpv07, whose
period already exceeds the gate.

Which makes the levers, as arithmetic on measured quantities rather than
recommendations:

| Change | ocpv07 cadence | namespaces/h | 370-namespace sweep |
|---|---|---|---|
| today (B=25, in the tick loop) | 744 s | 121 | 3.0 h |
| `--batch 50` | 1,181 s | 152 | 2.4 h |
| `--tier3 300` | 744 s | 121 | 3.0 h |
| tier 3 out of the tick loop, B=25 | 444 s | 203 | **1.8 h** |

Only the last one crosses the 2 h window, and it does so with a smaller batch
than today's. This is also why the "batch size is a weak lever" analysis above
was right at `c = 16–27 s` and is not right at `c ≈ 17 s`: the fixed 300 s term
is now large relative to the work, so anything that removes it beats anything
that amortises it. Both statements are kept in this document because the
regime, not the arithmetic, is what changed.

## What closing the gap requires

1. **Credentials**: `cluster-reader` kubeconfigs for `ocpv01`, `ocpv02`,
   `ocpv04`, held in `stargate-kubeconfigs` under the canonical names. Same
   service-account model as the existing five; read-only.
2. **One registry, not two**: `--clusters` was *intersected* with
   `STARGATE_CLUSTERS`, so a name in only one was dropped without a word. PR
   `#168` collapses this to a single source with `--clusters` authoritative, and
   removes the legacy alias fallback that resolves `ocpv06` to a revoked token.
   Do not add clusters by editing one of the two lists.
3. **Capacity**: this is not free, and the first fix was resources, not code.
   The scheduler ran five workers in one pod with a **1-CPU limit at 76%
   throttled**; it is now at 3 CPUs / 35% in-burst throttling, which halved `c`
   and took the tier-3 tick from 1,084 s to 744 s (see "Measured: the ceiling
   was real…"). Two things are still true. Tier-3 throughput is bounded by the
   300 s sleep at the end of every tick and by `TIER3_INTERVAL`, not by
   collection cost, so the busiest cluster is re-checked every ~3.0 h against a
   2 h window. And adding three clusters and ~330 labs, two of them CNV-heavy,
   would put a sixth, seventh and eighth worker into that same pod: 3 CPUs
   absorbed five workers measured at 35% throttled, which is not the same as
   headroom for eight. Adding clusters and fixing cadence are still the same
   job, but the limit is no longer the first thing to move — the cadence gates
   are.

Until 1–3 are done, treat any fleet-wide statement from StarGate as covering
roughly three quarters of running labs — and note that the temporal gap
compounds it rather than overlapping with it.
