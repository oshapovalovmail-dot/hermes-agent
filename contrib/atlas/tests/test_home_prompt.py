"""Execute exact native method AST without native/home initialization.

HOME_PROMPT_SOURCE selects the physically patched runtime; external transports,
secret/config loaders and first-contact intro are bounded dependency fixtures.
No real Telegram input, delivery, model, auth or profile initialization occurs.
"""
import ast
import asyncio
from contextlib import suppress
from enum import Enum
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class Platform(Enum):
    TELEGRAM = 'telegram'
    SLACK = 'slack'
    LOCAL = 'local'
    WEBHOOK = 'webhook'


SOURCE = Path(os.environ.get('HOME_PROMPT_SOURCE', str(Path(os.environ.get('ATLAS_TEST_CORE', 'runtime')) / 'gateway/run_turn_prepare.py')))


def method():
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_hmwa_first_contact_notes')
    namespace = {'Platform': Platform, 'suppress': suppress, 'os': os, 't': lambda key, **kw: (key, kw), 'logger': SimpleNamespace(debug=lambda *a, **kw: None)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace[node.name]


class HomePrompt(unittest.IsolatedAsyncioTestCase):
    async def call(self, flag='absent', *, history=None, internal=False, platform=Platform.TELEGRAM, home='', first=False, scoped_home=False):
        notices, notes = [], []
        raw = {} if flag == 'absent' else {'gateway': {'home_channel_prompt': flag}}
        run = ModuleType('gateway.run')
        run._load_gateway_config = lambda: raw
        run._gateway_config_home = lambda: Path('/fixture/scoped-profile')
        run._home_target_env_var = lambda p: 'FIXTURE_HOME_TARGET'
        secret = ModuleType('agent.secret_scope')
        secret.UnscopedSecretError = type('UnscopedSecretError', (Exception,), {})
        secret.get_secret = lambda key: home
        onboarding = ModuleType('agent.onboarding')
        onboarding.first_contact_turn_note = lambda *a, **kw: 'INTRO'
        config = ModuleType('gateway.config')
        config.load_gateway_config = lambda: SimpleNamespace(get_home_channel=lambda p: scoped_home)
        async def deliver(source, text):
            notices.append(text)
        async def has_sessions():
            return not first
        owner = SimpleNamespace(async_session_store=SimpleNamespace(has_any_sessions=has_sessions), config=SimpleNamespace(get_home_channel=lambda p: False), _deliver_platform_notice=deliver)
        source = SimpleNamespace(platform=platform, chat_type='dm', profile='tg-fixture')
        with patch.dict(sys.modules, {'gateway.run': run, 'agent.secret_scope': secret, 'agent.onboarding': onboarding, 'gateway.config': config}):
            await method()(owner, source, history or [], notes, internal=internal)
        return notices, notes

    async def test_explicit_false_two_fresh_threads_no_home_preserves_intro(self):
        for first in (True, False):
            notices, notes = await self.call(False, first=first)
            self.assertEqual(notices, [])
            self.assertEqual(notes, ['INTRO'] if first else [])

    async def test_default_true_and_non_boolean_values_preserve_legacy_prompt(self):
        for flag in ('absent', True, 'false', 0, None):
            with self.subTest(flag=flag):
                notices, _ = await self.call(flag)
                self.assertEqual(len(notices), 1)
                self.assertEqual(notices[0][0], 'gateway.notify.no_home_channel')

    async def test_existing_secret_or_scoped_config_home_no_prompt(self):
        self.assertEqual((await self.call(home='set'))[0], [])
        self.assertEqual((await self.call(scoped_home=True))[0], [])

    async def test_history_internal_local_webhook_unchanged(self):
        for kw in ({'history': ['prior']}, {'internal': True}, {'platform': Platform.LOCAL}, {'platform': Platform.WEBHOOK}):
            self.assertEqual(await self.call(**kw), ([], []))

    async def test_slack_command_unchanged(self):
        notices, _ = await self.call(platform=Platform.SLACK)
        self.assertEqual(notices[0][1]['sethome_cmd'], '/hermes sethome')


if __name__ == '__main__':
    unittest.main(verbosity=2)
