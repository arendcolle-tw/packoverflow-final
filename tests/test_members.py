import io
import json
import stat
import threading
import time
import urllib.error

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowly import client
from knowly.client import StoreError
from knowly.members import Members

ROOT = "http://knowly.test"
ADMIN = "-admin-token-" + "x" * 40
QUESTION = "What time does the nightly payroll export start?"
ANSWER = "16:00, so three retries still finish before the bank closes the SFTP window at 18:00."
REQUIRED = ("id", "person", "topic", "source", "source_id", "at", "human_role", "actor")


class FakeStore:
    """POST /store/members and POST /store/facts. Tokens start with '-' like real ones can."""

    def __init__(self):
        self.members: dict[str, str] = {}
        self.rows: list[dict] = []
        self.member_calls = 0
        self.delay = 0.0

    def __call__(self, request, timeout=None):
        path, body = request.full_url.removeprefix(ROOT), json.loads(request.data)
        token = request.headers["Authorization"].removeprefix("Bearer ")
        if path == "/store/members":
            assert token == ADMIN
            self.member_calls += 1
            time.sleep(self.delay)
            self.members[f"-tok{self.member_calls}"] = body["person"]
            return io.BytesIO(json.dumps({"person": body["person"], "token": f"-tok{self.member_calls}"}).encode())
        assert path == "/store/facts"
        person = self.members.get(token)
        if person is None:
            raise urllib.error.HTTPError(request.full_url, 401, "unknown member token", {}, io.BytesIO(b""))
        rejected = [f"row {i}: empty field" for i, row in enumerate(body) if not all(row.get(k) for k in REQUIRED)]
        self.rows += [{**row, "person": person} for row in body if all(row.get(k) for k in REQUIRED)]
        return io.BytesIO(json.dumps({"added": len(body) - len(rejected), "updated": 0, "rejected": rejected}).encode())


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(client.urllib.request, "urlopen", store)
    return store, Members(f"{ROOT}/store/", ADMIN, tmp_path / "state" / "member_tokens.json")


def test_token_created_once_and_reused(setup, tmp_path):
    store, members = setup
    token = members.token_for("tristan")
    assert token.startswith("-")
    assert members.token_for("tristan") == token
    assert Members(f"{ROOT}/store", ADMIN, tmp_path / "state" / "member_tokens.json").token_for("tristan") == token
    assert store.member_calls == 1
    assert json.loads((tmp_path / "state" / "member_tokens.json").read_text()) == {"tristan": token}


def test_tokens_file_is_mode_600(setup, tmp_path):
    _, members = setup
    members.token_for("tristan")
    members.token_for("alberic")
    path = tmp_path / "state" / "member_tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert set(json.loads(path.read_text())) == {"tristan", "alberic"}
    assert not list(path.parent.glob(".tokens-*"))


def test_concurrent_calls_create_one_member(setup):
    store, members = setup
    store.delay = 0.05
    results = []
    threads = [threading.Thread(target=lambda: results.append(members.token_for("alberic"))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.member_calls == 1
    assert len(set(results)) == 1 and len(results) == 8


def test_missing_admin_token_is_reported(tmp_path, setup):
    store, _ = setup
    with pytest.raises(RuntimeError, match="KNOWLY_ADMIN_TOKEN"):
        Members(f"{ROOT}/store", "", tmp_path / "tokens.json").token_for("tristan")
    assert store.member_calls == 0


def test_store_fact_posts_one_answered_question_row(setup):
    store, members = setup
    row = members.store_fact("tristan", QUESTION, ANSWER, "payroll-export-schedule", "1729440000.123456")
    assert row["id"] == "question:1729440000.123456:tristan"
    assert row["source_id"] == "question-1729440000.123456"
    assert (row["source"], row["human_role"], row["actor"]) == ("gap_form", "answered_question", "human")
    assert row["why"] == ANSWER and row["task"] == QUESTION
    assert row["at"].endswith("+00:00")
    assert store.rows == [row]


def test_store_fact_truncates_long_text(setup):
    _, members = setup
    row = members.store_fact("tristan", "q" * 300, "f" * 300, "topic", "1.2")
    assert len(row["why"]) == 200 and len(row["task"]) == 80


def test_store_fact_raises_on_rejected(setup):
    _, members = setup
    with pytest.raises(StoreError, match="rejected"):
        members.store_fact("tristan", QUESTION, ANSWER, "", "1.2")


def test_store_fact_replaces_a_stale_token(setup, tmp_path):
    store, members = setup
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "member_tokens.json").write_text(json.dumps({"tristan": "-from-an-old-store"}))
    row = members.store_fact("tristan", QUESTION, ANSWER, "payroll-export-schedule", "1.2")
    assert store.member_calls == 1 and store.rows == [row]
    assert json.loads((tmp_path / "state" / "member_tokens.json").read_text())["tristan"] == "-tok1"


def test_store_fact_against_the_real_store_routes(tmp_path, monkeypatch):
    store_mod = pytest.importorskip("knowly.store")
    facts = store_mod.open_store(tmp_path / "data", None)
    app = FastAPI()
    app.include_router(store_mod.build_router(facts, ADMIN), prefix="/store")
    http = TestClient(app)

    def urlopen(request, timeout=None):
        response = http.request(request.get_method(), request.full_url.removeprefix(ROOT), content=request.data,
                                headers=dict(request.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, response.text, {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    tokens = tmp_path / "member_tokens.json"
    tokens.write_text(json.dumps({"tristan": "-from-an-old-store"}))
    members = Members(f"{ROOT}/store", ADMIN, tokens)

    row = members.store_fact("tristan", QUESTION, ANSWER, "payroll-export-schedule", "1729440000.123456")
    long = members.store_fact("tristan", "q" * 300, "f" * 300, "topic", "1.2")

    stored = {r["id"]: r for r in facts.rows()}
    assert stored[row["id"]] == row and stored[long["id"]] == long
    assert json.loads(tokens.read_text())["tristan"] != "-from-an-old-store"
    with pytest.raises(StoreError, match="rejected"):
        members.store_fact("tristan", QUESTION, ANSWER, "", "1.3")
