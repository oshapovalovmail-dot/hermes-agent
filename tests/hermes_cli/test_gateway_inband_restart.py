"""Only the drain-aware, exact in-band restart may cross the lifecycle guard."""
from argparse import Namespace
from types import SimpleNamespace

import pytest
from tools.terminal_tool_guards import gateway_lifecycle_block
from hermes_cli import gateway


@pytest.mark.parametrize("command", ["hermes gateway restart", "/opt/hermes/bin/hermes gateway restart"])
def test_exact_restart_can_reach_child_cli(monkeypatch, command):
    monkeypatch.setattr("tools.process_registry._is_supervised_gateway_process", lambda: True)
    assert gateway_lifecycle_block(command=command, env=SimpleNamespace(), env_type="local",
                                   cwd="/tmp", workdir=None, session_key="fixture") is None


@pytest.mark.parametrize("command", ["hermes gateway restart; echo unsafe", "hermes gateway stop",
                                     "hermes gateway restart --all", "hermes gateway restart && echo unsafe"])
def test_other_lifecycle_shapes_stay_blocked(monkeypatch, command):
    monkeypatch.setattr("tools.process_registry._is_supervised_gateway_process", lambda: True)
    assert gateway_lifecycle_block(command=command, env=SimpleNamespace(), env_type="local",
                                   cwd="/tmp", workdir=None, session_key="fixture") is not None


def test_in_band_restart_only_requests_ancestor_drain(monkeypatch):
    monkeypatch.setattr("tools.process_registry._is_supervised_gateway_process", lambda: True)
    monkeypatch.setattr("gateway.status.get_running_pid", lambda: 4242)
    requested = []
    monkeypatch.setattr(gateway, "_request_gateway_self_restart", lambda pid: requested.append(pid) or True)
    gateway._cmd_restart(Namespace(all=False, system=False, force=False))
    assert requested == [4242]


def test_in_band_restart_refuses_when_safe_request_fails(monkeypatch):
    monkeypatch.setattr("tools.process_registry._is_supervised_gateway_process", lambda: True)
    monkeypatch.setattr("gateway.status.get_running_pid", lambda: 4242)
    monkeypatch.setattr(gateway, "_request_gateway_self_restart", lambda pid: False)
    with pytest.raises(SystemExit) as error:
        gateway._cmd_restart(Namespace(all=False, system=False, force=False))
    assert error.value.code == 1
