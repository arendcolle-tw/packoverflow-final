"""Map Tristan's recorder rows (ideas/tristan/data/signals-*.json) onto the knowledge-graph POST /signals body.

Dry run by default: prints the payload summary and writes it to --out. Posts only with --post URL and --token.
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ideas" / "tristan"))
from recorder.sessions import scrub  # noqa: E402  same redaction the recorder applied on the laptop

REQUIRED = ("id", "person", "topic", "source", "source_id", "at", "human_role", "actor")
ROLES = {"decided", "corrected", "explained_why", "answered_question", "accepted_as_is"}
ACTORS = {"human", "agent", "unknown"}
# Same sets as ideas/alberic/knowledge_graph/graph.py; tests/test_to_graph.py checks the graph accepts our output.
SOURCES = {"claude_session", "meeting", "copilot_chat", "copilot_cli", "m365_copilot", "screenshot", "mcp_record"}


def to_signal(row: dict) -> tuple[dict | None, str | None]:
    """Return (signal, None) or (None, reason it was dropped)."""
    if not isinstance(row, dict):
        return None, "not an object"
    missing = [f for f in REQUIRED if not isinstance(row.get(f), str) or not row[f]]
    if missing:
        return None, f"missing {', '.join(missing)}"
    if row["human_role"] not in ROLES or row["actor"] not in ACTORS:
        return None, "unknown human_role or actor"
    if row["source"] not in SOURCES:
        return None, f"unknown source {row['source']}"
    try:
        datetime.fromisoformat(row["at"].replace("Z", "+00:00"))
    except ValueError:
        return None, "at is not an ISO time"
    why = row.get("why")
    if why is not None and not isinstance(why, str):
        return None, "why is not text"
    signal = {f: row[f] for f in REQUIRED}
    # The service requires person but overrides it with the member token's person.
    signal["why"] = scrub(why)[:200] if why and why.strip() else None
    for field, limit in (("task", 80), ("app", 300)):
        if isinstance(row.get(field), str) and row[field].strip():
            signal[field] = scrub(row[field])[:limit]
    return signal, None


def convert(rows: list) -> tuple[list[dict], list[str]]:
    signals, dropped, seen = [], [], {}
    for row in rows:
        signal, reason = to_signal(row)
        if signal is None:
            dropped.append(f"{(row or {}).get('id', '?') if isinstance(row, dict) else '?'}: {reason}")
            continue
        seen[signal["id"]] = len(signals)  # later row wins per id, like the graph
        signals.append(signal)
    return [signals[i] for i in sorted(seen.values())], dropped


def post(signals: list[dict], url: str, token: str, chunk: int = 1000) -> list[dict]:
    if not url.startswith(("https://", "http://")):
        raise ValueError("--post needs an http(s) URL")
    results = []
    for start in range(0, len(signals), chunk):
        request = urllib.request.Request(
            url.rstrip("/") + "/signals",
            data=json.dumps(signals[start:start + chunk], ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            results.append(json.load(response))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="recorder output, e.g. ideas/tristan/data/signals-tristan.json")
    parser.add_argument("--out", type=Path, help="write the /signals body here")
    parser.add_argument("--post", metavar="URL", help="knowledge-graph service base URL")
    parser.add_argument("--token", help="member token; the service sets person from it")
    args = parser.parse_args()
    if args.post and not args.token:
        parser.error("--post needs --token")

    rows = [r for f in args.files for r in json.loads(f.read_text())]
    signals, dropped = convert(rows)
    print(f"{len(rows)} rows in, {len(signals)} signals out, {len(dropped)} dropped", file=sys.stderr)
    for line in dropped[:10]:
        print(f"  dropped {line}", file=sys.stderr)
    if args.out:
        args.out.write_text(json.dumps(signals, indent=1, ensure_ascii=False) + "\n")
    if args.post:
        print(json.dumps(post(signals, args.post, args.token)), file=sys.stderr)


if __name__ == "__main__":
    main()
