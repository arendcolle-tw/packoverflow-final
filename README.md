<p align="center">
  <img src="assets/hero.svg" alt="Knowly: one central, fact-based knowledge base. Every fact has a person and a reason." width="100%">
</p>

# Knowly

Knowly is a central, fact-based knowledge base for a team. Every fact names the person it comes from and their reason.

A recorder on each laptop summarises Claude Code sessions, and screenshots of other AI chats, into one row per session about the decisions the person made. It pushes the rows to Alberic's knowledge graph in `ideas/alberic`. Anyone can ask a question in Slack, through MCP or over HTTP. Haiku answers from the matching facts only and names the person, their reason, the source task and the date. When no fact answers the question, Knowly DMs the colleague with the closest related fact in Slack, and their answer goes into the graph as their own fact.

The stage demo and its setup script are in [`demo/README.md`](demo/README.md). The hackathon team setup guide is [`docs/team-setup.md`](docs/team-setup.md).

## Repo layout

| Path | Contents |
|---|---|
| `src/knowly/` | the server: Slack bot, MCP endpoint, `POST /api/ask` and the ask flow |
| `src/knowly/recorder/` | session and screenshot recorder, Claude Code hook and its installer |
| `tests/` | pytest suite |
| `demo/` | `full_demo.sh` and the stage script |
| `site/` | HyperFrames marketing page |
| `app/` | the team's hackathon app, deployed by `.github/workflows/deploy.yml` |
| `ideas/<name>/` | each person's experiments; `ideas/alberic` is the knowledge graph Knowly reads and writes |
| `docs/` | team setup guide, deploy notes, Claude project instructions, the header image |

## Setup

```bash
uv venv --python 3.13
uv pip install -e '.[dev]' slack-cli-hooks
.venv/bin/python -m pytest -q
```

## Run the server

The server reads the knowledge graph at `KG_URL`, default `http://127.0.0.1:8770`. `demo/full_demo.sh` starts a local copy of the graph there.

- With the Slack CLI, run `slack run` from the repo root. It installs the app from `manifest.json`, runs `app.py` and passes `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`.
- Without it, run `.venv/bin/knowly-server`. It listens on `127.0.0.1:8091` (`HOST` and `PORT` change it) and starts the Slack bot only when both Slack tokens are set.

Make an access token per person with `.venv/bin/knowly-token <person>`. `--revoke` deletes every token of that person.

| Env var | Default | Use |
|---|---|---|
| `KG_URL` | `http://127.0.0.1:8770` | the knowledge graph |
| `SLACK_PEOPLE` | | `tristan:U0C9D2HJUA1,...` maps person keys to Slack user ids where first names do not match |
| `DEFAULT_EXPERT` | | the person to ask when nobody but the asker has a related fact |
| `KNOWLY_TOKENS_DB` | `data/tokens.db` | access tokens |
| `KNOWLY_QUESTIONS_DB` | `data/questions.db` | questions sent to colleagues and their answers |
| `KNOWLY_GRAPH_TOKENS` | `data/graph_tokens.json` | `{"<person>": "<graph member token>"}`, used to post a colleague's Slack answer to the graph as their fact |

## Recording facts

### Backfill

```bash
.venv/bin/knowly-record --person tristan --push <graph url> --token <graph member token>
```

The recorder summarises every session whose compacted text changed since the last run, writes the rows to `~/.cache/knowly/signals-<person>.json` (`--out` changes it) and, with `--push`, posts them in chunks of 1000 to `<url>/signals`. `--mode turns` labels each human turn instead. `KNOWLY_TOKEN` can replace `--token`.

### Live capture

```bash
.venv/bin/knowly-install --person tristan --push <graph url> --token <graph member token> --write-settings
```

The installer writes `~/.config/knowly/recorder.json` (mode 600) and adds `knowly-hook` as a Stop and SessionEnd hook in `~/.claude/settings.json`. When a session whose folder or transcript path contains `packoverflow` (`--match` changes it) stops or ends, the hook starts a background worker and returns. The worker summarises that session again and pushes its one row, and skips the session when its compacted text is unchanged. On Stop the worker waits until 60 s have passed since the previous summary of the session, so the summary includes the turns written meanwhile. The worker logs to `~/.cache/knowly/hook.log`.

### Screenshots

For chats in Copilot, ChatGPT, Teams or any other assistant the recorder cannot read, drop a screenshot of the chat in `~/Knowly/screenshots` (`--dir` changes it).

```bash
.venv/bin/knowly-screenshots --person tristan --watch --push <graph url> --token <graph member token>
```

`--watch` checks the folder every 5 s. `claude -p --model sonnet` transcribes each new `.png`, `.jpg`, `.jpeg` or `.webp` once, in an empty temp folder with only the Read tool, and the Haiku classifier labels each human turn. The rows have `source` `screenshot`.

### Row shape

```json
{"id": "<session>:summary", "person": "tristan", "topic": "payroll-export",
 "source": "claude_session", "source_id": "<session>", "at": "<time of the last human turn>",
 "human_role": "corrected", "actor": "human", "task": "Plan the nightly payroll SFTP export",
 "why": "Set retries to 3, not 5, \"because the bank closes the SFTP window at 18:00\""}
```

`human_role` is `decided`, `corrected`, `explained_why` or `accepted_as_is`. `why` is at most 200 characters on what the person chose, corrected or ruled out, and `task` at most 80. The recorder keeps quote marks only around words the person typed.

## Asking

- Slack: `@knowly <question>` in a channel the bot is in, a DM to the bot, or `/knowly <question>`.
- MCP: `claude mcp add --transport http knowly <host>/mcp --header "Authorization: Bearer <token>"`. Clients that cannot set headers, such as a claude.ai custom connector or Copilot Studio, use the personal URL `<host>/u/<token>/mcp`. The one tool is `ask(question)`.
- HTTP: `POST /api/ask` with `Authorization: Bearer <token>` and `{"question": "..."}` returns `{known, text, question_id, pinged, sources}`, or 502 when the graph is unreachable. `GET /healthz` returns `{"ok": true}`.

When the graph does not answer the question, Knowly DMs the colleague with the strongest related fact (never the asker, else `DEFAULT_EXPERT`) with the question, who asked, up to three related facts and an Answer button. The same open question does not DM the same colleague twice. Only that colleague can submit the answer, at most 200 characters. The server posts it to the graph as their fact (`source` `gap_form`, `human_role` `answered_question`) and DMs the asker when the asker has a Slack account.

The bot maps person keys to the first name of each full Slack member. Guests are skipped, and a first name that two members share maps to nobody, so set `SLACK_PEOPLE` for them.

## Privacy

- The recorder reads only the session folders in `~/.claude/projects` whose name contains `packoverflow`.
- Raw sessions and screenshots stay on the laptop. Only the rows leave it.
- The recorder replaces pasted content with `[pasted]`, and tokens, private keys, values after `password=`, `token:` and similar, passwords in URLs and email addresses with `[redacted]`.
- Summarising runs `claude -p --model haiku` without tools under the person's own Claude Code login, on a compacted copy of the session: the human turns verbatim and Claude's text replies cut to about 1500 characters, without tool calls, tool output or subagent runs.

## Unfinished

- Knowly tokens are bearer tokens without login or expiry. Anyone holding one can ask as its person until `knowly-token --revoke` deletes it.
- The token and question stores are SQLite files next to the server, so a Cloud Run restart loses them.
- Copilot and ChatGPT sessions are read only through screenshots.
