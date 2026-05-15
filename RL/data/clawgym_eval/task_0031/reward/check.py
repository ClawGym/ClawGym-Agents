import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return rows, list(reader.fieldnames)
    except Exception:
        return None, None


def _load_tsv_dicts_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return rows, list(reader.fieldnames)
    except Exception:
        return None, None


def _parse_meeting_notes(text: str) -> Optional[Dict[str, Any]]:
    date = None
    decisions: List[str] = []
    actions: List[Dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("MEETING_DATE:"):
            # format: MEETING_DATE: YYYY-MM-DD
            date_val = line.split("MEETING_DATE:", 1)[1].strip()
            date = date_val
        elif line.startswith("DECISION:"):
            decisions.append(line.split("DECISION:", 1)[1].strip())
        elif line.startswith("ACTION:"):
            # Expect format: ACTION: id=A2 owner=Alex due=2026-04-18 related_task_id=1018 text=Prototype ...
            m = re.match(
                r"^ACTION:\s*id=([^ ]+)\s+owner=([^ ]+)\s+due=([0-9]{4}-[0-9]{2}-[0-9]{2})\s+related_task_id=([^ ]+)\s+text=(.+)$",
                line,
            )
            if not m:
                return None
            actions.append(
                {
                    "id": m.group(1),
                    "owner": m.group(2),
                    "due": m.group(3),
                    "related_task_id": m.group(4),
                    "text": m.group(5),
                }
            )
    if date is None:
        return None
    return {"date": date, "decisions": decisions, "actions": actions}


def _compute_expected_ranked_followups(backlog_rows: List[Dict[str, str]], input_columns: List[str]) -> List[Dict[str, str]]:
    # Filter: tag == "eigensolver" AND status == "open"
    filtered: List[Dict[str, str]] = [
        r for r in backlog_rows if r.get("tag", "") == "eigensolver" and r.get("status", "") == "open"
    ]

    def to_int(x: str) -> int:
        try:
            return int(x)
        except Exception:
            return 0

    # Sort by: priority asc, impact desc, effort asc, id asc
    sorted_rows = sorted(
        filtered,
        key=lambda r: (to_int(r.get("priority", "0")), -to_int(r.get("impact", "0")), to_int(r.get("effort", "0")), to_int(r.get("id", "0"))),
    )
    # Append rank column
    expected: List[Dict[str, str]] = []
    rank = 1
    for r in sorted_rows:
        out_row = {k: r.get(k, "") for k in input_columns}
        out_row["rank"] = str(rank)
        expected.append(out_row)
        rank += 1
    return expected


def _find_section_lines(lines: List[str], section_name: str) -> Optional[List[str]]:
    # Identify a section where a heading line equals the section name (ignoring leading # and whitespace)
    def norm_heading(s: str) -> str:
        return s.lstrip(" #\t").rstrip().strip()

    start_idx = None
    for i, ln in enumerate(lines):
        if norm_heading(ln) == section_name:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find next heading (any line whose normalized heading equals a known section name among Decisions, Action items, Notes)
    # We'll consider any line that after stripping leading '#' and whitespace matches 'Decisions', 'Action items', or 'Notes'
    known_sections = {"Decisions", "Action items", "Notes"}
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if norm_heading(lines[j]) in known_sections:
            end_idx = j
            break
    return lines[start_idx:end_idx]


def _contains_all_tokens_in_line(line: str, tokens: List[str]) -> bool:
    s = line
    return all(tok in s for tok in tokens)


def _get_bullet_lines(text: str) -> List[str]:
    bullets = []
    for ln in text.splitlines():
        stripped = ln.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped)
    return bullets


def _compare_csv_rows(actual_rows: List[Dict[str, str]], expected_rows: List[Dict[str, str]], columns: List[str]) -> bool:
    if len(actual_rows) != len(expected_rows):
        return False
    for i in range(len(expected_rows)):
        exp = expected_rows[i]
        act = actual_rows[i]
        for c in columns:
            if act.get(c, "") != exp.get(c, ""):
                return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "meeting_minutes_sections_present": 0.0,
        "meeting_minutes_decisions_verbatim": 0.0,
        "meeting_minutes_action_items_coverage": 0.0,
        "meeting_minutes_notes_section_omitted_when_no_mismatch": 0.0,
        "ranked_followups_csv_correct": 0.0,
        "status_update_includes_date_and_decisions_recapped": 0.0,
        "status_update_top_3_bullets_correct": 0.0,
        "status_update_open_eigensolver_count_included": 0.0,
        "reminders_tsv_header_and_rows_correct": 0.0,
    }

    # Load inputs
    meeting_notes_path = workspace / "input" / "meeting_raw_notes.txt"
    backlog_csv_path = workspace / "input" / "project_backlog.csv"

    meeting_notes_text = _read_text_safe(meeting_notes_path)
    backlog_rows, backlog_cols = _load_csv_dicts_safe(backlog_csv_path)

    # Parse meeting notes
    parsed_notes = _parse_meeting_notes(meeting_notes_text) if meeting_notes_text is not None else None

    # Compute expected components if possible
    decisions_expected: List[str] = []
    actions_expected: List[Dict[str, str]] = []
    meeting_date_expected: Optional[str] = None
    if parsed_notes is not None:
        decisions_expected = parsed_notes["decisions"]
        actions_expected = parsed_notes["actions"]
        meeting_date_expected = parsed_notes["date"]

    # Compute owner mismatches between ACTION owner and backlog owner by related_task_id
    mismatches: List[Tuple[str, str, str, str]] = []  # list of (action_id, action_owner, task_id, task_owner)
    backlog_owner_by_id: Dict[str, str] = {}
    if backlog_rows is not None:
        for r in backlog_rows:
            backlog_owner_by_id[str(r.get("id", ""))] = r.get("owner", "")
    if actions_expected and backlog_rows is not None:
        for a in actions_expected:
            task_id = a.get("related_task_id", "")
            action_owner = a.get("owner", "")
            task_owner = backlog_owner_by_id.get(str(task_id), "")
            if task_owner and action_owner and task_owner != action_owner:
                mismatches.append((a.get("id", ""), action_owner, task_id, task_owner))

    # 1) Grade meeting_minutes.md
    meeting_minutes_path = workspace / "out" / "meeting_minutes.md"
    meeting_minutes_text = _read_text_safe(meeting_minutes_path)
    if meeting_minutes_text is not None:
        lines = meeting_minutes_text.splitlines()
        decisions_section = _find_section_lines(lines, "Decisions")
        action_items_section = _find_section_lines(lines, "Action items")
        # Sections present
        if decisions_section is not None and action_items_section is not None:
            scores["meeting_minutes_sections_present"] = 1.0
        # Decisions verbatim inclusion (decisions appear as substrings in the Decisions section)
        if decisions_section is not None and decisions_expected:
            decisions_text = "\n".join(decisions_section)
            if all(dec in decisions_text for dec in decisions_expected):
                scores["meeting_minutes_decisions_verbatim"] = 1.0
        # Action items coverage
        if action_items_section is not None and actions_expected:
            ai_lines = action_items_section
            ai_text = "\n".join(ai_lines)
            all_ok = True
            for a in actions_expected:
                # Find a line that contains the id and owner and related_task_id together
                id_val = a.get("id", "")
                owner_val = a.get("owner", "")
                rtid_val = a.get("related_task_id", "")
                due_val = a.get("due", "")
                text_val = a.get("text", "")
                found_group_line = False
                for ln in ai_lines:
                    if id_val in ln and owner_val in ln and rtid_val in ln:
                        found_group_line = True
                        break
                if not found_group_line:
                    all_ok = False
                    break
                # Ensure due date appears somewhere in the section
                if due_val not in ai_text:
                    all_ok = False
                    break
                # Ensure text appears somewhere in the section
                if text_val not in ai_text:
                    all_ok = False
                    break
            if all_ok:
                scores["meeting_minutes_action_items_coverage"] = 1.0
        # Notes subsection handling
        # If mismatches exist, we might expect a Notes subsection, but the prompt for our data has no mismatches
        # We enforce: when no mismatches, there should be no "Notes" heading present
        if mismatches == []:
            # detect any heading line named Notes
            has_notes_heading = False
            for ln in lines:
                if ln.lstrip(" #\t").rstrip().strip() == "Notes":
                    has_notes_heading = True
                    break
            if not has_notes_heading:
                scores["meeting_minutes_notes_section_omitted_when_no_mismatch"] = 1.0

    # 2) Grade ranked_followups.csv
    ranked_path = workspace / "out" / "ranked_followups.csv"
    ranked_rows, ranked_cols = _load_csv_dicts_safe(ranked_path)
    # Need backlog to compute expected and its header
    if backlog_rows is not None and backlog_cols is not None and ranked_rows is not None and ranked_cols is not None:
        expected_rows = _compute_expected_ranked_followups(backlog_rows, backlog_cols)
        expected_cols = backlog_cols + ["rank"]
        if ranked_cols == expected_cols:
            # Compare all rows and order
            if _compare_csv_rows(ranked_rows, expected_rows, expected_cols):
                scores["ranked_followups_csv_correct"] = 1.0

    # 3) Grade status_update.md
    status_update_path = workspace / "out" / "status_update.md"
    status_update_text = _read_text_safe(status_update_path)
    if status_update_text is not None and backlog_rows is not None and backlog_cols is not None and meeting_date_expected is not None:
        # Compute expected top 3 and count
        expected_ranked = _compute_expected_ranked_followups(backlog_rows, backlog_cols)
        expected_top3 = expected_ranked[:3]
        count_open_eigensolver = len(expected_ranked)

        # (a) meeting date present and (b) one-sentence recap of decisions: check for key phrases
        has_date = meeting_date_expected in status_update_text
        # Recap: look for "block-Lanczos" and also CSR with 64-bit indices key phrases
        lc_text = status_update_text
        has_block_lanczos = "block-Lanczos" in lc_text or "block-lanczos" in lc_text
        has_csr_64 = ("CSR with 64-bit indices" in lc_text) or (("CSR" in lc_text) and ("64-bit" in lc_text) and ("indices" in lc_text))
        if has_date and has_block_lanczos and has_csr_64:
            scores["status_update_includes_date_and_decisions_recapped"] = 1.0

        # (c) bullet list of top 3 items with id, title, owner, and deadline (or "no deadline")
        bullets = _get_bullet_lines(status_update_text)
        ok_bullets = True
        if len(bullets) >= 3:
            for item in expected_top3:
                item_id = item.get("id", "")
                item_title = ""
                item_owner = ""
                item_deadline = ""
                # Find corresponding row in backlog by id to get title & owner & deadline
                for r in backlog_rows:
                    if r.get("id", "") == item_id:
                        item_title = r.get("title", "")
                        item_owner = r.get("owner", "")
                        item_deadline = r.get("deadline", "")
                        break
                # Find a bullet that contains id, title, owner, and deadline or "no deadline"
                found = False
                for bl in bullets:
                    if (item_id in bl) and (item_title in bl) and (item_owner in bl):
                        if item_deadline:
                            if item_deadline in bl:
                                found = True
                                break
                        else:
                            # no deadline
                            if "no deadline" in bl.lower():
                                found = True
                                break
                if not found:
                    ok_bullets = False
                    break
        else:
            ok_bullets = False
        if ok_bullets:
            scores["status_update_top_3_bullets_correct"] = 1.0

        # (d) count of open eigensolver items
        count_ok = False
        for ln in status_update_text.splitlines():
            lnl = ln.lower()
            if "open" in lnl and "eigensolver" in lnl and str(count_open_eigensolver) in ln:
                count_ok = True
                break
        if count_ok:
            scores["status_update_open_eigensolver_count_included"] = 1.0

    # 4) Grade reminders.tsv
    reminders_path = workspace / "out" / "reminders.tsv"
    reminders_rows, reminders_cols = _load_tsv_dicts_safe(reminders_path)
    if reminders_rows is not None and reminders_cols is not None and parsed_notes is not None and backlog_rows is not None and backlog_cols is not None:
        expected_header = ["due_date", "owner", "message", "related_task_id"]
        # Build expected rows
        expected: List[Dict[str, str]] = []
        # From ACTION lines
        for a in actions_expected:
            expected.append(
                {
                    "due_date": a.get("due", ""),
                    "owner": a.get("owner", ""),
                    "message": a.get("text", ""),
                    "related_task_id": a.get("related_task_id", ""),
                }
            )
        # From top 3 items in ranked_followups with non-empty deadline
        expected_ranked = _compute_expected_ranked_followups(backlog_rows, backlog_cols)
        top3 = expected_ranked[:3]
        # Map id to title for message, and owner for owner, and deadline for due_date
        idx_to_row = {r.get("id", ""): r for r in backlog_rows}
        for item in top3:
            tid = item.get("id", "")
            src = idx_to_row.get(tid, {})
            deadline = src.get("deadline", "")
            if deadline:
                expected.append(
                    {
                        "due_date": deadline,
                        "owner": src.get("owner", ""),
                        "message": f"Follow up on task {tid}: {src.get('title', '')}",
                        "related_task_id": tid,
                    }
                )
        # Compare header and rows (order-insensitive rows)
        header_ok = reminders_cols == expected_header
        rows_ok = False
        if header_ok:
            # Normalize rows to tuples for set comparison
            def row_to_tuple(r: Dict[str, str]) -> Tuple[str, str, str, str]:
                return (r.get("due_date", ""), r.get("owner", ""), r.get("message", ""), r.get("related_task_id", ""))

            actual_set = [row_to_tuple(r) for r in reminders_rows]
            expected_set = [row_to_tuple(r) for r in expected]
            # Exact multiset equality
            actual_sorted = sorted(actual_set)
            expected_sorted = sorted(expected_set)
            rows_ok = (actual_sorted == expected_sorted)
        if header_ok and rows_ok:
            scores["reminders_tsv_header_and_rows_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()