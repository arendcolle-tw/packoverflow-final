import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = Path.home() / ".cache" / "packoverflow-recorder"
LOG = STATE / "hook.log"
DEFAULT_CONFIG = Path.home() / ".config" / "whoknows" / "recorder.json"
MIN_INTERVAL = 60


def load_config() -> dict | None:
    try:
        config = json.loads(Path(os.environ.get("WHOKNOWS_RECORDER_CONFIG") or DEFAULT_CONFIG).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or not all(isinstance(config.get(k), str) and config[k] for k in ("person", "push_url", "token")):
        return None
    return {**config, "match": config.get("match") or "packoverflow", "push_path": config.get("push_path") or "/signals"}


def hook(event: dict) -> None:
    if os.environ.get("RECORDER_CHILD"):
        return
    config = load_config()
    transcript = event.get("transcript_path") or ""
    if not config or not transcript or not any(config["match"] in str(event.get(k) or "") for k in ("cwd", "transcript_path")):
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as log:
        subprocess.Popen(
            [sys.executable, "-m", "recorder.hook", "--worker", transcript, event.get("hook_event_name") or "Stop"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
        )


def work(transcript: Path, event: str = "Stop") -> None:
    config = load_config()
    if not config:
        return
    # Imported here so the hook itself stays fast: run.py pulls in urllib, ssl and the summariser.
    from recorder.run import load_summaries, locked_update, push, record_summaries
    from recorder.summarise import compact

    session = transcript.stem
    summaries = STATE / "summaries.json"
    locks = STATE / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with open(locks / f"{session}.lock", "w") as lock:
        # Wait instead of skipping: the running worker read the transcript before this Stop's turn was written.
        fcntl.flock(lock, fcntl.LOCK_EX)
        text = compact(transcript)
        previous = load_summaries(summaries).get(session) or {}
        if not text or previous.get("sha256") == hashlib.sha256(text.encode()).hexdigest():
            return
        wait = previous.get("summarised_at", 0) + MIN_INTERVAL - time.time()
        if wait > 0 and event != "SessionEnd":
            # Sleeping instead of skipping means this summary includes the turns written meanwhile.
            time.sleep(wait)
        rows = record_summaries([transcript], config["person"], STATE / "sessions" / f"{session}.json", cache_path=summaries)
        try:
            stored, skipped = push(rows, config["push_url"], config["token"], config["push_path"])
        except Exception:
            # Forget this session's hash so the next Stop resends instead of skipping unchanged text.
            locked_update(summaries, lambda path: {s: v for s, v in load_summaries(path).items() if s != session})
            raise
        print(f"{datetime.now().isoformat(timespec='seconds')} {session[:8]} {event}: pushed {stored} stored, {skipped} skipped", flush=True)


def main() -> None:
    try:
        if sys.argv[1:2] == ["--worker"]:
            work(Path(sys.argv[2]), *sys.argv[3:4])
        else:
            hook(json.load(sys.stdin))
    except Exception:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a") as log:
                log.write(f"{datetime.now().isoformat(timespec='seconds')} {traceback.format_exc()}")
        except OSError:
            pass


if __name__ == "__main__":
    main()
