import importlib

import pytest
from fastapi.testclient import TestClient

from knowly.graph import GraphError

HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
KNOWN = {"known": True, "question_id": None, "pinged": None,
         "text": "tristan: retry 3 times, not 5, \"because the bank closes the SFTP window at 18:00\" (Payroll SFTP export, 2026-10-20).",
         "sources": [{"person": "tristan", "task": "Payroll SFTP export", "at": "2026-10-20T10:00:00+00:00",
                      "why": "retry 3 times, not 5, \"because the bank closes the SFTP window at 18:00\""}]}
UNKNOWN = {"known": False, "question_id": "q1", "pinged": "tristan",
           "text": "Not recorded yet. Related: tristan on Payroll SFTP export. I asked tristan; ask again once they have answered.",
           "sources": KNOWN["sources"]}


class FakeAsker:
    def __init__(self):
        self.calls = []
        self.notify = None

    async def ask(self, question, asker):
        self.calls.append((question, asker))
        if "unreachable" in question:
            raise GraphError("connection refused")
        return KNOWN if "retries" in question else UNKNOWN


@pytest.fixture
def mcp_api(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLY_TOKENS_DB", str(tmp_path / "tokens.db"))
    monkeypatch.setenv("KNOWLY_QUESTIONS_DB", str(tmp_path / "questions.db"))
    monkeypatch.setenv("KNOWLY_GRAPH_TOKENS", str(tmp_path / "graph_tokens.json"))
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    server = importlib.reload(importlib.import_module("knowly.server"))
    asker = FakeAsker()
    monkeypatch.setattr(server, "asker", asker)
    monkeypatch.setattr(server.mcp, "asker", asker)
    with TestClient(server.app) as client:
        yield client, server.tokens, asker


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
    route = routes(tokens, "lies")[kind]
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
    assert asker.calls == [("How many SFTP retries does the payroll export do?", "lies")]


def test_ask_unknown_question_reports_who_was_asked(mcp_api):
    client, tokens, asker = mcp_api
    result = call(client, routes(tokens, "lies")["bearer"], "ask", {"question": "What time does the nightly payroll export start?"})
    assert not result["isError"]
    assert result["structuredContent"]["known"] is False and result["structuredContent"]["pinged"] == "tristan"
    assert result["content"][0]["text"].endswith("I asked tristan; ask again once they have answered.")


def test_ask_takes_the_asker_from_the_token_only(mcp_api):
    client, tokens, asker = mcp_api
    route = routes(tokens, "lies")["personal"]
    result = call(client, route, "ask", {"question": "What time does the export start?", "asker": "tristan", "person": "tristan"})
    assert not result["isError"]
    assert asker.calls == [("What time does the export start?", "lies")]


@pytest.mark.parametrize("arguments", [{}, {"question": " x "}, {"question": "q" * 301}])
def test_ask_rejects_empty_or_overlong_questions(mcp_api, arguments):
    client, tokens, asker = mcp_api
    assert call(client, routes(tokens, "lies")["bearer"], "ask", arguments)["isError"]
    assert asker.calls == []


def test_ask_reports_an_unreachable_graph_as_a_tool_error(mcp_api):
    client, tokens, _ = mcp_api
    result = call(client, routes(tokens, "lies")["bearer"], "ask", {"question": "graph unreachable?"})
    assert result["isError"] and "knowledge graph is unreachable" in result["content"][0]["text"]


def test_unknown_or_missing_token_is_401(mcp_api):
    client, tokens, asker = mcp_api
    tokens.add("lies")
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    for url, headers in [("/u/wk_wrong/mcp", {}), ("/mcp", {}), ("/mcp", {"Authorization": "Bearer wk_wrong"}),
                         ("/mcp", {"Authorization": "wrong"})]:
        response = client.post(url, json=body, headers={**HEADERS, **headers})
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert asker.calls == []


def test_api_ask_uses_the_token_person(mcp_api):
    client, tokens, asker = mcp_api
    auth = {"Authorization": f"Bearer {tokens.add('lies')}"}
    for headers in [{}, {"Authorization": "Bearer wk_wrong"}]:
        assert client.post("/api/ask", json={"question": "What time?"}, headers=headers).status_code == 401
    assert client.post("/api/ask", json={"question": "x"}, headers=auth).status_code == 422
    response = client.post("/api/ask", json={"question": "What time does the nightly payroll export start?", "asker": "x"},
                           headers=auth)
    assert response.status_code == 200 and response.json() == UNKNOWN
    assert asker.calls == [("What time does the nightly payroll export start?", "lies")]
    assert client.post("/api/ask", json={"question": "graph unreachable?"}, headers=auth).status_code == 502


class FakeGraph:
    def __init__(self):
        self.posted = []

    def lookup(self, question):
        evidence = {"source_id": "s-payroll", "at": "2026-10-20T10:00:00+00:00", "similarity": 0.3, "role": "decided",
                    "why": "retry 3 times, not 5, \"because the bank closes the SFTP window at 18:00\"",
                    "task": "Payroll SFTP export"}
        return {"question": question, "status": "single_point", "best_similarity": 0.3,
                "people": [{"person": "tristan", "proficiency": 0.4, "evidence": [evidence]}]}

    def post_rows(self, rows, token):
        self.posted.append((rows, token))
        return {"added": len(rows), "updated": 0, "rejected": []}

    def invalidate(self):
        pass


def test_demo_flow_through_mcp_with_the_real_asker(mcp_api, tmp_path, monkeypatch):
    from knowly.ask import Asker

    client, tokens, _ = mcp_api
    graph, pings = FakeGraph(), []
    (tmp_path / "graph_tokens.json").write_text('{"tristan": "kg_tristan"}')

    def compose(question, lookup):
        e = lookup["people"][0]["evidence"][0]
        return {"answered": False, "text": f"Not recorded yet. Related: tristan, {e['why']} ({e['task']}).",
                "sources": [{"person": "tristan", "task": e["task"], "at": e["at"], "why": e["why"]}]}

    async def notify(record):
        pings.append(record)

    asker = Asker(graph, tmp_path / "questions.db", tmp_path / "graph_tokens.json", notify=notify, compose=compose)
    server = importlib.import_module("knowly.server")
    monkeypatch.setattr(server.mcp, "asker", asker)
    lies = routes(tokens, "lies")["bearer"]
    question = {"question": "What time does the nightly payroll export start?"}

    first = call(client, lies, "ask", question)["structuredContent"]
    assert first["known"] is False and first["pinged"] == "tristan" and "I asked tristan" in first["text"]
    [record] = pings
    assert (record["asker"], record["target"], record["question"]) == ("lies", "tristan", question["question"])
    assert call(client, lies, "ask", question)["structuredContent"]["question_id"] == record["id"] and len(pings) == 1

    row = asker.record_answer(record["id"], "tristan", "It starts at 16:00 so three retries finish before 18:00")
    assert graph.posted == [([row], "kg_tristan")] and row["person"] == "tristan"

    again = call(client, lies, "ask", question)["structuredContent"]
    assert again["known"] is True and "tristan" in again["text"] and "16:00" in again["text"]
