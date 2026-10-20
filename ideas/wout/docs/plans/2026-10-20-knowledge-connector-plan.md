# Knowledge Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A hosted MCP connector judges add to their own Claude with a personal URL, which records what they actually know vs what they just prompt and answers "who knows X?" across everyone connected.

**Architecture:** One FastAPI app: the existing clock routes, a `/join` page that mints personal tokens, and a FastMCP Streamable HTTP app mounted at `/u/{token}`. A gate resolves the token to a person and puts it in a contextvar the tools read. A live store merges the committed seed rows with JSONL-appended live rows and keeps the token table. Albéric's `who_knows` is vendored for ranking.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, `mcp>=1.30,<2` (FastMCP), pytest, httpx. Cloud Run via buildpacks.

**Spec:** `ideas/wout/docs/2026-10-20-knowledge-connector-design.md`

## Global Constraints

- All files under `ideas/wout/`. Merge straight to `main` when done.
- Run from `ideas/wout/` with `uv run --python 3.13 --with fastapi --with uvicorn --with httpx --with pytest --with 'mcp>=1.30,<2' ...`.
- Person always comes from the token in the URL, never from tool arguments.
- `kind` values: `decided | corrected | explained_why | prompted`. `prompted` maps to `human_role: accepted_as_is`, `why: None`.
- `why` at most 200 chars, required for the three reasoning kinds. `topic` normalized to lowercase kebab-case, at most 60 chars. 1 to 50 items per call.
- Live rows: `source: claude_session`, `actor: human`, `id: mcp-<uuid4 hex>`, `source_id: mcp-<person>-<topic>` (Albéric's ranking groups by `source_id.split(":")[0]`, so no colon and one task per person and topic).
- Person key: name stripped, lowercased, inner whitespace collapsed to one space, 1 to 40 chars.
- Token: `secrets.token_urlsafe(16)`.
- Headline copy in `what_i_know`: `Claude handled {prompted} of your requests on its own. You reasoned {reasoned} times.`
- No AI calls on the server. No secrets in git. No em-dashes. Comments only for non-obvious whys.

## Review Focus

1. A tool call through an unknown or missing token: HTTP 404 before the MCP layer, no row stored. Test in Task 3.
2. A judge sends a `why` with HTML or a 5,000-char string, or 500 items: rejected per item or per call with a reason, nothing crashes, the page still renders text only. Test in Task 1.
3. Two judges joining with "Jan " and "jan": both map to person `jan`. Test in Task 1.
4. Cloud Run host header: the MCP endpoint answers on a non-localhost Host. Test in Task 3.
5. The service restarts: seed rows are back, live rows from the JSONL file are back, tokens are back. Test in Task 2.

---

## File Structure

```
ideas/wout/
  knowledge_clock/people.py         # pure: person_key, normalize_topic, items_to_rows, person_view
  knowledge_clock/live_store.py     # LiveStore: seed + JSONL live rows + token table
  knowledge_clock/connector.py      # FastMCP server, tools, prompt, PersonGate, current_person
  knowledge_clock/server.py         # modify: store-backed config, /join, mount connector, lifespan
  knowledge_clock/static/join.html
  vendor/proficiency/               # copy of ideas/alberic/proficiency (score.py, __init__.py)
  requirements.txt  Procfile  .python-version
  tests/test_people.py  tests/test_live_store.py  tests/test_connector.py
```

### Task 1: People logic

**Files:** Create `knowledge_clock/people.py`, `tests/test_people.py`

**Interfaces:**
- Consumes: `validate` from `knowledge_clock/store.py`, `compute_topics` from `clock.py`.
- Produces:
  - `person_key(name: str) -> str | None` (None when empty or over 40 chars after normalizing)
  - `normalize_topic(topic: str) -> str` (lowercase, non-alphanumerics to `-`, collapsed, stripped, cut to 60)
  - `items_to_rows(items: list[dict], person: str, now: datetime) -> tuple[list[dict], list[str]]` rows and one error string per rejected item, `"item {i}: {reason}"`. More than 50 items: `([], ["at most 50 items per call"])`.
  - `person_view(signals: list[dict], person: str, now: datetime) -> dict`: `{person, headline, reasoned, prompted, knows: [{topic, latest_why, last_at, only_you}], only_prompts: [topic]}`. `knows` sorted with `only_you` first, then most recent. `only_you` is true when no other person has a clock-resetting row on that topic.

- [ ] **Step 1: Tests**

```python
NOW = parse_at("2026-10-20T12:00:00Z")

def test_person_key():
    assert person_key("  Jan ") == person_key("jan") == "jan"
    assert person_key("Anne  Marie") == "anne marie"
    assert person_key("   ") is None and person_key("x" * 41) is None

def test_normalize_topic():
    assert normalize_topic("Payroll: PC 200 Indexation!") == "payroll-pc-200-indexation"

def test_items_to_rows_maps_kinds():
    rows, errors = items_to_rows([
        {"topic": "Aikido scan", "kind": "decided", "why": "we only scan main"},
        {"topic": "aikido scan", "kind": "prompted", "why": "ignored"},
    ], "jan", NOW)
    assert errors == []
    assert [(r["human_role"], r["why"]) for r in rows] == [("decided", "we only scan main"), ("accepted_as_is", None)]
    assert rows[0]["source_id"] == "mcp-jan-aikido-scan" and rows[0]["at"] == "2026-10-20T12:00:00+00:00"
    assert rows[0]["id"].startswith("mcp-") and rows[0]["actor"] == "human"

def test_items_to_rows_rejects_bad_items():
    rows, errors = items_to_rows([
        {"topic": "x", "kind": "decided"},
        {"topic": "x", "kind": "vibes", "why": "a"},
        {"topic": "x", "kind": "decided", "why": "a" * 201},
        {"topic": "", "kind": "decided", "why": "a"},
        {"topic": "x", "kind": "decided", "why": "<b>ok</b>", "happened_at": "2026-09-30T10:00:00Z"},
    ], "jan", NOW)
    assert len(rows) == 1 and rows[0]["at"] == "2026-09-30T10:00:00+00:00" and len(errors) == 4
    assert items_to_rows([{"topic": "x", "kind": "prompted"}] * 51, "jan", NOW) == ([], ["at most 50 items per call"])

def test_person_view():
    sig = [row(person="jan", topic="a", why="mine"), row(person="jan", topic="b"), row(person="piet", topic="b"),
           row(person="jan", topic="c", human_role="accepted_as_is")]
    v = person_view(sig, "jan", NOW)
    assert (v["reasoned"], v["prompted"]) == (2, 1)
    assert v["headline"] == "Claude handled 1 of your requests on its own. You reasoned 2 times."
    assert [(k["topic"], k["only_you"]) for k in v["knows"]] == [("a", True), ("b", False)]
    assert v["knows"][0]["latest_why"] == "mine" and v["only_prompts"] == ["c"]
```

- [ ] **Step 2: Run, expect FAIL.** `uv run ... pytest tests/test_people.py -q`
- [ ] **Step 3: Implement.** `happened_at` parsed with `parse_at`; invalid -> error. Each built row must pass `validate`.
- [ ] **Step 4: Run all tests, expect PASS.**
- [ ] **Step 5: Commit** `"Add people logic for the connector"`

### Task 2: Live store

**Files:** Create `knowledge_clock/live_store.py`, `tests/test_live_store.py`

**Interfaces:**
- Consumes: `load_signals`, `validate` from `store.py`.
- Produces: `class LiveStore(seed_paths: list[Path], data_dir: Path)` with `rows() -> list[dict]` (seed + live, validated), `append(rows: list[dict]) -> None` (appends JSON lines to `data_dir/live_signals.jsonl`), `create_member(name: str) -> tuple[str, str] | None` returns `(token, person)` or None for an invalid name, `person_for(token: str) -> str | None`, `skipped -> int`. Tokens persist in `data_dir/members.json`. One `threading.Lock` guards writes. Corrupt JSONL lines are skipped.

- [ ] **Step 1: Tests**

```python
def test_rows_merge_seed_and_live_and_survive_restart(tmp_path):
    seed = write(tmp_path, "seed.json", [row(id="s:1")])
    store = LiveStore([seed], tmp_path / "live")
    store.append([row(id="mcp-1", source_id="mcp-jan-x", person="jan")])
    again = LiveStore([seed], tmp_path / "live")
    assert sorted(r["id"] for r in again.rows()) == ["mcp-1", "s:1"]

def test_members(tmp_path):
    store = LiveStore([], tmp_path / "live")
    token, person = store.create_member("  Jan ")
    assert person == "jan" and store.person_for(token) == "jan"
    assert LiveStore([], tmp_path / "live").person_for(token) == "jan"
    assert store.person_for("nope") is None and store.create_member("   ") is None

def test_corrupt_live_line_skipped(tmp_path):
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "live_signals.jsonl").write_text('{"bad"\n' + json.dumps(row(id="ok")) + "\n")
    assert [r["id"] for r in LiveStore([], tmp_path / "live").rows()] == ["ok"]
```

- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement.** **Step 4: Run all, PASS.** **Step 5: Commit** `"Add live store with member tokens"`

### Task 3: Connector and app wiring

**Files:** Create `knowledge_clock/connector.py`, `knowledge_clock/static/join.html`, `vendor/__init__.py`, `vendor/proficiency/` (copy of `git show origin/main:ideas/alberic/proficiency/{__init__,score}.py`), `tests/test_connector.py`. Modify `knowledge_clock/server.py`, `tests/test_server.py` (fixtures set `KC_DATA_DIR`).

**Interfaces:**
- Consumes: Tasks 1 and 2, `compute_topics`, `vendor.proficiency.score.who_knows`.
- Produces:
  - `current_person: ContextVar[str | None]`
  - `build_mcp(store: LiveStore, now: Callable[[], datetime]) -> FastMCP` named `packoverflow`, `stateless_http=True`, `json_response=True`, `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)`, with tools `record_signals(items: list[SignalItem])` (response includes `known_topics`), `what_i_know()`, `who_knows(question: str)`, `knowledge_risks()`, `list_topics()` (`[{topic, people}]` sorted by people desc, max 60) and prompt `map_my_knowledge`. `SignalItem` is a pydantic model `{topic: str, kind: Literal[...], why: str | None = None, happened_at: str | None = None}`. Tools return dicts. `who_knows` drops numeric `proficiency` and `contribution` from Albéric's output (no visible scores) and keeps person, evidence whys, status, owner.
  - `class PersonGate(app, store)`: ASGI wrapper for the mount; reads `scope["path_params"]["token"]`, 404 JSON when unknown, else sets `current_person` and calls the MCP app.
  - `server.py`: `store = LiveStore(seed paths from KC_SIGNALS, Path(KC_DATA_DIR or "data/live"))` created per app; existing `_config` reads `store.rows()`; `GET /join` serves `join.html`; `POST /api/join {name}` -> `{person, url, claude_code}` where `url = f"{base}/u/{token}/mcp"`, base from the request (`x-forwarded-proto` honored); 422 on invalid name. FastAPI `lifespan` runs `mcp.session_manager.run()`. Mount `/u/{token}` -> `PersonGate(mcp.streamable_http_app(), store)`.
  - `data/live/` is gitignored.
- Server `instructions` text: when the user decides, corrects Claude, or explains why, call `record_signals` with their own words (max 200 chars), one short topic each; never record secrets, credentials or personal data about others; use `what_i_know` to show "what you actually know vs what you just prompt".
- `map_my_knowledge` text: first call `list_topics` and reuse names; search the user's past chats (claude.ai) or read the session files under `~/.claude/projects` (Claude Code); for each topic, record decisions/corrections/explanations with the user's own words and `happened_at`, and topics where they only asked and accepted as `prompted`; batches of at most 50; if past chats are not visible, ask the user three short questions about recent work and record from the answers; then call `what_i_know` and present two lists: "what you actually know" and "what you just prompt".

- [ ] **Step 1: Tests** (in-process: set `current_person` and call `await mcp.call_tool(...)`; HTTP: `TestClient` against `server.app` inside `with TestClient(app) as c:` so the lifespan runs)

```python
async def test_record_then_what_i_know(store):
    mcp = build_mcp(store, lambda: NOW)
    current_person.set("jan")
    await mcp.call_tool("record_signals", {"items": [{"topic": "aikido", "kind": "decided", "why": "only main"}]})
    view = structured(await mcp.call_tool("what_i_know", {}))
    assert view["reasoned"] == 1 and view["knows"][0]["topic"] == "aikido"

async def test_who_knows_hides_scores(store_with_seed):
    out = structured(await build_mcp(store_with_seed, lambda: NOW).call_tool("who_knows", {"question": "aikido security scan"}))
    assert out["people"] and "proficiency" not in out["people"][0]

def test_join_and_gate(client):
    r = client.post("/api/join", json={"name": "Jan"}, headers={"host": "knowledge-mcp-xyz.a.run.app", "x-forwarded-proto": "https"})
    url = r.json()["url"]
    assert url.startswith("https://knowledge-mcp-xyz.a.run.app/u/") and url.endswith("/mcp")
    assert client.post("/api/join", json={"name": "  "}).status_code == 422
    assert client.post("/u/nope/mcp", json={}).status_code == 404

def test_mcp_initialize_over_http(client):
    token = client.post("/api/join", json={"name": "Jan"}).json()["url"].split("/u/")[1].split("/")[0]
    r = client.post(f"/u/{token}/mcp", headers={"host": "knowledge-mcp-xyz.a.run.app", "accept": "application/json, text/event-stream"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
    assert r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == "packoverflow"
```

`structured(result)` is a test helper that pulls the dict out of FastMCP's `call_tool` return value.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** connector, server changes, join page (name field, then shows the URL with a copy button, three claude.ai steps, the `claude mcp add --transport http packoverflow <url>` command; DOM via `textContent` only).
- [ ] **Step 4: Run all tests, PASS.** Then run locally and connect real Claude Code: `claude mcp add --transport http packoverflow-local http://localhost:8765/u/<token>/mcp`, call `what_i_know` once. Expected: tool answers with the headline.
- [ ] **Step 5: Commit** `"Add knowledge connector with personal URLs"`

### Task 4: Deploy

**Files:** Create `requirements.txt` (`fastapi`, `uvicorn`, `mcp>=1.30,<2`), `Procfile` (`web: KC_DATA_DIR=/tmp/kc uvicorn knowledge_clock.server:app --host 0.0.0.0 --port $PORT`), `.python-version` (`3.13`).

- [ ] **Step 1:** Merge to `main` (sync, check only `ideas/wout/` changed, push).
- [ ] **Step 2:** Trigger: `gh workflow run deploy.yml -f source=ideas/wout -f service=knowledge-mcp`, then `gh run watch`. Expected: run succeeds and prints the service URL.
- [ ] **Step 3:** Smoke test: `curl -s <url>/api/summary` returns counts; `POST <url>/api/join` returns a URL; `claude mcp add --transport http packoverflow <that url>` in Claude Code and `what_i_know` answers.
- [ ] **Step 4:** Post `CHANGE:` in #hackathon-finale with the `/join` URL and the one-line how-to, and ask the team to join and run "map my knowledge" before the pitch. Ask Arend for min/max instances 1 (or Firestore).

### Task 5 (stretch): Persistence beyond one instance

Only if Arend enables Firestore or there is time: `LiveStore` backend writing rows and members to Firestore when `KC_STORE=firestore`. Same tests run against a fake.
