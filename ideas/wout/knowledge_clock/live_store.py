import json
import secrets
import threading
from pathlib import Path

from knowledge_clock.people import person_key
from knowledge_clock.store import load_signals, validate

# Module-level because the server builds a store per request.
_LOCK = threading.Lock()


class LiveStore:
    def __init__(self, seed_paths: list[Path], data_dir: Path):
        self.seed_paths = seed_paths
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
        with _LOCK, self.live_path.open("a") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")

    def create_member(self, name: str) -> tuple[str, str] | None:
        person = person_key(name)
        if person is None:
            return None
        token = secrets.token_urlsafe(16)
        with _LOCK:
            self._members = {**self._load_members(), token: person}
            self.members_path.write_text(json.dumps(self._members))
        return token, person

    def person_for(self, token: str) -> str | None:
        return self._members.get(token)
