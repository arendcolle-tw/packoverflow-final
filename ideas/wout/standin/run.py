import argparse
import json
from pathlib import Path

from knowledge_clock.store import validate
from standin.classify import classify
from standin.sessions import human_turns, scrub, subagent_runs


def _key(item: dict) -> str:
    return f"{item['source_id']}:{item['message_uuid']}"


def to_rows(turns: list[dict], runs: list[dict], labels: dict[str, dict], person: str) -> list[dict]:
    rows = []
    for item, is_agent in [(t, False) for t in turns] + [(r, True) for r in runs]:
        label = labels.get(_key(item))
        if not label:
            continue
        why = None if is_agent or not label.get("why") else scrub(label["why"])[:200]
        rows.append({
            "id": _key(item),
            "person": person,
            "topic": label["topic"],
            "source": "claude_session",
            "source_id": item["source_id"],
            "at": item["at"],
            "human_role": "accepted_as_is" if is_agent else label["human_role"],
            "why": why,
            "actor": "agent" if is_agent else label["actor"],
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Stand-in for Tristan's ingestion: Claude sessions to signal rows.")
    parser.add_argument("--projects-dir", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--match", default="packoverflow")
    parser.add_argument("--person", required=True)
    parser.add_argument("--out", type=Path, default=Path("data/signals.json"))
    args = parser.parse_args()

    turns, runs = [], []
    for project in sorted(args.projects_dir.glob(f"*{args.match}*")):
        for session_file in sorted(project.glob("*.jsonl")):
            turns += human_turns(session_file)
            runs += subagent_runs(session_file.with_suffix(""))

    items = [{**t, "key": _key(t)} for t in turns + runs]
    labels = {label["key"]: label for label in classify(items)}
    rows = to_rows(turns, runs, labels, args.person)
    valid = sorted((r for r in rows if validate(r)), key=lambda r: r["at"])

    args.out.write_text(json.dumps(valid, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(turns)} human turns, {len(runs)} subagent runs, {len(labels)} labels, "
          f"{len(valid)} rows written, {len(rows) - len(valid)} invalid, {len(items) - len(rows)} unlabeled")


if __name__ == "__main__":
    main()
