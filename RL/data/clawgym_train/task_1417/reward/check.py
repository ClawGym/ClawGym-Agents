import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_constraints_yaml(text: Optional[str]) -> Dict[str, object]:
    """
    Minimal parser for the given constraints.yaml structure.
    Extracts only the keys used by the grader:
      - required_topics: list[str]
      - materials_available: list[str]
      - assessment.exit_ticket_questions_required: int
      - assessment.final_reflection_required: bool
      - scheduling.proposed_dates: list[str]
      - scheduling.room_preference: str
      - deliverables.curriculum_outline_fields: list[str]
      - constraints: list[str]
      - required_components_per_session: list[str]
    """
    result = {
        "required_topics": [],
        "materials_available": [],
        "assessment": {
            "exit_ticket_questions_required": None,
            "final_reflection_required": None,
        },
        "scheduling": {
            "proposed_dates": [],
            "room_preference": None,
        },
        "deliverables": {
            "curriculum_outline_fields": [],
        },
        "constraints": [],
        "required_components_per_session": [],
    }
    if text is None:
        return result

    lines = text.splitlines()

    def _collect_list(start_idx: int) -> Tuple[List[str], int]:
        items = []
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            if re.match(r"^\s*-\s", line):
                val = re.sub(r"^\s*-\s*", "", line).strip()
                # Strip surrounding quotes if present
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                items.append(val)
                i += 1
            else:
                break
        return items, i

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        # Top-level keys
        if re.match(r'^\s*required_topics:\s*$', line):
            items, i = _collect_list(i)
            result["required_topics"] = items
            continue
        if re.match(r'^\s*materials_available:\s*$', line):
            items, i = _collect_list(i)
            result["materials_available"] = items
            continue
        if re.match(r'^\s*constraints:\s*$', line):
            items, i = _collect_list(i)
            result["constraints"] = items
            continue
        if re.match(r'^\s*required_components_per_session:\s*$', line):
            items, i = _collect_list(i)
            result["required_components_per_session"] = items
            continue
        if re.match(r'^\s*assessment:\s*$', line):
            i += 1
            # parse nested keys under assessment
            while i < len(lines) and re.match(r'^\s{2,}\S', lines[i]):
                subline = lines[i].strip()
                m1 = re.match(r'^exit_ticket_questions_required:\s*(\d+)\s*$', subline)
                m2 = re.match(r'^final_reflection_required:\s*(true|false)\s*$', subline, flags=re.IGNORECASE)
                if m1:
                    result["assessment"]["exit_ticket_questions_required"] = int(m1.group(1))
                elif m2:
                    result["assessment"]["final_reflection_required"] = m2.group(1).lower() == "true"
                i += 1
            continue
        if re.match(r'^\s*scheduling:\s*$', line):
            i += 1
            while i < len(lines) and re.match(r'^\s{2,}\S', lines[i]):
                subline = lines[i]
                if re.match(r'^\s*proposed_dates:\s*$', subline.strip()):
                    items, i = _collect_list(i)
                    result["scheduling"]["proposed_dates"] = items
                    continue
                m = re.match(r'^\s*room_preference:\s*(.+)\s*$', subline.strip())
                if m:
                    val = m.group(1).strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    result["scheduling"]["room_preference"] = val
                i += 1
            continue
        if re.match(r'^\s*deliverables:\s*$', line):
            i += 1
            while i < len(lines) and re.match(r'^\s{2,}\S', lines[i]):
                subline = lines[i]
                if re.match(r'^\s*curriculum_outline_fields:\s*$', subline.strip()):
                    items, i = _collect_list(i)
                    result["deliverables"]["curriculum_outline_fields"] = items
                    continue
                i += 1
            continue
        i += 1

    return result


def _find_section_blocks(md_text: Optional[str], headings: List[str]) -> Tuple[bool, Dict[str, List[str]], List[str]]:
    """
    Locate sections with given headings in exact order.
    Returns (order_ok, sections_content_map, found_headings_order)
    Sections are identified by markdown headings lines (#, ##, etc).
    """
    content_map: Dict[str, List[str]] = {h: [] for h in headings}
    found_order: List[str] = []
    if md_text is None:
        return False, content_map, found_order

    lines = md_text.splitlines()
    # Find indices of headings
    indices: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines):
        m = re.match(r'^\s*#{1,6}\s*(.+?)\s*$', line)
        if m:
            title = m.group(1).strip()
            if title in headings:
                indices.append((idx, title))
    # build content slices
    if not indices:
        return False, content_map, found_order
    # Determine order_ok
    found_order = [t for _, t in indices]
    order_ok = found_order == headings
    # Collect content under each heading until next heading
    for i, (start_idx, title) in enumerate(indices):
        end_idx = indices[i + 1][0] if i + 1 < len(indices) else len(lines)
        content_map[title] = lines[start_idx + 1 : end_idx]
    return order_ok, content_map, found_order


def _extract_action_items_from_notes(notes_text: Optional[str]) -> List[Dict[str, object]]:
    """
    Extract action items from input/meeting_notes.md with format:
    - ACTION @Owner DUE: YYYY-MM-DD -> Task text
    """
    if notes_text is None:
        return []
    items: List[Dict[str, object]] = []
    lines = notes_text.splitlines()
    for idx, line in enumerate(lines, start=1):
        m = re.match(
            r'^\s*-\s*ACTION\s*@(?P<owner>\S+)\s+DUE:\s*(?P<due>\d{4}-\d{2}-\d{2})\s*->\s*(?P<task>.+?)\s*$',
            line
        )
        if m:
            items.append({
                "owner": m.group("owner"),
                "task": m.group("task").strip(),
                "due_date": m.group("due"),
                "status": "pending",
                "source_line": idx,
            })
    return items


def _extract_decisions_from_notes(notes_text: Optional[str]) -> List[str]:
    if notes_text is None:
        return []
    lines = notes_text.splitlines()
    decs = []
    for line in lines:
        m = re.match(r'^\s*-\s*DECISION:\s*(.+?)\s*$', line)
        if m:
            decs.append(m.group(1).strip())
    return decs


def _extract_open_questions_from_notes(notes_text: Optional[str]) -> List[str]:
    if notes_text is None:
        return []
    lines = notes_text.splitlines()
    opens = []
    for line in lines:
        m = re.match(r'^\s*-\s*OPEN:\s*(.+?)\s*$', line)
        if m:
            opens.append(m.group(1).strip())
    return opens


def _parse_markdown_table(lines: List[str]) -> List[Dict[str, str]]:
    """
    Parse a simple pipe-delimited markdown table.
    Returns list of row dicts with headers as keys.
    Ignores separator line (---).
    """
    rows: List[Dict[str, str]] = []
    # Find header
    header = None
    for i, line in enumerate(lines):
        if '|' in line:
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            # detect separator
            if all(re.match(r'^:?-{3,}:?$', c) for c in cells):
                continue
            if header is None:
                header = cells
                continue
            else:
                val_cells = [c.strip() for c in line.strip().strip('|').split('|')]
                if len(val_cells) == len(header):
                    row = {h: v for h, v in zip(header, val_cells)}
                    rows.append(row)
    return rows


def _curriculum_banned_content_present(session: Dict[str, object]) -> bool:
    banned_keywords = [
        "tactical",
        "sensitive procedure",
        "sensitive procedures",
        "advanced aerobatic",
        "aerobatic",
        "flight maneuvers",
        "maneuvers",
        "simulator",
        "simulation",
        "flight instruction",
    ]
    def _scan_text(s: str) -> bool:
        lower = s.lower()
        for kw in banned_keywords:
            if kw in lower:
                return True
        return False

    # Scan across textual fields and lists
    fields_to_check = ["title", "leadership_takeaway", "safety_takeaway"]
    for f in fields_to_check:
        val = session.get(f)
        if isinstance(val, str) and _scan_text(val):
            return True
    for list_field in ["objectives", "activities"]:
        vals = session.get(list_field)
        if isinstance(vals, list):
            for item in vals:
                if isinstance(item, str) and _scan_text(item):
                    return True
    assessment = session.get("assessment")
    if isinstance(assessment, dict):
        rp = assessment.get("reflection_prompt")
        if isinstance(rp, str) and _scan_text(rp):
            return True
        eq = assessment.get("exit_ticket_questions")
        if isinstance(eq, list):
            for q in eq:
                if isinstance(q, str) and _scan_text(q):
                    return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "curriculum_outline_json_valid_structure": 0.0,
        "per_session_components_check": 0.0,
        "materials_within_available": 0.0,
        "coverage_all_required_topics_present": 0.0,
        "topic_coverage_csv_columns_and_format": 0.0,
        "topic_coverage_csv_consistency": 0.0,
        "banned_content_absent_in_curriculum": 0.0,
        "meeting_summary_headings_order": 0.0,
        "meeting_summary_decisions_present": 0.0,
        "meeting_summary_open_questions_present": 0.0,
        "action_items_csv_complete_and_correct": 0.0,
        "action_items_table_complete_and_correct": 0.0,
        "rewritten_email_content_requirements": 0.0,
    }

    # Load constraints
    constraints_text = _read_text_safe(workspace / "input" / "constraints.yaml")
    constraints = _parse_constraints_yaml(constraints_text)
    required_topics: List[str] = constraints.get("required_topics", [])
    materials_available: List[str] = constraints.get("materials_available", [])
    exit_required = constraints.get("assessment", {}).get("exit_ticket_questions_required", 2)
    proposed_dates: List[str] = constraints.get("scheduling", {}).get("proposed_dates", [])
    room_pref: Optional[str] = constraints.get("scheduling", {}).get("room_preference", None)

    # 1) Curriculum outline checks
    outline_path = workspace / "outputs" / "curriculum_outline.json"
    outline = _load_json_safe(outline_path)
    valid_structure = False
    per_session_components_ok = False
    materials_ok = False
    banned_ok = False
    coverage_ok = False

    if isinstance(outline, list) and len(outline) == 4:
        # Validate sessions numbers and schema
        session_numbers = []
        schema_ok = True
        components_ok = True
        materials_subset_ok = True
        banned_absent = True
        coverage_map: Dict[str, List[int]] = {t: [] for t in required_topics}
        for sess in outline:
            if not isinstance(sess, dict):
                schema_ok = False
                break
            # Required fields presence
            required_fields = constraints.get("deliverables", {}).get("curriculum_outline_fields", [])
            for rf in required_fields:
                if rf not in sess:
                    schema_ok = False
                    break
            if not schema_ok:
                break
            # Types and values
            sn = sess.get("session_number")
            if not isinstance(sn, int) or not (1 <= sn <= 4):
                schema_ok = False
                break
            session_numbers.append(sn)
            title = sess.get("title")
            objectives = sess.get("objectives")
            activities = sess.get("activities")
            leadership = sess.get("leadership_takeaway")
            safety = sess.get("safety_takeaway")
            materials = sess.get("materials")
            assessment = sess.get("assessment")
            req_topics_cov = sess.get("required_topics_covered")

            if not (isinstance(title, str) and title.strip()):
                schema_ok = False
                break
            if not (isinstance(objectives, list) and 2 <= len(objectives) <= 3 and all(isinstance(o, str) and o.strip() for o in objectives)):
                schema_ok = False
                break
            if not (isinstance(activities, list) and 2 <= len(activities) <= 4 and all(isinstance(a, str) and a.strip() for a in activities)):
                schema_ok = False
                break
            if not (isinstance(leadership, str) and leadership.strip()):
                schema_ok = False
                break
            if not (isinstance(safety, str) and safety.strip()):
                schema_ok = False
                break
            if not (isinstance(materials, list) and all(isinstance(m, str) and m.strip() for m in materials)):
                schema_ok = False
                break
            if not isinstance(assessment, dict):
                schema_ok = False
                break
            exit_q = assessment.get("exit_ticket_questions")
            reflection_prompt = assessment.get("reflection_prompt")
            if not (isinstance(exit_q, list) and len(exit_q) == exit_required and all(isinstance(q, str) and q.strip() for q in exit_q)):
                components_ok = False
            if not (isinstance(reflection_prompt, str) and reflection_prompt.strip()):
                components_ok = False
            # required_topics_covered list
            if not (isinstance(req_topics_cov, list) and all(isinstance(t, str) and t.strip() for t in req_topics_cov)):
                schema_ok = False
                break
            # materials subset
            for m in materials:
                if m not in materials_available:
                    materials_subset_ok = False
            # banned content
            if _curriculum_banned_content_present(sess):
                banned_absent = False
            # coverage mapping
            for t in req_topics_cov:
                if t in coverage_map:
                    coverage_map[t].append(sn)
        # Check session numbers unique and complete
        if sorted(session_numbers) != [1, 2, 3, 4]:
            schema_ok = False

        valid_structure = bool(schema_ok)
        per_session_components_ok = bool(components_ok and schema_ok)
        materials_ok = bool(materials_subset_ok and schema_ok)
        banned_ok = bool(banned_absent and schema_ok)
        # coverage across required topics at least once
        if schema_ok:
            coverage_ok = all(len(sorted(set(coverage_map.get(t, [])))) >= 1 for t in required_topics)

    scores["curriculum_outline_json_valid_structure"] = 1.0 if valid_structure else 0.0
    scores["per_session_components_check"] = 1.0 if per_session_components_ok else 0.0
    scores["materials_within_available"] = 1.0 if materials_ok else 0.0
    scores["banned_content_absent_in_curriculum"] = 1.0 if banned_ok else 0.0
    scores["coverage_all_required_topics_present"] = 1.0 if coverage_ok else 0.0

    # 1b) topic_coverage.csv checks
    topic_cov_path = workspace / "outputs" / "topic_coverage.csv"
    topic_csv = _load_csv_safe(topic_cov_path)
    columns_ok = False
    consistency_ok = False
    if topic_csv is not None:
        # columns must be topic, sessions, coverage_count
        header = topic_csv[0].keys() if topic_csv else []
        columns_ok = list(header) == ["topic", "sessions", "coverage_count"] if isinstance(header, dict) else False
        # Recompute from outline if valid_structure
        if valid_structure and isinstance(outline, list):
            # Build mapping from outline
            recompute: Dict[str, List[int]] = {t: [] for t in required_topics}
            for sess in outline:
                sn = sess.get("session_number")
                for t in sess.get("required_topics_covered", []):
                    if t in recompute and isinstance(sn, int):
                        recompute[t].append(sn)
            # Normalize
            for t in recompute:
                recompute[t] = sorted(set(recompute[t]))
            # Check each required topic row exists and matches
            csv_map = {row.get("topic"): row for row in topic_csv}
            consistency_ok = True
            for t in required_topics:
                if t not in csv_map:
                    consistency_ok = False
                    break
                row = csv_map[t]
                sessions_str = row.get("sessions", "")
                coverage_count_str = row.get("coverage_count", "")
                expected_sessions = ";".join(str(n) for n in recompute[t])
                expected_count = str(len(recompute[t]))
                if sessions_str != expected_sessions or coverage_count_str != expected_count:
                    consistency_ok = False
                    break
    scores["topic_coverage_csv_columns_and_format"] = 1.0 if columns_ok else 0.0
    scores["topic_coverage_csv_consistency"] = 1.0 if consistency_ok else 0.0

    # 2) Meeting summary and action items
    meeting_notes_path = workspace / "input" / "meeting_notes.md"
    meeting_notes_text = _read_text_safe(meeting_notes_path)

    meeting_summary_path = workspace / "outputs" / "meeting_summary.md"
    meeting_summary_text = _read_text_safe(meeting_summary_path)

    headings_order_ok, sections_map, found_order = _find_section_blocks(
        meeting_summary_text,
        ["Decisions", "Open Questions", "Action Items"]
    )
    scores["meeting_summary_headings_order"] = 1.0 if headings_order_ok else 0.0

    # Decisions present
    decisions_from_notes = _extract_decisions_from_notes(meeting_notes_text)
    decisions_present_ok = False
    if headings_order_ok:
        decisions_section = "\n".join(sections_map.get("Decisions", []))
        if decisions_from_notes:
            decisions_present_ok = all(d in decisions_section for d in decisions_from_notes)
        else:
            # No decisions in notes implies trivially true
            decisions_present_ok = True
    scores["meeting_summary_decisions_present"] = 1.0 if decisions_present_ok else 0.0

    # Open questions present
    open_from_notes = _extract_open_questions_from_notes(meeting_notes_text)
    open_present_ok = False
    if headings_order_ok:
        open_section = "\n".join(sections_map.get("Open Questions", []))
        if open_from_notes:
            open_present_ok = all(o in open_section for o in open_from_notes)
        else:
            open_present_ok = True
    scores["meeting_summary_open_questions_present"] = 1.0 if open_present_ok else 0.0

    # Action items CSV and table checks
    expected_actions = _extract_action_items_from_notes(meeting_notes_text)

    # CSV
    action_csv_path = workspace / "outputs" / "action_items.csv"
    action_csv = _load_csv_safe(action_csv_path)
    csv_ok = False
    if action_csv is not None:
        # columns exactly: owner,task,due_date,status,source_line
        if action_csv:
            header_cols = list(action_csv[0].keys())
            if header_cols == ["owner", "task", "due_date", "status", "source_line"]:
                # Build comparison
                csv_items = [{
                    "owner": row.get("owner", ""),
                    "task": row.get("task", ""),
                    "due_date": row.get("due_date", ""),
                    "status": row.get("status", ""),
                    "source_line": int(row.get("source_line", "0")) if str(row.get("source_line", "")).isdigit() else None,
                } for row in action_csv]
                # match all expected
                csv_ok = True
                for exp in expected_actions:
                    match = None
                    for item in csv_items:
                        if (
                            item["owner"] == exp["owner"]
                            and item["task"] == exp["task"]
                            and item["due_date"] == exp["due_date"]
                            and item["status"] == "pending"
                            and item["source_line"] == exp["source_line"]
                        ):
                            match = item
                            break
                    if match is None:
                        csv_ok = False
                        break
                # Ensure no malformed rows
                for item in csv_items:
                    if item["source_line"] is None:
                        csv_ok = False
                        break
    scores["action_items_csv_complete_and_correct"] = 1.0 if csv_ok else 0.0

    # Table in meeting_summary.md
    table_ok = False
    if headings_order_ok and sections_map.get("Action Items") is not None:
        table_rows = _parse_markdown_table(sections_map["Action Items"])
        if table_rows:
            headers = list(table_rows[0].keys())
            # header names should be exactly as required
            # Case-insensitive compare of header names
            normalized_headers = [h.strip().lower() for h in headers]
            if normalized_headers == ["owner", "task", "due_date", "status", "source_line"]:
                # Build items from table rows
                table_items = []
                all_rows_valid = True
                for row in table_rows:
                    try:
                        source_line_val = row.get("source_line", "").strip()
                        source_line_int = int(source_line_val)
                    except Exception:
                        all_rows_valid = False
                        break
                    table_items.append({
                        "owner": row.get("owner", "").strip(),
                        "task": row.get("task", "").strip(),
                        "due_date": row.get("due_date", "").strip(),
                        "status": row.get("status", "").strip().lower(),
                        "source_line": source_line_int,
                    })
                if all_rows_valid:
                    table_ok = True
                    for exp in expected_actions:
                        found = None
                        for item in table_items:
                            if (
                                item["owner"] == exp["owner"]
                                and item["task"] == exp["task"]
                                and item["due_date"] == exp["due_date"]
                                and item["status"] == "pending"
                                and item["source_line"] == exp["source_line"]
                            ):
                                found = item
                                break
                        if found is None:
                            table_ok = False
                            break
    scores["action_items_table_complete_and_correct"] = 1.0 if table_ok else 0.0

    # 3) Rewritten email checks
    email_path = workspace / "outputs" / "rewritten_email.txt"
    email_text = _read_text_safe(email_path)
    email_ok = False
    if email_text is not None:
        # word count 150-180
        words = re.findall(r'\b\w+\b', email_text)
        wc_ok = 150 <= len(words) <= 180
        # includes proposed May dates and preferred room
        dates_ok = all(d in email_text for d in proposed_dates) if proposed_dates else False
        room_ok = (room_pref in email_text) if room_pref else False
        # request confirmation by 2026-04-24
        confirm_ok = ("2026-04-24" in email_text and re.search(r'\bconfirm|confirmation\b', email_text, flags=re.IGNORECASE) is not None)
        # mention background as former Navy pilot who served with Alexander Armatas
        background_ok = (re.search(r'\bformer\b', email_text, flags=re.IGNORECASE) is not None and
                         re.search(r'\bNavy\b', email_text, flags=re.IGNORECASE) is not None and
                         re.search(r'Alexander\s+Armatas', email_text) is not None)
        # refer to attached curriculum outline as "outputs/curriculum_outline.json" and invite feedback
        attach_ok = ('outputs/curriculum_outline.json' in email_text)
        feedback_ok = (re.search(r'\bfeedback\b', email_text, flags=re.IGNORECASE) is not None)
        # Clear, respectful tone heuristic (presence of please or thank)
        tone_ok = (re.search(r'\bplease\b', email_text, flags=re.IGNORECASE) is not None or
                   re.search(r'\bthank\b', email_text, flags=re.IGNORECASE) is not None)

        email_ok = all([wc_ok, dates_ok, room_ok, confirm_ok, background_ok, attach_ok, feedback_ok, tone_ok])
    scores["rewritten_email_content_requirements"] = 1.0 if email_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()