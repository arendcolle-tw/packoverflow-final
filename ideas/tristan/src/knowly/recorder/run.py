import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from knowly.recorder.classify import ACTORS, ROLES, classify
from knowly.recorder.sessions import scrub, session_files, session_items
from knowly.recorder.summarise import compact, summarise, to_row

CACHE = Path.home() / ".cache" / "knowly" / "cache.json"
SUMMARIES = CACHE.with_name("summaries.json")


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


def locked_update(path: Path, update) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Hook workers for parallel sessions share these files: reload under a lock, then replace the file atomically.
    with open(path.with_suffix(".lock"), "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = update(path)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False))
        os.replace(tmp, path)
    return cache


def save_cache(path: Path, labels: dict[str, dict], tasks: dict[str, str]) -> dict:
    def update(path: Path) -> dict:
        cache = load_cache(path)
        cache["labels"].update(labels)
        cache["tasks"] = {**tasks, **{s: t for s, t in cache["tasks"].items() if t}}
        return cache

    return locked_update(path, update)


def load_summaries(path: Path) -> dict:
    try:
        cache = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return cache if isinstance(cache, dict) else {}


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


def record_summaries(files: list[Path], person: str, out: Path, cache_path: Path = SUMMARIES, workers: int = 4) -> list[dict]:
    """One row per session. A session is summarised again only when its compacted text changed."""
    cache = load_summaries(cache_path)
    texts = {f: text for f in files if (text := compact(f))}
    digests = {f: hashlib.sha256(text.encode()).hexdigest() for f, text in texts.items()}
    todo = [f for f in texts if (cache.get(f.stem) or {}).get("sha256") != digests[f]]
    fresh = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(summarise, texts[f]): f for f in todo}
        for n, future in enumerate(as_completed(futures), 1):
            f = futures[future]
            try:
                row = to_row(f, future.result(), person)
            except (subprocess.SubprocessError, ValueError, KeyError) as error:
                print(f"[{n}/{len(todo)}] session {f.stem[:8]} failed: {error}", file=sys.stderr)
                continue
            fresh[f.stem] = {"sha256": digests[f], "summarised_at": time.time(), "row": row}
            print(f"[{n}/{len(todo)}] session {f.stem[:8]}: {row['human_role']}, {row['task']}", file=sys.stderr)
    if fresh:
        cache = locked_update(cache_path, lambda path: {**load_summaries(path), **fresh})

    # A session whose new summary failed keeps its previous row.
    rows = sorted(({**cache[f.stem]["row"], "person": person} for f in texts if f.stem in cache), key=lambda r: r["at"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    roles = Counter(r["human_role"] for r in rows)
    print(f"{len(files)} sessions, {len(texts)} with human turns, {len(fresh)} newly summarised, {len(rows)} rows -> {out}")
    print(f"Claude alone {roles['accepted_as_is']} · human reasoning {len(rows) - roles['accepted_as_is']}")
    return rows


def check_url(url: str) -> None:
    """Only send member tokens over HTTPS, or plain HTTP to this machine for local testing."""
    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if not parts.hostname or parts.username or not (parts.scheme == "https" or (parts.scheme == "http" and local)):
        raise ValueError(f"refusing to send to {url!r}: use an https:// URL")


def push(rows: list[dict], url: str, token: str, chunk: int = 1000) -> tuple[int, int]:
    check_url(url)
    stored = skipped = 0
    for start in range(0, len(rows), chunk):
        batch = json.dumps(rows[start:start + chunk], ensure_ascii=False).encode()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        with urllib.request.urlopen(urllib.request.Request(url.rstrip("/") + "/signals", batch, headers), timeout=30) as response:
            result = json.load(response)
        stored += result["added"] + result["updated"]
        skipped += len(result["rejected"])
        if result["rejected"]:
            print(f"rejected: {result['rejected'][0]}", file=sys.stderr)
    return stored, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn your Claude Code sessions into knowledge signal rows.")
    parser.add_argument("--person", required=True, help="your first name, e.g. tristan")
    parser.add_argument("--projects-dir", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--match", default="packoverflow", help="only session folders whose name contains this")
    parser.add_argument("--mode", choices=["summary", "turns"], default="summary",
                        help="summary: one row per session with Claude's summary of your decisions (default); "
                             "turns: one row per human turn")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--push", metavar="URL", help="also send the rows to the knowledge graph at this URL")
    parser.add_argument("--token", default=os.environ.get("KNOWLY_TOKEN"), help="graph member token, default $KNOWLY_TOKEN")
    args = parser.parse_args()
    if args.push and not args.token:
        parser.error("--push needs --token or KNOWLY_TOKEN")

    person = " ".join(args.person.split()).lower()
    out = args.out or CACHE.with_name(f"signals-{person}.json")
    files = session_files(args.projects_dir, args.match)
    rows = (record_summaries if args.mode == "summary" else record)(files, person, out, workers=args.workers)
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
