"""Optional portable failures retain outcomes without logging private exception data."""
import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.integrations.test_portable_extensions import load

PRIVATE = "synthetic-exception-secret /synthetic/private/path"


def assert_private_logs(caplog, logger, expected):
    records = [record for record in caplog.records if record.name == logger.name]
    assert len(records) == expected
    for record in records:
        assert "RuntimeError" in record.getMessage()
        assert PRIVATE not in record.getMessage()
        assert "synthetic-exception-secret" not in record.getMessage()
        assert "/synthetic/private/path" not in record.getMessage()
        assert record.exc_info is None
        assert record.levelno == logging.WARNING


def test_checkpoint_failure_is_optional_and_private(monkeypatch, caplog):
    plugin = load("project-memory-bank")
    monkeypatch.setattr(plugin.bank, "bound", lambda _: "synthetic-bank")
    handoff = Mock(side_effect=RuntimeError(PRIVATE))
    monkeypatch.setattr(plugin.bank, "handoff", handoff)
    assert plugin.save_checkpoint(session_id="synthetic-session") is None
    handoff.assert_called_once_with("synthetic-bank", "synthetic-session")
    assert_private_logs(caplog, plugin.logger, 1)


def test_search_failure_payload_is_preserved_but_log_is_private(monkeypatch, caplog):
    plugin = load("web-yandex")
    module = importlib.import_module(plugin.__name__ + ".provider")
    from tools import interrupt
    monkeypatch.setattr(interrupt, "is_interrupted", lambda: False)
    monkeypatch.setattr(module.httpx, "post", Mock(side_effect=RuntimeError(PRIVATE)))
    assert module.YandexSearchProvider().search("synthetic query") == {
        "success": False, "provider": "yandex", "error": "RuntimeError: " + PRIVATE,
    }
    assert_private_logs(caplog, module.logger, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["delivery", "callback", "deletion", "acknowledgement"])
async def test_reminder_failures_preserve_error_and_fallback(monkeypatch, tmp_path, caplog, failure):
    from gateway.config import PlatformConfig
    plugin = load("reminder-actions")
    module = importlib.import_module(plugin.__name__ + ".adapter")
    adapter = module.ReminderAdapter(PlatformConfig(), root=tmp_path / "store", route={}, jobs=["synthetic-job"])
    if failure == "delivery":
        monkeypatch.setattr(adapter, "_db", AsyncMock(side_effect=RuntimeError(PRIVATE)))
        result = await adapter.send("inbox", "notice\n\n[watch-actions:" + "a" * 32 + "]",
                                    metadata={"job_id": "synthetic-job"})
        assert not result.success and result.error == "reminder_controls_RuntimeError"
    else:
        query = SimpleNamespace(
            data="wr:c:" + "a" * 32, from_user=SimpleNamespace(id=1), answer=AsyncMock(),
            message=SimpleNamespace(from_user=SimpleNamespace(is_bot=True, id=2),
                                    chat=SimpleNamespace(id=3), message_id=4, message_thread_id=5),
        )
        db = AsyncMock(return_value={"status": "closed", "message_ids": [4]})
        if failure == "callback":
            db.side_effect = RuntimeError(PRIVATE)
        monkeypatch.setattr(adapter, "_db", db)
        delete = AsyncMock(side_effect=RuntimeError(PRIVATE))
        monkeypatch.setattr(adapter, "_delete_notifications", delete)
        fallback = AsyncMock()
        monkeypatch.setattr(adapter, "send", fallback)
        if failure == "acknowledgement":
            query.answer.side_effect = RuntimeError(PRIVATE)
        with pytest.raises(module.ApplicationHandlerStop):
            await adapter.reminder_callback(SimpleNamespace(callback_query=query), SimpleNamespace(bot=SimpleNamespace(id=2)))
        if failure == "callback":
            delete.assert_not_awaited()
            assert "Статус черновика не подтверждён" in query.answer.await_args.args[0]
        else:
            delete.assert_awaited_once_with(SimpleNamespace(id=2), 3, [4])
            assert "Нажми «Закрыть» ещё раз" in query.answer.await_args.args[0]
        if failure == "acknowledgement":
            fallback.assert_awaited_once_with("3", query.answer.await_args.args[0], metadata={"thread_id": "5"})
        else:
            fallback.assert_not_awaited()
    assert_private_logs(caplog, module.logger, 2 if failure == "acknowledgement" else 1)
