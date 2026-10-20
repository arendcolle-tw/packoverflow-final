#!/usr/bin/env python3
"""End-to-end check of Knowly's learning loop against a running server.

python tests/e2e/check_loop.py --url http://127.0.0.1:8091 --admin-token="$KNOWLY_ADMIN_TOKEN" [--asker-token=<mcp/api token for alberic>]

Use the --flag=value form: tokens may start with "-".
"""
import argparse
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

QUESTION = "What time does the nightly payroll export start?"
failures = []


def call(base, path, token=None, body=None, timeout=300):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code} on {path}: {error.read().decode(errors='replace')[:300]}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"{path} unreachable: {error.reason}") from None


def check(step, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {step}")
    if detail:
        print("      " + str(detail).replace("\n", "\n      "))
    if not ok:
        failures.append(step)
    return ok


def text_of(answer):
    return answer.get("text") or answer.get("answer") or ""


def pinged_of(answer):
    target = answer.get("pinged") or answer.get("ask_person") or ""
    return (target.get("person") or target.get("name") or "") if isinstance(target, dict) else str(target)


def fact(fact_id, source, source_id, role, why, task):
    return {"id": fact_id, "person": "tristan", "topic": "payroll-sftp-export", "source": source, "source_id": source_id,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "human_role": role, "actor": "human", "why": why, "task": task}


def run(args):
    base, run_id = args.url.rstrip("/"), secrets.token_hex(4)
    print(f"run {run_id} against {base}")

    health = call(base, "/healthz", timeout=10)
    check("1 GET /healthz", bool(health and health.get("ok", True)), health)

    tokens = {}
    for person in ("tristan", "alberic"):
        member = call(base, "/store/members", args.admin_token, {"person": person})
        tokens[person] = (member or {}).get("token") or ""
        if not check(f"2 POST /store/members {person}", bool(tokens[person]), f"person={member.get('person')}"):
            return

    decision = fact(f"e2e:payroll:{run_id}", "claude_session", f"e2e-{run_id}", "decided",
                    'Set retries to 3 instead of 5 "because the bank closes the SFTP window at 18:00 '
                    'and a late file is rejected anyway".',
                    "Plan the nightly payroll SFTP export to the bank")
    added = call(base, "/store/facts", tokens["tristan"], [decision])
    check("3 POST /store/facts decision", added.get("added") == 1, added)

    if args.asker_token:
        first = call(base, "/api/ask", args.asker_token, {"question": f"{QUESTION} ({run_id})"})
        check("4 ask before the answer: known false, pings tristan",
              first.get("known") is False and "tristan" in pinged_of(first).lower(),
              f"known={first.get('known')} pinged={pinged_of(first)!r}\n{text_of(first)}")
    else:
        print("SKIP  4 ask before the answer (no --asker-token)")

    reply = fact(f"thread:e2e-{run_id}:tristan", "gap_form", f"thread-e2e-{run_id}", "answered_question",
                 "16:00, so three retries still finish before the bank closes the SFTP window at 18:00.", QUESTION)
    added = call(base, "/store/facts", tokens["tristan"], [reply])
    check("5 POST /store/facts thread reply", added.get("added") == 1, added)

    if args.asker_token:
        second = call(base, "/api/ask", args.asker_token, {"question": QUESTION})
        check("6 ask after the answer: known true, mentions 16:00",
              second.get("known") is True and "16:00" in text_of(second),
              f"known={second.get('known')}\n{text_of(second)}")
    else:
        print("SKIP  6 ask after the answer (no --asker-token)")

    found = call(base, "/store/who_knows?" + urllib.parse.urlencode({"q": "nightly payroll export start"}), tokens["tristan"])
    names = {p.get("person") for p in found.get("people", []) if isinstance(p, dict)} | {found.get("owner")}
    check("7 GET /store/who_knows lists tristan", "tristan" in names, f"people={sorted(n for n in names if n)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8091")
    parser.add_argument("--admin-token", required=True)
    parser.add_argument("--asker-token", help="Knowly API or MCP token for alberic, enables steps 4 and 6")
    args = parser.parse_args()
    try:
        run(args)
    except (RuntimeError, AttributeError, ValueError) as error:
        check("request", False, error)
    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'ALL PASSED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
