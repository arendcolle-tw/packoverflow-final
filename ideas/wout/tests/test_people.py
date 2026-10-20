from knowledge_clock.clock import parse_at
from knowledge_clock.people import items_to_rows, normalize_topic, person_key, person_view
from tests.helpers import row

NOW = parse_at("2026-10-20T12:00:00Z")


def test_person_key():
    assert person_key("  Jan ") == person_key("jan") == "jan"
    assert person_key("Anne  Marie") == "anne marie"
    assert person_key("   ") is None and person_key("x" * 41) is None


def test_normalize_topic():
    assert normalize_topic("Payroll: PC 200 Indexation!") == "payroll-pc-200-indexation"


def test_items_to_rows_maps_kinds():
    rows, errors = items_to_rows([
        {"topic": "Aikido scan", "kind": "decided", "why": "we only scan main"},
        {"topic": "aikido scan", "kind": "prompted", "why": "ignored"},
    ], "jan", NOW)
    assert errors == []
    assert [(r["human_role"], r["why"]) for r in rows] == [("decided", "we only scan main"), ("accepted_as_is", None)]
    assert rows[0]["source_id"] == "mcp-jan-aikido-scan" and rows[0]["at"] == "2026-10-20T12:00:00+00:00"
    assert rows[0]["id"].startswith("mcp-") and rows[0]["actor"] == "human"


def test_items_to_rows_rejects_bad_items():
    rows, errors = items_to_rows([
        {"topic": "x", "kind": "decided"},
        {"topic": "x", "kind": "vibes", "why": "a"},
        {"topic": "x", "kind": "decided", "why": "a" * 201},
        {"topic": "", "kind": "decided", "why": "a"},
        {"topic": "x", "kind": "decided", "why": "<b>ok</b>", "happened_at": "2026-09-30T10:00:00Z"},
    ], "jan", NOW)
    assert len(rows) == 1 and rows[0]["at"] == "2026-09-30T10:00:00+00:00" and len(errors) == 4
    assert errors[0].startswith("item 0:")
    assert items_to_rows([{"topic": "x", "kind": "prompted"}] * 51, "jan", NOW) == ([], ["at most 50 items per call"])


def test_items_to_rows_rejects_bad_time():
    rows, errors = items_to_rows([{"topic": "x", "kind": "decided", "why": "a", "happened_at": "last week"}], "jan", NOW)
    assert rows == [] and errors[0].startswith("item 0:")


def test_person_view():
    sig = [row(person="jan", topic="a", why="mine"), row(person="jan", topic="b"), row(person="piet", topic="b"),
           row(person="jan", topic="c", human_role="accepted_as_is")]
    v = person_view(sig, "jan", NOW)
    assert (v["reasoned"], v["prompted"]) == (2, 1)
    assert v["headline"] == "Claude handled 1 of your requests on its own. You reasoned 2 times."
    assert [(k["topic"], k["only_you"]) for k in v["knows"]] == [("a", True), ("b", False)]
    assert v["knows"][0]["latest_why"] == "mine" and v["only_prompts"] == ["c"]
