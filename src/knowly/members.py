"""One fact store member token per person, created on first use with the admin token."""

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from knowly.client import StoreClient, StoreError


class Members:
    def __init__(self, base_url: str, admin_token: str, tokens_path: Path):
        self.store = StoreClient(base_url)
        self.admin_token = admin_token
        self.tokens_path = Path(tokens_path)

    def token_for(self, person: str, stale: str | None = None) -> str:
        """The stored token, or a new member. `stale` is a token the store refused, so it is replaced."""
        self.tokens_path.parent.mkdir(parents=True, exist_ok=True)
        # flock serialises threads and processes, so concurrent first calls create one member.
        with open(self.tokens_path.with_name(self.tokens_path.name + ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            tokens = json.loads(self.tokens_path.read_text()) if self.tokens_path.exists() else {}
            if tokens.get(person) and tokens[person] != stale:
                return tokens[person]
            if not self.admin_token:
                raise RuntimeError(f"KNOWLY_ADMIN_TOKEN is not set, so Knowly cannot make {person} a member")
            tokens[person] = self.store.create_member(person, self.admin_token)
            fd, tmp = tempfile.mkstemp(dir=self.tokens_path.parent, prefix=".tokens-")  # mkstemp creates mode 600
            with os.fdopen(fd, "w") as f:
                json.dump(tokens, f, indent=2)
            os.replace(tmp, self.tokens_path)
            return tokens[person]

    def store_fact(self, person: str, question: str, fact: str, topic: str, question_id: str) -> dict:
        row = {
            "id": f"question:{question_id}:{person}", "person": person, "topic": topic, "source": "gap_form",
            "source_id": f"question-{question_id}", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "human_role": "answered_question", "actor": "human", "why": fact[:200], "task": question[:80],
        }
        token = self.token_for(person)
        try:
            self.store.post_facts([row], token)
        except StoreError as error:
            if error.status != 401:
                raise
            self.store.post_facts([row], self.token_for(person, stale=token))
        return row
