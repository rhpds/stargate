"""AnarchySubject evidence — identify the catalog item and its lab source.

Reviewer feedback (2026-11-18): a namespace suffix (`zt-rhelbu`) is shared by a
whole catalog, and the lab repo/branch is set per request. Without the
AnarchySubject vars a failure cannot be reproduced.
"""

from collectors.babylon.collect_anarchy_state import collect_anarchysubject


def _subject(vars_block):
    return {
        "metadata": {"name": "sandbox-abc12-zt-rhelbu", "namespace": "babylon-anarchy-1"},
        "spec": {"vars": vars_block},
        "status": {"state": "started", "towerJobs": {}},
    }


class TestCatalogIdentity:
    def test_reads_a_structured_catalog_item(self):
        ev = collect_anarchysubject(_subject({
            "guid": "abc12",
            "catalog_item": {"metadata": {"name": "zt-rhel-bu-lab-developer-cnv"}},
        }))
        assert ev.observed["catalog_item"] == "zt-rhel-bu-lab-developer-cnv"
        assert ev.observed["guid"] == "abc12"

    def test_reads_a_plain_string_catalog_item(self):
        ev = collect_anarchysubject(_subject({"catalog_item": "ocp4-cluster"}))
        assert ev.observed["catalog_item"] == "ocp4-cluster"

    def test_falls_back_to_catalog_item_name(self):
        ev = collect_anarchysubject(_subject({"catalog_item_name": "published.lab.prod"}))
        assert ev.observed["catalog_item"] == "published.lab.prod"

    def test_reads_the_agnosticv_source(self):
        ev = collect_anarchysubject(_subject({
            "catalog_item": "zt-rhel-bu-lab-developer-cnv",
            "parameter_values": {
                "__meta__": {
                    "agnosticv_meta": {
                        "repo_url": "https://github.com/rhpds/zt-rhelbu",
                        "ref": "main",
                        "config": "prod",
                    }
                }
            },
        }))
        assert ev.observed["lab_source"] == {
            "repo_url": "https://github.com/rhpds/zt-rhelbu",
            "ref": "main",
            "config": "prod",
        }

    def test_never_captures_secret_shaped_meta(self):
        ev = collect_anarchysubject(_subject({
            "catalog_item": "x",
            "parameter_values": {
                "__meta__": {
                    "agnosticv_meta": {"repo_url": "https://github.com/x/y"},
                    "aws_secret_access_key": "AKIA-not-a-real-value",
                    "deployer_password": "hunter2",
                }
            },
        }))
        blob = repr(ev.observed)
        assert "AKIA" not in blob
        assert "hunter2" not in blob
