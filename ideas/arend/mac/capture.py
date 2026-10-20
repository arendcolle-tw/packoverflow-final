"""Step 2, the capture loop (Mac only). Run from ideas/arend:

    bash mac/build.sh            # once
    python3 mac/capture.py       # starts recording, prints a visible line

Every 2 seconds: read the frontmost window. Blocked or non-allowlisted
windows are skipped before any screenshot is taken. Otherwise take a shot of
that one window into a private temp folder, OCR it, delete the image at once,
redact, and append {ts, app, title, text, clipboard} to local/events.jsonl.
OCR runs when the window changes, and every 6 seconds inside the same window
so in-window changes (a filter, a total) are seen; identical text is not
stored twice.

Pause: press p (Enter), or create a file named PAUSE in ideas/arend. q stops.
Needs Screen Recording permission for your terminal app (System Settings,
Privacy & Security, Screen Recording). macOS asks the first time.
"""
import os
import select
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json  # noqa: E402

from followwork import capture  # noqa: E402

FOW = os.path.join(capture.LOCAL, "bin", "fow")
TICK = 2.0
SAME_WINDOW_EVERY = 3  # ticks


def front():
    out = subprocess.run([FOW, "front"], capture_output=True, text=True, timeout=5).stdout
    return json.loads(out or "{}")


def ocr_window(window_id, tmpdir):
    path = os.path.join(tmpdir, "w.png")
    try:
        subprocess.run(["screencapture", "-x", "-o", "-l", str(window_id), path],
                       check=True, timeout=10)
        return subprocess.run([FOW, "ocr", path], capture_output=True, text=True,
                              timeout=20).stdout
    finally:
        if os.path.exists(path):
            os.remove(path)  # the image never outlives this function


def clipboard():
    try:
        return subprocess.run([FOW, "clip"], capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return ""


def key_pressed():
    if not sys.stdin.isatty():
        return None
    r, _, _ = select.select([sys.stdin], [], [], 0)
    return sys.stdin.readline().strip().lower() if r else None


def main():
    if not os.path.exists(FOW):
        sys.exit("Run bash mac/build.sh first.")
    rules = capture.Rules()
    stats = capture.load_stats()
    tmpdir = tempfile.mkdtemp(prefix="fow-")
    os.chmod(tmpdir, 0o700)
    paused_by_key = False
    last_key, last_text, ticks = None, None, 0
    print("● recording: follow the work is capturing allowlisted windows as text.")
    print("  p + Enter pauses, q + Enter stops, or create ideas/arend/PAUSE.")
    try:
        while True:
            k = key_pressed()
            if k == "q":
                break
            if k == "p":
                paused_by_key = not paused_by_key
                print("❚❚ paused" if paused_by_key else "● recording")
            if paused_by_key or capture.paused():
                time.sleep(TICK)
                continue
            w = front()
            key = (w.get("app"), w.get("title"))
            ticks += 1
            if key == last_key and ticks % SAME_WINDOW_EVERY:
                time.sleep(TICK)
                continue
            if rules.verdict(*key) != "ok" or not w.get("window_id"):
                capture.process_frame(dict(w, ts=time.time(), text=""), rules, stats)
                last_key = key
                time.sleep(TICK)
                continue
            text = ocr_window(w["window_id"], tmpdir)
            if key != last_key or text != last_text:
                frame = {"ts": time.time(), "app": w["app"], "title": w["title"],
                         "text": text, "clipboard": clipboard()}
                ev = capture.process_frame(frame, rules, stats)
                if ev:
                    capture.append_event(ev)
                    print(f"  + {ev['app']}: {ev['title'][:60]}")
                capture.save_stats(stats)
            last_key, last_text = key, text
            time.sleep(TICK)
    finally:
        capture.save_stats(stats)
        os.rmdir(tmpdir) if not os.listdir(tmpdir) else None
        print("stopped. Review with: python3 -m followwork.review")


if __name__ == "__main__":
    main()
