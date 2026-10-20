#!/bin/bash
# Step 1, the OCR spike. Answers: is macOS Vision text good enough to name a
# step like "Filter on joint committee PC 200"?
#
# 1. Do a real spreadsheet-to-portal task and take ~10 window shots with
#    Cmd+Shift+4 then Space (one window each). Put them in one folder.
# 2. bash mac/ocr_spike.sh ~/Desktop/spike
#
# Prints the OCR text per image and which step keywords were found, and saves
# the text to local/spike/. It does not delete your screenshots: delete them
# yourself when you are done, they are raw images.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:?usage: bash mac/ocr_spike.sh <folder with screenshots>}"
[ -x local/bin/fow ] || bash mac/build.sh
mkdir -p local/spike
KEYWORDS='joint committee|paritair|PC ?[0-9]{3}|filter|total|sum|gross|bruto|indexation|indexering|mysdworx|save|opslaan'
n=0; hit=0
for img in "$DIR"/*.png "$DIR"/*.jpg; do
  [ -e "$img" ] || continue
  n=$((n+1))
  name=$(basename "$img")
  /usr/bin/time -p local/bin/fow ocr "$img" > "local/spike/$name.txt" 2> local/spike/time.txt
  secs=$(awk '/^real/ {print $2}' local/spike/time.txt)
  found=$(grep -Eoi "$KEYWORDS" "local/spike/$name.txt" | sort -fu | paste -sd, - || true)
  lines=$(wc -l < "local/spike/$name.txt" | tr -d ' ')
  [ -n "$found" ] && hit=$((hit+1))
  echo "=== $name  ($lines lines, ${secs}s)  keywords: ${found:-none}"
  head -20 "local/spike/$name.txt"
done
echo
echo "$hit of $n screenshots contain step keywords. Text saved in local/spike/."
echo "Now run the redaction on it:  python3 -c \"import sys,glob; sys.path.insert(0,'.'); from followwork.redact import redact; [print(redact(open(f).read())) for f in sorted(glob.glob('local/spike/*.txt'))]\" | less"
