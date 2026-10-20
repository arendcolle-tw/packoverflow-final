"""HTTP client for the Knowly fact store, which the server mounts at <url>/store."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROWS_TTL = 30
FACT_KEYS = ("person", "topic", "task", "why", "human_role", "source", "source_id", "at")
STOPWORDS = set(
    "the and for that this with are was were have has had from what when where which who whom why how does did "
    "can could should would will many much times time our your their its into about than then there".split()
)


class StoreError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class StoreClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._rows: list[dict] | None = None
        self._rows_at = 0.0

    def _call(self, path: str, body: object = None, token: str | None = None) -> object:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base_url + path, data, headers), timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode(errors="replace")
            raise StoreError(f"{path.split('?')[0]}: HTTP {error.code} {detail}", error.code) from error
        except (OSError, ValueError) as error:
            raise StoreError(f"{path.split('?')[0]}: {error}") from error

    def rows(self) -> list[dict]:
        if self._rows is None or time.monotonic() - self._rows_at > ROWS_TTL:
            self._rows = self._call("/rows")
            self._rows_at = time.monotonic()
        return self._rows

    def invalidate(self) -> None:
        self._rows = None

    def lookup(self, question: str) -> dict:
        found = self._call("/who_knows?" + urllib.parse.urlencode({"q": question[:300]}))
        # The store groups rows into one task per (person, source_id before the first ":"), titled by the earliest row's task.
        tasks: dict[tuple[str, str], str] = {}
        topics: dict[tuple[str, str], str] = {}
        for row in sorted(self.rows(), key=lambda r: r.get("at") or ""):
            key = (row["person"], row["source_id"].split(":")[0])
            if row.get("task"):
                tasks.setdefault(key, row["task"])
            topics.setdefault(key, row.get("topic"))
        people = []
        for p in found.get("people", []):
            evidence = [
                {
                    "source_id": e["source_id"],
                    "at": e["at"],
                    "similarity": e["similarity"],
                    "why": e["whys"][0]["why"] if e.get("whys") else None,
                    "role": e["whys"][0]["role"] if e.get("whys") else None,
                    "task": tasks.get((p["person"], e["source_id"])),
                    "topic": topics.get((p["person"], e["source_id"])),
                }
                for e in p.get("evidence", [])
            ]
            if evidence:
                people.append({"person": p["person"], "proficiency": p["proficiency"], "evidence": evidence})
        best = max((e["similarity"] for p in people for e in p["evidence"]), default=0.0)
        return {"question": question, "status": found.get("status"), "people": people, "best_similarity": best}

    def search(self, query: str, limit: int = 12) -> list[dict]:
        """Facts behind who_knows evidence in ranking order, then facts whose own words share the query's keywords."""
        rows = [r for r in self.rows() if r.get("why")]
        by_task: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            by_task.setdefault((row["person"], row["source_id"].split(":")[0]), []).append(row)

        hits: list[tuple[dict, str, float]] = []
        seen: set[str] = set()
        for person in self.lookup(query)["people"]:
            for evidence in person["evidence"]:
                for row in by_task.get((person["person"], evidence["source_id"]), []):
                    if row["id"] not in seen:
                        seen.add(row["id"])
                        hits.append((row, "who_knows", evidence["similarity"]))

        # who_knows matches a task's summary, not the reasons under it, so also match the reasons themselves.
        wanted = set(re.findall(r"\w{3,}", query.lower())) - STOPWORDS
        keyword = []
        for row in rows:
            words = set(re.findall(r"\w{3,}", f"{row['why']} {row.get('task') or ''} {row['topic']}".lower()))
            score = len(wanted & words) / len(wanted) if wanted else 0
            if row["id"] not in seen and score >= 0.3:
                keyword.append((row, "keyword", round(score, 2)))
        hits += sorted(keyword, key=lambda hit: -hit[2])
        return [{**{k: row.get(k) for k in FACT_KEYS}, "match": match, "score": score} for row, match, score in hits[:limit]]

    def post_facts(self, rows: list[dict], token: str) -> dict:
        result = self._call("/facts", rows, token)
        self.invalidate()
        if result.get("rejected"):
            raise StoreError(f"/facts rejected: {'; '.join(result['rejected'])}")
        return result

    def create_member(self, person: str, admin_token: str) -> str:
        return self._call("/members", {"person": person}, admin_token)["token"]
