"""Post a repo's commits as artifacts: python -m knowledge_graph.import_git <repo> --since 2026-10-19

Authors map to person keys through seed/people.json. Sends to --url (POST /artifacts, Bearer $KG_ADMIN_TOKEN),
or writes a JSON file with --out (the service loads seed/artifacts.json on startup).
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

import httpx

from knowledge_graph.gaps import person_for_email

SEP, END = "\x1f", "\x1e"
LINK = "https://github.com/arendcolle-tw/packoverflow-final/commit/"


def commits(repo: str, since: str, link: str = LINK) -> list[dict]:
    log = subprocess.run(
        ["git", "-C", repo, "log", "--no-merges", f"--since={since}", f"--format=%H{SEP}%ae{SEP}%aI{SEP}%s{SEP}%b{END}"],
        capture_output=True, text=True, check=True,
    ).stdout
    out = []
    for entry in filter(str.strip, log.split(END)):
        sha, email, at, title, body = entry.strip("\n").split(SEP)
        out.append({"id": f"commit-{sha[:12]}", "kind": "commit", "author": person_for_email(email), "at": at,
                    "title": title[:300], "body": body.strip()[:2000], "link": link + sha})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="knowledge_graph.import_git")
    parser.add_argument("repo")
    parser.add_argument("--since", default="2026-10-19")
    parser.add_argument("--url", default="https://knowledge-graph-323892475788.us-central1.run.app")
    parser.add_argument("--out", help="write the artifacts to this file instead of posting")
    args = parser.parse_args()

    found = commits(args.repo, args.since)
    if args.out:
        Path(args.out).write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {len(found)} commits to {args.out}")
        return
    response = httpx.post(f"{args.url}/artifacts", json=found, timeout=60,
                          headers={"Authorization": f"Bearer {os.environ['KG_ADMIN_TOKEN']}"})
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
