"""Post a repo's commits as artifacts: python -m knowly.store.import_git <repo> --since 2026-10-19

Authors map to person keys through a JSON file {"person": ["email", ...]}, by default <KNOWLY_DATA_DIR>/people.json.
Sends to <KNOWLY_URL>/store/artifacts with $KNOWLY_ADMIN_TOKEN, or writes a JSON file with --out.
"""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import httpx

SEP, END = "\x1f", "\x1e"


def commits(repo: str, since: str, people: dict[str, list[str]], link: str | None) -> list[dict]:
    log = subprocess.run(
        ["git", "-C", repo, "log", "--no-merges", f"--since={since}", f"--format=%H{SEP}%ae{SEP}%aI{SEP}%s{SEP}%b{END}"],
        capture_output=True, text=True, check=True,
    ).stdout
    by_email = {email.lower(): person for person, emails in people.items() for email in emails}
    out = []
    for entry in filter(str.strip, log.split(END)):
        sha, email, at, title, body = entry.strip("\n").split(SEP)
        out.append({"id": f"commit-{sha[:12]}", "kind": "commit", "author": by_email.get(email.lower()), "at": at,
                    "title": title[:300], "body": body.strip()[:2000], "link": link + sha if link else None})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="knowly.store.import_git")
    parser.add_argument("repo")
    parser.add_argument("--since", default="2026-10-19")
    parser.add_argument("--url", default=os.environ.get("KNOWLY_URL", "http://127.0.0.1:8091"))
    parser.add_argument("--people", default=str(Path(os.environ.get("KNOWLY_DATA_DIR", "data")) / "people.json"))
    parser.add_argument("--out", help="write the artifacts to this file instead of posting")
    args = parser.parse_args()

    people_file = Path(args.people)
    people = json.loads(people_file.read_text()) if people_file.exists() else {}
    remote = subprocess.run(["git", "-C", args.repo, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    link = re.sub(r"^git@([^:]+):", r"https://\1/", remote).removesuffix(".git") + "/commit/" if remote else None
    found = commits(args.repo, args.since, people, link)
    if args.out:
        Path(args.out).write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {len(found)} commits to {args.out}")
        return
    response = httpx.post(f"{args.url.rstrip('/')}/store/artifacts", json=found, timeout=60,
                          headers={"Authorization": f"Bearer {os.environ['KNOWLY_ADMIN_TOKEN']}"})
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
