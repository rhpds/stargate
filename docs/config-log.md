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

## Still owed

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
