from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowly import ask as ask_mod
from knowly.ask import Asker
from knowly.client import StoreError
from knowly.mcp_server import MemberMCP
from knowly.tokens import Tokens

HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
SOURCES = [{"person": "tristan", "task": "Payroll SFTP export", "at": "2026-10-20",
            "why": "retry 3 times, not 5, \"because the bank closes the SFTP window at 18:00\""}]
KNOWN = {"known": True, "question_id": None, "pinged": None, "sources": SOURCES,
         "text": "Three retries. Tristan chose that because the bank closes the SFTP window at 18:00."}
UNKNOWN = {"known": False, "question_id": "q1", "pinged": "tristan", "sources": SOURCES,
           "text": "Based on what's in Knowly there's no answer to this yet. Tristan set up the payroll SFTP export, so he's "
                   "the one to ask.\n\nTristan, do you know when the export starts?"}


class FakeAsker:
    def __init__(self):
        self.calls = []

    async def ask(self, question, asker):
        self.calls.append((question, asker))
        if "unreachable" in question:
            raise StoreError("connection refused")
        return KNOWN if "retries" in question else UNKNOWN


def serve(tokens, asker):
    mcp = MemberMCP(tokens, asker)

    @asynccontextmanager
    async def lifespan(_):
        async with mcp.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_route("/mcp", mcp)
    app.add_route("/u/{token}/mcp", mcp)
    return TestClient(app)


@pytest.fixture
def mcp_api(tmp_path):
    tokens, asker = Tokens(tmp_path / "tokens.db"), FakeAsker()
    with serve(tokens, asker) as client:
        yield client, tokens, asker


def routes(tokens, person):
    token = tokens.add(person)
    return {"personal": (f"/u/{token}/mcp", {}), "bearer": ("/mcp", {"Authorization": f"Bearer {token}"})}


def rpc(client, route, method, params=None, id=1):
    url, auth = route
    response = client.post(url, json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}},
                           headers={**HEADERS, **auth})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def call(client, route, tool, arguments=None):
    return rpc(client, route, "tools/call", {"name": tool, "arguments": arguments or {}})


@pytest.mark.parametrize("kind", ["personal", "bearer"])
def test_mcp_protocol_and_ask_on_both_routes(mcp_api, kind):
    client, tokens, asker = mcp_api
    route = routes(tokens, "alberic")[kind]
    init = rpc(client, route, "initialize", {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
    assert init["serverInfo"]["name"] == "knowly" and "Call ask when" in init["instructions"]
    url, auth = route
    note = client.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={**HEADERS, **auth})
    assert note.status_code == 202

    [tool] = rpc(client, route, "tools/list")["tools"]
    assert tool["name"] == "ask"
    assert set(tool["inputSchema"]["properties"]) == {"question"} and tool["inputSchema"]["required"] == ["question"]

    known = call(client, route, "ask", {"question": "  How many SFTP retries does the payroll export do?  "})
    assert not known["isError"] and known["structuredContent"] == KNOWN
    assert known["content"][0]["text"] == KNOWN["text"]
    assert asker.calls == [("How many SFTP retries does the payroll export do?", "alberic")]


def test_ask_unknown_question_reports_who_was_asked(mcp_api):
    client, tokens, _ = mcp_api
    result = call(client, routes(tokens, "alberic")["bearer"], "ask", {"question": "What time does the nightly payroll export start?"})
    assert not result["isError"]
    assert result["structuredContent"]["known"] is False and result["structuredContent"]["pinged"] == "tristan"
    assert result["content"][0]["text"].endswith("Tristan, do you know when the export starts?")


def test_ask_takes_the_asker_from_the_token_only(mcp_api):
    client, tokens, asker = mcp_api
    route = routes(tokens, "alberic")["personal"]
    result = call(client, route, "ask", {"question": "What time does the export start?", "asker": "tristan", "person": "tristan"})
    assert not result["isError"]
    assert asker.calls == [("What time does the export start?", "alberic")]


@pytest.mark.parametrize("arguments", [{}, {"question": " x "}, {"question": "q" * 301}])
def test_ask_rejects_empty_or_overlong_questions(mcp_api, arguments):
    client, tokens, asker = mcp_api
    assert call(client, routes(tokens, "alberic")["bearer"], "ask", arguments)["isError"]
    assert asker.calls == []


def test_ask_reports_an_unreachable_store_as_a_tool_error(mcp_api):
    client, tokens, _ = mcp_api
    result = call(client, routes(tokens, "alberic")["bearer"], "ask", {"question": "store unreachable?"})
    assert result["isError"] and "fact store is unreachable" in result["content"][0]["text"]


def test_unknown_or_missing_token_is_401(mcp_api):
    client, tokens, asker = mcp_api
    tokens.add("alberic")
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    for url, headers in [("/u/wk_wrong/mcp", {}), ("/mcp", {}), ("/mcp", {"Authorization": "Bearer wk_wrong"}),
                         ("/mcp", {"Authorization": "wrong"})]:
        response = client.post(url, json=body, headers={**HEADERS, **headers})
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert asker.calls == []


class FakeMembers:
    def __init__(self):
        self.stored = []

    def store_fact(self, person, question, fact, topic, question_id):
        self.stored.append((person, question, fact))
        return {"id": f"question:{question_id}:{person}", "person": person, "why": fact}


def test_demo_flow_through_mcp_with_the_real_asker(tmp_path, monkeypatch):
    def answer(question, asker, base_url):
        return {"answered": False, "answer": "Based on what's in Knowly there's no answer to this yet.",
                "sources": SOURCES, "ask_person": "tristan", "why_them": "Tristan set up the payroll export.",
                "ping": "{person}, do you know when the export starts?"}

    async def notify(record):
        pings.append(record)

    pings, members = [], FakeMembers()
    monkeypatch.setattr(ask_mod, "answer", answer)
    tokens = Tokens(tmp_path / "tokens.db")
    asker = Asker("http://knowly.test/store", tmp_path, members, notify=notify)
    question = {"question": "What time does the nightly payroll export start?"}

    with serve(tokens, asker) as client:
        alberic = routes(tokens, "alberic")["bearer"]
        first = call(client, alberic, "ask", question)["structuredContent"]
        assert first["known"] is False and first["pinged"] == "tristan"
        assert first["text"].endswith("\n\nTristan, do you know when the export starts?")
        [record] = pings
        assert (record["asker"], record["target"], record["question"]) == ("alberic", "tristan", question["question"])
        assert call(client, alberic, "ask", question)["structuredContent"]["question_id"] == record["id"] and len(pings) == 1

        asker.record_answer(record["id"], "tristan", "It starts at 16:00 so three retries finish before 18:00")
        assert members.stored == [("tristan", question["question"], "It starts at 16:00 so three retries finish before 18:00")]

        again = call(client, alberic, "ask", question)["structuredContent"]
        assert again["known"] is True and again["text"].startswith("Tristan answered this on") and "16:00" in again["text"]
