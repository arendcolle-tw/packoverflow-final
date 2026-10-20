import argparse
import json
import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path

from recorder.hook import DEFAULT_CONFIG, ROOT


def merge_stop_hook(settings_path: Path, entry: dict) -> str:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
    hooks = [h for group in stop for h in group.get("hooks", [])]
    if any(h.get("command") == entry["command"] for h in hooks):
        return f"{settings_path} already has this Stop hook"
    # Earlier installs wrote the command without `|| true`.
    old = next((h for h in hooks if h.get("command") == entry["command"].removesuffix(" || true")), None)
    note = ""
    if settings_path.exists():
        backup = settings_path.with_name(f"{settings_path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(settings_path, backup)
        note = f", backup at {backup}"
    if old:
        old.update(entry)
    else:
        stop.append({"hooks": [entry]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return f"{'updated' if old else 'added'} the Stop hook in {settings_path}{note}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Record this Mac's Claude Code sessions into a Who knows store.")
    parser.add_argument("--person", required=True, help="your first name, e.g. tristan")
    parser.add_argument("--push", required=True, metavar="URL", help="the Who knows store, e.g. https://whoknows.example")
    parser.add_argument("--token", required=True, help="your store token from `python -m whoknows.store <person>`")
    parser.add_argument("--match", default="packoverflow", help="only record sessions whose cwd or transcript path contains this")
    parser.add_argument("--write-settings", action="store_true", help="merge the Stop hook into the settings file")
    parser.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    args = parser.parse_args()

    person = " ".join(args.person.split()).lower()
    config_path = Path(os.environ.get("WHOKNOWS_RECORDER_CONFIG") or DEFAULT_CONFIG)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump({"person": person, "push_url": args.push.rstrip("/"), "token": args.token, "match": args.match}, f, indent=2)
    config_path.chmod(0o600)
    print(f"wrote {config_path} (mode 600)")

    uv = shlex.quote(shutil.which("uv") or "uv")
    # uv exits 2 on its own errors, and a Stop hook exiting 2 sends Claude back to work.
    command = f"cd {shlex.quote(str(ROOT))} && {uv} run --no-project --python 3.13 python -m recorder.hook || true"
    entry = {"type": "command", "command": command, "timeout": 10}
    if args.write_settings:
        print(merge_stop_hook(args.settings, entry))
    else:
        print(f"\nAdd this Stop hook to {args.settings}, or rerun with --write-settings:\n")
        print(json.dumps({"hooks": {"Stop": [{"hooks": [entry]}]}}, indent=2))
    print(f"\nBackfill past sessions once:\n  cd {shlex.quote(str(ROOT))} && {uv} run --no-project --python 3.13 "
          f"python -m recorder.run --person {shlex.quote(person)} --match {shlex.quote(args.match)} "
          f"--push {shlex.quote(args.push)} --token <token>")


if __name__ == "__main__":
    main()
