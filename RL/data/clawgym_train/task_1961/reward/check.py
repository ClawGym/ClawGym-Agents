import json
import sys
import csv
from pathlib import Path
from datetime import datetime, date, timedelta


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _parse_date(s: str):
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def _parse_datetime(s: str):
    # format: YYYY-MM-DD HH:MM
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _get_as_of(workspace: Path):
    p = workspace / "input" / "as_of.txt"
    txt = _read_text(p).strip()
    if not txt:
        return None
    return _parse_date(txt.splitlines()[0].strip())


def _compute_comms_metrics(workspace: Path):
    path = workspace / "input" / "communications.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    # Clean rows and parse datetime
    msgs = []
    for r in rows:
        dt = _parse_datetime(r.get("datetime", "").strip())
        if dt is None:
            return None
        msgs.append({
            "id": r.get("id"),
            "thread": r.get("thread", ""),
            "datetime": dt,
            "from": r.get("from", ""),
            "to": r.get("to", ""),
            "channel": r.get("channel", ""),
            "body": r.get("body", ""),
        })
    total_messages = len(msgs)
    me_to_lawyer = sum(1 for m in msgs if m["from"] == "Me" and m["to"] == "Lawyer")
    lawyer_to_me = sum(1 for m in msgs if m["from"] == "Lawyer" and m["to"] == "Me")
    # Group by thread and sort by datetime then by id numeric if possible
    from collections import defaultdict
    threads = defaultdict(list)
    for m in msgs:
        threads[m["thread"]].append(m)
    for t in threads:
        threads[t].sort(key=lambda x: (x["datetime"], int(x["id"]) if isinstance(x["id"], str) and x["id"].isdigit() else 0))
    diffs = []
    for t, t_msgs in threads.items():
        for idx, m in enumerate(t_msgs):
            if m["from"] == "Me" and m["to"] == "Lawyer":
                # find next Lawyer->Me in same thread
                for j in range(idx + 1, len(t_msgs)):
                    nm = t_msgs[j]
                    if nm["from"] == "Lawyer" and nm["to"] == "Me" and nm["datetime"] > m["datetime"]:
                        delta = nm["datetime"] - m["datetime"]
                        hours = delta.total_seconds() / 3600.0
                        diffs.append(hours)
                        break
    if diffs:
        avg_hours = round(sum(diffs) / len(diffs) + 1e-12, 2)
    else:
        avg_hours = round(0.0, 2)
    return {
        "total_messages": total_messages,
        "me_to_lawyer": me_to_lawyer,
        "lawyer_to_me": lawyer_to_me,
        "avg_lawyer_response_hours": avg_hours,
    }


def _compute_compliance_metrics(workspace: Path):
    as_of = _get_as_of(workspace)
    if as_of is None:
        return None
    path = workspace / "input" / "compliance_log.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    items = []
    for r in rows:
        due = _parse_date(r.get("due_date", "").strip())
        if due is None:
            return None
        status = (r.get("status", "") or "").strip()
        requirement = (r.get("requirement", "") or "").strip()
        items.append({"due_date": due, "status": status, "requirement": requirement})
    in_scope = [it for it in items if it["due_date"] <= as_of]
    total_in_scope = len(in_scope)
    completed_in_scope = sum(1 for it in in_scope if it["status"].lower() == "completed")
    compliance_rate = round((completed_in_scope / total_in_scope) if total_in_scope > 0 else 0.0, 2)
    completed_items_count = sum(1 for it in items if it["status"].lower() == "completed")
    # Upcoming within 14 days (compliance items only here)
    end_date = as_of + timedelta(days=14)
    upcoming_compliance = [(it["requirement"], it["due_date"]) for it in items if (it["due_date"] > as_of and it["due_date"] <= end_date)]
    return {
        "compliance_rate": compliance_rate,
        "completed_items_count": completed_items_count,
        "upcoming_compliance": upcoming_compliance,
    }


def _compute_hearings_metrics(workspace: Path):
    as_of = _get_as_of(workspace)
    if as_of is None:
        return None
    path = workspace / "input" / "case_events.json"
    data = _load_json(path)
    if data is None:
        return None
    hearings = data.get("hearings", []) or []
    parsed = []
    for h in hearings:
        d = h.get("date")
        try:
            hd = date.fromisoformat(d)
        except Exception:
            return None
        parsed.append({"type": h.get("type", ""), "date": hd})
    # next hearing strictly after as_of
    future = [h for h in parsed if h["date"] > as_of]
    if future:
        next_hearing = min(future, key=lambda x: x["date"])
        next_hearing_date = next_hearing["date"].isoformat()
        days_until = (next_hearing["date"] - as_of).days
    else:
        next_hearing_date = ""
        days_until = 0
    # hearings within 14 days window
    end_date = as_of + timedelta(days=14)
    upcoming_hearings = [h for h in parsed if (h["date"] > as_of and h["date"] <= end_date)]
    return {
        "next_hearing_date": next_hearing_date,
        "days_until_next_hearing": days_until,
        "upcoming_hearings": upcoming_hearings,
    }


def _compute_total_charges(workspace: Path):
    path = workspace / "input" / "case_events.json"
    data = _load_json(path)
    if data is None:
        return None
    charges = data.get("charges", [])
    if not isinstance(charges, list):
        return None
    return len(charges)


def _load_metrics_json(workspace: Path):
    p = workspace / "output" / "metrics.json"
    data = _load_json(p)
    return data


def _float_equal(a: float, b: float, tol: float = 0.005) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _get_markdown_section(text: str, title: str) -> str:
    # Find a heading line matching title (case-insensitive), with or without '#' prefix
    lines = text.splitlines()
    indices = []
    normalized_title = title.strip().lower()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#"):
            # strip hashes and spaces
            stripped = s.lstrip("#").strip().lower()
            if stripped == normalized_title:
                indices.append(i)
        else:
            if s.lower() == normalized_title:
                indices.append(i)
    if not indices:
        return ""
    start = indices[0] + 1
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if s.startswith("#"):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def _find_bullet_lines(text: str):
    lines = text.splitlines()
    bullets = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets


def _word_count(text: str) -> int:
    return len(text.strip().split())


def _contains_any(text: str, keywords: list) -> bool:
    tl = text.lower()
    return any(k.lower() in tl for k in keywords)


def _is_professional(text: str) -> bool:
    greetings = ["hello", "hi", "dear", "good morning", "good afternoon", "good evening"]
    closings = ["thank", "thanks", "sincerely", "best regards", "best,", "respectfully"]
    slang = ["hey", "kno", "gonna", "probly", "prolly", "sry", "thx", "lol", "omg", "u "]
    has_greeting = any(g in text.lower() for g in greetings)
    has_closing = any(c in text.lower() for c in closings)
    has_slang = any(s in text.lower() for s in slang)
    return has_greeting and has_closing and not has_slang


def _no_guilt(text: str) -> bool:
    banned_phrases = [
        "i am guilty",
        "i'm guilty",
        "i admit guilt",
        "i admit i",
        "i did it",
        "i stole",
        "i shoplifted",
        "i committed",
        "i confess",
        "i plead guilty",
        "i pleadged guilty",  # typo guard
        "my guilt",
    ]
    return not _contains_any(text, banned_phrases)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        # metrics checks
        "metrics_total_messages_correct": 0.0,
        "metrics_me_to_lawyer_correct": 0.0,
        "metrics_lawyer_to_me_correct": 0.0,
        "metrics_avg_lawyer_response_hours_correct": 0.0,
        "metrics_compliance_rate_correct": 0.0,
        "metrics_completed_items_count_correct": 0.0,
        "metrics_upcoming_within_14_days_count_correct": 0.0,
        "metrics_days_until_next_hearing_correct": 0.0,
        "metrics_next_hearing_date_correct": 0.0,
        "metrics_total_charges_correct": 0.0,
        # report checks
        "report_sections_present": 0.0,
        "report_case_snapshot_matches_metrics": 0.0,
        "report_communication_summary_matches_metrics": 0.0,
        "report_compliance_summary_matches_metrics": 0.0,
        "report_upcoming_list_covers_expected": 0.0,
        "report_action_items_count_valid": 0.0,
        # rewritten messages checks
        "rewritten_public_defender_length_tone_and_originality": 0.0,
        "rewritten_public_defender_no_guilt": 0.0,
        "rewritten_probation_officer_length_tone_and_originality": 0.0,
        "rewritten_probation_officer_no_guilt": 0.0,
        # architecture checks
        "architecture_sections_present": 0.0,
        "architecture_folder_structure_references": 0.0,
        "architecture_data_sources_covered": 0.0,
        "architecture_schema_notes_covered": 0.0,
        "architecture_templates_reference": 0.0,
    }

    # Compute expected metric components
    comms = _compute_comms_metrics(workspace)
    compliance = _compute_compliance_metrics(workspace)
    hearings = _compute_hearings_metrics(workspace)
    total_charges = _compute_total_charges(workspace)

    # Load produced metrics.json
    metrics = _load_metrics_json(workspace)

    # Helper to fetch metric value safely
    def get_metric(key):
        if isinstance(metrics, dict) and key in metrics:
            return metrics.get(key)
        return None

    # Individual metric checks
    if metrics is not None and comms is not None:
        if get_metric("total_messages") == comms["total_messages"]:
            scores["metrics_total_messages_correct"] = 1.0
        if get_metric("me_to_lawyer") == comms["me_to_lawyer"]:
            scores["metrics_me_to_lawyer_correct"] = 1.0
        if get_metric("lawyer_to_me") == comms["lawyer_to_me"]:
            scores["metrics_lawyer_to_me_correct"] = 1.0
        mv = get_metric("avg_lawyer_response_hours")
        if mv is not None and _float_equal(mv, comms["avg_lawyer_response_hours"]):
            scores["metrics_avg_lawyer_response_hours_correct"] = 1.0

    if metrics is not None and compliance is not None:
        mv = get_metric("compliance_rate")
        if mv is not None and _float_equal(mv, compliance["compliance_rate"]):
            scores["metrics_compliance_rate_correct"] = 1.0
        if get_metric("completed_items_count") == compliance["completed_items_count"]:
            scores["metrics_completed_items_count_correct"] = 1.0

    # upcoming_within_14_days_count requires combining compliance and hearings
    if metrics is not None and compliance is not None and hearings is not None:
        upcoming_count_expected = len(compliance["upcoming_compliance"]) + len(hearings["upcoming_hearings"])
        if get_metric("upcoming_within_14_days_count") == upcoming_count_expected:
            scores["metrics_upcoming_within_14_days_count_correct"] = 1.0

    if metrics is not None and hearings is not None:
        if get_metric("days_until_next_hearing") == hearings["days_until_next_hearing"]:
            scores["metrics_days_until_next_hearing_correct"] = 1.0
        if get_metric("next_hearing_date") == hearings["next_hearing_date"]:
            scores["metrics_next_hearing_date_correct"] = 1.0

    if metrics is not None and total_charges is not None:
        if get_metric("total_charges") == total_charges:
            scores["metrics_total_charges_correct"] = 1.0

    # Report checks
    report_path = workspace / "output" / "case_progress_report.md"
    report_text = _read_text(report_path)
    if report_text:
        # Sections present
        required_sections = [
            "Case Snapshot",
            "Communication Summary",
            "Compliance Summary",
            "Upcoming (next 14 days)",
            "Action Items",
        ]
        sections_present = all(_get_markdown_section(report_text, s) != "" or any(ln.strip().lower() == s.lower() for ln in report_text.splitlines()) for s in required_sections)
        if sections_present:
            scores["report_sections_present"] = 1.0

        # Matches metrics: compare numbers present in appropriate sections
        if metrics is not None:
            # Case Snapshot
            snap = _get_markdown_section(report_text, "Case Snapshot")
            nhd = str(get_metric("next_hearing_date"))
            dnh = get_metric("days_until_next_hearing")
            snap_ok = False
            if isinstance(dnh, int) and nhd is not None:
                if nhd in snap and str(dnh) in snap:
                    snap_ok = True
            if snap_ok:
                scores["report_case_snapshot_matches_metrics"] = 1.0

            # Communication Summary
            comm_sec = _get_markdown_section(report_text, "Communication Summary")
            tm = get_metric("total_messages")
            m2l = get_metric("me_to_lawyer")
            l2m = get_metric("lawyer_to_me")
            alrh = get_metric("avg_lawyer_response_hours")
            comm_ok = False
            if all(x is not None for x in [tm, m2l, l2m, alrh]):
                # Ensure formatted floats have two decimals
                alrh_str = f"{float(alrh):.2f}"
                if (str(tm) in comm_sec) and (str(m2l) in comm_sec) and (str(l2m) in comm_sec) and (alrh_str in comm_sec):
                    comm_ok = True
            if comm_ok:
                scores["report_communication_summary_matches_metrics"] = 1.0

            # Compliance Summary
            comp_sec = _get_markdown_section(report_text, "Compliance Summary")
            cr = get_metric("compliance_rate")
            cic = get_metric("completed_items_count")
            comp_ok = False
            if cr is not None and cic is not None:
                cr_str = f"{float(cr):.2f}"
                if (cr_str in comp_sec) and (str(cic) in comp_sec):
                    comp_ok = True
            if comp_ok:
                scores["report_compliance_summary_matches_metrics"] = 1.0

            # Upcoming bullet list covers expected
            upcoming_sec = _get_markdown_section(report_text, "Upcoming (next 14 days)")
            bullets = _find_bullet_lines(upcoming_sec)
            if bullets and compliance is not None and hearings is not None:
                cover_ok = True
                # Check each upcoming compliance item appears with name and date
                for name, due_date in compliance["upcoming_compliance"]:
                    due_str = due_date.isoformat()
                    found = any((name in b and due_str in b) for b in bullets)
                    if not found:
                        cover_ok = False
                        break
                # Check each upcoming hearing appears with date and hearing type or the word "hearing"
                if cover_ok:
                    for h in hearings["upcoming_hearings"]:
                        dstr = h["date"].isoformat()
                        t = (h.get("type") or "").strip()
                        found = any((dstr in b and (t.lower() in b.lower() or "hearing" in b.lower())) for b in bullets)
                        if not found:
                            cover_ok = False
                            break
                if cover_ok:
                    scores["report_upcoming_list_covers_expected"] = 1.0

            # Action Items: 3–6 bullets
            actions_sec = _get_markdown_section(report_text, "Action Items")
            action_bullets = _find_bullet_lines(actions_sec)
            if 3 <= len(action_bullets) <= 6:
                scores["report_action_items_count_valid"] = 1.0

    # Rewritten messages checks
    # Public defender
    out_pd_path = workspace / "output" / "rewritten_messages" / "to_public_defender.txt"
    in_pd_path = workspace / "input" / "draft_messages" / "to_public_defender.txt"
    out_pd_text = _read_text(out_pd_path).strip()
    in_pd_text = _read_text(in_pd_path).strip()
    if out_pd_text:
        length_ok = _word_count(out_pd_text) <= 150 and _word_count(out_pd_text) > 0
        tone_ok = _is_professional(out_pd_text)
        orig_ok = (in_pd_text != "") and (out_pd_text.strip() != in_pd_text.strip())
        if length_ok and tone_ok and orig_ok:
            scores["rewritten_public_defender_length_tone_and_originality"] = 1.0
        if _no_guilt(out_pd_text):
            scores["rewritten_public_defender_no_guilt"] = 1.0

    # Probation officer
    out_po_path = workspace / "output" / "rewritten_messages" / "to_probation_officer.txt"
    in_po_path = workspace / "input" / "draft_messages" / "to_probation_officer.txt"
    out_po_text = _read_text(out_po_path).strip()
    in_po_text = _read_text(in_po_path).strip()
    if out_po_text:
        length_ok = _word_count(out_po_text) <= 150 and _word_count(out_po_text) > 0
        tone_ok = _is_professional(out_po_text)
        orig_ok = (in_po_text != "") and (out_po_text.strip() != in_po_text.strip())
        if length_ok and tone_ok and orig_ok:
            scores["rewritten_probation_officer_length_tone_and_originality"] = 1.0
        if _no_guilt(out_po_text):
            scores["rewritten_probation_officer_no_guilt"] = 1.0

    # Solution architecture checks
    arch_path = workspace / "output" / "solution_architecture.md"
    arch_text = _read_text(arch_path)
    if arch_text:
        # Sections presence
        arch_sections = [
            "Objectives",
            "Data Sources",
            "Proposed Folder Structure",
            "Data Schema Notes",
            "Update Cadence & Automation",
            "Communication Templates",
        ]
        sections_ok = all(_get_markdown_section(arch_text, s) != "" or any(ln.strip().lower() == s.lower() for ln in arch_text.splitlines()) for s in arch_sections)
        if sections_ok:
            scores["architecture_sections_present"] = 1.0

        # Folder structure references
        pfs = _get_markdown_section(arch_text, "Proposed Folder Structure")
        required_paths = [
            "input/",
            "input/case_events.json",
            "input/communications.csv",
            "input/compliance_log.csv",
            "input/as_of.txt",
            "input/draft_messages/to_public_defender.txt",
            "input/draft_messages/to_probation_officer.txt",
            "output/metrics.json",
            "output/case_progress_report.md",
            "output/solution_architecture.md",
            "output/rewritten_messages/to_public_defender.txt",
            "output/rewritten_messages/to_probation_officer.txt",
        ]
        if pfs and all(rp in pfs for rp in required_paths):
            scores["architecture_folder_structure_references"] = 1.0

        # Data sources covered
        ds = _get_markdown_section(arch_text, "Data Sources")
        ds_required = [
            "input/case_events.json",
            "input/communications.csv",
            "input/compliance_log.csv",
            "input/as_of.txt",
            "input/draft_messages/to_public_defender.txt",
            "input/draft_messages/to_probation_officer.txt",
        ]
        if ds and all(r in ds for r in ds_required):
            scores["architecture_data_sources_covered"] = 1.0

        # Schema notes
        schema = _get_markdown_section(arch_text, "Data Schema Notes")
        # Require mention of key fields
        schema_requirements = [
            "communications.csv", "from", "to", "datetime", "thread",
            "compliance_log.csv", "requirement", "due_date", "status",
            "case_events.json", "hearings", "charges",
        ]
        if schema and all(any(tok in line.lower() for line in schema.splitlines()) for tok in [s.lower() for s in schema_requirements]):
            scores["architecture_schema_notes_covered"] = 1.0

        # Communication templates reference
        ct = _get_markdown_section(arch_text, "Communication Templates")
        ct_required = [
            "rewritten",
            "output/rewritten_messages/to_public_defender.txt",
            "output/rewritten_messages/to_probation_officer.txt",
        ]
        if ct and all(r.lower() in ct.lower() for r in ct_required):
            scores["architecture_templates_reference"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()