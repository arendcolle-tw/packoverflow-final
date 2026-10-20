# Knowledge clock and connector

**Live:** https://knowledge-mcp-323892475788.us-central1.run.app/join gives you a personal connector URL for Claude (claude.ai, Claude desktop or Claude Code). Ask Claude "Map my knowledge with Packoverflow", then "Who knows ...?". Tools: `record_signals`, `what_i_know`, `who_knows` (Albéric's ranking, vendored in `vendor/`), `knowledge_risks`, `list_topics`, prompt `map_my_knowledge`. The person always comes from the token in the URL. Design: [docs/2026-10-20-knowledge-connector-design.md](docs/2026-10-20-knowledge-connector-design.md).

Deploy: `gh workflow run deploy.yml --ref main -f source=ideas/wout -f service=knowledge-mcp`. On Cloud Run live rows and tokens live in `/tmp/kc`, so they are lost when the instance stops, unless the service runs with `--min-instances 1 --max-instances 1`.


For every critical system or topic: how often AI handled it, how often a human actually reasoned about it (decided, corrected Claude, explained why), who did, and why. Only human reasoning resets the clock, so AI-written text never counts as knowledge.
Statuses: `dark` (no human reasoning ever), `fading` (none in 14 days), `single_point` (one person), `healthy`.
Design: [docs/2026-10-20-knowledge-clock-design.md](docs/2026-10-20-knowledge-clock-design.md).

## Run

From `ideas/wout/`:

```bash
uv run --python 3.13 --with fastapi --with uvicorn --with 'mcp>=1.30,<2' uvicorn knowledge_clock.server:app --port 8765
```

Open http://localhost:8765. Demo mode is on by default (fixed "now" of 2026-10-20 16:15). `KC_NOW=live` uses the real time, `KC_SIGNALS=a.json,b.json` reads several signal files (a later file replaces rows with the same `source_id`), `KC_FADING_DAYS` changes the fading threshold.

Open http://localhost:8765/?me=wout to see the questions for one person: decisions and corrections of Claude without a why. Answers go to `data/whys.json` (not committed) and show up as that row's why.

Tests:

```bash
uv run --python 3.13 --with pytest --with pytest-asyncio --with fastapi --with httpx --with 'mcp>=1.30,<2' pytest -q
```

Regenerate `data/signals.json` from your own local Claude sessions (stand-in for Tristan's ingestion, takes a few minutes):

```bash
uv run --python 3.13 python -m standin.run --person wout
```

Only the extracted rows are committed, never raw sessions.

## Unfinished

- `data/signals.json` holds only Wout's sessions, so no topic can be `healthy` yet. Tristan's multi-person rows replace the stand-in.
- `fading` uses a fixed 14 days. Albéric's proficiency decay should replace it.
- Meeting notes as a second source: the row shape supports `source: meeting`, nothing reads meetings yet.
- No login on the clock page. Anyone who can reach the server can answer an open question for anyone (`POST /api/why`).
- The connector's identity is a bearer URL, not a password login. OAuth is a stretch.
- Live rows are lost on Cloud Run restarts until min/max instances are 1 or Firestore is added.
