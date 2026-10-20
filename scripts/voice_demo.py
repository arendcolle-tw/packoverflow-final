"""Score app/voice/demo-rows.json with Albéric's ranking and write app/voice/demo-answer.json.

The voice demo topic (nightly payroll export retries) is seeded, labeled demo data. Its answer comes from the
same code as the live graph (ideas/alberic), never from a second copy in app/. Rerun after editing the rows:
  python3 scripts/voice_demo.py
"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ideas" / "alberic"))

from knowledge_graph.graph import KnowledgeGraph  # noqa: E402

QUESTION = "nightly payroll export retries to the bank over SFTP"
AT = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)

rows_path = ROOT / "app" / "voice" / "demo-rows.json"
with tempfile.TemporaryDirectory() as tmp:
    graph = KnowledgeGraph(Path(tmp) / "demo.sqlite", seed_paths=[rows_path])
    answer = {"who_knows": graph.who_knows(QUESTION, at=AT), "risks": graph.risks(at=AT), "rows": graph.rows()}
(ROOT / "app" / "voice" / "demo-answer.json").write_text(json.dumps(answer, indent=1) + "\n")
w = answer["who_knows"]
print(w["status"], w["owner"], [(p["person"], p["proficiency"]) for p in w["people"]], answer["risks"][0]["status"])
