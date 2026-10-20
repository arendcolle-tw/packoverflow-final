# Who knows

A Slack bot that answers "who actually knows how to do X". The recorder turns each person's Claude Code sessions into rows, one per human turn, and labels whether the person decided, corrected Claude, explained why, or accepted what Claude supplied. A central FastAPI service stores the rows in SQLite. The bot ranks people by their own reasoning in similar sessions and replies with the person, a verbatim quote of their why, the source Claude session and a status.

## Row shape

```json
{"id": "<session>:<message uuid>", "person": "tristan", "topic": "aikido-security-scan",
 "source": "claude_session", "source_id": "<session>", "at": "2026-10-15T10:00:00Z",
 "human_role": "decided", "why": "<the person's own words, or null>", "actor": "human",
 "task": "Set up the aikido security scan in CI"}
```

`human_role` is `decided`, `corrected`, `explained_why` or `accepted_as_is`. `actor` is `human`, `agent` (a subagent prompt) or `unknown`. A subagent run has id `<session>:<agent>:run` and source_id `<session>:<agent>`. The recorder keeps a `why` only when it is a verbatim substring of what the person typed, so the model cannot write reasons for them.

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
- The recorder replaces pasted content with `[pasted]`, and tokens (`sk-`, `sk_live_`/`rk_test_`, `gh*_`, `github_pat_`, `glpat-`, `xox*`, `xapp-`, `AKIA`, `AIza`, `ATATT`, `npm_`, `hf_`, `ya29.`, JWTs, `Bearer` values, Slack webhook URLs, store tokens `wk_`, private keys), values after `password=`, `secret:`, `api_key=`, `token=` and similar, passwords in URLs and email addresses with `[redacted]`, before labelling. `record_signal` over MCP applies the same scrub. It skips the summary Claude writes on `/compact`.
- Labelling runs `claude -p --model haiku` under the person's own Claude Code login. The label cache is `~/.cache/packoverflow-recorder/cache.json`.

## Run locally

1. Create a Slack app in a test workspace at api.slack.com/apps: Create New App, From a manifest, paste `slack-manifest.yml`. Install it to the workspace. Under Basic Information, create an app-level token with the `connections:write` scope.
2. Put both tokens in `ideas/tristan/.env` (gitignored):
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   ```
   Optional: `WHOKNOWS_NOW=2026-10-20T16:00:00Z` fixes "now" for the demo (rows captured later count as captured at that time), `WHOKNOWS_DB` sets the SQLite path (default `data/store.db`), `SLACK_PEOPLE=wout:U0123,alberic:U0456` maps person keys to Slack user ids where first names do not match.
3. Start the server from `ideas/tristan/`:
   ```bash
   uv run --python 3.13 --with-requirements requirements.txt --env-file .env uvicorn whoknows.server:app --port 8090
   ```
   On start the server loads every `data/signals-*.json` into the store. Without the Slack tokens it serves only the HTTP API.
4. Make a token per person:
   ```bash
   uv run --python 3.13 --with-requirements requirements.txt python -m whoknows.store tristan
   ```
   `POST /api/signals` sets each row's person from the token and skips row ids that another person owns. `--revoke` deletes every token of that person.

## Backfill

```bash
uv run --python 3.13 python -m recorder.run --person tristan --push http://localhost:8090 --token <token>
```

Labels every turn missing from the cache, writes `data/signals-tristan.json` and, with `--push`, posts the rows to the store.

The team's one store is the knowledge graph (`ideas/alberic`, https://knowledge-graph-323892475788.us-central1.run.app). Pass that as `--push` with your graph member token: the recorder, the hook and the screenshot watcher post to `POST /signals`, and fall back to `POST /api/signals` only for the old Who knows store. `WHOKNOWS_TOKEN` can replace `--token`.

## Live capture

```bash
uv run --python 3.13 python -m recorder.install --person tristan --push <url> --token <token> --write-settings
```

Adds a Claude Code Stop hook (`python -m recorder.hook`). When a session in a `packoverflow` folder stops, the hook starts a background worker that labels that session and pushes its rows. The hook reads person, URL and token from `~/.config/whoknows/recorder.json` and the worker logs to `~/.cache/packoverflow-recorder/hook.log`. The classifier's own `claude -p` runs set `RECORDER_CHILD=1`, and the hook skips them.

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

- `@whoknows set up the aikido security scan` in a channel the bot is in. The bot replies in a thread.
- A DM to the bot with the task.
- `/whoknows set up the aikido security scan`, answered in the channel.
- The "Ask <name>" button opens a group DM with the asker and that colleague, with the question and the colleague's earlier why. This needs the `mpim:write` scope, so reinstall an app created before it was in the manifest. Without it the button falls back to a 1:1 DM with the colleague.

The bot matches person keys to the first name in each full member's real name from `users.list`. Guests are skipped, and a first name that two members share matches nobody, so set `SLACK_PEOPLE` for them.

## API

`/api` calls need `Authorization: Bearer <token>`.

- `POST /api/signals` takes a JSON list of at most 5000 rows in a body of at most 4 MB with a Content-Length, and returns `{"stored": n, "skipped": n}`.
- `GET /api/who-knows?q=<task>` returns the ranking: status, people with score, roles and evidence, and session counts.
- `GET /healthz` returns `{"ok": true}`.

## MCP

The server exposes an MCP endpoint, so Claude Code, claude.ai or Copilot can ask the store and record signals. The person comes from the token only.

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

| Tool | Arguments | Returns |
|---|---|---|
| `who_knows` | `task` | the ranking as `/api/who-knows` returns it, with each colleague's quoted why, its task and date |
| `record_signal` | `task`, `what_happened` (`decided`, `corrected`, `explained_why`), `why`, optional `topic` | the stored row, source `mcp_record`, actor `unknown` |
| `my_knowledge` | none | the caller's tasks where they reasoned and the tasks where they only accepted AI output, with turn counts |

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
uv run --python 3.13 --with pytest --with httpx --with fastapi --with uvicorn --with slack_bolt --with aiohttp pytest -q
```

## Unfinished

- SQLite on Cloud Run is a file in the instance, so a redeploy or restart loses pushed rows and tokens. The server reseeds rows from `data/signals-*.json` on start.
- `python -m whoknows.store` writes tokens to a local SQLite file, so it cannot make tokens for the deployed service.
- Tokens are bearer tokens without login or expiry. Anyone holding one can query and can write rows as its person until `--revoke` deletes it.
- Copilot sessions are not read directly yet, only through screenshots or MCP. The row's `source` field (`claude_session`, `screenshot` and `mcp_record` today) leaves room for them.
