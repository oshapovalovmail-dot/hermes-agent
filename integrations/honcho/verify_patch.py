"""Validate the exported patch against an explicit local immutable Honcho source.

Never imports or writes the source checkout. Does not clone, start services, or
fetch model weights. The test interpreter and its dependencies are caller-owned.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

BASE = "2ad56a4d715b015d744ea86f05a287069d264898"
FILES = ("pyproject.toml", "src/config.py", "src/embedding_client.py", "tests/llm/test_embedding_client.py")


def verify(source: Path, python: Path) -> int:
    patch = Path(__file__).with_name("exact-tokenizer.patch")
    with tempfile.TemporaryDirectory(prefix="honcho-patch-") as td:
        sandbox = Path(td)
        # Read only immutable Git objects. No checkout config, .env, skills, or runtime state.
        archive = subprocess.check_output(["git", "-C", str(source), "archive", BASE, "src", *FILES])
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(sandbox, filter="data")
        for args in (["--check"], []):
            subprocess.run(["git", "apply", *args, str(patch)], cwd=sandbox, check=True)
        # Run the actual patched module outside Honcho's app/database conftests.
        tests = sandbox / "unit"
        tests.mkdir()
        (tests / "test_embedding_client.py").write_bytes((sandbox / FILES[-1]).read_bytes())
        (tests / "conftest.py").write_text(
            'import socket\nimport pytest\n'
            '@pytest.fixture(autouse=True)\n'
            'def no_network(monkeypatch):\n'
            '    def denied(*a, **k):\n'
            '        raise AssertionError("Honcho patch unit tests must not reach the network")\n'
            '    monkeypatch.setattr(socket, "create_connection", denied)\n'
            '    monkeypatch.setattr(socket.socket, "connect", denied)\n'
        )
        home = sandbox / "home"
        home.mkdir()
        # No inherited API credentials, .env lookup outside sandbox, or service addresses.
        env = {"HOME": str(home), "PATH": os.defpath, "PYTHONPATH": str(sandbox), "TZ": "UTC",
               "TIKTOKEN_CACHE_DIR": os.environ.get("TIKTOKEN_CACHE_DIR", str(home / "tiktoken"))}
        print("base=" + BASE + " patch_sha256=" + hashlib.sha256(patch.read_bytes()).hexdigest(), flush=True)
        return subprocess.run([str(python), "-m", "pytest", "-c", "/dev/null", "--confcutdir", str(tests),
                               "-o", "asyncio_mode=auto", "-o", "asyncio_default_fixture_loop_scope=function",
                               str(tests / "test_embedding_client.py"), "-q", "--tb=short", "-p", "no:cacheprovider"],
                              cwd=sandbox, env=env).returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    options = parser.parse_args()
    raise SystemExit(verify(options.source, options.python))
