"""Contracts against synthetic HTTP responses; fixtures are not live search evidence."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[2] / "integrations/local-plugins/web-yandex"


class SearchContract(unittest.TestCase):
    def setUp(self):
        path = ROOT / "provider.py"
        self.assertTrue(path.is_file(), "Yandex search provider is not implemented")
        spec = importlib.util.spec_from_file_location("yandex_provider_test", path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.response = {
            "message": {"content": "Generated answer [7]", "role": "assistant"},
            "is_answer_rejected": False,
            "links": ["https://example.org/a", "https://example.org/b"],
            "titles": ["Page A", "Page B"],
            "used_sources": {"7": {"url": "https://example.org/b", "title": "Page B", "context": "Source text"}},
            "reqid": "synthetic-request",
        }
        self.post = self.enterContext(patch("httpx.post", return_value=httpx.Response(200, json=self.response)))
        self.enterContext(patch("tools.browser_use_cli.browser_exec", side_effect=AssertionError("Search must not use the browser")))

    def test_sources_keep_citation_ids_and_summary_is_not_a_snippet(self):
        result = self.mod.normalize(self.response, 1, "yandex")
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]["web"]), 1)
        self.assertEqual(result["data"]["web"][0]["description"], "")
        self.assertEqual(result["data"]["generated_summary"], "Generated answer [7]")
        self.assertEqual(result["data"]["citations"]["7"]["url"], "https://example.org/b")
        self.assertTrue(result["data"]["summary_is_generated"])

    def test_supported_wire_envelopes_preserve_sources(self):
        for wire in [self.response, {"result": self.response}, {"status": "finished", "data": {"search_result": self.response}}]:
            with self.subTest(wire=list(wire)):
                result = self.mod.normalize(wire, 5, "yandex-context")
                self.assertTrue(result["success"])
                self.assertEqual(result["data"]["web"][1]["description"], "Source text")
                self.assertEqual(result["data"]["request_id"], "synthetic-request")

    def test_malformed_responses_are_errors_not_empty_success(self):
        for wire in [{}, [], {"error": "upstream failed"}, {"message": {"content": "untrusted"}, "is_answer_rejected": "false"}]:
            with self.subTest(wire=wire):
                self.assertFalse(self.mod.normalize(wire, 5, "yandex")["success"])

    def test_rejection_is_failure_with_sources_preserved(self):
        self.response["is_answer_rejected"] = True
        result = self.mod.normalize(self.response, 5, "yandex")
        self.assertFalse(result["success"])
        self.assertTrue(result["rejected"])
        self.assertEqual(result["data"]["web"][0]["url"], "https://example.org/a")

    def test_text_is_bounded_and_truncation_visible(self):
        self.response["used_sources"]["7"]["context"] = "x" * 10000
        doc = self.mod.normalize(self.response, 5, "yandex-context")["data"]["web"][1]
        self.assertEqual(len(doc["description"]), 4000)
        self.assertTrue(doc["context_truncated"])
        self.assertEqual(doc["context_original_chars"], 10000)

    def test_non_http_source_urls_are_not_returned(self):
        self.response["links"].extend(["javascript:alert(1)", "https://secret:password@example.org/"])
        self.response["used_sources"]["bad"] = {"url": "file:///etc/passwd"}
        result = self.mod.normalize(self.response, 5, "yandex")
        self.assertEqual(len(result["data"]["web"]), 2)
        self.assertNotIn("bad", result["data"]["citations"])

    def test_search_uses_direct_http_not_browser(self):
        result = self.mod.YandexSearchProvider().search("test", 2)
        self.assertTrue(result["success"])
        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.args, ("https://ya.ru/search/xml/generative",))
        self.assertEqual(self.post.call_args.kwargs["json"], {"messages": [{"role": "user", "content": "test"}]})
        self.assertFalse(self.post.call_args.kwargs["follow_redirects"])
        self.assertLessEqual(self.post.call_args.kwargs["timeout"], 60)
        self.assertNotIn("trust_env", self.post.call_args.kwargs)
        import ssl
        context = self.post.call_args.kwargs["verify"]
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_http_failure_has_no_retry_or_fallback(self):
        for status in [301, 401, 403, 429, 500, 504]:
            with self.subTest(status=status):
                self.post.reset_mock()
                self.post.return_value = httpx.Response(status, text="failure")
                result = self.mod.YandexSearchProvider().search("test", 2)
                self.assertFalse(result["success"])
                self.assertIn(str(status), result["error"])
                self.post.assert_called_once()

    def test_query_is_json_data(self):
        query = '\");globalThis.stolen=true;//\n<secret>"'
        self.assertTrue(self.mod.YandexSearchProvider().search(query, 2)["success"])
        self.assertEqual(self.post.call_args.kwargs["json"]["messages"][0]["content"], query)

    def test_context_provider_uses_existing_workflow(self):
        self.mod.YandexSearchProvider(context=True, endpoint="https://context.example.invalid/run").search("test", 2)
        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.args, ("https://context.example.invalid/run",))
        self.assertEqual(self.post.call_args.kwargs["json"], {"unexported": True, "data": {"query": "test"}})

    def test_invalid_query_never_calls_network(self):
        for query in ["", "  ", None, "x" * 12001]:
            with self.subTest(query_type=type(query)):
                self.assertFalse(self.mod.YandexSearchProvider().search(query, 5)["success"])
        self.post.assert_not_called()

    def test_network_exception_is_structured(self):
        self.post.side_effect = httpx.TimeoutException("timed out")
        result = self.mod.YandexSearchProvider().search("test", 5)
        self.assertFalse(result["success"])
        self.assertIn("TimeoutException", result["error"])
        self.post.assert_called_once()

    def test_non_json_is_not_empty_success(self):
        self.post.return_value = httpx.Response(200, text="<html>login</html>")
        self.assertFalse(self.mod.YandexSearchProvider().search("test", 5)["success"])

    def test_cancelled_search_does_not_start_network(self):
        with patch("tools.interrupt.is_interrupted", return_value=True):
            self.assertFalse(self.mod.YandexSearchProvider().search("test", 5)["success"])
        self.post.assert_not_called()

    def test_provider_capabilities_are_search_only_and_probe_is_cheap(self):
        provider = self.mod.YandexSearchProvider()
        self.assertTrue(provider.is_available())
        self.assertTrue(provider.supports_search())
        self.assertFalse(provider.supports_extract())
        self.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
