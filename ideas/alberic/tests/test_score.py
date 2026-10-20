from datetime import datetime, timezone

from proficiency.score import who_knows

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def row(person, session, at, role="decided", actor="human", why="indexation of wages in joint committee 200"):
    return {"person": person, "source_id": session, "at": at, "human_role": role, "actor": actor, "why": why, "topic": "payroll"}


QUERY = "how do we apply the wage indexation for joint committee 200"


def test_only_human_reasoning_counts():
    signals = [row("lies", "s1", "2026-10-01", role="accepted_as_is"), row("jan", "s2", "2026-10-01", actor="agent")]
    result = who_knows(QUERY, signals, NOW)
    assert result["status"] == "dark"
    assert result["owner"] is None


def test_older_reasoning_counts_less():
    signals = [row("lies", "s1", "2025-10-01"), row("jan", "s2", "2026-10-01")]
    people = {p["person"]: p["proficiency"] for p in who_knows(QUERY, signals, NOW)["people"]}
    assert people["jan"] > people["lies"]


def test_others_doing_similar_tasks_later_takes_over():
    signals = [row("lies", "s1", "2026-09-01"), row("lies", "s1", "2026-09-01")] + [
        row("jan", f"j{i}", f"2026-10-0{i}") for i in range(1, 4)
    ]
    before = who_knows(QUERY, signals, datetime(2026, 9, 15, tzinfo=timezone.utc))
    after = who_knows(QUERY, signals, NOW)
    assert before["owner"] == "lies"
    assert after["owner"] == "jan"


def test_unrelated_tasks_are_ignored():
    signals = [row("lies", "s1", "2026-10-01", why="configure the aikido security scan on github")]
    assert who_knows(QUERY, signals, NOW)["similar_tasks"] == 0


def test_future_rows_are_invisible():
    signals = [row("jan", "s2", "2026-11-01")]
    assert who_knows(QUERY, signals, NOW)["people"] == []
