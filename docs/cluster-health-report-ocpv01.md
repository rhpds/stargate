# StarGate Cluster Health Report — ocpv01

**Cluster**: `ocpv01.dfw3.infra.example.com`
**Scanned**: 2026-05-06
**Type**: CNV lab workload cluster (large)
**Nodes**: 50 (3 control plane, 40 workers, 7 ceph)

## Lab Health: 100%

| Metric | Value |
|---|---|
| Sandbox namespaces | 120 |
| Active with running pods | 120 |
| With issues | **0** |
| **Lab health rate** | **100%** |

No lab failures. All 120 active sandbox environments healthy.

## Cluster Resources: Healthy

All 40 worker nodes at 1-6% CPU, 4-8% memory. No resource pressure. Significant headroom for Summit.

## Platform Issues

| Issue | Count | Same as other clusters? |
|---|---|---|
| Ceph cleanup Error pods | 2,910 | Yes — ocpv06 (1,509), ocpv08 (1,349) |
| ccm-monitoring push failures | 8 | Yes — all clusters |
| cnv-images issues | 3 | Yes — ocpv06, ocpv08 |
| kubernetes-secret-generator | Running (healthy) | Different — crashing on other clusters |
