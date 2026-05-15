import json
import re
import sys
import csv
from pathlib import Path


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_lines_safe(path: Path) -> list:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _contains_any(text: str, patterns: list) -> bool:
    tl = text.lower()
    for p in patterns:
        if p.lower() in tl:
            return True
    return False


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _has_unified_diff_markers(diff_text: str) -> bool:
    has_old = any(line.startswith("--- ") for line in diff_text.splitlines())
    has_new = any(line.startswith("+++ ") for line in diff_text.splitlines())
    has_hunk = any(line.startswith("@@") for line in diff_text.splitlines())
    return has_old and has_new and has_hunk


def _find_heading_presence(md_text: str, heading_keywords: list) -> float:
    lines = md_text.splitlines()
    headings = [l.strip() for l in lines if l.strip().startswith("#")]
    found = 0
    for kw in heading_keywords:
        if any(kw.lower() in h.lower() for h in headings):
            found += 1
    if not heading_keywords:
        return 1.0
    return found / len(heading_keywords)


def _iso_date(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))


def _email_facts_from_input(email_text: str) -> dict:
    facts = {}
    facts["amount_7500"] = bool(re.search(r"7[, ]?500", email_text))
    facts["year_2026"] = "2026" in email_text
    facts["month_june"] = "June" in email_text or "JUNE" in email_text or "june" in email_text
    facts["month_august"] = "August" in email_text or "AUGUST" in email_text or "august" in email_text
    facts["dr_rivera"] = "Dr. Rivera" in email_text
    facts["coastal_lab"] = "Coastal Vet Epi Lab" in email_text
    facts["brucellosis"] = "brucellosis" in email_text.lower()
    facts["maya"] = "Maya" in email_text
    has_fund = ("Zoonosis Data Catalyst Fund" in email_text) or ("ZDCF" in email_text)
    facts["fund_name_or_acronym"] = has_fund
    facts["6_may"] = bool(re.search(r"\b6 May\b", email_text))
    facts["7_may"] = bool(re.search(r"\b7 May\b", email_text))
    return facts


def _email_facts_preserved_ratio(polished_text: str, facts: dict) -> float:
    checks = []
    if facts.get("amount_7500", False):
        checks.append(bool(re.search(r"7[, ]?500", polished_text)))
    if facts.get("year_2026", False):
        checks.append("2026" in polished_text)
    if facts.get("month_june", False):
        checks.append(_contains_any(polished_text, ["June"]))
    if facts.get("month_august", False):
        checks.append(_contains_any(polished_text, ["August"]))
    if facts.get("dr_rivera", False):
        checks.append(_contains_any(polished_text, ["Dr. Rivera"]))
    if facts.get("coastal_lab", False):
        checks.append(_contains_any(polished_text, ["Coastal Vet Epi Lab"]))
    if facts.get("brucellosis", False):
        checks.append("brucellosis" in polished_text.lower())
    if facts.get("maya", False):
        checks.append(_contains_any(polished_text, ["Maya"]))
    if facts.get("fund_name_or_acronym", False):
        checks.append(_contains_any(polished_text, ["Zoonosis Data Catalyst Fund", "ZDCF"]))
    if facts.get("6_may", False):
        checks.append(bool(re.search(r"\b6 May\b", polished_text)))
    if facts.get("7_may", False):
        checks.append(bool(re.search(r"\b7 May\b", polished_text)))
    if not checks:
        return 0.0
    return sum(1.0 for c in checks if c) / float(len(checks))


def _notes_sections_score(clean_md: str, next_meeting_expected: bool) -> float:
    sections = ["Attendees", "Decisions", "Action Items"]
    if next_meeting_expected:
        sections.append("Next Meeting")
    lines = clean_md.splitlines()
    headings = [l.strip() for l in lines if l.strip().startswith("#")]
    score = 0
    for sec in sections:
        if any(sec.lower() in h.lower() for h in headings):
            score += 1
    return score / len(sections) if sections else 0.0


def _notes_decisions_preserved(clean_md: str) -> float:
    tokens = ["#04", "#07", "#09"]
    found = sum(1 for t in tokens if t in clean_md)
    return found / len(tokens)


def _csv_header_exact(rows, expected_header) -> bool:
    if not rows or len(rows) == 0:
        return False
    header = rows[0]
    return header == expected_header


def _csv_min_rows(rows, min_body_rows: int) -> bool:
    if rows is None or len(rows) < 1:
        return False
    return len(rows) - 1 >= min_body_rows


def _csv_due_dates_iso(rows) -> bool:
    if rows is None or len(rows) < 1:
        return False
    for r in rows[1:]:
        if len(r) < 3:
            return False
        due = r[2].strip()
        if due and not _iso_date(due):
            return False
    return True


def _csv_due_dates_expected(rows, expected_dates: set) -> float:
    if rows is None or len(rows) < 1:
        return 0.0
    dates = set()
    for r in rows[1:]:
        if len(r) >= 3:
            dates.add(r[2].strip())
    if not expected_dates:
        return 1.0
    matched = sum(1 for d in expected_dates if d in dates)
    return matched / len(expected_dates)


def _check_no_duplicate_variants(base_dir: Path, expected_files: set, base_stems: set) -> float:
    if not base_dir.exists():
        return 0.0
    extras_found = []
    for p in base_dir.glob("*"):
        if p.is_file():
            if p.name not in expected_files:
                for stem in base_stems:
                    if p.name.startswith(stem):
                        extras_found.append(p.name)
                        break
    return 1.0 if not extras_found else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "script_references_expected_paths": 0.0,
        "cron_line_exact": 0.0,
        "email_output_exists": 0.0,
        "email_subject_present": 0.0,
        "email_facts_preserved": 0.0,
        "notes_output_exists": 0.0,
        "notes_sections_present": 0.0,
        "notes_next_meeting_correction": 0.0,
        "decisions_preserved": 0.0,
        "action_csv_exists": 0.0,
        "action_csv_header_correct": 0.0,
        "action_items_min_three": 0.0,
        "action_items_due_dates_iso": 0.0,
        "action_items_expected_due_dates": 0.0,
        "funding_edited_exists": 0.0,
        "funding_diff_exists_and_unified": 0.0,
        "funding_edited_shorter": 0.0,
        "funding_headings_preserved": 0.0,
        "idempotency_no_duplicate_variants": 0.0,
    }

    script_path = workspace / "scripts" / "process_weekly.py"
    cron_path = workspace / "schedule" / "cron_example.txt"

    email_in = workspace / "input" / "emails" / "outreach_draft.txt"
    email_out = workspace / "output" / "emails" / "outreach_email_polished.txt"

    notes_in = workspace / "input" / "meetings" / "steering_call_raw.md"
    notes_out = workspace / "output" / "meetings" / "steering_call_notes_clean.md"
    action_csv = workspace / "output" / "meetings" / "action_items.csv"

    brief_in = workspace / "input" / "docs" / "funding_brief.md"
    brief_out = workspace / "output" / "docs" / "funding_brief_edited.md"
    brief_diff = workspace / "output" / "docs" / "funding_brief.diff"

    if script_path.exists() and script_path.is_file():
        scores["script_present"] = 1.0
        try:
            script_text = _read_text_safe(script_path)
            required_refs = [
                "input/emails/outreach_draft.txt",
                "output/emails/outreach_email_polished.txt",
                "input/meetings/steering_call_raw.md",
                "output/meetings/steering_call_notes_clean.md",
                "output/meetings/action_items.csv",
                "input/docs/funding_brief.md",
                "output/docs/funding_brief_edited.md",
                "output/docs/funding_brief.diff",
            ]
            present = sum(1 for r in required_refs if r in script_text)
            scores["script_references_expected_paths"] = present / len(required_refs)
        except Exception:
            scores["script_references_expected_paths"] = 0.0
    else:
        scores["script_present"] = 0.0
        scores["script_references_expected_paths"] = 0.0

    cron_content = _read_lines_safe(cron_path)
    required_cron = "0 9 * * MON python3 scripts/process_weekly.py"
    if cron_content:
        nonempty = [l for l in cron_content if l.strip() != ""]
        if len(nonempty) == 1 and nonempty[0].strip() == required_cron:
            scores["cron_line_exact"] = 1.0
        else:
            scores["cron_line_exact"] = 0.0
    else:
        scores["cron_line_exact"] = 0.0

    polished_email_text = _read_text_safe(email_out)
    if polished_email_text:
        scores["email_output_exists"] = 1.0
        first_line = _first_nonempty_line(polished_email_text)
        if first_line.startswith("Subject:") and len(first_line.replace("Subject:", "").strip()) > 0:
            scores["email_subject_present"] = 1.0
        else:
            scores["email_subject_present"] = 0.0
        input_email_text = _read_text_safe(email_in)
        if input_email_text:
            facts = _email_facts_from_input(input_email_text)
            scores["email_facts_preserved"] = _email_facts_preserved_ratio(polished_email_text, facts)
        else:
            scores["email_facts_preserved"] = 0.0
    else:
        scores["email_output_exists"] = 0.0
        scores["email_subject_present"] = 0.0
        scores["email_facts_preserved"] = 0.0

    clean_notes_text = _read_text_safe(notes_out)
    if clean_notes_text:
        scores["notes_output_exists"] = 1.0
        raw_notes_text = _read_text_safe(notes_in)
        next_meeting_expected = False
        if raw_notes_text:
            next_meeting_expected = "Next check-in" in raw_notes_text
        scores["notes_sections_present"] = _notes_sections_score(clean_notes_text, next_meeting_expected)
        has_0909 = "2026-05-09" in clean_notes_text
        has_1010 = "2026-05-10" in clean_notes_text
        if has_0909 and not has_1010:
            scores["notes_next_meeting_correction"] = 1.0
        else:
            scores["notes_next_meeting_correction"] = 0.0
        scores["decisions_preserved"] = _notes_decisions_preserved(clean_notes_text)
    else:
        scores["notes_output_exists"] = 0.0
        scores["notes_sections_present"] = 0.0
        scores["notes_next_meeting_correction"] = 0.0
        scores["decisions_preserved"] = 0.0

    if action_csv.exists() and action_csv.is_file():
        scores["action_csv_exists"] = 1.0
        rows = _load_csv_rows(action_csv)
        header_ok = _csv_header_exact(rows, ["owner", "task", "due_date"])
        scores["action_csv_header_correct"] = 1.0 if header_ok else 0.0
        scores["action_items_min_three"] = 1.0 if _csv_min_rows(rows, 3) else 0.0
        scores["action_items_due_dates_iso"] = 1.0 if _csv_due_dates_iso(rows) else 0.0
        expected_dates = {"2026-05-03", "2026-05-05", "2026-05-08"}
        scores["action_items_expected_due_dates"] = _csv_due_dates_expected(rows, expected_dates)
    else:
        scores["action_csv_exists"] = 0.0
        scores["action_csv_header_correct"] = 0.0
        scores["action_items_min_three"] = 0.0
        scores["action_items_due_dates_iso"] = 0.0
        scores["action_items_expected_due_dates"] = 0.0

    edited_text = _read_text_safe(brief_out)
    orig_text = _read_text_safe(brief_in)
    if edited_text:
        scores["funding_edited_exists"] = 1.0
        if orig_text:
            if len(edited_text) < len(orig_text):
                scores["funding_edited_shorter"] = 1.0
            else:
                scores["funding_edited_shorter"] = 0.0
            orig_headings = []
            for line in orig_text.splitlines():
                if line.startswith("## "):
                    orig_headings.append(line[3:].strip())
            if orig_headings:
                found_ratio = _find_heading_presence(edited_text, orig_headings)
            else:
                found_ratio = _find_heading_presence(edited_text, ["Context", "Rationale", "Pilot", "Selection", "Reporting", "Risks"])
            scores["funding_headings_preserved"] = found_ratio
        else:
            scores["funding_edited_shorter"] = 0.0
            scores["funding_headings_preserved"] = 0.0
    else:
        scores["funding_edited_exists"] = 0.0
        scores["funding_edited_shorter"] = 0.0
        scores["funding_headings_preserved"] = 0.0

    diff_text = _read_text_safe(brief_diff)
    if diff_text and _has_unified_diff_markers(diff_text):
        scores["funding_diff_exists_and_unified"] = 1.0
    else:
        scores["funding_diff_exists_and_unified"] = 0.0

    emails_dir = workspace / "output" / "emails"
    meetings_dir = workspace / "output" / "meetings"
    docs_dir = workspace / "output" / "docs"

    emails_ok = _check_no_duplicate_variants(
        emails_dir,
        expected_files={"outreach_email_polished.txt"},
        base_stems={"outreach_email_polished"}
    )
    meetings_ok = _check_no_duplicate_variants(
        meetings_dir,
        expected_files={"steering_call_notes_clean.md", "action_items.csv"},
        base_stems={"steering_call_notes_clean", "action_items"}
    )
    docs_ok = _check_no_duplicate_variants(
        docs_dir,
        expected_files={"funding_brief_edited.md", "funding_brief.diff"},
        base_stems={"funding_brief_edited", "funding_brief"}
    )
    scores["idempotency_no_duplicate_variants"] = min(emails_ok, meetings_ok, docs_ok)

    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace_arg = "."
    if len(sys.argv) >= 2:
        workspace_arg = sys.argv[1]
    result = grade([], workspace_arg)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()