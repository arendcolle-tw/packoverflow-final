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

## Backtracking: ask the owner for the missing why

The graph finds work with no recorded reasoning (a gap), Claude drafts the likely why, and the owner confirms or corrects it, out loud or typed. Their answer becomes a signal row in their own words.

1. **Find gaps** (`knowledge_graph/gaps.py`, on startup and after every write, or `POST /gaps/scan`):
   - `missing_why`: rows with `decided` or `corrected` and no `why`. Owner: that row's person.
   - `unrecorded_work`: artifacts (commits, tickets, docs) whose author has no signal row within 1.5 hours either side. Owner: the author when they're in `seed/people.json` or a member, else the top person from `who_knows(title + body)`.
   - Riskiest first: topics that are `dark` or `single_point` in `risks()`, then oldest. Same row or artifact, same gap id.
2. **Draft**: `POST /gaps/{id}/draft` asks `claude-sonnet-5-5` for at most 2 sentences in the owner's voice plus one check question. The context goes in `<context>` delimiters as data. Without `ANTHROPIC_API_KEY` or on any failure: a template draft ("You did X. Was that because ...?"), `draft_source: template`. Every new gap gets a template draft at once, so the board never waits on a quota.
3. **Ask the owner**: "Call <owner>" on the board phones them through ElevenLabs when calls are configured for them, otherwise opens `/gaps/{id}/talk`: the ElevenLabs web widget for the same agent, plus a text form with the draft prefilled.
4. **Store**: the post-call webhook (HMAC checked) or the text form stores the answer as a row: `source` `voice_call` or `gap_form`, `human_role` `explained_why`, `why` their words (at most 200 chars, near-verbatim from the transcript), `draft` = `confirmed` | `edited` | `rewritten`. A `confirmed` row (they only said yes) weighs 0.5, the others 1.0.

**A draft is a hypothesis, not knowledge.** Drafts live in the `gaps` table and never show up in `/rows`, `who_knows` or `risks`. The draft text only becomes a row when its owner confirms it, and then at half weight.

| Call | Auth | Does |
|---|---|---|
| `POST /artifacts` body: `[{id, kind: commit\|ticket\|doc, author, at, title, body (≤2000), link}]` | admin | store work artifacts, rescan |
| `GET /gaps?status=open` | | gaps; `open` = not answered yet (open, drafted, calling); never phone numbers |
| `POST /gaps/scan?claude=N` | admin | rescan; Claude-drafts the N riskiest template drafts |
| `POST /gaps/{id}/draft` | admin | Claude draft (template fallback) |
| `POST /gaps/{id}/call` | admin | phone the owner; 409 with the `/talk` URL when not configured |
| `GET /gaps/{id}/talk` | | voice widget and text form |
| `POST /gaps/{id}/answer` body: `{answer}` | owner's member token | store the typed answer (403 for someone else's gap) |
| `POST /webhooks/elevenlabs` | `ElevenLabs-Signature` HMAC | store the call's answer |
| `GET /gaps/board` | | the demo screen: open gaps, and answered ones as draft vs final side by side |

Commits: `python -m knowledge_graph.import_git ../.. --since 2026-10-19` posts this repo's commits (needs `KG_ADMIN_TOKEN`); `--out seed/artifacts.json` refreshes the seed the service loads on startup. Authors map to person keys through `seed/people.json`.

### Environment

| Variable | What | Without it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude drafts and transcript extraction | template drafts; the longest thing the person said |
| `ELEVENLABS_API_KEY` | outbound calls, agent setup | no phone calls |
| `ELEVENLABS_AGENT_ID` | the agent from `setup_agent` | no voice; text form only |
| `ELEVENLABS_PHONE_NUMBER_ID` | the Twilio number imported in ElevenLabs | the button opens the browser version |
| `ELEVENLABS_WEBHOOK_SECRET` | HMAC secret of the post-call webhook | every webhook is refused |
| `KG_PHONE_NUMBERS` | JSON `{"person": "+32..."}`, opted-in members only | nobody is phoned |

Create the agent once (prints `ELEVENLABS_AGENT_ID` and, with the webhook, `ELEVENLABS_WEBHOOK_SECRET`):

```bash
ELEVENLABS_API_KEY=<key> uv run --python 3.13 --with httpx python -m knowledge_graph.setup_agent \
  --webhook-url https://knowledge-graph-323892475788.us-central1.run.app/webhooks/elevenlabs
gcloud run services update knowledge-graph --region us-central1 --update-env-vars \
  ANTHROPIC_API_KEY=<key>,ELEVENLABS_API_KEY=<key>,ELEVENLABS_AGENT_ID=<agent id>,ELEVENLABS_WEBHOOK_SECRET=<secret>
# Phone calls, optional (the ^@^ delimiter lets the JSON keep its commas):
gcloud run services update knowledge-graph --region us-central1 --update-env-vars \
  '^@^ELEVENLABS_PHONE_NUMBER_ID=<phone number id>@KG_PHONE_NUMBERS={"arend":"+32..."}'
```

The agent greets the person, reads the subject and Claude's draft, asks "Is that right, or how would you put it?", asks the check question, reads the final version back in their words, and ends on a yes. It never invents reasons.

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
- Backtracking: ElevenLabs is only tested with mocks; the webhook signature format and payload follow ElevenLabs' docs and OpenAPI spec but have not met a real call yet.
- Backtracking: the phone call needs a Twilio number imported in ElevenLabs; without it the browser widget is the demo path.
- Backtracking: commits since 2026-10-19 are a seed file; new commits need `import_git` run by hand or in CI.
- Backtracking: the transcript fallback without Claude takes the person's longest turn, which can be their answer to the check question.
- Backtracking: no way to skip or reassign a gap yet (`skipped` exists as a status, nothing sets it).
