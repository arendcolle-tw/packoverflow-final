import asyncio
import importlib
import logging

import pytest
from fastapi.testclient import TestClient

from knowly.recorder.sessions import scrub
from knowly.tokens import Tokens


def test_member_tokens(tmp_path):
    tokens = Tokens(tmp_path / "tokens.db")
    token = tokens.add("alice")
    assert tokens.person_for(token) == "alice"
    assert token.startswith("wk_") and scrub(f"my token is {token}") == "my token is [redacted]"
    assert tokens.person_for("nope") is None
    other = tokens.add("bob")
    assert tokens.revoke("alice") == 1 and tokens.person_for(token) is None and tokens.person_for(other) == "bob"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLY_TOKENS_DB", str(tmp_path / "tokens.db"))
    monkeypatch.setenv("KNOWLY_QUESTIONS_DB", str(tmp_path / "questions.db"))
    monkeypatch.setenv("KNOWLY_GRAPH_TOKENS", str(tmp_path / "graph_tokens.json"))
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    server = importlib.reload(importlib.import_module("knowly.server"))
    with TestClient(server.app) as client:
        yield client, server.tokens


def test_api_requires_a_known_token(api):
    client, _ = api
    assert client.get("/healthz").json() == {"ok": True}
    for headers in [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "wrong"}]:
        assert client.post("/api/ask", json={"question": "what time?"}, headers=headers).status_code == 401


def test_access_log_hides_the_token_in_a_personal_url(api):
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "POST", "/u/wk_secret123/mcp", "1.1", 200), None)
    assert logging.getLogger("uvicorn.access").filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "POST /u/***/mcp HTTP/1.1" 200'


def test_api_rejects_large_or_unsized_bodies_before_the_token_check(api):
    client, _ = api
    limit = importlib.import_module("knowly.server").MAX_BODY
    assert client.post("/api/ask", content=b" " * (limit + 1)).status_code == 413
    assert client.post("/api/ask", content=iter([b"{}"])).status_code == 413
    assert client.post("/api/ask", json={"question": "what time?"}).status_code == 401


def test_lifespan_serves_while_slack_cannot_connect(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLY_TOKENS_DB", str(tmp_path / "tokens.db"))
    monkeypatch.setenv("KNOWLY_QUESTIONS_DB", str(tmp_path / "questions.db"))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    server = importlib.reload(importlib.import_module("knowly.server"))
    events = []

    class UnreachableSlack:
        def __init__(self, app, app_token):
            pass

        async def connect_async(self):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("connect cancelled")
                raise

        async def close_async(self):
            events.append("closed")

    monkeypatch.setattr(server, "AsyncSocketModeHandler", UnreachableSlack)

    async def start_and_stop():
        async with server.lifespan(server.app):
            await asyncio.sleep(0)
            events.append("serving")
        await asyncio.sleep(0)

    asyncio.run(asyncio.wait_for(start_and_stop(), 2))
    assert events == ["serving", "closed", "connect cancelled"]
    assert server.asker.notify is not None
