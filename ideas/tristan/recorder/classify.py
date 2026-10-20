import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

TOPICS = [
    "idea-and-scope",
    "pitch-and-submission",
    "aikido-security-scan",
    "github-repo-setup",
    "cloud-deploy",
    "slack-claude-pipeline",
    "claude-skills",
    "repo-cleanup",
    "hackathon-research",
    "sdworx-context",
    "session-recorder",
    "knowledge-clock",
    "knowledge-connector",
    "people-proficiency",
]
ROLES = ["decided", "corrected", "explained_why", "accepted_as_is"]
ACTORS = ["human", "agent", "unknown"]
BATCH_SIZE = 25

SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "topic": {"type": "string"},
                    "human_role": {"type": "string", "enum": ROLES},
                    "why": {"type": ["string", "null"]},
                    "actor": {"type": "string", "enum": ACTORS},
                },
                "required": ["key", "topic", "human_role", "why", "actor"],
            },
        },
    },
    "required": ["task", "items"],
}

INSTRUCTIONS = """You label turns from one {source} of a hackathon team. For each turn you get the
person's message and the last thing {assistant} said before it. Return one item per turn, same key.

task: one line of at most 80 characters naming what the person worked on in this session, in plain
words, for example "set up the Aikido security scan". No names, no secrets.

topic: the system or subject the turn is about, kebab-case. Reuse one of these when it fits:
{topics}. Invent a new short kebab-case topic only when none fits.

human_role, judged on what the HUMAN contributed, not on what {assistant} did:
- decided: the human makes a choice or sets direction with their own content.
- corrected: the human tells {assistant} it was wrong, or changes {assistant}'s output.
- explained_why: the human gives a reason for something.
- accepted_as_is: the human only asks, approves, or delegates. The content will come from {assistant}.

why: a verbatim quote of the human's own reason, at most 200 characters, or null if they gave none.
Copy the words exactly. Never paraphrase, never invent a reason.

actor: "agent" when the message is clearly pasted AI output or written by another agent,
"unknown" when you cannot tell, otherwise "human". "[pasted]" marks text the human pasted in.
Turns marked "subagent prompt" were written by {assistant} for a subagent: actor "agent", accepted_as_is.

Turns:
{turns}"""


def _command() -> list[str]:
    return [
        "claude", "-p",
        "--model", "haiku",
        "--no-session-persistence",
        "--tools", "",
        "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA),
    ]


def build_prompt(items: list[dict], source: str = "Claude Code session", assistant: str = "Claude") -> str:
    rendered = "\n\n".join(
        f"key: {i['key']}\n"
        + ("subagent prompt: " if i["is_agent"] else f"{assistant.lower()} said before: {i.get('context') or '(nothing)'}\nperson wrote: ")
        + i["text"][:1500]
        for i in items
    )
    return INSTRUCTIONS.format(topics=", ".join(TOPICS), turns=rendered, source=source, assistant=assistant)


def parse_output(stdout: str, key: str = "items") -> dict:
    payload = json.loads(stdout)
    structured = payload.get("structured_output")
    if isinstance(structured, dict) and key in structured:
        return structured
    text = payload.get("result", "")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def _run_batch(items: list[dict], cwd: str, source: str, assistant: str) -> dict:
    # RECORDER_CHILD stops the live hook from recording the classifier's own sessions.
    done = subprocess.run(
        _command(), input=build_prompt(items, source, assistant), capture_output=True, text=True,
        cwd=cwd, timeout=600, check=True, env={**os.environ, "RECORDER_CHILD": "1"},
    )
    return parse_output(done.stdout)


def classify(
    items: list[dict], workers: int = 4, source: str = "Claude Code session", assistant: str = "Claude",
) -> tuple[dict[str, dict], dict[str, str]]:
    """Label items in per-session batches. Returns (labels by item key, task by session)."""
    by_session: dict[str, list[dict]] = {}
    for item in items:
        by_session.setdefault(item["session"], []).append(item)
    batches = [
        (session, rows[start:start + BATCH_SIZE])
        for session, rows in by_session.items()
        for start in range(0, len(rows), BATCH_SIZE)
    ]

    labels, tasks = {}, {}
    # Runs outside the repo so the classifier never shows up as a session we ingest next time.
    with tempfile.TemporaryDirectory() as cwd, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_batch, batch, cwd, source, assistant): session for session, batch in batches}
        for n, future in enumerate(as_completed(futures), 1):
            session = futures[future]
            try:
                result = future.result()
            except (subprocess.SubprocessError, ValueError, KeyError) as error:
                print(f"[{n}/{len(batches)}] session {session[:8]} failed: {error}", file=sys.stderr)
                continue
            tasks.setdefault(session, result.get("task", "").strip())
            labels.update({label["key"]: label for label in result["items"] if "key" in label})
            print(f"[{n}/{len(batches)}] session {session[:8]}: {len(result['items'])} labels", file=sys.stderr)
    return labels, tasks
