import argparse
import json
import os
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

from knowly.capture.hook import DEFAULT_CONFIG

EVENTS = ("Stop", "SessionEnd")
# The console scripts of the venv that runs this installer.
BIN = Path(sys.executable).parent


def merge_hooks(settings_path: Path, entry: dict) -> str:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    changes = []
    for event in EVENTS:
        groups = settings.setdefault("hooks", {}).setdefault(event, [])
        if any(h.get("command") == entry["command"] for group in groups for h in group.get("hooks", [])):
            continue
        groups.append({"hooks": [dict(entry)]})
        changes.append(f"added the {event} hook")
    if not changes:
        return f"{settings_path} already has the {' and '.join(EVENTS)} hooks"
    note = ""
    if settings_path.exists():
        backup = settings_path.with_name(f"{settings_path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(settings_path, backup)
        note = f", backup at {backup}"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return f"{' and '.join(changes)} in {settings_path}{note}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture this Mac's Claude Code sessions into Knowly.")
    parser.add_argument("--person", required=True, help="your first name, e.g. tristan")
    parser.add_argument("--push", default=os.environ.get("KNOWLY_URL"), metavar="URL",
                        help="the Knowly server, e.g. its Cloud Run URL, default $KNOWLY_URL")
    parser.add_argument("--token", default=os.environ.get("KNOWLY_TOKEN"), help="your member token, default $KNOWLY_TOKEN")
    parser.add_argument("--match", default="packoverflow", help="only capture sessions whose cwd or transcript path contains this")
    parser.add_argument("--write-settings", action="store_true", help="merge the Stop and SessionEnd hooks into the settings file")
    parser.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    args = parser.parse_args()
    if not args.push or not args.token:
        parser.error("needs --push or KNOWLY_URL, and --token or KNOWLY_TOKEN")

    person = " ".join(args.person.split()).lower()
    url = args.push.rstrip("/")
    config_path = Path(os.environ.get("KNOWLY_CAPTURE_CONFIG") or DEFAULT_CONFIG)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump({"person": person, "url": url, "token": args.token, "match": args.match}, f, indent=2)
    config_path.chmod(0o600)
    print(f"wrote {config_path} (mode 600)")

    hook = BIN / "knowly-hook"
    if not hook.exists():
        print(f"warning: {hook} does not exist, run `uv pip install -e .` in the Knowly repo", file=sys.stderr)
    # A Stop hook that exits 2 sends Claude back to work, so a missing or broken venv must not fail it.
    entry = {"type": "command", "command": f"{shlex.quote(str(hook))} || true", "timeout": 10}
    if args.write_settings:
        print(merge_hooks(args.settings, entry))
    else:
        print(f"\nAdd these hooks to {args.settings}, or rerun with --write-settings:\n")
        print(json.dumps({"hooks": {event: [{"hooks": [entry]}] for event in EVENTS}}, indent=2))
    # --token= keeps a token that starts with "-" from being read as a flag.
    print(f"\nBackfill past sessions once:\n  {shlex.quote(str(BIN / 'knowly-record'))} --person {shlex.quote(person)} "
          f"--match {shlex.quote(args.match)} --push {shlex.quote(url)} --token=<token>")


if __name__ == "__main__":
    main()
