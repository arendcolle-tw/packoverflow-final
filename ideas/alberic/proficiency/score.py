"""who_knows(task, at): rank people by how much they reasoned about tasks similar to this one.

One Claude session (source_id) is one task. There is no topic list: the "topic" is the set of
past tasks similar to the question. Only human reasoning counts, it decays with time, and it
drops when others did similar tasks after you (takeover).
"""

import math
import re
from collections import Counter
from datetime import datetime, timezone

ROLE_WEIGHT = {"decided": 1.0, "explained_why": 1.0, "answered_question": 1.0, "corrected": 0.7, "accepted_as_is": 0.0}
ACTOR_WEIGHT = {"human": 1.0, "unknown": 0.5, "agent": 0.0}
DECAY_DAYS = 90
MIN_SIMILARITY = 0.1
OWNER_THRESHOLD = 0.2

STOPWORDS = set(
    "the and for that this with you are but not was have from all just what our can will its into then "
    "very also use using want would should could about more them they het een van dat die niet wat ook "
    "met voor zijn maar als wel nog naar bij heb hebben gewoon".split()
)


def parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2 and w not in STOPWORDS]


def row_weight(row: dict) -> float:
    weight = ROLE_WEIGHT.get(row["human_role"], 0.0) * ACTOR_WEIGHT.get(row["actor"], 0.0)
    # Only saying "yes" to Claude's draft is close to accepted_as_is: half weight.
    return weight * 0.5 if row.get("draft") == "confirmed" else weight


def build_tasks(signals: list[dict], at: datetime) -> list[dict]:
    """Group rows into tasks by (person, session). Subagent rows (`<session>:<agent>`) belong to their parent.

    Keying on the person too means a row posted under a colleague's session id cannot change their task.
    """
    by_session: dict[tuple[str, str], list[dict]] = {}
    for row in signals:
        if parse_at(row["at"]) <= at:
            by_session.setdefault((row["person"], row["source_id"].split(":")[0]), []).append(row)

    tasks = []
    for (person, source_id), rows in by_session.items():
        rows.sort(key=lambda r: r["at"])
        summary = next((r["task"] for r in rows if r.get("task")), None)
        text = summary or " ".join([rows[0].get("topic", "").replace("-", " ")] + [r["why"] for r in rows if r["why"]])
        tasks.append({
            "source_id": source_id,
            "person": person,
            "at": parse_at(rows[-1]["at"]),
            "text": text,
            "rows": rows,
        })
    return tasks


def _tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    df = Counter(word for doc in docs for word in set(doc))
    vectors = []
    for doc in docs:
        counts = Counter(doc)
        # Smoothed idf (+1): words every task shares must still match, or identical tasks score 0.
        vec = {w: c * (math.log((1 + len(docs)) / (1 + df[w])) + 1) for w, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({w: v / norm for w, v in vec.items()})
    return vectors


def similarities(query: str, tasks: list[dict]) -> list[float]:
    vectors = _tfidf([tokens(query)] + [tokens(t["text"]) for t in tasks])
    q = vectors[0]
    return [sum(q.get(w, 0.0) * v for w, v in vec.items()) for vec in vectors[1:]]


def who_knows(query: str, signals: list[dict], at: datetime | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    tasks = build_tasks(signals, at)
    relevant = [(t, s) for t, s in zip(tasks, similarities(query, tasks)) if s >= MIN_SIMILARITY]
    return {"query": query, "at": at.isoformat(), **rank(relevant, at)}


def rank(relevant: list[tuple[dict, float]], at: datetime) -> dict:
    """Rank people over (task, similarity) pairs. Callers pick the tasks: similar to a question, or one topic."""
    people: dict[str, dict] = {}
    for task, sim in relevant:
        reasoning = sum(
            row_weight(r) * math.exp(-(at - parse_at(r["at"])).total_seconds() / 86400 / DECAY_DAYS) for r in task["rows"]
        )
        later = [t for t, _ in relevant if t["at"] > task["at"]]
        own_later = sum(1 for t in later if t["person"] == task["person"])
        takeover = (1 + own_later) / (1 + len(later))

        contribution = sim * reasoning * takeover
        entry = people.setdefault(task["person"], {"person": task["person"], "raw": 0.0, "evidence": []})
        entry["raw"] += contribution
        if contribution > 0:
            entry["evidence"].append({
                "source_id": task["source_id"],
                "at": task["at"].isoformat(),
                "similarity": round(sim, 2),
                "takeover": round(takeover, 2),
                "contribution": round(contribution, 3),
                "whys": [{"role": r["human_role"], "why": r["why"]} for r in task["rows"] if r["why"] and row_weight(r) > 0],
            })

    ranked = []
    for entry in people.values():
        entry["proficiency"] = round(1 - math.exp(-entry.pop("raw")), 3)
        entry["evidence"].sort(key=lambda e: -e["contribution"])
        ranked.append(entry)
    ranked.sort(key=lambda e: -e["proficiency"])

    above = [p for p in ranked if p["proficiency"] >= OWNER_THRESHOLD]
    # dark = no human reasoning ever; reasoning that decayed to ~0 is fading, not dark.
    if not any(p["evidence"] for p in ranked):
        status = "dark"
    elif not above:
        status = "fading"
    elif len(above) == 1:
        status = "single_point"
    else:
        status = "healthy"

    return {
        "status": status,
        "owner": above[0]["person"] if above else None,
        "similar_tasks": len(relevant),
        "people": ranked,
    }
