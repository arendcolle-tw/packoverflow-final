"""Optional: let Claude polish rule-based names. Off unless FOLLOW_WORK_CLAUDE=1.

Only the rule-based title and step names are sent (already redacted, no OCR
text). Results are cached in local/polish_cache.json. Any failure falls back
to the rule-based names, so the demo never depends on the API.
"""
import hashlib
import json
import os
import urllib.request

from . import capture

CACHE = os.path.join(capture.LOCAL, "polish_cache.json")
MODEL = os.environ.get("FOLLOW_WORK_MODEL", "claude-haiku-5-5")


def _load():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def polish(proc):
    if os.environ.get("FOLLOW_WORK_CLAUDE") != "1" or not os.environ.get("ANTHROPIC_API_KEY"):
        return proc
    key = hashlib.sha1(json.dumps([proc["title"], proc["steps"]]).encode()).hexdigest()
    cache = _load()
    if key not in cache:
        prompt = ("Rewrite this procedure for a payroll consultant's team wiki. Keep the same "
                  "number of steps, same order, short imperative English, no new facts. "
                  'Answer only JSON {"title": str, "steps": [str]}.\n'
                  + json.dumps({"title": proc["title"], "steps": proc["steps"]}))
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({"model": MODEL, "max_tokens": 600,
                             "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                text = json.load(r)["content"][0]["text"]
            got = json.loads(text[text.index("{"):text.rindex("}") + 1])
            if len(got["steps"]) != len(proc["steps"]):
                return proc
            cache[key] = got
            os.makedirs(capture.LOCAL, exist_ok=True)
            with open(CACHE, "w") as f:
                json.dump(cache, f)
        except Exception:
            return proc
    return dict(proc, title=cache[key]["title"], steps=cache[key]["steps"])
