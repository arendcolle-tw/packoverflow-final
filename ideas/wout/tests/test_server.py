from pathlib import Path

from conftest import CODE

import pytest
from fastapi.testclient import TestClient

from tests.helpers import row, write


@pytest.fixture
def client(tmp_path, monkeypatch):
    signals = write(tmp_path, "signals.json", [
        row(human_role="accepted_as_is", at="2026-10-20T09:00:00Z"),
        row(why="<script>alert(1)</script>", at="2026-10-20T10:00:00Z"),
    ])
    monkeypatch.setenv("KC_SIGNALS", str(signals))
    monkeypatch.setenv("KC_ALIASES", str(tmp_path / "none.json"))
    monkeypatch.setenv("KC_WHYS", str(tmp_path / "whys.json"))
    monkeypatch.setenv("KC_DATA_DIR", str(tmp_path / "live"))
    from knowledge_clock.server import app
    return TestClient(app)


def test_summary_and_topics(client):
    s = client.get("/api/summary").json()
    assert s["ai_count"] == 1 and s["human_count"] == 1 and s["skipped"] == 0
    assert s["now"] == "2026-10-20T14:15:00+00:00"
    assert [t["topic"] for t in client.get("/api/topics").json()] == ["aikido"]


def test_detail_404_and_raw_why(client):
    assert client.get("/api/topics/nope").status_code == 404
    assert client.get("/api/topics/aikido").json()["signals"][0]["why"] == "<script>alert(1)</script>"


def test_page_never_injects_html(client):
    html = (Path(__file__).parents[1] / "knowledge_clock/static/index.html").read_text()
    assert "innerHTML" not in html and "/api/summary" in html
    assert client.get("/").status_code == 200


@pytest.fixture
def qclient(tmp_path, monkeypatch):
    signals = write(tmp_path, "signals.json", [
        row(id="s2:q1", source_id="s2", topic="slack-bot", human_role="corrected", why=None),
        row(id="s2:q2", source_id="s2", topic="slack-bot", human_role="decided", why="already said"),
        row(id="s2:q3", source_id="s2", topic="slack-bot", human_role="accepted_as_is", why=None),
        row(id="s2:q4", source_id="s2", topic="slack-bot", human_role="decided", why=None, actor="unknown"),
    ])
    monkeypatch.setenv("KC_SIGNALS", str(signals))
    monkeypatch.setenv("KC_ALIASES", str(tmp_path / "none.json"))
    monkeypatch.setenv("KC_WHYS", str(tmp_path / "whys.json"))
    monkeypatch.setenv("KC_DATA_DIR", str(tmp_path / "live"))
    from knowledge_clock.server import app
    client = TestClient(app)
    token = client.post("/api/join", json={"name": "wout", "code": CODE}).json()["url"].split("/u/")[1].split("/")[0]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_why_needs_the_owners_token(qclient):
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "x"}, headers={"Authorization": ""}).status_code == 401
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "x"}, headers={"Authorization": "Bearer nope"}).status_code == 401
    other = qclient.post("/api/join", json={"name": "tristan", "code": CODE}).json()["url"].split("/u/")[1].split("/")[0]
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "x"}, headers={"Authorization": f"Bearer {other}"}).status_code == 404


def test_join_refuses_a_taken_name_a_bad_code_and_odd_names(qclient):
    assert qclient.post("/api/join", json={"name": "Wout", "code": CODE}).status_code == 409
    assert qclient.post("/api/join", json={"name": "jan", "code": "wrong"}).status_code == 403
    assert qclient.post("/api/join", json={"name": "<script>", "code": CODE}).status_code == 422


def test_questions_list_only_unexplained_human_decisions(qclient):
    assert [q["id"] for q in qclient.get("/api/questions").json()] == ["s2:q1"]
    other = qclient.post("/api/join", json={"name": "tristan", "code": CODE}).json()["url"].split("/u/")[1].split("/")[0]
    assert qclient.get("/api/questions", headers={"Authorization": f"Bearer {other}"}).json() == []
    assert qclient.get("/api/questions", headers={"Authorization": ""}).status_code == 401


def test_answering_removes_question_and_shows_why(qclient):
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "the bot posts twice otherwise"}).status_code == 204
    assert qclient.get("/api/questions").json() == []
    whys = [s["why"] for s in qclient.get("/api/topics/slack-bot").json()["signals"]]
    assert "the bot posts twice otherwise" in whys


def test_why_validation(qclient):
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "   "}).status_code == 422
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "x" * 201}).status_code == 422
    assert qclient.post("/api/why", json={"id": "nope", "why": "because"}).status_code == 404


def test_why_only_for_open_questions(qclient):
    assert qclient.post("/api/why", json={"id": "s2:q2", "why": "overwrite"}).status_code == 404
    assert qclient.post("/api/why", json={"id": "s2:q3", "why": "for an AI row"}).status_code == 404
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "first"}).status_code == 204
    assert qclient.post("/api/why", json={"id": "s2:q1", "why": "second"}).status_code == 404
    whys = [s["why"] for s in qclient.get("/api/topics/slack-bot").json()["signals"]]
    assert "already said" in whys and "first" in whys and "overwrite" not in whys
