"""AAP2 failure ingestion — TDD red/green.

Tests that AAP job failures from Grafana can be ingested, classified,
and stored as ground truth for the StarGate corpus.
"""

import pytest


class TestAAP2FailureParser:
    """Parse AAP2 Grafana failure data into StarGate's format."""

    def test_parser_exists(self):
        from engine.aap_ingestion import parse_aap_failure
        assert callable(parse_aap_failure)

    def test_parse_vm_provisioning_timeout(self):
        from engine.aap_ingestion import parse_aap_failure
        raw = {
            "guid": "cjgs2",
            "job_title": "partner.ocpmulti-wksp-cnv.prod",
            "type": "provision",
            "error_msg": 'fatal: [bastion]: FAILED! => {"api_found": true, "attempts": 30, "changed": false, "resources": [{"status": {"printableStatus": "Provisioning"}}]}',
            "task": "Wait till VM is running",
            "play": "Step 004.2 - Install OpenShift using Assisted Installer",
            "role": "host-ocp4-assisted-installer",
            "category": "general_failure",
            "cluster": "aap2-prod-bastion-partner0",
            "status": "failed",
        }
        result = parse_aap_failure(raw)
        assert result["failure_class"] == "vm_provisioning_timeout"
        assert "namespace" in result or "guid" in result

    def test_parse_ec2_capacity(self):
        from engine.aap_ingestion import parse_aap_failure
        raw = {
            "guid": "qkm4h",
            "job_title": "partner.ocp-wksp-ai-parasol-insurance.prod",
            "type": "destroy",
            "error_msg": "Unable to start instances: An error occurred (InsufficientInstanceCapacity)",
            "task": "Ensure EC2 instances are running",
            "role": "unknown",
            "category": "general_failure",
            "status": "failed",
        }
        result = parse_aap_failure(raw)
        assert result["failure_class"] == "ec2_capacity_exhausted"

    def test_parse_service_unavailable(self):
        from engine.aap_ingestion import parse_aap_failure
        raw = {
            "guid": "5m6kd",
            "job_title": "partner.ocp4-quarkus-superheroes-demo-cnv.prod",
            "type": "provision",
            "error_msg": "Status code was 503 and not [200]: HTTP Error 503: Service Unavailable",
            "task": "[quarkus-superheroes-java21-openshift] - Verify Quarkus services are running",
            "role": "ocp4_workload_quarkus_super_heroes_demo",
            "status": "failed",
        }
        result = parse_aap_failure(raw)
        assert result["failure_class"] == "service_unavailable"

    def test_parse_vault_decryption(self):
        from engine.aap_ingestion import parse_aap_failure
        raw = {
            "guid": "qgmn9",
            "job_title": "partner.osp-on-ocp-cnv.dev",
            "type": "provision",
            "error_msg": "Decryption failed (no vault secrets were found that could decrypt)",
            "task": "Set up StorageCluster",
            "role": "ocp4_workload_external_odf",
            "status": "failed",
        }
        result = parse_aap_failure(raw)
        assert result["failure_class"] == "vault_decryption_failed"

    def test_parse_ssh_connection(self):
        from engine.aap_ingestion import parse_aap_failure
        raw = {
            "guid": "729h4",
            "job_title": "partner.ocp-virt-roadshow-multi.prod",
            "type": "provision",
            "error_msg": "Shared connection to ssh.cluster.rhdp.example.com closed.",
            "task": "Find installer Pods in Error Status",
            "role": "host-ocp4-assisted-installer",
            "status": "failed",
        }
        result = parse_aap_failure(raw)
        assert result["failure_class"] == "ssh_connection_failed"

    def test_parse_job_cancellation(self):
        from engine.aap_ingestion import parse_aap_failure
        raw = {
            "guid": "9phz5",
            "job_title": "partner.ocp-wksp-ai-parasol-insurance.prod",
            "type": "stop",
            "error_msg": "Task was canceled due to receiving a shutdown signal.",
            "task": "job_failure",
            "role": "system",
            "status": "failed",
        }
        result = parse_aap_failure(raw)
        assert result["failure_class"] == "job_cancelled"


class TestAAP2FailureClassification:
    """New failure classes for AAP2 failures."""

    def test_failure_classes_registered(self):
        from engine.aap_ingestion import AAP_FAILURE_CLASSES
        assert "vm_provisioning_timeout" in AAP_FAILURE_CLASSES
        assert "ec2_capacity_exhausted" in AAP_FAILURE_CLASSES
        assert "vault_decryption_failed" in AAP_FAILURE_CLASSES
        assert "ssh_connection_failed" in AAP_FAILURE_CLASSES
        assert "service_unavailable" in AAP_FAILURE_CLASSES
        assert "job_cancelled" in AAP_FAILURE_CLASSES

    def test_each_class_has_remediation(self):
        from engine.aap_ingestion import AAP_FAILURE_CLASSES
        for cls_name, cls_data in AAP_FAILURE_CLASSES.items():
            assert "remediation" in cls_data, f"{cls_name} missing remediation"
            assert len(cls_data["remediation"]) > 0


class TestBatchIngestion:
    """Batch ingest multiple failures."""

    def test_batch_ingest_exists(self):
        from engine.aap_ingestion import batch_ingest
        assert callable(batch_ingest)

    def test_batch_ingest_returns_summary(self):
        from engine.aap_ingestion import batch_ingest
        failures = [
            {"guid": "test1", "error_msg": "InsufficientInstanceCapacity", "type": "destroy", "status": "failed"},
            {"guid": "test2", "error_msg": "503: Service Unavailable", "type": "provision", "status": "failed"},
        ]
        result = batch_ingest(failures)
        assert "total" in result
        assert "classified" in result
        assert result["total"] == 2
