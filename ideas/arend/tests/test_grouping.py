import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from followwork.extract import group_steps  # noqa: E402


def ev(t, app, title, text=""):
    return {"ts": t, "app": app, "title": title, "text": text}


class GroupingTest(unittest.TestCase):
    def test_same_window_is_one_step(self):
        events = [
            ev(0, "Microsoft Excel", "export_oct.xlsx"),
            ev(2, "Microsoft Excel", "export_oct.xlsx"),
            ev(4, "Microsoft Excel", "export_oct.xlsx"),
            ev(6, "Google Chrome", "mysdworx - Salary data"),
            ev(8, "Google Chrome", "mysdworx - Salary data"),
        ]
        steps = group_steps(events)
        self.assertEqual(len(steps), 2)
        self.assertEqual([len(s) for s in steps], [3, 2])

    def test_title_change_in_same_app_is_new_step(self):
        events = [
            ev(0, "Google Chrome", "mysdworx - Clients"),
            ev(2, "Google Chrome", "mysdworx - Salary data"),
        ]
        self.assertEqual(len(group_steps(events)), 2)

    def test_brief_detour_is_dropped(self):
        # A 1-frame glance at another window between two frames of the same
        # window does not split the step.
        events = [
            ev(0, "Microsoft Excel", "export_oct.xlsx"),
            ev(2, "Slack", "general"),
            ev(4, "Microsoft Excel", "export_oct.xlsx"),
        ]
        steps = group_steps(events)
        self.assertEqual(len(steps), 1)
        self.assertEqual(len(steps[0]), 2)


if __name__ == "__main__":
    unittest.main()
