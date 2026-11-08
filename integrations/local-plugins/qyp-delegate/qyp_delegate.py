from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

MAX_OUTPUT = 50_000
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _settings():
    from hermes_cli.config import load_config_readonly
    settings = ((load_config_readonly() or {}).get("plugins", {}).get("entries", {})
                .get("qyp-delegate", {}).get("settings", {}))
    if settings.get("enabled") is not True:
        raise ValueError("QYP delegation is disabled; explicit operator approval/configuration required")
    for key in ("host", "remote_home", "remote_hermes_home", "remote_hermes", "default_workdir", "allowed_roots"):
        if not settings.get(key):
            raise ValueError("Missing QYP setting: " + key)
    if not re.fullmatch(r"[a-zA-Z0-9_.@-]+", settings["host"]) or settings["host"].startswith("-"):
        raise ValueError("Invalid SSH host")
    if not isinstance(settings["allowed_roots"], list):
        raise ValueError("allowed_roots must be an array")
    home = PurePosixPath(settings["remote_home"])
    if not home.is_absolute() or home == PurePosixPath("/") or ".." in home.parts:
        raise ValueError("remote_home must be a concrete absolute directory")
    for raw in settings["allowed_roots"]:
        path = PurePosixPath(raw)
        if not path.is_relative_to(home) or path == home or ".." in path.parts:
            raise ValueError("allowed_roots must be concrete subtrees of remote_home")
    return settings


DELEGATE_QYP_SCHEMA = {
    "name": "delegate_qyp",
    "description": (
        "Delegate a bounded task to the configured SSH worker. Use action=submit with wait=true for a "
        "foreground result or wait=false for a durable background job; then use "
        "action=status/cancel with job_id. mode=execution keeps inference local and "
        "exposes only qyp_terminal to the child; mode=remote_agent runs Hermes itself "
        "on QYP and requires model egress plus remote credentials; auto defaults to "
        "execution so endpoint reachability cannot be mistaken for auth readiness. "
        "Arcadia workdirs are "
        "restricted to the configured allowlist. Do not use this for macOS GUI tasks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["submit", "status", "cancel"], "default": "submit"},
            "goal": {"type": "string", "description": "Self-contained task for the worker."},
            "job_id": {"type": "string", "description": "Required for status/cancel."},
            "mode": {"type": "string", "enum": ["auto", "execution", "remote_agent"], "default": "auto"},
            "workdir": {"type": "string", "default": ""},
            "wait": {"type": "boolean", "default": True},
            "timeout": {"type": "integer", "minimum": 10, "maximum": 3600, "default": 900},
            "max_turns": {"type": "integer", "minimum": 1, "maximum": 500, "default": 120},
            "toolsets": {"type": "array", "items": {"type": "string"}},
            "skills": {"type": "array", "items": {"type": "string"}},
        },
    },
}

QYP_TERMINAL_SCHEMA = {
    "name": "qyp_terminal",
    "description": (
        "Execute one shell command on the configured SSH worker. Intended only for a child created by "
        "delegate_qyp execution mode. The command runs in a validated remote workdir. "
        "Return actual stdout/stderr and exit code; verify side effects explicitly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "workdir": {"type": "string", "default": ""},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 3600, "default": 180},
        },
        "required": ["command"],
    },
}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_names(values: Any, *, field: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{field} must be an array")
    result: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if not value or not _SAFE_NAME.fullmatch(value):
            raise ValueError(f"invalid {field} entry: {value!r}")
        if value not in result:
            result.append(value)
    return result


def validate_workdir(raw: str | None) -> str:
    settings = _settings()
    path = PurePosixPath(str(raw or settings["default_workdir"]).strip())
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("workdir must be absolute and contain no '..'")
    if not any(path.is_relative_to(PurePosixPath(root)) for root in settings["allowed_roots"]):
        raise ValueError("workdir must start inside a configured allowed subtree")
    return str(path)


def _remote_cd(workdir):
    # Check the physical cwd too: a remote symlink must not escape an approved root.
    roots = _settings()["allowed_roots"]
    checks = " || ".join('[ "$PWD" = ' + shlex.quote(r) + ' ] || [[ "$PWD" == ' + shlex.quote(r.rstrip("/") + "/") + '* ]]' for r in roots)
    return "cd -P " + shlex.quote(workdir) + " && ( " + checks + " )"


def check_qyp_delegate_available() -> bool:
    try:
        _settings()
    except ValueError:
        return False
    return shutil.which("ssh") is not None


def _ssh_prefix() -> list[str]:
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        _settings()["host"],
    ]


def resolve_mode(mode: str) -> str:
    normalized = str(mode or "auto").strip().lower()
    if normalized not in {"auto", "execution", "remote_agent"}:
        raise ValueError("mode must be auto, execution, or remote_agent")
    if normalized == "auto":
        # Network reachability proves only egress. It says nothing about the
        # selected remote Hermes profile or whether its OAuth credentials are
        # present and fresh. Keep automatic delegation on the deterministic
        # local-inference path; callers that intentionally provisioned remote
        # inference can still request remote_agent explicitly.
        return "execution"
    return normalized


def _augment_execution_goal(goal: str, workdir: str) -> str:
    return (
        "You are a delegated worker. All filesystem and process actions must run on "
        f"the configured SSH worker through qyp_terminal. Remote working directory: {workdir}. "
        "Do not claim completion without real command output. Do not schedule more "
        "delegation jobs. Return a concise result with changed paths and verification.\n\n"
        f"TASK:\n{goal}"
    )


def build_execution_invocation(
    *,
    goal: str,
    workdir: str,
    timeout: int,
    toolsets: list[str],
    skills: list[str],
    hermes_home: Path | str | None = None,
    max_turns: int = 120,
) -> tuple[list[str], dict[str, str]]:
    home = Path(hermes_home or os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    allowed_extras = [name for name in toolsets if name not in {"terminal", "file", "code_execution", "delegation", "qyp_delegate"}]
    child_toolsets = ["qyp_worker", *allowed_extras]
    command = [
        sys.executable,
        "-m", "hermes_cli.main",
        "chat", "-Q",
        "--source", "qyp-delegate",
        "--pass-session-id",
        "--max-turns", str(max_turns),
        "--toolsets", ",".join(child_toolsets),
    ]
    if skills:
        command.extend(["--skills", ",".join(skills)])
    command.extend(["-q", goal])
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    env["QYP_DELEGATE_CHILD"] = "1"
    env["QYP_DELEGATE_WORKDIR"] = workdir
    env["QYP_DELEGATE_TIMEOUT"] = str(timeout)
    env.pop("TERMINAL_ENV", None)
    env.pop("TERMINAL_SSH_HOST", None)
    env.pop("TERMINAL_SSH_USER", None)
    env.pop("TERMINAL_CWD", None)
    return command, env


def build_remote_invocation(
    *,
    goal: str,
    workdir: str,
    timeout: int,
    toolsets: list[str],
    skills: list[str],
    max_turns: int = 120,
) -> tuple[list[str], None]:
    remote_parts = [
        _remote_cd(workdir),
        "&&",
        f"env HERMES_HOME={shlex.quote(_settings()['remote_hermes_home'])}",
        shlex.quote(_settings()["remote_hermes"]),
        "chat", "-Q",
        "--source", "qyp-delegate",
        "--pass-session-id",
        "--max-turns", str(max_turns),
    ]
    if toolsets:
        remote_parts.extend(["--toolsets", shlex.quote(",".join(toolsets))])
    if skills:
        remote_parts.extend(["--skills", shlex.quote(",".join(skills))])
    remote_parts.extend(["-q", shlex.quote(goal)])
    return _ssh_prefix() + [" ".join(remote_parts)], None


def handle_qyp_terminal(args: dict[str, Any]) -> str:
    try:
        command_text = str(args.get("command") or "").strip()
        if not command_text:
            raise ValueError("command is required")
        workdir = validate_workdir(args.get("workdir") or os.environ.get("QYP_DELEGATE_WORKDIR"))
        timeout = _clamp_int(
            args.get("timeout") or os.environ.get("QYP_DELEGATE_TIMEOUT"), 180, 1, 3600
        )
        remote = _remote_cd(workdir) + " && bash -lc " + shlex.quote(command_text)
        started = time.monotonic()
        result = subprocess.run(
            _ssh_prefix() + [remote],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return _json({
            "success": result.returncode == 0,
            "host": _settings()["host"],
            "workdir": workdir,
            "exit_code": result.returncode,
            "output": result.stdout[-MAX_OUTPUT:],
            "error": result.stderr[-MAX_OUTPUT:],
            "duration_seconds": round(time.monotonic() - started, 3),
        })
    except subprocess.TimeoutExpired as exc:
        return _json({
            "success": False,
            "error_code": "timeout",
            "error": f"QYP command exceeded {exc.timeout}s; outcome may be unknown",
            "retryable": False,
        })
    except (OSError, ValueError) as exc:
        return _json({"success": False, "error_code": "invalid_request", "error": str(exc)})


def _default_jobs_root() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "qyp-delegate" / "jobs"


def _reject_symlinks(path: Path) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Job state cannot traverse a symlink")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _reject_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    _reject_symlinks(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _run_invocation(command: list[str], env: dict[str, str] | None, timeout: int, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "status": "completed" if result.returncode == 0 else "failed",
            "mode": mode,
            "host": _settings()["host"],
            "exit_code": result.returncode,
            "final_response": result.stdout[-MAX_OUTPUT:],
            "stderr": result.stderr[-MAX_OUTPUT:],
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "status": "timeout",
            "mode": mode,
            "host": _settings()["host"],
            "error_code": "timeout_unknown",
            "error": f"delegated task exceeded {exc.timeout}s; verify remote side effects before retry",
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except OSError as exc:
        return {
            "success": False,
            "status": "failed",
            "mode": mode,
            "host": _settings()["host"],
            "error_code": "spawn_failed",
            "error": str(exc),
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def _job_paths(root: Path, job_id: str) -> tuple[Path, Path]:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id or ""):
        raise ValueError("invalid job_id")
    job_dir = root / job_id
    _reject_symlinks(job_dir)
    return job_dir / "spec.json", job_dir / "result.json"


def _background_worker(spec_path: Path) -> int:
    spec = _read_json(spec_path)
    result = _run_invocation(
        list(spec["command"]),
        (os.environ | dict(spec["env"])) if spec.get("env") else None,
        int(spec["timeout"]),
        str(spec["mode"]),
    )
    result["job_id"] = spec["job_id"]
    _write_json_atomic(spec_path.parent / "result.json", result)
    return 0 if result.get("success") else 1


def _status(job_id: str, root: Path) -> dict[str, Any]:
    spec_path, result_path = _job_paths(root, job_id)
    if result_path.exists():
        return _read_json(result_path)
    if not spec_path.exists():
        return {"success": False, "error_code": "not_found", "error": "job not found", "job_id": job_id}
    spec = _read_json(spec_path)
    pid = int(spec.get("pid") or 0)
    if pid and _pid_alive(pid):
        return {"success": True, "status": "running", "job_id": job_id, "mode": spec.get("mode"), "pid": pid}
    return {
        "success": False,
        "status": "failed",
        "error_code": "worker_crashed",
        "error": "background worker exited without a result artifact",
        "job_id": job_id,
    }


def _cancel(job_id: str, root: Path) -> dict[str, Any]:
    spec_path, result_path = _job_paths(root, job_id)
    if result_path.exists():
        return _read_json(result_path)
    if not spec_path.exists():
        return {"success": False, "error_code": "not_found", "error": "job not found", "job_id": job_id}
    spec = _read_json(spec_path)
    pid = int(spec.get("pid") or 0)
    if pid and _pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    result = {"success": True, "status": "cancelled", "job_id": job_id, "mode": spec.get("mode")}
    _write_json_atomic(result_path, result)
    return result


def handle_delegate_qyp(args: dict[str, Any], *, jobs_root: Path | str | None = None) -> str:
    root = Path(jobs_root) if jobs_root is not None else _default_jobs_root()
    try:
        _settings()
        action = str(args.get("action") or "submit").strip().lower()
        if action == "status":
            return _json(_status(str(args.get("job_id") or ""), root))
        if action == "cancel":
            return _json(_cancel(str(args.get("job_id") or ""), root))
        if action != "submit":
            raise ValueError("action must be submit, status, or cancel")

        goal = str(args.get("goal") or "").strip()
        if not goal:
            raise ValueError("goal is required")
        workdir = validate_workdir(args.get("workdir"))
        timeout = _clamp_int(args.get("timeout"), 900, 10, 3600)
        max_turns = _clamp_int(args.get("max_turns"), 120, 1, 500)
        mode = resolve_mode(str(args.get("mode") or "auto"))
        toolsets = _safe_names(args.get("toolsets"), field="toolsets")
        skills = _safe_names(args.get("skills"), field="skills")

        if mode == "execution":
            child_goal = _augment_execution_goal(goal, workdir)
            command, env = build_execution_invocation(
                goal=child_goal,
                workdir=workdir,
                timeout=timeout,
                toolsets=toolsets,
                skills=skills,
                max_turns=max_turns,
            )
        else:
            command, env = build_remote_invocation(
                goal=goal,
                workdir=workdir,
                timeout=timeout,
                toolsets=toolsets,
                skills=skills,
                max_turns=max_turns,
            )

        if bool(args.get("wait", True)):
            result = _run_invocation(command, env, timeout, mode)
            result["workdir"] = workdir
            return _json(result)

        job_id = uuid.uuid4().hex
        spec_path, _ = _job_paths(root, job_id)
        spec = {
            "job_id": job_id,
            "mode": mode,
            "workdir": workdir,
            "timeout": timeout,
            "command": command,
            "env": {k: v for k, v in (env or {}).items() if k in {"HERMES_HOME", "QYP_DELEGATE_CHILD", "QYP_DELEGATE_WORKDIR", "QYP_DELEGATE_TIMEOUT"}},
            "created_at": time.time(),
        }
        _write_json_atomic(spec_path, spec)
        worker = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--run-job", str(spec_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        spec["pid"] = worker.pid
        _write_json_atomic(spec_path, spec)
        return _json({
            "success": True,
            "status": "running",
            "job_id": job_id,
            "pid": worker.pid,
            "mode": mode,
            "host": _settings()["host"],
            "workdir": workdir,
        })
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _json({"success": False, "error_code": "invalid_request", "error": str(exc)})


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-job", type=Path)
    ns = parser.parse_args()
    if ns.run_job:
        return _background_worker(ns.run_job)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
