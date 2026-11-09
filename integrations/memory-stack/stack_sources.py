"""Immutable source/model preparation; never reads a live service worktree."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

from stack_paths import physical_path, private_write

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PINS = json.loads((HERE / "pins.json").read_text())


def clean_environment() -> dict:
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("GIT_", "OPENAI_", "ANTHROPIC_", "GEMINI_", "UV_"))}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
    return env


def git(directory: Path, *args: str, timeout: int = 240) -> bytes:
    result = subprocess.run(["git", "-C", str(directory), *args], env=clean_environment(),
                            capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"pinned Git operation failed ({args[0]}); no source fallback")
    return result.stdout


def fetch_cache(destination: Path, url: str, revision: str) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("source cache destination must be new")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(destination)], env=clean_environment(),
                   check=True, capture_output=True, timeout=30)
    git(destination, "remote", "add", "origin", url)
    git(destination, "config", "remote.origin.promisor", "true")
    git(destination, "config", "remote.origin.partialclonefilter", "blob:none")
    git(destination, "-c", "http.lowSpeedLimit=1024", "-c", "http.lowSpeedTime=60",
        "fetch", "--filter=blob:none", "--depth=1", "origin", revision)
    if git(destination, "rev-parse", "FETCH_HEAD").decode().strip() != revision:
        raise ValueError("fetched source commit differs from pin")


def model_assets(destination: Path, cache: Path | None = None) -> dict:
    destination.mkdir(mode=0o755)
    if cache is not None:
        cache = physical_path(cache)
    manifest = {}
    for name, expected in PINS["assets"].items():
        output = destination / name
        if cache is None:
            url = (f"https://huggingface.co/{PINS['hf_repo']}/resolve/"
                   f"{PINS['hf_revision']}/{name}")
            source = urllib.request.urlopen(url, timeout=120)
        else:
            origin = physical_path(cache / name)
            if origin.stat().st_size != expected["size"]:
                raise ValueError(f"cached model size mismatch: {name}")
            source = origin.open("rb")
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with source, os.fdopen(descriptor, "wb") as target:
            os.fchmod(target.fileno(), 0o644)
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > expected["size"]:
                    raise ValueError(f"model download exceeds expected size: {name}")
                digest.update(block)
                target.write(block)
        if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
            output.unlink()
            raise ValueError(f"model SHA-256/size mismatch: {name}")
        manifest[name] = {"size": size, "sha256": digest.hexdigest()}
    return manifest


def providers(destination: Path, names: list[str], cache: Path | None = None) -> dict:
    helper_path = REPO / "integrations/memory-providers/install.py"
    spec = importlib.util.spec_from_file_location("stack_provider_reconstruction", helper_path)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    manifest = json.loads(helper_path.with_name("manifest.json").read_text())
    if cache is not None:
        cache = physical_path(cache)
    else:
        cache = destination.parent.parent / "source-cache"
        for name in names:
            pin = manifest["providers"][name]
            fetch_cache(cache / name, pin["repo"], pin["commit"])
    for name in names:
        helper.reconstruct(name, destination / name, cache)
        if name == "openviking":
            apply_external_patch(destination / name)
    return {name: manifest["providers"][name] for name in names}


def apply_external_patch(plugin: Path) -> None:
    """Extend only the installer-owned native plugin, with exact input/output pins."""
    pins = PINS["openviking_external"]
    patch = HERE / "openviking-external.patch"
    entry = plugin / "__init__.py"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != pins["patch_sha256"]:
        raise ValueError("external Compose patch differs from its pin")
    if hashlib.sha256(entry.read_bytes()).hexdigest() != pins["baseline_sha256"]:
        raise ValueError("external Compose plugin preimage differs from its pin")
    for flags in [("--check",), ()]:
        git(plugin, "apply", *flags, str(patch))
    if hashlib.sha256(entry.read_bytes()).hexdigest() != pins["postimage_sha256"]:
        raise ValueError("external Compose plugin postimage differs from its pin")
    private_write(plugin / "EXTERNAL_COMPOSE_PATCH.json", json.dumps(pins, indent=2) + "\n")


def honcho_source(destination: Path, source: Path | None = None) -> None:
    cache = destination.parent / "honcho-git"
    if source is not None:
        source = physical_path(source)
        if git(source, "cat-file", "-t", PINS["honcho_commit"]).strip() != b"commit":
            raise ValueError("backend source cache lacks the pinned Honcho commit")
        fetch_cache(cache, str(source), PINS["honcho_commit"])
    else:
        fetch_cache(cache, "https://github.com/plastic-labs/honcho", PINS["honcho_commit"])
    # A new detached worktree, never a checkout/reset in a user-supplied source.
    git(cache, "worktree", "add", "--detach", str(destination), PINS["honcho_commit"])
    patch = REPO / "integrations/honcho/exact-tokenizer.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != PINS["honcho_patch_sha256"]:
        raise ValueError("Honcho exact-tokenizer patch SHA-256 mismatch")
    for flags in [("--check",), ()]:
        git(destination, "apply", *flags, str(patch))
    lock_patch = HERE / "honcho-lock.patch"
    if not lock_patch.is_file() or hashlib.sha256(lock_patch.read_bytes()).hexdigest() != PINS["honcho_lock_patch_sha256"]:
        raise ValueError("reviewed Honcho dependency lock patch is missing or changed")
    for flags in [("--check",), ()]:
        git(destination, "apply", *flags, str(lock_patch))


def stage_frida(destination: Path) -> None:
    destination.mkdir()
    for name in ["server.py", "requirements-runtime.lock"]:
        shutil.copyfile(REPO / "integrations/frida" / name, destination / name)
