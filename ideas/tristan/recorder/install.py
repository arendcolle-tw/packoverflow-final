import argparse
import json
import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path

from recorder.hook import DEFAULT_CONFIG, ROOT


EVENTS = ("Stop", "SessionEnd")


def merge_hooks(settings_path: Path, entry: dict) -> str:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    changes = []
    for event in EVENTS:
        groups = settings.setdefault("hooks", {}).setdefault(event, [])
        hooks = [h for group in groups for h in group.get("hooks", [])]
        if any(h.get("command") == entry["command"] for h in hooks):
            continue
        # Earlier installs wrote the command without `|| true`.
        old = next((h for h in hooks if h.get("command") == entry["command"].removesuffix(" || true")), None)
        if old:
            old.update(entry)
        else:
            groups.append({"hooks": [dict(entry)]})
        changes.append(f"{'updated' if old else 'added'} the {event} hook")
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
    parser = argparse.ArgumentParser(description="Record this Mac's Claude Code sessions into the knowledge graph.")
    parser.add_argument("--person", required=True, help="your first name, e.g. tristan")
    parser.add_argument("--push", required=True, metavar="URL", help="the store, e.g. the knowledge graph's Cloud Run URL")
    parser.add_argument("--push-path", default="/signals",
                        help="the store's endpoint for rows: /signals for the knowledge graph (default), /api/signals for the whoknows server")
    parser.add_argument("--token", required=True, help="your member token for the store")
    parser.add_argument("--match", default="packoverflow", help="only record sessions whose cwd or transcript path contains this")
    parser.add_argument("--write-settings", action="store_true", help="merge the Stop and SessionEnd hooks into the settings file")
    parser.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    args = parser.parse_args()

    person = " ".join(args.person.split()).lower()
    config_path = Path(os.environ.get("WHOKNOWS_RECORDER_CONFIG") or DEFAULT_CONFIG)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump({"person": person, "push_url": args.push.rstrip("/"), "push_path": args.push_path, "token": args.token,
                   "match": args.match}, f, indent=2)
    config_path.chmod(0o600)
    print(f"wrote {config_path} (mode 600)")

    uv = shlex.quote(shutil.which("uv") or "uv")
    # uv exits 2 on its own errors, and a Stop hook exiting 2 sends Claude back to work.
    command = f"cd {shlex.quote(str(ROOT))} && {uv} run --no-project --python 3.13 python -m recorder.hook || true"
    entry = {"type": "command", "command": command, "timeout": 10}
    if args.write_settings:
        print(merge_hooks(args.settings, entry))
    else:
        print(f"\nAdd these hooks to {args.settings}, or rerun with --write-settings:\n")
        print(json.dumps({"hooks": {event: [{"hooks": [entry]}] for event in EVENTS}}, indent=2))
    print(f"\nBackfill past sessions once:\n  cd {shlex.quote(str(ROOT))} && {uv} run --no-project --python 3.13 "
          f"python -m recorder.run --person {shlex.quote(person)} --match {shlex.quote(args.match)} "
          f"--push {shlex.quote(args.push)} --push-path {shlex.quote(args.push_path)} --token <token>")


if __name__ == "__main__":
    main()
