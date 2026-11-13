"""Principal construction stays in the scoped plugin, not a global import."""

import ast, collections, os, types, unittest
import logging
from unittest.mock import patch
from pathlib import Path

SOURCE = Path(os.environ["ATLAS_GUARD_SOURCE"])


class PrincipalBoundary(unittest.TestCase):
    def service(self):
        tree = ast.parse(SOURCE.read_text())
        cls = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Service"
        )
        ns = {
            "OWNER": "123456789",
            "Principal": collections.namedtuple(
                "Principal", "user_id session_key role profile chat_id thread_id"
            ),
        }
        fn = [
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "principal_for_binding"
        ]
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=fn, type_ignores=[])),
                str(SOURCE),
                "exec",
            ),
            ns,
        )
        service = types.SimpleNamespace(
            admission=types.SimpleNamespace(valid=lambda b: b is self.binding)
        )
        service.principal_for_binding = lambda b, k: ns["principal_for_binding"](
            service.admission, b, k
        )
        return service

    def setUp(self):
        self.binding = types.SimpleNamespace(
            user_id="41", chat_id="41", chat_type="dm", profile="tg-41", thread_id=None
        )

    def test_member_exact_bound_fields(self):
        p = self.service().principal_for_binding(self.binding, "native-key")
        self.assertEqual(tuple(p), ("41", "native-key", "member", "tg-41", "41", ""))

    def test_owner_keeps_same_ceiling_identity(self):
        self.binding.user_id = "123456789"
        p = self.service().principal_for_binding(self.binding, "native-key")
        self.assertEqual(p.role, "owner")

    def test_unissued_equivalent_binding_denied(self):
        s = self.service()
        with self.assertRaises(PermissionError):
            s.principal_for_binding(
                types.SimpleNamespace(**vars(self.binding)), "native-key"
            )

    def test_revocation_denied(self):
        s = self.service()
        s.admission.valid = lambda b: False
        with self.assertRaises(PermissionError):
            s.principal_for_binding(self.binding, "native-key")

    def test_group_retains_namespace_and_thread(self):
        self.binding.chat_id = "-1009"
        self.binding.profile = "tg-group-n1009-t8"
        self.binding.thread_id = "8"
        p = self.service().principal_for_binding(self.binding, "group-key")
        self.assertEqual(
            (p.chat_id, p.profile, p.thread_id), ("-1009", "tg-group-n1009-t8", "8")
        )


class Diagnostics(unittest.TestCase):
    def guard(self, error):
        tree = ast.parse(SOURCE.read_text())
        cls = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Service"
        )
        methods = [
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef)
            and n.name in ("guard_llm", "_guard_diagnostic")
        ]
        scope = {"logging": logging, "os": os, "json": __import__("json")}
        exec(
            compile(
                ast.fix_missing_locations(
                    ast.Module(
                        body=[
                            ast.ClassDef(
                                name="Guard",
                                bases=[],
                                keywords=[],
                                body=methods,
                                decorator_list=[],
                            )
                        ],
                        type_ignores=[],
                    )
                ),
                str(SOURCE),
                "exec",
            ),
            scope,
        )
        g = scope["Guard"]()
        g._guard_diagnostic_seen = set()
        g.ctx = types.SimpleNamespace(profile_name="private-do-not-emit")
        g.admission = types.SimpleNamespace(valid=lambda b: False)

        def deny():
            raise error

        g.authorized_principal = deny
        return g

    def test_known_code_and_boolean_snapshot(self):
        with self.assertLogs("atlas.guard", level="WARNING") as logs:
            result = self.guard(
                PermissionError("ambient_identity_forbidden")
            ).guard_llm(prompt="sensitive-prompt")
        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Bound admitted private Telegram profile required.",
            },
        )
        text = " ".join(logs.output)
        self.assertIn("ambient_identity_forbidden", text)
        self.assertNotIn("sensitive-prompt", text)
        self.assertNotIn("private-do-not-emit", text)

    def test_unknown_exception_is_redacted(self):
        with self.assertLogs("atlas.guard", level="WARNING") as logs:
            self.guard(ValueError("secret-test-value")).guard_llm(
                key="secret-test-value"
            )
        self.assertIn("unclassified_guard_denial", " ".join(logs.output))
        self.assertNotIn("secret-test-value", " ".join(logs.output))

    def test_telemetry_failure_cannot_replace_denial(self):
        g = self.guard(PermissionError("ambient_identity_forbidden"))
        with patch.object(
            logging.getLogger("atlas.guard"),
            "warning",
            side_effect=RuntimeError("sensitive-log-error"),
        ):
            self.assertEqual(
                g.guard_llm(),
                {
                    "action": "block",
                    "message": "Bound admitted private Telegram profile required.",
                },
            )

    def test_repeated_code_is_bounded(self):
        g = self.guard(PermissionError("ambient_identity_forbidden"))
        with self.assertLogs("atlas.guard", level="WARNING") as logs:
            for _ in range(20):
                g.guard_llm()
        self.assertEqual(len(logs.output), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
