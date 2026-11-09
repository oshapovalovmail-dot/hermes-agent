"""CLI validation must finish before any fetch, install, or Docker mutation."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "integrations/memory-stack/install.py"


def invoke(*arguments):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, arguments)],
                          capture_output=True, text=True, timeout=20, check=False)


def test_help_exposes_all_lifecycle_commands():
    result = invoke("--help")
    assert result.returncode == 0
    for word in ["prepare", "up", "check", "down"]:
        assert word in result.stdout


def test_provider_is_required_before_any_files_are_created(tmp_path):
    root = tmp_path / "absent"
    result = invoke("prepare", "--root", root)
    assert result.returncode != 0
    assert "--provider" in result.stderr
    assert not root.exists()


@pytest.mark.parametrize("url", ["https://key@example.invalid/v1", "https://example.invalid/v1?key=value",
                                  "https://example.invalid/v1#fragment", "file:///tmp/api"])
def test_credential_bearing_or_non_http_url_is_rejected_before_prepare(tmp_path, url):
    root = tmp_path / "absent"
    key = tmp_path / "key"
    key.write_text("fixture-only-value")
    key.chmod(0o600)
    result = invoke("prepare", "--provider", "both", "--root", root,
                    "--llm-base-url", url, "--llm-model", "fixture-model", "--llm-api-key-file", key)
    assert result.returncode != 0
    assert not root.exists()
    assert "fixture-only-value" not in result.stdout + result.stderr


def test_lifecycle_cannot_adopt_arbitrary_existing_directory(tmp_path):
    for action in ["up", "check", "down"]:
        result = invoke(action, "--root", tmp_path)
        assert result.returncode != 0
        assert "ok" in json.loads(result.stdout)


def test_private_key_failure_does_not_leave_half_created_root(tmp_path):
    root = tmp_path / "absent"
    key = tmp_path / "public-key"
    key.write_text("fixture-only-value")
    key.chmod(0o644)
    result = invoke("prepare", "--provider", "openviking", "--root", root,
                    "--llm-base-url", "https://example.invalid/v1", "--llm-model", "fixture-model",
                    "--llm-api-key-file", key)
    assert result.returncode != 0
    assert not root.exists()
    assert "fixture-only-value" not in result.stdout + result.stderr
