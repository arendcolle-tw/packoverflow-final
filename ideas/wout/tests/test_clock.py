from knowledge_clock.clock import certainty, compute_topics, parse_at, summarize, topic_detail
from tests.helpers import row

NOW = parse_at("2026-10-20T16:15:00+02:00")


def test_certainty_levels():
    assert certainty(row(source="meeting", human_role="answered_question")) == "confirmed"
    assert certainty(row()) == "likely"
    assert certainty(row(actor="unknown")) == "uncertain"
    assert certainty(row(human_role="accepted_as_is")) == "ai"
    assert certainty(row(actor="agent", human_role="decided")) == "ai"


def test_dark_when_only_ai():
    [t] = compute_topics([row(human_role="accepted_as_is"), row(actor="agent")], NOW)
    assert (t["status"], t["ai_count"], t["human_count"], t["days_since"]) == ("dark", 2, 0, None)


def test_dark_when_only_uncertain():
    [t] = compute_topics([row(actor="unknown")], NOW)
    assert t["status"] == "dark" and t["uncertain_count"] == 1


def test_single_point_then_healthy():
    [t] = compute_topics([row(person="wout")], NOW)
    assert t["status"] == "single_point"
    [t] = compute_topics([row(person="wout"), row(person="tristan")], NOW)
    assert t["status"] == "healthy"


def test_fading_beats_single_point():
    [t] = compute_topics([row(at="2026-09-30T19:00:00Z")], NOW, fading_days=14)
    assert t["status"] == "fading" and t["days_since"] == 19


def test_timestamps_and_future():
    for at in ["2026-10-20T10:00:00Z", "2026-10-20T12:00:00+02:00", "2026-10-20T10:00:00"]:
        assert parse_at(at).tzinfo is not None
    [t] = compute_topics([row(at="2026-10-25T10:00:00Z")], NOW)
    assert t["days_since"] == 0


def test_aliases_merge_topics():
    topics = compute_topics(
        [row(topic="aikido"), row(topic="aikido-scan", person="tristan")], NOW, aliases={"aikido-scan": "aikido"}
    )
    assert [t["topic"] for t in topics] == ["aikido"] and topics[0]["status"] == "healthy"


def test_sort_order_and_reasoners():
    sig = [
        row(topic="a", human_role="accepted_as_is"),
        row(topic="b"),
        row(topic="c", at="2026-09-01T00:00:00Z"),
        row(topic="d", person="x"),
        row(topic="d", person="y", why="because PC 200"),
        row(topic="d", person="y"),
    ]
    topics = compute_topics(sig, NOW)
    assert [t["status"] for t in topics] == ["dark", "single_point", "fading", "healthy"]
    assert topics[3]["reasoners"][0] == {
        "person": "y",
        "count": 2,
        "last_at": "2026-10-20T10:00:00+00:00",
        "last_why": "because PC 200",
    }


def test_detail_and_summary():
    sig = [row(why="w1"), row(human_role="accepted_as_is")]
    d = topic_detail(sig, "aikido", NOW)
    assert len(d["signals"]) == 2 and {s["certainty"] for s in d["signals"]} == {"likely", "ai"}
    assert topic_detail(sig, "nope", NOW) is None
    s = summarize(compute_topics(sig, NOW))
    assert s == {
        "ai_count": 1,
        "human_count": 1,
        "topic_count": 1,
        "by_status": {"dark": 0, "single_point": 1, "fading": 0, "healthy": 0},
    }
