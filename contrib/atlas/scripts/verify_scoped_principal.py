#!/usr/bin/env python3
"""Portable full-native scoped-Principal causal regression; no live services.

Use a PM-built verification interpreter and an owned fresh installed source root.
Only local scripted HTTP model/Telegram transports are used. No top-level guard
alias or plugin sys.path repair is permitted. Root and private policy consent is
validated before native initialization. --guard-source-dir is a causal-control
source override, never a runtime installation operation.
"""

from pathlib import Path
import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", required=True, type=Path)
parser.add_argument("--work", required=True, type=Path)
parser.add_argument("--guard-source-dir", type=Path)
args = parser.parse_args()
A = args.root.resolve(strict=True)
R = args.work.absolute()
if R.exists() or R.is_symlink() or not R.parent.is_dir():
    parser.error("fresh_owned_fixture_required")
policy = (A / "control/SOUL.md").read_bytes()
consent = json.loads((A / "control/instruction-policy-approval.json").read_text())
pin = hashlib.sha256(policy).hexdigest()
if (
    consent.get("approved") is not True
    or consent.get("scope") != "native-home-initialization"
    or not consent.get("provenance")
    or consent.get("sha256") != pin
    or str(A / "home") not in consent.get("homes", [])
):
    raise PermissionError("approved_fixture_policy_required")
R.mkdir(mode=0o700)
H = R / "home"
P = H / "profiles/tg-41"
for path in (H, P, R / "control", R / "sandbox", R / "os-home", R / "scratch"):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
for home in (H, P):
    (home / "SOUL.md").write_bytes(policy)
(R / "control/instruction-policy-approval.json").write_text(
    json.dumps(
        {
            "approved": True,
            "scope": "native-home-initialization",
            "sha256": pin,
            "homes": [str(H), str(P)],
            "provenance": "Explicit project policy consent inherited for owned native regression only",
        }
    )
)
(R / "control/operator.json").write_text(json.dumps({"owner_telegram_id": "123456789"}))
plugins = (
    args.guard_source_dir.resolve(strict=True)
    if args.guard_source_dir
    else A / "home/plugins/qyp_guard"
)
shutil.copytree(
    plugins, H / "plugins/qyp_guard", ignore=shutil.ignore_patterns("__pycache__")
)
(P / "plugins").symlink_to(H / "plugins", target_is_directory=True)
# A closed environment prevents inherited gateway identity/config from entering.
scratch = str(R / "scratch")
os.environ.clear()
os.environ.update(
    PATH="/usr/bin:/bin",
    HOME=str(R / "os-home"),
    HERMES_HOME=str(H),
    TMPDIR=scratch,
    PYTHONDONTWRITEBYTECODE="1",
    HERMES_TELEMETRY_ENABLED="0",
)
sys.path.insert(0, str(A / "runtime"))
logging.basicConfig(
    level=logging.WARNING, handlers=[logging.FileHandler(R / "native.log")]
)
from gateway.atlas_admission import (
    AdmissionGate,
    StaffProof,
    install_gate,
    current_binding,
    GuardedRequest,
)
from gateway.config import Platform, PlatformConfig, load_gateway_config
from gateway.run import GatewayRunner
from gateway.run_runtime import initialize_gateway_runtime
from gateway.runtime_ownership import process_ownership
from hermes_cli.plugins import get_plugin_manager
from telegram import Update
from telegram.ext import Application, ExtBot, TypeHandler
from plugins.platforms.telegram.adapter import TelegramAdapter
from plugins.platforms.telegram.update_admission import TelegramApplication
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall
from telegram.request import BaseRequest
import hermes_yaml as yaml


class Staff:
    allowed = True

    async def verify(self, uid, username):
        return (
            StaffProof(uid, "fixture", True, True, False, username)
            if self.allowed and username == "fixture_41"
            else None
        )


class Wire(BaseRequest):
    def __init__(self):
        self.calls = []

    @property
    def read_timeout(self):
        return 2

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kw):
        ep = url.rsplit("/", 1)[-1]
        p = request_data.parameters if request_data else {}
        self.calls.append((ep, p))
        if ep == "getMe":
            d = {
                "id": 123456,
                "is_bot": True,
                "first_name": "fixture",
                "username": "fixture_atlas_bot",
            }
        elif ep == "sendMessage":
            d = {
                "message_id": 99,
                "date": 1,
                "chat": {"id": 41, "type": "private"},
                "text": p.get("text", ""),
            }
        else:
            d = True
        return 200, json.dumps({"ok": True, "result": d}).encode()


async def wait(pred):
    end = time.monotonic() + 35
    while time.monotonic() < end:
        if pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("bounded native turn wait")


async def main():
    llm = FakeLLMServer(
        default_text="NATIVE_SCOPE_MODEL_OK", aux=lambda req: Text("aux")
    )
    llm.start()
    settings = {
        "root": str(R / "sandbox"),
        "sandbox_backend": "disabled",
        "media_policy_integrated": True,
    }
    cfg = {
        "model": {
            "default": "fake-model",
            "provider": "custom",
            "base_url": llm.base_url,
            "api_key": "fixture-key",
            "api_mode": "chat_completions",
            "context_length": 128000,
        },
        "agent": {"max_turns": 2, "api_max_retries": 0},
        "memory": {"provider": "builtin"},
        "compression": {"enabled": False},
        "sessions": {"auto_prune": False},
        "display": {"tool_progress": "off", "busy_input_mode": "queue"},
        "plugins": {
            "enabled": ["qyp_guard"],
            "entries": {"qyp_guard": {"enabled": True, "settings": settings}},
        },
        "gateway": {
            "multiplex_profiles": True,
            "busy_input_mode": "queue",
            "profile_routes": [
                {
                    "name": "fixture",
                    "platform": "telegram",
                    "chat_id": "41",
                    "user_id": "41",
                    "profile": "tg-41",
                }
            ],
        },
    }
    cfg["agent"]["allowed_tools"] = ["qyp_role"]
    cfg["platform_toolsets"] = {"telegram": ["qyp_guard"]}
    cfg["plugins"]["isolation"] = "in_process"
    for home in (H, P):
        (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    staff = Staff()
    gate = AdmissionGate(staff)
    install_gate(gate)
    manager = get_plugin_manager()
    manager.discover_and_load()
    assert any(
        getattr(cb, "__name__", "") == "guard_llm"
        for cb in manager._hooks.get("pre_llm_call", [])
    ), "native guard hook not loaded"
    # No sys.path plugin directory; let the real loader create the scoped modules.
    assert not any(n == "qyp_guard" or n.startswith("qyp_guard.") for n in sys.modules)
    assert all(Path(p).resolve() != (H / "plugins").resolve() for p in sys.path if p)
    wire = Wire()
    bot = ExtBot("123456:fixture-not-a-secret", request=GuardedRequest(wire, gate))
    adapter = TelegramAdapter(
        PlatformConfig(
            enabled=True,
            typing_indicator=False,
            extra={"atlas_admission": True, "dm_policy": "open", "allow_from": ["*"]},
        )
    )
    adapter._bot = bot
    adapter._update_receipt_dir = H / "receipts"
    app = (
        Application.builder()
        .bot(bot)
        .application_class(TelegramApplication, {"adapter": adapter})
        .build()
    )
    await app.initialize()

    async def inbound(u, c):
        await adapter._handle_text_message(u, c)

    app.add_handler(TypeHandler(Update, inbound))
    runner = GatewayRunner(load_gateway_config())
    runner.adapters = {Platform.TELEGRAM: adapter}
    adapter.gateway_runner = runner
    runner._gateway_loop = asyncio.get_running_loop()
    runner._running = True
    runner.config._runtime_profile_homes = (("default", H), ("tg-41", P))
    process_ownership.reserve([H, P])
    await initialize_gateway_runtime(runner)
    runner._note_served_profiles([("default", H), ("tg-41", P)])
    runner._wire_adapter_handlers(adapter)
    trace = []
    native_key = [None]

    def observe(frame, event, arg):
        if event == "call" and frame.f_code.co_name in ("guard_llm", "guard_tool"):
            from hermes_constants import get_hermes_home
            from hermes_cli.profiles import get_active_profile_name
            from gateway.session_context import bound_session_key

            native_key[0] = bound_session_key()
            b = current_binding()
            trace.append(
                {
                    "function": frame.f_code.co_name,
                    "event": "call",
                    "binding_valid": gate.valid(b),
                    "active_home_is_private": get_hermes_home().resolve()
                    == P.resolve(),
                    "active_profile_exact": b is not None
                    and get_active_profile_name() == b.profile,
                    "ctx_profile_exact": b is not None
                    and frame.f_locals["self"].ctx.profile_name == b.profile,
                }
            )
        if event == "exception" and frame.f_code.co_name in (
            "principal",
            "authorized_principal",
        ):
            exc = arg[1]
            # Fixed classes + source location only; no exception text or context.
            trace.append(
                {
                    "function": frame.f_code.co_name,
                    "exception_type": type(exc).__name__,
                    "line": frame.f_lineno,
                    "module": frame.f_globals.get("__name__"),
                }
            )
        return observe

    import threading

    result = {"scope": "native-home-scoped-principal", "completed": False}
    threading.settrace_all_threads(observe)
    sys.settrace(observe)
    try:
        llm.push(ToolCall("qyp_role", {}), Text("NATIVE_SCOPE_MODEL_OK"))
        u = Update.de_json(
            {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "date": int(time.time()),
                    "from": {
                        "id": 41,
                        "is_bot": False,
                        "first_name": "fixture",
                        "username": "fixture_41",
                    },
                    "chat": {"id": 41, "type": "private"},
                    "text": "Reply NATIVE_SCOPE_MODEL_OK",
                },
            },
            bot,
        )
        await app.process_update(u)
        await wait(lambda: any(ep == "sendMessage" for ep, p in wire.calls))
        await wait(lambda: not adapter._background_tasks)
        result = {
            "scope": "native-home-scoped-principal",
            "model_requests": len(llm.requests),
            "main_model_requests": len(llm.main_requests()),
            "reply_texts": [
                p.get("text") for ep, p in wire.calls if ep == "sendMessage"
            ],
            "trace": trace,
            "qyp_global_alias_present": "qyp_guard" in sys.modules,
            "guard_modules_home_scoped": all(
                n.startswith("hermes_plugins.")
                for n in sys.modules
                if "qyp_guard" in n and n.endswith(".broker")
            ),
            "native_full_producer": True,
            "manual_binding_or_ctx_profile": False,
        }
        (R / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        calls = [row for row in trace if row.get("event") == "call"]
        assert calls and all(
            row["binding_valid"]
            and row["active_home_is_private"]
            and row["active_profile_exact"]
            and row["ctx_profile_exact"]
            for row in calls
        )
        assert result["guard_modules_home_scoped"]
        assert len(llm.main_requests()) > 0, (
            "causal RED: installed full native hook must reach model"
        )
        assert any(
            p.get("text", "").replace("\\", "") == "NATIVE_SCOPE_MODEL_OK"
            for ep, p in wire.calls
            if ep == "sendMessage"
        ), "exact native SDK reply absent"
        assert any(row["function"] == "guard_tool" for row in calls), (
            "actual native tool policy hook missing"
        )
        tool_payloads = [
            m
            for request in llm.main_requests()
            for m in request.get("messages", [])
            if m.get("role") == "tool"
        ]
        assert any(
            '"ok": true' in str(m.get("content", ""))
            and '"role": "member"' in str(m.get("content", ""))
            for m in tool_payloads
        ), "native role result not consumed by model"
        from gateway.run import _profile_runtime_scope
        from gateway.platforms.event import MessageType

        event = adapter._build_message_event(u.message, MessageType.TEXT, update_id=1)
        with _profile_runtime_scope(P):
            pm = get_plugin_manager()
            svc = next(
                cb.__self__
                for cb in pm._hooks["pre_llm_call"]
                if getattr(cb, "__name__", "") == "guard_llm"
            )
            mod = sys.modules[svc.__class__.__module__]
            who = mod.principal_for_binding(
                gate, event.source._atlas_binding, native_key[0]
            )
            (svc.broker.workspace(who) / "scoped.txt").write_text(
                "FIXTURE_SCOPED_EXPORT"
            )
            exported = svc.broker.export(who, "scoped.txt")["path"]
            carrier = dict(vars(event.source))
            resolved = pm.invoke_hook(
                "resolve_media_delivery_path",
                path=exported,
                session_key=native_key[0],
                bound_source=carrier,
                policy="qyp_guard",
            )
            assert any(row.get("path") == exported for row in resolved), (
                "scoped native media resolution failed"
            )
            foreign = dict(carrier, profile="tg-42")
            assert all(
                row.get("path") is None
                for row in pm.invoke_hook(
                    "resolve_media_delivery_path",
                    path=exported,
                    session_key=native_key[0],
                    bound_source=foreign,
                    policy="qyp_guard",
                )
            )
        result["scoped_media_own_pass_foreign_denied"] = True
        with _profile_runtime_scope(P):
            # Exercise actual dispatch attachment staging through the loaded hook.
            event.media_urls = ["fixture://selected/report.txt"]
            event.media_types = ["text/plain"]
            event.text = "Read fixture://selected/report.txt"
            event.append_inbound_attachment_snapshot(
                "report.txt", b"OWNED_NATIVE_INPUT"
            )
            decisions = pm.invoke_hook(
                "pre_gateway_dispatch", event=event, session_key=native_key[0]
            )
            assert not any(
                isinstance(row, dict) and row.get("action") == "skip"
                for row in decisions
            )
            assert event.media_urls == [] and "/inputs/attachment-" in event.text
            result["native_inbound_attachment_staged"] = True
            from types import SimpleNamespace

            try:
                mod.principal_for_binding(
                    gate,
                    SimpleNamespace(
                        **{
                            name: getattr(event.source._atlas_binding, name)
                            for name in (
                                "user_id",
                                "profile",
                                "chat_id",
                                "thread_id",
                                "chat_type",
                            )
                        }
                    ),
                    native_key[0],
                )
            except (PermissionError, TypeError):
                result["unissued_binding_denied"] = True
            else:
                raise AssertionError("unissued binding must deny")
        before = len(llm.requests)
        staff.allowed = False
        denied = Update.de_json(
            {
                "update_id": 2,
                "message": {
                    "message_id": 2,
                    "date": int(time.time()),
                    "from": {
                        "id": 41,
                        "is_bot": False,
                        "first_name": "fixture",
                        "username": "fixture_41",
                    },
                    "chat": {"id": 41, "type": "private"},
                    "text": "MUST_NOT_REACH_MODEL",
                },
            },
            bot,
        )
        await app.process_update(denied)
        await asyncio.sleep(0.1)
        assert len(llm.requests) == before
        result["negative_staff_revocation_zero_requests"] = True
        result["actual_tool_result_consumed"] = True
        result["completed"] = True
        (R / "result.json").write_text(json.dumps(result, indent=2))
    finally:
        sys.settrace(None)
        threading.settrace_all_threads(None)
        runner._running = False
        for authority in runner.session_authorities:
            for live in authority.sessions.values():
                if live.task and not live.task.done():
                    live.task.cancel()
        runner._shutdown_executor(drain_timeout=5)
        runner.session_store.close_all_db_handles()
        runner.close_all_session_db_handles()
        for _, path in runner.config._runtime_profile_homes:
            process_ownership.release(path)
        await app.shutdown()
        if adapter._update_receipt_flush:
            await adapter._update_receipt_flush
        from tools.mcp_tool_lifecycle import shutdown_mcp_servers

        await asyncio.to_thread(shutdown_mcp_servers)
        llm.stop()
        llm._thread.join(timeout=3)
        assert not llm._thread.is_alive()
        result["teardown"] = {
            "model_thread_stopped": True,
            "bot_sdk_closed": True,
            "owned_profile_reservations_released": True,
        }
        (R / "result.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
