import json
from pathlib import Path

from knowledge_clock.clock import parse_at

FIELDS = {"id", "person", "topic", "source", "source_id", "at", "human_role", "why", "actor"}
ROLES = {"decided", "corrected", "explained_why", "answered_question", "accepted_as_is"}
SOURCES = {"claude_session", "meeting"}
ACTORS = {"human", "agent", "unknown"}


def validate(row: dict) -> bool:
    if not isinstance(row, dict) or not FIELDS <= row.keys():
        return False
    if not all(isinstance(row[f], str) and row[f] for f in FIELDS - {"why"}):
        return False
    if row["human_role"] not in ROLES or row["source"] not in SOURCES or row["actor"] not in ACTORS:
        return False
    if row["why"] is not None and not isinstance(row["why"], str):
        return False
    try:
        parse_at(row["at"])
    except ValueError:
        return False
    return True


def load_signals(paths: list[Path]) -> tuple[list[dict], int]:
    by_id: dict[str, dict] = {}
    skipped = 0
    for path in paths:
        if not path.exists():
            continue
        try:
            rows = json.loads(path.read_text())
        except json.JSONDecodeError:
            rows = None
        if not isinstance(rows, list):
            skipped += 1
            continue
        valid = [r for r in rows if validate(r)]
        skipped += len(rows) - len(valid)
        replaced_sources = {r["source_id"] for r in valid}
        by_id = {i: r for i, r in by_id.items() if r["source_id"] not in replaced_sources}
        by_id.update({r["id"]: r for r in valid})
    return list(by_id.values()), skipped


def _load_mapping(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_aliases(path: Path) -> dict[str, str]:
    return _load_mapping(path)


def load_whys(path: Path) -> dict[str, str]:
    return _load_mapping(path)


def save_why(path: Path, row_id: str, why: str) -> None:
    whys = load_whys(path)
    whys[row_id] = why
    path.write_text(json.dumps(whys, indent=1, ensure_ascii=False))


def apply_whys(rows: list[dict], whys: dict[str, str]) -> list[dict]:
    return [{**r, "why": whys[r["id"]]} if r["id"] in whys else r for r in rows]
