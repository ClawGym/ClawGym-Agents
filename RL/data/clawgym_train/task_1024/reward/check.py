import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()
        i += 1
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key_part, rest = line.split(":", 1)
        key = key_part.strip()
        value = rest.strip()
        if value == "":
            items = []
            while i < n:
                nxt = lines[i]
                if re.match(r"^\s*-\s+", nxt):
                    item_val = re.sub(r"^\s*-\s+", "", nxt).strip()
                    if (item_val.startswith('"') and item_val.endswith('"')) or (item_val.startswith("'") and item_val.endswith("'")):
                        item_val = item_val[1:-1]
                    items.append(item_val)
                    i += 1
                else:
                    break
            data[key] = items
        else:
            val = value
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[key] = val
    return data


def _parse_transcript_headers_and_actions(path: Path, action_markers: List[str]) -> Tuple[Dict[str, str], List[str]]:
    content = _read_text(path)
    if content is None:
        return {}, []
    headers: Dict[str, str] = {}
    action_lines: List[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Meeting:"):
            headers["Meeting"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Date:"):
            headers["Date"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Participants:"):
            headers["Participants"] = line.split(":", 1)[1].strip()
            continue
        for m in action_markers:
            if line.startswith(m):
                action_lines.append(line)
                break
    return headers, action_lines


def _extract_due_date(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)
    return None


def _clean_description(desc: str) -> str:
    desc = desc.strip()
    if desc.endswith("."):
        desc = desc[:-1]
    desc = desc.strip()
    return desc


def _parse_action_item_from_line(line: str, markers: List[str]) -> Optional[Dict[str, str]]:
    body = line
    for m in markers:
        if body.startswith(m):
            body = body[len(m):].strip()
            break
    body = body.lstrip(":").strip()
    due = _extract_due_date(body)
    body_wo_due = re.sub(r"\bby\s+\d{4}-\d{2}-\d{2}\b", "", body, flags=re.IGNORECASE).strip()
    m1 = re.match(r"^([A-Z][a-zA-Z]+)\s+will\s+(.*)$", body_wo_due)
    m2 = re.match(r"^([A-Z][a-zA-Z]+)\s+to\s+(.*)$", body_wo_due)
    assignee = None
    desc = None
    if m1:
        assignee = m1.group(1).strip()
        desc = _clean_description(m1.group(2))
    elif m2:
        assignee = m2.group(1).strip()
        desc = _clean_description(m2.group(2))
    else:
        parts = body_wo_due.split()
        if len(parts) >= 2:
            assignee = parts[0]
            desc = _clean_description(" ".join(parts[1:]))
        else:
            return None
    return {
        "assignee": assignee,
        "description": desc,
        "due_date": due if due is not None else "",
    }


def _read_csv_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_bullet_action_items_from_md(md_text: str) -> List[Dict[str, Optional[str]]]:
    items = []
    for line in md_text.splitlines():
        m = re.match(r"^\s*[-*]\s+([^—]+)\s+—\s+(.*?)(?:\s+\(Due:\s*(\d{4}-\d{2}-\d{2})\))?\s*$", line)
        if m:
            assignee = m.group(1).strip()
            desc = m.group(2).strip()
            due = m.group(3) if m.group(3) else ""
            items.append({"assignee": assignee, "description": desc, "due_date": due})
    return items


def _endswith_path_or_equal(actual: str, expected: str) -> bool:
    try:
        a = str(actual)
        e = str(expected)
        return a == e or a.endswith(str(e).replace("\\", "/")) or a.replace("\\", "/").endswith(e.replace("\\", "/"))
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "notes_file_exists": 0.0,
        "notes_title_and_date_correct": 0.0,
        "notes_participants_correct": 0.0,
        "notes_action_items_list_format_and_content": 0.0,
        "action_items_csv_structure": 0.0,
        "action_items_csv_rows_correct": 0.0,
        "invalid_error_json_structure": 0.0,
        "invalid_error_json_missing_headers_correct": 0.0,
        "logging_session_log_contains_error": 0.0,
        "logging_error_summary_derived_from_session_log": 0.0,
        "effective_config_written_and_matches_yaml": 0.0,
    }

    config_path = workspace / "config" / "meeting_rules.yaml"
    cfg = _load_simple_yaml(config_path)
    if not isinstance(cfg, dict):
        return scores

    incoming_dir = cfg.get("incoming_dir")
    notes_dir = cfg.get("notes_dir")
    invalid_dir = cfg.get("invalid_dir")
    logs_dir = cfg.get("logs_dir")
    action_items_csv_path = cfg.get("action_items_csv")
    file_glob = cfg.get("file_glob")
    required_headers = cfg.get("required_headers", [])
    action_markers = cfg.get("action_item_markers", [])

    if not all(isinstance(x, str) for x in [incoming_dir, notes_dir, invalid_dir, logs_dir, action_items_csv_path, file_glob]):
        return scores
    if not isinstance(required_headers, list) or not isinstance(action_markers, list):
        return scores

    incoming_dir_path = workspace / incoming_dir
    valid_basename = "psc_2025-03-15.txt"
    invalid_basename = "psc_missing_date.txt"
    valid_transcript_path = incoming_dir_path / valid_basename
    invalid_transcript_path = incoming_dir_path / invalid_basename

    valid_headers, valid_action_lines = _parse_transcript_headers_and_actions(valid_transcript_path, action_markers)
    if valid_headers and valid_action_lines is not None:
        expected_meeting = valid_headers.get("Meeting")
        expected_date = valid_headers.get("Date")
        expected_participants_raw = valid_headers.get("Participants")
    else:
        expected_meeting = None
        expected_date = None
        expected_participants_raw = None

    expected_participants_list: List[str] = []
    if expected_participants_raw:
        expected_participants_list = [p.strip() for p in expected_participants_raw.split(";") if p.strip()]
    expected_action_items: List[Dict[str, str]] = []
    if valid_action_lines is not None and action_markers:
        for line in valid_action_lines:
            parsed = _parse_action_item_from_line(line.strip(), action_markers)
            if parsed:
                expected_action_items.append(parsed)

    notes_out_dir = workspace / notes_dir
    expected_notes_file = notes_out_dir / valid_basename.replace(".txt", ".md")
    notes_text = _read_text(expected_notes_file)
    if notes_text is not None:
        scores["notes_file_exists"] = 1.0
        title_ok = isinstance(expected_meeting, str) and (expected_meeting in notes_text)
        date_ok = isinstance(expected_date, str) and (expected_date in notes_text)
        scores["notes_title_and_date_correct"] = 1.0 if (title_ok and date_ok) else 0.0

        participants_label_present = bool(re.search(r"participants", notes_text, re.IGNORECASE))
        names_present = all([(name in notes_text) for name in expected_participants_list]) if expected_participants_list else False
        expected_count = len(expected_participants_list)
        participants_count_ok = False
        for line in notes_text.splitlines():
            if re.search(r"participants", line, re.IGNORECASE):
                if re.search(rf"\b{expected_count}\b", line):
                    participants_count_ok = True
                    break
        if not participants_count_ok and participants_label_present:
            if re.search(rf"\(\s*{expected_count}\s*\)", notes_text) or re.search(rf"\b{expected_count}\b", notes_text):
                participants_count_ok = True
        scores["notes_participants_correct"] = 1.0 if (participants_label_present and names_present and participants_count_ok) else 0.0

        extracted_md_items = _extract_bullet_action_items_from_md(notes_text)
        expected_tuples = set()
        for item in expected_action_items:
            expected_tuples.add((item["assignee"], item["description"], item["due_date"]))
        observed_tuples = set()
        for item in extracted_md_items:
            observed_tuples.add((item.get("assignee", ""), item.get("description", ""), item.get("due_date", "")))

        if expected_tuples.issubset(observed_tuples):
            due_items_ok = True
            for item in expected_action_items:
                if item["due_date"]:
                    pattern = re.compile(rf"{re.escape(item['assignee'])}.*\(Due:\s*{re.escape(item['due_date'])}\)")
                    if not any(pattern.search(line) for line in notes_text.splitlines()):
                        due_items_ok = False
                        break
            scores["notes_action_items_list_format_and_content"] = 1.0 if due_items_ok else 0.0
        else:
            scores["notes_action_items_list_format_and_content"] = 0.0
    else:
        scores["notes_file_exists"] = 0.0
        scores["notes_title_and_date_correct"] = 0.0
        scores["notes_participants_correct"] = 0.0
        scores["notes_action_items_list_format_and_content"] = 0.0

    csv_path = workspace / action_items_csv_path
    csv_data = _read_csv_rows(csv_path)
    if csv_data is not None:
        headers, rows = csv_data
        expected_headers = ["source_file", "meeting", "date", "assignee", "description", "due_date"]
        if headers == expected_headers:
            scores["action_items_csv_structure"] = 1.0
        else:
            scores["action_items_csv_structure"] = 0.0

        rows_ok = False
        if isinstance(expected_meeting, str) and isinstance(expected_date, str) and expected_action_items:
            csv_tuples = []
            for r in rows:
                src = (r.get("source_file") or "")
                meeting = (r.get("meeting") or "")
                date = (r.get("date") or "")
                assignee = (r.get("assignee") or "")
                desc = (r.get("description") or "")
                due = (r.get("due_date") or "")
                csv_tuples.append((src, meeting, date, assignee, desc, due))

            if len(csv_tuples) == len(expected_action_items):
                all_match = True
                for item in expected_action_items:
                    found = False
                    for tup in csv_tuples:
                        src_ok = _endswith_path_or_equal(tup[0], valid_basename)
                        if src_ok and tup[1] == expected_meeting and tup[2] == expected_date and tup[3] == item["assignee"] and tup[4] == item["description"] and tup[5] == item["due_date"]:
                            found = True
                            break
                    if not found:
                        all_match = False
                        break
                no_invalid_refs = all(("psc_missing_date.txt" not in tup[0]) for tup in csv_tuples)
                rows_ok = all_match and no_invalid_refs
        scores["action_items_csv_rows_correct"] = 1.0 if rows_ok else 0.0
    else:
        scores["action_items_csv_structure"] = 0.0
        scores["action_items_csv_rows_correct"] = 0.0

    invalid_out_dir = workspace / cfg.get("invalid_dir")
    invalid_error_file = invalid_out_dir / invalid_basename.replace(".txt", ".error.json")
    invalid_json = _load_json(invalid_error_file)
    if isinstance(invalid_json, dict):
        has_fields = all(k in invalid_json for k in ["file", "error", "missing_headers", "detected_headers"])
        scores["invalid_error_json_structure"] = 1.0 if has_fields else 0.0
        content_ok = False
        if has_fields:
            missing = invalid_json.get("missing_headers")
            detected = invalid_json.get("detected_headers")
            err_msg = str(invalid_json.get("error", "")).lower()
            file_field = str(invalid_json.get("file", ""))
            inv_headers, _ = _parse_transcript_headers_and_actions(invalid_transcript_path, action_markers)
            expected_missing = []
            for h in required_headers:
                if h not in inv_headers:
                    expected_missing.append(h)
            date_missing_ok = "Date" in expected_missing and isinstance(missing, list) and "Date" in missing
            detected_ok = isinstance(detected, dict) and ("Meeting" in detected) and ("Participants" in detected) and (detected.get("Meeting") == inv_headers.get("Meeting")) and (detected.get("Participants") == inv_headers.get("Participants"))
            file_ok = _endswith_path_or_equal(file_field, str(invalid_transcript_path)) or _endswith_path_or_equal(file_field, invalid_basename)
            error_msg_ok = ("missing" in err_msg and "date" in err_msg) or ("Date" in str(invalid_json.get("error", "")))
            content_ok = date_missing_ok and detected_ok and file_ok and error_msg_ok
        scores["invalid_error_json_missing_headers_correct"] = 1.0 if content_ok else 0.0
    else:
        scores["invalid_error_json_structure"] = 0.0
        scores["invalid_error_json_missing_headers_correct"] = 0.0

    logs_out_dir = workspace / cfg.get("logs_dir")
    session_log = logs_out_dir / "session.log"
    error_summary = logs_out_dir / "error_summary.txt"
    session_text = _read_text(session_log)
    if session_text is not None:
        error_lines = [ln for ln in session_text.splitlines() if "ERROR" in ln]
        has_error_for_invalid = any(("psc_missing_date" in ln and ("Date" in ln or "date" in ln or "missing" in ln.lower())) for ln in error_lines)
        scores["logging_session_log_contains_error"] = 1.0 if has_error_for_invalid else 0.0

        summary_text = _read_text(error_summary)
        if summary_text is not None:
            summary_lines = summary_text.splitlines()
            all_errors_included = all(any(err.strip() == s.strip() or err.strip() in s for s in summary_lines) for err in error_lines) if error_lines else False
            scores["logging_error_summary_derived_from_session_log"] = 1.0 if all_errors_included and len(error_lines) > 0 else 0.0
        else:
            scores["logging_error_summary_derived_from_session_log"] = 0.0
    else:
        scores["logging_session_log_contains_error"] = 0.0
        scores["logging_error_summary_derived_from_session_log"] = 0.0

    effective_config_path = logs_out_dir / "effective_config.json"
    effective_cfg = _load_json(effective_config_path)
    if isinstance(effective_cfg, dict):
        keys_to_check = ["incoming_dir", "notes_dir", "invalid_dir", "logs_dir", "action_items_csv", "file_glob", "required_headers", "action_item_markers"]
        has_all_keys = all(k in effective_cfg for k in keys_to_check)
        if has_all_keys:
            str_ok = True
            for k in ["incoming_dir", "notes_dir", "invalid_dir", "logs_dir", "action_items_csv", "file_glob"]:
                v_yaml = cfg.get(k)
                v_eff = effective_cfg.get(k)
                if not isinstance(v_eff, str) or not isinstance(v_yaml, str):
                    str_ok = False
                    break
                if not _endswith_path_or_equal(v_eff, v_yaml):
                    str_ok = False
                    break
            lists_ok = True
            for k in ["required_headers", "action_item_markers"]:
                v_yaml = cfg.get(k)
                v_eff = effective_cfg.get(k)
                if not (isinstance(v_yaml, list) and isinstance(v_eff, list) and v_eff == v_yaml):
                    lists_ok = False
                    break
            scores["effective_config_written_and_matches_yaml"] = 1.0 if (str_ok and lists_ok) else 0.0
        else:
            scores["effective_config_written_and_matches_yaml"] = 0.0
    else:
        scores["effective_config_written_and_matches_yaml"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()