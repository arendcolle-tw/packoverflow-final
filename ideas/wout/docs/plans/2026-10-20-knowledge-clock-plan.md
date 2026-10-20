# Knowledge Clock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A service that reads knowledge signals (Claude sessions now, meetings later) and shows, per topic, how often AI handled it versus how often a human reasoned about it, who did, and why.

**Architecture:** A pure function turns signal rows into topic summaries (`clock.py`). A loader validates and merges signal files (`store.py`). FastAPI serves JSON and one static page. A throwaway stand-in turns local Claude session files into signal rows via `claude -p`, until Tristan's ingestion replaces it.

**Tech Stack:** Python 3.12 through `uv run`, FastAPI, uvicorn, vanilla HTML/JS, pytest, httpx.

**Spec:** `ideas/wout/docs/2026-10-20-knowledge-clock-design.md`

## Global Constraints

- All files under `ideas/wout/`. Branch `idea/wout`.
- Run everything from `ideas/wout/` with `uv run --python 3.12 --with fastapi --with uvicorn --with httpx --with pytest ...`. No other dependencies.
- Signal row fields: `id, person, topic, source, source_id, at, human_role, why, actor`.
- `REASONING_ROLES = {"decided", "corrected", "explained_why", "answered_question"}`. `accepted_as_is` and `actor == "agent"` count toward `ai_count`.
- Certainty: meeting + human + reasoning = `confirmed`; claude_session + human + reasoning = `likely`; actor `unknown` + reasoning = `uncertain`; everything else = `ai`. Only `confirmed` and `likely` reset the clock.
- Status order: `dark`, `fading`, `single_point`, `healthy`. Sort order: `dark`, `single_point`, `fading`, `healthy`, then `ai_count` descending.
- `FADING_DAYS` default 14. Demo now `2026-10-20T16:15:00+02:00`.
- Headline copy: `Claude handled {ai_count} requests on its own. Humans reasoned {human_count} times.`
- Raw session text never committed. Only signal rows. `why` at most 200 chars, scrubbed of key-like strings and emails.
- No em-dashes anywhere. Comments only when the why is non-obvious, one line.

## Review Focus

1. Tristan's file has a malformed row (missing field, unknown role, bad timestamp): the row is skipped and counted, the API still answers. Test in Task 2.
2. A `why` containing `<script>` or HTML: shown as text, never executed. Test in Task 5.
3. `claude -p` writes its own session files into `~/.claude/projects`, and the next stand-in run ingests the classifier prompt as a human turn: the command uses `--no-session-persistence` and runs outside the repo. Test in Task 4.
4. Timestamps with `Z`, with an offset, without a zone, or in the future: all parse, `days_since` is never negative. Test in Task 1.
5. A topic whose only rows are `uncertain`, and two topic names that are aliases of one system: the first is `dark`, the second merges into one topic. Test in Task 1.

---

## File Structure

```
ideas/wout/
  conftest.py                     # empty, puts ideas/wout on sys.path for tests
  README.md                       # what it is, how to run, what's unfinished
  knowledge_clock/__init__.py
  knowledge_clock/clock.py        # pure: certainty, compute_topics, topic_detail, summarize
  knowledge_clock/store.py        # load + validate + merge signal files, load aliases
  knowledge_clock/server.py       # FastAPI app, config from env
  knowledge_clock/static/index.html
  standin/__init__.py
  standin/sessions.py             # jsonl -> human turns, subagent runs; scrub
  standin/classify.py             # claude -p prompt, command, parse
  standin/run.py                  # CLI writing data/signals.json
  data/signals.json               # generated, committed
  data/aliases.json               # {} at start
  tests/test_clock.py  tests/test_store.py  tests/test_server.py
  tests/test_sessions.py  tests/test_classify.py
```

### Task 1: Clock core

**Files:**
- Create: `ideas/wout/conftest.py`, `ideas/wout/knowledge_clock/__init__.py`, `ideas/wout/knowledge_clock/clock.py`
- Test: `ideas/wout/tests/test_clock.py`

**Interfaces:**
- Produces:
  - `parse_at(value: str) -> datetime` (aware, UTC if no zone; raises `ValueError` on garbage)
  - `certainty(signal: dict) -> str` returns `"confirmed" | "likely" | "uncertain" | "ai"`
  - `compute_topics(signals: list[dict], now: datetime, fading_days: int = 14, aliases: dict[str, str] | None = None) -> list[dict]`
    Each topic: `{topic, status, ai_count, human_count, uncertain_count, last_human_reasoning_at: str | None, days_since: int | None, reasoners: [{person, count, last_at, last_why}]}`, sorted per Global Constraints. `reasoners` sorted by `count` desc. `last_why` is the most recent non-null why of that person on that topic.
  - `topic_detail(signals, topic, now, fading_days=14, aliases=None) -> dict | None`: the topic dict plus `signals: [{id, person, at, human_role, why, certainty, source, source_id}]`, newest first. `None` if the topic is unknown.
  - `summarize(topics: list[dict]) -> dict`: `{ai_count, human_count, topic_count, by_status: {dark, single_point, fading, healthy}}`

- [ ] **Step 1: Write the failing tests**

Helper `row(**kw)` returns a valid signal with defaults `person="wout", topic="aikido", source="claude_session", source_id="s1", at="2026-10-20T10:00:00Z", human_role="decided", why=None, actor="human"` and a unique `id`. `NOW = parse_at("2026-10-20T16:15:00+02:00")`.

```python
def test_certainty_levels():
    assert certainty(row(source="meeting", human_role="answered_question")) == "confirmed"
    assert certainty(row()) == "likely"
    assert certainty(row(actor="unknown")) == "uncertain"
    assert certainty(row(human_role="accepted_as_is")) == "ai"
    assert certainty(row(actor="agent", human_role="decided")) == "ai"

def test_dark_when_only_ai():
    [t] = compute_topics([row(human_role="accepted_as_is"), row(actor="agent")], NOW)
    assert (t["status"], t["ai_count"], t["human_count"], t["days_since"]) == ("dark", 2, 0, None)

def test_dark_when_only_uncertain():
    [t] = compute_topics([row(actor="unknown")], NOW)
    assert t["status"] == "dark" and t["uncertain_count"] == 1

def test_single_point_then_healthy():
    [t] = compute_topics([row(person="wout")], NOW)
    assert t["status"] == "single_point"
    [t] = compute_topics([row(person="wout"), row(person="tristan")], NOW)
    assert t["status"] == "healthy"

def test_fading_beats_single_point():
    [t] = compute_topics([row(at="2026-09-30T19:00:00Z")], NOW, fading_days=14)
    assert t["status"] == "fading" and t["days_since"] == 19

def test_timestamps_and_future():
    for at in ["2026-10-20T10:00:00Z", "2026-10-20T12:00:00+02:00", "2026-10-20T10:00:00"]:
        assert parse_at(at).tzinfo is not None
    [t] = compute_topics([row(at="2026-10-25T10:00:00Z")], NOW)
    assert t["days_since"] == 0

def test_aliases_merge_topics():
    topics = compute_topics([row(topic="aikido"), row(topic="aikido-scan", person="tristan")], NOW, aliases={"aikido-scan": "aikido"})
    assert [t["topic"] for t in topics] == ["aikido"] and topics[0]["status"] == "healthy"

def test_sort_order_and_reasoners():
    sig = [row(topic="a", human_role="accepted_as_is"), row(topic="b"), row(topic="c", at="2026-09-01T00:00:00Z"),
           row(topic="d", person="x"), row(topic="d", person="y", why="because PC 200"), row(topic="d", person="y")]
    topics = compute_topics(sig, NOW)
    assert [t["status"] for t in topics] == ["dark", "single_point", "fading", "healthy"]
    assert topics[3]["reasoners"][0] == {"person": "y", "count": 2, "last_at": "2026-10-20T10:00:00+00:00", "last_why": "because PC 200"}

def test_detail_and_summary():
    sig = [row(why="w1"), row(human_role="accepted_as_is")]
    d = topic_detail(sig, "aikido", NOW)
    assert len(d["signals"]) == 2 and {s["certainty"] for s in d["signals"]} == {"likely", "ai"}
    assert topic_detail(sig, "nope", NOW) is None
    s = summarize(compute_topics(sig, NOW))
    assert s == {"ai_count": 1, "human_count": 1, "topic_count": 1, "by_status": {"dark": 0, "single_point": 1, "fading": 0, "healthy": 0}}
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError: knowledge_clock`)

Run: `cd ideas/wout && uv run --python 3.12 --with pytest pytest tests/test_clock.py -q`

- [ ] **Step 3: Implement the functions above in `knowledge_clock/clock.py`.** `days_since = max(0, (now - last).days)`. `last_at` is serialized with `datetime.isoformat()` in UTC. `human_count` counts `confirmed` + `likely` rows only.

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit** `git add ideas/wout && git commit -m "Add knowledge clock core"`

### Task 2: Signal store

**Files:**
- Create: `ideas/wout/knowledge_clock/store.py`, `ideas/wout/data/aliases.json` (`{}`)
- Test: `ideas/wout/tests/test_store.py`

**Interfaces:**
- Consumes: `parse_at` from Task 1.
- Produces:
  - `validate(row: dict) -> bool`: all nine fields present, `human_role` in the five roles, `source` in `{"claude_session", "meeting"}`, `actor` in `{"human", "agent", "unknown"}`, `at` parses, `why` is `str | None`.
  - `load_signals(paths: list[Path]) -> tuple[list[dict], int]`: valid rows and skipped count. Missing file contributes nothing. A later file's rows replace every earlier row with the same `source_id`. Duplicate `id`s keep the last.
  - `load_aliases(path: Path) -> dict[str, str]`: `{}` if missing.

- [ ] **Step 1: Write the failing tests** (write JSON files into `tmp_path`)

```python
def test_skips_malformed_rows(tmp_path):
    good = row(); bad1 = {**row(), "human_role": "vibes"}; bad2 = {**row()}; del bad2["person"]; bad3 = {**row(), "at": "yesterday"}
    rows, skipped = load_signals([write(tmp_path, "a.json", [good, bad1, bad2, bad3])])
    assert [r["id"] for r in rows] == [good["id"]] and skipped == 3

def test_later_file_replaces_same_source(tmp_path):
    standin = [row(id="s1:a", source_id="s1"), row(id="s2:a", source_id="s2")]
    real = [row(id="s1:x", source_id="s1")]
    rows, _ = load_signals([write(tmp_path, "standin.json", standin), write(tmp_path, "real.json", real)])
    assert sorted(r["id"] for r in rows) == ["s1:x", "s2:a"]

def test_missing_files(tmp_path):
    assert load_signals([tmp_path / "nope.json"]) == ([], 0)
    assert load_aliases(tmp_path / "nope.json") == {}
```

`row` and `write` helpers live in `tests/helpers.py` and are reused by Task 1 and Task 5 tests (move Task 1's `row` there).

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement** in `knowledge_clock/store.py`.
- [ ] **Step 4: Run all tests, expect PASS**
- [ ] **Step 5: Commit** `"Add signal store with validation and source replacement"`

### Task 3: Stand-in session parsing

**Files:**
- Create: `ideas/wout/standin/__init__.py`, `ideas/wout/standin/sessions.py`
- Test: `ideas/wout/tests/test_sessions.py`

**Interfaces:**
- Produces:
  - `human_turns(session_file: Path) -> list[dict]`: `{source_id: sessionId, message_uuid: uuid, at: timestamp, text, context}`. A record is a human turn when `type == "user"`, `isSidechain` is falsy, `isMeta` is falsy, content is a string or text blocks with no `tool_result` block, and the stripped text does not start with `<`. `<pasted_content ...>...</pasted_content>` blocks are replaced by `[pasted]` (pasted text is not the human's own knowledge). `context` is the last assistant text before it, at most 400 chars.
  - `subagent_runs(session_dir: Path) -> list[dict]`: one per `subagents/**/agent-*.jsonl`: `{source_id: "<sessionId>:<agentId>", message_uuid: "run", at: first timestamp, text: first user prompt, at most 1500 chars}`.
  - `scrub(text: str) -> str`: replaces `sk-[A-Za-z0-9_-]{10,}`, `ghp_[A-Za-z0-9]{20,}`, `xox[baprs]-[A-Za-z0-9-]+`, `AKIA[0-9A-Z]{16}` and email addresses with `[redacted]`.

- [ ] **Step 1: Write the failing tests** with a hand-built jsonl in `tmp_path`: one real human turn, one tool_result user record, one `isMeta` record, one `<command-name>` record, one sidechain record, one assistant text before the human turn, one human turn with a pasted block.

```python
def test_human_turns_filters(tmp_path):
    turns = human_turns(make_session(tmp_path))
    assert [t["text"] for t in turns] == ["We go with FastAPI because nobody picked a stack", "Use this: [pasted] and keep it short"]
    assert turns[0]["context"] == "Which stack?" and turns[0]["source_id"] == "sess-1"

def test_subagent_runs(tmp_path):
    runs = subagent_runs(make_subagent(tmp_path))
    assert runs == [{"source_id": "sess-1:abc", "message_uuid": "run", "at": "2026-10-20T09:00:00Z", "text": "Review the design doc"}]

def test_scrub():
    assert scrub("key sk-ant-abcdefghijkl mail wout@techwolf.ai") == "key [redacted] mail [redacted]"
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement** in `standin/sessions.py`.
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `"Add stand-in Claude session parser"`

### Task 4: Stand-in classification and real data

**Files:**
- Create: `ideas/wout/standin/classify.py`, `ideas/wout/standin/run.py`, `ideas/wout/data/signals.json` (generated)
- Test: `ideas/wout/tests/test_classify.py`

**Interfaces:**
- Consumes: `human_turns`, `subagent_runs`, `scrub` from Task 3; `validate` from Task 2.
- Produces:
  - `TOPIC_HINTS: list[str]`: `["aikido-security-scan", "github-repo-setup", "slack-claude-pipeline", "claude-skills", "repo-cleanup", "idea-and-scope", "pitch-and-submission", "knowledge-clock"]`. The model may add new kebab-case topics.
  - `build_command(schema: dict) -> list[str]`: `["claude", "-p", "--model", "haiku", "--no-session-persistence", "--tools", "", "--output-format", "json", "--json-schema", json.dumps(schema)]`.
  - `build_prompt(turns: list[dict]) -> str`: asks for one object per turn `{key, topic, human_role, why, actor}` using the role definitions from the spec. `why` is a verbatim quote of the human's own reason, at most 200 chars, or null. `actor` is `agent` when the text is clearly pasted AI output or another agent, `unknown` when unsure.
  - `parse_output(stdout: str) -> list[dict]`: reads `structured_output.items` if present, else the first JSON array inside `result`.
  - `classify(turns: list[dict]) -> list[dict]`: runs the command with `cwd` set to a temp dir outside the repo, prompt on stdin, batches of 25 turns.
  - `run.py` CLI: `--projects-dir ~/.claude/projects --match packoverflow --person wout --out data/signals.json`. Subagent runs become rows with `actor="agent"`, `human_role="accepted_as_is"`, `why=None`, topic from classification. Every row gets `id = f"{source_id}:{message_uuid}"`, `source="claude_session"`, `why` scrubbed and cut to 200 chars. Rows failing `validate` are dropped and the count printed.

- [ ] **Step 1: Write the failing tests**

```python
def test_command_never_persists_sessions():
    cmd = build_command({"type": "object"})
    assert "--no-session-persistence" in cmd and cmd[cmd.index("--model") + 1] == "haiku"

def test_parse_structured_and_text():
    items = [{"key": "k1", "topic": "aikido-security-scan", "human_role": "decided", "why": None, "actor": "human"}]
    assert parse_output(json.dumps({"structured_output": {"items": items}})) == items
    assert parse_output(json.dumps({"result": "Here you go:\n" + json.dumps(items)})) == items

def test_prompt_contains_turns_and_hints():
    p = build_prompt([{"key": "k1", "text": "Wait, put the skills back", "context": "Removed skills"}])
    assert "k1" in p and "Wait, put the skills back" in p and "aikido-security-scan" in p
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement** `classify.py` and `run.py`.
- [ ] **Step 4: Run tests, expect PASS**
- [ ] **Step 5: Generate real data.** Run: `cd ideas/wout && uv run --python 3.12 python -m standin.run --person wout --out data/signals.json`. Expected: a printed count of rows (roughly 40 human turns plus subagent runs) and 0 or few dropped. Open the file: every row has a topic, `why` values are the human's own words, no raw prompt text beyond 200-char whys, no secrets.
- [ ] **Step 6: Commit** `"Add stand-in classifier and real signals from Wout's sessions"`

### Task 5: API and page

**Files:**
- Create: `ideas/wout/knowledge_clock/server.py`, `ideas/wout/knowledge_clock/static/index.html`, `ideas/wout/README.md`
- Test: `ideas/wout/tests/test_server.py`

**Interfaces:**
- Consumes: everything in Tasks 1 and 2.
- Produces: `app: FastAPI` in `knowledge_clock/server.py`. Config read per request from env: `KC_SIGNALS` (comma-separated paths, default `data/signals.json`), `KC_ALIASES` (default `data/aliases.json`), `KC_FADING_DAYS` (default `14`), `KC_NOW` (unset = demo time `2026-10-20T16:15:00+02:00`, `live` = real time, else an ISO time). Paths are relative to `ideas/wout/`.
  - `GET /api/summary` -> `summarize(...)` plus `skipped` and `now`.
  - `GET /api/topics` -> list from `compute_topics`.
  - `GET /api/topics/{topic}` -> `topic_detail`, 404 if `None`.
  - `GET /` -> `static/index.html`.

- [ ] **Step 1: Write the failing tests** using `TestClient`, with `KC_SIGNALS` pointing at a tmp file via `monkeypatch.setenv`.

```python
def test_summary_and_topics(client):
    s = client.get("/api/summary").json()
    assert s["ai_count"] == 1 and s["human_count"] == 1 and s["skipped"] == 0
    assert [t["topic"] for t in client.get("/api/topics").json()] == ["aikido"]

def test_detail_404_and_encoded_topic(client):
    assert client.get("/api/topics/nope").status_code == 404
    assert client.get("/api/topics/aikido").json()["signals"][0]["why"] == "<script>alert(1)</script>"

def test_page_never_injects_html():
    html = (Path(__file__).parents[1] / "knowledge_clock/static/index.html").read_text()
    assert "innerHTML" not in html and "/api/summary" in html
```

The fixture file has one `accepted_as_is` row and one `decided` row with `why="<script>alert(1)</script>"` on topic `aikido`.

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `server.py`.**
- [ ] **Step 4: Build `index.html`.** All DOM built with `createElement` and `textContent`. Topic names go through `encodeURIComponent` in fetch URLs. Layout:
  - Top: the headline copy from Global Constraints in large type, below it `{topic_count} topics · {dark} dark · {single_point} single point`.
  - Topic list, one row each: topic name, status chip (dark = near-black, single_point = red, fading = amber, healthy = green), "last human reasoning {days_since} days ago" or "never", a two-part bar of `ai_count` vs `human_count`, reasoner names.
  - Click a row: a detail panel with each human signal: person, date, role, certainty label, and the why in quotes.
- [ ] **Step 5: Run tests, expect PASS.** Then run the app: `cd ideas/wout && uv run --python 3.12 --with fastapi --with uvicorn uvicorn knowledge_clock.server:app --port 8765` and open `http://localhost:8765`. Expected: the headline shows real counts from `data/signals.json`, at least one `dark` or `single_point` topic, a click shows whys.
- [ ] **Step 6: Write `README.md`:** what it is (3 lines), how to run (the two commands), what's unfinished (Tristan's real rows, Albéric's decay, meetings, why-question).
- [ ] **Step 7: Commit** `"Add knowledge clock API and page"`

### Task 6: Ship and align

- [ ] **Step 1:** Use the `hack-ship-check` skill: run the app, walk the main path once, screenshot.
- [ ] **Step 2:** Push to branch `idea/wout`.
- [ ] **Step 3:** Post `CHANGE:` in #hackathon-finale: where `data/signals.json` lives, the row shape it uses, the API endpoints. Read the channel first and adapt to anything Tristan or Albéric posted.

### Task 7: Vision text for the pitch

**Files:** Create `ideas/wout/VISION.md`.

- [ ] **Step 1:** Write it, at most one page:
  - The 30-second beat: the honest line from our own data (real counts from `/api/summary` and the most striking `dark` or `single_point` topic), the bridge "That's four people after one day. Now picture SD Worx after ten years.", then the mainframe line.
  - The four threads in one sentence each, framed as how the clock measures them.
  - Answers to the jury's five questions, one line each, taken from the design.
  - Why SD Worx should care: critical-skills and succession insight they could offer their 100,000+ customers, on top of mysdworx and agentic payroll.
- [ ] **Step 2:** Commit `"Add long-term vision text for the pitch"`, push, and tell Wout it is ready for whoever builds the deck.

### Task 8 (stretch): Ask for the why

Only after Task 7.

**Files:** Modify `knowledge_clock/server.py`, `knowledge_clock/static/index.html`, `knowledge_clock/store.py`. Create `data/whys.json` at runtime (gitignored).

**Interfaces:**
- `GET /api/questions?person=wout` -> rows with `human_role in {"decided", "corrected"}`, `source == "claude_session"`, `actor == "human"`, `why is None`, minus rows answered in `whys.json`.
- `POST /api/why` body `{id: str, why: str}` -> 204. 404 for unknown id, 422 for empty or over 200 chars. Stored `{id: why}` in `whys.json`. `load_signals` callers apply it so answered rows carry the why.

- [ ] **Step 1: Tests:** unanswered row listed; after POST it disappears from questions and `topic_detail` shows the why; empty why is 422; unknown id is 404.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**, plus a small "1 question for you" card on the page.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `"Add ask-for-the-why"`
