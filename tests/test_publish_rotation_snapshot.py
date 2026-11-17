"""Publishing an audit snapshot — the daily ingest step (TDD, RED first)."""

import json

import pytest

from scripts import publish_rotation_snapshot as pub


def _snapshot(rows):
    return {"date": "2026-11-18", "by_provider": rows}


class TestBuildPayload:
    def test_maps_raw_names_into_page_buckets(self):
        payload = pub.build_payload(_snapshot([
            {"provider": "AWS", "verified_live": 50, "live_locations": 300, "untracked_live": 0},
            {"provider": "P1 — AWS; DNS/Route 53 account credentials",
             "verified_live": 2, "live_locations": 4, "untracked_live": 1},
        ]))

        assert payload["date"] == "2026-11-18"
        assert payload["providers"] == [
            {"provider": "AWS", "verified_live": 52, "live_locations": 304, "untracked_live": 1},
        ]

    def test_drops_rows_with_no_evidence(self):
        payload = pub.build_payload(_snapshot([
            {"provider": "AWS", "verified_live": 1, "live_locations": 1, "untracked_live": 0},
            {"provider": "Rundeck", "verified_live": 0, "live_locations": 0, "untracked_live": 0},
        ]))

        assert [p["provider"] for p in payload["providers"]] == ["AWS"]

    def test_identical_evidence_for_one_bucket_counts_once(self):
        # Found in the 2026-11-17 snapshot: two raw names were two views of the
        # same audit bucket, so the fleet total was inflated by 4/73/1.
        payload = pub.build_payload(_snapshot([
            {"provider": "Datastores", "verified_live": 4, "live_locations": 73, "untracked_live": 1},
            {"provider": "Storage", "verified_live": 4, "live_locations": 73, "untracked_live": 1},
        ]))

        assert payload["providers"] == [
            {"provider": "Datastores / storage", "verified_live": 4,
             "live_locations": 73, "untracked_live": 1},
        ]


class TestPublish:
    def test_sends_the_admin_key_and_returns_the_response(self, monkeypatch):
        seen = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"date": "2026-11-18", "providers": 1}'

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            seen["key"] = request.get_header("X-api-key")
            seen["body"] = json.loads(request.data.decode())
            return _Response()

        monkeypatch.setattr(pub.urllib.request, "urlopen", fake_urlopen)
        result = pub.publish({"date": "2026-11-18", "providers": []}, "http://api:8090/", "k")

        assert result == {"date": "2026-11-18", "providers": 1}
        assert seen["url"] == "http://api:8090/integration/rotation-snapshot"
        assert seen["key"] == "k"
        assert seen["body"]["date"] == "2026-11-18"

    def test_missing_api_key_fails_before_any_request(self, monkeypatch, tmp_path):
        monkeypatch.delenv("STARGATE_ADMIN_API_KEY", raising=False)
        monkeypatch.setattr(pub.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no request"))

        path = tmp_path / "snap.json"
        path.write_text(json.dumps(_snapshot([
            {"provider": "AWS", "verified_live": 1, "live_locations": 1, "untracked_live": 0},
        ])))

        assert pub.main(["--snapshot", str(path)]) == 2


class TestLoadSnapshot:
    def test_rejects_a_file_that_is_not_an_audit_snapshot(self, tmp_path):
        path = tmp_path / "nope.json"
        path.write_text(json.dumps({"totals": {}}))

        with pytest.raises(ValueError, match="by_provider"):
            pub.load_snapshot(str(path))


class TestCredentials:
    def test_reads_both_export_shapes(self, tmp_path):
        path = tmp_path / "coverage.csv"
        path.write_text(
            "sha256_16,credential,live_copies,clusters,coverage,jira\n"
            "abc123,aws_key,9,c1; c2,in-jira,GPTEINFRA-1\n"
        )
        rows = pub.build_credentials(str(path))
        assert rows == [{
            "id": "abc123", "credential": "aws_key", "provider": "",
            "live_copies": 9, "clusters": "c1; c2", "example_location": "",
            "coverage": "in-jira", "jira_keys": "GPTEINFRA-1",
        }]

    def test_publishes_to_the_credentials_endpoint(self, monkeypatch):
        seen = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"date": "2026-11-18", "credentials": 1}'

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return _Response()

        monkeypatch.setattr(pub.urllib.request, "urlopen", fake_urlopen)
        result = pub.publish_credentials({"date": "2026-11-18", "credentials": []},
                                         "http://api:8090", "k")

        assert result["credentials"] == 1
        assert seen["url"].endswith("/integration/rotation-credentials")
