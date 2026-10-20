"""Load demo/seed/facts.json (and background.json when present) into a Knowly server; with --sessions, also run
the Claude Code sessions in sessions.json and record them with knowly-record.

Usage: python demo/seed/seed.py --url http://127.0.0.1:8091 --admin-token=$KNOWLY_ADMIN_TOKEN [--sessions] [--knowly-bin .venv/bin]
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data"
TOKENS = DATA / "seed_tokens.json"


def post(url: str, token: str, body) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def member_tokens(people: list[str], url: str, admin: str) -> dict[str, str]:
    """Reuse tokens saved by an earlier run when the server still accepts them, so re-runs add no extra members."""
    saved = json.loads(TOKENS.read_text()) if TOKENS.exists() else {}
    for person in people:
        if saved.get(person):
            try:
                post(f"{url}/store/facts", saved[person], [])
                print(f"member {person}: reused")
                continue
            except urllib.error.HTTPError as error:
                if error.code != 401:
                    raise
        saved[person] = post(f"{url}/store/members", admin, {"person": person})["token"]
        print(f"member {person}: created")
    DATA.mkdir(parents=True, exist_ok=True)
    fd = os.open(TOKENS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(saved, out, indent=2)
    return saved


def claude(folder: Path, args: list[str], out: Path) -> dict:
    # stdout to a file and stdin from /dev/null: claude -p keeps no pipe open that could hang this script.
    env = {k: v for k, v in os.environ.items() if k != "KNOWLY_CAPTURE_CHILD"}
    with out.open("w") as stdout:
        subprocess.run(["claude", "-p", *args, "--model", "haiku", "--tools", "", "--output-format", "json"],
                       cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=stdout, check=True, timeout=600)
    return json.loads(out.read_text())


def record(session: dict, url: str, token: str, knowly_bin: Path) -> str:
    folder = Path(session["folder"]).expanduser()
    slug = folder.name
    logs = DATA / "seed-sessions"
    logs.mkdir(parents=True, exist_ok=True)
    existing = list((Path.home() / ".claude" / "projects").glob(f"*{slug}/*.jsonl"))
    if existing:
        print(f"session {slug}: already in Claude Code, recording it again")
    else:
        folder.mkdir(parents=True, exist_ok=True)
        first, *rest = session["turns"]
        session_id = claude(folder, [first], logs / f"{slug}-1.json")["session_id"]
        for n, turn in enumerate(rest, start=2):
            claude(folder, [turn, "--resume", session_id], logs / f"{slug}-{n}.json")
        print(f"session {slug}: ran {len(session['turns'])} turns as {session['person']}")

    base = [str(knowly_bin / "knowly-record"), "--mode", "summary", "--match", slug, "--push", url,
            f"--token={token}", "--out", str(logs / f"{slug}-rows.json")]
    log = logs / f"{slug}-record.log"
    for cmd in (base[:3] + ["--person", session["person"]] + base[3:], base):
        with log.open("w") as out:
            done = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        text = log.read_text()
        if done.returncode == 0:
            return text.strip().splitlines()[-1] if text.strip() else "recorded"
        if "--person" not in text:
            break
    return f"knowly-record failed, see {log}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8091")
    parser.add_argument("--admin-token", default=os.environ.get("KNOWLY_ADMIN_TOKEN"))
    parser.add_argument("--sessions", action="store_true", help="also run and record the sessions in sessions.json")
    parser.add_argument("--knowly-bin", type=Path, default=ROOT / ".venv" / "bin")
    args = parser.parse_args()
    if not args.admin_token:
        parser.error("--admin-token=VALUE or KNOWLY_ADMIN_TOKEN is required")
    url = args.url.rstrip("/")

    rows = json.loads((HERE / "facts.json").read_text())
    if (HERE / "background.json").exists():
        rows += json.loads((HERE / "background.json").read_text())
    sessions = json.loads((HERE / "sessions.json").read_text())
    people = list(dict.fromkeys([r["person"] for r in rows] + [s["person"] for s in sessions]))
    tokens = member_tokens(people, url, args.admin_token)

    summary = []
    for person in people:
        mine = [r for r in rows if r["person"] == person]
        if not mine:
            continue
        result = post(f"{url}/store/facts", tokens[person], mine)
        line = f"{person}: {len(mine)} facts, {result['added']} added, {result['updated']} updated, {len(result['rejected'])} rejected"
        print(line)
        for rejected in result["rejected"][:3]:
            print(f"  rejected: {rejected}")
        summary.append(line)

    if args.sessions:
        for session in sessions:
            try:
                line = f"session {Path(session['folder']).name} ({session['person']}): " + record(
                    session, url, tokens[session["person"]], args.knowly_bin)
            except (subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
                line = f"session {Path(session['folder']).name} ({session['person']}): failed, {type(error).__name__}: {error}"
            print(line)
            summary.append(line)

    print("\nsummary")
    for line in summary:
        print(f"  {line}")
    print(f"tokens saved in {TOKENS}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit(f"HTTP {error.code} from {error.url}: {error.read().decode(errors='replace')[:200]}")
    except urllib.error.URLError as error:
        sys.exit(f"cannot reach the Knowly server: {error.reason}")
