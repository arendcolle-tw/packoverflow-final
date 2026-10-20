import re
import uuid
from datetime import datetime, timezone

from knowledge_clock.clock import RESETS_CLOCK, certainty, parse_at
from knowledge_clock.store import validate

KIND_TO_ROLE = {"decided": "decided", "corrected": "corrected", "explained_why": "explained_why", "prompted": "accepted_as_is"}
MAX_ITEMS = 50


def person_key(name: str) -> str | None:
    key = " ".join(name.split()).lower()
    return key if 0 < len(key) <= 40 else None


def normalize_topic(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60].strip("-")


def _item_to_row(item: dict, person: str, now: datetime) -> dict:
    kind = item.get("kind")
    if kind not in KIND_TO_ROLE:
        raise ValueError(f"kind must be one of {', '.join(KIND_TO_ROLE)}")
    topic = normalize_topic(str(item.get("topic") or ""))
    if not topic:
        raise ValueError("topic is empty")
    why = None
    if kind != "prompted":
        why = (item.get("why") or "").strip()
        if not why:
            raise ValueError("why is required for decided, corrected and explained_why, in the user's own words")
        if len(why) > 200:
            raise ValueError("why is longer than 200 characters")
    try:
        at = parse_at(item["happened_at"]) if item.get("happened_at") else now
    except (ValueError, TypeError):
        raise ValueError("happened_at is not an ISO time") from None
    row = {
        "id": f"mcp-{uuid.uuid4().hex}",
        "person": person,
        "topic": topic,
        "source": "claude_session",
        "source_id": f"mcp-{person.replace(' ', '-')}-{topic}",
        "at": at.astimezone(timezone.utc).isoformat(),
        "human_role": KIND_TO_ROLE[kind],
        "why": why,
        "actor": "human",
    }
    if not validate(row):
        raise ValueError("not a valid signal")
    return row


def items_to_rows(items: list[dict], person: str, now: datetime) -> tuple[list[dict], list[str]]:
    if len(items) > MAX_ITEMS:
        return [], [f"at most {MAX_ITEMS} items per call"]
    rows, errors = [], []
    for i, item in enumerate(items):
        try:
            rows.append(_item_to_row(item, person, now))
        except ValueError as error:
            errors.append(f"item {i}: {error}")
    return rows, errors


def person_view(signals: list[dict], person: str, now: datetime) -> dict:
    reasoners_by_topic: dict[str, set[str]] = {}
    mine: dict[str, list[dict]] = {}
    for signal in signals:
        if certainty(signal) in RESETS_CLOCK:
            reasoners_by_topic.setdefault(signal["topic"], set()).add(signal["person"])
        if signal["person"] == person:
            mine.setdefault(signal["topic"], []).append(signal)

    reasoned = prompted = 0
    knows, only_prompts = [], []
    for topic, rows in mine.items():
        resetting = sorted((r for r in rows if certainty(r) in RESETS_CLOCK), key=lambda r: parse_at(r["at"]))
        reasoned += len(resetting)
        prompted += sum(1 for r in rows if certainty(r) == "ai")
        if not resetting:
            only_prompts.append(topic)
            continue
        whys = [r["why"] for r in resetting if r["why"]]
        knows.append({
            "topic": topic,
            "latest_why": whys[-1] if whys else None,
            "last_at": parse_at(resetting[-1]["at"]).astimezone(timezone.utc).isoformat(),
            "only_you": reasoners_by_topic[topic] == {person},
        })

    knows.sort(key=lambda k: k["last_at"], reverse=True)
    knows.sort(key=lambda k: not k["only_you"])
    return {
        "person": person,
        "headline": f"Claude handled {prompted} of your requests on its own. You reasoned {reasoned} times.",
        "reasoned": reasoned,
        "prompted": prompted,
        "knows": knows,
        "only_prompts": sorted(only_prompts),
    }
