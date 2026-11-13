"""Native Telegram SDK serializer checks without Hermes initialization."""
import json
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_state as state
m = state.m
from telegram.ext import ExtBot
from telegram.request import BaseRequest
from telegram.error import Forbidden


class Wire(BaseRequest):
    def __init__(self):
        self.calls = []
        self.status = "administrator"

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        data = request_data.parameters if request_data is not None else {}
        self.calls.append((endpoint, dict(data)))
        if endpoint == "getMe":
            result = {"id": 123456, "is_bot": True, "first_name": "Fixture", "username": "fixture_bot"}
        elif endpoint == "getChatMember":
            result = {"status": self.status,
                      "user": {"id": m.TASHA_ID, "is_bot": True, "first_name": "FixtureTasha"}}
            if self.status == "administrator":
                result.update({key: False for key in (
                    "can_be_edited", "is_anonymous", "can_manage_chat", "can_delete_messages",
                    "can_manage_video_chats", "can_restrict_members", "can_promote_members",
                    "can_change_info", "can_invite_users", "can_post_stories",
                    "can_edit_stories", "can_delete_stories")})
        elif endpoint == "sendMessage":
            result = {"message_id": 1, "date": 1,
                      "chat": {"id": int(data["chat_id"]), "type": "supergroup", "is_forum": True},
                      "text": data["text"]}
        else:
            raise AssertionError("unexpected SDK endpoint")
        return 200, json.dumps({"ok": True, "result": result}).encode()


class SDKChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        helper = state.AdmissionRegressions()
        self.gate, self.binding, _, _ = helper.issued(thread="1")
        self.wire = Wire()
        self.bot = ExtBot("123456:synthetic-test-not-a-secret",
                          request=m.GuardedRequest(self.wire, self.gate))
        await self.bot.initialize()
        self.gate._issued[id(self.binding)] = (self.binding, self.bot, 0)

    async def asyncTearDown(self):
        await self.bot.shutdown()

    async def test_general_topic_native_serializer_allows_omitted_topic(self):
        with m.binding_scope(self.binding):
            result = await self.bot.send_message(-10011, "fixture General")
        self.assertEqual(result.message_id, 1)
        sent = [data for endpoint, data in self.wire.calls if endpoint == "sendMessage"]
        self.assertEqual(len(sent), 1)
        self.assertNotIn("message_thread_id", sent[0])

    async def test_native_serializer_blocks_different_topic(self):
        with m.binding_scope(self.binding), self.assertRaises(Forbidden):
            await self.bot.send_message(-10011, "not delivered", message_thread_id=7)
        self.assertFalse(any(endpoint == "sendMessage" for endpoint, _ in self.wire.calls))

    async def test_native_serializer_blocks_demotion(self):
        self.wire.status = "member"
        with m.binding_scope(self.binding), self.assertRaises(Forbidden):
            await self.bot.send_message(-10011, "not delivered")
        self.assertFalse(self.gate.valid(self.binding))
        self.assertFalse(any(endpoint == "sendMessage" for endpoint, _ in self.wire.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
