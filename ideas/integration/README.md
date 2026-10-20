# Integration: recorder rows into the knowledge graph

`to_graph.py` maps Tristan's recorder output (`ideas/tristan/data/signals-*.json`, also the screenshot files) onto the body of the knowledge-graph service's `POST /signals`.

- Keeps `id, topic, source, source_id, at, human_role, actor, why` and the optional `task` and `app`.
- Keeps `person` because the service requires it, but the service replaces it with the member token's person.
- Re-runs the recorder's own secret scrub on `why`, `task` and `app` and caps them at 200, 80 and 300 characters.
- Rejects rows with an unknown role, actor or source (the graph's own list) or a bad time, and dedupes on `id` (later row wins).

```bash
python3 ideas/integration/to_graph.py ideas/tristan/data/signals-wout.json --out /tmp/signals.json   # dry run
python3 ideas/integration/to_graph.py ideas/tristan/data/signals-*.json --post <service url> --token <member token>
```

One token is one person, so post each person's file with their own token.

Tests: `python3 -m pytest -q ideas/integration/tests`

The recorder itself (`ideas/tristan/recorder`) now posts to `POST /signals` too, so `--push <graph url>` works without this script.

A row id belongs to its first writer: posting Wout's rows with someone else's token is rejected, by design.

## Unfinished

- Not run against the live service yet, only against a local copy of it: needs a member token from `POST /members`.
