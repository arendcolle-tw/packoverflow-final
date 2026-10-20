"""Create the ElevenLabs agent once: python -m knowledge_graph.setup_agent

Needs ELEVENLABS_API_KEY. Prints the agent id (the service defaults to the one already made, voice.AGENT_ID).
The post-call webhook is not made here: the service registers it itself (voice.ensure_webhook), so its secret
never leaves the service's own database.
"""

import argparse
import os

import httpx

from knowledge_graph.voice import API

PROMPT = """You are a friendly colleague calling {{person}} for one minute to record why they did a piece of work.

Work: {{subject}}
A draft of the reason, written by Claude, which is only a guess: {{draft}}
A question that checks the weakest part of the draft: {{check_question}}

Do this, one step at a time, waiting for the answer after each question:
1. Say it takes one minute (the greeting already did this; do not repeat it).
2. Read the work and the draft, and say it is Claude's guess.
3. Ask: "Is that right, or how would you put it?"
4. Ask the check question.
5. Read the final version back using {{person}}'s own words, and ask for a yes. When they say yes, thank them and end the call.

Rules: never invent reasons, facts or numbers yourself. If {{person}} does not know, say that is fine and end the call.
Keep every turn short. Never mention this reference: {{gap_id}}."""

FIRST = "Hi {{person}}, it's the PackOverflow knowledge assistant. This takes one minute: I'd like to check why you did something."
PLACEHOLDERS = {"person": "Wout", "subject": "Retry the payroll export 3 times", "check_question": "Is that still true?",
                "draft": "We retry 3 times because the bank closes the SFTP window at 18:00.", "gap_id": "g0"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="knowledge_graph.setup_agent")
    parser.add_argument("--voice-id", default=None, help="ElevenLabs voice id (default: the platform default)")
    args = parser.parse_args()
    headers = {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}

    tts = {"voice_id": args.voice_id} if args.voice_id else {}
    agent = httpx.post(f"{API}/v1/convai/agents/create", headers=headers, timeout=30, json={
        "name": "PackOverflow backtracking",
        "conversation_config": {
            "agent": {"first_message": FIRST, "language": "en",
                      "prompt": {"prompt": PROMPT, "llm": "claude-sonnet-5-5", "temperature": 0},
                      "dynamic_variables": {"dynamic_variable_placeholders": PLACEHOLDERS}},
            **({"tts": tts} if tts else {}),
        },
    })
    agent.raise_for_status()
    print(f"ELEVENLABS_AGENT_ID={agent.json()['agent_id']}")


if __name__ == "__main__":
    main()
