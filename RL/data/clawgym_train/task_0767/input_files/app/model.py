import json
import csv
from typing import List, Dict, Optional

REQUIRED_FIELDS = ["id", "title", "status", "priority"]
ALLOWED_STATUSES = {"todo", "in_progress", "done"}


def load_tasks(json_path: str) -> List[Dict]:
    """
    Load tasks from a JSON file at json_path.
    Must validate that each task has required fields with correct types:
      - id: int
      - title: non-empty str
      - status: one of {todo, in_progress, done}
      - priority: int in [1, 5]
    Return a list of normalized dicts containing only the required fields.
    """
    raise NotImplementedError("load_tasks is not implemented yet")


def filter_tasks(tasks: List[Dict], status: Optional[str] = None, min_priority: Optional[int] = None) -> List[Dict]:
    """
    Return tasks filtered by optional status and minimum priority (inclusive).
    Does not mutate the input.
    """
    raise NotImplementedError("filter_tasks is not implemented yet")


def stats(tasks: List[Dict]) -> Dict:
    """
    Compute summary statistics:
      - total: int
      - by_status: dict with keys todo, in_progress, done
      - avg_priority: float (average over all tasks)
    """
    raise NotImplementedError("stats is not implemented yet")


def export_csv(tasks: List[Dict], csv_path: str) -> int:
    """
    Write tasks to csv_path with header id,title,status,priority (in that order).
    Return the number of data rows written.
    """
    raise NotImplementedError("export_csv is not implemented yet")
