import asyncio
import json
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from knowly.agent import PING, answer
from knowly.config import person_key
from knowly.slack.extract import kebab_topic

log = logging.getLogger(__name__)

SCHEMA = """CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, question TEXT NOT NULL, asker TEXT NOT NULL, target TEXT, related_json TEXT,
    status TEXT NOT NULL, answer TEXT, created_at TEXT NOT NULL, answered_at TEXT)"""


class Asker:
    """Answers questions from MCP, POST /api/ask and Slack DMs, and asks a colleague when the answer is not recorded."""

    def __init__(self, base_url: str, data_dir: Path, members, notify=None, default_expert: str = ""):
        self.base_url = base_url
        self.members = members
        self.notify = notify
        self.default_expert = default_expert.strip()
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(Path(data_dir) / "questions.db", check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute(SCHEMA)

    async def ask(self, question: str, asker: str) -> dict:
        """Returns text for MCP and /api/ask, plus answer and ping (with a {person} placeholder) for Slack."""
        question = question.strip()
        result = await asyncio.to_thread(answer, question, asker, self.base_url)
        sources = result["sources"]
        reply = {"known": True, "text": result["answer"], "answer": result["answer"], "ping": None,
                 "question_id": None, "pinged": None, "sources": sources}
        if result["answered"]:
            return reply

        earlier = self._answered(question)
        if earlier:
            text = f"{earlier['target'].title()} answered this on {earlier['answered_at'][:10]}: {earlier['answer']}"
            return {**reply, "text": text, "answer": text, "question_id": earlier["id"]}

        me = person_key(asker)
        target = result["ask_person"] if person_key(result["ask_person"] or "") != me else None
        ping = result.get("ping") if target else None
        if not target and person_key(self.default_expert) not in ("", me):
            target = self.default_expert
        if not target:
            return {**reply, "known": False}
        ping = ping or PING.format(person="{person}", asker=asker.title(), question=question)

        record = self._open(question, target)
        if record is None:
            record = {
                "id": secrets.token_hex(6), "question": question, "asker": asker, "target": target,
                "related": sources[:3], "status": "open", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._db.execute(
                "INSERT INTO questions (id, question, asker, target, related_json, status, created_at) VALUES (?,?,?,?,?,?,?)",
                (record["id"], question, asker, target, json.dumps(record["related"]), "open", record["created_at"]),
            )
            if self.notify:
                try:
                    await self.notify({**record, "ping": ping})
                except Exception:
                    log.exception("notify failed for question %s", record["id"])
        text = f"{result['answer']}\n\n{ping.replace('{person}', target.title())}"
        return {**reply, "known": False, "text": text, "ping": ping, "question_id": record["id"], "pinged": target}

    def record_answer(self, question_id: str, person: str, text: str) -> dict:
        record = self.get(question_id)
        if record is None:
            raise KeyError(f"no question {question_id}")
        if person_key(record["target"] or "") != person_key(person):
            raise PermissionError(f"only {record['target']} can answer question {question_id}")
        text = text.strip()
        if not 1 <= len(text) <= 200:
            raise ValueError("an answer must be 1 to 200 characters")
        row = self.members.store_fact(record["target"], record["question"], text, kebab_topic("", record["question"]),
                                      question_id)
        self._db.execute("UPDATE questions SET status='answered', answer=?, answered_at=? WHERE id=?",
                         (text, datetime.now(timezone.utc).isoformat(timespec="seconds"), question_id))
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
            "SELECT id FROM questions WHERE status='open' ORDER BY created_at").fetchall():
            record = self.get(found["id"])
            if person_key(record["target"] or "") == person_key(target) and re.findall(r"\w+", record["question"].lower()) == key:
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
