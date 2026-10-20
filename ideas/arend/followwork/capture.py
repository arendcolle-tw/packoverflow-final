"""Shared capture rules: opt-in, pause, allowlist, blocklist, redaction.

The Mac capture loop and the demo replay both push frames through
process_frame, so the demo exercises exactly the same rules as live capture.
"""
import json
import os
import re

from .redact import count_redactions, redact

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = os.path.join(ROOT, "local")
EVENTS = os.path.join(LOCAL, "events.jsonl")
STATS = os.path.join(LOCAL, "stats.json")
PAUSE = os.path.join(ROOT, "PAUSE")
MAX_TEXT = 4000


def _read_list(name):
    with open(os.path.join(ROOT, name)) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


class Rules:
    def __init__(self):
        self.allow = {a.lower() for a in _read_list("allowlist.txt")}
        words = _read_list("blocklist.txt")
        self.block = re.compile(r"(?i)\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")

    def verdict(self, app, title):
        if self.block.search(app or "") or self.block.search(title or ""):
            return "blocked"
        if (app or "").lower() not in self.allow:
            return "not_allowed"
        return "ok"


def paused():
    return os.path.exists(PAUSE)


def process_frame(frame, rules, stats):
    """Return a redacted event dict, or None when the frame must not be kept.

    frame: {ts, app, title, text, clipboard?}. The text is OCR output; the
    image it came from is already deleted by the caller.
    """
    v = rules.verdict(frame.get("app"), frame.get("title"))
    if v != "ok":
        stats[v] = stats.get(v, 0) + 1
        return None
    ev = {
        "ts": frame["ts"],
        "app": frame["app"],
        "title": redact(frame.get("title", "")),
        "text": redact(frame.get("text", ""))[:MAX_TEXT],
    }
    if frame.get("clipboard"):
        ev["clipboard"] = redact(frame["clipboard"])[:200]
    n = sum(count_redactions(ev.get(k)) for k in ("title", "text", "clipboard"))
    stats["redacted"] = stats.get("redacted", 0) + n
    stats["kept"] = stats.get("kept", 0) + 1
    return ev


def load_stats():
    try:
        with open(STATS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_stats(stats):
    os.makedirs(LOCAL, exist_ok=True)
    with open(STATS, "w") as f:
        json.dump(stats, f)


def append_event(ev):
    os.makedirs(LOCAL, exist_ok=True)
    with open(EVENTS, "a") as f:
        f.write(json.dumps(ev) + "\n")


def load_events():
    try:
        with open(EVENTS) as f:
            return [json.loads(ln) for ln in f if ln.strip()]
    except OSError:
        return []


def write_events(events):
    os.makedirs(LOCAL, exist_ok=True)
    with open(EVENTS, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
