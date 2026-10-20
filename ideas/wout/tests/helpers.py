import itertools
import json
from pathlib import Path

_ids = itertools.count()


def row(**kw) -> dict:
    base = {
        "id": f"s1:m{next(_ids)}",
        "person": "wout",
        "topic": "aikido",
        "source": "claude_session",
        "source_id": "s1",
        "at": "2026-10-20T10:00:00Z",
        "human_role": "decided",
        "why": None,
        "actor": "human",
    }
    return {**base, **kw}


def write(dir: Path, name: str, rows: list[dict]) -> Path:
    path = dir / name
    path.write_text(json.dumps(rows))
    return path
