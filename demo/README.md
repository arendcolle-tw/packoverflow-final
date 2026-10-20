# Demo

`demo/full_demo.sh` sets up the whole demo on this Mac and prints every question used on stage. Run it from anywhere; it is safe to run again.

```bash
demo/full_demo.sh           # set up, reusing what already exists
demo/full_demo.sh --reset   # wipe data/ and the demo Claude session, then set up
demo/full_demo.sh --stop    # stop the server
```

## Setup steps in the script

1. Writes a random admin token to `data/admin_token` if there is none, stops any `slack run` for team T0C9C4CTJEP and starts one Knowly server with `slack run` from the repo root. The server holds the fact store (under `/store`), the Slack bot, MCP and `POST /api/ask` on port 8091, with `KNOWLY_DATA_DIR=data`, `KNOWLY_CHANNEL=ask_knowly`, `SLACK_PEOPLE=tristan:U0C9D2HJUA1`, `KNOWLY_ALLOW_SELF=1` and `DEFAULT_EXPERT=tristan`. Log: `data/slack-run.log`.
2. Creates members `tristan` and `alberic` with `POST /store/members` and writes their member tokens to `data/member_tokens.json`. The server stores answers from Slack with the replier's token from that file.
3. Creates Alberic's MCP token with `knowly-token --db data/tokens.db alberic` and keeps it in `data/alberic-mcp-token`.
4. Runs a real Claude Code session with Haiku in `~/Knowly/demo-payroll`: tristan asks for the nightly payroll SFTP export plan with 5 retries, then says "No, retry 3 times, not 5, because the bank closes the SFTP window at 18:00 and a late file is rejected anyway." `knowly-record --mode summary --push http://127.0.0.1:8091` summarises it and pushes one fact to `/store/facts` under tristan's name, and keeps a copy in `data/demo-rows.json`. A later run without `--reset` skips this step when the store already has tristan's facts. The script then prints what the store returns for the payroll queries.
5. Prints the four steps below and the MCP alternative for Alberic.

Needs `claude` logged in, `slack` logged in to the BotTesting workspace, `uv`, and `.venv` in the repo root with Knowly and the Slack CLI hooks installed:

```bash
uv venv --python 3.13
uv pip install -e '.[dev]' slack-cli-hooks
```

## Before going on stage

1. `demo/full_demo.sh --reset`, then check that its step 4 output shows tristan's payroll fact for both queries.
2. Open Slack in the BotTesting workspace, in `#ask_knowly`: Alberic on one screen to ask, Tristan (U0C9D2HJUA1) on the other to answer. Knowly (local) must be a member of the channel; if not, `/invite @knowly` there. `SLACK_PEOPLE` maps Tristan by id; Knowly finds Alberic by his Slack name, accents and case ignored.
3. For the MCP alternative, in a second terminal, run the lines the script prints under "The same answers over MCP" and check that `/mcp` in Claude Code lists `knowly` as connected.

## The four steps

### 1. Tristan's session becomes a fact

Show `data/demo-rows.json` or the script's step 4 output: one fact, person tristan, task the session title, why "retry 3 times, not 5, because the bank closes the SFTP window at 18:00".

Say: "Tristan just worked on the payroll export with Claude. He overruled Claude on the retries and said why. Knowly kept only that decision and his reason, and stored it as his fact. The session itself stays on his laptop."

### 2. A question nobody wrote down

Alberic posts in `#ask_knowly`:

```
What time does the nightly payroll export start?
```

Knowly searches the fact store and answers in the thread in its own words, for example: "Based on what's in Knowly there's no answer to this yet. Tristan set up the nightly payroll export and decided its retry policy, so he's the one to ask." The related fact shows underneath as "Tristan · date". A second message tags Tristan with the question, so Slack notifies him.

Say: "The store has no start time, but it knows tristan reasoned about the same export, so Knowly asks him instead of guessing."

### 3. Tristan answers in the thread

Tristan replies in that thread:

```
It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff
```

Knowly parses the reply into a fact under Tristan's name, stores it with his member token, puts a check mark on the reply and thanks him in the thread. `KNOWLY_ALLOW_SELF=1` also lets the asker answer their own question, for a rehearsal with one Slack account.

Say: "One sentence in Slack. His answer is now a fact under his name, with his reason, same as anything he decided in a Claude session."

### 4. Ask again

Alberic posts the same question in `#ask_knowly` as a new message. Knowly answers in a sentence or two, for example "The export starts at 16:00. Tristan chose that so three retries still finish before the bank closes the SFTP window at 18:00.", with "Tristan · today's date" underneath.

Say: "Next time anyone asks, the answer is there, with who said it and why."

## MCP alternative

The script prints a `claude mcp add` line for Alberic with his MCP token. In his Claude Code, `Ask knowly: What time does the nightly payroll export start?` calls the `ask` tool on the same server and gets the same answers as `#ask_knowly`. Without Claude Code, the printed `curl` to `POST /api/ask` with Alberic's token runs the same ask. Outside Slack the ping names Tristan in plain text.

## Fallbacks

- Claude Code does not call the tool: name it, "Use the knowly ask tool: What time does the nightly payroll export start?".
- Knowly does not answer in `#ask_knowly`: check that it is in the channel and read `data/slack-run.log`, then rerun `demo/full_demo.sh`, which restarts the server.

## Reset

`demo/full_demo.sh --reset` stops the server, deletes `data/` (fact store, member and MCP tokens, admin token, open questions, threads) and the demo session in `~/.claude/projects/*demo-payroll`, then sets everything up again with a fresh Claude session. Alberic's MCP token changes, so rerun the printed `claude mcp add` line.
