import math
import re
from collections import Counter
from datetime import datetime, timezone

ROLE_WEIGHT = {"decided": 1.0, "explained_why": 1.0, "corrected": 0.7, "accepted_as_is": 0.0}
ACTOR_WEIGHT = {"human": 1.0, "unknown": 0.5, "agent": 0.0}
DECAY_DAYS = 90
FADING_DAYS = 30
MIN_SIMILARITY = 0.15
MIN_SCORE = 0.2
STOPWORDS = set(
    "the and for that this with you are but not was have from all just what our can will its into then "
    "how who does did get make about knows know someone anyone here there should would could".split()
)


def parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS]


def row_weight(row: dict) -> float:
    return ROLE_WEIGHT.get(row["human_role"], 0.0) * ACTOR_WEIGHT.get(row["actor"], 0.0)


def sessions(rows: list[dict]) -> list[dict]:
    """One Claude session is one task. Subagent rows (`<session>:<agent>`) belong to their parent session."""
    by_session: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        # Keyed by person too, so rows posted under a colleague's session id cannot change that session.
        by_session.setdefault((row["person"], row["source_id"].split(":")[0]), []).append(row)
    result = []
    for (person, source_id), session_rows in by_session.items():
        session_rows.sort(key=lambda r: r["at"])
        task = next((r["task"] for r in session_rows if r.get("task")), None) or session_rows[0]["topic"].replace("-", " ")
        text = " ".join([task] + [r["topic"].replace("-", " ") for r in session_rows] + [r["why"] or "" for r in session_rows])
        result.append({
            "source_id": source_id,
            "task": task,
            "person": person,
            "rows": session_rows,
            "words": Counter(words(text)),
        })
    return result


def similarities(query: str, candidates: list[dict]) -> list[float]:
    docs = [Counter(words(query))] + [c["words"] for c in candidates]
    df = Counter(w for doc in docs for w in doc)
    vectors = []
    for doc in docs:
        vec = {w: n * (math.log((len(docs) + 1) / (df[w] + 1)) + 1) for w, n in doc.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({w: v / norm for w, v in vec.items()})
    query_vec = vectors[0]
    return [sum(query_vec.get(w, 0.0) * v for w, v in vec.items()) for vec in vectors[1:]]


def who_knows(query: str, rows: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    candidates = sessions(rows)
    relevant = [(s, sim) for s, sim in zip(candidates, similarities(query, candidates)) if sim >= MIN_SIMILARITY]

    people: dict[str, dict] = {}
    claude_alone = human_reasoning = 0
    for session, sim in relevant:
        for row in session["rows"]:
            weight = row_weight(row)
            if weight == 0:
                claude_alone += 1
                continue
            human_reasoning += 1
            # Rows after a fixed demo "now" (WHOKNOWS_NOW) are live captures, so they count as now.
            at = min(parse_at(row["at"]), now)
            contribution = sim * weight * math.exp(-(now - at).total_seconds() / 86400 / DECAY_DAYS)
            person = people.setdefault(row["person"], {
                "person": row["person"], "raw": 0.0, "last_reasoned": at, "roles": Counter(), "evidence": [],
            })
            person["raw"] += contribution
            person["last_reasoned"] = max(person["last_reasoned"], at)
            person["roles"][row["human_role"]] += 1
            if row["why"]:
                person["evidence"].append({
                    "why": row["why"], "role": row["human_role"], "at": row["at"],
                    "task": session["task"], "source_id": session["source_id"], "weight": contribution,
                })

    ranked = []
    for person in people.values():
        person["score"] = round(1 - math.exp(-person.pop("raw")), 3)
        person["evidence"] = sorted(person["evidence"], key=lambda e: -e["weight"])[:3]
        person["days_since"] = (now - person["last_reasoned"]).days
        person["last_reasoned"] = person["last_reasoned"].isoformat()
        person["roles"] = dict(person["roles"])
        ranked.append(person)
    ranked.sort(key=lambda p: -p["score"])

    recent = [p for p in ranked if p["days_since"] <= FADING_DAYS]
    knowers = [p for p in recent if p["score"] >= MIN_SCORE] or recent[:1]
    if not relevant:
        status = "unknown"
    elif not ranked:
        status = "dark"
    elif not recent:
        status = "fading"
    elif len(knowers) == 1:
        status = "single_point"
    else:
        status = "healthy"

    return {
        "query": query,
        "status": status,
        "people": ranked,
        "knowers": [p["person"] for p in knowers],
        "similar_sessions": len(relevant),
        "claude_alone": claude_alone,
        "human_reasoning": human_reasoning,
        "top_session": max(relevant, key=lambda r: r[1])[0]["task"] if relevant else None,
    }
