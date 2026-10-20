import sys

import pytest

CODE = "test-invite-code"


@pytest.fixture(autouse=True)
def _join_code(monkeypatch):
    monkeypatch.setenv("KC_JOIN_CODE", CODE)


@pytest.fixture(autouse=True)
def _reset_join_limit():
    # The join rate limit is per process; every test starts with a clean slate.
    server = sys.modules.get("knowledge_clock.server")
    if server is not None:
        server._JOINS.clear()
