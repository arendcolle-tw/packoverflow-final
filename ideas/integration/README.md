# Integration: recorder rows into the knowledge graph

`to_graph.py` maps Tristan's recorder output (`ideas/tristan/data/signals-*.json`, also the screenshot files) onto the body of the knowledge-graph service's `POST /signals`.

- Keeps `id, topic, source, source_id, at, human_role, actor, why` and the optional `task` and `app`.
- Drops `person`, because the service takes it from the member token.
- Re-runs the recorder's own secret scrub on `why`, `task` and `app` and caps them at 200, 80 and 40 characters.
- Rejects rows with an unknown role, actor or source (allowed: `claude_session`, `meeting`, `screenshot`, `mcp_record`, `copilot_*`) or a bad time, and dedupes on `id` (later row wins).

```bash
python3 ideas/integration/to_graph.py ideas/tristan/data/signals-wout.json --out /tmp/signals.json   # dry run
python3 ideas/integration/to_graph.py ideas/tristan/data/signals-*.json --post <service url> --token <member token>
```

One token is one person, so post each person's file with their own token.

Tests: `python3 -m pytest -q ideas/integration/tests`

## Unfinished

- Not run against the live service: no member token exists yet, and the service's exact field rules are assumed from its brief.
