import argparse
import json
from pathlib import Path

from vendor.proficiency.score import parse_at, who_knows

DEFAULT_SIGNALS = Path(__file__).resolve().parents[2] / "wout" / "data" / "signals.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Who knows how to do this task, right now?")
    parser.add_argument("task", help="what you are about to work on, in plain words")
    parser.add_argument("--at", help="pretend it is this moment (ISO date), default now")
    parser.add_argument("--signals", nargs="+", default=[str(DEFAULT_SIGNALS)], help="signal row files")
    parser.add_argument("--json", action="store_true", help="print the raw result")
    args = parser.parse_args()

    signals = [row for path in args.signals for row in json.loads(Path(path).read_text())]
    result = who_knows(args.task, signals, parse_at(args.at) if args.at else None)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    print(f"{result['status']} · owner: {result['owner'] or 'nobody'} · {result['similar_tasks']} similar tasks")
    for person in result["people"]:
        print(f"\n{person['person']}  {person['proficiency']:.2f}")
        for ev in person["evidence"][:3]:
            print(f"  {ev['at'][:10]}  session {ev['source_id'][:8]}  sim {ev['similarity']}  takeover {ev['takeover']}")
            for why in ev["whys"][:2]:
                print(f"    {why['role']}: {why['why'][:100]}")


if __name__ == "__main__":
    main()
