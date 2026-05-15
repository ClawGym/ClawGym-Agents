import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


ALLOWED_INPUT_SUFFIXES = {".csv", ".jsonl", ".yaml", ".yml", ".txt"}


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _count_non_empty_lines(path: Path) -> Optional[int]:
    try:
        count = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    except Exception:
        return None


def _list_input_files(workspace: Path) -> List[Path]:
    input_dir = workspace / "input"
    if not input_dir.exists():
        return []
    files = []
    for p in input_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in ALLOWED_INPUT_SUFFIXES:
            files.append(p)
    return files


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                s = ln.strip()
                if not s:
                    continue
                items.append(json.loads(s))
        return items
    except Exception:
        return None


def _parse_simple_team_yaml(path: Path) -> Optional[Dict[str, str]]:
    """
    Very simple YAML parser for the provided team.yaml structure.
    Expects:
    owners:
      Key: Value
      ...
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    owners: Dict[str, str] = {}
    in_owners = False
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if not in_owners:
            if line.strip().startswith("owners:"):
                in_owners = True
            continue
        else:
            # Expect indented entries like "  Water: Eng. Ouma"
            if not line.startswith(" "):
                # end of owners block
                break
            # Remove leading spaces then split on first colon
            stripped = line.strip()
            if ":" not in stripped:
                continue
            key, val = stripped.split(":", 1)
            owners[key.strip()] = val.strip()
    if not owners:
        return None
    return owners


def _compute_expected_metrics(workspace: Path) -> Optional[Dict[str, Dict[str, float]]]:
    """
    Compute expected ward-level metrics from input files.
    Returns a dict keyed by ward with:
    {
      "ward": str,
      "total_events": int,
      "expected_attendance_sum": int,
      "actual_checkins_sum": int,
      "attendance_rate": float (rounded to 2 decimals),
      "active_pledges": int,
      "completed_pledges": int,
      "high_priority_feedback_count": int
    }
    """
    events_path = workspace / "input" / "events.csv"
    attendance_path = workspace / "input" / "attendance.csv"
    pledges_path = workspace / "input" / "pledges.jsonl"
    feedback_path = workspace / "input" / "feedback.jsonl"

    events = _read_csv_dicts(events_path)
    attendance = _read_csv_dicts(attendance_path)
    pledges = _read_jsonl(pledges_path)
    feedback = _read_jsonl(feedback_path)

    if any(x is None for x in [events, attendance, pledges, feedback]):
        return None

    # Map event_id -> (ward, expected_attendance)
    event_by_id: Dict[str, Tuple[str, int]] = {}
    ward_stats: Dict[str, Dict[str, float]] = {}

    for e in events:
        ward = e.get("ward", "").strip()
        try:
            expected = int(e.get("expected_attendance", "0"))
        except ValueError:
            return None
        event_id = e.get("id", "").strip()
        if not ward or not event_id:
            return None
        event_by_id[event_id] = (ward, expected)
        w = ward_stats.setdefault(
            ward,
            {
                "ward": ward,
                "total_events": 0,
                "expected_attendance_sum": 0,
                "actual_checkins_sum": 0,
                "attendance_rate": 0.0,
                "active_pledges": 0,
                "completed_pledges": 0,
                "high_priority_feedback_count": 0,
            },
        )
        w["total_events"] += 1
        w["expected_attendance_sum"] += expected

    # Actual checkins by joining attendance on event_id
    for a in attendance:
        eid = a.get("event_id", "").strip()
        try:
            count = int(a.get("attendee_count", "0"))
        except ValueError:
            return None
        if eid in event_by_id:
            ward, _ = event_by_id[eid]
            w = ward_stats.setdefault(
                ward,
                {
                    "ward": ward,
                    "total_events": 0,
                    "expected_attendance_sum": 0,
                    "actual_checkins_sum": 0,
                    "attendance_rate": 0.0,
                    "active_pledges": 0,
                    "completed_pledges": 0,
                    "high_priority_feedback_count": 0,
                },
            )
            w["actual_checkins_sum"] += count

    # Pledges counts
    for p in pledges:
        ward = str(p.get("ward", "")).strip()
        status = str(p.get("status", "")).strip().lower()
        if not ward:
            return None
        w = ward_stats.setdefault(
            ward,
            {
                "ward": ward,
                "total_events": 0,
                "expected_attendance_sum": 0,
                "actual_checkins_sum": 0,
                "attendance_rate": 0.0,
                "active_pledges": 0,
                "completed_pledges": 0,
                "high_priority_feedback_count": 0,
            },
        )
        if status == "pending":
            w["active_pledges"] += 1
        elif status == "completed":
            w["completed_pledges"] += 1

    # Feedback high priority
    for fb in feedback:
        ward = str(fb.get("ward", "")).strip()
        priority = str(fb.get("priority", "")).strip()
        if not ward:
            return None
        if priority == "High":
            w = ward_stats.setdefault(
                ward,
                {
                    "ward": ward,
                    "total_events": 0,
                    "expected_attendance_sum": 0,
                    "actual_checkins_sum": 0,
                    "attendance_rate": 0.0,
                    "active_pledges": 0,
                    "completed_pledges": 0,
                    "high_priority_feedback_count": 0,
                },
            )
            w["high_priority_feedback_count"] += 1

    # Attendance rate
    for w in ward_stats.values():
        exp = w["expected_attendance_sum"]
        act = w["actual_checkins_sum"]
        rate = 0.0
        if exp > 0:
            rate = round(float(act) / float(exp) + 1e-8, 2)
        w["attendance_rate"] = rate

    return ward_stats


def _parse_metrics_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    expected_cols = [
        "ward",
        "total_events",
        "expected_attendance_sum",
        "actual_checkins_sum",
        "attendance_rate",
        "active_pledges",
        "completed_pledges",
        "high_priority_feedback_count",
    ]
    # Verify header order strictly
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
    except Exception:
        return None
    if header != expected_cols:
        return None
    return rows


def _extract_section(text: str, header_prefix: str) -> Optional[str]:
    """
    Extract section content that starts with a line beginning with header_prefix (case-insensitive),
    until the next line that starts with a capital letter followed by a dot (e.g., 'B.').
    """
    lines = text.splitlines()
    start_idx = None
    header_lower = header_prefix.lower()
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith(header_lower):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find end index
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        s = lines[j].strip()
        if re.match(r"^[A-Z]\.\s", s):
            end_idx = j
            break
    content = "\n".join(lines[start_idx:end_idx]).strip()
    return content


def _get_high_priority_feedback(workspace: Path) -> Optional[List[Dict[str, str]]]:
    feedback_path = workspace / "input" / "feedback.jsonl"
    feedback = _read_jsonl(feedback_path)
    if feedback is None:
        return None
    highs = []
    for fb in feedback:
        if str(fb.get("priority", "")).strip() == "High":
            highs.append({
                "ward": str(fb.get("ward", "")).strip(),
                "category": str(fb.get("category", "")).strip(),
                "message": str(fb.get("message", "")).strip()
            })
    return highs


def _get_overdue_pledges(workspace: Path) -> Optional[List[Dict[str, str]]]:
    pledges_path = workspace / "input" / "pledges.jsonl"
    pledges = _read_jsonl(pledges_path)
    if pledges is None:
        return None
    overdue = []
    for p in pledges:
        status = str(p.get("status", "")).strip().lower()
        last_update = str(p.get("last_update", "")).strip()
        if status == "pending" and last_update and last_update < "2024-01-01":
            overdue.append({
                "pledge_id": str(p.get("pledge_id", "")).strip(),
                "ward": str(p.get("ward", "")).strip(),
                "theme": str(p.get("theme", "")).strip(),
                "last_update": last_update
            })
    return overdue


def _load_contacts(workspace: Path) -> Optional[List[Dict[str, str]]]:
    contacts_path = workspace / "input" / "contacts.csv"
    return _read_csv_dicts(contacts_path)


def _parse_metrics_rows(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    parsed: Dict[str, Dict[str, float]] = {}
    for r in rows:
        ward = r.get("ward", "").strip()
        try:
            parsed[ward] = {
                "total_events": int(r.get("total_events", "0")),
                "expected_attendance_sum": int(r.get("expected_attendance_sum", "0")),
                "actual_checkins_sum": int(r.get("actual_checkins_sum", "0")),
                "attendance_rate": float(r.get("attendance_rate", "0")),
                "active_pledges": int(r.get("active_pledges", "0")),
                "completed_pledges": int(r.get("completed_pledges", "0")),
                "high_priority_feedback_count": int(r.get("high_priority_feedback_count", "0")),
            }
        except Exception:
            # If parsing fails, leave as empty
            return {}
    return parsed


def _top_high_categories_all(highs: List[Dict[str, str]], top_n: int = 3) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for h in highs:
        cat = h["category"]
        counts[cat] = counts.get(cat, 0) + 1
    # Sort by count desc, then name asc for determinism
    sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return sorted_items[:top_n]


def _top_high_category_by_ward(highs: List[Dict[str, str]]) -> Dict[str, Optional[str]]:
    # For each ward, determine a top category by count (ties: sorted by name)
    by_ward: Dict[str, Dict[str, int]] = {}
    for h in highs:
        by_ward.setdefault(h["ward"], {})
        by_ward[h["ward"]][h["category"]] = by_ward[h["ward"]].get(h["category"], 0) + 1
    result: Dict[str, Optional[str]] = {}
    for ward, cnts in by_ward.items():
        if not cnts:
            result[ward] = None
        else:
            # Choose highest count, then name asc
            best = sorted(cnts.items(), key=lambda x: (-x[1], x[0]))[0][0]
            result[ward] = best
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inspection_file_complete": 0.0,
        "metrics_csv_schema_valid": 0.0,
        "metrics_values_correct": 0.0,
        "compute_metrics_script_present": 0.0,
        "reproducibility_command_recorded": 0.0,
        "status_report_sections_present": 0.0,
        "status_report_totals_correct": 0.0,
        "highlights_top3_with_quotes": 0.0,
        "overdue_pledges_list_correct": 0.0,
        "emails_generated_all_wards": 0.0,
        "emails_content_uses_metrics_and_category": 0.0,
        "meeting_notes_agenda_quality": 0.0,
        "meeting_notes_action_items_quality": 0.0,
        "whatsapp_rewrite_length_and_jargon": 0.0,
    }

    # 1) Inspection file
    inspection_path = workspace / "outputs" / "inspection.txt"
    input_files = _list_input_files(workspace)
    if inspection_path.exists():
        text = _safe_read_text(inspection_path) or ""
        ok = True
        for f in input_files:
            rel = f.relative_to(workspace).as_posix()
            cnt = _count_non_empty_lines(f)
            if cnt is None:
                ok = False
                break
            # find a line that contains the relative path and the exact count as an integer token
            found = False
            for line in text.splitlines():
                if rel in line:
                    # look for the count as a whole number in the line
                    numbers = re.findall(r"\d+", line)
                    if str(cnt) in numbers:
                        found = True
                        break
            if not found:
                ok = False
                break
        # Ensure it at least mentions all files with allowed extensions
        if ok:
            scores["inspection_file_complete"] = 1.0

    # 2) Metrics computation and script + reproducibility
    metrics_path = workspace / "outputs" / "metrics.csv"
    metrics_rows = None
    if metrics_path.exists():
        rows = _parse_metrics_csv(metrics_path)
        if rows is not None:
            scores["metrics_csv_schema_valid"] = 1.0
            metrics_rows = rows

    expected = _compute_expected_metrics(workspace)
    if metrics_rows is not None and expected is not None:
        parsed_metrics = _parse_metrics_rows(metrics_rows)
        # Verify wards and values
        all_good = True
        # Must contain exactly the wards present in expected (or at least those wards)
        for ward, expvals in expected.items():
            if ward not in parsed_metrics:
                all_good = False
                break
            got = parsed_metrics[ward]
            # Compare all fields with exact numbers and attendance_rate with 2 decimals
            fields = [
                "total_events",
                "expected_attendance_sum",
                "actual_checkins_sum",
                "active_pledges",
                "completed_pledges",
                "high_priority_feedback_count",
            ]
            for k in fields:
                if int(got.get(k, -999999)) != int(expvals[k]):
                    all_good = False
                    break
            if not all_good:
                break
            # Check attendance rate with 2 decimals tolerance
            if round(float(got.get("attendance_rate", -1.0)), 2) != round(float(expvals["attendance_rate"]), 2):
                all_good = False
                break
        if all_good:
            scores["metrics_values_correct"] = 1.0

    # Script presence
    script_path = workspace / "scripts" / "compute_metrics.py"
    if script_path.exists() and script_path.is_file():
        scores["compute_metrics_script_present"] = 1.0

    # Reproducibility command recorded
    repro_path = workspace / "outputs" / "REPRODUCIBILITY.txt"
    if repro_path.exists():
        repro_text = _safe_read_text(repro_path) or ""
        # Check that a command references the script and outputs/metrics.csv
        if ("scripts/compute_metrics.py" in repro_text) and ("outputs/metrics.csv" in repro_text):
            # Ideally includes 'python' or 'python3'
            if ("python " in repro_text) or ("python3 " in repro_text):
                scores["reproducibility_command_recorded"] = 1.0

    # 3) Status report sections and content
    status_path = workspace / "outputs" / "status_report.md"
    if status_path.exists():
        stext = _safe_read_text(status_path) or ""
        has_a = bool(re.search(r"^A\.\s*Summary", stext, flags=re.IGNORECASE | re.MULTILINE))
        has_b = bool(re.search(r"^B\.\s*Highlights", stext, flags=re.IGNORECASE | re.MULTILINE))
        has_c = bool(re.search(r"^C\.\s*Overdue", stext, flags=re.IGNORECASE | re.MULTILINE))
        if has_a and has_b and has_c:
            scores["status_report_sections_present"] = 1.0

        # Totals correct grounded in metrics.csv
        if metrics_rows is not None:
            totals = {
                "total_events": 0,
                "expected_attendance_sum": 0,
                "actual_checkins_sum": 0,
                "active_pledges": 0,
                "completed_pledges": 0,
                "high_priority_feedback_count": 0,
            }
            for r in metrics_rows:
                try:
                    totals["total_events"] += int(r["total_events"])
                    totals["expected_attendance_sum"] += int(r["expected_attendance_sum"])
                    totals["actual_checkins_sum"] += int(r["actual_checkins_sum"])
                    totals["active_pledges"] += int(r["active_pledges"])
                    totals["completed_pledges"] += int(r["completed_pledges"])
                    totals["high_priority_feedback_count"] += int(r["high_priority_feedback_count"])
                except Exception:
                    totals = None
                    break
            if totals is not None:
                a_section = _extract_section(stext, "A. Summary")
                if a_section:
                    # Check that each total number appears in the summary section
                    # We require at least the expected vs actual attendance and pledges and high-priority totals
                    required_numbers = [
                        totals["total_events"],
                        totals["expected_attendance_sum"],
                        totals["actual_checkins_sum"],
                        totals["active_pledges"],
                        totals["completed_pledges"],
                        totals["high_priority_feedback_count"],
                    ]
                    found_all = True
                    for num in required_numbers:
                        # look for the number as a standalone or within delimiters
                        if re.search(rf"\b{re.escape(str(num))}\b", a_section) is None:
                            found_all = False
                            break
                    if found_all:
                        scores["status_report_totals_correct"] = 1.0

        # Highlights: top three High categories with example message excerpt in quotes
        highs = _get_high_priority_feedback(workspace)
        if highs is not None:
            top3 = _top_high_categories_all(highs, top_n=3)
            categories_set = set([c for c, _ in top3])
            b_section = _extract_section(stext, "B. Highlights")
            if b_section:
                bullets = [ln.strip() for ln in b_section.splitlines() if ln.strip().startswith(("-", "*"))]
                # Accept at least 3 bullets, each containing a category name and a quoted excerpt
                valid_count = 0
                for b in bullets:
                    has_quote = '"' in b or '“' in b or '”' in b
                    has_cat = any(cat in b for cat in categories_set)
                    if has_quote and has_cat:
                        valid_count += 1
                if valid_count >= 3:
                    scores["highlights_top3_with_quotes"] = 1.0

        # Overdue pledges list
        overdue = _get_overdue_pledges(workspace)
        if overdue is not None:
            c_section = _extract_section(stext, "C. Overdue")
            if c_section:
                all_present = True
                for od in overdue:
                    # Each item should include pledge_id, ward, theme, last_update
                    pid, ward, theme, lu = od["pledge_id"], od["ward"], od["theme"], od["last_update"]
                    for token in [pid, ward, theme, lu]:
                        if re.search(rf"\b{re.escape(token)}\b", c_section) is None:
                            all_present = False
                            break
                    if not all_present:
                        break
                # And should not include non-overdue pending pledge IDs incorrectly
                pledges_all = _read_jsonl(workspace / "input" / "pledges.jsonl") or []
                non_overdue_pending = [
                    p for p in pledges_all
                    if str(p.get("status", "")).strip().lower() == "pending"
                    and str(p.get("last_update", "")).strip() >= "2024-01-01"
                ]
                wrongly_included = False
                for p in non_overdue_pending:
                    pid = str(p.get("pledge_id", "")).strip()
                    if pid and re.search(rf"\b{re.escape(pid)}\b", c_section):
                        wrongly_included = True
                        break
                if all_present and not wrongly_included:
                    scores["overdue_pledges_list_correct"] = 1.0

    # 4) Ward emails
    contacts = _load_contacts(workspace) or []
    emails_dir = workspace / "outputs" / "emails"
    metrics_ok = (metrics_rows is not None)
    highs_all = _get_high_priority_feedback(workspace) or []
    top_by_ward = _top_high_category_by_ward(highs_all)
    emails_exist = True
    emails_content_ok = True
    metrics_by_ward = _parse_metrics_rows(metrics_rows) if metrics_rows else {}
    for c in contacts:
        ward = c.get("ward", "").strip()
        name = c.get("name", "").strip()
        email_file = emails_dir / f"{ward}.txt"
        if not email_file.exists():
            emails_exist = False
            continue
        etext = _safe_read_text(email_file) or ""
        lines = etext.splitlines()
        if not lines:
            emails_exist = False
            emails_content_ok = False
            continue
        subj_expected = f"Subject: Ward Update - {ward} Metrics and Actions"
        if lines[0].strip() != subj_expected:
            emails_content_ok = False
        # Greeting
        if len(lines) < 2 or not lines[1].strip().startswith(f"Dear {name},"):
            emails_content_ok = False
        # Content checks: metrics references
        if metrics_ok and ward in metrics_by_ward:
            m = metrics_by_ward[ward]
            # Look for total_events, attendance_rate (as decimal with 2 decimals), and pending active pledges
            if re.search(rf"\b{m['total_events']}\b", etext) is None:
                emails_content_ok = False
            # attendance_rate string with 2 decimals
            ar_s = f"{m['attendance_rate']:.2f}"
            if ar_s not in etext:
                emails_content_ok = False
            if re.search(rf"\b{m['active_pledges']}\b", etext) is None:
                emails_content_ok = False
        # Category presence or fallback phrase
        top_cat = top_by_ward.get(ward)
        if top_cat:
            if top_cat not in etext:
                emails_content_ok = False
        else:
            if "No High priority items this cycle" not in etext:
                emails_content_ok = False

    if contacts and emails_exist:
        scores["emails_generated_all_wards"] = 1.0
    if contacts and emails_content_ok and emails_exist:
        scores["emails_content_uses_metrics_and_category"] = 1.0

    # 5) Meeting notes and action items
    notes_path = workspace / "outputs" / "meeting_notes.md"
    team_map = _parse_simple_team_yaml(workspace / "input" / "team.yaml") or {}
    if notes_path.exists():
        ntext = _safe_read_text(notes_path) or ""
        agenda_sec = _extract_section(ntext, "A. Agenda")
        action_sec = _extract_section(ntext, "B. Action items")
        agenda_ok = False
        action_ok = False
        if agenda_sec:
            agenda_bullets = [ln.strip() for ln in agenda_sec.splitlines() if ln.strip().startswith(("-", "*"))]
            # At least three bullets, referencing highlights (categories) and overdue pledges
            highs_list = _get_high_priority_feedback(workspace) or []
            high_cats = set([h["category"] for h in highs_list])
            overdue_list = _get_overdue_pledges(workspace) or []
            overdue_ids = set([o["pledge_id"] for o in overdue_list])
            if len(agenda_bullets) >= 3:
                # Require at least one mention of a High category and at least one overdue pledge id across bullets
                mentions_cat = any(any(cat in b for cat in high_cats) for b in agenda_bullets)
                mentions_od = any(any(pid in b for pid in overdue_ids) for b in agenda_bullets)
                if mentions_cat and mentions_od:
                    agenda_ok = True
        if action_sec:
            action_bullets = [ln.strip() for ln in action_sec.splitlines() if ln.strip().startswith(("-", "*"))]
            if len(action_bullets) >= 5:
                valid_all = True
                # Build mapping for pledge theme owners
                pledges = _read_jsonl(workspace / "input" / "pledges.jsonl") or []
                pledge_by_id = {str(p.get("pledge_id", "")).strip(): p for p in pledges}
                mapping_values = set(team_map.values())
                mapping_keys = set(team_map.keys())
                for b in action_bullets:
                    # Must include "Owner: <name> | Source: <id or category>"
                    m = re.search(r"Owner:\s*(.+?)\s*\|\s*Source:\s*(.+)$", b)
                    if not m:
                        valid_all = False
                        break
                    owner = m.group(1).strip()
                    source = m.group(2).strip()
                    # Owner must be from team.yaml values
                    if owner not in mapping_values:
                        valid_all = False
                        break
                    # If source is a pledge id, owner must match pledge theme owner
                    if source in pledge_by_id:
                        theme = str(pledge_by_id[source].get("theme", "")).strip()
                        expected_owner = team_map.get(theme)
                        if expected_owner is None or expected_owner != owner:
                            valid_all = False
                            break
                    else:
                        # Treat source as category; if it exists in mapping keys, enforce owner equals mapped owner
                        if source in mapping_keys:
                            if team_map.get(source) != owner:
                                valid_all = False
                                break
                        else:
                            # Category not in mapping: accept any mapped owner
                            pass
                if valid_all:
                    action_ok = True
        if agenda_ok:
            scores["meeting_notes_agenda_quality"] = 1.0
        if action_ok:
            scores["meeting_notes_action_items_quality"] = 1.0

    # 6) WhatsApp rewrite constraints
    wa_src_path = workspace / "input" / "drafts" / "whatsapp_update.txt"
    wa_out_path = workspace / "outputs" / "whatsapp_update_rewrite.txt"
    if wa_out_path.exists():
        wtext = _safe_read_text(wa_out_path) or ""
        # <=100 words
        words = re.findall(r"\b\w+\b", wtext)
        length_ok = len(words) <= 100 and len(words) > 0
        # Avoid some jargon words and exclamation points for neutrality
        jargon_terms = {"crunch", "crunching", "tight", "actionable", "jargon", "!"}
        jargon_ok = True
        for jt in jargon_terms:
            if jt in wtext.lower():
                jargon_ok = False
                break
        if length_ok and jargon_ok:
            scores["whatsapp_rewrite_length_and_jargon"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()