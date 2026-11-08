"""Reconstruct reviewed catalog plugins into a NEW explicit staging directory.

No imports of provider code, dependency installs, config writes or service starts.
Network access requires --fetch; an existing pinned Git cache works fully offline.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent


def git(*args: str, cwd: Path | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, timeout=120,
    ).stdout


def digest(files: dict[str, bytes]) -> str:
    """Bind canonical paths and bytes, independent of archive headers or mtimes."""
    rows = [[name, hashlib.sha256(data).hexdigest()] for name, data in sorted(files.items())]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def source_files(cache: Path, pin: dict) -> dict[str, bytes]:
    """Read only the immutable commit object, never a cache working tree."""
    archive = git("archive", "--format=tar", f"{pin['commit']}:{pin['subdir']}", cwd=cache)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or str(path) != member.name.rstrip("/"):
                raise ValueError(f"Noncanonical archive path: {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"Unsupported archive entry: {member.name}")
            if member.name in files:
                raise ValueError(f"Duplicate archive entry: {member.name}")
            files[member.name] = stream.extractfile(member).read()
    if digest(files) != pin["source_sha256"]:
        raise ValueError("Pinned source digest mismatch")
    return files


def fetch_source(cache: Path, pin: dict) -> None:
    """Explicit network operation; never changes an existing checkout or remote."""
    if cache.exists():
        raise FileExistsError(f"Refusing to change existing cache: {cache}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    git("init", "--bare", str(cache))
    git("-C", str(cache), "fetch", "--depth=1", pin["repo"], pin["commit"])


def reconstruct(name: str, destination: Path, cache_root: Path, *, fetch: bool = False) -> Path:
    """Validate source + patch before applying, then verify exact resulting bytes."""
    manifest = json.loads((HERE / "manifest.json").read_text())
    pin = manifest["providers"][name]
    cache = cache_root.resolve() / name
    if fetch and not cache.exists():
        fetch_source(cache, pin)
    files = source_files(cache, pin)
    patch = (HERE / "patches" / f"{name}.patch").read_bytes()
    if hashlib.sha256(patch).hexdigest() != pin["patch_sha256"]:
        raise ValueError("Patch digest mismatch")
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Destination must be new: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".memory-stage-", dir=destination.parent) as tmp:
        stage = Path(tmp)
        for relative, data in files.items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        apply_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        apply_env.update(GIT_CEILING_DIRECTORIES=str(stage), GIT_CONFIG_NOSYSTEM="1",
                         GIT_CONFIG_GLOBAL=os.devnull)
        for flags in [("--check",), ()]:
            subprocess.run(["git", "apply", "--unidiff-zero", *flags, "-"], cwd=stage, input=patch,
                           check=True, capture_output=True, env=apply_env, timeout=30)
        result = {str(p.relative_to(stage)): p.read_bytes() for p in stage.rglob("*") if p.is_file()}
        if any(p.is_symlink() for p in stage.rglob("*")) or digest(result) != pin["result_sha256"]:
            raise ValueError("Reconstructed plugin digest mismatch")
        # Copy into a new directory, never merge with an installed provider.
        shutil.copytree(stage, destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=("honcho", "openviking"))
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="opt in to fetching a missing pinned cache")
    args = parser.parse_args()
    print(reconstruct(args.provider, args.destination, args.source_cache, fetch=args.fetch))


if __name__ == "__main__":
    main()
