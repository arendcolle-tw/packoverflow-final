# Knowledge clock

For every critical system or topic: how often AI handled it, how often a human actually reasoned about it (decided, corrected Claude, explained why), who did, and why. Only human reasoning resets the clock, so AI-written text never counts as knowledge.
Statuses: `dark` (no human reasoning ever), `fading` (none in 14 days), `single_point` (one person), `healthy`.
Design: [docs/2026-10-20-knowledge-clock-design.md](docs/2026-10-20-knowledge-clock-design.md).

## Run

From `ideas/wout/`:

```bash
uv run --python 3.13 --with fastapi --with uvicorn uvicorn knowledge_clock.server:app --port 8765
```

Open http://localhost:8765. Demo mode is on by default (fixed "now" of 2026-10-20 16:15). `KC_NOW=live` uses the real time, `KC_SIGNALS=a.json,b.json` reads several signal files (a later file replaces rows with the same `source_id`), `KC_FADING_DAYS` changes the fading threshold.

Tests:

```bash
uv run --python 3.13 --with pytest --with fastapi --with httpx pytest -q
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
- Asking for the why when someone overrules Claude without one.
- No login. Security lives in `app/`.
