import csv
import json;
import sys
from datetime import datetime, timedelta, date, time
from pathlib import Path
from typing import List, Tuple, Dict, Optional


MEETING_DATE_STR = "2026-04-20"
MEETING_DATE = date(2026, 4, 20)
MEETING_START_TIME = time(14, 0)
MEETING_END_TIME = time(15, 0)
MEETING_START_DT = datetime.combine(MEETING_DATE, MEETING_START_TIME)
TOTAL_MINUTES_LIMIT = 60
ALLOWED_LANGUAGES = {"Old French", "Latin"}

# Expected output headers
SELECTION_HEADERS = [
    "doc_id",
    "title",
    "language",
    "rarity_score",
    "due_date",
    "estimated_minutes",
    "status_from_register",
    "has_draft",
    "derived_purpose",
    "eligible_for_meeting",
    "selected_order",
]
AGENDA_HEADERS = [
    "order",
    "start_time_utc",
    "end_time_utc",
    "doc_id",
    "title",
    "language",
    "purpose",
    "assignee",
]
ACTION_HEADERS = [
    "doc_id",
    "action",
    "assignee",
    "language",
    "due_date",
    "meeting_date",
]


def _read_csv_strict(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not path.exists():
        return None, None
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows_raw = list(reader)
        if not rows_raw:
            return [], []
        header = rows_raw[0]
        # Re-read with DictReader to map rows
        with path.open(newline="", encoding="utf-8") as f:
            dict_reader = csv.DictReader(f)
            rows = [dict(r) for r in dict_reader]
        return header, rows
    except Exception:
        return None, None


def _safe_int(x: str) -> Optional[int]:
    try:
        return int(str(x).strip())
    except Exception:
        return None


def _safe_date(x: str) -> Optional[date]:
    try:
        return datetime.strptime(str(x).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _bool_from_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    val = str(s).strip().lower()
    if val in {"true", "t", "yes", "1"}:
        return True
    if val in {"false", "f", "no", "0"}:
        return False
    return None


def _parse_time_or_datetime(s: str, default_date: date) -> Optional[datetime]:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None
    # Strip Z suffix
    if txt.endswith("Z"):
        txt = txt[:-1]
    # Try datetime formats
    fmts = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(txt, fmt)
        except Exception:
            pass
    # Try time-only formats
    time_fmts = ["%H:%M", "%H:%M:%S"]
    for tf in time_fmts:
        try:
            t = datetime.strptime(txt, tf).time()
            return datetime.combine(default_date, time(t.hour, t.minute))
        except Exception:
            pass
    return None


def _minutes_between(a: datetime, b: datetime) -> int:
    delta = b - a
    return int(round(delta.total_seconds() / 60.0))


def _load_register(workspace: Path) -> Optional[List[Dict[str, str]]]:
    reg_path = workspace / "input" / "docs" / "register.csv"
    header, rows = _read_csv_strict(reg_path)
    if header is None or rows is None:
        return None
    # Validate required columns exist
    required_cols = {"doc_id", "title", "language", "rarity_score", "status", "due_date", "estimated_minutes"}
    if not set(required_cols).issubset(set(header)):
        return None
    return rows


def _load_collaborators(workspace: Path) -> Optional[List[Dict[str, str]]]:
    collab_path = workspace / "input" / "collaborators.csv"
    header, rows = _read_csv_strict(collab_path)
    if header is None or rows is None:
        return None
    required_cols = {"name", "languages", "tz"}
    if not set(required_cols).issubset(set(header)):
        return None
    return rows


def _list_drafts(workspace: Path) -> Optional[set]:
    drafts_dir = workspace / "input" / "drafts"
    if not drafts_dir.exists():
        return set()
    try:
        ids = set()
        for p in drafts_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".txt":
                ids.add(p.stem)
        return ids
    except Exception:
        return None


def _compute_expected(register_rows: List[Dict[str, str]], collaborators: List[Dict[str, str]], draft_ids: set) -> Dict:
    # Build base docs with computed fields
    docs = []
    for r in register_rows:
        doc_id = r.get("doc_id", "").strip()
        title = r.get("title", "").strip()
        language = r.get("language", "").strip()
        rarity_score = _safe_int(r.get("rarity_score", ""))
        status = r.get("status", "").strip()
        due_date = r.get("due_date", "").strip()
        estimated_minutes = _safe_int(r.get("estimated_minutes", ""))
        has_draft = doc_id in draft_ids
        derived_purpose = "Review" if has_draft else "Assign"
        eligible = language in ALLOWED_LANGUAGES
        docs.append({
            "doc_id": doc_id,
            "title": title,
            "language": language,
            "rarity_score": rarity_score,
            "status": status,
            "due_date": due_date,
            "estimated_minutes": estimated_minutes,
            "has_draft": has_draft,
            "derived_purpose": derived_purpose,
            "eligible_for_meeting": eligible,
        })
    # Ranking and selection
    def sort_key(d):
        due = _safe_date(d["due_date"])
        return (-int(d["rarity_score"]), due or date.max, d["doc_id"])
    reviews = [d for d in docs if d["eligible_for_meeting"] and d["has_draft"]]
    assigns = [d for d in docs if d["eligible_for_meeting"] and not d["has_draft"]]
    reviews.sort(key=sort_key)
    assigns.sort(key=sort_key)
    ordered = reviews + assigns
    # Select within 60 minutes
    selected = []
    total = 0
    for d in ordered:
        minutes = int(d["estimated_minutes"])
        if total + minutes <= TOTAL_MINUTES_LIMIT:
            selected.append(d)
            total += minutes
        else:
            continue
    # Compute assignees based on collaborators' language capabilities
    # Prepare eligibility sets
    def eligible_collabs(lang: str) -> List[str]:
        elig = []
        for c in collaborators:
            langs = [s.strip() for s in str(c.get("languages", "")).split(";")]
            if lang in langs:
                elig.append(c.get("name", "").strip())
        return sorted(elig)
    assignment_counts: Dict[str, int] = {}
    assignments: Dict[str, str] = {}
    for d in selected:
        lang = d["language"]
        candidates = eligible_collabs(lang)
        # choose collaborator with fewer assigned items, then alphabetical
        best_name = None
        best_count = None
        for name in candidates:
            count = assignment_counts.get(name, 0)
            if best_count is None or count < best_count or (count == best_count and name < best_name):
                best_name = name
                best_count = count
        if best_name is None:
            best_name = ""  # No eligible collaborator found
        assignments[d["doc_id"]] = best_name
        assignment_counts[best_name] = assignment_counts.get(best_name, 0) + 1
    # Compute schedule times
    schedule = {}
    current = MEETING_START_DT
    for idx, d in enumerate(selected, start=1):
        minutes = int(d["estimated_minutes"])
        start_dt = current
        end_dt = current + timedelta(minutes=minutes)
        schedule[d["doc_id"]] = {
            "order": idx,
            "start": start_dt,
            "end": end_dt,
            "assignee": assignments.get(d["doc_id"], ""),
        }
        current = end_dt
    expected = {
        "docs": docs,
        "selected": selected,
        "assignments": assignments,
        "schedule": schedule,
    }
    return expected


def _match_header_exact(actual: List[str], expected: List[str]) -> bool:
    return actual == expected


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "selection_file_exists": 0.0,
        "selection_header_correct": 0.0,
        "selection_content_correct": 0.0,
        "selection_ranking_and_limit": 0.0,
        "agenda_file_exists": 0.0,
        "agenda_header_correct": 0.0,
        "agenda_schedule_and_assignments_correct": 0.0,
        "action_items_file_exists": 0.0,
        "action_items_header_correct": 0.0,
        "action_items_content_correct": 0.0,
        "meeting_md_exists": 0.0,
        "meeting_md_header_and_attendees": 0.0,
        "meeting_md_agenda_items_present": 0.0,
    }

    # Load inputs
    register_rows = _load_register(workspace)
    collaborators = _load_collaborators(workspace)
    draft_ids = _list_drafts(workspace)

    if register_rows is None or collaborators is None or draft_ids is None:
        # Without inputs we cannot validate outputs; return zeros
        return scores

    expected = _compute_expected(register_rows, collaborators, draft_ids)

    # Build a map for quick lookup from register
    reg_map = {r["doc_id"].strip(): r for r in register_rows}

    # Output paths
    outputs_dir = workspace / "outputs"
    selection_path = outputs_dir / "selection.csv"
    agenda_path = outputs_dir / "agenda_items.csv"
    action_path = outputs_dir / "action_items.csv"
    meeting_md_path = outputs_dir / "meeting_agenda_2026-04-20.md"

    # Validate selection.csv
    sel_header, sel_rows = _read_csv_strict(selection_path)
    if sel_header is not None and sel_rows is not None:
        scores["selection_file_exists"] = 1.0
        if _match_header_exact(sel_header, SELECTION_HEADERS):
            scores["selection_header_correct"] = 1.0
        # Content validation
        try:
            # Must have exactly one row per register doc
            reg_doc_ids = [r["doc_id"].strip() for r in register_rows]
            sel_doc_ids = [r.get("doc_id", "").strip() for r in sel_rows]
            if set(reg_doc_ids) != set(sel_doc_ids) or len(sel_doc_ids) != len(reg_doc_ids):
                raise AssertionError("selection.csv doc_ids do not match register.")
            # Build map
            sel_map = {r["doc_id"].strip(): r for r in sel_rows}
            # Check fields for each doc
            for doc_id in reg_doc_ids:
                reg = reg_map[doc_id]
                row = sel_map.get(doc_id)
                if row is None:
                    raise AssertionError(f"Missing selection row for {doc_id}")
                # Title, language exact
                if (row.get("title", "").strip() != reg.get("title", "").strip() or
                    row.get("language", "").strip() != reg.get("language", "").strip()):
                    raise AssertionError(f"Title/language mismatch for {doc_id}")
                # rarity_score, due_date, estimated_minutes, status_from_register
                if _safe_int(row.get("rarity_score", "")) != _safe_int(reg.get("rarity_score", "")):
                    raise AssertionError(f"rarity_score mismatch for {doc_id}")
                if row.get("due_date", "").strip() != reg.get("due_date", "").strip():
                    raise AssertionError(f"due_date mismatch for {doc_id}")
                if _safe_int(row.get("estimated_minutes", "")) != _safe_int(reg.get("estimated_minutes", "")):
                    raise AssertionError(f"estimated_minutes mismatch for {doc_id}")
                if row.get("status_from_register", "").strip() != reg.get("status", "").strip():
                    raise AssertionError(f"status_from_register mismatch for {doc_id}")
                # has_draft
                has_draft_expected = doc_id in draft_ids
                has_draft_val = _bool_from_str(row.get("has_draft", ""))
                if has_draft_val is None or has_draft_val != has_draft_expected:
                    raise AssertionError(f"has_draft mismatch for {doc_id}")
                # derived_purpose
                derived_expected = "Review" if has_draft_expected else "Assign"
                if row.get("derived_purpose", "").strip() != derived_expected:
                    raise AssertionError(f"derived_purpose mismatch for {doc_id}")
                # eligible_for_meeting
                eligible_expected = reg.get("language", "").strip() in ALLOWED_LANGUAGES
                eligible_val = _bool_from_str(row.get("eligible_for_meeting", ""))
                if eligible_val is None or eligible_val != eligible_expected:
                    raise AssertionError(f"eligible_for_meeting mismatch for {doc_id}")
                # selected_order
                selected_docs = [d["doc_id"] for d in expected["selected"]]
                if doc_id in selected_docs:
                    expected_order = selected_docs.index(doc_id) + 1
                    sel_order_val = _safe_int((row.get("selected_order", "") or "").strip() or "0")
                    # selected_order must be the expected positive int
                    if sel_order_val != expected_order:
                        raise AssertionError(f"selected_order mismatch for {doc_id}")
                else:
                    # If not selected, selected_order should be empty
                    if str(row.get("selected_order", "")).strip() != "":
                        raise AssertionError(f"selected_order should be empty for non-selected {doc_id}")
            scores["selection_content_correct"] = 1.0
            # Ranking and limit check: ensure that selected_order 1..N align with expected and total minutes <= 60
            selected_orders = [(doc_id, sel_map[doc_id].get("selected_order", "").strip()) for doc_id in sel_map]
            # Extract only non-empty
            present_selected = [(doc, _safe_int(ordv)) for doc, ordv in selected_orders if ordv != ""]
            # Sort by order
            present_selected.sort(key=lambda x: x[1] if x[1] is not None else 9999)
            expected_selected_sequence = [d["doc_id"] for d in expected["selected"]]
            actual_sequence = [doc for doc, ordv in present_selected]
            if actual_sequence != expected_selected_sequence:
                raise AssertionError("Selected sequence does not match expected.")
            # Total minutes check
            total_minutes = sum(_safe_int(reg_map[doc]["estimated_minutes"]) or 0 for doc in actual_sequence)
            if total_minutes > TOTAL_MINUTES_LIMIT:
                raise AssertionError("Total selected minutes exceed 60.")
            scores["selection_ranking_and_limit"] = 1.0
        except Exception:
            # Keep zeros for content/ranking if any mismatch or error
            pass

    # Validate agenda_items.csv
    ag_header, ag_rows = _read_csv_strict(agenda_path)
    if ag_header is not None and ag_rows is not None:
        scores["agenda_file_exists"] = 1.0
        if _match_header_exact(ag_header, AGENDA_HEADERS):
            scores["agenda_header_correct"] = 1.0
        try:
            expected_selected = expected["selected"]
            expected_schedule = expected["schedule"]
            expected_assignments = expected["assignments"]
            # Must have exactly the number of selected items
            if len(ag_rows) != len(expected_selected):
                raise AssertionError("Agenda row count mismatch.")
            # Sort rows by order
            try:
                ag_rows_sorted = sorted(ag_rows, key=lambda r: _safe_int(r.get("order", "")) or 0)
            except Exception:
                ag_rows_sorted = ag_rows
            # Build expected sequence by order
            expected_seq = [(i + 1, d["doc_id"]) for i, d in enumerate(expected_selected)]
            # Validate each row
            total_minutes = 0
            last_end = MEETING_START_DT
            for idx, row in enumerate(ag_rows_sorted, start=1):
                # Expected doc_id for this order
                exp_order, exp_doc = expected_seq[idx - 1]
                if _safe_int(row.get("order", "")) != exp_order:
                    raise AssertionError(f"Agenda order mismatch at position {idx}.")
                doc_id = row.get("doc_id", "").strip()
                if doc_id != exp_doc:
                    raise AssertionError(f"Agenda doc_id mismatch at order {idx}.")
                # Title, language, purpose
                reg = reg_map[doc_id]
                if row.get("title", "").strip() != reg.get("title", "").strip():
                    raise AssertionError(f"Agenda title mismatch for {doc_id}.")
                if row.get("language", "").strip() != reg.get("language", "").strip():
                    raise AssertionError(f"Agenda language mismatch for {doc_id}.")
                expected_purpose = "Review" if (doc_id in draft_ids) else "Assign"
                if row.get("purpose", "").strip() != expected_purpose:
                    raise AssertionError(f"Agenda purpose mismatch for {doc_id}.")
                # Assignee
                expected_assignee = expected_assignments.get(doc_id, "")
                if row.get("assignee", "").strip() != expected_assignee:
                    raise AssertionError(f"Agenda assignee mismatch for {doc_id}.")
                # Times
                start_field = row.get("start_time_utc", "")
                end_field = row.get("end_time_utc", "")
                start_dt = _parse_time_or_datetime(start_field, MEETING_DATE)
                end_dt = _parse_time_or_datetime(end_field, MEETING_DATE)
                if start_dt is None or end_dt is None:
                    raise AssertionError(f"Agenda times unparsable for {doc_id}.")
                exp_times = expected_schedule[doc_id]
                exp_start = exp_times["start"]
                exp_end = exp_times["end"]
                # Compare to minute precision
                if start_dt.year != exp_start.year or start_dt.month != exp_start.month or start_dt.day != exp_start.day or start_dt.hour != exp_start.hour or start_dt.minute != exp_start.minute:
                    raise AssertionError(f"Agenda start_time mismatch for {doc_id}.")
                if end_dt.year != exp_end.year or end_dt.month != exp_end.month or end_dt.day != exp_end.day or end_dt.hour != exp_end.hour or end_dt.minute != exp_end.minute:
                    raise AssertionError(f"Agenda end_time mismatch for {doc_id}.")
                # Sequential and within window
                if idx == 1:
                    if start_dt != MEETING_START_DT:
                        raise AssertionError("First agenda item must start at 14:00 UTC.")
                if start_dt != last_end and idx != 1:
                    raise AssertionError("Agenda items must be sequential without gaps or overlaps.")
                dur = _minutes_between(start_dt, end_dt)
                total_minutes += dur
                last_end = end_dt
            if total_minutes > TOTAL_MINUTES_LIMIT:
                raise AssertionError("Agenda total minutes exceed 60.")
            if last_end > datetime.combine(MEETING_DATE, MEETING_END_TIME):
                raise AssertionError("Agenda exceeds meeting window.")
            scores["agenda_schedule_and_assignments_correct"] = 1.0
        except Exception:
            pass

    # Validate action_items.csv
    act_header, act_rows = _read_csv_strict(action_path)
    if act_header is not None and act_rows is not None:
        scores["action_items_file_exists"] = 1.0
        if _match_header_exact(act_header, ACTION_HEADERS):
            scores["action_items_header_correct"] = 1.0
        try:
            expected_selected_ids = [d["doc_id"] for d in expected["selected"]]
            # Must have exactly one row per scheduled doc
            act_ids = [r.get("doc_id", "").strip() for r in act_rows]
            if set(act_ids) != set(expected_selected_ids) or len(act_ids) != len(expected_selected_ids):
                raise AssertionError("Action items doc_id set mismatch.")
            # Validate per row
            act_map = {r["doc_id"].strip(): r for r in act_rows}
            for doc_id in expected_selected_ids:
                r = act_map[doc_id]
                reg = reg_map[doc_id]
                purpose = "Review" if (doc_id in draft_ids) else "Assign"
                expected_action = "Review draft and finalize comments" if purpose == "Review" else "Start translation draft"
                if r.get("action", "").strip() != expected_action:
                    raise AssertionError(f"Action text mismatch for {doc_id}.")
                expected_assignee = expected["assignments"].get(doc_id, "")
                if r.get("assignee", "").strip() != expected_assignee:
                    raise AssertionError(f"Action assignee mismatch for {doc_id}.")
                if r.get("language", "").strip() != reg.get("language", "").strip():
                    raise AssertionError(f"Action language mismatch for {doc_id}.")
                if r.get("due_date", "").strip() != reg.get("due_date", "").strip():
                    raise AssertionError(f"Action due_date mismatch for {doc_id}.")
                if r.get("meeting_date", "").strip() != MEETING_DATE_STR:
                    raise AssertionError(f"Action meeting_date mismatch for {doc_id}.")
            scores["action_items_content_correct"] = 1.0
        except Exception:
            pass

    # Validate meeting agenda markdown
    md_text = _read_text(meeting_md_path)
    if md_text is not None:
        scores["meeting_md_exists"] = 1.0
        try:
            # Header with meeting date/time and one-line purpose: check date and times and UTC presence
            if (MEETING_DATE_STR in md_text and "14:00" in md_text and "15:00" in md_text and "UTC" in md_text):
                # Attendees section listing all collaborators (names only): ensure names appear
                all_names_present = True
                for c in collaborators:
                    name = c.get("name", "").strip()
                    if name and name not in md_text:
                        all_names_present = False
                        break
                if all_names_present:
                    scores["meeting_md_header_and_attendees"] = 1.0
        except Exception:
            pass
        try:
            # Agenda section enumerating the scheduled items; for each expected item, ensure a line contains all required tokens
            lines = [ln.strip() for ln in md_text.splitlines() if ln.strip()]
            ok_all = True
            for d in expected["selected"]:
                doc_id = d["doc_id"]
                title = d["title"]
                language = d["language"]
                purpose = d["derived_purpose"]
                assignee = expected["assignments"].get(doc_id, "")
                sched = expected["schedule"][doc_id]
                start_str = sched["start"].strftime("%H:%M")
                end_str = sched["end"].strftime("%H:%M")
                found = False
                tokens = [start_str, end_str, doc_id, title, language, purpose, assignee]
                for ln in lines:
                    if all(tok in ln for tok in tokens):
                        found = True
                        break
                if not found:
                    ok_all = False
                    break
            if ok_all:
                scores["meeting_md_agenda_items_present"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()