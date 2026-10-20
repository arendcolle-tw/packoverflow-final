import asyncio
import json
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, question TEXT NOT NULL, asker TEXT NOT NULL, target TEXT, related_json TEXT,
    status TEXT NOT NULL, answer TEXT, created_at TEXT NOT NULL, answered_at TEXT)"""


def related_facts(lookup: dict) -> list[dict]:
    facts = [
        {"person": p["person"], **ev}
        for p in lookup.get("people") or []
        for ev in p.get("evidence") or []
    ]
    return sorted(facts, key=lambda f: f.get("similarity") or 0, reverse=True)


class Asker:
    def __init__(self, graph, db_path: Path, tokens_path: Path, notify=None, compose=None):
        if compose is None:
            from whoknows.answer import compose
        self.graph = graph
        self.compose = compose
        self.tokens_path = Path(tokens_path)
        self.notify = notify
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute(SCHEMA)

    async def ask(self, question: str, asker: str) -> dict:
        question = question.strip()
        lookup = await asyncio.to_thread(self.graph.lookup, question)
        composed = await asyncio.to_thread(self.compose, question, lookup)
        sources = composed.get("sources") or []
        if composed.get("answered"):
            return {"known": True, "text": composed["text"], "question_id": None, "pinged": None, "sources": sources}

        earlier = self._answered(question)
        if earlier:
            text = f"{earlier['target']} answered this on {earlier['answered_at'][:10]}: \"{earlier['answer']}\""
            return {"known": True, "text": text, "question_id": earlier["id"], "pinged": None, "sources": sources}

        facts = related_facts(lookup)
        me = asker.strip().lower()
        target = next((f["person"] for f in facts if f["person"].lower() != me), None)
        if not target and os.environ.get("DEFAULT_EXPERT", "").strip().lower() not in ("", me):
            target = os.environ["DEFAULT_EXPERT"].strip()
        if not target:
            text = f"{composed['text']}\n\nNobody else has recorded anything related, so I could not find anyone to ask."
            return {"known": False, "text": text, "question_id": None, "pinged": None, "sources": sources}

        record = self._open(question, target)
        if record is None:
            record = {
                "id": secrets.token_hex(6), "question": question, "asker": asker, "target": target,
                "related": facts[:3], "status": "open", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._db.execute(
                "INSERT INTO questions (id, question, asker, target, related_json, status, created_at) VALUES (?,?,?,?,?,?,?)",
                (record["id"], question, asker, target, json.dumps(record["related"]), "open", record["created_at"]),
            )
            if self.notify:
                try:
                    await self.notify(record)
                except Exception:
                    log.exception("notify failed for question %s", record["id"])
        text = f"{composed['text']}\n\nI asked {target}; ask again once they have answered."
        return {"known": False, "text": text, "question_id": record["id"], "pinged": target, "sources": sources}

    def record_answer(self, question_id: str, person: str, text: str) -> dict:
        record = self.get(question_id)
        if record is None:
            raise KeyError(f"no question {question_id}")
        if (record["target"] or "").lower() != person.lower():
            raise PermissionError(f"only {record['target']} can answer question {question_id}")
        text = text.strip()
        if not 1 <= len(text) <= 200:
            raise ValueError("an answer must be 1 to 200 characters")
        try:
            token = json.loads(self.tokens_path.read_text())[record["target"]]
        except (OSError, ValueError, KeyError):
            raise RuntimeError(f"no graph member token for {record['target']} in {self.tokens_path}") from None

        topic = next((f["topic"] for f in record["related"] if f.get("topic")), "questions")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = {
            "id": f"ask:{question_id}:{record['target']}", "person": record["target"], "topic": topic,
            "source": "gap_form", "source_id": f"ask-{question_id}", "at": now, "human_role": "answered_question",
            "actor": "human", "why": text, "task": record["question"][:80],
        }
        self.graph.post_rows([row], token)
        self.graph.invalidate()
        self._db.execute(
            "UPDATE questions SET status='answered', answer=?, answered_at=? WHERE id=?", (text, now, question_id)
        )
        return row

    def get(self, question_id: str) -> dict | None:
        found = self._db.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if found is None:
            return None
        record = dict(found)
        record["related"] = json.loads(record.pop("related_json") or "[]")
        return record

    def _open(self, question: str, target: str) -> dict | None:
        key = re.findall(r"\w+", question.lower())
        for found in self._db.execute(
            "SELECT id FROM questions WHERE status='open' AND lower(target)=? ORDER BY created_at", (target.lower(),)
        ).fetchall():
            record = self.get(found["id"])
            if re.findall(r"\w+", record["question"].lower()) == key:
                return record
        return None

    def _answered(self, question: str) -> dict | None:
        key = re.findall(r"\w+", question.lower())
        for found in self._db.execute(
            "SELECT id, question FROM questions WHERE status='answered' ORDER BY answered_at DESC"
        ).fetchall():
            if re.findall(r"\w+", found["question"].lower()) == key:
                return self.get(found["id"])
        return None
