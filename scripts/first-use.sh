#!/usr/bin/env bash
# Checks that this Mac can work in the hackathon repo. Safe to rerun.
cd "$(dirname "$0")/.." || exit 1

fail=0
ok()   { echo "PASS  $1"; }
warn() { echo "WARN  $1"; echo "      fix: $2"; }
bad()  { echo "FAIL  $1"; echo "      fix: $2"; fail=1; }

if command -v git >/dev/null; then ok "git installed"; else bad "git installed" "xcode-select --install"; fi

if command -v gh >/dev/null; then
  ok "gh installed"
  if gh auth status >/dev/null 2>&1; then
    ok "gh logged in as $(gh api user --jq .login)"
  else
    bad "gh logged in" "gh auth login --hostname github.com --git-protocol https --web"
  fi
else
  bad "gh installed" "brew install gh"
fi

if [ -n "$(git config user.name)" ] && [ -n "$(git config user.email)" ]; then
  ok "git name and email set"
else
  bad "git name and email set" "git config --global user.name 'Your Name' && git config --global user.email you@techwolf.ai"
fi

if git ls-remote origin HEAD >/dev/null 2>&1; then
  ok "can reach origin"
else
  bad "can reach origin" "gh auth setup-git, then rerun this script"
fi

if command -v gh >/dev/null && [ "$(gh repo view --json viewerPermission --jq .viewerPermission 2>/dev/null)" != "" ]; then
  perm=$(gh repo view --json viewerPermission --jq .viewerPermission)
  case "$perm" in
    WRITE|MAINTAIN|ADMIN) ok "push access to this repo ($perm)" ;;
    *) bad "push access to this repo (you have $perm)" "ask the repo owner to add your GitHub username as a collaborator" ;;
  esac
else
  bad "push access to this repo" "log in to gh first"
fi

if command -v gcloud >/dev/null && gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q .; then
  ok "gcloud logged in"
else
  warn "gcloud logged in (only needed to deploy by hand)" "brew install --cask google-cloud-sdk, then gcloud auth login"
fi

if [ "$fail" -eq 0 ]; then
  touch .first-use-ok
  echo "All required checks pass."
else
  rm -f .first-use-ok
  echo "Fix the FAIL lines and run this script again."
fi
exit "$fail"
