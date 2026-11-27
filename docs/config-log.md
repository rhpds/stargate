# Config log

Config changes are not releases (see `docs/config-management.md`): a
ConfigMap/Secret edit or an `oc set env` costs no build and no new image, so it
may happen any day — but it has to be written down. This is that record. Image
rebuilds and rollouts to a new digest still belong in the Friday process.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 2026-11-21 ~05:50 | `deploy/stargate-scheduler`, `STARGATE_CLUSTERS` | `ocpv05,ocpv06,ocpv07,ocpv08,ocpv09` → `ocpv03,ocpv06,ocpv07,ocpv08,ocpv09` | `ocpv05`'s API host no longer resolves (`api.ocpv05.dal10.infra.demo.redhat.com: no such host`) and it had not been scanned since 2026-10-21. `ocpv03` is alive — 162 namespaces, 47 of them live `sandbox-*` labs — and had not been scanned since 2026-11-02. | `oc set env deploy/stargate-scheduler -n stargate STARGATE_CLUSTERS='{"ocpv05":"kubeconfig-ocpv05","ocpv06":"kubeconfig-ocpv06","ocpv07":"kubeconfig-ocpv07","ocpv08":"kubeconfig-ocpv08","ocpv09":"kubeconfig-ocpv09"}'` |
| 2026-11-21 ~05:53 | `deploy/stargate-scheduler`, container `scheduler`, `command` / `args` | `--clusters ocpv05,...` → `--clusters ocpv03,ocpv06,ocpv07,ocpv08,ocpv09`; `command` reduced to `["python3","-m","cli.scheduler"]` so the flags live only in `args` | The env change alone did nothing. `--clusters` is intersected with `STARGATE_CLUSTERS` and unknown names were dropped without a word, so `ocpv03` never started and the scheduler still reported `Clusters: 4`. Verified after the fix: `Clusters: 5`, `Started: ocpv03, ocpv06, ocpv07, ocpv08, ocpv09`, and `ocpv03` evaluations resumed within a minute. | Restore the previous `command` / `args` from the Deployment revision history. |

## Not a release

No image was rebuilt and no rollout to a new digest happened. The pod restarts
above are ordinary config-induced rolling restarts.

## 2026-11-23 — an out-of-band release, and a data repair

The opposite of everything above: two images were rebuilt and both Deployments
rolled to new digests on a Monday. It was explicitly approved, and it is
recorded here because the Friday rule is the only reason it needs recording.
The data repair in the third row has no other home.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 15:05 | `main` | `#161` squash-merged as `6e2720b` | Two write-path defects, both invisible until `#157` began logging lost writes. `runs.namespace` held the temp-dir basename (`sg-ocpv03-_44upomh`) instead of the lab, and two namespaces of the same family collected in the same second produced one `run_id`, so the second POST hit the 409 existence check and its whole evaluation was discarded. Measured just before the fix: **468 of 468** tier-3 rows in the last hour misnamed, 932 drops in 44 h (~21/hour, ~3,250 stage evaluations), still climbing. | `git revert 6e2720b` |
| ~15:10 | `deploy/stargate-api`, `deploy/stargate-scheduler` | Images re-pinned by digest: api `6aa9ffb8…`→`04cbfe69…`, scanner `c6b4a40e…`→`1b5a4b72…`. API rolled first, deliberately. | API first because the new `build_run_id` digests whatever namespace the caller sends — collisions stop before the scanner change lands. Both built from a clean `git archive 6e2720b` via `oc start-build --from-dir`, so the images provably match the merge commit. Scheduler `command`/`args` preserved verbatim. | `oc set image deploy/stargate-api -n stargate api=…stargate-api@sha256:6aa9ffb8a64a3374ec053617235f346b9ef0882bfed98a894e501d49bf09a570` and `oc set image deploy/stargate-scheduler -n stargate scheduler=…stargate-scanner@sha256:c6b4a40eda7fd1ca4f56104710bd2af6f94b15cf329857c07f46c02e8e4bdb96` |
| ~15:22 | `runs` table | `namespace := lab_code` for **550,155** tier-3 rows, single transaction, with an undo table `runs_ns_backfill_20261123` written in the same commit | The `sg-*` values are random and unrecoverable once overwritten, so the old value was captured rather than trusting a restore. Excluded by design: 43,923 tier-1 `scheduler` and 200 `credential-replication` rows, whose `namespace` genuinely is the cluster; and 6,219 rows with no recoverable namespace (`lab_code` of `ocp4-*`, `showroom-*`, `guid:*`, or null). | `UPDATE runs r SET namespace=b.old_namespace FROM runs_ns_backfill_20261123 b WHERE r.run_id=b.run_id;` |

Verified after the rollout, not inferred: the deployed scanner accepts
`--namespace`, the deployed API returns distinct run ids for two labs of one
demo in the same second, and every tier-3 row since the fix has
`namespace = lab_code` with zero 409s and zero errors in the new pod.

`scripts/deploy.sh` would have been a silent no-op here: it ends in
`oc rollout restart`, which does nothing against a digest-pinned Deployment.

Also merged at 15:41 on 2026-11-23, **not built**: `#162` `87391e1`, `#163`
`9a8d87e`, `#164` `227eea3`, `#165` `1e46bb4`. They change no running
deployment; they join the Friday build.

## 2026-11-23 ~18:56 — the scheduler was throttled, not slow

The cadence work so far (`#167`) had been reasoning about collector code and
batch size. The cgroup said the limit was neither.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| ~18:56 | `deploy/stargate-scheduler`, container `scheduler`, `resources` | requests `cpu: 500m` → `1`; limits `cpu: 1` → `3`; memory unchanged (requests `1Gi`, limits `2Gi`) | `/sys/fs/cgroup/cpu.stat` in the pod showed **89,823 of 118,206 CFS periods throttled (76%)**, `throttled_usec` 88,093 CPU-seconds (~24.5 CPU-hours) of running time lost, with usage pinned at 973m of a 1000m limit. Tier-3 collection is serial in-process, so a 1-CPU ceiling was the collection rate. The node was not the constraint: `ocp-infra01-worker03` has 95,500m allocatable and was 10% CPU-busy. | `oc set resources deploy/stargate-scheduler -n stargate --limits=cpu=1,memory=2Gi --requests=cpu=500m,memory=1Gi` |

The pod restarted at 18:55:50Z (`stargate-scheduler-85f89cfb45-7mgb7`); image,
`command`, and `args` were untouched, so this is a rollout of the same digest
`sha256:1b5a4b72…`.

Measured after, not inferred:

- Throttling since the restart: 1,633 of 7,189 periods (22.7%), and 213 of 609
  periods (35%) in a 60 s window taken mid-batch — the steady state moves with
  the scan phase, and 35% is the honest in-burst figure, not the 11.9% read in
  the first minutes.
- Per-lab collection cost `c = span/(n−1)` over tier-3 batches from `runs`
  (batch split at gaps > 120 s, `n ≥ 5`), same-day windows before and after the
  restart:

  | Cluster | `c` before | `c` after | avg batch span before → after |
  |---|---|---|---|
  | ocpv03 | 19.7 s | 9.6 s | 467 s → 180 s |
  | ocpv06 | 31.2 s | 13.7 s | 749 s → 305 s |
  | ocpv07 | 33.8 s | 17.1 s | 783 s → 285 s |
  | ocpv08 | 32.9 s | 15.6 s | 791 s → 275 s |
  | ocpv09 | 31.2 s | 16.1 s | 748 s → 262 s |

- The write path survived the restart: every tier-3 row since has
  `namespace = lab_code`.

`#169` carries the same numbers into `deploy/helm/stargate/values.yaml` so the
chart stops asking for the CPU that caused this. That chart change is **not**
the deploy path — the `stargate` Helm release has been `failed` since revision 7
and its image refs are `:latest` while the live Deployments are digest-pinned,
so a `helm upgrade` would unpin them. The live change above was made with
`oc set resources` and is the record of what is actually running.

## 2026-11-23 ~19:31 — tier-3 batch 25 → 50, and what it cost tier 1

`#167`'s lever table predicted 1,181 s cadence and 2.4 h on ocpv07 from this
change, as arithmetic on measured quantities. It was run live to replace the
arithmetic with a measurement. The measurement agrees with the arithmetic and
disagrees with the framing: the sweep did shorten, and the price was paid by
tier 1, because both run inside the same loop.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| ~19:31 | `deploy/stargate-scheduler`, container `scheduler`, `args` | `--batch 25` → `50` (JSON patch on `args/12`, preceded by a `test` op so a moved index cannot silently rewrite a different flag) | After the CPU change, `c` is 9.6–18.3 s and the fixed 300 s sleep is ~40% of the cycle, which makes batch size a real lever again where it had been a weak one at `c = 16–27 s` (`#167`). Predictions: 1,181 s cadence, 2.4 h on ocpv07. | `oc patch deploy stargate-scheduler -n stargate --type=json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/args/12","value":"25"}]'` |
| ~20:25 | same | `--batch 50` → `25` | Measured below: it reaches 2.5 h, not 2 h, and takes tier 1 from 744 s to 1,218 s on ocpv07 — node metrics read once every 20 minutes against a 300 s target. It buys a freshness the target does not accept, with a cost the target does not allow. The structural fix is `#171`, not a bigger batch. | re-apply the row above |

Pod `stargate-scheduler-698d54d6cc-lsfvz` on `ocp-infra01-worker01`, started
19:31:16Z. Image, resources, and `command` untouched: same digest
`sha256:1b5a4b72…`. The restart also reset tier-1 continuity, which is why the
tick timestamps below begin here.

Two consequences of measuring on this digest rather than on the Friday build,
both of which bound what the numbers mean:

- The rotation policy under test is the **pre-`#164`** one. `#162`–`#165` are
  merged and not built, so the namespace-selection starvation fix is not in this
  pod. Batch size and tick shape are unaffected; which namespaces make up a
  batch is not.
- `#165`'s overrun warning is not in this image either, so the log is silent
  about cadence by construction. Every timing below is derived from `runs`, and
  the absence of a warning in `oc logs` is not evidence that the gate found
  nothing — the gate is not running.

Measured 19:31–20:24Z, two full batches on every cluster (`runs`, batches split
at gaps > 120 s; `c = span/(n−1)` over the completed batches only, since an
in-flight batch drags the average down):

| Cluster | batch `n` | spans | `c` | start-to-start | namespaces/h | sweep |
|---|---|---|---|---|---|---|
| ocpv03 | 30 (whole cluster) | 298, 275, 322, 270 | 10.4 s | 615 / 893 s | ~176 | 62 ns → 0.35 h |
| ocpv06 | 50 | 776, 750 | 15.6 s | 1,096 s | 164 | 320 ns → 1.95 h |
| ocpv07 | 50 | 899, 882 | 18.2 s | 1,225 s | 147 | 370 ns → 2.52 h |
| ocpv08 | 50 | 775, 807 | 16.1 s | 1,102 s | 163 | 329 ns → 2.02 h |
| ocpv09 | 50 | 757, 734 | 15.2 s | 1,075 s | 167 | 249 ns → 1.49 h |

ocpv07 predicted 1,225 s against 1,181 s of arithmetic — close enough that the
model holds. Four of five clusters come to roughly 2 h or better; **ocpv07 does
not**, and it is the largest, so the one cluster that matters most is the one
the change does not fix. ocpv03's two cadences are the interval-gate
quantisation again: its tick period is 555 s, below `TIER3_INTERVAL=600`, so
tier 3 skips a tick and alternates between 615 s and 893 s.

The cost, and it is not a side note:

| Cluster | tier-1 period, batch 25 | tier-1 period, batch 50 | vs the 300 s target |
|---|---|---|---|
| ocpv03 | 305 / 591 s | 635 s | 2.1× |
| ocpv06 | ~473 s | 1,094 s | 3.6× |
| ocpv07 | 744 s | 1,218 s | 4.1× |
| ocpv08 | ~503 s | 1,128 s | 3.8× |
| ocpv09 | ~487 s | 1,082 s | 3.6× |

The tick that carried a batch cost the batch plus the sleep: on ocpv07 the batch
was 918 s of work and the period came out at 1,218 s. A 50-namespace batch is
not free; its cost moved out of tier 3's cadence and into tier 1's period, where
nothing was watching for it.

CPU pressure rose with it: **42.5% of CFS periods throttled** in a mid-batch
60 s window (35% at batch 25), and `c` moved from 17.1 s to 18.2 s on ocpv07.
3 CPUs absorbed batch 25 with margin; batch 50 is leaning on it.

The write path survived: 390 of 390 tier-3 rows since the restart have
`namespace = lab_code`.

**What this settles.** Batch size is a lever, and it is the wrong one: it trades
tier-3 freshness against tier-1 freshness inside a loop where tier 3 should not
be. `#171` (`--tier3-independent`) takes the batch out of the tier-1 tick and
takes the 300 s sleep out of the tier-3 cadence, which is the only arrangement
in which both can meet their own targets. At the measured `c` a
25-namespace batch is ~455 s, so `max(TIER3_INTERVAL=300, 455)` is 455 s, which
puts ocpv07 at ~1.9 h — while tier 1 returns to ~305 s, because the sleep is
suddenly the only thing in the tick again.

## 2026-11-23 ~20:57 — the second release of the day, and the cadence change

Explicitly approved out of band ("merge and build and deploy the release"), like
the 15:05 one above, and recorded here for the same reason: the Friday rule is
the only reason it needs recording. `#166`–`#172` squash-merged into `main` at
`b681105`, and both images were rebuilt from that tree as **binary** builds
(`stargate-api-353`, `stargate-scanner-50`; `oc get build … -o json` reports
`source.type: Binary`, i.e. `oc start-build --from-dir`). Worth stating plainly:
OpenShift records **no git commit** for a binary build, so the link from digest
to commit is the tree that was sent, not a recorded sha. The 15:05 entry above
says "provably match the merge commit" — the digests are provable, the commit is
not, and the same caveat applies to these two.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 20:57 | builds | `stargate-api-353` → api `sha256:e6745fe6…`, `stargate-scanner-50` → scanner `sha256:c3a8c508…` | Seven merged PRs: `#166` this file for the 15:05 deploy, `#167`/`#170` fleet-inventory and snapshot completeness, `#168` one cluster registry, `#169` scheduler CPU limit in the chart, `#171` `--tier3-independent`, `#172` external-evidence attribution. | rebuild from `git archive 6e2720b` (see the 15:05 rows) |
| 20:59 | `deploy/stargate-api` | `sha256:04cbfe69…` → `sha256:e6745fe6…`, API first; pods `stargate-api-5454bd8496-*` | API first, as at 15:05: the new image is the one that accepts what the new scanner sends. `rollout status` completed before the scanner was touched. | `oc rollout undo deploy/stargate-api -n stargate` — the previous revision is api `sha256:04cbfe69…`. The full previous digest is not recorded in this file; read it from `oc rollout history` or the `stargate-api` ImageStream before undoing, not from a truncation. |
| 21:00 | `deploy/stargate-scheduler`, container `scheduler` | image `sha256:1b5a4b72…` → `sha256:c3a8c508…` **and** `args` `--batch 25` (tier 3 inside the tier-1 tick) → `--tier1 300 --tier2 900 --tier3 300 --batch 25 --tier3-independent`, in one JSON patch | `#171`. Batch size was measured and rejected earlier the same day (previous section): the batch was never the problem, its *placement* in the tier-1 tick was. Tier 3 now runs on its own thread so the 300 s sleep stays in tier 1 where it belongs. Image and args in **one** patch so the flag never runs against an image that does not know it. | `oc rollout undo deploy/stargate-scheduler -n stargate` — previous revision is image `sha256:1b5a4b72…` with the pre-`#171` args |
| 21:13 | `deploy/stargate-scheduler`, container `scheduler`, `limits.cpu` | `3` → `5`; pod `stargate-scheduler-944cc98cd-zsscm` | `#169` is the chart half; the live half is this. An independent tier-3 thread reads the same cluster more often, and the 3-CPU pod was at **50.9%** of CFS periods throttled. Cumulative since the restart at 21:13: `nr_throttled` 8,414 of 63,798 `nr_periods` — **13.2%**. | `oc set resources deploy/stargate-scheduler -n stargate --limits=cpu=3 -c scheduler` |

Each row leaves a ReplicaSet behind, so the times above are the deployment's own
record rather than recollection — `oc get rs -n stargate -o
custom-columns=…,CREATED:…,IMAGE:…,CPU:…`:

| ReplicaSet | created | image | CPU limit |
|---|---|---|---|
| `stargate-api-5454bd8496` | 20:59:39Z | `e6745fe6…` | 1 |
| `stargate-scheduler-599dffdfcd` | 21:00:34Z | `c3a8c508…` | **3** |
| `stargate-scheduler-944cc98cd` | 21:13:18Z | `c3a8c508…` | **5** |

The middle row is why image+args and the CPU limit are separate rows and not one
patch: at 21:00 the flag went live on three CPUs, and 13 minutes later the limit
changed under it. That 13-minute window is the "flag, still 3 CPU" line in the
fleet measurements below — the configuration that throttled 50.9% of CFS periods
— so it is recorded rather than quietly folded into one row.

Flags and CPU limit are **one change**, not two. `--tier3-independent` gives the
batch its own thread, but both threads draw on the same CFS quota: at 3 CPUs the
new thread would simply take the periods tier 1 used to get, moving the
throttling rather than removing it. The reasoning is in
`docs/cluster-fleet.md`, "The real limit is CPU, not code" — the flag without the
limit is not half a fix, it is a regression waiting for a busy hour.

Verified after the rollout, not inferred: the running pod carries the digest
above with 0 restarts and the args shown, and tier 1 is back inside its target
on every cluster — median `cluster-health` tick period since the 21:13 restart,
from `stages` joined to `runs`:

| Cluster | ticks | median period |
|---|---|---|
| ocpv03 | 39 | 303 s |
| ocpv06 | 39 | 305 s |
| ocpv07 | 39 | 306 s |
| ocpv08 | 39 | 305 s |
| ocpv09 | 39 | 305 s |

The same reading before the change was **744 s on ocpv07** and 1,218 s at batch
50. Tier 3 also runs: 4,060 tier-3 runs since the restart, every one with
`namespace = lab_code`, so the `#161` write-path fix survived the rebuild.

## 2026-11-24 ~16:15 — sixteen PRs in one release, and the first scraped metrics

Approved out of band again (Tuesday, not Friday), because the queue had grown to
sixteen reviewed PRs and the freshness work is only true once deployed. All
sixteen merged through GitHub — no direct push to `main` — and `main` is
`c8cf85e`. Two had real conflicts, both resolved rather than force-merged:
`#177` kept main's freshly measured 3-CPU/5-CPU rows and inserted its own
"How the sweep is watched" after them, and `#176`/`#177` both appended a `##`
section before `## CORS` in `docs/configuration.md`, so both survive.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 16:12 | build `stargate-api-354` | api `sha256:e6745fe6…` → `sha256:4c7781a6…` | Built from a clean `git archive c8cf85e` via `oc start-build --from-dir` (Binary source, like 353/50 — OpenShift records no commit for a binary build, so the link is the tree sent, not a stored sha). Contains `#177` freshness, `#178` oldest-first tier-3, `#181` run closing, `#183` fresh-install bootstrap, `#184` API CPU, `#185` rotation-sync refusal, `#187` argv-only pipes, `#188` docs. | rebuild from `git archive c8cf85e`; previous digest is api `e6745fe6…` (build 353) |
| 16:15 | `deploy/stargate-api` | image → `sha256:4c7781a6…` **and** `limits.cpu` `1` → `2` (`-c api`), in one rollout; ReplicaSet `stargate-api-7864db88b` | `#184`. The 1-CPU pod was throttled in **18.5% / 14.2%** of CFS periods (two replicas) while averaging 0.70 cores, which is what pushed `/evaluate` past the scanner's 10 s client timeout and orphaned the runs `#181` now closes. API first, as always. | `oc set image deploy/stargate-api -n stargate api=…stargate-api@sha256:e6745fe6e9e9ad7d4f56269c4956271eca33fc862e9bd25a6acec4822235383d` and `oc set resources deploy/stargate-api -n stargate -c api --limits=cpu=1` |
| 16:15 | `runs` table | `alembic_version` `r9a0b1c2d3e4` → `s0b1c2d3e4f5`; index `idx_runs_namespace_started_at` created | `#182`, applied by `init_db()` on API startup rather than by hand — the first release to use that path. Plain transactional `CREATE INDEX` (not `CONCURRENTLY`) on 627,567 rows / 323 MB; holds a SHARE lock for ~3 s, which blocks writes but not reads, and `runs` gains ~14 rows/min. The freshness probe measured 1,501 ms without it and 64.0 ms with it. | `DROP INDEX idx_runs_namespace_started_at; UPDATE alembic_version SET version_num='r9a0b1c2d3e4';` |
| 16:18 | `deploy/stargate-scheduler` | scanner `sha256:c3a8c508…` → `sha256:c0b38474…`; ReplicaSet `stargate-scheduler-64c8778f85` | Build `stargate-scanner-51`. `args` and `limits.cpu: 5` were left untouched by the patch and verified after: `--clusters ocpv03,ocpv06,ocpv07,ocpv08,ocpv09 --api-url … --no-babylon --tier1 300 --tier2 900 --tier3 300 --batch 25 --tier3-independent`. | `oc set image deploy/stargate-scheduler -n stargate scheduler=…stargate-scanner@sha256:c3a8c508af79ace347dfdf7743a2c8dcf2ecb3d912f8115d88241a8aaa4c42eb` |
| 16:21 | `svc/stargate-api` label, `servicemonitor/stargate-api`, `prometheusrule/stargate-alerts` | Service gained `app: stargate-api`; the two monitoring objects created | `#180`. Nothing had ever scraped StarGate: 356 `stargate_*` samples sat on `:8090/metrics` with no reader, and the cluster's `Default`/`Watchdog`/`Critical` receivers had zero integrations. Applied surgically from a digest-pinned `helm template` rather than by a full `helm upgrade`, because the release (see below) is stale. | `oc delete servicemonitor stargate-api prometheusrule stargate-alerts -n stargate` and `oc label svc stargate-api app-` |

Verified after the rollout, not inferred: both API pods are on `4c7781a6…` with
0 restarts at a 2-CPU limit, `/health` returns 200 with `tier3: ok`, the
migration log reads `Running upgrade r9a0b1c2d3e4 -> s0b1c2d3e4f5` with no error,
and the scheduler is on `c0b38474…` with the args and 5-CPU limit above and its
first tier-1 tick inside 60 s. The freshness signal is live and green — sweep age
per cluster against the 7,200 s target:

| Cluster | live namespaces | never scanned | sweep age |
|---|---|---|---|
| ocpv03 | 35 | 0 | 366 s |
| ocpv06 | 255 | 0 | 6,350 s |
| ocpv07 | 248 | 6 | 6,556 s |
| ocpv08 | 231 | 4 | ~5,900 s |
| ocpv09 | 237 | 4 | ~5,500 s |

And Prometheus now has the target: `up{job="stargate-api"}` is `1` for both
pods from `openshift-user-workload-monitoring/user-workload`, with
`stargate_tier3_*` labelled by cluster. The ServiceMonitor only matches because
the Service gained the `app` label it had never carried; the old Service had
none, so a ServiceMonitor alone would have selected nothing.

Three things this release did **not** fix, stated because they are the kind that
look fixed from a dashboard:

- The 495 rows still in `running` (oldest 2026-11-19) are the accumulated leak.
  `#181` stops new ones being orphaned; it does not sweep history. Five of them
  are from this rollout's own 16:00Z window — an API restart cuts in-flight
  `/evaluate` calls, which is the same failure shape at a smaller scale.
- The Helm release `stargate` is still revision 7, status **failed**, dated
  2026-07-17, with July values (`tier3: 3600`, a fleet that includes
  `ocpv-infra01/02` and `ocp-us-east-1`, `:latest` images). Everything since has
  been applied with `oc set image` / `oc set resources` / `oc patch`. A blind
  `helm upgrade` would therefore revert this section. `values-infra01.yaml` is
  now digest-pinned to prevent that, but the release still needs reconciling on
  a Friday, together with `oauth.cookieSecret`, which `values-infra01.yaml` does
  not carry even though the templates mount it.
- `stargate-beat` and `stargate-worker` still reference api `7d3e51fc…` at 0
  replicas. Scaling either up would run a pre-`#181`, pre-`#184` image.

## 2026-11-24 ~22:50 — the investigation feedback loop, and a verdict backfill

Approved out of band again (Tuesday, not Friday). `main` is `3d3ef9f`. This
release carries `#190` and `#191`: `#190` fixes verdict extraction, rolls
`cost_estimate` into the run detail, adds `evidence_sufficient` to
`trust_dimensions`, and closes the timeout race between `as_completed` and the
stuck sweeper; `#191` adds `scripts/backfill_investigation_verdicts.py` and the
`COPY scripts/ scripts/` line the image needs to ship it.

The defect being repaired is narrow and worth stating exactly. The agent's
dominant output shape is

```
### 6. Verdict

> **TRANSIENT**
```

and the old extractor required the verdict word to be adjacent to "Verdict" via
`[:\s*]`, which the blank line and blockquote defeat. 563 of 848 null-verdict
rows mention "verdict" in that blockquote form; only 34 matched the old regex.
Everything downstream of the verdict — learned suppression (three `TRANSIENT`),
tri-state reporting, the Slack transient filter — was blind for those rows.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 22:48 | builds `stargate-api-355`, `stargate-scanner-52` | api `sha256:4c7781a6…` → `sha256:89d66ee5…` (102 s); scanner `sha256:c0b38474…` → `sha256:8b2b3860…` (52 s) | Both from a clean `git archive 3d3ef9f` via `oc start-build --from-dir` (Binary source, as with 353/50 — no commit is recorded for a binary build, so the digest proves the tree sent, not a stored sha). | rebuild from `git archive 3d3ef9f`; previous digests api `4c7781a6…` (355's predecessor) and scanner `c0b38474…` |
| 22:50 | `deploy/stargate-api` | image → `sha256:89d66ee5…`, revision 556 → 557, ReplicaSet `stargate-api-68cf8c67cb`; `limits.cpu: 2` and the `oauth-proxy` sidecar (100m/128Mi) left untouched | `#190` + `#191`. API first, as always. | `oc set image deploy/stargate-api -n stargate api=…stargate-api@sha256:4c7781a692eb32cdcf7be3c95c1ec8990c3dbf8fa9232cd048a406c9c538f8da` |
| 22:51 | `deploy/stargate-scheduler` | scanner `sha256:c0b38474…` → `sha256:8b2b3860…`, revision 63 → 64 | Build 52. `args` and `limits.cpu: 5` were not part of the patch and were verified after. | `oc set image deploy/stargate-scheduler -n stargate scheduler=…stargate-scanner@sha256:c0b38474b874792cc8438682e35dfc91bf884f20f7f444a58fcfd0a2c744a518` |
| 22:52 | `investigations.trust_dimensions` | 1,100 rows written (899 `verdict`, 979 `evidence_sufficient`, 0 `confidence`); rollback record `/tmp/verdicts.jsonl`, 1,100 lines, md5 `a9261778debacb85d3b902f024025482` | `#191`, run inside the new API pod (the image is the only place the script exists). Data-only: no workload restarted, no schema touched. | replay the rollback JSONL; each line carries `id`, `job_id`, `before`, `after` |

The backfill is deliberately narrow: only rows with **no** verdict are examined
at all, a populated field is never overwritten, and a row whose analysis
contains no verdict stays null. Dry run first (1,100 changes predicted), then
`--apply`, then `--apply` again, which reported `0 changed` — idempotent. The
arithmetic closes on a single run:

| Verdict | before | after | Δ |
|---|---|---|---|
| TRANSIENT | 822 | 1,502 | +680 |
| ACTIONABLE | 704 | 913 | +209 |
| UNKNOWN | 29 | 39 | +10 |
| null | 1,261 | 362 | −899 |

Verified after the rollout, not inferred: both API pods are on `89d66ee5…` with
0 restarts, `/health` is 200 with every component `ok` (`api`, `database`,
`scanners`, `llm`, `executor_kubeconfig`, `sandbox_api`), `init_db()` found
`alembic_version` already at `s0b1c2d3e4f5` and logged no migration, and the
scheduler reports all five clusters.

The verdict fix was also exercised end to end on a row created *after* the
deploy, rather than inferred from the backfill. A manual trigger on
`sandbox-pgxxx-zt-ansiblebu` (ocpv08, `service_has_no_endpoints`) produced
`inv-5c4c1725`: 12 iterations, verdict `TRANSIENT`, confidence 0.88,
`evidence_sufficient: true` — the blockquote shape that used to come back
NULL. That same run is what exposed the cost defect below. Freshness is inside target with
`never_scanned` at zero everywhere:

| Cluster | sweep age | never scanned |
|---|---|---|
| ocpv03 | 274 s | 0 |
| ocpv06 | 2,889 s | 0 |
| ocpv07 | 2,898 s | 0 |
| ocpv08 | 2,494 s | 0 |
| ocpv09 | 2,690 s | 0 |

**Why this shipped at 22:50 and not at 18:00.** It was ready to build four
hours earlier and could not be. A `compute` MachineConfigPool rollout rebooted
worker01 and worker02; both came back with `currentConfig == desiredConfig` and
then stopped answering (`virt-handler is not responsive`, CNV marking them
unresponsive). The single-replica image registry lived on worker01, and its
`ReadWriteOnce` ceph volume was pinned by `VolumeAttachment csi-f7a1973…`, so
the registry lost all endpoints and every pull cluster-wide failed with
`dial tcp 172.30.2.235:5000: i/o timeout` — 111 pods not Running, including
`stargate-scheduler`, `stargate-babylon-worker`, `stargate-demo` and the second
API replica. A binary build pushes into that registry, so building was not
possible either.

The recovery was **not** anything done here. The registry mounted the same PVC
on worker00 at ~21:16Z and pulls resumed; worker02 returned at 22:36:15Z and
worker01 at 22:38:36Z. Scan cadence shows the gap plainly: the 17:00Z bucket
has 190 runs instead of the usual 340–410, then nothing until 21:15Z (220),
then back to 407/409/400. The lesson is recorded because it contradicts what
was believed at the time: an RBD volume held by a dead node **can** be released
without a manual `oc delete volumeattachment`, and the registry did not need a
node to come back first — it needed the kubelet to be declared gone long enough.
The scheduled deploy overlapped the return of the nodes, so once both were back
the new API pods were scheduled onto worker01 and worker02 — the two nodes that
had been dead an hour earlier — at 22:50:21Z.

What this release does **not** fix, stated because it looks fixed from a
dashboard:

- 362 complete investigations still have no verdict. They are not a parser
  failure this time — their stored `analysis` contains no verdict section at
  all, and the backfill does not invent one.
- 810 rows still carry a null `evidence_sufficient`. Rows that already had a
  verdict were out of scope by design, so a null there stayed null.
- `cost_estimate` is still NULL on **every** investigation, new ones included —
  this release did not fix it, and the claim in `#190` that it did is wrong for
  the path that matters. `_call_llm_with_tools` prices the `llm_metrics` row
  inside a `finally` but returns the provider's raw `usage` dict, which carries
  tokens and no money, so `_spent()` reads a missing key and `total_cost` stays
  `0.0`. Verified at 23:27Z on a deliberately triggered investigation
  (`inv-5c4c1725`, 12 iterations): 12 `llm_metrics` rows, all 12 priced, and
  `investigations.cost_estimate` NULL. `#194` moves the pricing onto the
  returned dict. Historical NULLs stay NULL either way — `llm_metrics` has no
  `job_id`, so past spend cannot be attributed to past investigations.
- `scripts/backfill_investigation_verdicts.py` advertises `--dry-run` in its
  docstring but does not implement the flag — dry run is the default (omit
  `--apply`). Found while running it; the deployed image keeps the wart.
- The human-review backlog is untouched: 2,876 `unreviewed` and 279
  `needs_human_review`. Filling verdicts does not review anyone's judgement.

## 2026-11-25 — the writer fixed, and 50 verdicts it had already invented

Two more out-of-band API releases (Wednesday), approved, both on `main` =
`3d3ef9f`. No scanner image changed, because no scanner code changed: verdicts
are written by the API's own code, on whichever pod finishes the investigation.

`#190` fixed the extractor's *shape* problem — `### 6. Verdict`, a blank line, a
blockquote. It did not fix the *invention* problem. The same extractor fell
through to a bare-enum scan, and the agent's appended adjudication summary
carries its own classification line, so the last resort collected that instead
of nothing. Replayed over the 2,456 stored verdicts (2,818 complete
investigations), 50 could not be substantiated from the report at all: 48 lifted
from that appended block and 2 from upper-case prose adjectives ("the PVC is
primary — ACTIONABLE"; ids `2957` and `2867`). `#196` deletes the last resort
and strips the adjudication summary before section scanning, and now requires a
verdict-shaped body rather than a nearby mention — two real verdicts (`id=293`,
`id=2945`) were nearly dropped because a lower-case YAML `verdict:` key shadowed
the actual heading.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 01:05 → 01:07 | build `stargate-api-356` (104 s) | api `sha256:89d66ee5…` → `sha256:c5d396cb…` | `#194`. `_call_llm_with_tools` priced each call in a `finally` to fill `llm_metrics`, but returned the provider's raw `usage` dict, which carries tokens and no money, so `_spent()` read a missing key and `total_cost` stayed `0.0` — on the tool-calling path, which is most of the spend. The fix prices the dict once before returning it; the `finally` reads the value back instead of recomputing. | rebuild from `git archive 115b0d3`; previous digest is api `89d66ee5…` (build 355) |
| 01:07 | `deploy/stargate-api` | revision 557 → 558, ReplicaSet `stargate-api-6c44665f79`; `limits.cpu: 2` and the `oauth-proxy` sidecar (100m/128Mi) left untouched | `#194`, API only. | `oc set image deploy/stargate-api -n stargate api=…stargate-api@sha256:89d66ee518cef0bed2d556de2599dbcd5e9a843d63f902bf95f1ac7f529bcaa0` |
| 20:12 → 20:14 | build `stargate-api-357` (111 s) | api `sha256:c5d396cb…` → `sha256:34660f01…` | `#196`, the verdict extractor. Built from a clean `git archive a227222` via `oc start-build --from-dir`; the digest proves the tree sent, not a stored sha, as with every binary build here. | rebuild from `git archive a227222`; previous digest is api `c5d396cb…` (build 356) |
| 20:14 | `deploy/stargate-api` | revision 558 → 559, ReplicaSet `stargate-api-66ffcdc4bb`; `limits.cpu: 2`, memory 2Gi and the sidecar untouched | `#196`. | `oc set image deploy/stargate-api -n stargate api=…stargate-api@sha256:c5d396cbb3c30d848355371e34ff18ea32f11189803d42b17b4b0930e7b26fb9` |
| 20:15 | `investigations.trust_dimensions` | 50 rows: `verdict` `ACTIONABLE` → `null`. Rollback record 50 lines, md5 `aa58f20afb65aea5369c8c460a74df83`, copied out of the pod because `/tmp` dies with it | `#197`. A stored verdict the report does not state is wrong in a way a dashboard cannot see: it feeds learned suppression, the tri-state report and the Slack transient filter. Null is exactly what the writer stores for a verdict-less investigation, so the schema stays uniform. | replay the 50-line JSONL; each line carries `id`, `job_id`, `before`, `after` |

The repair is deliberately narrow. Only a row with **no** verdict is examined;
only `verdict` is written; a row whose report states a different verdict is
reported and never rewritten (that is not a call a script should make). It
re-derives with the deployed parser rather than a copy, and refuses to run on an
image that predates the fix, which is what caught the deployed `#197` script
lacking the `--dry-run` flag its docstring promised — amended before it ran
(`670dc524…`, byte-identical to `a16a9b9`). Dry run first: 50 predicted, 0
disagreements, and the list was identical to the independently derived 50.

| Verdict | before | after | Δ |
|---|---|---|---|
| TRANSIENT | 1,504 | 1,504 | 0 |
| ACTIONABLE | 914 | 864 | −50 |
| UNKNOWN | 39 | 39 | 0 |
| null | 367 | 417 | +50 |

All 50 were `ACTIONABLE`, all 50 already had `confidence = null` and
`evidence_sufficient = true`, and `usage_optimized` split 21/29 — every one of
those fields was read back against the rollback record and is unchanged. A
second `--apply` reported `0 written`, so the repair is idempotent rather than
merely finished.

`#194`'s cost fix was proved on a deliberately triggered investigation rather
than inferred: `inv-5e0ae4cc`, 2 iterations, `cost_estimate = 0.048723` where
the same window had been NULL for every row. Seven complete investigations carry
a cost, all created after 01:07Z. That is the whole population and it stays
small: `llm_metrics` has no `job_id`, so past spend cannot be attributed to past
investigations and those NULLs stay NULL. `inv-5e0ae4cc` happens to also be one
of the 50 repaired — its verdict came from the adjudication block under rev 558,
so the row that proved the cost fix also carried the defect that `#196` closed
an hour later.

Verified after the rollout, not inferred: rev 559 is 2/2 ready with 0 restarts,
`/health` is 200 with every component `ok`, the pod's `tasks/maintenance.py`
contains `_strip_adjudication_summary` and no last-resort scan, the scheduler is
still revision 64 on `8b2b3860…` with its args and 5-CPU limit, and the database
arithmetic closes — 2,824 complete, 2,407 with a verdict, 417 without.

This does not fix:

- 417 complete investigations still have no verdict: the 367 that never had one
  plus the 50 just nulled. The repair changes what the system believes, not what
  the agent said; those reports are still verdict-less.
- `#192`, `#193`, `#194`, `#195`, `#196` and `#197` are all still open, and
  `main` is still `3d3ef9f`. The running images come from branch commits.
- `values-infra01.yaml` is repinned here to the live pair (api `34660f01…`,
  scanner `8b2b3860…`), so the chart no longer describes a release the fleet is
  not running. The Helm release object itself is still revision 7, **failed**,
  dated 2026-07-17 — Friday's work, together with `oauth.cookieSecret`.
- The human-review backlog is unchanged: 2,876 `unreviewed`, 279
  `needs_human_review`. A verdict is not a review.

## 2026-11-25 ~20:20 — five credential literals moved into `stargate-secrets`

Not a release: no image was built and the digest is still `34660f01…`, but the
Deployment rolled once, because env values sourced from a Secret are only read
when a container starts.

The API carried 51 env vars, five of them literal credentials — the GeoLux key,
the AAP event-0 password, the 16-key additional-key list, the two read-only
keys, and the LLM health targets list, which embeds a provider `sk-` key. Those
values sat in the Deployment spec and in the pod template of every ReplicaSet in
its history, readable by anyone with read access to a ReplicaSet in the
namespace.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 20:18 | `secret/stargate-secrets` | five keys added — `geolux-api-key`, `aap-event0-pass`, `additional-api-keys`, `readonly-api-keys`, `llm-health-targets` — 6 keys → 11, the six existing untouched | Values copied from the live Deployment, never retyped, then compared back by SHA-256 in the Secret and again inside the pod. No key name collided. | `oc patch secret stargate-secrets --type json -p '[{"op":"remove","path":"/data/geolux-api-key"},{"op":"remove","path":"/data/aap-event0-pass"},{"op":"remove","path":"/data/additional-api-keys"},{"op":"remove","path":"/data/readonly-api-keys"},{"op":"remove","path":"/data/llm-health-targets"}]'` |
| 20:20 | `deploy/stargate-api`, container `api`, `env` | those five switched from `value:` to `valueFrom.secretKeyRef`; revision 559 → 560, ReplicaSet `stargate-api-547bd94b75` | A strategic merge alone is rejected — it keeps `value` next to `valueFrom` (`may not be specified when value is not empty`) — so the patch clears `value` explicitly and was server-dry-run first. | `oc rollout undo deploy/stargate-api --to-revision=559` (restores the literals), then remove the five Secret keys above |

`STARGATE_DATABASE_URL` was left as it was, deliberately. Its value is
`postgresql://stargate:$(POSTGRES_PASSWORD)@stargate-postgres:5432/stargate` —
not a literal credential, but a reference the kubelet expands from the
secret-backed `POSTGRES_PASSWORD` declared before it. Copying the resolved URL
into the Secret would write the database password under a second key, make
rotation a two-key operation, and reduce no exposure. The ordering constraint
behind "no pod starts without a DB URL" is already met: `POSTGRES_PASSWORD` is
env index 10, `STARGATE_DATABASE_URL` index 11.

Verified after the rollout, not inferred: 51 env vars still present; none of the
five has a `value`; the in-pod SHA-256 of each equals the Secret's
(`41ae8b0d5ab7`, `9fe681937388`, `3208c2a222c6`, `eb75120a5c57`,
`117a0b514c3d`); 2/2 pods with the `api` and `oauth-proxy` containers and the
2 CPU / 2 Gi limits intact; `/health` 200 with every component `ok`, `tier3`
included. Auth semantics are unchanged, checked in-process rather than by
guessing at HTTP codes: the admin key is valid, a bogus key is not, both
read-only keys are valid **and** flagged read-only, and all 16 additional keys
are valid. (An earlier probe reported 403 for "the read-only key" only because
that variable holds two comma-separated keys and the raw joined string is not
itself a key.)

What this does **not** do:

- The five literals still exist in the ten retired ReplicaSets (rev 550–559, all
  at 0 replicas); only rev 560's `api` container is clean — its `oauth-proxy`
  sidecar still carried all five, which is corrected under 2026-11-27 below.
  They were not deleted,
  because they are the rollback anchors. Rotating the five credentials is what
  retires those copies — until rotation, they are still readable in the
  namespace's ReplicaSet history.
- One pod (`7r5hl`) was `OOMKilled` at 20:22Z, `exitCode 137`, at the 2 Gi
  limit, while `/admin/llm/metrics` was read with the admin key. The request
  returned 200 first, and the other replica on the same spec did not restart,
  so the env change is not the cause. It was not reproduced on purpose: doing so
  kills a live API pod. The metrics aggregation exceeding the API's memory limit
  deserves its own fix.
- The rollout cuts in-flight `/evaluate` calls. None were in flight —
  `investigations` had 0 rows in `running` at the time — and the 500 stale
  `running` runs are the pre-existing leak, not new.

## 2026-11-27 ~19:32 — the sidecar the credential migration missed

This corrects the 25 Nov entry above, which claimed rev 560's template was
clean. It was clean for the `api` container only.

`oc set env` selects **every** container in the pod when `--containers` is not
given. Every env var ever set on this Deployment out of band therefore landed
twice: once in `api`, once in `oauth-proxy`. The 25 Nov migration then patched
only the `api` container, so all five credentials — GeoLux key, AAP event-0
password, the additional-key list, the two read-only keys, the LLM health
targets — remained as plaintext `value:` literals in the sidecar, in rev 560's
template and in all nine retired ReplicaSets. The proxy never read any of them;
it needs only its args.

Not a release: no image was built, the digest is still `34660f01…`.

| When (UTC) | Where | Change | Why | Revert |
|---|---|---|---|---|
| 19:31 | `deploy/stargate-api`, container `oauth-proxy`, `env` | all 32 vars removed (`env: []`) via JSON patch; revision 560 → 561, ReplicaSet `stargate-api-75b6c5f9dd` | The proxy substitutes no env into its args (checked: zero `$(…)` references), so the vars were dead weight and pure exposure. Removing them is smaller than converting them to refs. Server-dry-run first, with `test` ops pinning container index 1 to `oauth-proxy` and env index 0 to `STARGATE_AAP_EVENT0_PASS` so the patch could not land on the wrong container. | `oc rollout undo deploy/stargate-api --to-revision=560` (restores the literals) |

Verified after the rollout, from the new ReplicaSet's template rather than from
the patch: sidecar `env` is empty; `api` still has 51 vars, 11 of them
`secretKeyRef`; sidecar args are the same 9, `--skip-auth-regex=^/mcp` included;
sidecar resources still 50m/64Mi → 100m/128Mi; `api` still 2 CPU / 2 Gi and
digest `34660f01…`; 2/2 pods, 0 restarts. `/health` inside the pod reports
`ok` — the route returns the oauth login page for `/health`, so the in-pod call
is the only real check. `/mcp` returns 401 rather than a redirect, which is the
`skip-auth-regex` still working; a normal path still goes to the proxy.

What this does **not** do:

- The five values remain in rev 560's ReplicaSet and the nine before it, all at
  0 replicas. Rev 561 is the first template in the Deployment's history with no
  credential literal in either container. Rotation is what retires the rest.
- During this session a credential diff printed four of these values into the
  terminal transcript (the AAP password, one additional key, the GeoLux key,
  and the start of a read-only key) before the output was narrowed to
  name-and-kind only. They were already exposed in the ReplicaSet history, so
  this widened the audience rather than creating the exposure — but it means
  rotation of these five is no longer optional, and the transcript should be
  treated as secret material.

## Still owed

- `STARGATE_INVESTIGATE_MAX_ANOMALOUS_PER_DAY=25` is set in the live API env
  but **no Python file reads it** — a repo-wide grep finds no reference. On
  2026-11-24, 72 `auto_anomalous` investigations were created against a nominal
  cap of 25. Either the throttle moved to a variable under another name or the
  cap has not been enforced since a rename. It reads like a safety control, so
  it should be either wired up or removed rather than left looking active.

- A Jira or AAP note, which is where the team's change record actually lives
  (`docs/config-management.md`, "What counts as a release"). This file is the
  repo-side copy, not a replacement.
- `#173` landed **before** the next Helm apply: it is in `c8cf85e`, and
  `values.yaml`, `values-infra01.yaml` and the templates now agree with the live
  deployment (`tier3: 300`, scheduler `limits.cpu: "5"`,
  `--tier3-independent`, API `limits.cpu: "2"`, fleet `ocpv03,ocpv06–09`). The
  chart at `b681105` described the pre-21:00 deployment in three ways; a digest
  render from `c8cf85e` now reproduces the live args, resources and env. The
  remaining gap is not the chart but the failed release object itself, plus
  `oauth.cookieSecret`.
- The cadence change is live and now measured per namespace, not by aggregate
  rate: `stargate_tier3_sweep_age_seconds` has been scraped since 16:21Z on
  2026-11-24, and all five clusters sit under the 7,200 s target (worst is
  ocpv07 at 6,556 s, i.e. ~1.8 h — within the ~1.9 h projection). What is still
  unproven is a **full** sweep window after `#178` changed selection; the
  gauge, not this table, is what will answer that.
- The rotation's list-index defect is fixed by `#178`, deployed 16:18Z on
  2026-11-24: tier-3 batches now select oldest-attempt-first, so a lab cannot be
  skipped merely because the pod list re-sorted beneath the index. Its own
  effect is measured by the same gauge, and by `never_scanned` (currently 6/4/4
  on ocpv07/08/09, all new labs awaiting a first sweep).

- Coverage is still five clusters. `ocpv01` (dfw3, 244 labs), `ocpv02` (dfw3,
  77) and `ocpv04` (lon3, 8) are unscanned, blocked on `cluster-reader`
  kubeconfigs stored under the canonical names `kubeconfig-ocpv01`,
  `kubeconfig-ocpv02`, `kubeconfig-ocpv04` in the `stargate-kubeconfigs`
  secret. Nothing in the code needs to change for them; the kubeconfigs do not
  exist yet.
- The manifests used to disagree with production: `values.yaml`,
  `values-infra01.yaml` and `deploy/agnosticv/stargate-platform/prod.yaml` all
  listed `ocpv05` (retired — its API host no longer resolves) and omitted
  `ocpv03`. `#168` fixed that and is in `b681105`; all three now read
  `ocpv03,ocpv06,ocpv07,ocpv08,ocpv09`. The fleet list no longer needs editing
  in two places to mean one thing: `--clusters` is authoritative, where it used
  to be intersected with `STARGATE_CLUSTERS` and unknown names were dropped
  silently — which is the only reason a wrong list was survivable.
