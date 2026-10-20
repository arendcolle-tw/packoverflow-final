<p align="center">
  <img src="assets/hero.svg" alt="Knowly: one centralised knowledge base. All files, facts and sessions in one place." width="100%">
</p>

Knowly is one centralised knowledge base. All files, facts and sessions sit in one place, and every fact has a person and a reason.

## How it works

1. **Capture.** Every Claude session is summarised around the decisions you made and why, and stored as your fact.
2. **Ask.** Ask in Slack (`#ask-knowly`) or from Claude over MCP. The Knowly agent searches the knowledge base and answers with the person, their reason and the source.
3. **Learn.** When Knowly does not know, it tags the person most likely to know. Their reply in the thread becomes a fact, so the next person gets the answer straight away.

## Run the demo

```bash
./demo/full_demo.sh
```

Then follow [demo/README.md](demo/README.md).

## Develop

```bash
uv venv --python 3.13 && uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
knowly-server
```

## Layout

```
src/knowly/   capture, store, agent, slack, server
tests/        test suite
demo/         one-command demo setup and stage script
assets/       images
app/          team web app
```

## Unfinished

- Claude runs through the `claude` CLI; a server deployment needs an API key instead.
- SQLite storage, so one instance at a time.

Built at the Tectonic Hackathon final (SD Worx track) by the Packoverflow team.
