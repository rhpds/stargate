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

## Still owed

- A Jira or AAP note, which is where the team's change record actually lives
  (`docs/config-management.md`, "What counts as a release"). This file is the
  repo-side copy, not a replacement.
- The manifests disagreed with production: `deploy/helm/stargate/values.yaml`,
  `deploy/helm/stargate/values-infra01.yaml`, and
  `deploy/agnosticv/stargate-platform/prod.yaml` all list `ocpv05` (retired — its
  API host no longer resolves) and omit `ocpv03`, and they carry clusters
  (`ocpv-infra01`, `ocpv-infra02`, `ocp-us-east-1`) that the live args do not.
  They were not edited in this record because that does not change the running
  deployment. `#168` corrects all of them to
  `ocpv03,ocpv06,ocpv07,ocpv08,ocpv09`, alongside the change that makes the
  value authoritative: `--clusters` used to be intersected with
  `STARGATE_CLUSTERS` and unknown names were dropped silently, which is the only
  reason a wrong list was survivable.
