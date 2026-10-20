import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

from knowly.capture.turns import classify
from knowly.capture.run import CACHE, push, to_rows
from knowly.capture.sessions import scrub

STATE = CACHE.with_name("screenshots.json")
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
POLL_SECONDS = 5
# A file younger than this may still be half written by the screenshot tool or Finder.
SETTLE_SECONDS = 2
TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*([ap])\.?m\b)?", re.IGNORECASE)

SCHEMA = {
    "type": "object",
    "properties": {
        "app": {"type": "string", "description": "the chat app, lowercase: copilot, chatgpt, teams, claude, gemini or unknown"},
        "title": {"type": "string", "description": "the conversation title shown, or an empty string"},
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string", "enum": ["human", "assistant"]},
                    "text": {"type": "string"},
                    "time": {"type": ["string", "null"]},
                },
                "required": ["speaker", "text", "time"],
            },
        },
    },
    "required": ["app", "title", "turns"],
}

PROMPT = """Read the image {path} with the Read tool. It is a screenshot of a chat between a person and an AI assistant.

Return:
- app: the chat app, lowercase, one word such as copilot, chatgpt, teams, claude or gemini, or unknown.
- title: the conversation title if one is shown, else "".
- turns: every message from top to bottom. speaker is "human" for the person and "assistant" for the AI.
  text is the message transcribed exactly as shown, word for word, keeping typos. Never summarise, translate
  or correct it. A message cut off at the edge of the image: transcribe the visible part.
  time is the time shown with that message, exactly as displayed, or null.
Skip buttons, suggested prompts, disclaimers and other interface text."""


def read_image(image: Path, model: str) -> dict:
    # Runs in an empty temp dir so the Read tool can open the copy without a permission prompt.
    with tempfile.TemporaryDirectory() as cwd:
        copy = Path(cwd) / f"screenshot{image.suffix.lower()}"
        shutil.copyfile(image, copy)
        done = subprocess.run(
            ["claude", "-p", "--model", model, "--no-session-persistence", "--tools", "Read", "--allowedTools", "Read",
             "--output-format", "json", "--json-schema", json.dumps(SCHEMA)],
            input=PROMPT.format(path=copy), capture_output=True, text=True,
            cwd=cwd, timeout=600, check=True, env={**os.environ, "KNOWLY_CAPTURE_CHILD": "1"},
        )
    payload = json.loads(done.stdout)
    structured = payload.get("structured_output")
    if isinstance(structured, dict) and "turns" in structured:
        return structured
    text = payload.get("result", "")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def shown_at(shown, taken: datetime) -> str:
    match = TIME.search(str(shown or ""))
    at = taken
    if match:
        hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
        if match[4]:
            hour = hour % 12 + (12 if match[4].lower() == "p" else 0)
        if hour < 24 and minute < 60 and second < 60:
            at = taken.replace(hour=hour, minute=minute, second=second, microsecond=0)
            # A message cannot be sent after the screenshot was taken, so a later time is from the day before.
            if at > taken:
                at -= timedelta(days=1)
    return at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def transcript_items(turns: list, digest: str, taken: datetime, person: str) -> list[dict]:
    source_id = f"shot-{digest[:12]}"
    items, context = {}, ""
    for n, turn in enumerate(turns if isinstance(turns, list) else []):
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text") or "").strip()
        if turn.get("speaker") == "assistant":
            if text:
                context = scrub(text[-400:])
            continue
        if turn.get("speaker") != "human" or not text:
            continue
        text = scrub(text)
        # Keyed by the person and the turn's words only, so a retake or an overlapping scroll capture, where the
        # assistant message before a turn can be out of frame, gives the same row id and the store merges it.
        words = " ".join(re.findall(r"\w+", text.casefold()))
        key = "shot-turn-" + hashlib.sha256(f"{person}\n{words}".encode()).hexdigest()[:16]
        items.setdefault(key, {
            "source_id": source_id,
            "message_uuid": f"t{n}",
            "at": shown_at(turn.get("time"), taken),
            "text": text,
            "context": context,
            "is_agent": False,
            "key": key,
            "session": source_id,
        })
    return list(items.values())


def process(image: Path, digest: str, person: str, model: str) -> dict:
    taken = datetime.fromtimestamp(image.stat().st_mtime).astimezone()
    transcript = read_image(image, model)
    app = re.sub(r"[^a-z0-9]+", "-", str(transcript.get("app") or "").lower()).strip("-")[:40] or "unknown"
    title = str(transcript.get("title") or "").strip()
    items = transcript_items(transcript.get("turns"), digest, taken, person)
    labels, tasks = classify(items, source=f"{app} chat screenshot", assistant="the assistant") if items else ({}, {})
    if items and not labels:
        raise ValueError("the classifier returned no labels")
    source_id = f"shot-{digest[:12]}"
    rows = to_rows(items, labels, {source_id: tasks.get(source_id) or title}, person)
    return {"file": image.name, "app": app, "title": title, "rows": [{**r, "source": "screenshot", "app": app} for r in rows]}


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def record(folder: Path, person: str, out: Path, state_path: Path = STATE, model: str = "sonnet",
           failed: set | None = None, workers: int = 4) -> tuple[list[dict], int]:
    """Read every screenshot not seen before. Returns all of the person's screenshot rows and how many new images it read."""
    state = load_state(state_path)
    failed = set() if failed is None else failed
    found: dict[str, Path] = {}
    for image in sorted(folder.iterdir()):
        if image.suffix.lower() not in IMAGES or image.name.startswith("."):
            continue
        try:
            if image.is_file() and time.time() - image.stat().st_mtime >= SETTLE_SECONDS:
                found.setdefault(hashlib.sha256(image.read_bytes()).hexdigest(), image)
        except OSError:
            continue
    new = {digest: image for digest, image in found.items() if digest not in state and digest not in failed}

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, image, digest, person, model): digest for digest, image in new.items()}
        for future in as_completed(futures):
            digest = futures[future]
            try:
                state[digest] = future.result()
            except (subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
                # Kept out of the state file, so the next run tries it again.
                failed.add(digest)
                print(f"{new[digest].name}: not read: {error}", file=sys.stderr)
                continue
            done += 1
            state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = state_path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False))
            os.replace(tmp, state_path)
            print(f"{new[digest].name}: {state[digest]['app']}, {len(state[digest]['rows'])} rows", file=sys.stderr)

    latest = {r["id"]: r for entry in state.values() for r in entry["rows"] if r["person"] == person}
    rows = sorted(latest.values(), key=lambda r: r["at"])
    if done or not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    return rows, done


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn screenshots of AI chats into Knowly facts.")
    parser.add_argument("--person", required=True, help="your first name, e.g. tristan")
    parser.add_argument("--dir", type=Path, default=Path.home() / "Knowly" / "screenshots")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--model", default="sonnet", help="the Claude model that reads the screenshots")
    parser.add_argument("--push", nargs="?", const=os.environ.get("KNOWLY_URL", ""), metavar="URL",
                        help="also send the facts to the Knowly server at URL, default $KNOWLY_URL")
    parser.add_argument("--token", default=os.environ.get("KNOWLY_TOKEN"), help="your member token, default $KNOWLY_TOKEN")
    parser.add_argument("--watch", action="store_true", help=f"keep reading new screenshots, checking every {POLL_SECONDS} s")
    args = parser.parse_args()
    if args.push == "":
        parser.error("--push needs a URL or KNOWLY_URL")
    if args.push and not args.token:
        parser.error("--push needs --token or KNOWLY_TOKEN")

    person = " ".join(args.person.split()).lower()
    out = args.out or CACHE.with_name(f"facts-{person}-screenshots.json")
    args.dir.mkdir(parents=True, exist_ok=True)
    if args.watch:
        print(f"watching {args.dir}, Ctrl-C to stop", file=sys.stderr)
    failed: set[str] = set()
    try:
        while True:
            rows, done = record(args.dir, person, out, state_path=STATE, model=args.model, failed=failed)
            if done or not args.watch:
                print(f"{done} new screenshots read, {len(rows)} rows -> {out}")
            if args.push and (done or not args.watch):
                try:
                    stored, skipped = push(rows, args.push, args.token)
                    print(f"pushed {len(rows)} rows: {stored} stored, {skipped} skipped -> {args.push}")
                except (OSError, ValueError, KeyError) as error:
                    detail = (f"HTTP {error.code} {error.read().decode(errors='replace')[:200]}"
                              if isinstance(error, urllib.error.HTTPError) else error)
                    message = f"push to {args.push} failed: {detail}; rows kept in {out}"
                    if not args.watch:
                        sys.exit(message)
                    print(message, file=sys.stderr)
            if not args.watch:
                return
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
