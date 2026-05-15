import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import Counter


# Helper functions

def read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None


def load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        actions = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                actions.append(obj)
        return actions
    except Exception:
        return None


def extract_actions_from_file(path: Path) -> Optional[List[dict]]:
    pat = re.compile(r"^Action:\s*(.+?)\s*-\s*(.+?)(?:;\s*due\s*(\d{4}-\d{2}-\d{2}))?\s*$")
    lines = read_text_lines(path)
    if lines is None:
        return None
    actions = []
    for i, raw in enumerate(lines, start=1):
        m = pat.match(raw.strip())
        if m:
            person = m.group(1).strip()
            task = m.group(2).strip()
            due = (m.group(3) or "").strip()
            actions.append({
                "source_file": str(path),
                "line_no": i,
                "person": person,
                "task": task,
                "due_date": due
            })
    return actions


def extract_expected_actions(workspace: Path) -> Optional[List[dict]]:
    files = [
        workspace / "input" / "notes" / "weekly_advising_2026-04-15.md",
        workspace / "input" / "notes" / "grad_seminar_2026-04-17.md",
    ]
    all_actions: List[dict] = []
    for p in files:
        acts = extract_actions_from_file(p)
        if acts is None:
            return None
        all_actions.extend(acts)
    return all_actions


def parse_csv_strict(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [row for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None


def load_roster(workspace: Path) -> Optional[Dict[str, str]]:
    roster_path = workspace / "input" / "roster" / "students.csv"
    parsed = parse_csv_strict(roster_path)
    if parsed is None:
        return None
    header, rows = parsed
    if "name" not in header or "email" not in header:
        return None
    mapping = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip()
        if name:
            mapping[name.lower()] = email
    return mapping


def sort_key_due_person(rec: dict):
    due = (rec.get("due_date") or "").strip()
    person = (rec.get("person") or "").strip()
    if due:
        return (0, due, person)
    else:
        return (1, "", person)


def compute_expected_join_rows(workspace: Path) -> Optional[List[Dict[str, str]]]:
    actions = extract_expected_actions(workspace)
    if actions is None:
        return None
    roster = load_roster(workspace)
    if roster is None:
        return None
    # Build joined records
    joined = []
    for rec in actions:
        person = rec["person"]
        email = roster.get(person.lower(), "")
        joined.append({
            "source_file": rec["source_file"],
            "line_no": str(rec["line_no"]),
            "person": person,
            "email": email,
            "task": rec["task"],
            "due_date": rec["due_date"],
        })
    # Sort by due_date ascending (empty last), then person ascending
    def k(r):
        due = (r["due_date"] or "").strip()
        person = (r["person"] or "").strip()
        if due:
            return (0, due, person)
        else:
            return (1, "", person)
    joined_sorted = sorted(joined, key=k)
    return joined_sorted


def get_attendance_info(workspace: Path) -> Optional[Dict[str, Dict[str, str]]]:
    info = {}
    files = {
        "2026-04-15": workspace / "input" / "notes" / "weekly_advising_2026-04-15.md",
        "2026-04-17": workspace / "input" / "notes" / "grad_seminar_2026-04-17.md",
    }
    for date, path in files.items():
        lines = read_text_lines(path)
        if lines is None:
            return None
        attendees_line = None
        for line in lines:
            if line.strip().startswith("Attendees:"):
                attendees_line = line.strip()
                break
        if not attendees_line:
            return None
        # Extract names substring exactly as appears after "Attendees: "
        if ":" in attendees_line:
            names = attendees_line.split(":", 1)[1].strip()
        else:
            names = attendees_line.replace("Attendees", "").strip()
        count = 0 if not names else len([n for n in [x.strip() for x in names.split(",")] if n])
        info[date] = {"names": names, "count": str(count)}
    return info


def extract_themes_and_advices(workspace: Path) -> Optional[Tuple[List[str], List[str]]]:
    paths = [
        workspace / "input" / "notes" / "weekly_advising_2026-04-15.md",
        workspace / "input" / "notes" / "grad_seminar_2026-04-17.md",
    ]
    themes_list: List[str] = []
    seen_themes = set()
    advices: List[str] = []
    for p in paths:
        lines = read_text_lines(p)
        if lines is None:
            return None
        for line in lines:
            ls = line.strip()
            if ls.startswith("Theme:"):
                theme = ls.split(":", 1)[1].strip()
                if theme not in seen_themes:
                    seen_themes.add(theme)
                    themes_list.append(theme)
            if ls.startswith("Advice:"):
                advice = ls.split(":", 1)[1].strip()
                advices.append(advice)
    return themes_list, advices


def find_heading_indices(lines: List[str], headings: List[str]) -> Dict[str, int]:
    idxs = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in headings and stripped not in idxs:
            idxs[stripped] = i
    return idxs


def get_section_lines(lines: List[str], start_heading: str, next_heading: str) -> List[str]:
    # Returns non-empty lines between start_heading and next_heading (exclusive)
    content: List[str] = []
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == start_heading:
            start_idx = i + 1
            break
    if start_idx is None:
        return content
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip() == next_heading:
            end_idx = j
            break
    for k in range(start_idx, end_idx):
        if lines[k].strip() != "":
            content.append(lines[k].rstrip("\n"))
    return content


def parse_bullet_items(lines: List[str]) -> List[str]:
    items = []
    for line in lines:
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            items.append(s[2:].strip())
    return items


def parse_markdown_table(lines: List[str]) -> Tuple[List[str], List[List[str]]]:
    # Expects lines for a table; returns (header_cells, rows_cells)
    # Handles typical pipe-separated markdown tables.
    filtered = [ln for ln in lines if ln.strip() != ""]
    if not filtered:
        return [], []
    # Identify header line
    header_line = None
    sep_index = None
    for i, ln in enumerate(filtered):
        if header_line is None:
            header_line = ln
            continue
        # Next line should be separator with dashes
        if set(ln.replace("|", "").replace(" ", "")) <= {"-", ":"} and "-" in ln:
            sep_index = i
            break
        else:
            # If no separator line, still try to parse treating the next lines as rows
            sep_index = 1
            break
    if header_line is None:
        return [], []
    header_cells = [c.strip() for c in header_line.strip().split("|")]
    header_cells = [c for c in header_cells if c != ""]
    rows_cells: List[List[str]] = []
    start_rows = sep_index + 1 if sep_index is not None else 1
    for ln in filtered[start_rows:]:
        cells = [c.strip() for c in ln.strip().split("|")]
        cells = [c for c in cells if c != ""]
        if cells:
            rows_cells.append(cells)
    return header_cells, rows_cells


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "actions_jsonl_present_valid": 0.0,
        "actions_jsonl_exact_match": 0.0,
        "action_items_csv_present_valid_header": 0.0,
        "action_items_csv_exact_join_and_sort": 0.0,
        "meeting_summary_final_exists": 0.0,
        "meeting_summary_headings_preserved": 0.0,
        "meeting_summary_dates_counts_correct": 0.0,
        "meeting_summary_attendance_lines_valid": 0.0,
        "meeting_summary_themes_bullets_correct": 0.0,
        "meeting_summary_advice_bullets_correct": 0.0,
        "meeting_summary_action_table_matches_csv": 0.0,
    }

    # Step 1: actions.jsonl checks
    actions_jsonl_path = workspace / "output" / "actions.jsonl"
    jsonl_actions = load_jsonl(actions_jsonl_path)
    if jsonl_actions is not None:
        # Validate structure for each line
        valid_struct = True
        for rec in jsonl_actions:
            if not all(k in rec for k in ["source_file", "line_no", "person", "task", "due_date"]):
                valid_struct = False
                break
        if valid_struct:
            scores["actions_jsonl_present_valid"] = 1.0

    expected_actions = extract_expected_actions(workspace)
    if expected_actions is not None and jsonl_actions is not None:
        # Strict equality including order and values
        if jsonl_actions == expected_actions:
            scores["actions_jsonl_exact_match"] = 1.0

    # Step 2: action_items_joined.csv checks
    action_items_csv_path = workspace / "output" / "action_items_joined.csv"
    parsed_csv = parse_csv_strict(action_items_csv_path)
    required_header = ["source_file", "line_no", "person", "email", "task", "due_date"]
    if parsed_csv is not None:
        header, rows = parsed_csv
        if header == required_header:
            scores["action_items_csv_present_valid_header"] = 1.0

    expected_join_rows = compute_expected_join_rows(workspace)
    if parsed_csv is not None and expected_join_rows is not None:
        header, rows = parsed_csv
        # Compare number of rows and exact cell values in order
        def row_to_tuple(r: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
            return (
                (r.get("source_file") or "").strip(),
                (r.get("line_no") or "").strip(),
                (r.get("person") or "").strip(),
                (r.get("email") or "").strip(),
                (r.get("task") or "").strip(),
                (r.get("due_date") or "").strip(),
            )
        actual = [row_to_tuple(r) for r in rows]
        expected = [(
            r["source_file"],
            r["line_no"],
            r["person"],
            r["email"],
            r["task"],
            r["due_date"],
        ) for r in expected_join_rows]
        if actual == expected:
            scores["action_items_csv_exact_join_and_sort"] = 1.0

    # Step 3: meeting_summary_final.md checks
    meeting_final_path = workspace / "output" / "meeting_summary_final.md"
    final_lines = read_text_lines(meeting_final_path)
    if final_lines is not None:
        scores["meeting_summary_final_exists"] = 1.0

        # Basic headings preserved check
        headings = [
            "Meeting Summary: Advising Hours (2026-04-15) and Graduate Seminar (2026-04-17)",
            "Overview",
            "Attendance",
            "Key Themes",
            "Career Guidance Offered",
            "Action Items",
            "Notes",
        ]
        if final_lines:
            indices = []
            ok_order = True
            for h in headings:
                try:
                    idx = next(i for i, ln in enumerate(final_lines) if ln.strip() == h)
                    indices.append(idx)
                except StopIteration:
                    ok_order = False
                    break
            if ok_order and all(earlier < later for earlier, later in zip(indices, indices[1:])):
                scores["meeting_summary_headings_preserved"] = 1.0

        # Dates and counts correctness in Notes section
        attendance_info = get_attendance_info(workspace)
        if attendance_info is not None:
            expected_dates_text = "Dates covered: 2026-04-15; 2026-04-17."
            expected_counts_text = f"Counts: 2026-04-15: {attendance_info['2026-04-15']['count']}; 2026-04-17: {attendance_info['2026-04-17']['count']}."
            text = "\n".join(final_lines)
            dates_ok = expected_dates_text in text
            counts_ok = expected_counts_text in text
            if dates_ok and counts_ok:
                scores["meeting_summary_dates_counts_correct"] = 1.0

        # Attendance table lines validation
        if attendance_info is not None:
            att_section_lines = get_section_lines(final_lines, "Attendance", "Key Themes")
            # Keep only non-empty lines
            att_non_empty = [ln for ln in att_section_lines if ln.strip() != ""]
            # Must be exactly two lines, each including expected date, count, and names substring
            expected_entries = [
                ("2026-04-15", attendance_info["2026-04-15"]["count"], attendance_info["2026-04-15"]["names"]),
                ("2026-04-17", attendance_info["2026-04-17"]["count"], attendance_info["2026-04-17"]["names"]),
            ]
            if len(att_non_empty) == 2:
                checks = []
                for (date, cnt, names), line in zip(expected_entries, att_non_empty):
                    has_date = (date in line)
                    has_count = (str(cnt) in line)
                    has_names = (names in line)
                    checks.append(has_date and has_count and has_names)
                if all(checks):
                    scores["meeting_summary_attendance_lines_valid"] = 1.0

        # Themes bullet list correctness (set equality)
        extracted = extract_themes_and_advices(workspace)
        if extracted is not None:
            expected_themes, expected_advices = extracted

            themes_section_lines = get_section_lines(final_lines, "Key Themes", "Career Guidance Offered")
            theme_bullets = parse_bullet_items(themes_section_lines)
            if theme_bullets:
                if set(theme_bullets) == set(expected_themes):
                    scores["meeting_summary_themes_bullets_correct"] = 1.0

            # Advice bullet list correctness (multiset equality)
            advice_section_lines = get_section_lines(final_lines, "Career Guidance Offered", "Action Items")
            advice_bullets = parse_bullet_items(advice_section_lines)
            if advice_bullets:
                if Counter(advice_bullets) == Counter(expected_advices):
                    scores["meeting_summary_advice_bullets_correct"] = 1.0

        # Action summary table matches CSV
        if parsed_csv is not None:
            header, rows = parsed_csv
            # Build expected rows for table from CSV rows in the same order
            expected_table_header = ["person", "email", "task", "due_date", "source_file"]
            expected_table_rows = []
            for r in rows:
                expected_table_rows.append([
                    (r.get("person") or "").strip(),
                    (r.get("email") or "").strip(),
                    (r.get("task") or "").strip(),
                    (r.get("due_date") or "").strip(),
                    (r.get("source_file") or "").strip(),
                ])
            action_section_lines = get_section_lines(final_lines, "Action Items", "Notes")
            tbl_header, tbl_rows = parse_markdown_table(action_section_lines)
            if tbl_header and tbl_rows:
                # Normalize header cells
                norm_header = [h.strip() for h in tbl_header]
                if norm_header == expected_table_header and len(tbl_rows) == len(expected_table_rows):
                    # Normalize rows cells to 5 columns
                    rows_ok = True
                    for actual_cells, exp_cells in zip(tbl_rows, expected_table_rows):
                        # Some markdown tables may omit trailing empty cells; enforce exact 5 after normalization
                        if len(actual_cells) != 5:
                            rows_ok = False
                            break
                        act_norm = [c.strip() for c in actual_cells]
                        if act_norm != exp_cells:
                            rows_ok = False
                            break
                    if rows_ok:
                        scores["meeting_summary_action_table_matches_csv"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()