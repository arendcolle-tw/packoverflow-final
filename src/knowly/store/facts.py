"""The fact store: every fact with the person it comes from and their reason, ranked per question by scoring."""

import hashlib
import json
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from knowly.store.mirror import GcsMirror
from knowly.store.scoring import OWNER_THRESHOLD, build_tasks, parse_at, rank, row_weight, who_knows

REQUIRED = ("id", "person", "topic", "source", "source_id", "at", "human_role", "actor")
LIMITS = {"why": 200, "task": 80, "app": 300}  # optional fields and their max length
MAX_STRING = 300
ROLES = {"decided", "corrected", "explained_why", "answered_question", "accepted_as_is"}
SOURCES = {"claude_session", "meeting", "copilot_chat", "copilot_cli", "m365_copilot", "screenshot", "mcp_record",
           "slack_thread", "voice_call", "voice_widget_unverified", "gap_form"}
DRAFTS = {"confirmed", "edited", "rewritten"}  # optional `draft`: how much a person changed a Claude draft
ACTORS = {"human", "agent", "unknown"}


def validate(row: dict) -> str | None:
    """Return why a fact is rejected, or None when it is valid."""
    if not isinstance(row, dict):
        return "not an object"
    missing = set(REQUIRED) - row.keys()
    if missing:
        return f"missing {', '.join(sorted(missing))}"
    if not all(isinstance(row[f], str) and row[f] for f in REQUIRED):
        return "empty field"
    if row["human_role"] not in ROLES or row["source"] not in SOURCES or row["actor"] not in ACTORS:
        return "unknown human_role, source or actor"
    for field, limit in LIMITS.items():
        if row.get(field) is not None and not isinstance(row[field], str):
            return f"{field} is not text"
        if len(row.get(field) or "") > limit:
            return f"{field} longer than {limit} characters"
    if row.get("draft") is not None and row["draft"] not in DRAFTS:
        return "unknown draft"
    if any(len(row[f]) > MAX_STRING for f in REQUIRED):
        return f"field longer than {MAX_STRING} characters"
    try:
        parse_at(row["at"])
    except ValueError:
        return "at is not an ISO time"
    return None


def _clean(row: dict) -> dict:
    """Known fields only; `why` is always present (None when missing), task, app and draft only when set."""
    out = {f: row[f] for f in REQUIRED}
    out["why"] = row.get("why")
    out.update({f: row[f] for f in ("task", "app", "draft") if row.get(f) is not None})
    return out


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class FactStore:
    """Facts live in one SQLite file at `path`. `mirror` is anything with upload(path), and optionally download(path)
    to restore a missing file. Each fact id belongs to the first person who wrote it."""

    def __init__(self, path: Path, mirror=None):
        self.path = Path(path)
        self.mirror = mirror
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() and hasattr(mirror, "download"):
            mirror.download(self.path)

        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, person TEXT NOT NULL, row TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS members (token TEXT PRIMARY KEY, person TEXT NOT NULL);"
            # Work without a session behind it, and gaps with Claude's draft. Drafts never enter `facts`.
            "CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, row TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS gaps (id TEXT PRIMARY KEY, row TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        self._rows: dict[str, dict] = {
            id_: json.loads(row) for id_, row in self._db.execute("SELECT id, row FROM facts ORDER BY rowid")
        }

    def rows(self) -> list[dict]:
        return list(self._rows.values())

    def add_facts(self, rows: list[dict], person: str | None = None) -> dict:
        """Store valid facts. `person` (from a member token) overrides each fact's person."""
        valid, rejected = [], []
        for i, row in enumerate(rows):
            reason = validate(row)
            if reason:
                rejected.append(f"row {i}: {reason}")
            elif row["id"] in self._rows and self._rows[row["id"]]["person"] != (person or row["person"]):
                rejected.append(f"row {i}: id belongs to someone else")
            else:
                valid.append(row)
        with self._lock:
            updated = sum(1 for row in valid if row["id"] in self._rows)
            self._write(valid, person)
        return {"added": len(valid) - updated, "updated": updated, "rejected": rejected}

    def _write(self, rows: list[dict], person: str | None) -> None:
        if not rows:
            return
        for row in rows:
            row = _clean({**row, "person": person or row["person"]})
            owner = self._rows.get(row["id"], row)["person"]
            if owner != row["person"]:
                continue
            self._db.execute(
                "INSERT INTO facts (id, person, row) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET row = excluded.row",
                (row["id"], owner, json.dumps(row, ensure_ascii=False)),
            )
            self._rows[row["id"]] = row
        self._commit()

    def _commit(self) -> None:
        self._db.commit()
        if self.mirror:
            self.mirror.upload(self.path)

    def add_member(self, person: str) -> str:
        """Create a member token for `person`. Only its hash is stored, so the token is shown once."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute("INSERT INTO members (token, person) VALUES (?, ?)", (_hash(token), person))
            self._commit()
        return token

    def member(self, token: str) -> str | None:
        found = self._db.execute("SELECT person FROM members WHERE token = ?", (_hash(token),)).fetchone()
        return found[0] if found else None

    def members(self) -> set[str]:
        return {p for (p,) in self._db.execute("SELECT DISTINCT person FROM members")}

    def artifacts(self) -> list[dict]:
        return [json.loads(r) for (r,) in self._db.execute("SELECT row FROM artifacts ORDER BY rowid")]

    def add_artifacts(self, artifacts: list[dict]) -> int:
        with self._lock:
            for a in artifacts:
                self._db.execute(
                    "INSERT INTO artifacts (id, row) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET row = excluded.row",
                    (a["id"], json.dumps(a, ensure_ascii=False)),
                )
            self._commit()
        return len(artifacts)

    def setting(self, key: str) -> str | None:
        found = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return found[0] if found else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                             (key, value))
            self._commit()

    def gaps(self) -> list[dict]:
        return [json.loads(r) for (r,) in self._db.execute("SELECT row FROM gaps ORDER BY rowid")]

    def gap(self, gap_id: str) -> dict | None:
        found = self._db.execute("SELECT row FROM gaps WHERE id = ?", (gap_id,)).fetchone()
        return json.loads(found[0]) if found else None

    def save_gaps(self, gaps: list[dict]) -> None:
        with self._lock:
            for g in gaps:
                self._db.execute(
                    "INSERT INTO gaps (id, row) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET row = excluded.row",
                    (g["id"], json.dumps(g, ensure_ascii=False)),
                )
            self._commit()

    def who_knows(self, question: str, at: datetime | None = None) -> dict:
        return who_knows(question, self.rows(), at)

    def _topics(self, at: datetime) -> dict[str, dict]:
        by_topic: dict[str, list[dict]] = {}
        for row in self.rows():
            if parse_at(row["at"]) <= at:
                by_topic.setdefault(row["topic"], []).append(row)

        topics = {}
        for topic, rows in by_topic.items():
            ranking = rank([(task, 1.0) for task in build_tasks(rows, at)], at)
            reasoning = sorted((r for r in rows if row_weight(r) > 0), key=lambda r: r["at"])
            last = parse_at(reasoning[-1]["at"]) if reasoning else None
            topics[topic] = {
                "topic": topic,
                "status": ranking["status"],
                "owner": ranking["owner"],
                "ai_count": len(rows) - len(reasoning),
                "human_count": len(reasoning),
                "last_human_reasoning_at": last.isoformat() if last else None,
                "days_since": (at - last).days if last else None,
                "people": [
                    {"person": p["person"], "proficiency": p["proficiency"],
                     "last_why": next((w["why"] for e in p["evidence"] for w in e["whys"]), None)}
                    for p in ranking["people"] if p["evidence"]
                ],
            }
        return topics

    def risks(self, at: datetime | None = None) -> list[dict]:
        """Topics, riskiest first: dark, single_point, fading, healthy. Same decay as who_knows."""
        order = {"dark": 0, "single_point": 1, "fading": 2, "healthy": 3}
        topics = self._topics(at or datetime.now(timezone.utc)).values()
        return sorted(topics, key=lambda t: (order[t["status"]], -t["ai_count"], t["topic"]))

    def person_view(self, person: str, at: datetime | None = None) -> dict:
        """What this person actually knows (their reasoning, their words) vs what they only prompt."""
        at = at or datetime.now(timezone.utc)
        topics = self._topics(at)
        mine = [r for r in self.rows() if r["person"] == person and parse_at(r["at"]) <= at]
        reasoned = sum(1 for r in mine if row_weight(r) > 0)

        knows, only_prompts = [], []
        for topic in sorted({r["topic"] for r in mine}):
            me = next((p for p in topics[topic]["people"] if p["person"] == person), None)
            if me is None:
                only_prompts.append(topic)
                continue
            strong = [p for p in topics[topic]["people"] if p["proficiency"] >= OWNER_THRESHOLD]
            knows.append({
                "topic": topic,
                "proficiency": me["proficiency"],
                "latest_why": me["last_why"],
                "only_you": [p["person"] for p in strong] == [person],
            })
        knows.sort(key=lambda k: (not k["only_you"], -k["proficiency"]))

        return {
            "person": person,
            "headline": f"Claude handled {len(mine) - reasoned} of your requests on its own. You reasoned {reasoned} times.",
            "reasoned": reasoned,
            "prompted": len(mine) - reasoned,
            "knows": knows,
            "only_prompts": only_prompts,
        }


def open_store(data_dir: Path, bucket: str | None = None) -> FactStore:
    """The store at <data_dir>/facts.sqlite, mirrored to the Cloud Storage bucket when one is given."""
    mirror = None
    if bucket:
        try:
            mirror = GcsMirror(bucket)
        except Exception as error:  # noqa: BLE001
            print(f"Cloud Storage mirror unavailable, storing locally: {type(error).__name__}", file=sys.stderr)
    return FactStore(Path(data_dir) / "facts.sqlite", mirror)
