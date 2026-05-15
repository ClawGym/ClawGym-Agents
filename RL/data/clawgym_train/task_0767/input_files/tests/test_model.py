import os
import csv
import tempfile
import unittest
from app import model

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH = os.path.join(BASE_DIR, "data", "tasks.json")


class TestModel(unittest.TestCase):
    def test_load_tasks_valid(self):
        tasks = model.load_tasks(DATA_PATH)
        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 6)
        for t in tasks:
            # Only required fields should be present (normalize allowed)
            self.assertTrue(all(k in t for k in model.REQUIRED_FIELDS))
            self.assertIsInstance(t["id"], int)
            self.assertIsInstance(t["title"], str)
            self.assertTrue(t["title"].strip())
            self.assertIn(t["status"], model.ALLOWED_STATUSES)
            self.assertIsInstance(t["priority"], int)
            self.assertGreaterEqual(t["priority"], 1)
            self.assertLessEqual(t["priority"], 5)

    def test_filter_tasks_by_status(self):
        tasks = model.load_tasks(DATA_PATH)
        todos = model.filter_tasks(tasks, status="todo")
        self.assertEqual(len(todos), 2)
        self.assertTrue(all(t["status"] == "todo" for t in todos))

    def test_filter_tasks_by_priority(self):
        tasks = model.load_tasks(DATA_PATH)
        high = model.filter_tasks(tasks, min_priority=3)
        self.assertEqual(len(high), 4)
        self.assertTrue(all(t["priority"] >= 3 for t in high))

    def test_filter_tasks_combined(self):
        tasks = model.load_tasks(DATA_PATH)
        combined = model.filter_tasks(tasks, status="in_progress", min_priority=3)
        self.assertEqual(len(combined), 2)
        self.assertTrue(all((t["status"] == "in_progress" and t["priority"] >= 3) for t in combined))

    def test_stats(self):
        tasks = model.load_tasks(DATA_PATH)
        s = model.stats(tasks)
        self.assertEqual(s["total"], 6)
        self.assertEqual(s["by_status"].get("todo"), 2)
        self.assertEqual(s["by_status"].get("in_progress"), 2)
        self.assertEqual(s["by_status"].get("done"), 2)
        self.assertAlmostEqual(s["avg_priority"], 3.0)

    def test_export_csv(self):
        tasks = model.load_tasks(DATA_PATH)
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "out.csv")
            n = model.export_csv(tasks, out_path)
            self.assertEqual(n, 6)
            with open(out_path, newline="", encoding="utf-8") as f:
                r = csv.reader(f)
                header = next(r)
                self.assertEqual(header, ["id", "title", "status", "priority"])
                rows = list(r)
                self.assertEqual(len(rows), 6)


if __name__ == "__main__":
    unittest.main()
