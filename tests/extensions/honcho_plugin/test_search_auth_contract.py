"""Authentication failures must not be reported as an empty memory search."""

from types import SimpleNamespace

import pytest

from memory_test_plugins.honcho.session_auth import HonchoAuthError
from tests.extensions.honcho_plugin import test_capture_context_contract as capture

rig = capture.rig


@pytest.mark.parametrize("fallback", [False, True])
def test_search_auth_error_does_not_fall_back_to_empty(rig, monkeypatch, fallback):
    _, manager, session, _, _ = rig
    error = HonchoAuthError("fixture authentication failure")

    def primary(*args, **kwargs):
        if fallback:
            raise RuntimeError("fixture search endpoint unavailable")
        raise error

    def peer_search(*args, **kwargs):
        raise error

    manager.honcho.search = primary
    monkeypatch.setattr(manager, "_peer_ref", lambda peer: SimpleNamespace(search=peer_search))
    with pytest.raises(HonchoAuthError, match="fixture authentication failure"):
        manager.search_context(session.key, "certificate renewal")
