"""Review screen on 127.0.0.1. Nothing reaches out/procedures.json until Share.

    python3 -m followwork.review           # review your own captured events
    python3 -m followwork.review --demo    # seed the fixture task, show Reset
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import capture, demo
from .extract import extract
from .polish import polish

OUT = os.path.join(capture.ROOT, "out", "procedures.json")
DECISIONS = os.path.join(capture.LOCAL, "decisions.json")
PUBLIC = ("id", "topic", "title", "steps", "apps", "captured_at")


def _read(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def procedures():
    decisions = _read(DECISIONS, {})
    shared = {p["id"]: p for p in _read(OUT, [])}
    items = []
    for p in extract(capture.load_events()):
        p = polish(p)
        status = decisions.get(p["id"], "new")
        if status == "forgotten":
            continue
        items.append(dict(p, status=status, shared=shared.get(p["id"])))
    return items


def share(pid, credit):
    proc = next((p for p in procedures() if p["id"] == pid), None)
    if not proc:
        return None
    item = {k: proc[k] for k in PUBLIC}
    if credit and credit.strip():
        item["credit"] = credit.strip()[:80]
    item["source"] = "screen"
    out = [p for p in _read(OUT, []) if p["id"] != pid] + [item]
    _write(OUT, out)
    _decide(pid, "shared")
    return item


def _decide(pid, status):
    d = _read(DECISIONS, {})
    d[pid] = status
    _write(DECISIONS, d)


def forget(pid):
    """Delete the underlying events from this laptop, not just hide the card."""
    proc = next((p for p in procedures() if p["id"] == pid), None)
    if not proc:
        return 0
    lo, hi = proc["_span"]
    events = capture.load_events()
    keep = [e for e in events if not lo <= e["ts"] <= hi]
    capture.write_events(keep)
    _decide(pid, "forgotten")
    return len(events) - len(keep)


def reset_demo():
    demo_ids = {p["id"] for p in procedures()}
    stats = demo.reset()
    demo_ids |= {p["id"] for p in extract(capture.load_events())}
    _write(OUT, [p for p in _read(OUT, []) if p["id"] not in demo_ids])
    return stats


class Handler(BaseHTTPRequestHandler):
    demo_mode = False

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _local_host(self):
        # Blocks DNS rebinding: only answer requests addressed to this machine.
        host = self.headers.get("Host", "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._local_host():
            return self._send(403, {"error": "local only"})
        if self.path == "/":
            return self._send(200, PAGE.replace("__DEMO__", "true" if self.demo_mode else "false"),
                              "text/html")
        if self.path == "/api/state":
            items = [{k: v for k, v in p.items() if k != "_span"} for p in procedures()]
            return self._send(200, {"items": items, "stats": capture.load_stats(),
                                    "paused": capture.paused(), "out": os.path.relpath(OUT, capture.ROOT)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # Same-origin only: a page on another site must not be able to press Share.
        if not self._local_host():
            return self._send(403, {"error": "local only"})
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and origin.split("//", 1)[-1] != host:
            return self._send(403, {"error": "cross-origin"})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        pid = body.get("id", "")
        if self.path == "/api/share":
            item = share(pid, body.get("credit"))
            return self._send(200 if item else 404, {"written": item})
        if self.path == "/api/skip":
            _decide(pid, "skipped")
            return self._send(200, {"ok": True})
        if self.path == "/api/forget":
            return self._send(200, {"deleted_events": forget(pid)})
        if self.path == "/api/reset" and self.demo_mode:
            return self._send(200, {"stats": reset_demo()})
        self._send(404, {"error": "not found"})


PAGE = open(os.path.join(os.path.dirname(__file__), "review.html")).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="seed the fixture task and show Reset")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    Handler.demo_mode = args.demo
    if args.demo:
        reset_demo()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Review screen: http://127.0.0.1:{args.port}  (local only, Ctrl+C to stop)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
