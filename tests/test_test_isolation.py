"""Unit-test boundaries must fail closed without contacting external systems."""
import socket
import subprocess

import pytest


@pytest.mark.external_block_expected
def test_subprocess_execution_is_blocked(unit_external_effects_guard):
    assert getattr(subprocess.Popen, "_stargate_test_guard", False)
    with pytest.raises(RuntimeError, match="mock subprocess"):
        subprocess.run(["unit-test-forbidden-command"], check=True)
    assert unit_external_effects_guard == ["subprocess"]


@pytest.mark.external_block_expected
@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_network_connection_is_blocked(unit_external_effects_guard, method):
    assert getattr(getattr(socket.socket, method), "_stargate_test_guard", False)
    with socket.socket() as connection, pytest.raises(RuntimeError, match="mock network"):
        getattr(connection, method)(("192.0.2.1", 443))
    assert unit_external_effects_guard == ["network"]


@pytest.mark.external_block_expected
def test_datagram_send_is_blocked(unit_external_effects_guard):
    assert getattr(socket.socket.sendto, "_stargate_test_guard", False)
    with socket.socket(type=socket.SOCK_DGRAM) as connection, pytest.raises(RuntimeError, match="mock network"):
        connection.sendto(b"synthetic", ("192.0.2.1", 443))
    assert unit_external_effects_guard == ["network"]


@pytest.mark.external_block_expected
def test_dns_lookup_is_blocked(unit_external_effects_guard):
    with pytest.raises(RuntimeError, match="mock network"):
        socket.getaddrinfo("unit-test.invalid", 443)
    assert unit_external_effects_guard == ["network"]


def test_explicit_subprocess_mock_still_works(monkeypatch, unit_external_effects_guard):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: "synthetic")
    assert subprocess.run(["unit-test-forbidden-command"], check=True) == "synthetic"
    assert unit_external_effects_guard == []
