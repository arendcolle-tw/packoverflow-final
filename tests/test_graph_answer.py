import io
import json
import subprocess
import urllib.error

import pytest

from knowly import answer, graph
from knowly.answer import compose
from knowly.graph import GraphClient, GraphError

PAYROLL_WHY = 'Chose 3 retries over 5 "because the bank closes the SFTP window at 18:00"'
WHO_KNOWS = {
    "query": "payroll export", "status": "single_point", "owner": "tristan", "similar_tasks": 1,
    "people": [
        {"person": "tristan", "proficiency": 0.6, "evidence": [
            {"source_id": "s1", "at": "2026-10-19T10:00:00+00:00", "similarity": 0.42, "takeover": 1.0, "contribution": 0.4,
             "whys": [{"role": "decided", "why": PAYROLL_WHY}]},
        ]},
        {"person": "lies", "proficiency": 0.0, "evidence": []},
    ],
}
ROWS = [
    {"id": "s1:summary", "person": "tristan", "topic": "payroll", "source": "claude_session", "source_id": "s1",
     "at": "2026-10-19T10:00:00Z", "human_role": "decided", "actor": "human", "why": PAYROLL_WHY, "task": "Payroll SFTP export retries"},
]


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, request, timeout=None):
        path = request.full_url.split("8770", 1)[1]
        self.calls.append((request.get_method(), path, request.headers, request.data))
        reply = self.routes[path.split("?")[0]]
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())


@pytest.fixture
def http(monkeypatch):
    fake = FakeHttp({"/who_knows": WHO_KNOWS, "/rows": ROWS, "/signals": {"added": 1, "updated": 0, "rejected": []}})
    monkeypatch.setattr(graph.urllib.request, "urlopen", fake)
    return fake


def test_lookup_flattens_evidence_and_caches_rows(http):
    client = GraphClient("http://127.0.0.1:8770")
    found = client.lookup("When does the payroll export start?")
    assert found["status"] == "single_point"
    assert found["best_similarity"] == 0.42
    assert found["people"] == [{"person": "tristan", "proficiency": 0.6, "evidence": [
        {"source_id": "s1", "at": "2026-10-19T10:00:00+00:00", "similarity": 0.42, "why": PAYROLL_WHY,
         "role": "decided", "task": "Payroll SFTP export retries", "topic": "payroll"}]}]
    assert "q=When+does+the+payroll" in http.calls[0][1]

    client.lookup("again")
    assert [c[1] for c in http.calls].count("/rows") == 1
    client.invalidate()
    client.lookup("again")
    assert [c[1] for c in http.calls].count("/rows") == 2


def test_lookup_task_matches_grouped_source_ids(http):
    http.routes["/rows"] = [{**ROWS[0], "id": "ask:q1:tristan", "source_id": "ask:q1", "task": "When does it start?"}]
    http.routes["/who_knows"] = {**WHO_KNOWS, "people": [{**WHO_KNOWS["people"][0], "evidence": [
        {**WHO_KNOWS["people"][0]["evidence"][0], "source_id": "ask"}]}]}
    assert GraphClient("http://127.0.0.1:8770").lookup("x")["people"][0]["evidence"][0]["task"] == "When does it start?"


def test_post_rows_sends_bearer_and_drops_cache(http):
    client = GraphClient("http://127.0.0.1:8770")
    client.rows()
    assert client.post_rows(ROWS, "tok") == {"added": 1, "updated": 0, "rejected": []}
    method, path, headers, body = http.calls[-1]
    assert (method, path, headers["Authorization"]) == ("POST", "/signals", "Bearer tok")
    assert json.loads(body) == ROWS
    client.rows()
    assert [c[1] for c in http.calls].count("/rows") == 2


def test_post_rows_raises_on_rejected_rows(http):
    http.routes["/signals"] = {"added": 0, "updated": 0, "rejected": ["row 0: why longer than 200 characters"]}
    with pytest.raises(GraphError, match="why longer"):
        GraphClient("http://127.0.0.1:8770").post_rows(ROWS, "tok")


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"unknown member token")),
    urllib.error.URLError("connection refused"),
])
def test_http_failures_raise_graph_error(http, error):
    http.routes["/signals"] = error
    with pytest.raises(GraphError):
        GraphClient("http://127.0.0.1:8770").post_rows(ROWS, "tok")


def test_default_url_from_env(monkeypatch):
    monkeypatch.setenv("KG_URL", "http://graph.example/")
    assert GraphClient().base_url == "http://graph.example"


LOOKUP = {"question": "q", "status": "single_point", "best_similarity": 0.42, "people": [
    {"person": "tristan", "proficiency": 0.6, "evidence": [
        {"source_id": "s1", "at": "2026-10-19T10:00:00+00:00", "similarity": 0.42, "why": PAYROLL_WHY,
         "role": "decided", "task": "Payroll SFTP export retries", "topic": "payroll"}]}]}
PAYROLL_SOURCE = {"person": "tristan", "task": "Payroll SFTP export retries", "at": "2026-10-19T10:00:00+00:00", "why": PAYROLL_WHY}


def fake_claude(monkeypatch, result):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(cmd, 0, stdout=result if isinstance(result, str) else json.dumps({"structured_output": result}))

    monkeypatch.setattr(answer.subprocess, "run", run)
    return calls


def test_compose_answered(monkeypatch):
    calls = fake_claude(monkeypatch, {"answered": True, "text": "tristan: 3 retries.", "sources": [1, 1, 9]})
    out = compose("How many retries does the payroll export do?", LOOKUP)
    assert out == {"answered": True, "text": "tristan: 3 retries.", "sources": [PAYROLL_SOURCE]}
    cmd, kwargs = calls[0]
    assert cmd[:4] == ["claude", "-p", "--model", "haiku"] and "--no-session-persistence" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert kwargs["timeout"] == 25 and kwargs["env"]["RECORDER_CHILD"] == "1"
    assert "<data>" in kwargs["input"] and PAYROLL_WHY.replace('"', '\\"') in kwargs["input"]


def test_compose_not_answered_defaults_to_related(monkeypatch):
    fake_claude(monkeypatch, {"answered": False, "text": "Not recorded yet. Related: ...", "sources": []})
    out = compose("What time does the nightly payroll export start?", LOOKUP)
    assert out["answered"] is False and out["sources"] == [PAYROLL_SOURCE]


@pytest.mark.parametrize("result", ["not json", subprocess.TimeoutExpired("claude", 25), FileNotFoundError("claude"),
                                    {"answered": "yes", "text": "", "sources": []}])
def test_compose_falls_back_to_template(monkeypatch, result):
    fake_claude(monkeypatch, result)
    out = compose("What time does the nightly payroll export start?", LOOKUP)
    assert out["answered"] is False
    assert out["text"].startswith("Not recorded yet. Closest related facts:")
    assert "tristan, 2026-10-19" in out["text"] and out["sources"] == [PAYROLL_SOURCE]


def test_fallback_answers_when_similar_enough(monkeypatch):
    fake_claude(monkeypatch, subprocess.TimeoutExpired("claude", 25))
    out = compose("payroll SFTP export retries", {**LOOKUP, "best_similarity": 0.8})
    assert out["answered"] is True and out["text"].startswith("tristan (2026-10-19")


def test_compose_without_evidence_skips_claude(monkeypatch):
    calls = fake_claude(monkeypatch, {"answered": True, "text": "x", "sources": []})
    out = compose("anything", {"question": "anything", "status": "unknown", "people": [], "best_similarity": 0.0})
    assert out["answered"] is False and out["sources"] == [] and calls == []
