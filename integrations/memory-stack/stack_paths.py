"""Private, fresh-root boundaries shared by the optional memory-stack CLI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import tempfile


SCHEMA = 1


def provider_names(value: str) -> list[str]:
    choices = {"honcho": ["honcho"], "openviking": ["openviking"], "both": ["honcho", "openviking"]}
    if value not in choices:
        raise ValueError("provider must be honcho, openviking, or both")
    return choices[value]


def physical_path(value: Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("an absolute physical root without '..' is required")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("symlink paths are not allowed")
    return path


def private_write(path: Path, data: str | bytes) -> None:
    content = data.encode() if isinstance(data, str) else data
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def save_state(root: Path, state: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".state-", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, root / "state.json")
    finally:
        temporary.unlink(missing_ok=True)


def create_root(value: Path, provider: str) -> dict:
    provider_names(provider)
    root = physical_path(value)
    if root.exists() or root.is_symlink():
        raise FileExistsError("root must not exist; existing directories are never merged")
    checkout = Path(__file__).resolve().parents[2]
    if root.is_relative_to(checkout) or any((parent / ".git").exists() for parent in root.parents):
        raise ValueError("runtime data and credentials must be outside every Git worktree")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    state = {"schema": SCHEMA, "root": str(root), "owner_uid": os.getuid(),
             "project": "hermes-memory-" + identity, "provider": provider, "prepared": False}
    private_write(root / "state.json", json.dumps(state, indent=2) + "\n")
    return state


def load_root(value: Path) -> dict:
    root = physical_path(value)
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("root must be an owned private directory (0700)")
    marker = root / "state.json"
    descriptor = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) & 0o077:
            raise ValueError("invalid ownership marker")
        state = json.load(stream)
    expected = "hermes-memory-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    if state.get("schema") != SCHEMA or state.get("owner_uid") != os.getuid():
        raise ValueError("unsupported or foreign ownership marker")
    if state.get("root") != str(root) or state.get("project") != expected:
        raise ValueError("ownership marker belongs to a different root")
    provider_names(state.get("provider"))
    return state


def read_key(value: Path) -> str:
    key = physical_path(value)
    descriptor = os.open(key, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("key file must be regular, owned, and private (0600 or 0400)")
        content = stream.read(32769).strip()
    if not content or len(content) > 32768 or any(ord(char) <= 32 or ord(char) >= 127 for char in content):
        raise ValueError("key file must contain one nonempty ASCII credential, without spaces")
    return content


def validate_ports(ports: dict[str, int]) -> None:
    values = list(ports.values())
    if any(type(port) is not int or not 1024 <= port <= 65535 for port in values):
        raise ValueError("ports must be unprivileged integers from 1024 to 65535")
    if len(set(values)) != len(values):
        raise ValueError("service ports must be distinct")


def require_free_ports(ports: dict[str, int]) -> None:
    validate_ports(ports)
    for name, port in ports.items():
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise ValueError(f"{name}: requested loopback port {port} is unavailable") from error
