"""Canary labels must not retarget deletion of another profile's unit."""
import os
import plistlib
from types import SimpleNamespace
import pytest
from hermes_cli import profiles

@pytest.mark.platforms("macos")
def test_profile_cleanup_ignores_canary_label(tmp_path, monkeypatch):
    profile = tmp_path / ".hermes" / "profiles" / "worker"
    profile.mkdir(parents=True)
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    canary = agents / "ai.hermes.gateway-canary.plist"
    canary.write_bytes(plistlib.dumps({"EnvironmentVariables": {"HERMES_HOME": str(tmp_path / ".hermes")}}))
    own = agents / "ai.hermes.gateway-worker.plist"
    own.write_bytes(plistlib.dumps({"EnvironmentVariables": {"HERMES_HOME": str(profile)}}))
    monkeypatch.setattr("pwd.getpwuid", lambda uid: SimpleNamespace(pw_dir=str(tmp_path)))
    monkeypatch.setenv("HERMES_GATEWAY_LAUNCHD_LABEL", "ai.hermes.gateway-canary")
    calls = []
    monkeypatch.setattr(profiles.subprocess, "run", lambda argv, **kw: calls.append(argv))
    assert profiles._cleanup_gateway_service("worker", profile)
    assert canary.exists()
    assert not own.exists()
    assert calls == [["launchctl", "unload", str(own)]]
    assert os.environ["HERMES_GATEWAY_LAUNCHD_LABEL"] == "ai.hermes.gateway-canary"
