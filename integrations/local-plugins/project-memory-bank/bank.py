"""Selective file-based project memory; upstream code stays unmodified."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

UPSTREAM = Path(__file__).resolve().parent / "runtime"
UPSTREAM_SHA = "bde42c698f9e20ea196ce2add463c10910b98e64"
CORE = ("status.md", "checklist.md", "roadmap.md", "progress.md", "lessons.md", "agreements.md", "backlog.md")
MAX_FILE_BYTES = 1024 * 1024


def home() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()).expanduser().resolve()


def state() -> Path:
    root = home() / "project-memory"
    if root.is_symlink():
        raise ValueError("Project-memory state root must not be a symlink")
    return root


def key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def project_path(project: str) -> Path:
    p = Path(project).expanduser().resolve(strict=True)
    if not p.is_dir() or p in (Path.home().resolve(), Path(p.anchor)):
        raise ValueError("Select a concrete project directory, not HOME or filesystem root")
    return p


def bank_path(project: str) -> Path:
    return state() / "projects" / key(str(project_path(project))) / ".memory-bank"


def safe(path: Path, root: Path) -> Path:
    if root.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Refusing symlink or escaped path: {path}")
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ValueError(f"Refusing symlink: {current}")
        current = current.parent
    return path


def write(path: Path, text: str, root: Path) -> None:
    safe(path, root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".pm-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read(path: Path, root: Path) -> str:
    safe(path, root)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return ""
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError("Bank files must be regular files of at most 1 MiB")
        value = f.read(MAX_FILE_BYTES + 1)
        if len(value) > MAX_FILE_BYTES:
            raise ValueError("Bank file grew beyond the read budget")
        return value.decode("utf-8")


@contextmanager
def locked(bank: Path):
    safe(bank / ".hermes.lock", state())
    fd = os.open(bank / ".hermes.lock", os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError("Bank lock must be a regular file")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def initialize(project: str) -> Path:
    p = project_path(project)
    bank = safe(bank_path(str(p)), state())
    bank.mkdir(parents=True, exist_ok=True, mode=0o700)
    if bank.stat().st_uid != os.getuid():
        raise ValueError("Bank directory must belong to the current user")
    bank.chmod(0o700)
    with locked(bank):
        templates = {
            "status.md": "# Project status\n\n## Goal\nNot set.\n\n## Current state\nNot assessed.\n\n## Next step\nRead project sources and define the task.\n\n## Blockers\nNot assessed.\n",
            "checklist.md": "# Checklist\n",
            "roadmap.md": "# Roadmap\n\n<!-- mb-active-plans -->\n<!-- /mb-active-plans -->\n",
            "progress.md": "# Progress\n",
            "lessons.md": "# Lessons\n",
            "backlog.md": "# Backlog\n",
            ".hermes-project.json": json.dumps({"project": str(p), "created": now(), "upstream": UPSTREAM_SHA}, indent=2),
        }
        for name, text in templates.items():
            if not safe(bank / name, state()).exists():
                write(bank / name, text, state())
        for name in ("plans", "notes", "reports", "handoff"):
            safe(bank / name, state()).mkdir(exist_ok=True, mode=0o700)
    return bank


def locate(project: str) -> Path:
    bank = safe(bank_path(project), state())
    if not (bank / ".hermes-project.json").is_file():
        raise FileNotFoundError("No project bank; initialize explicitly")
    return bank


def bind(session: str, project: str) -> Path:
    if not session:
        raise ValueError("Session ID is required")
    bank = locate(project)
    path = state() / "sessions" / (key(session) + ".json")
    write(path, json.dumps({"project": str(project_path(project))}), state())
    return bank


def bound(session: str) -> Path | None:
    if not session:
        return None
    path = state() / "sessions" / (key(session) + ".json")
    if not safe(path, state()).exists():
        return None
    return locate(json.loads(read(path, state()))["project"])


def digest(bank: Path) -> str:
    return key("\0".join(name + "\0" + read(bank / name, bank) for name in CORE))


def revision(bank: Path) -> str | None:
    p = json.loads(read(bank / ".hermes-project.json", bank))["project"]
    # No code traversal, indexing, dirty-file discovery or monorepo-root scanning.
    run = subprocess.run(["git", "-C", p, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3, check=False)
    return run.stdout.strip() if run.returncode == 0 else None


def checkpoint(bank: Path) -> None:
    write(bank / ".checkpoint.json", json.dumps({"bank": digest(bank), "revision": revision(bank), "at": now()}), bank)


def freshness(bank: Path) -> dict:
    raw = read(bank / ".checkpoint.json", bank)
    old = json.loads(raw) if raw else {}
    current = revision(bank)
    return {"checkpoint_exists": bool(old), "bank_changed": old.get("bank") != digest(bank),
            "revision_changed": current != old.get("revision") if current else None,
            "revision_available": current is not None,
            "scope": "committed HEAD only; working-tree edits are not assessed"}


def upstream() -> Path:
    # This is an integrity check, not a signature: the reviewed fork commit is the trust anchor.
    manifest = json.loads((UPSTREAM / "SHA256SUMS.json").read_text())
    for name, expected in manifest.items():
        path = safe(UPSTREAM / name, UPSTREAM)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Vendored helper integrity mismatch")
    return UPSTREAM


def handoff(bank: Path, session: str = "") -> Path:
    source = upstream()
    with locked(bank):
        for name in ("handoff", "handoff/latest.md", "handoff/.digest", "handoff/archive"):
            safe(bank / name, bank)
        for name in ("handoff/latest.md", "handoff/.digest"):
            read(bank / name, bank)
        signature = digest(bank)
        if (bank / "handoff/latest.md").is_file() and read(bank / "handoff/.digest", bank) == signature:
            (bank / "handoff/latest.md").chmod(0o600)
            return bank / "handoff/latest.md"
        for name in CORE:
            safe(bank / name, bank)
        env = {**os.environ, "PYTHONPATH": str(source), "MB_PYTHON": sys.executable,
               "MB_SESSION_ID": session, "MB_HANDOFF_LOCK_TIMEOUT": "1"}
        subprocess.run(["bash", str(source / "scripts/mb-handoff.sh"), "--actualize", str(bank), "hermes_checkpoint"],
                       env=env, cwd=source, check=True, capture_output=True, text=True, timeout=8, umask=0o077)
        write(bank / "handoff/.digest", signature, bank)
    return bank / "handoff/latest.md"


def agree(bank: Path, statement: str, source: str, supersedes: int | None) -> str:
    if not source.strip():
        raise ValueError("Agreement requires operator confirmation provenance")
    repo = upstream()
    for path in (bank / "agreements.md", bank.parent / "AGENTS.md", bank.parent / "CLAUDE.md"):
        read(path, state())
    args = ["bash", str(repo / "scripts/mb-agree.sh"), "add", statement, "--source", source]
    if supersedes is not None:
        args += ["--supersedes", str(supersedes)]
    args.append(str(bank))
    env = {**os.environ, "MB_AGREEMENTS_PROJECT_ROOT": str(bank.parent), "MB_PYTHON": sys.executable}
    with locked(bank):
        return subprocess.run(args, cwd=repo, env=env, check=True, capture_output=True, text=True, timeout=15, umask=0o077).stdout


def verify_report(report: dict) -> dict:
    errors = []
    if not isinstance(report, dict):
        return {"passed": False, "errors": ["Report must be an object"]}
    checks = report.get("checks", [])
    agreements = report.get("agreements", [])
    if not isinstance(checks, list) or not checks:
        errors.append("No acceptance checks")
        checks = []
    if not isinstance(agreements, list):
        errors.append("agreements must be an array")
        agreements = []
    seen = set()
    for is_agreement, row in [(False, x) for x in checks] + [(True, x) for x in agreements]:
        if not isinstance(row, dict):
            errors.append("Invalid check row")
            continue
        ident = row.get("id")
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            errors.append("Missing or duplicate check ID")
        if isinstance(ident, str):
            seen.add(ident)
        allowed = {"satisfied", "not-applicable"} if is_agreement else {"pass"}
        if not isinstance(row.get("result"), str) or row["result"] not in allowed:
            errors.append(f"{ident}: not passed")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(x, str) or not x.strip() for x in evidence):
            errors.append(f"{ident}: evidence required")
    return {"passed": not errors, "errors": errors,
            "scope": "report structure and supplied outcomes; reviewer must establish source coverage and evidence validity"}
