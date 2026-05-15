import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _parse_recipients_yaml(path: Path) -> Optional[List[str]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    emails = []
    lines = text.splitlines()
    in_to = False
    base_indent = None
    for line in lines:
        if not in_to:
            if re.match(r"^\s*to\s*:\s*$", line):
                in_to = True
                base_indent = len(line) - len(line.lstrip(" "))
            continue
        else:
            if len(line.strip()) == 0:
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= (base_indent if base_indent is not None else 0):
                in_to = False
                base_indent = None
                continue
            m = re.search(r"email\s*:\s*(.+)$", line.strip())
            if m:
                email = m.group(1).strip()
                if email.startswith('"') and email.endswith('"'):
                    email = email[1:-1]
                if email.startswith("'") and email.endswith("'"):
                    email = email[1:-1]
                emails.append(email)
    return emails


def _parse_agenda_md(path: Path) -> Optional[Dict[str, object]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    meeting = {
        "title": None,
        "date_time": None,
        "participants": [],
        "agenda_items": [],
        "actions": [],
        "decisions": [],
    }
    for ln in lines:
        if ln.strip().startswith("# "):
            meeting["title"] = ln.strip().lstrip("# ").strip()
            break
    for ln in lines:
        m = re.match(r"^\s*Date\s*:\s*(.+)\s*$", ln)
        if m:
            meeting["date_time"] = m.group(1).strip()
            break
    for ln in lines:
        m = re.match(r"^\s*Participants\s*:\s*(.+)\s*$", ln)
        if m:
            plist = [p.strip() for p in m.group(1).split(",") if p.strip()]
            meeting["participants"] = plist
            break
    in_agenda = False
    for ln in lines:
        if not in_agenda:
            if re.match(r"^\s*Agenda\s*:\s*$", ln):
                in_agenda = True
            continue
        else:
            m = re.match(r"^\s*-\s+(.*)$", ln)
            if m:
                item = m.group(1).strip()
                meeting["agenda_items"].append(item)
                if "[DECISION]" in item:
                    dec_m = re.search(r"\[DECISION\]\s*(.*)$", item)
                    if dec_m:
                        decision_text = dec_m.group(1).strip()
                        if decision_text:
                            meeting["decisions"].append(decision_text)
                if "[ACTION]" in item:
                    assign_m = re.search(r"Assign\s*:\s*([^;]+)", item)
                    task_m = re.search(r"Task\s*:\s*([^;]+)", item)
                    due_m = re.search(r"Due\s*:\s*([0-9\-]+)", item)
                    action = {
                        "assignee": assign_m.group(1).strip() if assign_m else None,
                        "task": task_m.group(1).strip() if task_m else None,
                        "due": due_m.group(1).strip() if due_m else None,
                    }
                    meeting["actions"].append(action)
            else:
                continue
    return meeting


def _clean_agenda_item_for_recap(item: str) -> str:
    cut = re.split(r"\s*\[(ACTION|DECISION)\]\s*", item, maxsplit=1)[0].strip()
    return cut


def _extract_section_lines(text: str, header_name: str) -> List[str]:
    lines = text.splitlines()
    start_idx = None
    header_pattern = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
    for i, ln in enumerate(lines):
        m = header_pattern.match(ln)
        if m:
            name = m.group(1).strip().lower()
            if name == header_name.strip().lower():
                start_idx = i + 1
                break
    if start_idx is None:
        for i, ln in enumerate(lines):
            if ln.strip().lower() == header_name.strip().lower():
                start_idx = i + 1
                break
    if start_idx is None:
        return []
    section = []
    for j in range(start_idx, len(lines)):
        if header_pattern.match(lines[j]):
            break
        section.append(lines[j])
    return section


def _tokenize_ids(text: str) -> List[str]:
    return re.findall(r"\b[A-Z]{1,2}\d{3}\b", text)


def _get_weekly_stats(reading_log: List[Dict[str, str]]) -> Optional[Dict[str, object]]:
    dates = []
    for r in reading_log:
        d = _parse_date(r.get("date", "").strip())
        if d:
            dates.append(d)
    if not dates:
        return None
    end_date = max(dates).date()
    start_date = end_date - timedelta(days=6)
    completed = []
    for r in reading_log:
        d = _parse_date(r.get("date", "").strip())
        if not d:
            continue
        rd = d.date()
        status = (r.get("status") or "").strip()
        if status == "Completed" and start_date <= rd <= end_date:
            try:
                minutes = int(str(r.get("minutes", "")).strip())
            except Exception:
                continue
            completed.append({
                "date": rd.isoformat(),
                "id": (r.get("id") or "").strip(),
                "title": (r.get("title") or "").strip(),
                "universe": (r.get("universe") or "").strip(),
                "minutes": minutes
            })
    total_completed = len(completed)
    total_minutes = sum(x["minutes"] for x in completed)
    avg_minutes = round(total_minutes / total_completed, 1) if total_completed > 0 else 0.0
    uni_counts: Dict[str, Dict[str, float]] = {}
    for x in completed:
        u = x["universe"]
        if u not in uni_counts:
            uni_counts[u] = {"completed": 0, "minutes": 0}
        uni_counts[u]["completed"] += 1
        uni_counts[u]["minutes"] += x["minutes"]
    uni_stats = []
    for u, vals in uni_counts.items():
        c = int(vals["completed"])
        m = int(vals["minutes"])
        avg_u = round(m / c, 1) if c > 0 else 0.0
        uni_stats.append({"universe": u, "completed_items": c, "total_minutes": m, "avg_minutes": avg_u})
    top_sorted = sorted(completed, key=lambda x: (-x["minutes"], x["id"]))
    top3 = top_sorted[:3]
    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "completed": completed,
        "total_completed": total_completed,
        "total_minutes": total_minutes,
        "avg_minutes": avg_minutes,
        "universe_stats": uni_stats,
        "top3": top3
    }


def _compute_backlog_completion(backlog: List[Dict[str, str]]) -> Optional[Tuple[int, int, float]]:
    try:
        total = len(backlog)
        completed = sum(1 for r in backlog if (r.get("status") or "").strip() == "Completed")
        pct = (completed / total * 100.0) if total > 0 else 0.0
        return completed, total, pct
    except Exception:
        return None


def _parse_csv_numeric_row(row: Dict[str, str], int_fields: List[str], float_fields: List[str]) -> Optional[Dict[str, object]]:
    out = {}
    try:
        out.update(row)
        for f in int_fields:
            out[f] = int(row[f])
        for f in float_fields:
            out[f] = float(row[f])
        return out
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    reading_log_path = workspace / "input" / "data" / "reading_log.csv"
    backlog_path = workspace / "input" / "data" / "backlog.csv"
    agenda_path = workspace / "input" / "meetings" / "agenda.md"
    recipients_path = workspace / "input" / "messaging" / "recipients.yaml"

    reading_log = _load_csv_dicts(reading_log_path)
    backlog = _load_csv_dicts(backlog_path)
    agenda = _parse_agenda_md(agenda_path) if agenda_path.exists() else None
    recipients = _parse_recipients_yaml(recipients_path) if recipients_path.exists() else None

    weekly = None
    if reading_log is not None:
        weekly = _get_weekly_stats(reading_log)

    backlog_completion = None
    if backlog is not None:
        bc = _compute_backlog_completion(backlog)
        if bc:
            backlog_completion = bc

    expected_window_start = weekly["start"] if weekly else None
    expected_window_end = weekly["end"] if weekly else None
    expected_total_completed = weekly["total_completed"] if weekly else None
    expected_total_minutes = weekly["total_minutes"] if weekly else None
    expected_avg_minutes = weekly["avg_minutes"] if weekly else None
    expected_universe_stats = None
    if weekly:
        expected_universe_stats = {u["universe"]: u for u in weekly["universe_stats"]}
    expected_top3 = weekly["top3"] if weekly else None
    expected_weekly_completed_ids = set([x["id"] for x in weekly["completed"]]) if weekly else set()

    summary_path = workspace / "output" / "progress_summary.md"
    email_path = workspace / "output" / "club_update_email.txt"
    notes_path = workspace / "output" / "meeting_notes.md"
    weekly_csv_path = workspace / "output" / "weekly_stats_by_universe.csv"

    summary_text = _read_text_safe(summary_path)
    email_text = _read_text_safe(email_path)
    notes_text = _read_text_safe(notes_path)
    weekly_csv_rows = _load_csv_dicts(weekly_csv_path)

    scores = {
        "progress_summary_exists": 1.0 if summary_text is not None else 0.0,
        "reporting_window_correct": 0.0,
        "summary_headline_stats_correct": 0.0,
        "summary_breakdown_by_universe_present": 0.0,
        "summary_top3_listed_and_ordered": 0.0,
        "summary_backlog_completion_rate_correct": 0.0,
        "summary_ids_listed_and_in_backlog_completed": 0.0,
        "summary_has_written_summary": 0.0,
        "email_exists": 1.0 if email_text is not None else 0.0,
        "email_to_line_correct": 0.0,
        "email_subject_correct": 0.0,
        "email_headline_stats_present": 0.0,
        "email_priority1_list_correct": 0.0,
        "email_meeting_datetime_included": 0.0,
        "meeting_notes_exists": 1.0 if notes_text is not None else 0.0,
        "meeting_notes_title_correct": 0.0,
        "meeting_notes_attendees_correct": 0.0,
        "meeting_notes_agenda_recap_correct": 0.0,
        "meeting_notes_decisions_section": 0.0,
        "meeting_notes_action_items_correct": 0.0,
        "weekly_stats_by_universe_exists": 1.0 if weekly_csv_rows is not None else 0.0,
        "weekly_stats_by_universe_values_correct": 0.0,
    }

    if summary_text is not None and weekly and backlog_completion:
        if (expected_window_start in summary_text) and (expected_window_end in summary_text):
            scores["reporting_window_correct"] = 1.0

        expected_avg_str = f"{expected_avg_minutes:.1f}"
        cond_total_completed = re.search(rf"\b{expected_total_completed}\b", summary_text) is not None
        cond_total_minutes = re.search(rf"\b{expected_total_minutes}\b", summary_text) is not None
        cond_avg_minutes = re.search(rf"\b{re.escape(expected_avg_str)}\b", summary_text) is not None
        if cond_total_completed and cond_total_minutes and cond_avg_minutes:
            scores["summary_headline_stats_correct"] = 1.0

        uni_ok = True
        if expected_universe_stats:
            for uni, vals in expected_universe_stats.items():
                found = False
                for ln in summary_text.splitlines():
                    if uni in ln and re.search(rf"\b{vals['completed_items']}\b", ln) and re.search(rf"\b{vals['total_minutes']}\b", ln):
                        found = True
                        break
                if not found:
                    uni_ok = False
                    break
        else:
            uni_ok = False
        if uni_ok:
            scores["summary_breakdown_by_universe_present"] = 1.0

        top_ok = False
        if expected_top3:
            all_present = True
            positions = []
            for item in expected_top3:
                id_pat = re.escape(item["id"])
                title_pat = re.escape(item["title"])
                m_id = re.search(id_pat, summary_text)
                m_title = re.search(title_pat, summary_text)
                if not (m_id and m_title):
                    all_present = False
                    break
                positions.append(m_id.start())
            if all_present:
                in_order = positions == sorted(positions)
                top_ok = in_order
        if top_ok:
            scores["summary_top3_listed_and_ordered"] = 1.0

        comp, total, pct = backlog_completion
        frac_ok = (re.search(rf"\b{comp}\s*/\s*{total}\b", summary_text) is not None) or (re.search(rf"\b{comp}/{total}\b", summary_text) is not None)
        pct_ok = re.search(rf"\b{pct:.1f}%\b", summary_text) is not None or re.search(rf"\b{int(round(pct))}%\b", summary_text) is not None
        if frac_ok and pct_ok:
            scores["summary_backlog_completion_rate_correct"] = 1.0

        mentioned_ids = set(_tokenize_ids(summary_text))
        ids_ok = expected_weekly_completed_ids.issubset(mentioned_ids)
        backlog_status_ok = True
        if backlog is not None:
            status_map = {r.get("id", "").strip(): (r.get("status", "").strip()) for r in backlog}
            for wid in expected_weekly_completed_ids:
                if status_map.get(wid) != "Completed":
                    backlog_status_ok = False
                    break
        else:
            backlog_status_ok = False
        if ids_ok and backlog_status_ok:
            scores["summary_ids_listed_and_in_backlog_completed"] = 1.0

        sentences = re.split(r"[.!?]\s+", summary_text.strip())
        sentences = [s for s in sentences if len(re.sub(r"\s+", "", s)) >= 10]
        if len(sentences) >= 2:
            scores["summary_has_written_summary"] = 1.0

    if email_text is not None and weekly and backlog_completion and recipients:
        lines = email_text.splitlines()
        to_line = None
        for ln in lines:
            if ln.strip().lower().startswith("to:"):
                to_line = ln.strip()
                break
        if to_line:
            m = re.match(r"to\s*:\s*(.*)$", to_line, flags=re.IGNORECASE)
            if m:
                to_emails_line = m.group(1).strip()
                listed_emails = [e.strip() for e in to_emails_line.split(",") if e.strip()]
                if set(listed_emails) == set(recipients):
                    scores["email_to_line_correct"] = 1.0

        subj_line = None
        for ln in lines:
            if ln.strip().lower().startswith("subject:"):
                subj_line = ln.strip()
                break
        expected_subject = f"Subject: Metropolis DC Fan Club Weekly Update - {expected_window_end}" if expected_window_end else None
        if subj_line and expected_subject and subj_line == expected_subject:
            scores["email_subject_correct"] = 1.0

        expected_avg_str = f"{weekly['avg_minutes']:.1f}" if weekly else None
        comp, total, pct = backlog_completion
        cond_total_completed = re.search(rf"\b{weekly['total_completed']}\b", email_text) is not None if weekly else False
        cond_total_minutes = re.search(rf"\b{weekly['total_minutes']}\b", email_text) is not None if weekly else False
        cond_avg_minutes = re.search(rf"\b{re.escape(expected_avg_str)}\b", email_text) is not None if expected_avg_str else False
        cond_backlog_rate = (re.search(rf"\b{comp}\s*/\s*{total}\b", email_text) is not None) or (re.search(rf"\b{int(round(pct))}%\b", email_text) is not None) if backlog_completion else False
        if cond_total_completed and cond_total_minutes and cond_avg_minutes and cond_backlog_rate:
            scores["email_headline_stats_present"] = 1.0

        prio_items = []
        if backlog:
            for r in backlog:
                try:
                    pri = int(str(r.get("priority", "")).strip())
                except Exception:
                    continue
                status = (r.get("status") or "").strip()
                if pri == 1 and status != "Completed":
                    try:
                        estm = int(str(r.get("est_minutes", "")).strip())
                    except Exception:
                        continue
                    prio_items.append({
                        "id": (r.get("id") or "").strip(),
                        "title": (r.get("title") or "").strip(),
                        "universe": (r.get("universe") or "").strip(),
                        "est_minutes": estm
                    })
        prio_sorted = sorted(prio_items, key=lambda x: (-x["est_minutes"], x["id"]))
        expected_prio = prio_sorted[:5]
        bullet_lines = [ln for ln in lines if re.match(r"^\s*[-*]\s+", ln)]
        prio_ok = False
        if expected_prio:
            indices = []
            details_ok = True
            for item in expected_prio:
                found_line_index = None
                for idx, bl in enumerate(bullet_lines):
                    contains = (item["id"] in bl) and (item["title"] in bl) and (item["universe"] in bl) and (re.search(rf"\b{item['est_minutes']}\b", bl) is not None)
                    if contains:
                        found_line_index = idx
                        break
                if found_line_index is None:
                    details_ok = False
                    break
                indices.append(found_line_index)
            if details_ok:
                prio_ok = all(indices[i] < indices[i+1] for i in range(len(indices)-1))
        else:
            prio_ok = True
        if prio_ok:
            scores["email_priority1_list_correct"] = 1.0

        if agenda and agenda.get("date_time"):
            if agenda["date_time"] in email_text:
                scores["email_meeting_datetime_included"] = 1.0

    if notes_text is not None and agenda:
        title_ok = False
        title_line = None
        for ln in notes_text.splitlines():
            if ln.strip().startswith("# "):
                title_line = ln.strip().lstrip("# ").strip()
                break
        if title_line and isinstance(agenda.get("title"), str) and agenda.get("date_time"):
            if agenda["title"] in title_line and str(agenda["date_time"]) in title_line:
                title_ok = True
        if title_ok:
            scores["meeting_notes_title_correct"] = 1.0

        attendee_ok = False
        if agenda.get("participants"):
            missing = []
            for p in agenda["participants"]:
                if p not in notes_text:
                    missing.append(p)
            attendee_ok = (len(missing) == 0)
        if attendee_ok:
            scores["meeting_notes_attendees_correct"] = 1.0

        recap_lines = _extract_section_lines(notes_text, "Agenda Recap")
        recap_ok = False
        if recap_lines:
            cleaned_items = [_clean_agenda_item_for_recap(it) for it in (agenda.get("agenda_items") or [])]
            cleaned_items = [it for it in cleaned_items if it]
            present = all(any(ci in ln for ln in recap_lines) for ci in cleaned_items)
            recap_ok = present
        if recap_ok:
            scores["meeting_notes_agenda_recap_correct"] = 1.0

        decisions_lines = _extract_section_lines(notes_text, "Decisions")
        decisions_ok = False
        if decisions_lines:
            decisions_text = "\n".join(decisions_lines)
            expected_decisions = agenda.get("decisions") or []
            decisions_ok = all(dec in decisions_text for dec in expected_decisions)
        if decisions_ok:
            scores["meeting_notes_decisions_section"] = 1.0

        actions_lines = _extract_section_lines(notes_text, "Action Items")
        actions_ok = False
        if actions_lines:
            actions_text = "\n".join(actions_lines)
            expected_actions = agenda.get("actions") or []
            all_actions_present = True
            for act in expected_actions:
                a_ok = True
                if act.get("assignee"):
                    if f"Assignee: {act['assignee']}" not in actions_text:
                        a_ok = False
                if act.get("task"):
                    task_phrase = act["task"]
                    if task_phrase not in actions_text:
                        a_ok = False
                if act.get("due"):
                    if f"Due: {act['due']}" not in actions_text:
                        a_ok = False
                if not a_ok:
                    all_actions_present = False
                    break
            total_line_ok = re.search(rf"Total action items:\s*{len(expected_actions)}\b", actions_text) is not None
            actions_ok = all_actions_present and total_line_ok
        if actions_ok:
            scores["meeting_notes_action_items_correct"] = 1.0

    if weekly_csv_rows is not None and weekly:
        try:
            with (weekly_csv_path.open("r", encoding="utf-8", newline="")) as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        header_ok = header == ["universe", "completed_items", "total_minutes", "avg_minutes"]
        values_ok = False
        if header_ok:
            parsed = {}
            valid_rows = True
            for row in weekly_csv_rows:
                if not all(k in row for k in ["universe", "completed_items", "total_minutes", "avg_minutes"]):
                    valid_rows = False
                    break
                parsed_row = _parse_csv_numeric_row(row, int_fields=["completed_items", "total_minutes"], float_fields=["avg_minutes"])
                if parsed_row is None:
                    valid_rows = False
                    break
                parsed[parsed_row["universe"]] = parsed_row
            if valid_rows:
                checks = []
                for uni, stats in (expected_universe_stats or {}).items():
                    if stats["completed_items"] > 0:
                        if uni in parsed:
                            row = parsed[uni]
                            ok_row = (
                                row["completed_items"] == stats["completed_items"] and
                                row["total_minutes"] == stats["total_minutes"] and
                                abs(row["avg_minutes"] - float(f"{stats['avg_minutes']:.1f}")) < 1e-6
                            )
                            checks.append(ok_row)
                        else:
                            checks.append(False)
                values_ok = all(checks) if checks else False
        if header_ok and values_ok:
            scores["weekly_stats_by_universe_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()