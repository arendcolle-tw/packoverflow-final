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

graph = KnowledgeGraph(Path("data/graph.sqlite"), seed_paths=[Path("signals.json")], mirror=gcs_mirror)
graph.add_signals(rows)            # {"added", "updated", "rejected"}; dedupes on id, later row wins
graph.who_knows(question, at=None) # status, owner, people ranked with evidence and whys
graph.person_view(person, at=None) # headline, knows (with proficiency, only_you), only_prompts
graph.risks(at=None)               # topics riskiest first: dark, single_point, fading, healthy
graph.add_signals(rows, person="lies") # person from a member token overrides each row's person
```

Rows live in one SQLite file (`signals` table keyed on `id`, plus `members`). After each write the file is uploaded to `mirror` (anything with `upload(path)`); a missing file is restored with `mirror.download(path)` on startup. A JSONL file at `path`, the old format, is imported once and renamed to `<path>.imported`. Seed files only fill ids the database does not have. Topic status uses the same decay as `who_knows` instead of a fixed window: `dark` means no human reasoning ever, `fading` means it decayed below 0.2.

### Rows

Required: `id`, `person`, `topic`, `source`, `source_id`, `at` (ISO time), `human_role`, `actor`. Optional: `why` (≤200 chars), `task` (≤80, one-line session summary), `app` (≤300). Every string ≤300. Unknown fields are dropped.

- source: `claude_session`, `meeting`, `copilot_chat`, `copilot_cli`, `m365_copilot`, `screenshot`, `mcp_record`
- human_role: `decided`, `corrected`, `explained_why`, `answered_question`, `accepted_as_is`
- actor: `human`, `agent`, `unknown`

A row id belongs to the first person who wrote it; a later write by someone else is rejected. Sessions are grouped per `(person, source_id)`, so posting under a colleague's session id cannot change their task.

## HTTP API

Cloud Run service `knowledge-graph` (`knowledge_graph/server.py`). Reads are public, writes need a token.

| Call | Auth | Returns |
|---|---|---|
| `POST /signals` body: list of rows | `Bearer <member token>` | `{added, updated, rejected}`; person comes from the token |
| `POST /members` body: `{"person": ...}` | `Bearer $KG_ADMIN_TOKEN` | `{person, token}`; only the token's hash is stored |
| `GET /who_knows?q=...&at=...` | | `who_knows` |
| `GET /people/{person}?at=...` | | `person_view` |
| `GET /risks?at=...` | | `risks` |
| `GET /rows` | | all rows |
| `GET /health` | | `{storage: "gcs"\|"local", rows: n}` |

`at` is an optional ISO time to replay the past. Without `KG_ADMIN_TOKEN` (32+ chars) set, `/members` refuses everything. On an empty database the service seeds from `seed/signals-wout.json` (Wout's 51 rows).

Locally (data in `data/`, not committed):

```bash
KG_ADMIN_TOKEN=$(openssl rand -hex 24) uv run --python 3.13 --with-requirements requirements.txt uvicorn knowledge_graph.server:app --port 8080
```

Deploy: run the "Deploy to Cloud Run" workflow with `source=ideas/alberic`, `service=knowledge-graph`, `min_instances=1`, `max_instances=1` (SQLite has one writer, so exactly one instance). On Cloud Run the file is mirrored to bucket `<project>-knowledge-graph` (override with `KG_BUCKET`). Set the admin token once, outside git; later deploys keep it:

```bash
gcloud run services update knowledge-graph --region us-central1 --update-env-vars KG_ADMIN_TOKEN=$(openssl rand -hex 24)
```

## Run

From `ideas/alberic/`, reads Wout's rows at `ideas/wout/data/signals.json` by default:

```bash
uv run --python 3.13 python -m proficiency.cli "set up the aikido security scan" [--at 2026-10-05] [--json] [--signals a.json b.json]
```

`--at` replays the past: the owner of a task changes as people come and go.

Tests: `uv run --python 3.13 --with pytest --with fastapi --with httpx pytest -q`

## Unfinished

- Only Wout's sessions are in the rows, so every answer has one person. Tristan's multi-person rows fix that.
- Similarity is plain TF-IDF on the rows' `why` and topic. A one-line `task` summary per session (asked in Slack) matches better, and embeddings would handle synonyms.
- Wout's connector still reads its own file; it should sync from `GET /rows`.
- Recorders don't post yet; they should send rows to `POST /signals` with a member token.
- No way to revoke a member token or delete a row.
- Every write uploads the whole SQLite file; fine for thousands of rows, not millions.
- One instance only. More writers need a real database (Cloud SQL or Firestore).
