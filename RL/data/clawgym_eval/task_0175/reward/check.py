import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_lineup_yaml(path: Path) -> Optional[List[Dict[str, object]]]:
    """
    Minimal YAML parser tailored to the provided lineup.yaml structure:
    episodes:
      - episode_id: E101
        date: 2026-05-03
        venue: Some Venue
        comedians:
          - Name1
          - Name2
    Returns list of episode dicts with keys: episode_id, date, venue, comedians(list).
    """
    text = read_text(path)
    if text is None:
        return None

    lines = text.splitlines()
    episodes: List[Dict[str, object]] = []
    in_episodes = False
    current: Optional[Dict[str, object]] = None
    collecting_list: Optional[str] = None

    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue

        # Detect episodes section
        if not in_episodes:
            if line.strip() == "episodes:":
                in_episodes = True
            continue

        # Now we are inside the episodes section
        indent = len(line) - len(line.lstrip(" "))
        s = line.strip()

        # If collecting a list (e.g., comedians)
        if collecting_list == "comedians" and s.startswith("- "):
            if current is not None:
                name = s[2:].strip()
                current.setdefault("comedians", [])
                if isinstance(current["comedians"], list):
                    current["comedians"].append(name)
            continue

        # New episode item (bullet at low indentation)
        if s.startswith("- ") and indent <= 2:
            collecting_list = None
            current = {}
            episodes.append(current)
            remainder = s[2:].strip()
            if remainder:
                if ":" in remainder:
                    k, v = remainder.split(":", 1)
                    current[k.strip()] = v.strip()
            continue

        # Key-value within current episode
        if current is not None and ":" in s:
            k, v = s.split(":", 1)
            key = k.strip()
            val = v.strip()
            if key == "comedians":
                collecting_list = "comedians"
                current.setdefault("comedians", [])
            else:
                collecting_list = None
                current[key] = val
            continue

        # If we reach here, ignore unrecognized lines

    # Validate structure
    cleaned: List[Dict[str, object]] = []
    for ep in episodes:
        if "episode_id" in ep and "date" in ep and "venue" in ep and "comedians" in ep:
            if not isinstance(ep["comedians"], list):
                return None
            cleaned.append(
                {
                    "episode_id": str(ep["episode_id"]),
                    "date": str(ep["date"]),
                    "venue": str(ep["venue"]),
                    "comedians": [str(x) for x in ep["comedians"]],
                }
            )
        else:
            # Missing required keys
            return None
    return cleaned


def load_availability_csv(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    """
    Returns mapping: availability[date][name] = status ('available'/'unavailable' lower-cased).
    """
    try:
        availability: Dict[str, Dict[str, str]] = {}
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"name", "date", "status"}
            if reader.fieldnames is None or not required.issubset({fn.strip() for fn in reader.fieldnames}):
                return None
            for row in reader:
                name = (row.get("name") or "").strip()
                date = (row.get("date") or "").strip()
                status = (row.get("status") or "").strip().lower()
                if not name or not date or not status:
                    return None
                availability.setdefault(date, {})[name] = status
        return availability
    except Exception:
        return None


def unique_in_order(names: List[str]) -> List[str]:
    seen = set()
    result = []
    for n in names:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def compute_expected_schedule(
    episodes: List[Dict[str, object]], availability: Dict[str, Dict[str, str]]
) -> List[Dict[str, object]]:
    """
    Compute the expected schedule per rules:
    - Primary: first up to 3 available comedians in lineup order.
    - Backups: remaining available comedians beyond the first 3 in order.
    - Dropped: comedians marked unavailable for that episode date.
    - If no row for name/date in CSV, treat as available.
    - Exclude duplicates, preserve order.
    """
    schedule: List[Dict[str, object]] = []
    for ep in episodes:
        ep_id = str(ep.get("episode_id", ""))
        date = str(ep.get("date", ""))
        venue = str(ep.get("venue", ""))
        lineup = [str(x) for x in (ep.get("comedians") or [])]

        available_list: List[str] = []
        dropped_list: List[str] = []

        date_avail = availability.get(date, {})
        for name in lineup:
            status = date_avail.get(name)
            # Treat missing as available
            if status is None or status.lower() == "available":
                available_list.append(name)
            elif status.lower() == "unavailable":
                dropped_list.append(name)
            else:
                # Any unknown status -> treat as available conservatively
                available_list.append(name)

        available_list = unique_in_order(available_list)
        dropped_list = unique_in_order(dropped_list)

        primary = available_list[:3]
        backups = available_list[3:]

        entry = {
            "episode_id": ep_id,
            "date": date,
            "venue": venue,
            "primary": primary,
            "backups": backups,
            "dropped_unavailable": dropped_list,
        }
        schedule.append(entry)
    return schedule


def validate_schedule_json_structure(obj: object) -> Tuple[bool, Optional[List[Dict[str, object]]]]:
    """
    Validate structure of schedule JSON: list of objects, exact keys, field types.
    Returns (ok, casted_list_or_none)
    """
    if not isinstance(obj, list):
        return False, None
    casted: List[Dict[str, object]] = []
    for item in obj:
        if not isinstance(item, dict):
            return False, None
        keys = set(item.keys())
        required_keys = {"episode_id", "date", "venue", "primary", "backups", "dropped_unavailable"}
        if keys != required_keys:
            return False, None
        if not isinstance(item["episode_id"], str):
            return False, None
        if not isinstance(item["date"], str):
            return False, None
        if not isinstance(item["venue"], str):
            return False, None
        for k in ["primary", "backups", "dropped_unavailable"]:
            if not isinstance(item[k], list):
                return False, None
            if any(not isinstance(x, str) for x in item[k]):
                return False, None
            # Ensure no duplicates within each list
            if len(item[k]) != len(set(item[k])):
                return False, None
        # Enforce primary length <= 3
        if len(item["primary"]) > 3:
            return False, None
        casted.append(item)
    return True, casted


def notes_find_action_items_section(lines: List[str]) -> Optional[int]:
    """
    Returns index of the line that is the 'Action items' heading, accepting optional leading '#' markdown.
    """
    for i, raw in enumerate(lines):
        s = raw.strip()
        # Allow headings like "Action items" or "# Action items" or "## Action items"
        s_no_hash = s.lstrip("#").strip()
        if s_no_hash == "Action items":
            return i
    return None


def check_notes_episode_sections(notes_text: str, schedule: List[Dict[str, object]]) -> bool:
    """
    Checks that notes contain, for each episode in order, a top-level bullet containing episode_id and date,
    followed by exactly three sub-bullets with:
    - Primary: <json array>
    - Backups: <json array>
    - Dropped (unavailable): <json array>
    """
    lines = notes_text.splitlines()
    pos = 0
    for ep in schedule:
        ep_id = ep["episode_id"]
        ep_date = ep["date"]
        # Find top-level bullet line containing both episode_id and date
        found_idx = None
        for i in range(pos, len(lines)):
            line = lines[i]
            if line.startswith("- ") and (ep_id in line) and (ep_date in line):
                found_idx = i
                break
        if found_idx is None:
            return False
        # Collect subsequent sub-bullets (two-space indent)
        sublines: List[str] = []
        j = found_idx + 1
        while j < len(lines):
            if lines[j].startswith("  - "):
                sublines.append(lines[j])
                j += 1
            else:
                break
        pos = j
        # Expect exactly three sub-bullets with required labels
        expected_labels = {
            "Primary": json.dumps(ep["primary"], ensure_ascii=False),
            "Backups": json.dumps(ep["backups"], ensure_ascii=False),
            "Dropped (unavailable)": json.dumps(ep["dropped_unavailable"], ensure_ascii=False),
        }
        found_map: Dict[str, str] = {}
        for sl in sublines:
            m = re.match(r"^\s{2}-\s*(Primary|Backups|Dropped\s+\(unavailable\))\s*:\s*(.*)\s*$", sl)
            if not m:
                continue
            label = m.group(1)
            value = m.group(2)
            found_map[label] = value
        if set(found_map.keys()) != set(expected_labels.keys()):
            return False
        for lbl, expected_json in expected_labels.items():
            if found_map.get(lbl) != expected_json:
                return False
    return True


def check_notes_action_items(notes_text: str, schedule: List[Dict[str, object]]) -> bool:
    """
    Checks the 'Action items' section contains bullets for each dropped and backup entry:
    - Find replacement for {name} on {date} at {venue} (episode {episode_id})
    - Confirm backup availability for {name} on {date} (episode {episode_id})
    No extras, order can be arbitrary.
    """
    lines = notes_text.splitlines()
    idx = notes_find_action_items_section(lines)
    if idx is None:
        return False
    # Collect top-level bullets after the header
    found_items: List[str] = []
    for i in range(idx + 1, len(lines)):
        line = lines[i]
        if line.startswith("- "):
            found_items.append(line[2:].strip())
        # Stop collecting if a new heading starts
        elif line.strip().startswith("#"):
            break
        else:
            continue
    found_set = set(found_items)

    expected_items: List[str] = []
    for ep in schedule:
        date = ep["date"]
        venue = ep["venue"]
        ep_id = ep["episode_id"]
        for name in ep["dropped_unavailable"]:
            expected_items.append(f"Find replacement for {name} on {date} at {venue} (episode {ep_id})")
        for name in ep["backups"]:
            expected_items.append(f"Confirm backup availability for {name} on {date} (episode {ep_id})")
    expected_set = set(expected_items)

    return (found_set == expected_set) and (len(found_items) == len(expected_items))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    lineup_path = workspace / "input" / "config" / "lineup.yaml"
    availability_path = workspace / "input" / "data" / "availability.csv"
    router_path = workspace / "input" / "scripts" / "router.py"
    output_json_path = workspace / "output" / "episode_schedule.json"
    notes_path = workspace / "docs" / "booking_sync_notes.md"

    scores = {
        "router_mentions_comedians_field": 0.0,
        "router_reads_availability_csv": 0.0,
        "router_writes_meeting_notes": 0.0,
        "schedule_json_exists_and_valid": 0.0,
        "schedule_matches_expected": 0.0,
        "notes_episode_sections_match_json": 0.0,
        "notes_action_items_complete": 0.0,
    }

    # Check router script content heuristics
    router_text = read_text(router_path)
    if router_text is not None:
        if "comedians" in router_text:
            scores["router_mentions_comedians_field"] = 1.0
        if ("availability.csv" in router_text) or ("input/data/availability.csv" in router_text):
            scores["router_reads_availability_csv"] = 1.0
        if ("docs/booking_sync_notes.md" in router_text) or ("booking_sync_notes.md" in router_text):
            scores["router_writes_meeting_notes"] = 1.0

    # Load and validate schedule JSON
    schedule_json = load_json(output_json_path)
    valid_structure = False
    schedule_list: Optional[List[Dict[str, object]]] = None
    if schedule_json is not None:
        valid_structure, schedule_list = validate_schedule_json_structure(schedule_json)
    if valid_structure and schedule_list is not None:
        scores["schedule_json_exists_and_valid"] = 1.0

    # Compute expected schedule from inputs and compare to JSON
    episodes = parse_lineup_yaml(lineup_path)
    availability = load_availability_csv(availability_path)
    if episodes is not None and availability is not None and schedule_list is not None:
        expected = compute_expected_schedule(episodes, availability)
        # Exact match comparison (order and content)
        if expected == schedule_list:
            scores["schedule_matches_expected"] = 1.0

    # Notes checks based on JSON schedule
    notes_text = read_text(notes_path)
    if notes_text is not None and schedule_list is not None:
        if check_notes_episode_sections(notes_text, schedule_list):
            scores["notes_episode_sections_match_json"] = 1.0
        if check_notes_action_items(notes_text, schedule_list):
            scores["notes_action_items_complete"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()