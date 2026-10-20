"""Poke the graph by hand: python -m knowledge_graph [who "question" | person NAME | risks | add rows.json]"""

import argparse
import json
from pathlib import Path

from knowledge_graph import KnowledgeGraph
from proficiency.score import parse_at

HERE = Path(__file__).resolve().parents[1]
SEED = HERE.parent / "wout" / "data" / "signals.json"


def main() -> None:
    parser = argparse.ArgumentParser(prog="knowledge_graph")
    parser.add_argument("command", choices=["who", "person", "risks", "add"])
    parser.add_argument("arg", nargs="?")
    parser.add_argument("--at", help="pretend it is this moment (ISO date)")
    parser.add_argument("--store", default=str(HERE / "data" / "rows.jsonl"), help="graph file (not committed)")
    args = parser.parse_args()

    graph = KnowledgeGraph(Path(args.store), seed_paths=[SEED])
    at = parse_at(args.at) if args.at else None

    if args.command == "who":
        result = graph.who_knows(args.arg, at)
    elif args.command == "person":
        result = graph.person_view(args.arg, at)
    elif args.command == "risks":
        result = graph.risks(at)
    else:
        result = graph.add_signals(json.loads(Path(args.arg).read_text()))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
