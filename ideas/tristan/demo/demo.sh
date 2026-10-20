#!/usr/bin/env bash
# End-to-end demo: a real Claude Code session -> recorder -> store -> ask the Slack bot.
# Needs the server running (slack run, PORT=8092) and WHOKNOWS_DB pointing at the same database.
set -euo pipefail

ROOT=${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
URL=${URL:-http://127.0.0.1:8092}
PERSON=${PERSON:-tristan}
DB=${WHOKNOWS_DB:-$ROOT/data/demo.db}
WORK=${WORK:-$HOME/WhoKnows/demo-whoknows-payroll}
PY=$ROOT/.venv/bin/python
QUESTION=${QUESTION:-nightly payroll export retries}

mkdir -p "$WORK"
cd "$ROOT"
TOKEN=$("$PY" -m whoknows.store --db "$DB" "$PERSON")

echo "1/3  A real Claude Code session in $WORK, where $PERSON corrects Claude and says why"
cd "$WORK"
SESSION=$(claude -p "Draft a short plan for the nightly payroll export to the bank over SFTP, including how many times to retry a failed upload." \
  --model haiku --tools "" --output-format json | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["session_id"])')
claude -p --resume "$SESSION" --model haiku --tools "" --output-format json \
  "No, retry 3 times, not 5, because the bank closes the SFTP window at 18:00 and a late file is rejected anyway." > /dev/null
echo "     session $SESSION"

echo "2/3  Recorder: label the human turns, keep the verbatim why, push the rows to the store"
cd "$ROOT"
"$PY" -m recorder.run --person "$PERSON" --match "$(basename "$WORK")" --out "$ROOT/data/demo-rows.json" --push "$URL" --token "$TOKEN"

echo "3/3  The store's answer to: $QUESTION"
curl -s -G "$URL/api/who-knows" --data-urlencode "q=$QUESTION" -H "Authorization: Bearer $TOKEN" | "$PY" -c '
import json, sys
r = json.load(sys.stdin)
print("     status:", r["status"])
for p in r["people"][:2]:
    print("    ", p["person"] + ":", repr(p["evidence"][0]["why"] if p["evidence"] else None))'
echo
echo "Now in Slack (Bot-Testing): /whoknows $QUESTION   or DM the Who Knows (local) app."
