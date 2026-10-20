#!/usr/bin/env bash
# Sets up the Knowly demo on this Mac: one Knowly server on port 8091 (fact store, Slack bot in #ask_knowly, MCP)
# started by `slack run`, members tristan and alberic, and tristan's payroll session pushed as his fact.
# Usage: demo/full_demo.sh [--reset | --stop]
#   --reset  stops the server, wipes data/ and the demo Claude session, then sets everything up again
#   --stop   stops the server
set -euo pipefail

ROOT=${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
BIN=$ROOT/.venv/bin
PY=$BIN/python
DATA=$ROOT/data
PORT=8091
URL=http://127.0.0.1:$PORT
MEMBER_TOKENS=$DATA/member_tokens.json
ALBERIC_TOKEN_FILE=$DATA/alberic-mcp-token
ROWS=$DATA/demo-rows.json
SLACK_LOG=$DATA/slack-run.log
WORK=$HOME/Knowly/demo-payroll
ALBERIC_DIR=$HOME/Knowly/demo-alberic
TEAM=T0C9C4CTJEP
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

stop_server() {
  local pid
  for pid in $(pgrep -f "slack run --team $TEAM" || true); do
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
  done
  kill_port "$PORT"
}

if [ "$MODE" = --stop ]; then
  stop_server
  echo "stopped the Knowly server"
  exit 0
fi

[ -x "$BIN/knowly-token" ] || { echo "install Knowly first: uv pip install --python $PY -e '$ROOT[dev]' slack-cli-hooks" >&2; exit 1; }

if [ "$MODE" = --reset ]; then
  printf '== reset: data/ and the demo Claude session\n'
  stop_server
  rm -rf "$DATA"
  rm -rf "$HOME/.claude/projects/"*demo-payroll
fi

mkdir -p "$DATA"
if [ ! -s "$DATA/admin_token" ]; then
  (umask 077; "$PY" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$DATA/admin_token")
fi
ADMIN=$(cat "$DATA/admin_token")

printf '\n== 1/5  Knowly server on %s (slack run, team %s)\n' "$URL" "$TEAM"
stop_server
# ELEVENLABS_API_KEY would make the local store re-register the hosted voice webhook; KNOWLY_BUCKET would mirror to Cloud Storage.
(cd "$ROOT" && env -u ELEVENLABS_API_KEY -u KNOWLY_BUCKET \
  KNOWLY_DATA_DIR="$DATA" KNOWLY_URL="$URL" KNOWLY_ADMIN_TOKEN="$ADMIN" KNOWLY_CHANNEL=ask_knowly \
  SLACK_PEOPLE=tristan:U0C9D2HJUA1 KNOWLY_ALLOW_SELF=1 DEFAULT_EXPERT=tristan PORT="$PORT" \
  nohup slack run --team "$TEAM" --app local --manifest-source local --no-activity --hide-triggers --skip-update \
  > "$SLACK_LOG" 2>&1 < /dev/null &)
wait_for "$URL/healthz" 120 "$SLACK_LOG"
echo "   running, log $SLACK_LOG"

printf '\n== 2/5  members tristan and alberic -> %s\n' "$MEMBER_TOKENS"
"$PY" - "$URL/store" "$ADMIN" "$MEMBER_TOKENS" <<'PY'
import sys
from pathlib import Path

from knowly.client import StoreError
from knowly.members import Members

members = Members(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
for person in ("tristan", "alberic"):
    token = members.token_for(person)
    try:
        members.store.post_facts([], token)
    except StoreError as error:
        if error.status != 401:
            raise
        members.token_for(person, stale=token)
    print(f"   {person}: member")
PY
TOKEN=$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["tristan"])' "$MEMBER_TOKENS")

printf '\n== 3/5  MCP token for alberic -> %s\n' "$ALBERIC_TOKEN_FILE"
if [ ! -s "$ALBERIC_TOKEN_FILE" ]; then
  ALBERIC=$("$BIN/knowly-token" --db "$DATA/tokens.db" alberic)
  (umask 077; printf '%s\n' "$ALBERIC" > "$ALBERIC_TOKEN_FILE")
fi
ALBERIC=$(cat "$ALBERIC_TOKEN_FILE")
echo "   $ALBERIC"

printf '\n== 4/5  demo step 1: tristan'\''s Claude session -> knowly-record -> fact store\n'
FACTS=$(curl -fsS "$URL/store/rows" | "$PY" -c 'import json, sys; print(sum(r["person"] == "tristan" for r in json.load(sys.stdin)))')
if [ "$FACTS" -gt 0 ]; then
  echo "   tristan already has $FACTS facts"
elif [ -s "$ROWS" ]; then
  echo "   pushing $ROWS again"
  curl -fsS -X POST "$URL/store/facts" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" --data-binary @"$ROWS"
  echo
else
  rm -rf "$HOME/.claude/projects/"*demo-payroll
  mkdir -p "$WORK"
  SESSION=$(cd "$WORK" && env -u KNOWLY_CAPTURE_CHILD claude -p \
    "Draft a short plan for the nightly payroll export to the bank over SFTP, with 5 retries for a failed upload." \
    --model haiku --tools "" --output-format json | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["session_id"])')
  (cd "$WORK" && env -u KNOWLY_CAPTURE_CHILD claude -p \
    "No, retry 3 times, not 5, because the bank closes the SFTP window at 18:00 and a late file is rejected anyway." \
    --resume "$SESSION" --model haiku --tools "" --output-format json) > /dev/null
  echo "   session $SESSION in $WORK"
  "$BIN/knowly-record" --mode summary --person tristan --match demo-payroll \
    --push "$URL" --token="$TOKEN" --out "$ROWS"
fi
"$PY" - "$URL/store" "$QUESTION" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

store, question = sys.argv[1], sys.argv[2]
for query in ("nightly payroll SFTP export retries", question):
    with urllib.request.urlopen(f"{store}/who_knows?" + urllib.parse.urlencode({"q": query}), timeout=30) as response:
        found = json.load(response)
    print(f"   store for {query!r}: {found['status']}")
    for person in found["people"][:2]:
        top = person["evidence"][0] if person["evidence"] else {}
        why = (top.get("whys") or [{}])[0].get("why")
        print(f"     {person['person']} (similarity {top.get('similarity', 0):.2f}): {why}")
    if not found["people"]:
        print("     nothing related found, so step 2 will not show the payroll fact")
PY

mkdir -p "$ALBERIC_DIR"
cat <<EOF

== 5/5  run the demo in #ask_knowly (Knowly (local) must be in the channel: /invite @knowly)

Step 1  Tristan's payroll session is a fact in the store (shown above).
Step 2  Alberic posts in #ask_knowly:
          $QUESTION
        Expected in the thread: Knowly says there is no answer yet and why Tristan is the one to ask, then tags Tristan.
Step 3  Tristan replies in that thread:
          $ANSWER
        Expected: a check mark on the reply and a thank-you to Tristan saying it is saved to Knowly.
Step 4  Alberic posts the same question again in #ask_knowly, as a new message:
          $QUESTION
        Expected: 16:00, with Tristan's reason, and Tristan and today's date under it.

The same answers over MCP, as alberic in Claude Code (second terminal):
  cd $ALBERIC_DIR
  claude mcp remove -s local knowly 2>/dev/null; claude mcp add --transport http -s local knowly $URL/mcp --header "Authorization: Bearer $ALBERIC"
  claude
  > Ask knowly: $QUESTION

Or over HTTP:
  curl -s -X POST $URL/api/ask -H "Authorization: Bearer $ALBERIC" -H "Content-Type: application/json" -d '{"question": "$QUESTION"}'

Log: $SLACK_LOG     Reset: demo/full_demo.sh --reset     Stop: demo/full_demo.sh --stop
EOF
