<p align="center"><img src="assets/hero.svg" alt="Knowly" width="100%"></p>

One central, fact-based knowledge base. Every fact has a person and a reason.

## Motivation

A team holds a lot of knowledge. Much of it is in people's heads, and the rest is spread over documents, tickets, chats and AI sessions. When someone needs a piece of it, they cannot find it, or they find it without knowing who decided it or why, so they cannot trust it.

Knowly keeps that knowledge in one central, fact-based knowledge base. Each fact names the person it comes from and records their reason. Knowly fills the store from people's Claude sessions while they work, and from the answers people give to questions it could not answer yet. People ask in the tools they already use: a Slack channel, Claude Code or any other MCP client, or HTTP.

## How it works

<p align="center"><img src="assets/header.svg" alt="How Knowly works" width="100%"></p>

Knowly has three loops over one fact store.

| Loop | Flow |
|---|---|
| Write | You work with Claude. `knowly-hook`, or `knowly-record` for past sessions, summarises the session into one fact under your name: the decisions you made and your reason, quoted from what you typed. |
| Read | Someone asks in #ask-knowly, over MCP or with `POST /api/ask`. The Knowly agent searches the store and answers with the person, their reason, the source and the date. |
| Learn | When no fact answers the question, Knowly replies with the related facts and tags the person most likely to know. `knowly.slack` parses that person's reply in the thread into a fact under their name, and the agent answers the question the next time anyone asks. |

### Packages in `src/knowly/`

| Package | Contents |
|---|---|
| `config.py` | every setting, read from the environment (see [Configuration](#configuration)) |
| `server.py` | `knowly-server`: one FastAPI service with the store API, MCP, `/api/ask` and `/healthz`; starts the Slack bot when both Slack tokens are set |
| `store/` | `FactStore` on SQLite, scoring with time decay, the `/store` router, gaps (work and facts without a reason) with optional voice follow-up calls, the Cloud Storage mirror |
| `capture/` | sessions to facts: `knowly-record` (backfill), `knowly-hook` and `knowly-install` (live Claude Code hook), `knowly-screenshots` (Claude reads screenshots of other AI chats) |
| `agent/` | `answer(question, asker)`: runs Claude (`claude -p`, Haiku) with `search_facts`, `person_facts` and `recent_facts` over the store; returns an answer with sources, or "not known" with related facts and the person to ask |
| `slack/` | the bot (DM, @mention, `/knowly`), the #ask-knowly thread flow, and `extract`, which turns a reply into a fact |
| `ask.py` | the ask flow that Slack, MCP and `/api/ask` share |
| `members.py` | creates store members and their tokens on demand |
| `tokens.py` | `knowly-token`: MCP and API tokens per person |
| `mcp_server.py` | the MCP server with one tool, `ask` |
| `client.py` | HTTP client for the store API |

### Endpoints

| Route | Token | Use |
|---|---|---|
| `POST /store/facts` | member | add facts under the token's person |
| `POST /store/members` | admin | create a member; returns `{"person", "token"}` |
| `GET /store/who_knows?q=` | | people ranked by matching facts, with their reasons |
| `GET /store/people/{person}` | | one person's facts |
| `GET /store/risks` | | topics riskiest first: no reason recorded, one person only, fading |
| `GET /store/rows` | | every fact |
| `/store/gaps` | | work and facts without a recorded reason, with follow-up drafts |
| `POST /api/ask` | `knowly-token` | `{"question": "..."}`; the answer with sources, or related facts and the person to ask |
| `/mcp`, `/u/<token>/mcp` | `knowly-token` | MCP with the `ask` tool; the `/u/<token>` form is for clients that cannot set headers |
| `GET /healthz` | | `{"ok": true}` |

## Demo

The demo runs in #ask-knowly with two personas, tristan and lies.

1. Tristan plans the nightly payroll SFTP export with Claude and overrules it: retry 3 times, not 5, because the bank closes the SFTP window at 18:00. `knowly-record` stores that decision and his reason as his fact.
2. Lies asks "What time does the nightly payroll export start?". Knowly replies in the thread that the start time is not recorded, shows tristan's related retry fact and tags tristan.
3. Tristan replies in the thread: "16:00, so three retries still finish before the bank closes the SFTP window at 18:00." Knowly saves it as his fact and reacts with a checkmark.
4. Lies asks again. Knowly answers 16:00, with tristan's name, his reason and today's date.

```bash
./demo/full_demo.sh --reset
```

The script sets up the whole demo in one command. [`demo/README.md`](demo/README.md) is the stage script with fallbacks.

## Quickstart

```bash
uv venv --python 3.13
uv pip install -e '.[dev]'
source .venv/bin/activate
python -m pytest -q

export KNOWLY_ADMIN_TOKEN=$(openssl rand -hex 32)
knowly-server                 # http://127.0.0.1:8091
```

For the Slack bot, run `uv pip install slack-cli-hooks` once, then `slack run` from the repo root instead of `knowly-server`. The Slack CLI installs the app from `manifest.json`, runs `app.py` and sets `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`.

Create a member and keep the returned token:

```bash
curl -s -X POST http://127.0.0.1:8091/store/members \
  -H "Authorization: Bearer $KNOWLY_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"person": "tristan"}'
```

Record your past Claude sessions, then install the hook that records new ones:

```bash
knowly-record --push http://127.0.0.1:8091 --token=<member token>
knowly-install --push http://127.0.0.1:8091 --token=<member token> --write-settings
```

`knowly-install` adds `knowly-hook` as a Stop and SessionEnd hook in `~/.claude/settings.json`. The hook hands the summary to a background worker, debounced per session, and returns at once.

Ask from Claude Code over MCP:

```bash
knowly-token tristan
claude mcp add --transport http knowly http://127.0.0.1:8091/mcp --header "Authorization: Bearer <token>"
```

## Configuration

| Variable | Default | Use |
|---|---|---|
| `KNOWLY_DATA_DIR` | `./data` | folder for every SQLite file |
| `KNOWLY_URL` | `http://127.0.0.1:$PORT` | the server's own base URL |
| `KNOWLY_ADMIN_TOKEN` | | store admin token, at least 32 characters; required to create members |
| `KNOWLY_BUCKET` | | Cloud Storage bucket that mirrors the fact store |
| `KNOWLY_CHANNEL` | `ask-knowly` | Slack channel for questions |
| `KNOWLY_ALLOW_SELF` | | `1` lets one Slack account both ask and answer |
| `SLACK_PEOPLE` | | `name:Uxxx,...` maps person names to Slack user ids |
| `DEFAULT_EXPERT` | | the person to tag when no related fact names anyone else |
| `PORT` | `8091` | server port |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | set by `slack run` | the server starts the Slack bot when both are set |
| `KNOWLY_TOKEN` | | member token for `knowly-record`, instead of `--token` |
| `ANTHROPIC_API_KEY` | | Claude drafts the follow-up questions for gaps; without it the store uses a template |
| `ELEVENLABS_*` | | voice follow-up calls for gaps |

## Privacy and security

- `knowly-record` reads sessions on the laptop and pushes only the summaries. It never sends a raw session or screenshot to the store.
- Before summarising, capture replaces tokens, private keys, passwords and email addresses with `[redacted]`.
- Summarising runs `claude -p` under the person's own Claude Code login.
- The store sets a fact's person from the member token or the Slack identity, never from the request body.
- Capture checks every quote in a summary against what the person typed, and keeps quote marks only around their own words.
- The fact store is a SQLite file in `KNOWLY_DATA_DIR` on your own server, optionally mirrored to your own Cloud Storage bucket.

## Repository layout

```
src/knowly/           the Knowly service and CLIs (see Packages)
tests/                store, capture, agent, slack, server
demo/                 full_demo.sh and the stage script
assets/               hero.svg, header.svg, icon.png
app/                  a separate Node app of the team
.github/workflows/    Cloud Run deploys: app/ as packoverflow, the repo root as knowly
pyproject.toml        package and CLI entry points
manifest.json         Slack app manifest
app.py                entry point for `slack run`
```

## Unfinished

- Knowly calls Claude through the `claude` CLI, so the server needs a logged-in Claude Code. A server deployment needs an API key path.
- The store is SQLite, so Knowly runs as one instance.
- Tokens are bearer tokens. There is no SSO.
- Knowly does not cache answers; every question runs the agent.
- Screenshot capture and per-turn mode (`knowly-record --mode turns`) work but are not part of the demo.

---

Built at the Tectonic Hackathon final (SD Worx track) by the Packoverflow team.
