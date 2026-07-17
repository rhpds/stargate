"""Classification Accuracy Matrix — TDD/EDD/CDD/BDD for failure class patterns.

RED/GREEN TDD: tests written FIRST against the live classify_by_pattern() engine.
Each cell validates: input message -> classifier -> expected class (or unclassified).

Four dimensions per failure class:
  TDD — True Detection: genuine K8s events must classify correctly
  EDD — Evidence Discrimination: similar-but-wrong events must NOT match
  CDD — Cross-class Discrimination: multi-signal events -> most specific class
  BDD — Boundary Detection: edge cases, success contexts, substrings
"""

import pytest
from engine.failure_class_loader import classify_by_pattern, reload


@pytest.fixture(autouse=True, scope="module")
def _reload_classes():
    reload()


# ── Matrix cells ──────────────────────────────────────────────────────
#
# (dimension, input_message, expected_class)
#
# expected_class = "unclassified" means the message must NOT match any class.
# expected_class = "!foo" means the message must NOT classify as "foo"
#   (but may classify as something else or unclassified).

MATRIX = [
    # ═══════════════════════════════════════════════════════════════════
    # readiness_probe_failed
    # ═══════════════════════════════════════════════════════════════════

    # TDD — genuine events
    ("tdd", "Readiness probe failed: HTTP probe failed with statuscode: 503",
     "readiness_probe_failed"),
    ("tdd", "Liveness probe failed: Get http://10.0.0.1:8080/healthz: net/http: request canceled",
     "readiness_probe_failed"),
    ("tdd", "Unhealthy: Readiness probe failed: Get http://10.128.0.5:8080/health: dial tcp connect refused",
     "readiness_probe_failed"),

    # EDD — must NOT match
    ("edd", "Pod is Unhealthy due to memory pressure",
     "!readiness_probe_failed"),
    ("edd", "Node condition Unhealthy detected",
     "!readiness_probe_failed"),
    ("edd", "Container terminated: Unhealthy exit",
     "!readiness_probe_failed"),

    # CDD — shadowing: OOMKill in a probe message should still be probe
    ("cdd", "Readiness probe failed: OOMKilled",
     "readiness_probe_failed"),
    ("cdd", "Unhealthy: Readiness probe failed: container was OOMKilled",
     "readiness_probe_failed"),

    # BDD — boundary
    ("bdd", "Startup probe failed: timeout after 30s",
     "readiness_probe_failed"),

    # ═══════════════════════════════════════════════════════════════════
    # sync_failed
    # ═══════════════════════════════════════════════════════════════════

    # TDD — genuine events
    ("tdd", 'SyncFailed: sync "openshift-storage/ocs-storagecluster": not found',
     "sync_failed"),
    ("tdd", "reconciliation failed for operator xyz",
     "sync_failed"),
    ("tdd", "ReconcileFailed: failed to reconcile cluster",
     "sync_failed"),

    # EDD — must NOT match
    ("edd", "reconciliation completed successfully after retry failed initially",
     "!sync_failed"),
    ("edd", "reconciliation succeeded on second attempt",
     "!sync_failed"),

    # CDD — sync message with resolve signal should be sync, not resolution
    ("cdd", "SyncFailed: failed to resolve operand",
     "sync_failed"),

    # BDD — boundary
    ("bdd", "Sync completed with warnings",
     "!sync_failed"),

    # ═══════════════════════════════════════════════════════════════════
    # claim_misbound (already tight — verify it stays correct)
    # ═══════════════════════════════════════════════════════════════════

    # TDD
    ("tdd", "ClaimMisbound: PVC is bound to a non-existent PV",
     "claim_misbound"),
    ("tdd", "claim is bound to a non-existent volume",
     "claim_misbound"),

    # EDD
    ("edd", "PVC successfully bound to volume",
     "!claim_misbound"),

    # BDD
    ("bdd", "pvc misbound detected in namespace openshift-storage",
     "claim_misbound"),

    # ═══════════════════════════════════════════════════════════════════
    # resolution_failed
    # ═══════════════════════════════════════════════════════════════════

    # TDD — genuine events
    ("tdd", "ResolutionFailed: constraints not satisfiable",
     "resolution_failed"),
    ("tdd", "OLM resolution failed for operator packageserver",
     "resolution_failed"),

    # EDD — must NOT match
    ("edd", "DNS: failed to resolve hostname api.example.com",
     "!resolution_failed"),
    ("edd", "failed to resolve external dependency for build",
     "!resolution_failed"),
    ("edd", "Image build: failed to resolve base image tag",
     "!resolution_failed"),

    # CDD — OLM resolution with catalog context
    ("cdd", "ResolutionFailed: failed to resolve operator from catalog",
     "resolution_failed"),

    # BDD
    ("bdd", "Resolution completed after retry",
     "!resolution_failed"),

    # ═══════════════════════════════════════════════════════════════════
    # datasource_unrecognized
    # ═══════════════════════════════════════════════════════════════════

    # TDD — genuine events
    ("tdd", "UnrecognizedDataSourceKind: DataVolume has an unrecognized datasource kind",
     "datasource_unrecognized"),
    ("tdd", "unrecognized datasource type for DataVolume import",
     "datasource_unrecognized"),

    # EDD — must NOT match
    ("edd", "event from unknown source detected",
     "!datasource_unrecognized"),
    ("edd", "unknown source IP 10.0.0.1 blocked by firewall",
     "!datasource_unrecognized"),
    ("edd", "received data from unknown source system",
     "!datasource_unrecognized"),

    # BDD
    ("bdd", "DataSource validated successfully",
     "!datasource_unrecognized"),

    # ═══════════════════════════════════════════════════════════════════
    # deprecated_api
    # ═══════════════════════════════════════════════════════════════════

    # TDD — genuine events
    ("tdd", "deprecatedAnnotation: use status.conditions instead",
     "deprecated_api"),
    ("tdd", "deprecated API version batch/v1beta1 is scheduled for removal",
     "deprecated_api"),

    # EDD — must NOT match
    ("edd", "deprecated version of jquery detected in frontend build",
     "!deprecated_api"),
    ("edd", "This npm package version is deprecated, please upgrade",
     "!deprecated_api"),

    # BDD
    ("bdd", "API version extensions/v1beta1 deprecated, migrate to apps/v1",
     "deprecated_api"),

    # ═══════════════════════════════════════════════════════════════════
    # image_pull_secret_missing
    # ═══════════════════════════════════════════════════════════════════

    # TDD — genuine events
    ("tdd", "FailedToRetrieveImagePullSecret: unable to retrieve image pull secret default/my-secret",
     "image_pull_secret_missing"),
    ("tdd", "pull secret my-registry-creds not found in namespace default",
     "image_pull_secret_missing"),

    # EDD — must NOT match
    ("edd", "Successfully created imagePullSecrets for service account default",
     "!image_pull_secret_missing"),
    ("edd", "Updated imagePullSecrets configuration in deployment",
     "!image_pull_secret_missing"),
    ("edd", "imagePullSecrets validated successfully for all containers",
     "!image_pull_secret_missing"),

    # BDD
    ("bdd", "Warning: imagePullSecrets reference missing secret my-secret",
     "image_pull_secret_missing"),

    # ═══════════════════════════════════════════════════════════════════
    # oom_killed (bonus — substring false positive)
    # ═══════════════════════════════════════════════════════════════════

    # TDD
    ("tdd", "OOMKilled: container exceeded memory limit",
     "oom_killed"),
    ("tdd", "Container killed due to out of memory, exit code 137",
     "oom_killed"),

    # EDD — must NOT match on substring
    ("edd", "ROOM service started successfully",
     "!oom_killed"),
    ("edd", "ZOOM integration test passed",
     "!oom_killed"),
    ("edd", "Checking BLOOM model weights",
     "!oom_killed"),

    # ═══════════════════════════════════════════════════════════════════
    # pod_pending (bonus — overly broad)
    # ═══════════════════════════════════════════════════════════════════

    # TDD
    ("tdd", "pod my-app-xyz is Pending: awaiting scheduling",
     "pod_pending"),

    # EDD — must NOT match
    ("edd", "InstallPlan Pending approval by administrator",
     "!pod_pending"),
    ("edd", "Certificate renewal Pending",
     "!pod_pending"),
    ("edd", "Build Pending: waiting for worker",
     "!pod_pending"),

    # ═══════════════════════════════════════════════════════════════════
    # Cross-class shadowing tests (CDD)
    # ═══════════════════════════════════════════════════════════════════

    # Liveness probe + OOM -> should be readiness_probe_failed (probe context)
    ("cdd", "Liveness probe failed: OOMKilled",
     "readiness_probe_failed"),

    # Probe + image pull -> should be image_pull_backoff (more specific)
    ("cdd", "Readiness probe failed: Back-off pulling image registry.redhat.io/foo",
     "image_pull_backoff"),

    # CrashLoop + Probe -> should be pods_crashlooping (more specific)
    ("cdd", "Back-off restarting failed container: Readiness probe failed",
     "pods_crashlooping"),

    # OOMKilled standalone -> should be oom_killed, not readiness_probe_failed
    ("cdd", "OOMKilled: memory limit 256Mi exceeded",
     "oom_killed"),
]


def _check_expectation(result_class: str, expected: str) -> bool:
    """Check if classification result matches expectation.

    expected = "foo"   -> result must be exactly "foo"
    expected = "!foo"  -> result must NOT be "foo"
    """
    if expected.startswith("!"):
        return result_class != expected[1:]
    return result_class == expected


class TestClassificationAccuracy:
    """TDD/EDD/CDD/BDD accuracy matrix for failure class pattern matching."""

    @pytest.mark.parametrize(
        "dimension,message,expected",
        MATRIX,
        ids=[
            f"{dim}-{exp.lstrip('!')}-{msg[:50].replace(' ', '_')}"
            for dim, msg, exp in MATRIX
        ],
    )
    def test_classification_cell(self, dimension, message, expected):
        result_class, _ = classify_by_pattern(message)

        assert _check_expectation(result_class, expected), (
            f"\n  Dimension: {dimension.upper()}"
            f"\n  Input:     {message}"
            f"\n  Expected:  {expected}"
            f"\n  Got:       {result_class}"
        )


class TestClassificationMatrixCoverage:
    """Structural checks on the matrix itself."""

    def test_all_dimensions_covered(self):
        dims = {dim for dim, _, _ in MATRIX}
        assert dims == {"tdd", "edd", "cdd", "bdd"}

    def test_minimum_cells(self):
        assert len(MATRIX) >= 50, f"Matrix has {len(MATRIX)} cells, expected >= 50"

    def test_all_target_classes_have_tdd(self):
        target_classes = {
            "readiness_probe_failed", "sync_failed", "claim_misbound",
            "resolution_failed", "datasource_unrecognized", "deprecated_api",
            "image_pull_secret_missing",
        }
        tdd_classes = {exp for dim, _, exp in MATRIX if dim == "tdd" and not exp.startswith("!")}
        assert target_classes <= tdd_classes, (
            f"Missing TDD coverage for: {target_classes - tdd_classes}"
        )

    def test_all_target_classes_have_edd(self):
        target_classes = {
            "readiness_probe_failed", "sync_failed",
            "resolution_failed", "datasource_unrecognized", "deprecated_api",
            "image_pull_secret_missing",
        }
        edd_classes = {
            exp.lstrip("!") for dim, _, exp in MATRIX
            if dim == "edd" and exp.startswith("!")
        }
        assert target_classes <= edd_classes, (
            f"Missing EDD coverage for: {target_classes - edd_classes}"
        )
