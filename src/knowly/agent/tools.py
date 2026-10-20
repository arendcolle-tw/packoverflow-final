"""Stdio MCP server "knowly": read-only search over the fact store at KNOWLY_STORE_URL.

Run as `python -m knowly.agent.tools`; knowly.agent.answer starts it for `claude -p`.
"""

import json
import os

from mcp.server.mcpserver import MCPServer

from knowly.client import FACT_KEYS, StoreClient

store = StoreClient(os.environ.get("KNOWLY_STORE_URL", "http://127.0.0.1:8091/store"))
server = MCPServer(
    "knowly",
    instructions="Knowly's fact store: facts people recorded, each with the person, their reason (why), "
    "the task it came from, the source session or question, and its date.",
)


@server.tool()
def search_facts(query: str) -> str:
    """Search the knowledge base for facts related to a question or keywords. Returns facts with person, topic,
    task, why (their own words), human_role, source, source_id and at (ISO time), best matches first."""
    return json.dumps(store.search(query), ensure_ascii=False)


@server.tool()
def person_facts(person: str) -> str:
    """All facts one person recorded, newest first. person is the lowercase name used in the facts."""
    rows = [r for r in store.rows() if r.get("why") and r["person"].lower() == person.strip().lower()]
    rows.sort(key=lambda r: r["at"], reverse=True)
    return json.dumps([{k: r.get(k) for k in FACT_KEYS} for r in rows[:30]], ensure_ascii=False)


@server.tool()
def recent_facts(limit: int = 20) -> str:
    """The most recently recorded facts across everyone, newest first."""
    rows = sorted((r for r in store.rows() if r.get("why")), key=lambda r: r["at"], reverse=True)
    return json.dumps([{k: r.get(k) for k in FACT_KEYS} for r in rows[: max(1, min(limit, 50))]], ensure_ascii=False)


if __name__ == "__main__":
    server.run()
