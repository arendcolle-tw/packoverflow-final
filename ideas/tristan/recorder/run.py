import argparse
import fcntl
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from recorder.classify import ACTORS, ROLES, classify
from recorder.sessions import scrub, session_files, session_items

CACHE = Path.home() / ".cache" / "packoverflow-recorder" / "cache.json"
DATA = Path(__file__).resolve().parent.parent / "data"


def verbatim_why(why: str | None, text: str) -> str | None:
    """Keep a why only when it is the human's own words, so the model can't put reasons in their mouth."""
    quote = (why or "").strip().strip("\"'“”").strip()
    if not quote or " ".join(quote.split()).casefold() not in " ".join(text.split()).casefold():
        return None
    return scrub(quote)[:200]


def to_rows(items: list[dict], labels: dict[str, dict], tasks: dict[str, str], person: str) -> list[dict]:
    rows = []
    for item in items:
        label = labels.get(item["key"])
        if not label or label.get("human_role") not in ROLES or label.get("actor") not in ACTORS:
            continue
        topic = re.sub(r"[^a-z0-9]+", "-", str(label.get("topic", "")).lower()).strip("-")[:60].strip("-")
        if not topic:
            continue
        rows.append({
            "id": item["key"],
            "person": person,
            "topic": topic,
            "source": "claude_session",
            "source_id": item["source_id"],
            "at": item["at"],
            "human_role": "accepted_as_is" if item["is_agent"] else label["human_role"],
            "why": None if item["is_agent"] else verbatim_why(label.get("why"), item["text"]),
            "actor": "agent" if item["is_agent"] else label["actor"],
            "task": scrub(tasks.get(item["session"]) or "")[:80] or None,
        })
    return sorted(rows, key=lambda r: r["at"])


def load_cache(path: Path) -> dict:
    try:
        cache = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    return {"labels": cache.get("labels", {}), "tasks": cache.get("tasks", {})}


def save_cache(path: Path, labels: dict[str, dict], tasks: dict[str, str]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Hook workers for parallel sessions share this file: reload under a lock, then swap it in atomically.
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = load_cache(path)
        cache["labels"].update(labels)
        cache["tasks"] = {**tasks, **{s: t for s, t in cache["tasks"].items() if t}}
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False))
        os.replace(tmp, path)
    return cache


def record(files: list[Path], person: str, out: Path, cache_path: Path = CACHE, workers: int = 4) -> list[dict]:
    cache = load_cache(cache_path)
    items = [i for f in files for i in session_items(f)]
    todo = [i for i in items if i["key"] not in cache["labels"]]
    if todo:
        cache = save_cache(cache_path, *classify(todo, workers))

    rows = to_rows(items, cache["labels"], cache["tasks"], person)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")

    roles = Counter("agent" if r["actor"] == "agent" else r["human_role"] for r in rows)
    reasoned = sum(n for role, n in roles.items() if role in {"decided", "corrected", "explained_why"})
    print(f"{len(files)} sessions, {len(items)} turns, {len(todo)} newly labelled, {len(rows)} rows -> {out}")
    print(f"Claude alone {roles['accepted_as_is'] + roles['agent']} · human reasoning {reasoned} · "
          f"with a verbatim why {sum(1 for r in rows if r['why'])}")
    return rows


def push(rows: list[dict], url: str, token: str, chunk: int = 1000) -> tuple[int, int]:
    stored = skipped = 0
    for start in range(0, len(rows), chunk):
        request = urllib.request.Request(
            url.rstrip("/") + "/api/signals",
            data=json.dumps(rows[start:start + chunk], ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        stored += result["stored"]
        skipped += result["skipped"]
    return stored, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn your Claude Code sessions into knowledge signal rows.")
    parser.add_argument("--person", required=True, help="your first name, e.g. tristan")
    parser.add_argument("--projects-dir", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--match", default="packoverflow", help="only session folders whose name contains this")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--push", metavar="URL", help="also send the rows to this Who knows store")
    parser.add_argument("--token", default=os.environ.get("WHOKNOWS_TOKEN"), help="store token, default $WHOKNOWS_TOKEN")
    args = parser.parse_args()
    if args.push and not args.token:
        parser.error("--push needs --token or WHOKNOWS_TOKEN")

    person = " ".join(args.person.split()).lower()
    out = args.out or DATA / f"signals-{person}.json"
    rows = record(session_files(args.projects_dir, args.match), person, out, workers=args.workers)
    if not args.push:
        return
    try:
        stored, skipped = push(rows, args.push, args.token)
    except urllib.error.HTTPError as error:
        sys.exit(f"push to {args.push} failed: HTTP {error.code} {error.read().decode(errors='replace')[:200]}; rows kept in {out}")
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"push to {args.push} failed: {error}; rows kept in {out}")
    print(f"pushed {len(rows)} rows: {stored} stored, {skipped} skipped -> {args.push}")


if __name__ == "__main__":
    main()
