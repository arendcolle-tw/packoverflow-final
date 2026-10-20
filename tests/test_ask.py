import asyncio

import pytest

from knowly import ask as ask_mod
from knowly.ask import Asker

BASE = "http://knowly.test/store"
QUESTION = "What time does the nightly payroll export start?"
PAYROLL = {"person": "tristan", "task": "Payroll SFTP export retries", "at": "2026-10-18",
           "why": 'Retry 3 times, not 5, "because the bank closes the SFTP window at 18:00"'}
KNOWN = {"answered": True, "answer": "Three retries, tristan decided on 2026-10-18.", "sources": [PAYROLL],
         "ask_person": None, "why_them": None}
GAP = {"answered": False, "answer": "Only the retry count is recorded.", "sources": [PAYROLL],
       "ask_person": "tristan", "why_them": "Tristan planned the payroll export.",
       "ping": "{person}, do you know when the export starts?"}


class FakeMembers:
    def __init__(self):
        self.stored = []

    def store_fact(self, person, question, fact, topic, question_id):
        self.stored.append((person, question, fact, topic, question_id))
        return {"id": f"question:{question_id}:{person}", "person": person, "why": fact, "topic": topic}


@pytest.fixture
def make(tmp_path, monkeypatch):
    def build(result=GAP, default_expert=""):
        asked, pinged = [], []

        def answer(question, asker, base_url):
            asked.append((question, asker, base_url))
            return result

        async def notify(record):
            pinged.append(record)

        monkeypatch.setattr(ask_mod, "answer", answer)
        asker = Asker(BASE, tmp_path / "data", FakeMembers(), notify=notify, default_expert=default_expert)
        return asker, asked, pinged
    return build


def test_known_answer_creates_no_question(make):
    asker, asked, pinged = make(KNOWN)
    result = asyncio.run(asker.ask(f"  {QUESTION} ", "alberic"))
    assert result == {"known": True, "text": KNOWN["answer"], "answer": KNOWN["answer"], "ping": None,
                      "question_id": None, "pinged": None, "sources": [PAYROLL]}
    assert asked == [(QUESTION, "alberic", BASE)] and pinged == []


def test_unknown_asks_the_agents_pick_once(make, tmp_path):
    asker, _, pinged = make()
    result = asyncio.run(asker.ask(QUESTION, "alberic"))
    assert not result["known"] and result["pinged"] == "tristan"
    assert result["text"] == "Only the retry count is recorded.\n\nTristan, do you know when the export starts?"
    assert (result["answer"], result["ping"]) == (GAP["answer"], GAP["ping"])
    [record] = pinged
    assert record["ping"] == GAP["ping"]
    assert record["id"] == result["question_id"]
    assert (record["question"], record["asker"], record["target"], record["status"]) == (QUESTION, "alberic", "tristan", "open")
    assert record["related"] == [PAYROLL] and asker.get(result["question_id"])["related"] == [PAYROLL]
    assert (tmp_path / "data" / "questions.db").exists()


def test_duplicate_open_question_is_reused(make):
    asker, _, pinged = make()
    first = asyncio.run(asker.ask(QUESTION, "alberic"))
    second = asyncio.run(asker.ask("  what time does the NIGHTLY payroll export start ", "alberic"))
    assert second["question_id"] == first["question_id"]
    assert len(pinged) == 1


def test_the_asker_is_never_pinged(make):
    asker, _, pinged = make()
    result = asyncio.run(asker.ask(QUESTION, "Tristan"))
    assert result["pinged"] is None and result["question_id"] is None and pinged == []
    assert result["text"] == GAP["answer"]
    assert asyncio.run(asker.ask(QUESTION, "Trístan"))["pinged"] is None

    asker, _, _ = make(default_expert="tristan")
    assert asyncio.run(asker.ask(QUESTION, "tristan"))["pinged"] is None

    asker, _, _ = make({**GAP, "ask_person": None, "ping": None}, default_expert="alberic")
    result = asyncio.run(asker.ask(QUESTION, "tristan"))
    assert result["pinged"] == "alberic" and result["ping"] == f"{{person}}, Tristan is asking: “{QUESTION}” Do you know?"


def test_record_answer_stores_a_fact_and_answers_the_next_ask(make):
    asker, _, pinged = make()
    qid = asyncio.run(asker.ask(QUESTION, "alberic"))["question_id"]
    answer = "  It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff "
    row = asker.record_answer(qid, "Tristan", answer)

    assert asker.members.stored == [("tristan", QUESTION, answer.strip(), "nightly-payroll-export-start", qid)]
    assert row["id"] == f"question:{qid}:tristan"
    stored = asker.get(qid)
    assert (stored["status"], stored["answer"]) == ("answered", answer.strip())

    again = asyncio.run(asker.ask(QUESTION, "alberic"))
    assert again["known"] and "16:00" in again["text"] and again["text"].startswith("Tristan answered this on")
    assert len(pinged) == 1


def test_record_answer_checks_question_person_and_length(make):
    asker, _, _ = make()
    qid = asyncio.run(asker.ask(QUESTION, "alberic"))["question_id"]
    with pytest.raises(KeyError):
        asker.record_answer("gone", "tristan", "16:00")
    with pytest.raises(PermissionError):
        asker.record_answer(qid, "alberic", "16:00")
    with pytest.raises(ValueError):
        asker.record_answer(qid, "tristan", "   ")
    with pytest.raises(ValueError):
        asker.record_answer(qid, "tristan", "x" * 201)
    assert asker.members.stored == [] and asker.get(qid)["status"] == "open"


def test_a_failed_store_keeps_the_question_open(make):
    asker, _, _ = make()
    qid = asyncio.run(asker.ask(QUESTION, "alberic"))["question_id"]

    def down(*args):
        raise RuntimeError("store down")

    asker.members.store_fact = down
    with pytest.raises(RuntimeError):
        asker.record_answer(qid, "tristan", "16:00")
    assert asker.get(qid)["status"] == "open"
