from datetime import datetime, timezone
from pathlib import Path

from knowledge_graph import KnowledgeGraph

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)
REAL_ROWS = Path(__file__).resolve().parents[2] / "wout" / "data" / "signals.json"


def row(i, person, topic="pc-200-indexation", role="decided", at="2026-10-01", why="indexation of wages in joint committee 200"):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": f"s{i}",
            "at": at, "human_role": role, "why": why if role != "accepted_as_is" else None, "actor": "human"}


def test_add_signals_dedupes_on_id_and_survives_reload(tmp_path):
    graph = KnowledgeGraph(tmp_path / "rows.jsonl")
    assert graph.add_signals([row(1, "lies"), row(2, "jan")]) == {"added": 2, "updated": 0, "rejected": []}
    assert graph.add_signals([row(1, "lies", why="changed my mind")])["updated"] == 1

    reloaded = KnowledgeGraph(tmp_path / "rows.jsonl")
    assert len(reloaded.rows()) == 2
    assert {r["why"] for r in reloaded.rows()} >= {"changed my mind"}


def test_invalid_rows_are_rejected_with_a_reason(tmp_path):
    graph = KnowledgeGraph(tmp_path / "rows.jsonl")
    result = graph.add_signals([{"id": "x"}, {**row(1, "lies"), "human_role": "vibes"}])
    assert result["added"] == 0
    assert len(result["rejected"]) == 2
    assert graph.rows() == []


def test_mirror_gets_the_file_after_a_write(tmp_path):
    uploads = []
    graph = KnowledgeGraph(tmp_path / "rows.jsonl", mirror=type("M", (), {"upload": lambda self, p: uploads.append(p)})())
    graph.add_signals([row(1, "lies")])
    assert uploads == [tmp_path / "rows.jsonl"]


def test_risks_use_decay_not_a_fixed_window(tmp_path):
    graph = KnowledgeGraph(tmp_path / "rows.jsonl")
    graph.add_signals([
        row(1, "lies", topic="pay-transparency", at="2026-10-15"),
        row(2, "jan", topic="pay-transparency", at="2026-10-16"),
        row(3, "lies", topic="flexi-jobs", at="2026-10-10"),
        row(4, "jan", topic="mysdworx-login", role="accepted_as_is"),
        row(5, "an", topic="old-payroll-engine", at="2024-01-01"),
    ])
    status = {t["topic"]: t["status"] for t in graph.risks(NOW)}
    assert status == {"pay-transparency": "healthy", "flexi-jobs": "single_point", "mysdworx-login": "dark", "old-payroll-engine": "fading"}


def test_person_view_splits_knowing_from_prompting(tmp_path):
    graph = KnowledgeGraph(tmp_path / "rows.jsonl")
    graph.add_signals([row(1, "lies", topic="flexi-jobs"), row(2, "lies", topic="mysdworx-login", role="accepted_as_is")])
    view = graph.person_view("lies", NOW)
    assert [k["topic"] for k in view["knows"]] == ["flexi-jobs"]
    assert view["knows"][0]["only_you"] is True
    assert view["only_prompts"] == ["mysdworx-login"]
    assert view["reasoned"] == 1 and view["prompted"] == 1


def test_loads_the_real_seed_rows(tmp_path):
    graph = KnowledgeGraph(tmp_path / "rows.jsonl", seed_paths=[REAL_ROWS])
    assert len(graph.rows()) == 51
    assert graph.who_knows("aikido security scan", NOW)["owner"] == "wout"
