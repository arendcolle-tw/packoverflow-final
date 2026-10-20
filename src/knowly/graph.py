"""Client for Alberic's knowledge graph (ideas/alberic/knowledge_graph)."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ROWS_TTL = 30


class GraphError(Exception):
    pass


def check_base_url(url: str) -> str:
    """Only talk to the graph over HTTPS, or plain HTTP on this machine, so a bad KG_URL cannot make urlopen read file:// or other schemes."""
    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if not parts.hostname or parts.username or not (parts.scheme == "https" or (parts.scheme == "http" and local)):
        raise ValueError(f"refusing graph URL {url!r}: use an https:// URL")
    return url.rstrip("/")


class GraphClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = check_base_url(base_url or os.environ.get("KG_URL") or "http://127.0.0.1:8770")
        self._rows: list[dict] | None = None
        self._rows_at = 0.0

    def _call(self, path: str, body: object = None, token: str | None = None) -> object:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        try:
            # base_url is validated by check_base_url; path is a fixed endpoint with url-encoded query values.
            with urllib.request.urlopen(urllib.request.Request(self.base_url + path, data, headers), timeout=15) as response:  # nosec B310
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode(errors="replace")
            raise GraphError(f"{path.split('?')[0]}: HTTP {error.code} {detail}") from error
        except (OSError, ValueError) as error:
            raise GraphError(f"{path.split('?')[0]}: {error}") from error

    def rows(self) -> list[dict]:
        if self._rows is None or time.monotonic() - self._rows_at > ROWS_TTL:
            self._rows = self._call("/rows")
            self._rows_at = time.monotonic()
        return self._rows

    def invalidate(self) -> None:
        self._rows = None

    def lookup(self, question: str) -> dict:
        found = self._call("/who_knows?" + urllib.parse.urlencode({"q": question[:300]}))
        # The graph groups rows into one task per (person, source_id before the first ":"), titled by the earliest row's task.
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

    def post_rows(self, rows: list[dict], token: str) -> dict:
        result = self._call("/signals", rows, token)
        self.invalidate()
        if result.get("rejected"):
            raise GraphError(f"/signals rejected: {'; '.join(result['rejected'])}")
        return result
