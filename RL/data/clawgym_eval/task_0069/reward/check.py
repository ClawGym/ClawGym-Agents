import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(utf-8)
    except Exception:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None


def safe_load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    if not path.exists():
        return None, None
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fields = reader.fieldnames
            return rows, fields
    except Exception:
        return None, None


def email_is_valid(email: str) -> bool:
    if not email:
        return False
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def parse_team_history(path: Path) -> Optional[Dict[str, str]]:
    text = safe_read_text(path)
    if text is None:
        return None
    coach_name = None
    tournament_year = None
    tournament_venue = None
    for line in text.splitlines():
        l = line.strip()
        if l.lower().startswith("coach name:"):
            coach_name = l.split(":", 1)[1].strip()
        elif l.lower().startswith("tournament year:"):
            tournament_year = l.split(":", 1)[1].strip()
        elif l.lower().startswith("tournament venue:"):
            tournament_venue = l.split(":", 1)[1].strip()
    if not (coach_name and tournament_year and tournament_venue):
        return None
    coach_last = coach_name.split()[-1] if coach_name.split() else ""
    return {
        "COACH_FULL": coach_name,
        "COACH_LAST": coach_last,
        "TOURNAMENT_YEAR": tournament_year,
        "VENUE": tournament_venue,
    }


def parse_template_file(path: Path) -> Optional[Tuple[str, str]]:
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    if not lines:
        return None
    first = lines[0]
    if not first.startswith("Subject: "):
        return None
    subject_template = first[len("Subject: "):]
    body_lines = lines[1:]
    if body_lines and body_lines[0].strip() == "":
        body_lines = body_lines[1:]
    body_template = "\n".join(body_lines)
    return subject_template, body_template


def fill_template(template: str, values: Dict[str, str]) -> str:
    result = template
    for k, v in values.items():
        result = result.replace("{" + k + "}", v)
    return result


def normalize_text_for_body(s: str) -> str:
    return " ".join((s or "").split())


def parse_draft_file(path: Path) -> Optional[Tuple[str, str, str]]:
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    if len(lines) != 3:
        return None
    if not lines[0].startswith("To: ") or not lines[1].startswith("Subject: ") or not lines[2].startswith("Body: "):
        return None
    to_email = lines[0][len("To: "):].strip()
    subject = lines[1][len("Subject: "):].strip()
    body = lines[2][len("Body: "):].strip()
    return to_email, subject, body


def parse_validation_log(path: Path) -> Optional[Dict[str, int]]:
    text = safe_read_text(path)
    if text is None:
        return None
    total = None
    valid = None
    invalid = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("total="):
            try:
                total = int(line.split("=", 1)[1].strip())
            except Exception:
                return None
        elif line.startswith("valid="):
            try:
                valid = int(line.split("=", 1)[1].strip())
            except Exception:
                return None
        elif line.startswith("invalid="):
            try:
                invalid = int(line.split("=", 1)[1].strip())
            except Exception:
                return None
    if total is None or valid is None or invalid is None:
        return None
    return {"total": total, "valid": valid, "invalid": invalid}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "clean_csv_exists_and_structure": 0.0,
        "clean_csv_validity_correct": 0.0,
        "validation_log_consistency": 0.0,
        "drafts_for_all_valid": 0.0,
        "no_invalid_drafts": 0.0,
        "drafts_structure_valid": 0.0,
        "drafts_content_correct": 0.0,
        "summary_csv_correct": 0.0,
        "report_json_correct": 0.0,
    }

    # Load inputs and outputs
    contacts_path = workspace / "input" / "contacts.csv"
    contacts_rows, contacts_fields = safe_load_csv(contacts_path)

    clean_csv_path = workspace / "output" / "clean" / "contacts_clean.csv"
    clean_rows, clean_fields = safe_load_csv(clean_csv_path)

    # Check clean CSV structure and existence
    clean_exists = clean_rows is not None and clean_fields is not None
    if clean_exists and contacts_rows is not None:
        has_valid_col = "valid" in clean_fields
        same_count = len(clean_rows) == len(contacts_rows)
        scores["clean_csv_exists_and_structure"] = 1.0 if (has_valid_col and same_count) else 0.0
    else:
        scores["clean_csv_exists_and_structure"] = 0.0

    # Check validity column correctness (only if row counts match)
    if clean_exists and contacts_rows is not None and len(clean_rows) == len(contacts_rows):
        correctness = []
        for c_row, cl_row in zip(contacts_rows, clean_rows):
            email = c_row.get("email", "")
            expected_valid = "true" if email_is_valid(email) else "false"
            got_valid = (cl_row.get("valid", "") or "").strip().lower()
            correctness.append(1.0 if got_valid == expected_valid else 0.0)
        scores["clean_csv_validity_correct"] = (sum(correctness) / len(correctness)) if correctness else 0.0
    else:
        scores["clean_csv_validity_correct"] = 0.0

    # Validation log consistency
    log_path = workspace / "output" / "logs" / "validation.log"
    log_counts = parse_validation_log(log_path)
    if log_counts is not None and clean_exists and contacts_rows is not None:
        clean_valid_count = sum(1 for r in clean_rows if str(r.get("valid", "")).strip().lower() == "true")
        clean_total = len(clean_rows)
        clean_invalid_count = clean_total - clean_valid_count
        ok = (
            log_counts.get("total") == clean_total
            and log_counts.get("valid") == clean_valid_count
            and log_counts.get("invalid") == clean_invalid_count
            and clean_total == len(contacts_rows)
        )
        scores["validation_log_consistency"] = 1.0 if ok else 0.0
    else:
        scores["validation_log_consistency"] = 0.0

    # Parse team info and templates for content checks
    team_history_path = workspace / "input" / "team_history.md"
    team_info = parse_team_history(team_history_path)

    template_player_path = workspace / "input" / "templates" / "template_player.txt"
    template_supporter_path = workspace / "input" / "templates" / "template_supporter.txt"
    tpl_player = parse_template_file(template_player_path)
    tpl_supporter = parse_template_file(template_supporter_path)

    # Gather valid/invalid contacts from clean CSV
    valid_contacts: List[Dict[str, str]] = []
    invalid_contacts: List[Dict[str, str]] = []
    if clean_exists:
        for row in clean_rows:
            if str(row.get("valid", "")).strip().lower() == "true":
                valid_contacts.append(row)
            else:
                invalid_contacts.append(row)

    # Draft files
    drafts_dir = workspace / "output" / "drafts"
    draft_files = []
    if drafts_dir.exists() and drafts_dir.is_dir():
        draft_files = sorted([p for p in drafts_dir.iterdir() if p.is_file() and p.suffix == ".txt"])

    # Expected filenames for valid contacts
    expected_filenames = set()
    valid_map_by_filename = {}
    for r in valid_contacts:
        fn = f"{(r.get('last_name','') or '').strip()}_{(r.get('first_name','') or '').strip()}.txt"
        expected_filenames.add(fn)
        valid_map_by_filename[fn] = r

    actual_filenames = set([p.name for p in draft_files])

    present_valid = expected_filenames.intersection(actual_filenames)
    if clean_exists and len(valid_contacts) > 0:
        scores["drafts_for_all_valid"] = len(present_valid) / len(valid_contacts)
    else:
        scores["drafts_for_all_valid"] = 0.0

    # Ensure no drafts for invalid contacts
    invalid_filenames = set()
    for r in invalid_contacts:
        fn = f"{(r.get('last_name','') or '').strip()}_{(r.get('first_name','') or '').strip()}.txt"
        invalid_filenames.add(fn)
    extra_invalid = invalid_filenames.intersection(actual_filenames)
    if clean_exists:
        scores["no_invalid_drafts"] = 1.0 if len(extra_invalid) == 0 else 0.0
    else:
        scores["no_invalid_drafts"] = 0.0

    # Drafts structure check
    structures = []
    for p in draft_files:
        parsed = parse_draft_file(p)
        structures.append(1.0 if parsed is not None else 0.0)
    scores["drafts_structure_valid"] = (sum(structures) / len(structures)) if draft_files else 0.0

    # Drafts content correctness
    content_correct_flags = []
    if team_info and tpl_player and tpl_supporter and draft_files:
        subj_player, body_player = tpl_player
        subj_support, body_support = tpl_supporter
        for p in draft_files:
            parsed = parse_draft_file(p)
            if parsed is None:
                content_correct_flags.append(0.0)
                continue
            to_email, subj_actual, body_actual_line = parsed
            base = p.name
            contact_row = valid_map_by_filename.get(base)
            if contact_row is None:
                # If a draft corresponds to an invalid contact, content cannot be correct
                content_correct_flags.append(0.0)
                continue
            role = (contact_row.get("role") or "").strip()
            first_name = (contact_row.get("first_name") or "").strip()
            years = (contact_row.get("years") or "").strip()
            email = (contact_row.get("email") or "").strip()
            values = {
                "FIRST": first_name,
                "YEARS_PLAYED": years,
                "TOURNAMENT_YEAR": team_info["TOURNAMENT_YEAR"],
                "VENUE": team_info["VENUE"],
                "COACH_FULL": team_info["COACH_FULL"],
                "COACH_LAST": team_info["COACH_LAST"],
            }
            if role == "player":
                subj_expected = fill_template(subj_player, values)
                body_expected = fill_template(body_player, values)
            else:
                subj_expected = fill_template(subj_support, values)
                body_expected = fill_template(body_support, values)
            subj_ok = subj_actual == subj_expected
            body_ok = normalize_text_for_body(body_actual_line) == normalize_text_for_body(body_expected)
            to_ok = to_email == email
            no_placeholders = ("{" not in subj_actual and "}" not in subj_actual and "{" not in body_actual_line and "}" not in body_actual_line)
            flag = 1.0 if (subj_ok and body_ok and to_ok and no_placeholders) else 0.0
            content_correct_flags.append(flag)
    elif draft_files:
        content_correct_flags = [0.0 for _ in draft_files]

    scores["drafts_content_correct"] = (sum(content_correct_flags) / len(content_correct_flags)) if draft_files else 0.0

    # Summary CSV checks
    summary_csv_path = workspace / "output" / "summary" / "recipients.csv"
    summary_rows, summary_fields = safe_load_csv(summary_csv_path)
    draft_subjects_by_name = {}
    draft_to_emails_by_name = {}
    for p in draft_files:
        parsed = parse_draft_file(p)
        if parsed:
            to_email, subj, _ = parsed
            draft_subjects_by_name[p.name] = subj
            draft_to_emails_by_name[p.name] = to_email

    summary_ok = 0.0
    if summary_rows is not None and summary_fields is not None and draft_files:
        required_cols = ["first_name", "last_name", "email", "role", "template_used", "subject"]
        cols_ok = summary_fields == required_cols
        count_ok = len(summary_rows) == len(draft_files)
        row_flags = []
        if cols_ok and count_ok:
            for row in summary_rows:
                fn = f"{(row.get('last_name') or '').strip()}_{(row.get('first_name') or '').strip()}.txt"
                email = (row.get("email") or "").strip()
                role = (row.get("role") or "").strip()
                template_used = (row.get("template_used") or "").strip()
                subj = (row.get("subject") or "").strip()
                draft_present = fn in draft_subjects_by_name
                subj_match = draft_present and subj == draft_subjects_by_name.get(fn, "")
                email_match = draft_present and email == draft_to_emails_by_name.get(fn, "")
                expected_basename = "template_player.txt" if role == "player" else "template_supporter.txt"
                template_ok = template_used.endswith(expected_basename)
                row_flags.append(1.0 if (draft_present and subj_match and email_match and template_ok) else 0.0)
            per_row = (sum(row_flags) / len(row_flags)) if row_flags else 0.0
            summary_ok = 1.0 if per_row == 1.0 else per_row
        else:
            summary_ok = 0.0
    else:
        summary_ok = 0.0
    scores["summary_csv_correct"] = summary_ok

    # Report JSON checks
    report_json_path = workspace / "output" / "report" / "summary.json"
    report_ok = 0.0
    report = None
    report_text = safe_read_text(report_json_path)
    if report_text is not None:
        try:
            report = json.loads(report_text)
        except Exception:
            report = None
    if report is not None and contacts_rows is not None and clean_exists and log_counts is not None:
        expected_total_contacts = len(contacts_rows)
        expected_total_valid = sum(1 for r in clean_rows if str(r.get("valid", "")).strip().lower() == "true")
        expected_invalid = expected_total_contacts - expected_total_valid
        drafts_by_role: Dict[str, int] = {}
        for p in draft_files:
            r = valid_map_by_filename.get(p.name)
            if r:
                role = (r.get("role") or "").strip()
                drafts_by_role[role] = drafts_by_role.get(role, 0) + 1
        keys_present = all(k in report for k in ["total_contacts", "total_valid", "invalid_skipped", "drafts_written", "by_role"])
        if keys_present:
            conds = []
            conds.append(report.get("total_contacts") == expected_total_contacts)
            conds.append(report.get("total_valid") == expected_total_valid)
            conds.append(report.get("invalid_skipped") == expected_invalid)
            conds.append(report.get("drafts_written") == len(draft_files))
            conds.append(isinstance(report.get("by_role"), dict))
            conds.append(report.get("by_role") == drafts_by_role)
            conds.append(report.get("invalid_skipped") == log_counts.get("invalid"))
            report_ok = 1.0 if all(conds) else 0.0
        else:
            report_ok = 0.0
    else:
        report_ok = 0.0
    scores["report_json_correct"] = report_ok

    # Clamp scores
    for k, v in list(scores.items()):
        try:
            vv = float(v)
        except Exception:
            vv = 0.0
        if vv < 0.0:
            vv = 0.0
        if vv > 1.0:
            vv = 1.0
        scores[k] = vv

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()