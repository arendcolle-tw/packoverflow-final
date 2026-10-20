# Who knows this task

Give it the task you're about to start. It finds past Claude sessions on similar tasks and ranks the people who actually reasoned in them, with their own words as evidence. One session is one task. There is no topic list: the topic is whatever past tasks look like yours.

A session row counts `similarity × role × actor × time decay × takeover`:

- role: `decided`, `explained_why`, `answered_question` 1.0 · `corrected` 0.7 · `accepted_as_is` 0 (Claude's answer is not your knowledge)
- actor: `human` 1.0 · `unknown` 0.5 · `agent` 0
- time decay: `e^(−age / 90 days)`
- takeover: share of later similar tasks that were your own, so others redoing your work lowers your level

Per person the sum is squashed to 0–1. Status for the question: `dark` (no human reasoning), `fading` (nobody above 0.2), `single_point` (one person), `healthy`.

## Knowledge graph

`knowledge_graph.KnowledgeGraph` is the one store in the pipeline: Tristan's ingestion → this graph → Wout's MCP connector. Nodes are people, tasks (one Claude session) and evidence (one signal row); proficiency is the computed person → task edge.

```python
from knowledge_graph import KnowledgeGraph

graph = KnowledgeGraph(Path("data/rows.jsonl"), seed_paths=[Path("signals.json")], mirror=gcs_mirror)
graph.add_signals(rows)            # {"added", "updated", "rejected"}; dedupes on id, later row wins
graph.who_knows(question, at=None) # status, owner, people ranked with evidence and whys
graph.person_view(person, at=None) # headline, knows (with proficiency, only_you), only_prompts
graph.risks(at=None)               # topics riskiest first: dark, single_point, fading, healthy
```

Rows are stored as JSONL, one line per write, and the whole file is uploaded to `mirror` (anything with `upload(path)`) after each write. Topic status uses the same decay as `who_knows` instead of a fixed window: `dark` means no human reasoning ever, `fading` means it decayed below 0.2.

## Run

From `ideas/alberic/`, reads Wout's rows at `ideas/wout/data/signals.json` by default:

```bash
uv run --python 3.13 python -m proficiency.cli "set up the aikido security scan" [--at 2026-10-05] [--json] [--signals a.json b.json]
```

`--at` replays the past: the owner of a task changes as people come and go.

Tests: `uv run --python 3.13 --with pytest pytest -q`

## Unfinished

- Only Wout's sessions are in the rows, so every answer has one person. Tristan's multi-person rows fix that.
- Similarity is plain TF-IDF on the rows' `why` and topic. A one-line `task` summary per session (asked in Slack) matches better, and embeddings would handle synonyms.
- No API yet. Wout's clock can import `who_knows` directly.
