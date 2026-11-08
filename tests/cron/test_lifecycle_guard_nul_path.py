"""NUL-bearing pseudo-paths are unreadable, never a preflight crash."""
from pathlib import Path

import pytest

from cron import lifecycle_guard


@pytest.mark.parametrize("path", ["/tmp/no-script\x00payload", "~bad\x00payload"])
def test_nul_path_is_unreadable_without_guard_crash(path):
    assert lifecycle_guard._read_referenced_script(Path(path)) == (None, False)


def test_binary_pseudo_path_does_not_crash_command_scan():
    assert not lifecycle_guard.contains_gateway_lifecycle_command_or_referenced_script(
        "bash '/tmp/not-a-script\x00payload'", cwd="/tmp")
