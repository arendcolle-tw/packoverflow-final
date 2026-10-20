from datetime import datetime, timezone

REASONING_ROLES = {"decided", "corrected", "explained_why", "answered_question"}
RESETS_CLOCK = {"confirmed", "likely"}
STATUS_RANK = {"dark": 0, "single_point": 1, "fading": 2, "healthy": 3}


def parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def certainty(signal: dict) -> str:
    if signal["actor"] == "agent" or signal["human_role"] not in REASONING_ROLES:
        return "ai"
    if signal["actor"] == "unknown":
        return "uncertain"
    return "confirmed" if signal["source"] == "meeting" else "likely"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _group(signals: list[dict], aliases: dict[str, str] | None) -> dict[str, list[dict]]:
    aliases = aliases or {}
    groups: dict[str, list[dict]] = {}
    for signal in signals:
        topic = aliases.get(signal["topic"], signal["topic"])
        groups.setdefault(topic, []).append(signal)
    return groups


def _summarize_topic(topic: str, signals: list[dict], now: datetime, fading_days: int) -> dict:
    levels = [certainty(s) for s in signals]
    resetting = sorted(
        (s for s, level in zip(signals, levels) if level in RESETS_CLOCK), key=lambda s: parse_at(s["at"])
    )

    reasoners: dict[str, dict] = {}
    for signal in resetting:
        entry = reasoners.setdefault(signal["person"], {"person": signal["person"], "count": 0, "last_at": None, "last_why": None})
        entry["count"] += 1
        entry["last_at"] = _iso(parse_at(signal["at"]))
        if signal["why"]:
            entry["last_why"] = signal["why"]

    last = parse_at(resetting[-1]["at"]) if resetting else None
    days_since = max(0, (now - last).days) if last else None

    if last is None:
        status = "dark"
    elif days_since > fading_days:
        status = "fading"
    elif len(reasoners) == 1:
        status = "single_point"
    else:
        status = "healthy"

    return {
        "topic": topic,
        "status": status,
        "ai_count": levels.count("ai"),
        "human_count": len(resetting),
        "uncertain_count": levels.count("uncertain"),
        "last_human_reasoning_at": _iso(last) if last else None,
        "days_since": days_since,
        "reasoners": sorted(reasoners.values(), key=lambda r: -r["count"]),
    }


def compute_topics(
    signals: list[dict], now: datetime, fading_days: int = 14, aliases: dict[str, str] | None = None
) -> list[dict]:
    topics = [_summarize_topic(t, rows, now, fading_days) for t, rows in _group(signals, aliases).items()]
    return sorted(topics, key=lambda t: (STATUS_RANK[t["status"]], -t["ai_count"], t["topic"]))


def topic_detail(
    signals: list[dict], topic: str, now: datetime, fading_days: int = 14, aliases: dict[str, str] | None = None
) -> dict | None:
    rows = _group(signals, aliases).get(topic)
    if not rows:
        return None
    detail = _summarize_topic(topic, rows, now, fading_days)
    detail["signals"] = [
        {
            "id": s["id"],
            "person": s["person"],
            "at": s["at"],
            "human_role": s["human_role"],
            "why": s["why"],
            "certainty": certainty(s),
            "source": s["source"],
            "source_id": s["source_id"],
        }
        for s in sorted(rows, key=lambda s: parse_at(s["at"]), reverse=True)
    ]
    return detail


def summarize(topics: list[dict]) -> dict:
    by_status = {status: 0 for status in STATUS_RANK}
    for topic in topics:
        by_status[topic["status"]] += 1
    return {
        "ai_count": sum(t["ai_count"] for t in topics),
        "human_count": sum(t["human_count"] for t in topics),
        "topic_count": len(topics),
        "by_status": by_status,
    }
