from datetime import datetime, timezone

from knowly.store import FactStore

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def row(i, person, topic="pc-200-indexation", role="decided", at="2026-10-01", why="indexation of wages in joint committee 200"):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": f"s{i}",
            "at": at, "human_role": role, "why": why if role != "accepted_as_is" else None, "actor": "human"}


def test_add_facts_dedupes_on_id_and_survives_reload(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite")
    assert store.add_facts([row(1, "alberic"), row(2, "jan")]) == {"added": 2, "updated": 0, "rejected": []}
    assert store.add_facts([row(1, "alberic", why="changed my mind")])["updated"] == 1

    reloaded = FactStore(tmp_path / "facts.sqlite")
    assert len(reloaded.rows()) == 2
    assert {r["why"] for r in reloaded.rows()} >= {"changed my mind"}


def test_invalid_facts_are_rejected_with_a_reason(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite")
    result = store.add_facts([{"id": "x"}, {**row(1, "alberic"), "human_role": "vibes"}])
    assert result["added"] == 0
    assert len(result["rejected"]) == 2
    assert store.rows() == []


def test_mirror_gets_the_file_after_a_write(tmp_path):
    uploads = []
    store = FactStore(tmp_path / "facts.sqlite", mirror=type("M", (), {"upload": lambda self, p: uploads.append(p)})())
    store.add_facts([row(1, "alberic")])
    assert uploads == [tmp_path / "facts.sqlite"]


def test_risks_use_decay_not_a_fixed_window(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite")
    store.add_facts([
        row(1, "alberic", topic="pay-transparency", at="2026-10-15"),
        row(2, "jan", topic="pay-transparency", at="2026-10-16"),
        row(3, "alberic", topic="flexi-jobs", at="2026-10-10"),
        row(4, "jan", topic="mysdworx-login", role="accepted_as_is"),
        row(5, "an", topic="old-payroll-engine", at="2024-01-01"),
    ])
    status = {t["topic"]: t["status"] for t in store.risks(NOW)}
    assert status == {"pay-transparency": "healthy", "flexi-jobs": "single_point", "mysdworx-login": "dark", "old-payroll-engine": "fading"}


def test_person_view_splits_knowing_from_prompting(tmp_path):
    store = FactStore(tmp_path / "facts.sqlite")
    store.add_facts([row(1, "alberic", topic="flexi-jobs"), row(2, "alberic", topic="mysdworx-login", role="accepted_as_is")])
    view = store.person_view("alberic", NOW)
    assert [k["topic"] for k in view["knows"]] == ["flexi-jobs"]
    assert view["knows"][0]["only_you"] is True
    assert view["only_prompts"] == ["mysdworx-login"]
    assert view["reasoned"] == 1 and view["prompted"] == 1
