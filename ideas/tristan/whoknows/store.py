import argparse
import json
import secrets
import sqlite3
import threading
from pathlib import Path

from whoknows.rank import parse_at

FIELDS = ["id", "person", "topic", "source", "source_id", "at", "human_role", "why", "actor", "task", "app"]
ROLES = {"decided", "corrected", "explained_why", "accepted_as_is"}
ACTORS = {"human", "agent", "unknown"}
SOURCES = {"claude_session", "copilot_chat", "copilot_cli", "m365_copilot", "screenshot", "mcp_record"}
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "store.db"


def valid(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    required = ["id", "topic", "source", "source_id", "at", "human_role", "actor"]
    if not all(isinstance(row.get(f), str) and row[f] and len(row[f]) <= 300 for f in required):
        return False
    if row["human_role"] not in ROLES or row["actor"] not in ACTORS or row["source"] not in SOURCES:
        return False
    if not all(row.get(f) is None or (isinstance(row[f], str) and len(row[f]) <= 300) for f in ("why", "task", "app")):
        return False
    try:
        parse_at(row["at"])
    except ValueError:
        return False
    return True


class Store:
    def __init__(self, path: Path = DEFAULT_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute(f"CREATE TABLE IF NOT EXISTS signals ({', '.join(FIELDS)}, PRIMARY KEY (id))")
            have = {r["name"] for r in self._db.execute("PRAGMA table_info(signals)")}
            for field in FIELDS:
                if field not in have:
                    self._db.execute(f"ALTER TABLE signals ADD COLUMN {field}")
            self._db.execute("CREATE TABLE IF NOT EXISTS members (token TEXT PRIMARY KEY, person TEXT NOT NULL)")

    def upsert(self, rows: list[dict], person: str | None = None) -> tuple[int, int]:
        """Store valid rows. When `person` is given (from an access token) it overrides the rows' own person."""
        good = [{**r, "person": person or r.get("person")} for r in rows if valid(r)]
        good = [r for r in good if isinstance(r["person"], str) and r["person"]]
        with self._lock, self._db:
            # A row id stays with its first owner: a later write from anyone else changes nothing.
            stored = self._db.executemany(
                f"INSERT INTO signals ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))}) ON CONFLICT(id) DO UPDATE SET "
                f"{', '.join(f'{f} = excluded.{f}' for f in FIELDS[1:])} WHERE signals.person = excluded.person",
                [[r.get(f) for f in FIELDS] for r in good],
            ).rowcount
        return stored, len(rows) - stored

    def rows(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM signals")]

    def seed(self, paths: list[Path]) -> int:
        stored = 0
        for path in paths:
            try:
                rows = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(rows, list):
                stored += self.upsert(rows)[0]
        return stored

    def add_member(self, person: str) -> str:
        # The prefix lets the recorder's scrub recognise a pasted token.
        token = "wk_" + secrets.token_urlsafe(24)
        with self._lock, self._db:
            self._db.execute("INSERT INTO members VALUES (?, ?)", (token, person))
        return token

    def revoke(self, person: str) -> int:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM members WHERE person = ?", (person,)).rowcount

    def person_for(self, token: str) -> str | None:
        with self._lock:
            found = self._db.execute("SELECT person FROM members WHERE token = ?", (token,)).fetchone()
        return found["person"] if found else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an access token for one person, or revoke all of theirs.")
    parser.add_argument("person")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--revoke", action="store_true", help="delete every token of this person")
    args = parser.parse_args()
    person, store = " ".join(args.person.split()).lower(), Store(args.db)
    print(f"revoked {store.revoke(person)} tokens of {person}" if args.revoke else store.add_member(person))


if __name__ == "__main__":
    main()
