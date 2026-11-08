"""An old shell snapshot cannot override the current invocation's child identity."""
import os
import shlex
import subprocess

import pytest

from tools.environments.base_session_env import _wrap_command_script


@pytest.mark.platforms("posix")
@pytest.mark.parametrize("current", [None, "/fixture/current-board"])
def test_stale_snapshot_never_restores_foreign_child_context(tmp_path, current):
    marker = "HERMES_DELEGATED_CHILD_CONTEXT"
    snapshot = tmp_path / "old-snapshot"
    snapshot.write_text(f"export {marker}=/fixture/old-board\n")
    env = dict(os.environ)
    env.pop(marker, None)
    if current is not None:
        env[marker] = current
    script = _wrap_command_script(
        f'printf "IDENTITY=%s\\n" "${{{marker}-unset}}"',
        quoted_cwd=shlex.quote(str(tmp_path)), quoted_snap=shlex.quote(str(snapshot)),
        snap_tmp_template=shlex.quote(str(snapshot) + ".XXXXXXXXXX"),
        passthrough_names=(), snapshot_ready=True, cwd_marker="fixture_cwd",
    )
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert f"IDENTITY={current or 'unset'}\n" in result.stdout
    assert marker not in snapshot.read_text()
