# Who knows

A Slack bot that answers "who actually knows how to do X". The recorder turns each Claude Code session into one row: Claude's summary of the decisions the person made, and whether they decided, corrected Claude, explained why, or accepted what Claude supplied. Alberic's knowledge graph (`ideas/alberic/knowledge_graph`) is the central store for these rows. The Who knows server answers questions from Slack, MCP and `POST /api/ask`: it looks the question up in the graph and has Haiku answer from the matching rows only, naming the person, their reason, the source task and the date. When no row answers the question, the server DMs the colleague with the closest related fact in Slack, and their answer goes into the graph as their own row.

The four-step stage demo and its setup script are in `demo/README.md`.

## Row shape

```json
{"id": "<session>:summary", "person": "tristan", "topic": "aikido-security-scan",
 "source": "claude_session", "source_id": "<session>", "at": "<time of the last human turn>",
 "human_role": "decided", "actor": "human", "task": "Set up the aikido security scan in CI",
 "why": "Chose the CI scan over a pre-commit hook \"because local hooks get skipped\""}
```

`human_role` is `decided`, `corrected`, `explained_why` or `accepted_as_is`. `why` is a summary of at most 200 characters of what the person chose, corrected or ruled out. The recorder keeps quote marks only around words that appear verbatim (ignoring case and whitespace) in what the person typed, so a row never claims a quote the person did not write.

`--mode turns` gives the older shape instead: one row per human turn with id `<session>:<message uuid>`, `actor` `human`, `agent` (a subagent prompt, id `<session>:<agent>:run`) or `unknown`, and a `why` kept only when it is a verbatim substring of the turn.

## Ranking

Only rows where a human decided, corrected Claude or explained why count. Each row scores by the TF-IDF similarity of the question to its session's task, topics and whys, times `exp(-days / 90)`.

| Status | Meaning |
|---|---|
| `healthy` | two or more people reasoned about it in the last 30 days |
| `single_point` | one person did |
| `fading` | nobody did in the last 30 days |
| `dark` | similar sessions exist, Claude handled every turn |
| `unknown` | no similar session |

## Privacy

- The recorder reads `~/.claude/projects` on the laptop, only session folders whose name contains `packoverflow` (`--match` changes it).
- Raw sessions stay on the laptop. Only rows leave it, with a why of at most 200 characters and a task of at most 80.
- The recorder replaces pasted content with `[pasted]`, and tokens (`sk-`, `sk_live_`/`rk_test_`, `gh*_`, `github_pat_`, `glpat-`, `xox*`, `xapp-`, `AKIA`, `AIza`, `ATATT`, `npm_`, `hf_`, `ya29.`, JWTs, `Bearer` values, Slack webhook URLs, store tokens `wk_`, private keys), values after `password=`, `secret:`, `api_key=`, `token=` and similar, passwords in URLs and email addresses with `[redacted]`, before labelling. `It skips the summary Claude writes on `/compact`.
- Summarising runs `claude -p --model haiku` without tools under the person's own Claude Code login, on a compacted copy of the session: the human turns verbatim and Claude's text replies cut to about 1500 characters, without tool calls, tool output or subagent runs, at most about 60,000 characters. The summary cache is `~/.cache/packoverflow-recorder/summaries.json`, the turn label cache `cache.json` next to it.

## Run locally

1. Create a Slack app in a test workspace at api.slack.com/apps: Create New App, From a manifest, paste `slack-manifest.yml`. Install it to the workspace. Under Basic Information, create an app-level token with the `connections:write` scope.
2. Put both tokens in `ideas/tristan/.env` (gitignored):
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   ```
   Optional:
   - `KG_URL`, the knowledge graph (default `http://127.0.0.1:8770`).
   - `SLACK_PEOPLE=tristan:U0C9D2HJUA1,alberic:U0456` maps person keys to Slack user ids where first names do not match.
   - `DEFAULT_EXPERT`, the person to ask when the graph has nothing related from anyone but the asker.
   - `WHOKNOWS_DB`, the token store (default `data/store.db`). `WHOKNOWS_QUESTIONS_DB` (default `data/questions.db`) holds the questions sent to colleagues.
   - `WHOKNOWS_GRAPH_TOKENS` (default `data/graph_tokens.json`) is `{"<person>": "<graph member token>"}`. The server posts a colleague's Slack answer to the graph with their token from this file, so every person who answers needs an entry.
   - `WHOKNOWS_NOW=2026-10-20T16:00:00Z` fixes "now" for `/api/who-knows`.
3. Start the server from `ideas/tristan/`:
   ```bash
   uv run --python 3.13 --with-requirements requirements.txt --env-file .env uvicorn whoknows.server:app --port 8090
   ```
   On start the server loads every `data/signals-*.json` into the local store. Without the Slack tokens it serves only the HTTP API and MCP.
4. Make a token per person:
   ```bash
   uv run --python 3.13 --with-requirements requirements.txt python -m whoknows.store tristan
   ```
   `POST /api/signals` sets each row's person from the token and skips row ids that another person owns. `--revoke` deletes every token of that person.

## Backfill

```bash
uv run --python 3.13 python -m recorder.run --person tristan --push https://knowledge-graph-323892475788.us-central1.run.app --token <member token>
```

Summarises every session whose compacted text changed since the last run, writes `data/signals-tristan.json` and, with `--push`, posts the rows in chunks of 1000 to `<url>/signals`. `--mode turns` labels each human turn instead. `WHOKNOWS_TOKEN` can replace `--token`.

The team's one store is the knowledge graph (`ideas/alberic`, https://knowledge-graph-323892475788.us-central1.run.app). Pass that as `--push` with your graph member token. The recorder, the hook and the screenshot watcher post to `POST /signals` and fall back to `POST /api/signals` only for the old Who knows store; `--push-path /api/signals` picks that store directly.

## Live capture

```bash
uv run --python 3.13 python -m recorder.install --person tristan --push <url> --token <token> --write-settings
```

Adds `python -m recorder.hook` as a Claude Code Stop and SessionEnd hook. When a session in a `packoverflow` folder stops or ends, the hook starts a background worker and returns. The worker summarises that session again and pushes its one row. It skips the session when its compacted text is unchanged, and on Stop it sleeps until 60 s have passed since the session's previous summary, so the summary then includes the turns written meanwhile. SessionEnd summarises at once. The hook reads person, URL, push path (default `/signals`) and token from `~/.config/whoknows/recorder.json` and the worker logs to `~/.cache/packoverflow-recorder/hook.log`. The summariser's own `claude -p` runs set `RECORDER_CHILD=1`, and the hook skips them.

## Screenshots

For chats in Copilot, ChatGPT, Teams or any other assistant the recorder cannot read, drop a screenshot of the chat in a folder.

```bash
uv run --python 3.13 python -m recorder.screenshots --person tristan --watch --push <url> --token <token>
```

- The watched folder is `~/WhoKnows/screenshots` (`--dir` changes it). `--watch` checks it every 5 s; without it the command reads the folder once.
- It reads `.png`, `.jpg`, `.jpeg` and `.webp` files, skips hidden files, files younger than 2 s and files it cannot open, and reads each image once by its SHA-256. The read state is `~/.cache/packoverflow-recorder/screenshots.json`, and a failed read is retried on the next run.
- `claude -p --model sonnet` (`--model` changes it) transcribes a copy of the image in an empty temp folder with only the Read tool. The same Haiku classifier as for sessions then labels each human turn.
- Rows have `source` `screenshot`, the chat `app`, `source_id` `shot-<image hash>` and id `shot-turn-<hash of person and turn words>`, so a turn that shows up in a retake or an overlapping scroll capture is stored once.
- What leaves the laptop: the image and its transcript go to Claude under the person's own Claude Code login, and the store receives only the rows, with the same scrub and length limits as session rows. The images stay in the folder, and the rows are also written to `data/signals-<person>-screenshots.json`.

## Asking in Slack

- `@whoknows what time does the nightly payroll export start?` in a channel the bot is in. The bot posts "Looking it up..." in a thread and replaces it with the answer.
- A DM to the bot with the question.
- `/whoknows <question>`, answered in the channel.

Every question goes through the same ask as MCP. When the graph does not answer it, the bot DMs the colleague with the strongest related fact (not the asker, else `DEFAULT_EXPERT`) with the question, who asked, up to three related facts and an Answer button. A repeat of the same open question to the same colleague does not DM them again. Answer opens a modal for at most 200 characters. Only that colleague can submit it. The server then posts the answer to the graph as their row (`source` `gap_form`, `human_role` `answered_question`, task the question) and DMs the asker if the asker has a Slack account.

The bot matches person keys to the first name in each full member's real name from `users.list`. Guests are skipped, and a first name that two members share matches nobody, so set `SLACK_PEOPLE` for them. `SLACK_PEOPLE` entries win over `users.list`.

## API

`/api` calls need `Authorization: Bearer <token>`.

- `POST /api/signals` takes a JSON list of at most 5000 rows in a body of at most 4 MB with a Content-Length, and returns `{"stored": n, "skipped": n}`.
- `POST /api/ask` with `{"question": "..."}` runs the same ask as the MCP tool for the token's person and returns `{known, text, question_id, pinged, sources}`. It returns 502 when the graph is unreachable.
- `GET /api/who-knows?q=<task>` returns the ranking of the local store: status, people with score, roles and evidence, and session counts.
- `GET /healthz` returns `{"ok": true}`.

## MCP

The server exposes an MCP endpoint, so Claude Code, claude.ai or Copilot can ask questions. The person comes from the token only.

- `<host>/mcp` with `Authorization: Bearer <token>`, for clients that can set headers. Use this one where possible.
- `<host>/u/<token>/mcp`, the personal URL, for clients that cannot set headers, such as a claude.ai custom connector or Copilot Studio. The server's access log masks the token, but Cloud Run's request log keeps full URLs.

Claude Code:

```bash
claude mcp add --transport http whoknows <host>/mcp --header "Authorization: Bearer <token>"
```

GitHub Copilot in VS Code, `.vscode/mcp.json`:

```json
{
  "inputs": [{"type": "promptString", "id": "whoknows-token", "description": "Who knows token", "password": true}],
  "servers": {
    "whoknows": {
      "type": "http",
      "url": "<host>/mcp",
      "headers": {"Authorization": "Bearer ${input:whoknows-token}"}
    }
  }
}
```

The one tool is `ask(question)`, 2 to 300 characters. It returns the answer text, with the person, their reason, the source task and the date, and the same structured result as `POST /api/ask`. When the graph has no answer, the text says so, lists the closest related facts and names the colleague the bot asked in Slack.

## Deploy to Cloud Run

```bash
gh workflow run deploy.yml --ref main -f source=ideas/tristan -f service=whoknows
```

Google buildpacks install `requirements.txt` and start the `Procfile`. After the first deploy, run once (later deploys keep these settings):

```bash
gcloud run services update whoknows --project qwiklabs-gcp-04-61c2ca7d9c86 --region us-central1 \
  --min-instances 1 --max-instances 1 --no-cpu-throttling \
  --update-env-vars WHOKNOWS_DB=/tmp/whoknows.db,SLACK_BOT_TOKEN=xoxb-...,SLACK_APP_TOKEN=xapp-...
```

The service needs exactly one instance because the store is a SQLite file inside it and Socket Mode needs one open connection. `--no-cpu-throttling` keeps CPU allocated between HTTP requests so the instance can handle Slack events. `/tmp` is writable on Cloud Run.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Unfinished

- SQLite on Cloud Run is a file in the instance, so a redeploy or restart loses pushed rows and tokens. The server reseeds rows from `data/signals-*.json` on start.
- `python -m whoknows.store` writes tokens to a local SQLite file, so it cannot make tokens for the deployed service.
- Tokens are bearer tokens without login or expiry. Anyone holding one can query and can write rows as its person until `--revoke` deletes it.
- Copilot sessions are not read directly yet, only through screenshots. The row's `source` field (`claude_session`, `screenshot` and `gap_form` today) leaves room for them.
