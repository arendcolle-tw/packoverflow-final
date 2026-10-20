"""The knowledge graph: one place that holds every signal row and answers who knows what.

Tristan's ingestion and the connector's record_signals write through add_signals. Wout's connector
reads through who_knows, person_view and risks. Nodes are people, tasks (one Claude session each)
and evidence (one signal row). Proficiency is the computed person -> task edge, see proficiency.score.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from proficiency.score import OWNER_THRESHOLD, build_tasks, parse_at, rank, row_weight, who_knows

FIELDS = {"id", "person", "topic", "source", "source_id", "at", "human_role", "why", "actor"}
ROLES = {"decided", "corrected", "explained_why", "answered_question", "accepted_as_is"}
SOURCES = {"claude_session", "meeting"}
ACTORS = {"human", "agent", "unknown"}

_LOCK = threading.Lock()


def validate(row: dict) -> str | None:
    """Return why a row is rejected, or None when it is a valid signal."""
    if not isinstance(row, dict):
        return "not an object"
    missing = FIELDS - row.keys()
    if missing:
        return f"missing {', '.join(sorted(missing))}"
    if not all(isinstance(row[f], str) and row[f] for f in FIELDS - {"why"}):
        return "empty field"
    if row["human_role"] not in ROLES or row["source"] not in SOURCES or row["actor"] not in ACTORS:
        return "unknown human_role, source or actor"
    if row["why"] is not None and not isinstance(row["why"], str):
        return "why is not text"
    try:
        parse_at(row["at"])
    except ValueError:
        return "at is not an ISO time"
    return None


class KnowledgeGraph:
    """Rows live in one JSONL file (later lines win per id). `mirror` is anything with upload(path), e.g. a GCS mirror."""

    def __init__(self, path: Path, seed_paths: list[Path] = (), mirror=None):
        self.path = Path(path)
        self.mirror = mirror
        self._rows: dict[str, dict] = {}
        for seed in seed_paths:
            for row in json.loads(Path(seed).read_text()):
                if validate(row) is None:
                    self._rows[row["id"]] = row
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if validate(row) is None:
                    self._rows[row["id"]] = row

    def rows(self) -> list[dict]:
        return list(self._rows.values())

    def add_signals(self, rows: list[dict]) -> dict:
        valid, rejected = [], []
        for i, row in enumerate(rows):
            reason = validate(row)
            if reason:
                rejected.append(f"row {i}: {reason}")
            else:
                valid.append(row)
        with _LOCK:
            updated = sum(1 for row in valid if row["id"] in self._rows)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as out:
                for row in valid:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    self._rows[row["id"]] = row
            if self.mirror and valid:
                self.mirror.upload(self.path)
        return {"added": len(valid) - updated, "updated": updated, "rejected": rejected}

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
