import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from knowly.ask import Asker

ALB = Path(__file__).resolve().parents[2] / "alberic"
QUESTION = "What time does the nightly payroll export start?"
PAYROLL = {
    "person": "tristan", "proficiency": 0.4,
    "evidence": [{
        "source_id": "s1", "at": "2026-10-18T10:00:00+00:00", "similarity": 0.31, "role": "decided",
        "task": "Payroll SFTP export retries", "topic": "payroll-export",
        "why": 'Retry 3 times, not 5, "because the bank closes the SFTP window at 18:00"',
    }],
}


def alberic_validate():
    sys.path.insert(0, str(ALB))
    spec = importlib.util.spec_from_file_location("alberic_graph", ALB / "knowledge_graph" / "graph.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


class FakeGraph:
    def __init__(self, people):
        self.people, self.posted, self.invalidated = people, [], 0

    def lookup(self, question):
        best = max((e["similarity"] for p in self.people for e in p["evidence"]), default=0.0)
        return {"question": question, "status": "single_point", "people": self.people, "best_similarity": best}

    def post_rows(self, rows, token):
        self.posted.append((rows, token))
        return {"added": len(rows), "updated": 0, "rejected": []}

    def invalidate(self):
        self.invalidated += 1


def fake_compose(answered):
    def compose(question, lookup):
        sources = [{"person": p["person"], "task": e["task"], "at": e["at"], "why": e["why"]}
                   for p in lookup["people"] for e in p["evidence"]]
        return {"answered": answered, "text": "Answer text." if answered else "Not recorded yet.", "sources": sources}
    return compose


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.delenv("DEFAULT_EXPERT", raising=False)
    tokens = tmp_path / "graph_tokens.json"
    tokens.write_text(json.dumps({"tristan": "kg_tristan"}))

    def build(people=(PAYROLL,), answered=False):
        pinged = []

        async def notify(record):
            pinged.append(record)

        graph = FakeGraph(list(people))
        asker = Asker(graph, tmp_path / "questions.db", tokens, notify=notify, compose=fake_compose(answered))
        return asker, graph, pinged
    return build


def test_known_answer_creates_no_question(make):
    asker, _, pinged = make(answered=True)
    result = asyncio.run(asker.ask(QUESTION, "lies"))
    assert result == {"known": True, "text": "Answer text.", "question_id": None, "pinged": None,
                      "sources": [{"person": "tristan", "task": "Payroll SFTP export retries",
                                   "at": "2026-10-18T10:00:00+00:00", "why": PAYROLL["evidence"][0]["why"]}]}
    assert pinged == []


def test_unknown_asks_owner_of_related_fact_once(make):
    asker, _, pinged = make()
    result = asyncio.run(asker.ask(QUESTION, "lies"))
    assert not result["known"] and result["pinged"] == "tristan"
    assert result["text"].endswith("I asked tristan; ask again once they have answered.")
    assert len(pinged) == 1
    record = pinged[0]
    assert record["id"] == result["question_id"]
    assert (record["question"], record["asker"], record["target"], record["status"]) == (QUESTION, "lies", "tristan", "open")
    assert record["related"][0]["why"] == PAYROLL["evidence"][0]["why"]
    assert asker.get(result["question_id"])["related"] == record["related"]


def test_duplicate_open_question_is_reused(make):
    asker, _, pinged = make()
    first = asyncio.run(asker.ask(QUESTION, "lies"))
    second = asyncio.run(asker.ask("  what time does the NIGHTLY payroll export start ", "lies"))
    assert second["question_id"] == first["question_id"]
    assert len(pinged) == 1


def test_asker_is_never_pinged(make, monkeypatch):
    asker, _, pinged = make()
    result = asyncio.run(asker.ask(QUESTION, "Tristan"))
    assert result["pinged"] is None and result["question_id"] is None and pinged == []

    monkeypatch.setenv("DEFAULT_EXPERT", "tristan")
    assert asyncio.run(asker.ask(QUESTION, "tristan"))["pinged"] is None

    monkeypatch.setenv("DEFAULT_EXPERT", "alberic")
    assert asyncio.run(asker.ask(QUESTION, "tristan"))["pinged"] == "alberic"


def test_record_answer_posts_valid_row(make):
    asker, graph, _ = make()
    qid = asyncio.run(asker.ask(QUESTION, "lies"))["question_id"]
    answer = "  It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff "
    row = asker.record_answer(qid, "tristan", answer)

    assert graph.posted == [([row], "kg_tristan")] and graph.invalidated == 1
    assert row["id"] == f"ask:{qid}:tristan" and row["source_id"] == f"ask-{qid}"
    assert (row["person"], row["topic"], row["source"], row["human_role"], row["actor"]) == (
        "tristan", "payroll-export", "gap_form", "answered_question", "human")
    assert row["why"] == answer.strip() and row["task"] == QUESTION
    assert alberic_validate()(row) is None
    stored = asker.get(qid)
    assert (stored["status"], stored["answer"]) == ("answered", answer.strip())


def test_record_answer_checks_person_length_and_token(make, tmp_path):
    asker, graph, _ = make()
    qid = asyncio.run(asker.ask(QUESTION, "lies"))["question_id"]
    with pytest.raises(PermissionError):
        asker.record_answer(qid, "lies", "16:00")
    with pytest.raises(ValueError):
        asker.record_answer(qid, "tristan", "   ")
    with pytest.raises(ValueError):
        asker.record_answer(qid, "tristan", "x" * 201)
    (tmp_path / "graph_tokens.json").write_text(json.dumps({"alberic": "kg_alberic"}))
    with pytest.raises(RuntimeError, match="no graph member token for tristan"):
        asker.record_answer(qid, "tristan", "16:00")
    assert graph.posted == [] and asker.get(qid)["status"] == "open"


def test_topic_defaults_and_answered_question_reopens_nothing(make):
    people = [{"person": "tristan", "proficiency": 0.4, "evidence": [{**PAYROLL["evidence"][0], "topic": None}]}]
    asker, _, pinged = make(people=people)
    qid = asyncio.run(asker.ask(QUESTION, "lies"))["question_id"]
    assert asker.record_answer(qid, "tristan", "16:00")["topic"] == "questions"

    again = asyncio.run(asker.ask(QUESTION, "lies"))
    assert again["known"] and "16:00" in again["text"] and "tristan" in again["text"]
    assert len(pinged) == 1
