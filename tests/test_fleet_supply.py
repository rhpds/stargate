"""Fleet supply — the evidence-based ceiling for the capacity forecast.

TDD: written before _fleet_supply exists. Supply = what the fleet has
demonstrably sustained: per cluster, observed peak VM density over the
scan-history window x compute nodes. It is a floor-of-capacity (true
capacity is >= the observed peak), so deficits against it are early
warnings — the conservative direction for an advisory forecast. The
data source is the scan-history files (the DB path revives with the
persistence fix's Friday release).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.routers.capacity import fleet_supply_vm_slots

NOW = datetime.now(timezone.utc)


def _scan_file(tmp_path, hours_ago, clusters):
    ts = NOW - timedelta(hours=hours_ago)
    name = "scan-%s.json" % ts.strftime("%Y%m%d-%H%M%S")
    (tmp_path / name).write_text(json.dumps(clusters))
    return name


def _cluster(name, compute_nodes, vms_per_node):
    return {"cluster": name, "compute_nodes": compute_nodes,
            "vms_per_node": vms_per_node, "total_vms": compute_nodes * vms_per_node}


class TestFleetSupply:
    def test_peak_density_times_compute_nodes(self, tmp_path, monkeypatch):
        """Supply per cluster = the highest density observed in the
        window x current compute nodes, summed across the fleet."""
        monkeypatch.setattr("api.routers.capacity._scan_history_dir", lambda: tmp_path)
        _scan_file(tmp_path, 1, [_cluster("ocpv06", 15, 57.3), _cluster("ocpv07", 10, 40.0)])
        _scan_file(tmp_path, 5, [_cluster("ocpv06", 15, 60.0), _cluster("ocpv07", 10, 30.0)])
        supply = fleet_supply_vm_slots(window_hours=24)
        assert supply is not None
        # ocpv06: peak 60.0 x 15 = 900; ocpv07: peak 40.0 x 10 = 400
        assert supply["vm_slots"] == 1300
        assert supply["basis"] == "observed_peak_density"
        assert supply["window_hours"] == 24
        assert {c["cluster"]: c["vm_slots"] for c in supply["clusters"]} == {
            "ocpv06": 900, "ocpv07": 400}

    def test_old_scans_excluded_from_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.routers.capacity._scan_history_dir", lambda: tmp_path)
        _scan_file(tmp_path, 3, [_cluster("ocpv06", 15, 55.0)])
        _scan_file(tmp_path, 48, [_cluster("ocpv06", 15, 90.0)])  # outside 24h
        supply = fleet_supply_vm_slots(window_hours=24)
        assert supply["vm_slots"] == 15 * 55  # the 90 density is excluded

    def test_no_history_is_none_not_zero(self, tmp_path, monkeypatch):
        """No files -> supply is unobserved (None), never a fabricated
        zero capacity."""
        monkeypatch.setattr("api.routers.capacity._scan_history_dir", lambda: tmp_path)
        assert fleet_supply_vm_slots(window_hours=24) is None

    def test_zero_compute_nodes_contribute_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.routers.capacity._scan_history_dir", lambda: tmp_path)
        _scan_file(tmp_path, 1, [_cluster("ocpv06", 15, 50.0), _cluster("x", 0, 80.0)])
        supply = fleet_supply_vm_slots(window_hours=24)
        assert supply["vm_slots"] == 750

    def test_malformed_files_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.routers.capacity._scan_history_dir", lambda: tmp_path)
        _scan_file(tmp_path, 1, [_cluster("ocpv06", 15, 50.0)])
        (tmp_path / "scan-broken.json").write_text("{not json")
        supply = fleet_supply_vm_slots(window_hours=24)
        assert supply["vm_slots"] == 750
