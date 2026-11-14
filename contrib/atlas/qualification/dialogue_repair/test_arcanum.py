"""Offline causal tests of the actual sidecar; only native runner is a fixture."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[2]/'payload/services/atlas-read/sidecar.py'
spec = importlib.util.spec_from_file_location('sidecar_under_test', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
# Synthetic operator binding in memory only; published ACL stays deny-default.
assert m.ARC_ROOTS == () and m.GITHUB_REPOS == frozenset()
m.ARC_ROOTS = ('neuroexpert',)
m.GITHUB_REPOS = frozenset({'NousResearch/hermes-agent', 'oshapovalovmail-dot/hermes-agent'})
HOSTS = ('a.yandex-team.ru', 'arcanum.yandex-team.ru')
IDS = ('17068009', '16592861', '17054274', '16939956', '17054612')
PATCH = 'diff --git a/neuroexpert/test.py b/neuroexpert/test.py\n--- a/neuroexpert/test.py\n+++ b/neuroexpert/test.py\n@@ -1 +1 @@\n-old\n+new\n'
INVALID = (
 'http://a.yandex-team.ru/review/1', 'https://a.yandex-team.ru.evil/review/1',
 'https://arcanum.yandex-team.ru.evil/review/1', 'https://evil/review/1',
 'https://user@a.yandex-team.ru/review/1', 'https://a.yandex-team.ru:443/review/1',
 'https://arcanum.yandex-team.ru:443/review/1', 'https://a.yandex-team.ru./review/1',
 'https://A.yandex-team.ru/review/1', 'https://a.yandex-team.ru/review/1?',
 'https://a.yandex-team.ru/review/1#', 'https://arcanum.yandex-team.ru/review/1?x=1',
 'https://arcanum.yandex-team.ru/review/1#x', 'https://a.yandex-team.ru/review/0',
 'https://a.yandex-team.ru/review/01', 'https://a.yandex-team.ru/review/+1',
 'https://a.yandex-team.ru/review/１', 'https://a.yandex-team.ru/review/1//',
 'https://a.yandex-team.ru/review/./1', 'https://a.yandex-team.ru/review/2/../1',
 'https://a.yandex-team.ru/review/%31', 'https://a.yandex-team.ru/review/%2e%2e/1',
 'https://a.yandex-team.ru/review/1%2f', 'https://a.yandex-team.ru/review/1\n',
 ' https://a.yandex-team.ru/review/1', 'https://a.yandex-team.ru\\@evil/review/1',
 'https://a.yandex-team.ru/review/100000000000', '', None, 1,
)

class NativeFixture:
    def __init__(self, metadata_url, metadata_id=17068009, patch=PATCH):
        self.metadata = {'id': metadata_id, 'url': metadata_url, 'title': 'fixture'}
        self.patch = patch
        self.calls = []
    def __call__(self, argv, cwd=None):
        self.calls.append((argv, cwd))
        if argv == [m.ARC_CLI, 'pr', 'status', '17068009', '--json'] and cwd == m.ARC_CWD:
            return json.dumps(self.metadata)
        if argv == [m.ARC_CLI, 'pr', 'changes', '17068009'] and cwd == m.ARC_CWD:
            return self.patch
        raise AssertionError(('unexpected native command', argv, cwd))

def service(runner):
    # Avoid constructing any real auth/network client. Tracker is unused here.
    return m.ReadService(runner=runner, tracker_api=object())

class ArcanumTests(unittest.TestCase):
    def test_parse_aliases_five_observed_ids(self):
        for host in HOSTS:
            for prid in IDS + ('1', '99999999999'):
                for slash in ('', '/'):
                    with self.subTest(host=host, prid=prid, slash=slash):
                        self.assertEqual(m.parse_pr(f'https://{host}/review/{prid}{slash}'), ('arc', prid))

    def test_alias_matrix_preserves_requested_source_and_native_argv(self):
        for requested in HOSTS:
            for actual in HOSTS:
                for rs in ('', '/'):
                    for ns in ('', '/'):
                        for view in ('metadata', 'diff'):
                            url = f'https://{requested}/review/17068009{rs}'
                            with self.subTest(url=url, actual=actual, ns=ns, view=view):
                                runner = NativeFixture(f'https://{actual}/review/17068009{ns}')
                                answer = service(runner).pr_read(url, view=view)
                                self.assertTrue(answer['ok'], answer)
                                self.assertEqual(answer['source'], url)
                                self.assertEqual(runner.calls, [([m.ARC_CLI,'pr','status','17068009','--json'],m.ARC_CWD), ([m.ARC_CLI,'pr','changes','17068009'],m.ARC_CWD)])
                                if view == 'metadata':
                                    self.assertEqual(json.loads(answer['text'])['validated_paths'], ['neuroexpert/test.py'])
                                else:
                                    self.assertEqual(answer['text'], PATCH)

    def test_invalid_requests_reject_before_dispatch(self):
        for url in INVALID:
            with self.subTest(url=url):
                with self.assertRaises(m.PolicyError): m.parse_pr(url)
                runner = NativeFixture('https://a.yandex-team.ru/review/17068009')
                answer = service(runner).pr_read(url)
                self.assertEqual(answer['code'], 'invalid_argument')
                self.assertEqual(runner.calls, [])

    def test_invalid_native_metadata_rejects_before_patch(self):
        urls = INVALID + ('https://a.yandex-team.ru/review/17068010', 'https://arcanum.yandex-team.ru/review/17068010', 'https://github.com/NousResearch/hermes-agent/pull/17068009', 'https://a.yandex-team.ru/review/17068009//')
        for url in urls:
            with self.subTest(url=url):
                runner = NativeFixture(url)
                answer = service(runner).pr_read('https://a.yandex-team.ru/review/17068009')
                self.assertEqual(answer['code'], 'pr_metadata_unrecognized', answer)
                self.assertEqual(len(runner.calls), 1)
        for prid in (17068010, '17068009', None):
            with self.subTest(id=prid):
                runner = NativeFixture('https://a.yandex-team.ru/review/17068009', metadata_id=prid)
                self.assertEqual(service(runner).pr_read('https://a.yandex-team.ru/review/17068009')['code'], 'pr_metadata_unrecognized')
                self.assertEqual(len(runner.calls), 1)

    def test_whole_patch_acl_even_after_output_cutoff(self):
        patch = PATCH + ('+safe filler\n' * 200) + 'diff --git a/forbidden/file b/forbidden/file\n--- a/forbidden/file\n+++ b/forbidden/file\n'
        for host in HOSTS:
            for view in ('metadata', 'diff'):
                with self.subTest(host=host, view=view):
                    runner = NativeFixture('https://a.yandex-team.ru/review/17068009', patch=patch)
                    answer = service(runner).pr_read(f'https://{host}/review/17068009', view=view, max_chars=256)
                    self.assertEqual(answer['code'], 'pr_scope_denied')
                    self.assertEqual(answer['text'], '')
                    self.assertEqual(len(runner.calls), 2)

    def test_bounds_and_view_before_dispatch(self):
        for args in ({'max_chars':255}, {'max_chars':48001}, {'max_chars':True}, {'view':'comments'}):
            runner = NativeFixture('https://a.yandex-team.ru/review/17068009')
            self.assertEqual(service(runner).pr_read('https://a.yandex-team.ru/review/17068009', **args)['code'], 'invalid_argument')
            self.assertEqual(runner.calls, [])
        runner = NativeFixture('https://a.yandex-team.ru/review/17068009', patch=PATCH + '+filler\n' * 200)
        answer = service(runner).pr_read('https://a.yandex-team.ru/review/17068009', view='diff', max_chars=256)
        self.assertTrue(answer['ok'])
        self.assertTrue(answer['truncated'])
        self.assertEqual(answer['returned_chars'], 256)

    def test_github_acl_unchanged(self):
        self.assertEqual(m.GITHUB_REPOS, frozenset({'NousResearch/hermes-agent', 'oshapovalovmail-dot/hermes-agent'}))
        for repo in m.GITHUB_REPOS:
            self.assertEqual(m.parse_pr(f'https://github.com/{repo}/pull/1'), ('github', '1'))
        runner = NativeFixture('unused')
        self.assertEqual(service(runner).pr_read('https://github.com/evil/repo/pull/1')['code'], 'pr_acl_denied')
        self.assertEqual(runner.calls, [])

if __name__ == '__main__':
    print('SOURCE=' + str(SOURCE), flush=True)
    unittest.main(verbosity=2)
