import json
import os
import secrets
import threading
from pathlib import Path

from knowledge_clock.people import person_key
from knowledge_clock.store import load_signals, validate

# Module-level because the server builds a store per request.
_LOCK = threading.Lock()


class LiveStore:
    def __init__(self, seed_paths: list[Path], data_dir: Path, mirror=None, person_aliases: dict[str, str] | None = None):
        self.seed_paths = seed_paths
        self.person_aliases = person_aliases or {}
        self.mirror = mirror
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.live_path = data_dir / "live_signals.jsonl"
        self.members_path = data_dir / "members.json"
        self.skipped = 0
        self._members = self._load_members()

    def _load_members(self) -> dict[str, str]:
        try:
            members = json.loads(self.members_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return members if isinstance(members, dict) else {}

    def rows(self) -> list[dict]:
        seed, skipped = load_signals(self.seed_paths)
        live = []
        if self.live_path.exists():
            for line in self.live_path.read_text().splitlines():
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    candidate = None
                if validate(candidate):
                    live.append(candidate)
                elif line.strip():
                    skipped += 1
        self.skipped = skipped
        return seed + live

    def append(self, rows: list[dict]) -> None:
        with _LOCK:
            with self.live_path.open("a") as out:
                for row in rows:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
            if self.mirror:
                self.mirror.upload(self.live_path)

    def create_member(self, name: str) -> tuple[str, str] | None:
        person = person_key(name)
        if person is None:
            return None
        person = self.person_aliases.get(person, person)
        token = secrets.token_urlsafe(16)
        with _LOCK:
            self._members = {**self._load_members(), token: person}
            # Atomic replace: readers outside the lock must never see an empty file.
            tmp = self.members_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._members))
            os.replace(tmp, self.members_path)
            if self.mirror:
                self.mirror.upload(self.members_path)
        return token, person

    def has_member(self, person: str) -> bool:
        return person in self._load_members().values()

    def person_for(self, token: str) -> str | None:
        person = self._members.get(token)
        return self.person_aliases.get(person, person) if person else None
