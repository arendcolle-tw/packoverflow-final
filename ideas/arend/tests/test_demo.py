import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from followwork import capture, demo  # noqa: E402
from followwork.extract import extract  # noqa: E402


class DemoReplayTest(unittest.TestCase):
    """The fixture task, through the same rules as live capture."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (capture.LOCAL, capture.EVENTS, capture.STATS)
        capture.LOCAL = self.tmp
        capture.EVENTS = os.path.join(self.tmp, "events.jsonl")
        capture.STATS = os.path.join(self.tmp, "stats.json")
        demo.reset()

    def tearDown(self):
        capture.LOCAL, capture.EVENTS, capture.STATS = self.saved

    def test_nothing_private_is_stored(self):
        raw = open(capture.EVENTS).read()
        for bad in ["1Password", "Private Browsing", "KBC", "@", "BE71 0961"]:
            self.assertNotIn(bad, raw, bad)

    def test_learns_the_indexation_procedure(self):
        procs = extract(capture.load_events())
        self.assertEqual(len(procs), 2)
        steps = procs[0]["steps"]
        self.assertIn("Filter on joint committee PC 200", steps)
        self.assertTrue(any(s.startswith("Paste") for s in steps))
        self.assertEqual(procs[0]["topic"], "indexation, PC 200")
        self.assertNotIn("person", json.dumps(procs))


if __name__ == "__main__":
    unittest.main()
