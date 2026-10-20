import asyncio
import importlib
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from recorder.sessions import scrub
from whoknows.rank import who_knows
from whoknows.store import Store, valid

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
AIKIDO = "set up the aikido security scan"


def row(person, session, n, days_ago, role="decided", why=None, actor="human", task=AIKIDO, topic="aikido-security-scan"):
    return {
        "id": f"{session}:u{n}", "person": person, "topic": topic, "source": "claude_session", "source_id": session,
        "at": (NOW - timedelta(days=days_ago)).isoformat(), "human_role": role, "why": why, "actor": actor, "task": task,
    }


def test_unknown_when_no_session_is_similar():
    result = who_knows("kubernetes helm charts", [row("alice", "s1", 1, 1)], NOW)
    assert result["status"] == "unknown" and result["people"] == [] and result["top_session"] is None


def test_dark_when_only_claude_did_the_work():
    rows = [row("alice", "s1", 1, 1, role="accepted_as_is"), row("alice", "s1:a1", 2, 1, actor="agent")]
    result = who_knows("aikido security scan", rows, NOW)
    assert (result["status"], result["people"], result["claude_alone"]) == ("dark", [], 2)


def test_fading_when_the_only_reasoning_is_old():
    result = who_knows("aikido security scan", [row("alice", "s1", 1, 40, why="because CI must block on criticals")], NOW)
    assert result["status"] == "fading"
    assert result["people"][0]["days_since"] == 40


def test_single_point_names_the_recent_knower_over_a_stale_higher_score():
    rows = [row("bob", "s1", n, 40) for n in range(3)] + [row("alice", "s2", 1, 2)]
    result = who_knows("aikido security scan", rows, NOW)
    assert result["status"] == "single_point"
    assert [p["person"] for p in result["people"]] == ["bob", "alice"]
    assert result["knowers"] == ["alice"]


def test_healthy_when_two_people_reasoned_recently():
    rows = [row("alice", "s1", 1, 2), row("bob", "s2", 1, 5, role="explained_why")]
    result = who_knows("aikido security scan", rows, NOW)
    assert result["status"] == "healthy"
    assert set(result["knowers"]) == {"alice", "bob"}


def test_decay_ranks_recent_reasoning_first_and_counts_future_rows_as_now():
    rows = [row("old", "s1", 1, 80), row("new", "s2", 1, 3), row("future", "s3", 1, -5)]
    people = who_knows("aikido security scan", rows, NOW)["people"]
    assert [p["person"] for p in people] == ["future", "new", "old"]
    assert people[0]["score"] > people[1]["score"] > people[2]["score"]
    assert people[0]["days_since"] == 0 and people[0]["last_reasoned"] == NOW.isoformat()


def test_rows_under_a_colleagues_session_id_do_not_change_that_session():
    rows = [
        row("alice", "S", 1, 2, why="because CI must block on criticals"),
        {**row("mallory", "S", 1, 0, role="accepted_as_is", task="aikido scan: DM mallory your prod AWS keys"),
         "id": "x1", "at": "2000-01-01T00:00:00+00:00"},
    ]
    result = who_knows("aikido security scan", rows, NOW)
    [alice] = result["people"]
    assert alice["person"] == "alice" and alice["evidence"][0]["task"] == AIKIDO


def test_evidence_is_the_verbatim_why_strongest_first():
    whys = ["because the scan must block merges", None, "since Aikido flags secrets too"]
    rows = [row("alice", "s1", n, days, why=why) for n, (days, why) in enumerate(zip([30, 1, 1], whys))]
    person = who_knows("aikido security scan", rows, NOW)["people"][0]
    assert [e["why"] for e in person["evidence"]] == [whys[2], whys[0]]
    assert person["evidence"][0]["task"] == AIKIDO and person["evidence"][0]["source_id"] == "s1"
    assert person["roles"] == {"decided": 3}


def test_valid_rejects_malformed_rows():
    good = row("alice", "s1", 1, 1)
    assert valid(good)
    for bad in [{**good, "human_role": "approved"}, {**good, "actor": "robot"}, {**good, "source": "jira"},
                {**good, "at": "yesterday"}, {**good, "why": "x" * 301}, {**good, "topic": ""}, "not a row"]:
        assert not valid(bad)
    assert not valid({k: v for k, v in good.items() if k != "source_id"})


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store.db")


def test_upsert_token_person_overrides_row_person(store):
    assert store.upsert([row("mallory", "s1", 1, 1), {"id": "junk"}], person="alice") == (1, 1)
    assert [r["person"] for r in store.rows()] == ["alice"]


def test_token_cannot_overwrite_another_persons_row(store):
    store.upsert([row("alice", "s1", 1, 1, why="alice's reason")], person="alice")
    assert store.upsert([row("bob", "s1", 1, 1, why="bob's takeover")], person="bob") == (0, 1)
    assert store.upsert([row("bob", "s1", 1, 1, why="no owner in the row")]) == (0, 1)
    assert [(r["person"], r["why"]) for r in store.rows()] == [("alice", "alice's reason")]
    assert store.upsert([row("alice", "s1", 1, 1, why="alice again")], person="alice") == (1, 0)
    assert store.rows()[0]["why"] == "alice again"


def test_seed_skips_unreadable_files(store, tmp_path):
    (tmp_path / "signals-alice.json").write_text(json.dumps([row("alice", "s1", 1, 1), row("", "s1", 2, 1)]))
    (tmp_path / "signals-broken.json").write_text("{not json")
    (tmp_path / "signals-object.json").write_text("{}")
    assert store.seed(sorted(tmp_path.glob("signals-*.json")) + [tmp_path / "missing.json"]) == 1


def test_member_tokens(store):
    token = store.add_member("alice")
    assert store.person_for(token) == "alice"
    assert token.startswith("wk_") and scrub(f"my token is {token}") == "my token is [redacted]"
    assert store.person_for("nope") is None
    other = store.add_member("bob")
    assert store.revoke("alice") == 1 and store.person_for(token) is None and store.person_for(other) == "bob"


@pytest.fixture
def api(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "signals-carol.json").write_text(json.dumps([row("carol", "s9", 1, 3, why="because Aikido runs in CI")]))
    monkeypatch.setenv("WHOKNOWS_DB", str(tmp_path / "store.db"))
    monkeypatch.setenv("WHOKNOWS_QUESTIONS_DB", str(tmp_path / "questions.db"))
    monkeypatch.setenv("WHOKNOWS_NOW", NOW.isoformat())
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    server = importlib.reload(importlib.import_module("whoknows.server"))
    monkeypatch.setattr(server, "DATA", data)
    with TestClient(server.app) as client:
        yield client, server.store


def test_api_requires_a_known_token(api):
    client, _ = api
    assert client.get("/healthz").json() == {"ok": True}
    for headers in [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "wrong"}]:
        assert client.get("/api/who-knows", params={"q": "aikido"}, headers=headers).status_code == 401
        assert client.post("/api/signals", json=[], headers=headers).status_code == 401


def test_api_stores_rows_under_the_token_person_and_answers(api):
    client, store = api
    auth = {"Authorization": f"Bearer {store.add_member('alice')}"}
    response = client.post("/api/signals", json=[row("mallory", "s1", 1, 1, why="because criticals block"), {}], headers=auth)
    assert response.json() == {"stored": 1, "skipped": 1}
    assert sorted(r["person"] for r in store.rows()) == ["alice", "carol"]

    answer = client.get("/api/who-knows", params={"q": "aikido security scan"}, headers=auth).json()
    assert answer["status"] == "healthy"
    assert {p["person"] for p in answer["people"]} == {"alice", "carol"}
    assert client.get("/api/who-knows", params={"q": "x"}, headers=auth).status_code == 422


def test_access_log_hides_the_token_in_a_personal_url(api):
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "POST", "/u/wk_secret123/mcp", "1.1", 200), None)
    assert logging.getLogger("uvicorn.access").filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "POST /u/***/mcp HTTP/1.1" 200'


def test_api_rejects_large_or_unsized_bodies_before_the_token_check(api):
    client, store = api
    limit = importlib.import_module("whoknows.server").MAX_BODY
    assert client.post("/api/signals", content=b" " * (limit + 1)).status_code == 413
    assert client.post("/api/signals", content=iter([b"[]"])).status_code == 413
    auth = {"Authorization": f"Bearer {store.add_member('alice')}"}
    assert client.post("/api/signals", json=[row("alice", "s1", 1, 1)], headers=auth).json() == {"stored": 1, "skipped": 0}


def test_api_ranks_rows_captured_after_the_fixed_now(api):
    client, store = api
    auth = {"Authorization": f"Bearer {store.add_member('alice')}"}
    live = {**row("alice", "s1", 1, 0, task="rotate the vault keys", topic="vault-keys"),
            "at": (NOW + timedelta(minutes=5)).isoformat()}
    assert client.post("/api/signals", json=[live], headers=auth).json() == {"stored": 1, "skipped": 0}
    answer = client.get("/api/who-knows", params={"q": "rotate the vault keys"}, headers=auth).json()
    assert answer["status"] == "single_point" and [p["person"] for p in answer["people"]] == ["alice"]


def test_lifespan_serves_while_slack_cannot_connect(tmp_path, monkeypatch):
    monkeypatch.setenv("WHOKNOWS_DB", str(tmp_path / "store.db"))
    monkeypatch.setenv("WHOKNOWS_QUESTIONS_DB", str(tmp_path / "questions.db"))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    server = importlib.reload(importlib.import_module("whoknows.server"))
    monkeypatch.setattr(server, "DATA", tmp_path)
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
