#!/usr/bin/env bash
# Copies Albéric's packages from origin/main into vendor/ and points their imports at vendor.*
set -euo pipefail
cd "$(dirname "$0")"
git fetch -q origin
for pkg in proficiency knowledge_graph; do
  mkdir -p "$pkg"
  for f in $(git ls-tree --full-tree --name-only "origin/main:ideas/alberic/$pkg" | grep '\.py$'); do
    git show "origin/main:ideas/alberic/$pkg/$f" \
      | sed -E 's/^from (proficiency|knowledge_graph)/from vendor.\1/' > "$pkg/$f"
  done
done
echo "Vendored from ideas/alberic at $(git rev-parse --short origin/main). Re-run vendor/sync.sh, never edit by hand." > SOURCE.txt
