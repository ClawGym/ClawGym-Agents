import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple

def _to_bool(value: str) -> bool:
    """
    Interpret a string as a boolean for flags like 'yes', 'true', '1'.
    Case-insensitive; any other value returns False.
    """
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ("yes", "true", "1")

def load_tasks(csv_path: Path) -> List[Dict]:
    """
    Load tasks from a CSV with columns:
    id,title,effort_points,requires_external_contact,delete_data
    Converts effort_points to int and flags to bools.
    """
    tasks: List[Dict] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                tasks.append({
                    "id": row["id"],
                    "title": row["title"],
                    "effort_points": int(row["effort_points"]),
                    "requires_external_contact": _to_bool(row["requires_external_contact"]),
                    "delete_data": _to_bool(row["delete_data"])
                })
            except KeyError as e:
                raise ValueError(f"Missing expected column in tasks CSV: {e}") from e
            except ValueError as e:
                raise ValueError(f"Invalid numeric value in tasks CSV: {e}") from e
    return tasks

def load_team(json_path: Path) -> List[Dict]:
    """
    Load team members from JSON array with fields:
    name, role, daily_capacity (int).
    """
    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)
    members: List[Dict] = []
    for m in data:
        try:
            members.append({
                "name": m["name"],
                "role": m["role"],
                "daily_capacity": int(m["daily_capacity"])
            })
        except KeyError as e:
            raise ValueError(f"Missing expected key in team JSON: {e}") from e
        except ValueError as e:
            raise ValueError(f"Invalid daily_capacity in team JSON: {e}") from e
    return members

def total_effort(tasks: List[Dict]) -> int:
    """Sum the effort_points across tasks."""
    return sum(t.get("effort_points", 0) for t in tasks)

def group_sensitive(tasks: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Split tasks into those that require external contact and those that delete data.
    Returns (contact_tasks, deletion_tasks).
    """
    contact = [t for t in tasks if t.get("requires_external_contact")]
    deletion = [t for t in tasks if t.get("delete_data")]
    return contact, deletion

def estimate_days(total_points: int, team: List[Dict], hours_per_day_per_point: float = 1.0) -> float:
    """
    Very rough estimate: points per day equals sum of team daily_capacity.
    The hours_per_day_per_point parameter can be tuned if points map to hours.
    """
    capacity_points_per_day = sum(m.get("daily_capacity", 0) for m in team)
    if capacity_points_per_day <= 0:
        return float("inf")
    # Convert total points to "days" by dividing by team capacity.
    return total_points / capacity_points_per_day

def main(args: List[str]) -> None:
    """
    Usage:
      python script.py [path_to_tasks_csv] [path_to_team_json]

    If paths are omitted, defaults to 'tasks.csv' and 'team.json' in the current working directory.
    """
    tasks_path = Path(args[0]) if len(args) > 0 else Path("tasks.csv")
    team_path = Path(args[1]) if len(args) > 1 else Path("team.json")

    tasks = load_tasks(tasks_path)
    team = load_team(team_path)

    total_points = total_effort(tasks)
    contact_tasks, deletion_tasks = group_sensitive(tasks)
    days_estimate = estimate_days(total_points, team)

    print("=== Summary ===")
    print(f"Tasks: {len(tasks)}")
    print(f"Total effort points: {total_points}")
    print(f"Team members: {len(team)}")
    print(f"Estimated days (rough): {days_estimate:.2f}")
    print(f"Requires external contact: {len(contact_tasks)} task(s)")
    print(f"Requires data deletion: {len(deletion_tasks)} task(s)")

    # Print sample of sensitive tasks to guide confirmation workflows.
    if contact_tasks:
        print("\nExternal contact tasks:")
        for t in contact_tasks:
            print(f"- {t['id']} :: {t['title']}")
    if deletion_tasks:
        print("\nData deletion tasks:")
        for t in deletion_tasks:
            print(f"- {t['id']} :: {t['title']}")

if __name__ == "__main__":
    main(sys.argv[1:])