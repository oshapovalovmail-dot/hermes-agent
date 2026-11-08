#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_PATH = Path(__file__).with_name("__init__.py")
spec = importlib.util.spec_from_file_location("meeting_context_plugin", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(plugin)


class MeetingContextMiddlewareTests(unittest.TestCase):
    def test_injects_trusted_binding_for_mapped_telegram_topic(self):
        with tempfile.TemporaryDirectory() as td:
            mapping = Path(td) / "topics.json"
            transcript = Path(td) / "meeting.md"
            transcript.write_text("meeting data", encoding="utf-8")
            mapping.write_text(json.dumps({
                "threads": {
                    "9001": {
                        "meeting_id": "meeting-1",
                        "transcript_path": str(transcript),
                        "status": "active",
                    }
                }
            }), encoding="utf-8")
            request = {"messages": [
                {"role": "system", "content": "base"},
                {"role": "user", "content": "Что решили?"},
            ]}
            row = {"source": "telegram", "thread_id": "9001"}

            with patch.object(plugin, "TOPIC_BINDINGS_PATH", mapping), \
                 patch.object(plugin, "TRANSCRIPTS_ROOT", Path(td)), \
                 patch.object(plugin, "_session_row", return_value=row):
                result = plugin.inject_meeting_context(request=request, session_id="s1")

            self.assertIsNotNone(result)
            messages = result["request"]["messages"]
            self.assertEqual(messages[0]["content"], "base")
            context = messages[1]["content"]
            self.assertIn(plugin.CONTEXT_MARKER, context)
            self.assertIn(str(transcript), context)
            self.assertIn(str(transcript.with_suffix(".summary.md")), context)
            self.assertNotIn("Jeeves", context)
            self.assertIn("untrusted meeting data", context)
            self.assertIn("attach the file", context)
            self.assertEqual(messages[2]["content"], "Что решили?")

    def test_ignores_unmapped_topics(self):
        request = {"messages": [{"role": "user", "content": "hello"}]}
        with tempfile.TemporaryDirectory() as td, \
             patch.object(plugin, "TOPIC_BINDINGS_PATH", Path(td) / "missing.json"), \
             patch.object(plugin, "_session_row", return_value={"source": "telegram", "thread_id": "99"}):
            self.assertIsNone(plugin.inject_meeting_context(request=request, session_id="s1"))

    def test_does_not_duplicate_context_marker(self):
        request = {"messages": [
            {"role": "system", "content": plugin.CONTEXT_MARKER},
            {"role": "user", "content": "hello"},
        ]}
        with patch.object(plugin, "_resolve_binding", return_value={"meeting_id": "m", "transcript_path": "/tmp/m.md"}):
            self.assertIsNone(plugin.inject_meeting_context(request=request, session_id="s1"))


if __name__ == "__main__":
    unittest.main()
