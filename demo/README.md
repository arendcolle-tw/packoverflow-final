# Demo

`demo/full_demo.sh` sets up the whole demo on this Mac and prints every command and question used on stage. Run it from anywhere; it is safe to run again.

```bash
demo/full_demo.sh           # set up, reusing what already exists
demo/full_demo.sh --reset   # wipe the local graph, open questions and the demo session, then set up
demo/full_demo.sh --stop    # stop the bot and the local graph
```

## Setup steps in the script

1. Starts a local copy of Alberic's knowledge graph (`ideas/alberic`) on port 8770 with its data in `data/demo-graph/` and a random admin token in `data/demo-graph/admin_token`. Log: `data/demo-graph/server.log`.
2. Creates graph members `tristan` and `lies` and writes their graph tokens to `data/graph_tokens.json`. The bot posts tristan's answer with his token from that file.
3. Creates lies's MCP token with `knowly-token lies` in `data/tokens.db` and keeps it in `data/demo-lies-mcp-token`. `--reset` keeps it, so lies's MCP config stays valid.
4. Runs a real Claude Code session with Haiku in `~/Knowly/demo-knowly-payroll`: tristan asks for the nightly payroll SFTP export plan with 5 retries, then says "No, retry 3 times, not 5, because the bank closes the SFTP window at 18:00 and a late file is rejected anyway." `knowly-record --mode summary` summarises it and pushes one row to the graph as tristan's fact. A later run without `--reset` pushes `data/demo-rows.json` again and skips the session.
5. Stops any `slack run` for team T0C9C4CTJEP and starts the bot from the repo root with `KG_URL=http://127.0.0.1:8770`, `SLACK_PEOPLE=tristan:U0C9D2HJUA1`, `DEFAULT_EXPERT=tristan` and `PORT=8091`. Log: `data/slack-run.log`.
6. Prints the `claude mcp add` command for lies and the questions below.

Needs `claude` logged in, `slack` logged in to the BotTesting workspace, `uv`, and `.venv` in the repo root with Knowly and the Slack CLI hooks installed:

```bash
uv venv --python 3.13
uv pip install -e '.[dev]' slack-cli-hooks
```

## Before going on stage

1. `demo/full_demo.sh --reset`, then check that its step 4 output shows tristan's payroll fact for both queries.
2. In a second terminal, run the two lines the script prints under "lies's Claude Code" (`cd ~/Knowly/demo-lies`, then `claude mcp remove ...; claude mcp add ...`), then start `claude` there and check `/mcp` lists `knowly` as connected.
3. Open Slack as tristan in the BotTesting workspace, on the DM with Knowly (local).

## The four steps

### 1. Tristan's session becomes a fact

Show `data/demo-rows.json` or the script's step 4 output: one row, person tristan, task the session title, why "retry 3 times, not 5, because the bank closes the SFTP window at 18:00".

Say: "Tristan just worked on the payroll export with Claude. He overruled Claude on the retries and said why. The recorder kept only that decision and his reason, and pushed it to Alberic's knowledge graph as his fact. The session itself stays on his laptop."

### 2. Lies asks something nobody wrote down

In lies's Claude Code:

```
Ask knowly: What time does the nightly payroll export start?
```

Claude Code calls the `ask` tool. The answer says the start time is not recorded yet, shows tristan's related retry fact and says tristan has been asked. Tristan gets a Slack DM with the question, who asked, the related fact and an Answer button.

Say: "Lies is new on payroll. The graph has no start time, but it knows tristan reasoned about the same export, so the bot asks him instead of guessing."

### 3. Tristan answers in Slack

In Slack, tristan clicks Answer and submits:

```
It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff
```

The bot stores the answer in the graph as tristan's fact, with his own graph token. Lies has no Slack account in this workspace, so the bot sends her no DM.

Say: "One click and one sentence. His answer is now a fact in the graph under his name, same as anything he decided in a Claude session."

### 4. Lies asks again

In lies's Claude Code, the same question:

```
Ask knowly: What time does the nightly payroll export start?
```

The answer gives 16:00, tristan's reason, his name and today's date.

Say: "Next time anyone asks, the answer is there, with who said it and when."

## Fallbacks

- Claude Code does not call the tool: name it, "Use the knowly ask tool: What time does the nightly payroll export start?".
- No Claude Code: the script prints a `curl` to `POST /api/ask` with lies's token, which runs the same ask.
- No Slack DM: check `data/slack-run.log`, then rerun `demo/full_demo.sh`, which restarts the bot.

## Reset

`demo/full_demo.sh --reset` stops the bot and the local graph, deletes `data/demo-graph/`, `data/demo-rows.json`, `data/questions.db` and the demo session in `~/.claude/projects/*demo-knowly-payroll`, then sets everything up again with a fresh Claude session. Tristan's and lies's graph tokens in `data/graph_tokens.json` are replaced because the new graph does not know them. Lies's MCP token is kept.
