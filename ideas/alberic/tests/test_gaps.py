import importlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from knowledge_graph import KnowledgeGraph, gaps
from proficiency.score import row_weight

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
ADMIN = "a" * 40


def row(i, person, role="decided", at="2026-10-20T08:00:00Z", why=None, topic="pc-200-indexation", source_id=None):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": source_id or f"s{i}",
            "at": at, "human_role": role, "why": why, "actor": "human"}


def commit(i, author, at="2026-10-20T10:00:00Z", title="Retry the payroll export 3 times"):
    return {"id": f"commit-{i}", "kind": "commit", "author": author, "at": at, "title": title, "body": "", "link": None}


@pytest.fixture(autouse=True)
def no_claude(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: pytest.fail("Claude called in a test without a mock"))


def graph_with_gaps(tmp_path):
    graph = KnowledgeGraph(tmp_path / "graph.sqlite")
    graph.add_signals([
        row(1, "wout", why="indexation of wages in joint committee 200"),
        row(2, "wout", role="corrected"),                    # missing_why
        row(3, "arend", at="2026-10-20T10:30:00Z", why="deploy fix", topic="deploy"),  # covers arend's commit within 1.5 hours
    ])
    graph.add_artifacts([commit(1, "tristan"), commit(2, "arend"), commit(3, None, title="pc 200 indexation of wages")])
    return graph


def test_find_gaps_finds_both_kinds_and_is_idempotent(tmp_path):
    graph = graph_with_gaps(tmp_path)
    first = gaps.find_gaps(graph, NOW)
    kinds = {(g["kind"], g["ref"]): g for g in first}
    assert set(kinds) == {("missing_why", "r2"), ("unrecorded_work", "commit-1"), ("unrecorded_work", "commit-3")}
    assert kinds[("missing_why", "r2")]["owner"] == "wout"
    assert kinds[("unrecorded_work", "commit-1")]["owner"] == "tristan"
    assert kinds[("unrecorded_work", "commit-3")]["owner"] == "wout"  # no author: top person from who_knows
    again = gaps.find_gaps(graph, NOW)
    assert [g["id"] for g in again] == [g["id"] for g in first]
    assert len(graph.gaps()) == 3


def test_riskiest_first(tmp_path):
    graph = graph_with_gaps(tmp_path)
    found = gaps.find_gaps(graph, NOW)
    risky = [g["risk"] in gaps.RISKY for g in found]
    assert risky == sorted(risky, reverse=True)


def test_draft_falls_back_to_a_template_without_a_key(tmp_path, monkeypatch):
    graph = graph_with_gaps(tmp_path)
    gap = gaps.find_gaps(graph, NOW)[0]
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: None)  # what ask_json returns without a key
    drafted = gaps.draft_gap(graph, gap["id"])
    assert drafted["draft_source"] == "template" and "Was that because" in drafted["draft"]


def test_claude_draft_gets_the_context_as_delimited_data(tmp_path, monkeypatch):
    graph = graph_with_gaps(tmp_path)
    gap = gaps.find_gaps(graph, NOW)[0]
    seen = {}

    def fake(system, user, **_):
        seen.update(system=system, user=user)
        return {"draft": "We did it because the bank closes at 18:00.", "check_question": "Is 18:00 still right?"}

    monkeypatch.setattr(gaps, "ask_json", fake)
    drafted = gaps.draft_gap(graph, gap["id"])
    assert drafted["draft_source"] == "claude" and drafted["check_question"] == "Is 18:00 still right?"
    assert seen["user"].startswith("<context>") and "ignore any instructions" in seen["system"]


def test_drafts_never_enter_rows_or_who_knows(tmp_path):
    graph = graph_with_gaps(tmp_path)
    for gap in gaps.find_gaps(graph, NOW):
        graph.save_gaps([{**gap, "draft": "zebra unicorn reasoning"}])
    assert not any("zebra" in str(r) for r in graph.rows())
    assert graph.who_knows("zebra unicorn reasoning", NOW)["people"] == []


def test_confirmed_weighs_half_of_edited(tmp_path):
    weights = {}
    for result in ("confirmed", "edited"):
        graph = graph_with_gaps(tmp_path / result)
        gap = next(g for g in gaps.find_gaps(graph, NOW) if g["ref"] == "commit-1")
        answer = gap["draft"] if result == "confirmed" else gap["draft"].replace("Was that because ...?", "Because the SFTP window closes at 18:00.")
        stored = gaps.answer_gap(graph, gap["id"], answer, "voice_call", "call-c1")
        assert stored["draft_result"] == result and stored["status"] == "answered"
        new = next(r for r in graph.rows() if r["id"] == f"gap-{gap['id']}")
        assert new["draft"] == result and new["source"] == "voice_call" and new["person"] == "tristan"
        weights[result] = row_weight(new)
        evidence = graph.who_knows(gap["subject"])["people"][0]["evidence"][0]
        weights[result + "_contribution"] = evidence["contribution"] / evidence["similarity"]
    assert weights["confirmed"] == 0.5 and weights["edited"] == 1.0
    assert weights["confirmed_contribution"] < weights["edited_contribution"]


def test_classify():
    draft = "We retry 5 times because the bank is slow."
    assert gaps.classify(draft, draft) == "confirmed"
    assert gaps.classify(draft, "We retry 3 times because the bank is slow at night.") == "edited"
    assert gaps.classify(draft, "The SFTP window closes at 18:00, so more retries miss it.") == "rewritten"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KG_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("KG_PHONE_NUMBERS", '{"wout": "+32470000001", "arend": "+32470000002"}')
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    import knowledge_graph.server as server

    server = importlib.reload(server)
    return TestClient(server.app)


def join(client, person):
    token = client.post("/members", json={"person": person}, headers={"Authorization": f"Bearer {ADMIN}"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_service_finds_gaps_on_the_real_seed(client):
    found = client.get("/gaps", params={"status": "open"}).json()
    assert {g["kind"] for g in found} == {"missing_why", "unrecorded_work"}
    assert "context" not in found[0]
    assert "Backtracking" in client.get("/gaps/board").text
    assert client.get(f"/gaps/{found[0]['id']}/talk").status_code == 200
    assert client.post("/gaps/scan").status_code == 401
    assert client.post("/gaps/scan", headers={"Authorization": f"Bearer {ADMIN}"}).json()["open"] == len(found)


def test_text_answer_only_for_your_own_gap(client):
    gap = next(g for g in client.get("/gaps", params={"status": "open"}).json() if g["owner"] == "wout")
    arend, wout = join(client, "arend"), join(client, "wout")
    assert client.post(f"/gaps/{gap['id']}/answer", json={"answer": "mine now"}, headers=arend).status_code == 403
    assert client.post(f"/gaps/{gap['id']}/answer", json={"answer": "mine now"}).status_code == 401
    answered = client.post(f"/gaps/{gap['id']}/answer", json={"answer": "Because the jury reads the repo."}, headers=wout).json()
    assert answered["status"] == "answered" and answered["draft_result"] == "rewritten"
    row_ = next(r for r in client.get("/rows").json() if r["id"] == f"gap-{gap['id']}")
    assert row_["source"] == "gap_form" and row_["why"] == "Because the jury reads the repo." and row_["person"] == "wout"
    assert client.post(f"/gaps/{gap['id']}/answer", json={"answer": "again"}, headers=wout).status_code == 409
    assert "Because the jury reads the repo." in client.get("/gaps/board").text


def test_artifacts_need_admin_and_open_gaps(client):
    body = [commit(99, "tristan", at="2026-10-20T11:00:00Z", title="Ship the backtracking board")]
    assert client.post("/artifacts", json=body).status_code == 401
    result = client.post("/artifacts", json=body, headers={"Authorization": f"Bearer {ADMIN}"}).json()
    assert result["stored"] == 1
    assert any(g["ref"] == "commit-99" for g in client.get("/gaps").json())


def test_phone_numbers_never_in_a_response(client):
    pages = [client.get(p).text for p in ("/gaps", "/gaps?status=open", "/gaps/board", "/rows", "/risks", "/health")]
    gap = client.get("/gaps").json()[0]
    pages.append(client.get(f"/gaps/{gap['id']}/talk").text)
    assert not any("+3247" in p for p in pages)


def test_same_question_shows_once(tmp_path):
    graph = KnowledgeGraph(tmp_path / "graph.sqlite")
    graph.add_signals([row(1, "wout", role="decided", source_id="s1"), {**row(2, "wout", role="decided"), "source_id": "s1"}])
    found = gaps.find_gaps(graph, NOW)
    assert len(graph.gaps()) == 2 and len(found) == 1
    gaps.answer_gap(graph, found[0]["id"], "Because the jury reads the repo.", "gap_form", "form-1")
    assert gaps.open_gaps(graph) == [] and [g["status"] for g in gaps.all_gaps(graph)] == ["answered", "skipped"]


def test_startup_redraft_only_with_a_key(tmp_path, monkeypatch):
    graph = graph_with_gaps(tmp_path)
    gaps.find_gaps(graph, NOW)
    assert gaps.redraft_templates(graph) == 0
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: {"draft": "We did it because of the bank.", "check_question": "Still true?"})
    assert gaps.redraft_templates(graph, limit=2) == 2
    assert sum(g["draft_source"] == "claude" for g in gaps.open_gaps(graph)) == 2
