import plistlib
from unittest.mock import patch


def test_service_path_skips_nonexistent_node_modules(tmp_path):
    """Service PATH should not include node_modules/.bin if it doesn't exist."""
    from hermes_cli.gateway import _build_service_path_dirs
    with patch("hermes_cli.gateway.get_hermes_home", return_value=tmp_path / ".hermes"):
        dirs = _build_service_path_dirs(project_root=tmp_path)
    node_modules_bin = str(tmp_path / "node_modules" / ".bin")
    assert node_modules_bin not in dirs


def test_service_path_includes_node_modules_when_present(tmp_path):
    """Service PATH should include node_modules/.bin when it exists."""
    nm_bin = tmp_path / "node_modules" / ".bin"
    nm_bin.mkdir(parents=True)
    from hermes_cli.gateway import _build_service_path_dirs
    with patch("hermes_cli.gateway.get_hermes_home", return_value=tmp_path / ".hermes"):
        dirs = _build_service_path_dirs(project_root=tmp_path)
    assert str(nm_bin) in dirs


def test_launchd_label_override_controls_label_and_plist_path(tmp_path, monkeypatch):
    from hermes_cli import gateway

    monkeypatch.setenv("HERMES_GATEWAY_LAUNCHD_LABEL", "ai.hermes.gateway-v020-canary")
    monkeypatch.setattr("pwd.getpwuid", lambda _uid: type("User", (), {"pw_dir": str(tmp_path)})())

    assert gateway.get_launchd_label() == "ai.hermes.gateway-v020-canary"
    assert gateway.get_launchd_plist_path() == (
        tmp_path / "Library/LaunchAgents/ai.hermes.gateway-v020-canary.plist"
    )


def test_generated_launchd_plist_propagates_label_override(tmp_path, monkeypatch):
    from hermes_cli import gateway

    label = "ai.hermes.gateway-v020-canary"
    home = tmp_path / ".hermes-v020"
    monkeypatch.setenv("HERMES_GATEWAY_LAUNCHD_LABEL", label)
    monkeypatch.setattr(gateway, "get_hermes_home", lambda: home)
    monkeypatch.setattr(gateway, "_stable_service_working_dir", lambda: home)
    monkeypatch.setattr(gateway, "get_python_path", lambda: "/canary/.venv/bin/python")
    monkeypatch.setattr(gateway, "_build_service_path_dirs", lambda: ["/canary/.venv/bin"])
    monkeypatch.setattr(gateway, "_append_node_dir_for_service", lambda dirs: None)

    data = plistlib.loads(gateway.generate_launchd_plist().encode())
    environment = data["EnvironmentVariables"]

    assert data["Label"] == label
    assert environment["HERMES_GATEWAY_LAUNCHD_LABEL"] == label
    with patch.dict("os.environ", environment, clear=True):
        assert gateway.get_launchd_label() == label


def test_launchd_label_override_rejects_path_traversal(monkeypatch):
    import pytest
    from hermes_cli import gateway

    monkeypatch.setenv("HERMES_GATEWAY_LAUNCHD_LABEL", "../../production")

    with pytest.raises(ValueError, match="HERMES_GATEWAY_LAUNCHD_LABEL"):
        gateway.get_launchd_label()


