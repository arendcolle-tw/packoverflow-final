import argparse
import os
import secrets
import sqlite3
import threading
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "tokens.db"


class Tokens:
    def __init__(self, path: Path = DEFAULT_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS members (token TEXT PRIMARY KEY, person TEXT NOT NULL)")

    def add(self, person: str) -> str:
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
        return found[0] if found else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an access token for one person, or revoke all of theirs.")
    parser.add_argument("person")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("KNOWLY_TOKENS_DB", DEFAULT_DB)),
                        help="default $KNOWLY_TOKENS_DB, else data/tokens.db")
    parser.add_argument("--revoke", action="store_true", help="delete every token of this person")
    args = parser.parse_args()
    person, tokens = " ".join(args.person.split()).lower(), Tokens(args.db)
    print(f"revoked {tokens.revoke(person)} tokens of {person}" if args.revoke else tokens.add(person))


if __name__ == "__main__":
    main()
