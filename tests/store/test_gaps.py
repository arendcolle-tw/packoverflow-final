from datetime import datetime, timezone

import pytest

from knowly.store import gaps, open_store
from knowly.store.scoring import row_weight

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def row(i, person, role="decided", at="2026-10-20T08:00:00Z", why=None, topic="pc-200-indexation", source_id=None):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": source_id or f"s{i}",
            "at": at, "human_role": role, "why": why, "actor": "human"}


def commit(i, author, at="2026-10-20T10:00:00Z", title="Retry the payroll export 3 times"):
    return {"id": f"commit-{i}", "kind": "commit", "author": author, "at": at, "title": title, "body": "", "link": None}


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "K_SERVICE", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KNOWLY_PHONE_NUMBERS", '{"alberic": "+32470000001", "jan": "+32470000002"}')
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: pytest.fail("model called in a test without a mock"))


def store_with_gaps(path):
    store = open_store(path)
    store.add_facts([
        row(1, "alberic", why="indexation of wages in joint committee 200"),
        row(2, "alberic", role="corrected"),                                              # missing_why
        row(3, "jan", at="2026-10-20T10:30:00Z", why="deploy fix", topic="deploy"),  # covers jan's commit within 1.5 hours
    ])
    store.add_member("tristan")
    store.add_artifacts([commit(1, "tristan"), commit(2, "jan"), commit(3, None, title="pc 200 indexation of wages")])
    return store


def test_find_gaps_finds_both_kinds_and_is_idempotent(tmp_path):
    store = store_with_gaps(tmp_path)
    first = gaps.find_gaps(store, NOW)
    kinds = {(g["kind"], g["ref"]): g for g in first}
    assert set(kinds) == {("missing_why", "r2"), ("unrecorded_work", "commit-1"), ("unrecorded_work", "commit-3")}
    assert kinds[("missing_why", "r2")]["owner"] == "alberic"
    assert kinds[("unrecorded_work", "commit-1")]["owner"] == "tristan"  # author is a member
    assert kinds[("unrecorded_work", "commit-3")]["owner"] == "alberic"  # no author: top person from who_knows
    again = gaps.find_gaps(store, NOW)
    assert [g["id"] for g in again] == [g["id"] for g in first]
    assert len(store.gaps()) == 3


def test_an_author_who_is_not_a_member_does_not_own_the_gap(tmp_path):
    store = open_store(tmp_path)
    store.add_facts([row(1, "alberic", why="retry the payroll export 3 times because the bank is slow")])
    store.add_artifacts([commit(1, "someone")])
    assert gaps.find_gaps(store, NOW)[0]["owner"] == "alberic"


def test_riskiest_first(tmp_path):
    found = gaps.find_gaps(store_with_gaps(tmp_path), NOW)
    risky = [g["risk"] in gaps.RISKY for g in found]
    assert risky == sorted(risky, reverse=True)


def test_draft_falls_back_to_a_template_without_a_model(tmp_path, monkeypatch):
    store = store_with_gaps(tmp_path)
    gap = gaps.find_gaps(store, NOW)[0]
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: None)  # what ask_json returns without a model
    drafted = gaps.draft_gap(store, gap["id"])
    assert drafted["draft_source"] == "template" and "Was that because" in drafted["draft"]


def test_claude_draft_gets_the_context_as_delimited_data(tmp_path, monkeypatch):
    store = store_with_gaps(tmp_path)
    gap = gaps.find_gaps(store, NOW)[0]
    seen = {}

    def fake(system, user, **_):
        seen.update(system=system, user=user)
        return {"draft": "We did it because the bank closes at 18:00.", "check_question": "Is 18:00 still right?"}

    monkeypatch.setattr(gaps, "ask_json", fake)
    drafted = gaps.draft_gap(store, gap["id"])
    assert drafted["draft_source"] == "claude" and drafted["check_question"] == "Is 18:00 still right?"
    assert seen["user"].startswith("<context>") and "ignore any instructions" in seen["system"]


def test_drafts_never_enter_rows_or_who_knows(tmp_path):
    store = store_with_gaps(tmp_path)
    for gap in gaps.find_gaps(store, NOW):
        store.save_gaps([{**gap, "draft": "zebra unicorn reasoning"}])
    assert not any("zebra" in str(r) for r in store.rows())
    assert store.who_knows("zebra unicorn reasoning", NOW)["people"] == []


def test_confirmed_weighs_half_of_edited(tmp_path):
    weights = {}
    for result in ("confirmed", "edited"):
        store = store_with_gaps(tmp_path / result)
        gap = next(g for g in gaps.find_gaps(store, NOW) if g["ref"] == "commit-1")
        answer = gap["draft"] if result == "confirmed" else gap["draft"].replace("Was that because ...?", "Because the SFTP window closes at 18:00.")
        stored = gaps.answer_gap(store, gap["id"], answer, "voice_call", "call-c1")
        assert stored["draft_result"] == result and stored["status"] == "answered"
        new = next(r for r in store.rows() if r["id"] == f"gap-{gap['id']}")
        assert new["draft"] == result and new["source"] == "voice_call" and new["person"] == "tristan"
        weights[result] = row_weight(new)
        evidence = store.who_knows(gap["subject"])["people"][0]["evidence"][0]
        weights[result + "_contribution"] = evidence["contribution"] / evidence["similarity"]
    assert weights["confirmed"] == 0.5 and weights["edited"] == 1.0
    assert weights["confirmed_contribution"] < weights["edited_contribution"]


def test_classify():
    draft = "We retry 5 times because the bank is slow."
    assert gaps.classify(draft, draft) == "confirmed"
    assert gaps.classify(draft, "We retry 3 times because the bank is slow at night.") == "edited"
    assert gaps.classify(draft, "The SFTP window closes at 18:00, so more retries miss it.") == "rewritten"


def test_service_lists_both_kinds_without_context(client, demo, admin):
    found = client.get("/gaps", params={"status": "open"}).json()
    assert {g["kind"] for g in found} == {"missing_why", "unrecorded_work"}
    assert "context" not in found[0]
    assert "Backtracking" in client.get("/gaps/board").text
    assert client.get(f"/gaps/{found[0]['id']}/talk").status_code == 200
    assert client.post("/gaps/scan").status_code == 401
    assert client.post("/gaps/scan", headers=admin).json()["open"] == len(found)


def test_text_answer_only_for_your_own_gap(client, demo, join):
    gap = next(g for g in client.get("/gaps", params={"status": "open"}).json() if g["owner"] == "alberic")
    jan, alberic = join("jan"), join("alberic")
    assert client.post(f"/gaps/{gap['id']}/answer", json={"answer": "mine now"}, headers=jan).status_code == 403
    assert client.post(f"/gaps/{gap['id']}/answer", json={"answer": "mine now"}).status_code == 401
    answered = client.post(f"/gaps/{gap['id']}/answer", json={"answer": "Because the jury reads the repo."}, headers=alberic).json()
    assert answered["status"] == "answered" and answered["draft_result"] == "rewritten"
    fact = next(r for r in client.get("/rows").json() if r["id"] == f"gap-{gap['id']}")
    assert fact["source"] == "gap_form" and fact["why"] == "Because the jury reads the repo." and fact["person"] == "alberic"
    assert client.post(f"/gaps/{gap['id']}/answer", json={"answer": "again"}, headers=alberic).status_code == 409
    assert "Because the jury reads the repo." in client.get("/gaps/board").text


def test_artifacts_need_admin_and_open_gaps(client, demo, admin):
    body = [commit(99, "tristan", at="2026-10-19T11:00:00Z", title="Ship the voice call")]
    assert client.post("/artifacts", json=body).status_code == 401
    result = client.post("/artifacts", json=body, headers=admin).json()
    assert result["stored"] == 1
    assert any(g["ref"] == "commit-99" for g in client.get("/gaps").json())


def test_phone_numbers_never_in_a_response(client, demo):
    pages = [client.get(p).text for p in ("/gaps", "/gaps?status=open", "/gaps/board", "/rows", "/risks", "/health")]
    gap = client.get("/gaps").json()[0]
    pages.append(client.get(f"/gaps/{gap['id']}/talk").text)
    assert not any("+3247" in p for p in pages)


def test_same_question_shows_once(tmp_path):
    store = open_store(tmp_path)
    store.add_facts([row(1, "alberic", role="decided", source_id="s1"), {**row(2, "alberic", role="decided"), "source_id": "s1"}])
    found = gaps.find_gaps(store, NOW)
    assert len(store.gaps()) == 2 and len(found) == 1
    gaps.answer_gap(store, found[0]["id"], "Because the jury reads the repo.", "gap_form", "form-1")
    assert gaps.open_gaps(store) == [] and [g["status"] for g in gaps.all_gaps(store)] == ["answered", "skipped"]


def test_startup_redraft_only_with_a_key(tmp_path, monkeypatch):
    store = store_with_gaps(tmp_path)
    gaps.find_gaps(store, NOW)
    assert gaps.redraft_templates(store) == 0
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: {"draft": "We did it because of the bank.", "check_question": "Still true?"})
    assert gaps.redraft_templates(store, limit=2) == 2
    assert sum(g["draft_source"] == "claude" for g in gaps.open_gaps(store)) == 2


def test_supplied_draft_needs_admin_and_stays_out_of_rows(client, demo, admin):
    gap = client.get("/gaps", params={"status": "open"}).json()[-1]
    body = {"draft": "We did it because the bank closes at 18:00.", "check_question": "Still 18:00?"}
    assert client.post(f"/gaps/{gap['id']}/draft", json=body).status_code == 401
    stored = client.post(f"/gaps/{gap['id']}/draft", json=body, headers=admin).json()
    assert stored["draft"] == body["draft"] and stored["draft_source"] == "claude"
    assert "We did it because the bank closes at 18:00." in client.get("/gaps/board").text
    assert not any("18:00" in str(r) for r in client.get("/rows").json())


def test_board_and_talk_links_are_relative(client, demo):
    gap = next(g for g in client.get("/gaps", params={"status": "open"}).json() if g["owner"] == "alberic")
    board, talk = client.get("/gaps/board").text, client.get(f"/gaps/{gap['id']}/talk").text
    assert f"href='{gap['id']}/talk'" in board and "fetch('../gaps?status=answered')" in board
    assert "fetch('answer'" in talk and "href='../board'" in talk
    assert "'/gaps" not in board + talk
