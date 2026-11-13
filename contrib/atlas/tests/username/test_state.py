"""Pure admission-state regression tests; no gateway/home initialization."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

SOURCE = Path(os.environ["ADMISSION_SOURCE_FILE"])
spec = importlib.util.spec_from_file_location("candidate_admission_regression", SOURCE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class Staff:
    def __init__(self):
        self.allowed = True
        self.hold = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def verify(self, uid, username):
        proof = m.StaffProof(uid, "fixture-person", True, True, False, username) if self.allowed else None
        if self.hold:
            self.hold = False
            self.entered.set()
            await self.release.wait()
        return proof


class Bot:
    def __init__(self):
        self.status = "administrator"
        self.hold = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def get_chat_member(self, chat, uid):
        member = SimpleNamespace(status=self.status, user=SimpleNamespace(id=m.TASHA_ID, is_bot=True))
        if self.hold:
            self.hold = False
            self.entered.set()
            await self.release.wait()
        return member


class AdmissionRegressions(unittest.IsolatedAsyncioTestCase):
    def issued(self, kind="group", thread="7"):
        staff, bot = Staff(), Bot()
        gate = m.AdmissionGate(staff)
        binding = m.Binding("41", "41" if kind == "dm" else "-10011", kind, thread,
                            "tg-41" if kind == "dm" else "tg-group-n10011-t" + str(thread),
                            "fixture_user" if kind == "dm" else None)
        gate._issued[id(binding)] = (binding, bot, 0)
        return gate, binding, bot, staff

    async def test_late_group_success_cannot_restore_revoked_binding(self):
        gate, binding, bot, _ = self.issued()
        bot.hold = True
        stale = asyncio.create_task(gate.recheck(binding, bot))
        await bot.entered.wait()
        bot.status = "member"
        with self.assertRaises(PermissionError):
            await gate.recheck(binding, bot)
        self.assertFalse(gate.valid(binding))
        bot.status = "administrator"
        bot.release.set()
        result = await asyncio.gather(stale, return_exceptions=True)
        self.assertIsInstance(result[0], PermissionError)
        self.assertFalse(gate.valid(binding))

    async def test_late_staff_success_cannot_restore_revoked_binding(self):
        gate, binding, bot, staff = self.issued("dm", None)
        staff.hold = True
        stale = asyncio.create_task(gate.recheck(binding, bot))
        await staff.entered.wait()
        staff.allowed = False
        with self.assertRaises(PermissionError):
            await gate.recheck(binding, bot)
        self.assertFalse(gate.valid(binding))
        staff.allowed = True
        staff.release.set()
        result = await asyncio.gather(stale, return_exceptions=True)
        self.assertIsInstance(result[0], PermissionError)
        self.assertFalse(gate.valid(binding))

    async def test_general_topic_accepts_native_omitted_thread(self):
        gate, binding, bot, _ = self.issued(thread="1")
        with m.binding_scope(binding):
            await gate.authorize_request("sendMessage", {"chat_id": "-10011", "text": "fixture"})
        self.assertTrue(gate.valid(binding))

    async def test_general_topic_rejects_other_explicit_topic(self):
        gate, binding, _, _ = self.issued(thread="1")
        with m.binding_scope(binding), self.assertRaises(PermissionError):
            await gate.authorize_request("sendMessage", {"chat_id": "-10011", "message_thread_id": 7})

    async def test_specific_topic_rejects_omitted_thread(self):
        gate, binding, _, _ = self.issued(thread="7")
        with m.binding_scope(binding), self.assertRaises(PermissionError):
            await gate.authorize_request("sendMessage", {"chat_id": "-10011"})

    async def test_general_topic_rejects_other_chat(self):
        gate, binding, _, _ = self.issued(thread="1")
        with m.binding_scope(binding), self.assertRaises(PermissionError):
            await gate.authorize_request("sendMessage", {"chat_id": "-10012"})

    async def test_original_valid_binding_rechecks_normally(self):
        gate, binding, bot, _ = self.issued()
        self.assertIs(await gate.recheck(binding, bot), binding)
        self.assertTrue(gate.valid(binding))


if __name__ == "__main__":
    unittest.main(verbosity=2)
