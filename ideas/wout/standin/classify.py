import json
import subprocess
import tempfile

TOPIC_HINTS = [
    "aikido-security-scan",
    "github-repo-setup",
    "slack-claude-pipeline",
    "claude-skills",
    "repo-cleanup",
    "idea-and-scope",
    "pitch-and-submission",
    "knowledge-clock",
]
ROLES = ["decided", "corrected", "explained_why", "accepted_as_is"]
ACTORS = ["human", "agent", "unknown"]

SCHEMA = {
    "type": "object",
    "properties": {
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
        }
    },
    "required": ["items"],
}

INSTRUCTIONS = """You label turns from Claude Code sessions of a hackathon team. For each turn you get the
person's message and the last thing Claude said before it. Return one item per turn, same key.

topic: the system or subject the turn is about, kebab-case. Reuse one of these when it fits:
{hints}. Invent a new short kebab-case topic only when none fits.

human_role, judged on what the HUMAN contributed, not on what Claude did:
- decided: the human makes a choice or sets direction with their own content.
- corrected: the human tells Claude it was wrong, or changes Claude's output.
- explained_why: the human gives a reason for something.
- accepted_as_is: the human only asks, approves, or delegates. The content will come from Claude.

why: a verbatim quote of the human's own reason, at most 200 characters, or null if they gave none.
Never paraphrase, never invent a reason.

actor: "agent" when the message is clearly pasted AI output or written by another agent,
"unknown" when you cannot tell, otherwise "human". "[pasted]" marks text the human pasted in.

Turns:
{turns}"""


def build_command(schema: dict) -> list[str]:
    return [
        "claude", "-p",
        "--model", "haiku",
        "--no-session-persistence",
        "--tools", "",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
    ]


def build_prompt(turns: list[dict]) -> str:
    rendered = "\n\n".join(
        f"key: {t['key']}\nclaude said before: {t.get('context') or '(nothing)'}\nperson wrote: {t['text'][:1500]}"
        for t in turns
    )
    return INSTRUCTIONS.format(hints=", ".join(TOPIC_HINTS), turns=rendered)


def parse_output(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    structured = payload.get("structured_output")
    if isinstance(structured, dict) and "items" in structured:
        return structured["items"]
    text = payload.get("result", "")
    return json.loads(text[text.index("["): text.rindex("]") + 1])


def classify(turns: list[dict], batch_size: int = 25) -> list[dict]:
    items = []
    # Runs outside the repo so the classifier never shows up as a session we ingest next time.
    with tempfile.TemporaryDirectory() as cwd:
        for start in range(0, len(turns), batch_size):
            batch = turns[start:start + batch_size]
            done = subprocess.run(
                build_command(SCHEMA), input=build_prompt(batch), capture_output=True, text=True,
                cwd=cwd, timeout=600, check=True,
            )
            items.extend(parse_output(done.stdout))
    return items
