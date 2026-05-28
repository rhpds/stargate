"""Infrastructure mining — TDD red/green."""

import pytest


class TestInfraMiner:
    def test_mine_cluster_exists(self):
        from engine.infra_miner import mine_cluster_infra
        assert callable(mine_cluster_infra)

    def test_mine_ceph_exists(self):
        from engine.infra_miner import mine_ceph_health
        assert callable(mine_ceph_health)

    def test_mine_operators_exists(self):
        from engine.infra_miner import mine_operator_health
        assert callable(mine_operator_health)

    def test_mine_nodes_exists(self):
        from engine.infra_miner import mine_node_conditions
        assert callable(mine_node_conditions)


class TestSummitClasses:
    def test_summit_yaml_loads(self):
        from engine.failure_class_loader import get_classes_by_source, reload
        reload()
        summit = get_classes_by_source("summit")
        assert len(summit) >= 10
        assert "pool_exhausted_under_load" in summit
        assert "showroom_not_reachable" in summit
        assert "smoke_test_failed" in summit

    def test_infra_yaml_loads(self):
        from engine.failure_class_loader import get_classes_by_source, reload
        reload()
        infra = get_classes_by_source("infrastructure")
        assert len(infra) >= 12
        assert "ceph_health_warning" in infra
        assert "operator_degraded" in infra
        assert "ingress_5xx_spike" in infra


class TestTotalCorpus:
    def test_total_failure_classes(self):
        from engine.failure_class_loader import get_all_classes, reload
        reload()
        total = get_all_classes()
        assert len(total) >= 72, f"Expected 72+ classes, got {len(total)}"
