import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_lines(path: Path) -> Optional[List[str]]:
    text = read_text(path)
    if text is None:
        return None
    return text.splitlines()


def load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            return list(reader)
    except Exception:
        return None


def get_roster_names(roster_path: Path) -> Optional[Set[str]]:
    rows = load_csv_dicts(roster_path)
    if rows is None:
        return None
    names = set()
    try:
        for row in rows:
            if "Name" not in row:
                return None
            names.add((row.get("Name") or "").strip())
    except Exception:
        return None
    return names


def parse_transcript_actions(transcript_path: Path) -> Optional[List[Dict[str, str]]]:
    lines = read_lines(transcript_path)
    if lines is None:
        return None
    actions: List[Dict[str, str]] = []
    pattern = re.compile(
        r'^ACTION:\s*(.*?)\s+—\s+Owner:\s*(.*?)\s+—\s+Due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s+—\s+Tags:\s*(.*)\s*$'
    )
    for line in lines:
        m = pattern.match(line)
        if m:
            task = m.group(1).strip()
            owner = m.group(2).strip()
            due = m.group(3).strip()
            tags = m.group(4).strip()
            actions.append({"task": task, "owner": owner, "due_date": due, "tags": tags})
    return actions


def parse_transcript_decisions(transcript_path: Path) -> Optional[List[str]]:
    lines = read_lines(transcript_path)
    if lines is None:
        return None
    decisions: List[str] = []
    pat = re.compile(r'^DECISION:\s*(.*)\s*$')
    for line in lines:
        m = pat.match(line)
        if m:
            decisions.append(m.group(1).strip())
    return decisions


def extract_meeting_date_from_filename(path: Path) -> Optional[str]:
    m = re.search(r'meeting_(\d{4}-\d{2}-\d{2})_transcript\.txt$', path.name)
    return m.group(1) if m else None


def compute_expected_actions(workspace: Path) -> Optional[List[Dict[str, str]]]:
    input_dir = workspace / "input"
    if not input_dir.exists():
        return None
    transcript_paths = sorted(input_dir.glob("meeting_2026-04-*_transcript.txt"))
    if not transcript_paths:
        return None
    roster_names = get_roster_names(input_dir / "contact_roster.csv")
    if roster_names is None:
        return None
    all_actions: List[Dict[str, str]] = []
    for tpath in transcript_paths:
        meeting_date = extract_meeting_date_from_filename(tpath)
        if not meeting_date:
            continue
        acts = parse_transcript_actions(tpath)
        if acts is None:
            return None
        for a in acts:
            owner = a["owner"].strip()
            owner_in_roster = "true" if (owner != "TBD" and owner in roster_names) else "false"
            row = {
                "meeting_date": meeting_date,
                "task": a["task"],
                "owner": owner,
                "due_date": a["due_date"],
                "tags": a["tags"],
                "owner_in_roster": owner_in_roster,
            }
            all_actions.append(row)
    return all_actions


def load_action_items_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows: List[Dict[str, str]] = []
            for row in reader:
                clean = {}
                for k, v in row.items():
                    clean[k] = (v or "").strip()
                rows.append(clean)
            return rows
    except Exception:
        return None


def header_equals_exact(path: Path, expected_header: List[str]) -> bool:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return False
            return header == expected_header
    except Exception:
        return False


def list_scripts_extract_actions(scripts_dir: Path) -> List[Path]:
    if not scripts_dir.exists():
        return []
    return [p for p in scripts_dir.iterdir() if p.is_file() and p.name.startswith("extract_actions.")]


def extract_section_lines(lines: List[str], section_name: str) -> List[str]:
    name_lower = section_name.strip().lower()
    start_idx = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        s_norm = re.sub(r'^[#]+\s*', '', s).strip().lower()
        if s_norm == name_lower:
            start_idx = i
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        nxt = lines[j].lstrip()
        if nxt.startswith("#"):
            end_idx = j
            break
    return lines[start_idx + 1:end_idx]


def section_contains_all_substrings(section_lines: List[str], substrings: List[str]) -> bool:
    for ln in section_lines:
        if all(sub in ln for sub in substrings):
            return True
    return False


def parse_key_decisions_region(lines: List[str]) -> Tuple[int, int]:
    start = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.lower().startswith("## ") and stripped[3:].strip().lower() == "key decisions":
            start = i
            break
    if start == -1:
        return -1, -1
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j].strip()
        if ln.lower().startswith("## ") and j > start:
            end = j
            break
    return start, end


def parse_open_action_items_region(lines: List[str]) -> Tuple[int, int]:
    start = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.lower().startswith("## ") and stripped[3:].strip().lower() == "open action items":
            start = i
            break
    if start == -1:
        return -1, -1
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j].strip()
        if ln.lower().startswith("## ") and j > start:
            end = j
            break
    return start, end


def parse_open_action_item_lines(lines: List[str]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    pattern = re.compile(
        r'^\s*-?\s*(\d{4}-\d{2}-\d{2})\s+—\s+([^:]+):\s+(.+?)\s+\[tags:\s*([^\]]+)\]\s*$'
    )
    for ln in lines:
        m = pattern.match(ln)
        if m:
            items.append({
                "due_date": m.group(1).strip(),
                "owner": m.group(2).strip(),
                "task": m.group(3).strip(),
                "tags": m.group(4).strip(),
            })
    return items


def sort_actions_by_due(actions: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(actions, key=lambda x: x.get("due_date", ""))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_file_present": 0.0,
        "action_items_csv_exists_and_header": 0.0,
        "action_items_rows_match_expected": 0.0,
        "summary_2026_04_10_decisions_listed": 0.0,
        "summary_2026_04_10_decisions_stripped_prefix": 0.0,
        "summary_2026_04_10_actions_listed": 0.0,
        "summary_2026_04_17_decisions_listed": 0.0,
        "summary_2026_04_17_decisions_stripped_prefix": 0.0,
        "summary_2026_04_17_actions_listed": 0.0,
        "plan_updated_file_exists": 0.0,
        "plan_open_action_items_replaced_with_sorted_list": 0.0,
        "plan_key_decisions_april_section_appended": 0.0,
        "plan_key_decisions_prior_entries_preserved": 0.0,
    }

    # Check script presence
    scripts_dir = workspace / "scripts"
    scripts = list_scripts_extract_actions(scripts_dir)
    if len(scripts) > 0:
        scores["script_file_present"] = 1.0

    # Action items CSV checks
    action_csv_path = workspace / "workspace" / "action_items.csv"
    expected_header = ["meeting_date", "task", "owner", "due_date", "tags", "owner_in_roster"]
    if action_csv_path.exists() and header_equals_exact(action_csv_path, expected_header):
        scores["action_items_csv_exists_and_header"] = 1.0

    # Compute expected from inputs
    expected_actions = compute_expected_actions(workspace)

    # Load actual CSV rows
    actual_rows = None
    if action_csv_path.exists():
        actual_rows = load_action_items_csv(action_csv_path)

    if scores["action_items_csv_exists_and_header"] == 1.0 and expected_actions is not None and actual_rows is not None:
        def norm_row(r: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
            return (
                (r.get("meeting_date") or "").strip(),
                (r.get("task") or "").strip(),
                (r.get("owner") or "").strip(),
                (r.get("due_date") or "").strip(),
                (r.get("tags") or "").strip(),
                (r.get("owner_in_roster") or "").strip().lower(),
            )
        expected_set = {norm_row(r) for r in expected_actions}
        actual_set = {norm_row(r) for r in actual_rows}
        if expected_set == actual_set and len(actual_rows) == len(expected_actions):
            scores["action_items_rows_match_expected"] = 1.0

    # Summaries checks
    transcripts = sorted((workspace / "input").glob("meeting_2026-04-*_transcript.txt"))
    meeting_data: Dict[str, Dict[str, List]] = {}
    for tpath in transcripts:
        date = extract_meeting_date_from_filename(tpath)
        if not date:
            continue
        decisions = parse_transcript_decisions(tpath) or []
        actions = parse_transcript_actions(tpath) or []
        meeting_data[date] = {"decisions": decisions, "actions": actions}

    # 2026-04-10 summary
    summary_10_path = workspace / "notes" / "meeting_2026-04-10_summary.md"
    if summary_10_path.exists():
        s_lines = read_lines(summary_10_path) or []
        dec_section = extract_section_lines(s_lines, "Decisions")
        act_section = extract_section_lines(s_lines, "Action Items")
        expected_decisions_10 = meeting_data.get("2026-04-10", {}).get("decisions", [])
        if expected_decisions_10:
            if all(any(dec in ln for ln in dec_section) for dec in expected_decisions_10):
                scores["summary_2026_04_10_decisions_listed"] = 1.0
            # Ensure "DECISION:" prefix stripped in Decisions section
            if not any("DECISION:" in (ln or "") for ln in dec_section):
                scores["summary_2026_04_10_decisions_stripped_prefix"] = 1.0
        expected_actions_10 = meeting_data.get("2026-04-10", {}).get("actions", [])
        if expected_actions_10:
            found_all = True
            for a in expected_actions_10:
                needed = [a["task"], a["owner"], a["due_date"], a["tags"]]
                if not section_contains_all_substrings(act_section, needed):
                    found_all = False
                    break
            if found_all:
                scores["summary_2026_04_10_actions_listed"] = 1.0

    # 2026-04-17 summary
    summary_17_path = workspace / "notes" / "meeting_2026-04-17_summary.md"
    if summary_17_path.exists():
        s_lines = read_lines(summary_17_path) or []
        dec_section = extract_section_lines(s_lines, "Decisions")
        act_section = extract_section_lines(s_lines, "Action Items")
        expected_decisions_17 = meeting_data.get("2026-04-17", {}).get("decisions", [])
        if expected_decisions_17:
            if all(any(dec in ln for ln in dec_section) for dec in expected_decisions_17):
                scores["summary_2026_04_17_decisions_listed"] = 1.0
            if not any("DECISION:" in (ln or "") for ln in dec_section):
                scores["summary_2026_04_17_decisions_stripped_prefix"] = 1.0
        expected_actions_17 = meeting_data.get("2026-04-17", {}).get("actions", [])
        if expected_actions_17:
            found_all = True
            for a in expected_actions_17:
                needed = [a["task"], a["owner"], a["due_date"], a["tags"]]
                if not section_contains_all_substrings(act_section, needed):
                    found_all = False
                    break
            if found_all:
                scores["summary_2026_04_17_actions_listed"] = 1.0

    # Updated plan checks
    updated_plan_path = workspace / "output" / "advocacy_plan_updated.md"
    if updated_plan_path.exists():
        scores["plan_updated_file_exists"] = 1.0
        plan_lines = read_lines(updated_plan_path) or []

        # Open Action Items replaced with sorted list based on CSV
        o_start, o_end = parse_open_action_items_region(plan_lines)
        if o_start != -1:
            region_lines = plan_lines[o_start + 1:o_end]
            parsed_items = parse_open_action_item_lines(region_lines)

            # Build expected from action_items.csv if available; fall back to transcripts if needed
            expected_items: List[Dict[str, str]] = []
            if actual_rows:
                for r in actual_rows:
                    expected_items.append({
                        "due_date": (r.get("due_date") or "").strip(),
                        "owner": (r.get("owner") or "").strip(),
                        "task": (r.get("task") or "").strip(),
                        "tags": (r.get("tags") or "").strip(),
                    })
            else:
                # Fallback to transcripts-derived
                for data in meeting_data.values():
                    for a in data.get("actions", []):
                        expected_items.append({
                            "due_date": a["due_date"],
                            "owner": a["owner"],
                            "task": a["task"],
                            "tags": a["tags"],
                        })
            expected_sorted = sort_actions_by_due(expected_items)
            # Check that region lines parsed match expected and are sorted by due date
            if expected_sorted and parsed_items and len(expected_sorted) == len(parsed_items):
                # Order check
                due_dates_in_region = [x["due_date"] for x in parsed_items]
                if due_dates_in_region == sorted(due_dates_in_region):
                    to_tuple = lambda x: (x.get("due_date", ""), x.get("owner", ""), x.get("task", ""), x.get("tags", ""))
                    if [to_tuple(x) for x in parsed_items] == [to_tuple(x) for x in expected_sorted]:
                        scores["plan_open_action_items_replaced_with_sorted_list"] = 1.0

        # Key Decisions checks
        kd_start, kd_end = parse_key_decisions_region(plan_lines)
        if kd_start != -1:
            kd_region = plan_lines[kd_start + 1:kd_end]
            # Prior entries preserved: look for known March decision from input plan
            if any("2026-03-12:" in (ln or "") for ln in kd_region):
                scores["plan_key_decisions_prior_entries_preserved"] = 1.0

            # Find "April 2026" subsection presence and content
            april_idx = -1
            for i, ln in enumerate(kd_region):
                if "April 2026:" in ln:
                    april_idx = i
                    break
            if april_idx != -1:
                subregion = kd_region[april_idx + 1:]
                expected_apr_decisions: List[str] = []
                for mdate in ("2026-04-10", "2026-04-17"):
                    for dec in meeting_data.get(mdate, {}).get("decisions", []):
                        expected_apr_decisions.append(f"{mdate}: {dec}")
                if expected_apr_decisions:
                    found_all = True
                    for d in expected_apr_decisions:
                        if not any(d in ln for ln in subregion):
                            found_all = False
                            break
                    if found_all:
                        scores["plan_key_decisions_april_section_appended"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()