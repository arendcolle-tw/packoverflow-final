import fcntl
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = Path.home() / ".cache" / "packoverflow-recorder"
LOG = STATE / "hook.log"
DEFAULT_CONFIG = Path.home() / ".config" / "whoknows" / "recorder.json"


def load_config() -> dict | None:
    try:
        config = json.loads(Path(os.environ.get("WHOKNOWS_RECORDER_CONFIG") or DEFAULT_CONFIG).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or not all(isinstance(config.get(k), str) and config[k] for k in ("person", "push_url", "token")):
        return None
    return {**config, "match": config.get("match") or "packoverflow"}


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
            [sys.executable, "-m", "recorder.hook", "--worker", transcript],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
        )


def work(transcript: Path) -> None:
    config = load_config()
    if not config:
        return
    # Imported here so the hook itself stays fast: run.py pulls in urllib, ssl and the classifier.
    from recorder.run import push, record

    session = transcript.stem
    locks = STATE / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with open(locks / f"{session}.lock", "w") as lock:
        # Wait instead of skipping: the running worker read the transcript before this Stop's turn was written.
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = record([transcript], config["person"], STATE / "sessions" / f"{session}.json")
        stored, skipped = push(rows, config["push_url"], config["token"])
        print(f"{datetime.now().isoformat(timespec='seconds')} {session[:8]}: pushed {stored} stored, {skipped} skipped", flush=True)


def main() -> None:
    try:
        if sys.argv[1:2] == ["--worker"]:
            work(Path(sys.argv[2]))
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
