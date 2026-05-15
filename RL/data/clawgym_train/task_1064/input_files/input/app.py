#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import List, Dict, Any


def default_data_path() -> str:
    """Return the default path to the tasks.json file (same directory as this script)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.json")


def load_tasks(file_path: str) -> List[Dict[str, Any]]:
    """
    Load tasks from a JSON file.
    Returns an empty list if the file does not exist or is empty.
    Expects a JSON array of task objects with at least id, title, priority.
    """
    if not os.path.exists(file_path):
        print(f"No tasks file found at {file_path}. Starting with an empty task list.")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            if not isinstance(data, list):
                print("Invalid tasks file format: expected a JSON array.", file=sys.stderr)
                sys.exit(1)
            return data
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON from {file_path}: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Failed to read tasks from {file_path}: {e}", file=sys.stderr)
        sys.exit(1)


def print_task(task: Dict[str, Any]) -> None:
    """Print a single task in a user-friendly format."""
    tid = task.get("id", "?")
    title = task.get("title", "(no title)")
    priority = task.get("priority", "unspecified")
    print(f"[{tid}] ({priority}) {title}")


def list_tasks(tasks: List[Dict[str, Any]]) -> int:
    """Print all tasks. Returns the number of tasks printed."""
    if not tasks:
        print("No tasks to show.")
        return 0
    for task in sorted(tasks, key=lambda t: t.get("id", 0)):
        print_task(task)
    return len(tasks)


def filter_tasks(tasks: List[Dict[str, Any]], priority: str) -> int:
    """
    Print tasks filtered by priority. Returns the number of tasks printed.
    Priority comparison is case-insensitive.
    """
    if not priority:
        print("Priority not specified for filter.", file=sys.stderr)
        return 1
    p = priority.lower()
    filtered = [t for t in tasks if str(t.get("priority", "")).lower() == p]
    if not filtered:
        print(f"No tasks match priority '{priority}'.")
        return 0
    for task in sorted(filtered, key=lambda t: t.get("id", 0)):
        print_task(task)
    return len(filtered)


def build_parser() -> argparse.ArgumentParser:
    """Create and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        description="Tiny CLI To-Do Manager: list and filter tasks from a JSON file."
    )
    parser.add_argument(
        "--file",
        dest="file",
        default=default_data_path(),
        help="Path to tasks JSON file (default: tasks.json next to the script)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list command
    subparsers.add_parser("list", help="List all tasks")

    # filter command
    fp = subparsers.add_parser("filter", help="Filter tasks by priority")
    fp.add_argument(
        "--priority",
        "-p",
        required=True,
        choices=["low", "medium", "high"],
        help="Priority to filter by",
    )

    return parser


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    tasks = load_tasks(args.file)

    if args.command == "list":
        list_tasks(tasks)
        return 0
    elif args.command == "filter":
        filter_tasks(tasks, args.priority)
        return 0

    print("Unknown command.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())