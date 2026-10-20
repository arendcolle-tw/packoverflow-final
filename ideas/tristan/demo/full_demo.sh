#!/usr/bin/env bash
# Sets up the whole Knowly demo on this Mac: a local copy of Alberic's knowledge graph, graph members,
# tristan's payroll session pushed as a fact, and the Slack bot with MCP on port 8091.
# Usage: demo/full_demo.sh [--reset | --stop]
#   --reset  wipes the local graph, open questions and the demo session first, then sets everything up again
#   --stop   stops the bot and the local graph
set -euo pipefail

ROOT=${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
ALB=${ALB:-$(cd "$ROOT/../alberic" && pwd)}
BIN=$ROOT/.venv/bin
PY=$BIN/python
KG_PORT=8770
KG=http://127.0.0.1:$KG_PORT
GRAPH_DIR=$ROOT/data/demo-graph
TOKENS=$ROOT/data/graph_tokens.json
DB=${KNOWLY_TOKENS_DB:-$ROOT/data/tokens.db}
LIES_TOKEN_FILE=$ROOT/data/demo-lies-mcp-token
ROWS=$ROOT/data/demo-rows.json
WORK=$HOME/Knowly/demo-knowly-payroll
LIES_DIR=$HOME/Knowly/demo-lies
TEAM=T0C9C4CTJEP
BOT_PORT=8091
BOT=http://127.0.0.1:$BOT_PORT
SLACK_LOG=$ROOT/data/slack-run.log
QUESTION="What time does the nightly payroll export start?"
ANSWER="It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff"

MODE=${1:-}
case "$MODE" in
  ""|--reset|--stop) ;;
  *) echo "usage: $0 [--reset | --stop]" >&2; exit 2 ;;
esac
cd "$ROOT"

wait_for() {  # url, seconds, log file
  for _ in $(seq "$2"); do
    curl -fsS -o /dev/null "$1" 2>/dev/null && return 0
    sleep 1
  done
  echo "no answer from $1 after $2 s, see $3" >&2
  tail -n 20 "$3" >&2 || true
  exit 1
}

kill_port() {
  local pids
  pids=$(lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null || true)
  [ -n "$pids" ] || return 0
  echo "$pids" | xargs kill 2>/dev/null || true
  for _ in $(seq 20); do
    lsof -ti "tcp:$1" -sTCP:LISTEN >/dev/null 2>&1 || return 0
    sleep 0.5
  done
  lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
}

stop_slack() {
  local pid
  for pid in $(pgrep -f "slack run --team $TEAM" || true); do
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
  done
  kill_port "$BOT_PORT"
}

if [ "$MODE" = --stop ]; then
  stop_slack
  kill_port "$KG_PORT"
  echo "stopped the bot and the local graph"
  exit 0
fi

[ -x "$BIN/knowly-token" ] || { echo "install Knowly first: uv pip install --python $PY -e $ROOT" >&2; exit 1; }

if [ "$MODE" = --reset ]; then
  printf '== reset: local graph, open questions, demo session\n'
  stop_slack
  kill_port "$KG_PORT"
  rm -rf "$GRAPH_DIR" "$ROWS" "$ROOT/data/questions.db" "$ROOT/data/questions.db-wal" "$ROOT/data/questions.db-shm"
  rm -rf "$HOME/.claude/projects/"*demo-knowly-payroll
fi

printf '\n== 1/6  local knowledge graph on %s\n' "$KG"
mkdir -p "$GRAPH_DIR"
printf '*\n' > "$GRAPH_DIR/.gitignore"
if [ ! -s "$GRAPH_DIR/admin_token" ]; then
  kill_port "$KG_PORT"
  (umask 077; "$PY" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$GRAPH_DIR/admin_token")
fi
ADMIN=$(cat "$GRAPH_DIR/admin_token")
if curl -fsS -o /dev/null "$KG/health" 2>/dev/null; then
  echo "   already running"
else
  # ELEVENLABS_API_KEY would make this copy re-register the hosted graph's voice webhook.
  (cd "$ALB" && env -u ELEVENLABS_API_KEY -u K_SERVICE KG_DATA_DIR="$GRAPH_DIR" KG_ADMIN_TOKEN="$ADMIN" \
    nohup uv run --python 3.13 --with-requirements requirements.txt \
    uvicorn knowledge_graph.server:app --host 127.0.0.1 --port "$KG_PORT" >> "$GRAPH_DIR/server.log" 2>&1 < /dev/null &)
  wait_for "$KG/health" 180 "$GRAPH_DIR/server.log"
  echo "   started, log $GRAPH_DIR/server.log"
fi

printf '\n== 2/6  graph members tristan and lies -> %s\n' "$TOKENS"
"$PY" - "$KG" "$ADMIN" "$TOKENS" <<'PY'
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

kg, admin, path = sys.argv[1], sys.argv[2], Path(sys.argv[3])


def post(route, token, body):
    request = urllib.request.Request(kg + route, json.dumps(body).encode(),
                                     {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


tokens = json.loads(path.read_text()) if path.exists() else {}
for person in ("tristan", "lies"):
    if tokens.get(person):
        try:
            post("/signals", tokens[person], [])
            print(f"   {person}: token still valid")
            continue
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
    try:
        tokens[person] = post("/members", admin, {"person": person})["token"]
    except urllib.error.HTTPError as error:
        sys.exit(f"the graph on {kg} rejected data/demo-graph/admin_token (HTTP {error.code}); run demo/full_demo.sh --reset")
    print(f"   {person}: new member")
path.write_text(json.dumps(tokens, indent=2) + "\n")
path.chmod(0o600)
PY
TRISTAN=$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["tristan"])' "$TOKENS")

printf '\n== 3/6  MCP token for lies (tokens %s)\n' "$DB"
LIES=$(cat "$LIES_TOKEN_FILE" 2>/dev/null || true)
OWNER=$("$PY" -c 'import sys; from pathlib import Path; from knowly.tokens import Tokens; print(Tokens(Path(sys.argv[1])).person_for(sys.argv[2]))' "$DB" "${LIES:-none}")
if [ "$OWNER" != lies ]; then
  LIES=$("$BIN/knowly-token" --db "$DB" lies)
  (umask 077; printf '%s\n' "$LIES" > "$LIES_TOKEN_FILE")
fi
echo "   $LIES"

printf '\n== 4/6  demo step 1: tristan'\''s Claude Code session -> recorder -> graph\n'
COUNT=$("$PY" -c 'import json, sys; print(len(json.load(open(sys.argv[1]))))' "$ROWS" 2>/dev/null || echo 0)
if [ "$COUNT" -gt 0 ]; then
  echo "   reusing $COUNT rows from $ROWS"
  curl -fsS -X POST "$KG/signals" -H "Authorization: Bearer $TRISTAN" -H "Content-Type: application/json" --data-binary @"$ROWS"
  echo
else
  rm -rf "$HOME/.claude/projects/"*demo-knowly-payroll
  mkdir -p "$WORK"
  SESSION=$(cd "$WORK" && env -u RECORDER_CHILD claude -p \
    "Draft a short plan for the nightly payroll export to the bank over SFTP, with 5 retries for a failed upload." \
    --model haiku --tools "" --output-format json | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["session_id"])')
  (cd "$WORK" && env -u RECORDER_CHILD claude -p \
    "No, retry 3 times, not 5, because the bank closes the SFTP window at 18:00 and a late file is rejected anyway." \
    --resume "$SESSION" --model haiku --tools "" --output-format json) > /dev/null
  echo "   session $SESSION in $WORK"
  "$BIN/knowly-record" --mode summary --person tristan --match demo-knowly-payroll \
    --push "$KG" --token="$TRISTAN" --out "$ROWS"
fi
"$PY" - "$KG" "$QUESTION" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

kg, question = sys.argv[1], sys.argv[2]
for query in ("nightly payroll SFTP export retries", question):
    with urllib.request.urlopen(f"{kg}/who_knows?" + urllib.parse.urlencode({"q": query}), timeout=30) as response:
        found = json.load(response)
    print(f"   graph for {query!r}: {found['status']}")
    for person in found["people"][:2]:
        top = person["evidence"][0] if person["evidence"] else {}
        why = (top.get("whys") or [{}])[0].get("why")
        print(f"     {person['person']} (similarity {top.get('similarity', 0):.2f}): {why}")
    if not found["people"]:
        print("     nothing related found, so step 2 will not show the payroll fact")
PY

printf '\n== 5/6  Slack bot + MCP on %s (slack run, team %s)\n' "$BOT" "$TEAM"
stop_slack
(cd "$ROOT" && KG_URL="$KG" SLACK_PEOPLE=tristan:U0C9D2HJUA1 DEFAULT_EXPERT=tristan PORT="$BOT_PORT" KNOWLY_TOKENS_DB="$DB" \
  nohup slack run --team "$TEAM" --app local --manifest-source local --no-activity --hide-triggers --skip-update \
  > "$SLACK_LOG" 2>&1 < /dev/null &)
wait_for "$BOT/healthz" 120 "$SLACK_LOG"
echo "   running, log $SLACK_LOG"

mkdir -p "$LIES_DIR"
cat <<EOF

== 6/6  run the demo

lies's Claude Code (second terminal), once:
  cd $LIES_DIR
  claude mcp remove -s local knowly 2>/dev/null; claude mcp add --transport http -s local knowly $BOT/mcp --header "Authorization: Bearer $LIES"
  claude

Step 1  tristan's payroll session is in the graph (shown above).
Step 2  lies asks in Claude Code:
          Ask knowly: $QUESTION
        Expected: not recorded yet, the related payroll fact, "I asked tristan". tristan gets a Slack DM with an Answer button.
Step 3  tristan clicks Answer in Slack and submits:
          $ANSWER
Step 4  lies asks the same question again:
          Ask knowly: $QUESTION
        Expected: tristan's answer, his name and today's date.

Without Slack or Claude Code, the same ask over HTTP:
  curl -s -X POST $BOT/api/ask -H "Authorization: Bearer $LIES" -H "Content-Type: application/json" -d '{"question": "$QUESTION"}'

Reset: demo/full_demo.sh --reset     Stop: demo/full_demo.sh --stop
EOF
