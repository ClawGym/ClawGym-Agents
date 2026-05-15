import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def load_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    header, data = load_csv_with_header(path)
    if header is None or data is None:
        return None, None
    dicts = []
    for row in data:
        if len(row) != len(header):
            return None, None
        dicts.append({header[i]: row[i] for i in range(len(header))})
    return header, dicts


def parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def compute_expected_top_leads(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    leads_path = workspace / "input" / "leads.csv"
    header, rows = load_csv_dicts(leads_path)
    if header is None or rows is None:
        return None
    required_cols = {"lead_id", "company", "industry", "stage", "lead_score", "days_since_last_contact"}
    if not required_cols.issubset(set(header)):
        return None
    filtered = []
    for r in rows:
        try:
            stage = r["stage"].strip()
            industry = r["industry"].strip()
            lead_score = int(r["lead_score"].strip())
            days = int(r["days_since_last_contact"].strip())
        except Exception:
            return None
        if stage in ("Prospect", "Qualified") and industry in ("Healthcare", "Logistics") and lead_score >= 60:
            priority_score = round(0.6 * lead_score + 0.4 * days, 2)
            try:
                lead_id_int = int(r["lead_id"].strip())
            except Exception:
                return None
            filtered.append({
                "lead_id": lead_id_int,
                "company": r["company"].strip(),
                "industry": industry,
                "stage": stage,
                "lead_score": lead_score,
                "days_since_last_contact": days,
                "priority_score": priority_score,
            })
    filtered.sort(key=lambda x: (-x["priority_score"], x["company"]))
    for idx, item in enumerate(filtered, start=1):
        item["rank"] = idx
    return filtered


def parse_meeting_transcripts(workspace: Path) -> Optional[List[Dict[str, str]]]:
    meetings_dir = workspace / "input" / "meetings"
    if not meetings_dir.exists():
        return None
    all_items: List[Dict[str, str]] = []
    for p in sorted(meetings_dir.rglob("*.txt")):
        txt = read_text_safe(p)
        if txt is None:
            return None
        client = None
        mdate = None
        for line in txt.splitlines():
            if client is None:
                m = re.match(r"^\s*Client:\s*(.+?)\s*$", line)
                if m:
                    client = m.group(1).strip()
                    continue
            if mdate is None:
                m = re.match(r"^\s*Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", line)
                if m:
                    mdate = m.group(1).strip()
                    continue
        if client is None or mdate is None:
            return None
        for line in txt.splitlines():
            m = re.match(r"^\s*Action:\s*(.*?)\s*\|\s*Owner:\s*(.*?)\s*\|\s*Due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", line)
            if m:
                action = m.group(1).strip()
                owner = m.group(2).strip()
                due = m.group(3).strip()
                if parse_iso_date(due) is None:
                    return None
                all_items.append({
                    "meeting_date": mdate,
                    "client": client,
                    "action": action,
                    "owner": owner,
                    "due_date": due
                })
    all_items.sort(key=lambda x: (x["due_date"], x["client"]))
    return all_items


def extract_section(lines: List[str], section_keyword: str) -> List[str]:
    start_idx = None
    key_lower = section_keyword.lower()
    for i, line in enumerate(lines):
        if key_lower in line.lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if re.match(r"^\s*#\s*", lines[j]):
            end_idx = j
            break
    return lines[start_idx:end_idx]


def float_str_variants(val: float) -> List[str]:
    rounded = round(val, 2)
    return [str(rounded), f"{rounded:.2f}"]


def check_script_contents(script_text: Optional[str]) -> Dict[str, float]:
    checks = {
        "script_exists_and_shebang": 0.0,
        "script_references_inputs_outputs": 0.0,
    }
    if script_text is None:
        return checks
    first_line = script_text.splitlines()[0] if script_text.splitlines() else ""
    if first_line.startswith("#!") and "bash" in first_line.lower():
        checks["script_exists_and_shebang"] = 1.0
    needed_refs = [
        "input/schedule/next_run_date.txt",
        "input/leads.csv",
        "output/leads/top_leads.csv",
        "input/meetings",
        "output/meetings/action_items.csv",
        "input/drafts/outreach_email.txt",
        "output/messaging/outreach_email_rewrite.txt",
        "output/weekly/briefing_",
    ]
    if all(ref in script_text for ref in needed_refs):
        checks["script_references_inputs_outputs"] = 1.0
    return checks


def grade_top_leads(workspace: Path) -> Dict[str, float]:
    scores = {
        "top_leads_exists_format": 0.0,
        "top_leads_correct_rows_and_order": 0.0,
        "top_leads_priority_scores_correct": 0.0,
    }
    expected = compute_expected_top_leads(workspace)
    out_path = workspace / "output" / "leads" / "top_leads.csv"
    header, rows = load_csv_with_header(out_path)
    if header is None or rows is None:
        return scores
    expected_header = ["rank", "lead_id", "company", "industry", "stage", "lead_score", "days_since_last_contact", "priority_score"]
    if header == expected_header:
        scores["top_leads_exists_format"] = 1.0
    if expected is None:
        return scores
    parsed = []
    try:
        for r in rows:
            if len(r) != len(expected_header):
                return scores
            pr = {
                "rank": int(r[0].strip()),
                "lead_id": int(r[1].strip()),
                "company": r[2].strip(),
                "industry": r[3].strip(),
                "stage": r[4].strip(),
                "lead_score": int(r[5].strip()),
                "days_since_last_contact": int(r[6].strip()),
                "priority_score": float(r[7].strip()),
            }
            parsed.append(pr)
    except Exception:
        return scores
    if len(parsed) == len(expected):
        order_ok = True
        for i, pr in enumerate(parsed):
            if pr["rank"] != i + 1:
                order_ok = False
                break
        if order_ok:
            content_ok = True
            for i, pr in enumerate(parsed):
                ex = expected[i]
                if not (
                    pr["lead_id"] == ex["lead_id"] and
                    pr["company"] == ex["company"] and
                    pr["industry"] == ex["industry"] and
                    pr["stage"] == ex["stage"] and
                    pr["lead_score"] == ex["lead_score"] and
                    pr["days_since_last_contact"] == ex["days_since_last_contact"]
                ):
                    content_ok = False
                    break
            if content_ok:
                scores["top_leads_correct_rows_and_order"] = 1.0
    try:
        prio_ok = True
        for i, pr in enumerate(parsed):
            ex = expected[i]
            if round(pr["priority_score"], 2) != round(ex["priority_score"], 2):
                prio_ok = False
                break
        if prio_ok and len(parsed) == len(expected):
            scores["top_leads_priority_scores_correct"] = 1.0
    except Exception:
        pass
    return scores


def grade_action_items(workspace: Path) -> Dict[str, float]:
    scores = {
        "action_items_exists_format": 0.0,
        "action_items_correct_rows_and_order": 0.0,
    }
    expected = parse_meeting_transcripts(workspace)
    out_path = workspace / "output" / "meetings" / "action_items.csv"
    header, rows_dicts = load_csv_dicts(out_path)
    if header is None or rows_dicts is None:
        return scores
    expected_header = ["meeting_date", "client", "action", "owner", "due_date"]
    if header == expected_header:
        scores["action_items_exists_format"] = 1.0
    if expected is None:
        return scores
    if len(rows_dicts) != len(expected):
        return scores

    def norm_row(r: Dict[str, str]) -> Dict[str, str]:
        return {k: (r.get(k, "").strip()) for k in expected_header}
    all_match = True
    for i in range(len(expected)):
        if norm_row(rows_dicts[i]) != norm_row(expected[i]):
            all_match = False
            break
    if all_match:
        scores["action_items_correct_rows_and_order"] = 1.0
    return scores


def grade_outreach_rewrite(workspace: Path) -> Dict[str, float]:
    scores = {
        "outreach_rewrite_subject_and_body_constraints": 0.0,
        "outreach_rewrite_includes_cta": 0.0,
    }
    p = workspace / "output" / "messaging" / "outreach_email_rewrite.txt"
    txt = read_text_safe(p)
    if txt is None:
        return scores
    lines = txt.splitlines()
    first_nonempty_idx = None
    for i, line in enumerate(lines):
        if line.strip() != "":
            first_nonempty_idx = i
            break
    if first_nonempty_idx is None:
        return scores
    first_line = lines[first_nonempty_idx].strip()
    if not first_line.startswith("Subject:"):
        return scores
    subject = first_line[len("Subject:"):].strip()
    try:
        subj_ok = len(subject) <= 60
    except Exception:
        subj_ok = False
    body = "\n".join(lines[first_nonempty_idx + 1:]).strip()
    body_words = len(re.findall(r"\b\w+\b", body))
    body_ok = body_words <= 120 and body_words > 0
    if subj_ok and body_ok:
        scores["outreach_rewrite_subject_and_body_constraints"] = 1.0
    cta_phrase = "schedule a 30-minute call next week"
    if cta_phrase.lower() in body.lower():
        scores["outreach_rewrite_includes_cta"] = 1.0
    return scores


def grade_weekly_brief(workspace: Path) -> Dict[str, float]:
    scores = {
        "weekly_brief_filename_and_header": 0.0,
        "weekly_brief_includes_top_3_correct": 0.0,
        "weekly_brief_upcoming_items_window_correct": 0.0,
        "weekly_brief_notes_outreach_path": 0.0,
    }
    run_date_path = workspace / "input" / "schedule" / "next_run_date.txt"
    run_date_txt = read_text_safe(run_date_path)
    if run_date_txt is None:
        return scores
    run_date_str = run_date_txt.strip()
    run_date = parse_iso_date(run_date_str)
    if run_date is None:
        return scores
    brief_path = workspace / "output" / "weekly" / f"briefing_{run_date_str}.md"
    brief_txt = read_text_safe(brief_path)
    if brief_txt is None:
        return scores
    lines = brief_txt.splitlines()
    header_ok = any(run_date_str in (ln or "") for ln in lines[:10])
    if header_ok:
        scores["weekly_brief_filename_and_header"] = 1.0
    expected_leads = compute_expected_top_leads(workspace)
    if expected_leads is None:
        expected_leads = []
    top3 = expected_leads[:3]
    top_section_lines = extract_section(lines, "Top 3 Leads")
    top_section_text = "\n".join(top_section_lines)
    top_ok = True
    for r in [1, 2, 3]:
        if str(r) not in top_section_text:
            top_ok = False
            break
    if top_ok:
        for lead in top3:
            needed_tokens = [
                lead["company"],
                lead["industry"],
                lead["stage"],
                str(lead["lead_score"]),
                str(lead["days_since_last_contact"]),
            ]
            prio_variants = float_str_variants(lead["priority_score"])
            prio_present = any(pv in top_section_text for pv in prio_variants)
            if not prio_present:
                top_ok = False
                break
            for tok in needed_tokens:
                if tok not in top_section_text:
                    top_ok = False
                    break
            if not top_ok:
                break
    if top_ok and len(top_section_lines) > 0:
        scores["weekly_brief_includes_top_3_correct"] = 1.0
    all_items = parse_meeting_transcripts(workspace)
    upcoming_ok = False
    if all_items is not None:
        start_date = run_date
        end_date = run_date + timedelta(days=14)
        in_range = []
        out_range = []
        for it in all_items:
            due = parse_iso_date(it["due_date"])
            if due is None:
                continue
            if start_date <= due <= end_date:
                in_range.append(it)
            else:
                out_range.append(it)
        up_section_lines = extract_section(lines, "Upcoming Action Items (next 14 days)")
        up_text = "\n".join(up_section_lines)
        if up_text.strip() != "":
            all_present = True
            for it in in_range:
                if (it["action"] not in up_text) or (it["due_date"] not in up_text):
                    all_present = False
                    break
            none_extra = True
            for it in out_range:
                if it["action"] in up_text:
                    none_extra = False
                    break
            if all_present and none_extra:
                upcoming_ok = True
    if upcoming_ok:
        scores["weekly_brief_upcoming_items_window_correct"] = 1.0
    if "output/messaging/outreach_email_rewrite.txt" in brief_txt:
        scores["weekly_brief_notes_outreach_path"] = 1.0
    return scores


def grade_cron(workspace: Path) -> Dict[str, float]:
    scores = {
        "cron_entry_valid": 0.0,
    }
    p = workspace / "output" / "schedule" / "cron.txt"
    txt = read_text_safe(p)
    if txt is None:
        return scores
    lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
    if len(lines) != 1:
        return scores
    line = lines[0].rstrip()
    pattern = r'^\s*0\s+8\s+\*\s+\*\s+1\s+\./scripts/weekly_brief\.sh\s+#\s*weekly_brief\s*$'
    if re.match(pattern, line):
        scores["cron_entry_valid"] = 1.0
    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists_and_shebang": 0.0,
        "script_references_inputs_outputs": 0.0,
        "top_leads_exists_format": 0.0,
        "top_leads_correct_rows_and_order": 0.0,
        "top_leads_priority_scores_correct": 0.0,
        "action_items_exists_format": 0.0,
        "action_items_correct_rows_and_order": 0.0,
        "outreach_rewrite_subject_and_body_constraints": 0.0,
        "outreach_rewrite_includes_cta": 0.0,
        "weekly_brief_filename_and_header": 0.0,
        "weekly_brief_includes_top_3_correct": 0.0,
        "weekly_brief_upcoming_items_window_correct": 0.0,
        "weekly_brief_notes_outreach_path": 0.0,
        "cron_entry_valid": 0.0,
    }
    script_path = workspace / "scripts" / "weekly_brief.sh"
    script_text = read_text_safe(script_path)
    script_scores = check_script_contents(script_text)
    scores.update(script_scores)
    scores.update(grade_top_leads(workspace))
    scores.update(grade_action_items(workspace))
    scores.update(grade_outreach_rewrite(workspace))
    scores.update(grade_weekly_brief(workspace))
    scores.update(grade_cron(workspace))
    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()