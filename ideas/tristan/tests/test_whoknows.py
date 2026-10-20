import asyncio
import importlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from slack_bolt.async_app import AsyncApp
from slack_bolt.request.async_request import AsyncBoltRequest
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

import whoknows.slack as slack
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


def _result():
    rows = [row("alice", "s1", 1, 1, why="<!channel> & <@U999> because"),
            row("bob", "s2", 1, 2, why="because scans matter", task="<b>scan</b>")]
    return who_knows("<!here> aikido security scan", rows, NOW)


def _texts(rendered):
    for block in rendered:
        if "text" in block:
            yield block["text"]["text"]
        for element in block.get("elements", []):
            if element.get("type") == "mrkdwn":
                yield element["text"]


def test_blocks_escape_user_text_and_only_offer_known_people():
    rendered = slack.blocks(_result(), {"alice": "UALICE"})
    text = "\n".join(_texts(rendered))
    assert "&lt;!here&gt; aikido" in text and "&lt;!channel&gt; &amp; &lt;@U999&gt;" in text
    assert "&lt;b&gt;scan&lt;/b&gt;" in text and "*Bob*" in text and "<@UALICE>" in text
    assert re.findall(r"<[^>]*>", text) == ["<@UALICE>"]

    [actions] = [b for b in rendered if b["type"] == "actions"]
    [button] = actions["elements"]
    assert button["action_id"] == "ask_person_0" and button["text"]["text"] == "Ask Alice"
    assert json.loads(button["value"]) == {
        "user_id": "UALICE", "query": "<!here> aikido security scan", "why": "<!channel> & <@U999> because", "task": AIKIDO,
    }
    assert not [b for b in slack.blocks(_result(), {}) if b["type"] == "actions"]


@pytest.mark.parametrize("why", ["&" * 300, '"' * 300, "\x01" * 300, "\U0001f600" * 300])
def test_blocks_stay_within_block_kit_limits(why):
    long_name = "&" * 400
    rows = [row(long_name, "s1", 1, 1, why=why, task="&" * 300), row("bob", "s2", 1, 1)]
    result = who_knows("aikido security scan " + '&"' * 200, rows, NOW)
    for slack_ids in ({"bob": "U1"}, {"bob": "U1", slack.name_key(long_name): "U2"}):
        rendered = slack.blocks(result, slack_ids)
        # Slack counts UTF-16 code units, two bytes each.
        assert all(len(t.encode("utf-16-le")) <= 2 * 3000 for t in _texts(rendered))
        buttons = [e for b in rendered if b["type"] == "actions" for e in b["elements"]]
        assert buttons and all(
            len(b["value"].encode("utf-16-le")) <= 2 * 2000 and len(b["text"]["text"].encode("utf-16-le")) <= 2 * 75
            for b in buttons)


def test_plain_strips_slack_markup():
    text = "<@UBOT> who knows <!channel> &lt;deploy&gt; &amp; <https://x.io|the docs> in <#C1|ops>?"
    assert slack.plain(text) == "who knows !channel <deploy> & the docs in ops?"


class FakeClient(AsyncWebClient):
    calls: list = []
    members = [{"id": "UALICE", "profile": {"real_name": "Alice Doe"}}]
    mpim_scope = True

    async def api_call(self, api_method, *, http_verb="POST", files=None, data=None, params=None, json=None,
                       headers=None, auth=None):
        args = {**(params or {}), **(data or {}), **(json or {})}
        self.calls.append((api_method, {k: v for k, v in args.items() if v is not None}))
        if api_method == "conversations.open" and "," in args["users"] and not self.mpim_scope:
            raise SlackApiError("missing_scope", {"ok": False, "error": "missing_scope"})
        body = {
            "auth.test": {"user_id": "UBOT", "bot_id": "BBOT", "team_id": "T1"},
            "users.list": {"members": self.members},
            "conversations.open": {"channel": {"id": "DALICE"}},
        }.get(api_method, {})
        return AsyncSlackResponse(client=self, http_verb=http_verb, api_url=api_method, req_args={},
                                  data={"ok": True, **body}, headers={}, status_code=200)


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(slack, "_people_cache", {"at": 0.0, "ids": {}})
    monkeypatch.delenv("SLACK_PEOPLE", raising=False)
    # Bolt builds a new AsyncWebClient for every request, so the fake replaces the class.
    monkeypatch.setattr("slack_bolt.app.async_app.AsyncWebClient", FakeClient)
    monkeypatch.setattr(FakeClient, "calls", [])
    app = AsyncApp(token="xoxb-test", process_before_response=True)
    rows = [row("alice", "s1", 1, 1, why="<!channel> because")]
    slack.register(app, lambda: rows, NOW)
    return app, FakeClient.calls


def test_register_attaches_the_four_listeners(bot):
    app, _ = bot
    assert len(app._async_listeners) == 4
    assert {listener.ack_function.__name__ for listener in app._async_listeners} == {
        "on_mention", "on_dm", "on_command", "on_ask"}


def test_mention_answers_in_thread_through_bolt(bot):
    app, calls = bot
    body = {"type": "event_callback", "team_id": "T1", "api_app_id": "A1", "event_id": "Ev1", "event_time": 1,
            "event": {"type": "app_mention", "user": "UASKER", "channel": "C1", "ts": "1.0",
                      "text": "<@UBOT> who knows the <!channel> aikido security scan"}}
    response = asyncio.run(app.async_dispatch(AsyncBoltRequest(body=body, mode="socket_mode")))
    assert response.status == 200
    [(_, posted)] = [c for c in calls if c[0] == "chat.postMessage"]
    assert posted["channel"] == "C1" and posted["thread_ts"] == "1.0"
    text = "\n".join(_texts(posted["blocks"]))
    assert "!channel aikido" in text and "&lt;!channel&gt; because" in text and "<!" not in text + posted["text"]
    assert [b for b in posted["blocks"] if b["type"] == "actions"][0]["elements"][0]["action_id"] == "ask_person_0"


def test_slack_people_skips_guests_display_names_and_shared_first_names(monkeypatch):
    monkeypatch.setattr(slack, "_people_cache", {"at": 0.0, "ids": {}})
    monkeypatch.setenv("SLACK_PEOPLE", "bob:UBOB")
    monkeypatch.setattr(FakeClient, "members", [
        {"id": "UGUEST", "is_restricted": True, "profile": {"real_name": "Alice Outsider"}},
        {"id": "UEVE", "profile": {"real_name": "Eve Doe", "display_name": "Alice"}, "name": "alice"},
        {"id": "UALICE", "profile": {"real_name": "Alice Doe"}},
        {"id": "UBOB1", "profile": {"real_name": "Bob One"}},
        {"id": "UBOB2", "profile": {"real_name": "Bob Two"}},
        {"id": "UCAROL", "profile": {"real_name": "Carol Roe"}},
        {"id": "UCAROL2", "profile": {"real_name": "carol impostor"}},
    ])
    ids = asyncio.run(slack.slack_people(FakeClient(token="xoxb-test")))
    assert ids == {"alice": "UALICE", "eve": "UEVE", "bob": "UBOB"}


@pytest.mark.parametrize("mpim_scope, opened", [
    (True, [{"users": "UASKER,UALICE"}]),
    (False, [{"users": "UASKER,UALICE"}, {"users": "UALICE"}]),
])
def test_ask_button_dms_the_colleague_with_the_asker(bot, monkeypatch, mpim_scope, opened):
    app, calls = bot
    monkeypatch.setattr(FakeClient, "mpim_scope", mpim_scope)
    sent = []

    class FakeWebhook:
        def __init__(self, url, **_):
            self.url = url

        async def send_dict(self, message):
            sent.append(message)

    monkeypatch.setattr("slack_bolt.context.respond.async_respond.AsyncWebhookClient", FakeWebhook)
    value = json.dumps({"user_id": "UALICE", "query": "aikido <!here>", "why": "because & so", "task": AIKIDO})
    body = {"type": "block_actions", "team": {"id": "T1"}, "user": {"id": "UASKER"}, "api_app_id": "A1",
            "channel": {"id": "C1"}, "response_url": "https://hooks.slack.test/x", "trigger_id": "t",
            "actions": [{"type": "button", "action_id": "ask_person_1", "block_id": "b", "value": value}]}
    response = asyncio.run(app.async_dispatch(AsyncBoltRequest(body=body, mode="socket_mode")))
    assert response.status == 200
    assert [args for method, args in calls if method == "conversations.open"] == opened
    [(_, dm)] = [c for c in calls if c[0] == "chat.postMessage"]
    assert dm["channel"] == "DALICE" and "<@UASKER>" in dm["text"]
    assert "aikido &lt;!here&gt;" in dm["text"] and "because &amp; so" in dm["text"]
    assert sent[0]["response_type"] == "ephemeral" and sent[0]["replace_original"] is False


def test_command_responds_in_channel(bot, monkeypatch):
    app, _ = bot
    sent = []

    class FakeWebhook:
        def __init__(self, url, **_):
            pass

        async def send_dict(self, message):
            sent.append(message)

    monkeypatch.setattr("slack_bolt.context.respond.async_respond.AsyncWebhookClient", FakeWebhook)
    body = {"command": "/whoknows", "text": "aikido security scan", "team_id": "T1", "user_id": "UASKER",
            "channel_id": "C1", "response_url": "https://hooks.slack.test/x", "trigger_id": "t", "api_app_id": "A1"}
    response = asyncio.run(app.async_dispatch(AsyncBoltRequest(body=body, mode="socket_mode")))
    assert response.status == 200
    assert sent[0]["response_type"] == "in_channel" and sent[0]["blocks"][0]["text"]["text"] == "*Who knows:* _aikido security scan_"
