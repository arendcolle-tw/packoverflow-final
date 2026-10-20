import json
import sqlite3
from datetime import datetime, timezone

from knowledge_graph import KnowledgeGraph

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def row(i, person, topic="pc-200-indexation", role="decided", at="2026-10-01", why="indexation of wages in joint committee 200"):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": f"s{i}",
            "at": at, "human_role": role, "why": why if role != "accepted_as_is" else None, "actor": "human"}


def test_sqlite_survives_a_reload(tmp_path):
    graph = KnowledgeGraph(tmp_path / "graph.sqlite")
    graph.add_signals([row(1, "lies"), row(2, "jan")])
    token = graph.add_member("lies")

    reloaded = KnowledgeGraph(tmp_path / "graph.sqlite")
    assert {r["id"] for r in reloaded.rows()} == {"r1", "r2"}
    assert reloaded.member(token) == "lies"
    assert sqlite3.connect(tmp_path / "graph.sqlite").execute("SELECT count(*) FROM signals").fetchone() == (2,)


def test_jsonl_file_is_imported_once(tmp_path):
    path = tmp_path / "graph.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [row(1, "lies"), row(1, "lies", why="later line wins"), row(2, "jan")]) + "\nnot json\n")

    graph = KnowledgeGraph(path)
    assert len(graph.rows()) == 2
    assert next(r for r in graph.rows() if r["id"] == "r1")["why"] == "later line wins"
    assert (tmp_path / "graph.jsonl.imported").exists()

    graph.add_signals([row(3, "an")])
    assert len(KnowledgeGraph(path).rows()) == 3


def test_seed_fills_an_empty_database_without_overwriting(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([row(1, "lies", why="seeded")]))
    graph = KnowledgeGraph(tmp_path / "graph.sqlite", seed_paths=[seed])
    graph.add_signals([row(1, "lies", why="edited")])
    assert KnowledgeGraph(tmp_path / "graph.sqlite", seed_paths=[seed]).rows()[0]["why"] == "edited"


def test_missing_file_is_restored_from_the_mirror(tmp_path):
    KnowledgeGraph(tmp_path / "old.sqlite").add_signals([row(1, "lies")])

    class Mirror:
        def upload(self, path):
            pass

        def download(self, path):
            path.write_bytes((tmp_path / "old.sqlite").read_bytes())

    assert len(KnowledgeGraph(tmp_path / "new" / "graph.sqlite", mirror=Mirror()).rows()) == 1


def test_new_sources_and_optional_fields(tmp_path):
    graph = KnowledgeGraph(tmp_path / "graph.sqlite")
    rows = [{**row(i, "lies"), "source": s} for i, s in enumerate(
        ["meeting", "copilot_chat", "copilot_cli", "m365_copilot", "screenshot", "mcp_record"])]
    rows.append({**row(9, "lies", role="answered_question"), "task": "set up the aikido scan", "app": "Terminal", "extra": "dropped"})
    assert graph.add_signals(rows)["added"] == 7
    stored = next(r for r in graph.rows() if r["id"] == "r9")
    assert stored["task"] == "set up the aikido scan" and stored["app"] == "Terminal" and "extra" not in stored
    no_why = {k: v for k, v in row(10, "lies").items() if k != "why"}
    assert graph.add_signals([no_why])["added"] == 1


def test_length_limits(tmp_path):
    graph = KnowledgeGraph(tmp_path / "graph.sqlite")
    result = graph.add_signals([
        row(1, "lies", why="x" * 201),
        {**row(2, "lies"), "task": "x" * 81},
        {**row(3, "lies"), "app": "x" * 301},
        {**row(4, "lies"), "topic": "x" * 301},
        {**row(5, "lies"), "source": "slack"},
        {**row(6, "lies"), "task": 5},
        {**row(7, "lies"), "why": "x" * 200, "task": "x" * 80, "app": "x" * 300},
    ])
    assert result["added"] == 1
    assert len(result["rejected"]) == 6


def test_another_person_cannot_overwrite_a_row(tmp_path):
    graph = KnowledgeGraph(tmp_path / "graph.sqlite")
    graph.add_signals([row(1, "lies", why="mine")], person="lies")
    result = graph.add_signals([row(1, "lies", why="hijacked")], person="jan")
    assert result["added"] == result["updated"] == 0
    assert result["rejected"] == ["row 0: id belongs to someone else"]
    assert graph.rows()[0]["why"] == "mine" and graph.rows()[0]["person"] == "lies"


def test_rows_under_a_colleagues_session_do_not_change_their_task(tmp_path):
    graph = KnowledgeGraph(tmp_path / "graph.sqlite")
    graph.add_signals([row(1, "lies")], person="lies")
    before = graph.who_knows("indexation of wages in joint committee 200", NOW)
    graph.add_signals([{**row(2, "jan", role="accepted_as_is"), "source_id": "s1"}] * 3, person="jan")
    after = graph.who_knows("indexation of wages in joint committee 200", NOW)
    assert [p["person"] for p in after["people"] if p["evidence"]] == ["lies"]
    assert after["people"][0]["proficiency"] == before["people"][0]["proficiency"]
