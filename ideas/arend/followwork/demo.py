"""Demo mode: replay fixture frames through the real capture rules."""
import json
import os
import shutil
from datetime import datetime, timezone

from . import capture

FIXTURES = os.path.join(capture.ROOT, "fixtures", "frames.json")
DEMO_START = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc).timestamp()


def reset():
    """Wipe local state and replay the fixture task. Returns capture stats."""
    shutil.rmtree(capture.LOCAL, ignore_errors=True)
    rules = capture.Rules()
    stats = {}
    with open(FIXTURES) as f:
        frames = json.load(f)
    events = []
    for fr in frames:
        frame = dict(fr, ts=DEMO_START + fr["t"])
        ev = capture.process_frame(frame, rules, stats)
        if ev:
            events.append(ev)
    capture.write_events(events)
    capture.save_stats(stats)
    return stats


if __name__ == "__main__":
    print(reset())
    from .extract import extract
    for p in extract(capture.load_events()):
        print(json.dumps({k: v for k, v in p.items()}, indent=1))
