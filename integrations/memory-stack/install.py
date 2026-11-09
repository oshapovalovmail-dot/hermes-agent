#!/usr/bin/env python3
"""Prepare/start/check/stop an explicitly owned, fresh Hermes memory stack."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse

from stack_checks import check
from stack_paths import (create_root, load_root, physical_path, provider_names,
                         read_key, require_free_ports, save_state, validate_ports)
from stack_render import render
from stack_sources import PINS, honcho_source, model_assets, providers, stage_frida


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def inventory(root: Path) -> dict:
    paths = [root / "compose.json"]
    for directory in (root / "build", root / "hermes-home/plugins"):
        physical_path(directory)
        paths += list(directory.rglob("*"))
    paths += [root / "hermes-home" / name for name in (".env", "honcho.json", "ovcli.conf")
              if (root / "hermes-home" / name).exists()]
    if (root / "ov-template.json").exists():
        paths.append(root / "ov-template.json")
    result = {}
    for path in paths:
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(root / "build") or not target.exists():
                raise ValueError("source symlink leaves the owned build tree or is dangling")
            result[str(path.relative_to(root))] = {"symlink": os.readlink(path)}
            continue
        if path.is_file():
            physical_path(path)
            result[str(path.relative_to(root))] = digest(path)
    return result


def verify_inventory(root: Path, state: dict) -> None:
    if state.get("prepared") is not True:
        raise ValueError("root preparation did not finish; no services may be adopted")
    for relative, expected in state["inventory"].items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("invalid prepared-file inventory")
        path = root / path
        if isinstance(expected, dict):
            physical_path(path.parent)
            if (not path.is_symlink() or os.readlink(path) != expected.get("symlink")
                    or not path.resolve().is_relative_to(root / "build") or not path.resolve().exists()):
                raise ValueError("prepared source symlink changed or left the owned build tree")
            continue
        path = physical_path(path)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"prepared file changed: {relative}; use the original reviewed snapshot")
    if inventory(root) != state["inventory"]:
        raise ValueError("prepared input inventory changed; use the original reviewed snapshot")


def verify_writable_binds(root: Path, state: dict) -> None:
    names = provider_names(state["provider"])
    directories = (["postgres", "redis"] if "honcho" in names else [])
    directories += (["openviking"] if "openviking" in names else [])
    data = physical_path(root / "data")
    if not data.is_dir() or data.stat().st_uid != os.getuid():
        raise ValueError("mutable bind parent must be an owned physical data directory")
    for name in directories:
        path = physical_path(data / name)
        # Database entrypoints may legitimately chown their own mount on Linux.
        if not path.is_dir():
            raise ValueError("mutable bind must be a physical data directory")
    keys = ["llm.key"] + (["postgres.key"] if "honcho" in names else [])
    keys += (["openviking.key"] if "openviking" in names else [])
    for name in keys:
        read_key(root / name)  # Rotatable contents; the physical/private boundary remains mandatory.


def verify_model_assets(root: Path) -> None:
    for name, expected in PINS["assets"].items():
        path = physical_path(root / "model" / name)
        if path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
            raise ValueError(f"pinned model asset changed: {name}")


def docker_output(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError("Docker command failed; Docker Engine and Compose v2 must be available")
    return result.stdout


def owned_containers(root: Path, state: dict, *, require_running: bool = False) -> None:
    ids = docker_output("ps", "-aq", "--filter", "label=com.docker.compose.project=" + state["project"]).split()
    if require_running and not ids:
        raise ValueError("no containers belonging to this prepared stack are running")
    rows = json.loads(docker_output("inspect", *ids)) if ids else []
    published = {}
    for container in rows:
        labels = container["Config"]["Labels"] or {}
        if labels.get("com.docker.compose.project.working_dir") != str(root):
            raise ValueError("matching Compose project belongs to another working directory")
        files = labels.get("com.docker.compose.project.config_files", "").split(",")
        if str(root / "compose.json") not in files:
            raise ValueError("matching Compose project belongs to another configuration")
        service = labels.get("com.docker.compose.service")
        if container["State"]["Running"]:
            published[service] = {int(binding["HostPort"]): binding["HostIp"]
                                  for values in container["NetworkSettings"]["Ports"].values() if values
                                  for binding in values}
    if require_running:
        service_names = {"frida": "frida", "honcho": "honcho-api", "openviking": "openviking"}
        for name, port in state["ports"].items():
            if published.get(service_names[name], {}).get(port) != "127.0.0.1":
                raise ValueError(f"owned {name} does not publish the exact prepared loopback endpoint")


def compose(root: Path, state: dict, arguments: list[str], *, timeout: int) -> None:
    command = ["docker", "compose", "--project-name", state["project"], "--project-directory", str(root),
               "--file", str(root / "compose.json"), *arguments]
    result = subprocess.run(command, stdout=sys.stderr, stderr=sys.stderr, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("owned Compose operation failed; inspect this stack's logs, not another deployment")


def prepare(args) -> dict:
    names = provider_names(args.provider)
    root = physical_path(args.root)
    url = urllib.parse.urlsplit(args.llm_base_url)
    if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("LLM base URL must be HTTP(S), without credentials, query or fragment")
    if not args.llm_model.strip() or any(ord(char) <= 32 for char in args.llm_model):
        raise ValueError("a nonempty explicit LLM model identifier is required")
    key = read_key(args.llm_api_key_file)
    ports = {"frida": args.frida_port}
    if "honcho" in names:
        ports["honcho"] = 18500 if args.honcho_port is None else args.honcho_port
    elif args.honcho_port is not None:
        raise ValueError("--honcho-port is only valid when Honcho is selected")
    if "openviking" in names:
        ports["openviking"] = 18533 if args.openviking_port is None else args.openviking_port
    elif args.openviking_port is not None:
        raise ValueError("--openviking-port is only valid when OpenViking is selected")
    validate_ports(ports)
    require_free_ports(ports)
    state = create_root(root, args.provider)
    state.update(ports=ports, llm_base_url=args.llm_base_url.rstrip("/"), llm_model=args.llm_model)
    save_state(root, state)
    (root / "build").mkdir(mode=0o700)
    (root / "hermes-home").mkdir(mode=0o700)
    state["model_assets"] = model_assets(root / "model", args.model_cache)
    state["providers"] = providers(root / "hermes-home/plugins", names, args.source_cache)
    stage_frida(root / "build/frida")
    if "honcho" in names:
        honcho_source(root / "build/honcho", args.honcho_source_cache)
    render(root, state, state["llm_base_url"], args.llm_model, key)
    state.update(prepared=True, inventory=inventory(root))
    save_state(root, state)
    return {"ok": True, "stage": "prepared", "provider": args.provider, "root": str(root),
            "hermes_home": str(root / "hermes-home"), "project": state["project"], "ports": ports,
            "services_started": False, "derivation_verified": False}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="action", required=True)
    setup = commands.add_parser("prepare", help="fetch pinned artifacts into a NEW explicit root; start nothing")
    setup.add_argument("--provider", choices=["honcho", "openviking", "both"], required=True)
    setup.add_argument("--root", type=Path, required=True)
    setup.add_argument("--llm-base-url", required=True)
    setup.add_argument("--llm-model", required=True)
    setup.add_argument("--llm-api-key-file", type=Path, required=True)
    setup.add_argument("--model-cache", type=Path, help="read-only directory containing the pinned model assets")
    setup.add_argument("--source-cache", type=Path, help="read-only native provider Git caches, honcho/openviking")
    setup.add_argument("--honcho-source-cache", type=Path, help="read-only Git source containing the pinned backend commit")
    setup.add_argument("--frida-port", type=int, default=18501)
    setup.add_argument("--honcho-port", type=int)
    setup.add_argument("--openviking-port", type=int)
    for name, text in [("up", "build/start only the owned project"),
                       ("check", "real embeddings/storage/derived-memory checks in synthetic probe scopes"),
                       ("down", "stop only the owned project, retaining all persistent data")]:
        command = commands.add_parser(name, help=text)
        command.add_argument("--root", type=Path, required=True)
        if name in {"up", "check"}:
            command.add_argument("--timeout", type=int, default=180 if name == "up" else 120)
        if name == "check":
            command.add_argument("--storage-only", action="store_true", help="explicitly omit LLM derivation, never mark it verified")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if hasattr(args, "timeout") and args.timeout < 1:
            raise ValueError("timeout must be positive")
        if args.action == "prepare":
            report = prepare(args)
        else:
            root = physical_path(args.root)
            state = load_root(root)
            if args.action != "down":
                verify_inventory(root, state)
                verify_model_assets(root)
                verify_writable_binds(root, state)
            owned_containers(root, state, require_running=args.action == "check")
            if args.action == "up":
                compose(root, state, ["config", "--quiet"], timeout=30)
                compose(root, state, ["up", "--detach", "--build", "--force-recreate", "--wait",
                                      "--wait-timeout", str(args.timeout)], timeout=max(1800, args.timeout + 60))
                owned_containers(root, state, require_running=True)
                report = {"ok": True, "stage": "running", "root": str(root), "derivation_verified": False}
            elif args.action == "down":
                compose(root, state, ["down", "--timeout", "30"], timeout=90)
                if docker_output("ps", "-q", "--filter", "label=com.docker.compose.project=" + state["project"]).strip():
                    raise RuntimeError("owned containers remain running after down")
                report = {"ok": True, "stage": "stopped", "data_retained": True, "root": str(root)}
            else:
                report = check(state, storage_only=args.storage_only, timeout=args.timeout)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "stage": args.action, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
