import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from knowly import config, server
from knowly.client import StoreError
from knowly.config import Settings

ADMIN = "a" * 40
ENV = ["KNOWLY_DATA_DIR", "KNOWLY_URL", "KNOWLY_ADMIN_TOKEN", "KNOWLY_BUCKET", "KNOWLY_CHANNEL", "KNOWLY_ALLOW_SELF",
       "SLACK_PEOPLE", "DEFAULT_EXPERT", "PORT", "HOST", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]


def fact(person: str) -> dict:
    return {"id": "s1:payroll", "person": person, "topic": "payroll-export", "source": "claude_session",
            "source_id": "s1", "at": "2026-10-20T10:00:00+00:00", "human_role": "corrected", "actor": "human",
            "why": "retry 3 times, not 5, because the bank closes the SFTP window at 18:00", "task": "Payroll SFTP export"}


class FakeAsker:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error, self.notify = [], result, error, None

    async def ask(self, question, asker):
        self.calls.append((question, asker))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def api(tmp_path):
    app = server.create_app(Settings(data_dir=tmp_path, admin_token=ADMIN))
    with TestClient(app) as client:
        yield client, app


def test_settings_defaults(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    assert config.load() == Settings()


def test_settings_from_env(monkeypatch, tmp_path):
    for name, value in {"KNOWLY_DATA_DIR": str(tmp_path), "KNOWLY_ADMIN_TOKEN": f" {ADMIN}\n", "KNOWLY_BUCKET": "b",
                        "KNOWLY_CHANNEL": "#team-questions", "KNOWLY_ALLOW_SELF": "1", "PORT": "9001",
                        "SLACK_PEOPLE": "Tristan:U0C9D2HJUA1, Albéric:U2,broken", "DEFAULT_EXPERT": " tristan ",
                        "SLACK_BOT_TOKEN": "xoxb-1", "SLACK_APP_TOKEN": "xapp-1"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("KNOWLY_URL", raising=False)
    settings = config.load()
    assert (settings.data_dir, settings.url, settings.admin_token, settings.bucket) == \
        (tmp_path, "http://127.0.0.1:9001", ADMIN, "b")
    assert (settings.channel, settings.allow_self, settings.default_expert, settings.port) == \
        ("team-questions", True, "tristan", 9001)
    assert settings.people == {"tristan": "U0C9D2HJUA1", "alberic": "U2"}
    assert (settings.slack_bot_token, settings.slack_app_token) == ("xoxb-1", "xapp-1")
    monkeypatch.setenv("KNOWLY_URL", "https://knowly.example/")
    monkeypatch.setenv("KNOWLY_ALLOW_SELF", "true")
    assert (config.load().url, config.load().allow_self) == ("https://knowly.example", False)


def test_one_app_serves_the_store_under_store(api, tmp_path):
    client, _ = api
    assert client.get("/healthz").json() == {"ok": True}
    assert client.post("/store/members", json={"person": "tristan"}).status_code == 401
    joined = client.post("/store/members", json={"person": "tristan"}, headers={"Authorization": f"Bearer {ADMIN}"})
    member = {"Authorization": f"Bearer {joined.json()['token']}"}
    assert client.post("/store/facts", json=[fact("tristan")]).status_code == 401
    assert client.post("/store/facts", json=[fact("tristan")], headers=member).json()["rejected"] == []
    assert [row["person"] for row in client.get("/store/rows").json()] == ["tristan"]
    assert client.get("/store/health").status_code == 200
    assert client.get("/rows").status_code == 404
    assert (tmp_path / "facts.sqlite").exists() and (tmp_path / "tokens.db").exists()


def test_ask_needs_a_known_token(api):
    client, _ = api
    for headers in [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "wrong"}]:
        assert client.post("/api/ask", json={"question": "what time?"}, headers=headers).status_code == 401


def test_ask_answers_as_the_token_owner(api):
    client, app = api
    alberic = {"Authorization": f"Bearer {app.state.tokens.add('alberic')}"}
    app.state.asker = FakeAsker({"known": True, "text": "16:00, tristan", "question_id": None, "pinged": None, "sources": []})
    response = client.post("/api/ask", json={"question": "  What time does the export start? "}, headers=alberic)
    assert response.json()["text"] == "16:00, tristan"
    assert app.state.asker.calls == [("What time does the export start?", "alberic")]
    app.state.asker = FakeAsker(error=StoreError("/who_knows: connection refused"))
    response = client.post("/api/ask", json={"question": "what time?"}, headers=alberic)
    assert response.status_code == 502 and "connection refused" in response.json()["detail"]


def test_access_log_hides_the_token_in_a_personal_url():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "POST", "/u/secret123/mcp", "1.1", 200), None)
    assert logging.getLogger("uvicorn.access").filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "POST /u/***/mcp HTTP/1.1" 200'


def test_large_or_unsized_bodies_are_rejected_before_the_token_check(api):
    client, _ = api
    assert client.post("/api/ask", content=b" " * (server.MAX_BODY + 1)).status_code == 413
    assert client.post("/api/ask", content=iter([b"{}"])).status_code == 413
    assert client.post("/store/facts", content=b" " * (server.MAX_BODY + 1)).status_code == 413
    assert client.post("/api/ask", json={"question": "what time?"}).status_code == 401


class UnreachableSlack:
    events: list

    def __init__(self, app, app_token):
        assert app_token == "xapp-test"

    async def connect_async(self):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.events.append("connect cancelled")
            raise

    async def close_async(self):
        self.events.append("closed")


def serve_once(app, events):
    async def start_and_stop():
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)
            events.append("serving")
        await asyncio.sleep(0)

    asyncio.run(asyncio.wait_for(start_and_stop(), 5))


def test_slack_starts_with_the_channel_and_the_bot(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(UnreachableSlack, "events", events, raising=False)
    monkeypatch.setattr(server, "AsyncSocketModeHandler", UnreachableSlack)
    monkeypatch.setattr(server, "register_channel", lambda app, **kwargs: events.append(("channel", kwargs)))
    monkeypatch.setattr(server, "register_bot", lambda app, asker, settings: events.append(("bot", asker, settings)))
    settings = Settings(data_dir=tmp_path, admin_token=ADMIN, slack_bot_token="xoxb-test", slack_app_token="xapp-test",
                        people={"tristan": "U0C9D2HJUA1"}, allow_self=True)
    app = server.create_app(settings)
    serve_once(app, events)
    (_, channel), (_, asker, passed), *rest = events
    assert channel["channel"] == "ask-knowly" and channel["base_url"] == "http://127.0.0.1:8091/store"
    assert channel["members"] is app.state.members and channel["threads_db"] == tmp_path / "threads.db"
    assert channel["people"] == {"tristan": "U0C9D2HJUA1"} and channel["allow_self"] is True
    assert channel["answer_fn"] is server.answer and channel["extract_fn"] is server.extract
    assert asker is app.state.asker and passed is settings
    assert rest == ["serving", "closed", "connect cancelled"]


def test_server_serves_while_slack_cannot_connect(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(UnreachableSlack, "events", events, raising=False)
    monkeypatch.setattr(server, "AsyncSocketModeHandler", UnreachableSlack)
    app = server.create_app(Settings(data_dir=tmp_path, admin_token=ADMIN, slack_bot_token="xoxb-test",
                                     slack_app_token="xapp-test"))
    serve_once(app, events)
    assert events == ["serving", "closed", "connect cancelled"]
    assert app.state.asker.notify is not None


def test_no_slack_without_both_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "AsyncSocketModeHandler", None)
    events = []
    serve_once(server.create_app(Settings(data_dir=tmp_path, slack_bot_token="xoxb-test")), events)
    assert events == ["serving"]


def test_main_serves_on_the_configured_host_and_port(tmp_path, monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KNOWLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setenv("HOST", "0.0.0.0")
    seen = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda app, host, port: seen.update(app=app, host=host, port=port))
    server.main()
    assert (seen["host"], seen["port"]) == ("0.0.0.0", 9123)
    assert seen["app"].state.settings.url == "http://127.0.0.1:9123"
