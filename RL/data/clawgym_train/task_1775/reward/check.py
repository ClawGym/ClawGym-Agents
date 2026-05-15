import json
import csv
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_yaml_config(yaml_text: str) -> dict:
    # Extract required fields using regex due to stdlib limitation (no YAML parser).
    data = {
        "meeting_title": None,
        "meeting_date": None,
        "target_temp_c": None,
        "calibration_offset_c": None,
        "oil_smoke_point_c": None,
        "todos": [],
        "fixmes": [],
    }
    # Meeting title and date
    m = re.search(r'^\s*meeting_title:\s*"(.*)"\s*$', yaml_text, flags=re.MULTILINE)
    if not m:
        m = re.search(r'^\s*meeting_title:\s*(.+?)\s*$', yaml_text, flags=re.MULTILINE)
    if m:
        data["meeting_title"] = m.group(1).strip()

    m = re.search(r'^\s*meeting_date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$', yaml_text, flags=re.MULTILINE)
    if m:
        data["meeting_date"] = m.group(1).strip()

    # Numeric params
    for key in ["target_temp_c", "calibration_offset_c", "oil_smoke_point_c"]:
        patt = rf'^\s*{key}:\s*([\-0-9\.]+)'
        m = re.search(patt, yaml_text, flags=re.MULTILINE)
        if m:
            try:
                data[key] = float(m.group(1))
            except ValueError:
                data[key] = None

    # TODO and FIXME (inline comments)
    todos = re.findall(r'#\s*TODO:\s*(.*)', yaml_text)
    fixmes = re.findall(r'#\s*FIXME:\s*(.*)', yaml_text)
    data["todos"] = [t.strip() for t in todos if t.strip()]
    data["fixmes"] = [f.strip() for f in fixmes if f.strip()]
    return data


def parse_logger_py(py_text: str) -> dict:
    data = {
        "SOUS_VIDE_TARGET_C": None,
        "CALIBRATION_OFFSET_C": None,
        "OIL_SMOKE_POINT_C": None,
        "todos": [],
        "fixmes": [],
    }
    for key in ["SOUS_VIDE_TARGET_C", "CALIBRATION_OFFSET_C", "OIL_SMOKE_POINT_C"]:
        m = re.search(rf'^\s*{key}\s*=\s*([\-0-9\.]+)', py_text, flags=re.MULTILINE)
        if m:
            try:
                data[key] = float(m.group(1))
            except ValueError:
                data[key] = None

    # Extract TODO/FIXME anywhere in the file (including docstrings and comments)
    todos = re.findall(r'TODO:\s*(.*)', py_text)
    fixmes = re.findall(r'FIXME:\s*(.*)', py_text)
    data["todos"] = [t.strip() for t in todos if t.strip()]
    data["fixmes"] = [f.strip() for f in fixmes if f.strip()]
    return data


def parse_lesson_outline(md_text: str) -> List[Tuple[str, str]]:
    # Returns list of (heading, first_sentence)
    lines = md_text.splitlines()
    results: List[Tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("## "):
            heading = line[3:].strip()
            # Find first non-empty line after heading
            j = i + 1
            first_para_line = None
            while j < len(lines):
                content = lines[j].strip()
                if content:
                    first_para_line = content
                    break
                j += 1
            if first_para_line:
                # Extract first sentence up to first period.
                # If no period, take entire line.
                sentence = first_para_line
                # Consider period followed by space or end of line.
                idx = sentence.find(".")
                if idx != -1:
                    sentence = sentence[: idx + 1]
                results.append((heading, sentence.strip()))
            i = j
        else:
            i += 1
    return results


def parse_observations(text: str) -> List[str]:
    issues = []
    for line in text.splitlines():
        if line.startswith("ISSUE:"):
            issues.append(line.strip())
    return issues


def parse_csv_file(csv_path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def extract_section(text: str, section_name: str, other_sections: List[str]) -> Optional[str]:
    # Find the block of text for a given section_name up to the next other section.
    lines = text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if section_name.lower() in line.lower():
            start_idx = idx
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        for other in other_sections:
            if other.lower() in lines[idx].lower():
                end_idx = idx
                break
        if end_idx != len(lines):
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def safe_date_parse(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "meeting_notes_exists": 0.0,
        "action_items_csv_exists": 0.0,
        "csv_columns_and_structure": 0.0,
        "csv_expected_row_count": 0.0,
        "csv_id_sequence_and_count": 0.0,
        "csv_due_date_correct": 0.0,
        "csv_category_and_priority_correct": 0.0,
        "csv_source_file_mapping": 0.0,
        "meeting_notes_title_present": 0.0,
        "teaching_highlights_section_content": 0.0,
        "lab_issues_section_mismatches_and_refs": 0.0,
        "lab_issues_section_todos_fixmes": 0.0,
        "discussion_points_section_issues_listed": 0.0,
        "action_items_section_contains_ids": 0.0,
    }

    # Input files
    lesson_path = workspace / "input" / "lesson_outline.md"
    observations_path = workspace / "input" / "lab_observations.txt"
    config_path = workspace / "config" / "lab_settings.yaml"
    logger_path = workspace / "scripts" / "logger.py"

    lesson_text = read_text_safe(lesson_path)
    observations_text = read_text_safe(observations_path)
    config_text = read_text_safe(config_path)
    logger_text = read_text_safe(logger_path)

    # Output files
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    action_csv_path = workspace / "output" / "action_items.csv"

    meeting_notes_text = read_text_safe(meeting_notes_path)
    if meeting_notes_text is not None:
        scores["meeting_notes_exists"] = 1.0

    header, rows = parse_csv_file(action_csv_path) if action_csv_path.exists() else (None, None)
    if header is not None and rows is not None:
        scores["action_items_csv_exists"] = 1.0

    # Parse inputs
    config = parse_yaml_config(config_text) if config_text else None
    logger_info = parse_logger_py(logger_text) if logger_text else None
    topics = parse_lesson_outline(lesson_text) if lesson_text else None
    issues = parse_observations(observations_text) if observations_text else None

    # Compute expected items
    expected_mismatches = []
    if config and logger_info:
        # sous-vide target
        cfg_target = config.get("target_temp_c")
        py_target = logger_info.get("SOUS_VIDE_TARGET_C")
        if cfg_target is not None and py_target is not None and cfg_target != py_target:
            expected_mismatches.append(("sous_vide_target_c", py_target, cfg_target))
        # calibration offset
        cfg_cal = config.get("calibration_offset_c")
        py_cal = logger_info.get("CALIBRATION_OFFSET_C")
        if cfg_cal is not None and py_cal is not None and cfg_cal != py_cal:
            expected_mismatches.append(("calibration_offset_c", py_cal, cfg_cal))
        # oil smoke point
        cfg_smoke = config.get("oil_smoke_point_c")
        py_smoke = logger_info.get("OIL_SMOKE_POINT_C")
        if cfg_smoke is not None and py_smoke is not None and cfg_smoke != py_smoke:
            expected_mismatches.append(("oil_smoke_point_c", py_smoke, cfg_smoke))

    yaml_todos = config.get("todos", []) if config else []
    yaml_fixmes = config.get("fixmes", []) if config else []
    py_todos = logger_info.get("todos", []) if logger_info else []
    py_fixmes = logger_info.get("fixmes", []) if logger_info else []

    expected_todo_count_yaml = len(yaml_todos)
    expected_fixme_count_yaml = len(yaml_fixmes)
    expected_todo_count_py = len(py_todos)
    expected_fixme_count_py = len(py_fixmes)

    expected_observation_issues = issues if issues else []

    # Check CSV structure
    expected_header = ["id", "description", "source_file", "category", "due_date", "priority"]
    if header is not None and rows is not None:
        if header == expected_header:
            scores["csv_columns_and_structure"] = 1.0

        # Expected counts
        if config and logger_info and issues is not None:
            expected_total = len(expected_mismatches) + expected_todo_count_yaml + expected_fixme_count_yaml + expected_todo_count_py + expected_fixme_count_py + len(expected_observation_issues)
            if len(rows) == expected_total:
                scores["csv_expected_row_count"] = 1.0

        # ID sequence A1..An
        ids_ok = True
        for idx, row in enumerate(rows, start=1):
            if row.get("id") != f"A{idx}":
                ids_ok = False
                break
        if ids_ok and len(rows) > 0:
            scores["csv_id_sequence_and_count"] = 1.0

        # Due date
        due_ok = False
        if config and config.get("meeting_date"):
            dt = safe_date_parse(config.get("meeting_date"))
            if dt:
                due_date_str = (dt + timedelta(days=3)).strftime("%Y-%m-%d")
                due_ok = all(r.get("due_date") == due_date_str for r in rows)
        if due_ok:
            scores["csv_due_date_correct"] = 1.0

        # Category and priority correctness
        allowed_categories = {"mismatch", "todo", "fixme", "observation_issue"}
        cat_counts = {"mismatch": 0, "todo": 0, "fixme": 0, "observation_issue": 0}
        catprio_ok = True
        for r in rows:
            cat = r.get("category", "")
            pr = r.get("priority", "")
            if cat not in allowed_categories:
                catprio_ok = False
                break
            if cat == "todo" and pr != "Medium":
                catprio_ok = False
                break
            if cat in {"mismatch", "fixme", "observation_issue"} and pr != "High":
                catprio_ok = False
                break
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        expected_cat_counts = None
        if config and logger_info and issues is not None:
            expected_cat_counts = {
                "mismatch": len(expected_mismatches),
                "todo": expected_todo_count_yaml + expected_todo_count_py,
                "fixme": expected_fixme_count_yaml + expected_fixme_count_py,
                "observation_issue": len(expected_observation_issues),
            }
        if catprio_ok and expected_cat_counts is not None and cat_counts == expected_cat_counts:
            scores["csv_category_and_priority_correct"] = 1.0

        # Source file mapping
        source_ok = True
        if rows:
            for r in rows:
                src = r.get("source_file", "")
                cat = r.get("category", "")
                if src not in {"scripts/logger.py", "config/lab_settings.yaml", "input/lab_observations.txt"}:
                    source_ok = False
                    break
                if cat == "observation_issue" and src != "input/lab_observations.txt":
                    source_ok = False
                    break
                if cat in {"todo", "fixme"}:
                    # Must correspond to actual source file containing the item
                    # Count-based validation: ensure sufficient rows per source
                    pass  # Defer counts check below
                if cat == "mismatch" and src not in {"scripts/logger.py", "config/lab_settings.yaml"}:
                    source_ok = False
                    break
            # Count-based check for todo/fixme per source
            if source_ok:
                todo_yaml_rows = sum(1 for r in rows if r.get("category") == "todo" and r.get("source_file") == "config/lab_settings.yaml")
                todo_py_rows = sum(1 for r in rows if r.get("category") == "todo" and r.get("source_file") == "scripts/logger.py")
                fixme_yaml_rows = sum(1 for r in rows if r.get("category") == "fixme" and r.get("source_file") == "config/lab_settings.yaml")
                fixme_py_rows = sum(1 for r in rows if r.get("category") == "fixme" and r.get("source_file") == "scripts/logger.py")
                obs_rows = sum(1 for r in rows if r.get("category") == "observation_issue" and r.get("source_file") == "input/lab_observations.txt")
                mismatch_rows = sum(1 for r in rows if r.get("category") == "mismatch" and r.get("source_file") in {"scripts/logger.py", "config/lab_settings.yaml"})

                # Only if inputs are parsed
                if config and logger_info and issues is not None:
                    if not (todo_yaml_rows == expected_todo_count_yaml and
                            todo_py_rows == expected_todo_count_py and
                            fixme_yaml_rows == expected_fixme_count_yaml and
                            fixme_py_rows == expected_fixme_count_py and
                            obs_rows == len(expected_observation_issues) and
                            mismatch_rows == len(expected_mismatches)):
                        source_ok = False
        if source_ok:
            scores["csv_source_file_mapping"] = 1.0

    # Meeting notes checks
    if meeting_notes_text and config:
        # Title line contains meeting_title and meeting_date
        mt = config.get("meeting_title")
        md = config.get("meeting_date")
        if mt and md:
            first_nonempty = None
            for line in meeting_notes_text.splitlines():
                if line.strip():
                    first_nonempty = line.strip()
                    break
            if first_nonempty and (mt in first_nonempty) and (md in first_nonempty):
                scores["meeting_notes_title_present"] = 1.0

        # Teaching Highlights section content
        th_section = extract_section(
            meeting_notes_text,
            "Teaching Highlights",
            ["Lab Issues from Config/Code", "Discussion Points from Observations", "Action Items"],
        )
        th_ok = False
        if th_section and topics is not None:
            th_ok = True
            for heading, sentence in topics:
                if (heading not in th_section) or (sentence not in th_section):
                    th_ok = False
                    break
        if th_ok:
            scores["teaching_highlights_section_content"] = 1.0

        # Lab Issues from Config/Code section: mismatches and TODO/FIXME
        li_section = extract_section(
            meeting_notes_text,
            "Lab Issues from Config/Code",
            ["Teaching Highlights", "Discussion Points from Observations", "Action Items"],
        )
        li_mismatch_ok = False
        li_todo_fixme_ok = False
        if li_section and config and logger_info:
            # Mismatches: ensure both values for each mismatch appear, and file names appear
            files_present = ("scripts/logger.py" in li_section) and ("config/lab_settings.yaml" in li_section)
            mis_ok = files_present
            for name, py_val, cfg_val in expected_mismatches:
                # Check that string representations of values appear
                py_str = str(int(py_val)) if float(py_val).is_integer() else str(py_val)
                cfg_str = str(int(cfg_val)) if float(cfg_val).is_integer() else str(cfg_val)
                if py_str not in li_section or cfg_str not in li_section:
                    mis_ok = False
                    break
            if mis_ok and expected_mismatches:
                li_mismatch_ok = True
            elif mis_ok and not expected_mismatches:
                # If there are no mismatches, consider it okay to not list values
                li_mismatch_ok = True

            # TODO/FIXME notes presence with file references
            tf_ok = True
            # Require that for every TODO/FIXME extracted, its text appears and a file reference appears somewhere
            for t in (yaml_todos or []):
                if t not in li_section or "config/lab_settings.yaml" not in li_section:
                    tf_ok = False
                    break
            for f in (yaml_fixmes or []):
                if f not in li_section or "config/lab_settings.yaml" not in li_section:
                    tf_ok = False
                    break
            for t in (py_todos or []):
                if t not in li_section or "scripts/logger.py" not in li_section:
                    tf_ok = False
                    break
            for f in (py_fixmes or []):
                if f not in li_section or "scripts/logger.py" not in li_section:
                    tf_ok = False
                    break
            if tf_ok:
                li_todo_fixme_ok = True

        if li_mismatch_ok:
            scores["lab_issues_section_mismatches_and_refs"] = 1.0
        if li_todo_fixme_ok:
            scores["lab_issues_section_todos_fixmes"] = 1.0

        # Discussion Points from Observations
        dp_section = extract_section(
            meeting_notes_text,
            "Discussion Points from Observations",
            ["Teaching Highlights", "Lab Issues from Config/Code", "Action Items"],
        )
        dp_ok = False
        if dp_section and issues is not None:
            dp_ok = all(issue in dp_section for issue in issues)
        if dp_ok:
            scores["discussion_points_section_issues_listed"] = 1.0

        # Action Items section contains IDs from CSV
        ai_section = extract_section(
            meeting_notes_text,
            "Action Items",
            ["Teaching Highlights", "Lab Issues from Config/Code", "Discussion Points from Observations"],
        )
        ai_ok = False
        if ai_section and rows is not None and len(rows) > 0:
            ai_ok = all((r.get("id") or "") in ai_section for r in rows)
        if ai_ok:
            scores["action_items_section_contains_ids"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()