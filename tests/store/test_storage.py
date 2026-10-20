import sqlite3
from datetime import datetime, timezone

from knowly.store import FactStore, facts, open_store

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def row(i, person, topic="pc-200-indexation", role="decided", at="2026-10-01", why="indexation of wages in joint committee 200"):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": f"s{i}",
            "at": at, "human_role": role, "why": why if role != "accepted_as_is" else None, "actor": "human"}


def test_sqlite_survives_a_reload(tmp_path):
    store = open_store(tmp_path)
    store.add_facts([row(1, "alberic"), row(2, "jan")])
    token = store.add_member("alberic")

    reloaded = open_store(tmp_path)
    assert {r["id"] for r in reloaded.rows()} == {"r1", "r2"}
    assert reloaded.member(token) == "alberic"
    assert sqlite3.connect(tmp_path / "facts.sqlite").execute("SELECT count(*) FROM facts").fetchone() == (2,)


def test_bucket_mirror_with_a_local_fallback(tmp_path, monkeypatch):
    class Mirror:
        def __init__(self, bucket):
            self.bucket = bucket

        def upload(self, path):
            pass

    monkeypatch.setattr(facts, "GcsMirror", Mirror)
    assert open_store(tmp_path, "knowly-facts").mirror.bucket == "knowly-facts"
    assert open_store(tmp_path).mirror is None

    def unavailable(bucket):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(facts, "GcsMirror", unavailable)
    assert open_store(tmp_path, "knowly-facts").mirror is None


def test_missing_file_is_restored_from_the_mirror(tmp_path):
    FactStore(tmp_path / "old.sqlite").add_facts([row(1, "alberic")])

    class Mirror:
        def upload(self, path):
            pass

        def download(self, path):
            path.write_bytes((tmp_path / "old.sqlite").read_bytes())

    assert len(FactStore(tmp_path / "new" / "facts.sqlite", mirror=Mirror()).rows()) == 1


def test_sources_and_optional_fields(tmp_path):
    store = open_store(tmp_path)
    rows = [{**row(i, "alberic"), "source": s} for i, s in enumerate(
        ["meeting", "copilot_chat", "copilot_cli", "m365_copilot", "screenshot", "mcp_record", "slack_thread"])]
    rows.append({**row(9, "alberic", role="answered_question"), "task": "set up the aikido scan", "app": "Terminal", "extra": "dropped"})
    assert store.add_facts(rows)["added"] == 8
    stored = next(r for r in store.rows() if r["id"] == "r9")
    assert stored["task"] == "set up the aikido scan" and stored["app"] == "Terminal" and "extra" not in stored
    no_why = {k: v for k, v in row(10, "alberic").items() if k != "why"}
    assert store.add_facts([no_why])["added"] == 1


def test_length_limits(tmp_path):
    store = open_store(tmp_path)
    result = store.add_facts([
        row(1, "alberic", why="x" * 201),
        {**row(2, "alberic"), "task": "x" * 81},
        {**row(3, "alberic"), "app": "x" * 301},
        {**row(4, "alberic"), "topic": "x" * 301},
        {**row(5, "alberic"), "source": "slack"},
        {**row(6, "alberic"), "task": 5},
        {**row(7, "alberic"), "why": "x" * 200, "task": "x" * 80, "app": "x" * 300},
    ])
    assert result["added"] == 1
    assert len(result["rejected"]) == 6


def test_another_person_cannot_overwrite_a_fact(tmp_path):
    store = open_store(tmp_path)
    store.add_facts([row(1, "alberic", why="mine")], person="alberic")
    result = store.add_facts([row(1, "alberic", why="hijacked")], person="jan")
    assert result["added"] == result["updated"] == 0
    assert result["rejected"] == ["row 0: id belongs to someone else"]
    assert store.rows()[0]["why"] == "mine" and store.rows()[0]["person"] == "alberic"


def test_facts_under_a_colleagues_session_do_not_change_their_task(tmp_path):
    store = open_store(tmp_path)
    store.add_facts([row(1, "alberic")], person="alberic")
    before = store.who_knows("indexation of wages in joint committee 200", NOW)
    store.add_facts([{**row(2, "jan", role="accepted_as_is"), "source_id": "s1"}] * 3, person="jan")
    after = store.who_knows("indexation of wages in joint committee 200", NOW)
    assert [p["person"] for p in after["people"] if p["evidence"]] == ["alberic"]
    assert after["people"][0]["proficiency"] == before["people"][0]["proficiency"]
