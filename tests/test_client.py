import io
import json
import urllib.error

import pytest

from knowly import client as client_mod
from knowly.client import StoreClient, StoreError

BASE = "https://knowly.test/store"
PAYROLL_WHY = 'Chose 3 retries over 5 "because the bank closes the SFTP window at 18:00"'
WHO_KNOWS = {
    "query": "payroll export", "status": "single_point", "owner": "tristan", "similar_tasks": 1,
    "people": [
        {"person": "tristan", "proficiency": 0.6, "evidence": [
            {"source_id": "s1", "at": "2026-10-19T10:00:00+00:00", "similarity": 0.42, "takeover": 1.0, "contribution": 0.4,
             "whys": [{"role": "decided", "why": PAYROLL_WHY}]},
        ]},
        {"person": "alberic", "proficiency": 0.0, "evidence": []},
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
        path = request.full_url.removeprefix(BASE)
        self.calls.append((request.get_method(), path, request.headers, request.data))
        reply = self.routes[path.split("?")[0]]
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())


@pytest.fixture
def http(monkeypatch):
    fake = FakeHttp({"/who_knows": WHO_KNOWS, "/rows": ROWS, "/facts": {"added": 1, "updated": 0, "rejected": []},
                     "/members": {"person": "tristan", "token": "member-token"}})
    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake)
    return fake


def test_lookup_flattens_evidence_and_caches_rows(http):
    store = StoreClient(BASE + "/")
    found = store.lookup("When does the payroll export start?")
    assert found["status"] == "single_point"
    assert found["best_similarity"] == 0.42
    assert found["people"] == [{"person": "tristan", "proficiency": 0.6, "evidence": [
        {"source_id": "s1", "at": "2026-10-19T10:00:00+00:00", "similarity": 0.42, "why": PAYROLL_WHY,
         "role": "decided", "task": "Payroll SFTP export retries", "topic": "payroll"}]}]
    assert "q=When+does+the+payroll" in http.calls[0][1]

    store.lookup("again")
    assert [c[1] for c in http.calls].count("/rows") == 1
    store.invalidate()
    store.lookup("again")
    assert [c[1] for c in http.calls].count("/rows") == 2


def test_lookup_task_matches_grouped_source_ids(http):
    http.routes["/rows"] = [{**ROWS[0], "id": "question:q1:tristan", "source_id": "question:q1", "task": "When does it start?"}]
    http.routes["/who_knows"] = {**WHO_KNOWS, "people": [{**WHO_KNOWS["people"][0], "evidence": [
        {**WHO_KNOWS["people"][0]["evidence"][0], "source_id": "question"}]}]}
    assert StoreClient(BASE).lookup("x")["people"][0]["evidence"][0]["task"] == "When does it start?"


def test_post_facts_sends_bearer_and_drops_cache(http):
    store = StoreClient(BASE)
    store.rows()
    assert store.post_facts(ROWS, "tok") == {"added": 1, "updated": 0, "rejected": []}
    method, path, headers, body = http.calls[-1]
    assert (method, path, headers["Authorization"]) == ("POST", "/facts", "Bearer tok")
    assert json.loads(body) == ROWS
    store.rows()
    assert [c[1] for c in http.calls].count("/rows") == 2


def test_post_facts_raises_on_rejected_rows(http):
    http.routes["/facts"] = {"added": 0, "updated": 0, "rejected": ["row 0: why longer than 200 characters"]}
    with pytest.raises(StoreError, match="why longer"):
        StoreClient(BASE).post_facts(ROWS, "tok")


def test_create_member_uses_the_admin_token(http):
    assert StoreClient(BASE).create_member("tristan", "admin-token") == "member-token"
    method, path, headers, body = http.calls[-1]
    assert (method, path, headers["Authorization"], json.loads(body)) == (
        "POST", "/members", "Bearer admin-token", {"person": "tristan"})


@pytest.mark.parametrize("error, status", [
    (urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"unknown member token")), 401),
    (urllib.error.URLError("connection refused"), None),
])
def test_http_failures_raise_store_error_with_the_status(http, error, status):
    http.routes["/facts"] = error
    with pytest.raises(StoreError) as raised:
        StoreClient(BASE).post_facts(ROWS, "tok")
    assert raised.value.status == status


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://knowly.example", "https://user:pw@knowly.example", "ftp://knowly.example"])
def test_refuses_unsafe_store_urls(url):
    with pytest.raises(ValueError):
        StoreClient(url)
