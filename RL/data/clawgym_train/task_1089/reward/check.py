import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_jsonl_with_malformed(path: Path) -> Tuple[List[dict], List[Tuple[int, str]], int]:
    """
    Returns (valid_records, malformed[(line_no, raw_line)], total_lines)
    """
    valid = []
    malformed = []
    total = 0
    if not path.exists():
        return valid, malformed, total
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return valid, malformed, total
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        total += 1
        stripped = line.rstrip("\n")
        try:
            rec = json.loads(stripped)
            valid.append(rec)
        except Exception:
            malformed.append((idx, stripped))
    return valid, malformed, total


def load_contacts_csv(path: Path) -> Dict[str, str]:
    mapping = {}
    if not path.exists():
        return mapping
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                county = (row.get("county") or "").strip()
                email = (row.get("clerk_email") or "").strip()
                if county and email:
                    mapping[county] = email
    except Exception:
        return {}
    return mapping


def list_email_txts(emails_dir: Path) -> List[Path]:
    if not emails_dir.exists():
        return []
    return sorted([p for p in emails_dir.iterdir() if p.is_file() and p.suffix == ".txt"])


def parse_email(path: Path) -> Optional[Dict[str, str]]:
    content = read_text_safe(path)
    if content is None:
        return None
    lines = content.splitlines()
    if len(lines) < 3:
        return {"to": "", "subject": "", "body": "", "raw": content}
    to_line = lines[0]
    subj_line = lines[1]
    blank_ok = (lines[2].strip() == "")
    body = "\n".join(lines[3:]) if blank_ok else "\n".join(lines[2:])
    return {"to": to_line, "subject": subj_line, "body": body, "raw": content, "has_blank_line": blank_ok}


def count_words(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def load_json_safe(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "emails_expected_files": 0.0,
        "emails_headers_structure": 0.0,
        "emails_bodies_requirements": 0.0,
        "sms_template_constraints": 0.0,
        "errors_log_format_and_content": 0.0,
        "error_analysis_content": 0.0,
        "summary_counts": 0.0,
        "summary_events_by_type_counts": 0.0,
        "summary_emails_created_consistency": 0.0,
        "summary_internal_consistency": 0.0,
    }

    # Load inputs to compute expected results
    feed_path = workspace / "input" / "status_feed.jsonl"
    contacts_path = workspace / "input" / "county_contacts.csv"
    raw_msg_path = workspace / "input" / "raw_message.txt"  # not used for grading directly
    error_snippet_path = workspace / "input" / "error_snippet.txt"

    valid_records, malformed, total_lines = load_jsonl_with_malformed(feed_path)
    contacts = load_contacts_csv(contacts_path)

    # Compute expected events_by_type from valid records
    expected_events_by_type: Dict[str, int] = {}
    for rec in valid_records:
        event = rec.get("event")
        if isinstance(event, str):
            expected_events_by_type[event] = expected_events_by_type.get(event, 0) + 1

    # Targeted events for emails
    targeted_events = []
    for rec in valid_records:
        event = rec.get("event")
        if event in {"signature_mismatch", "rejected"}:
            voter_id = rec.get("voter_id")
            county = rec.get("county")
            ts = rec.get("timestamp")
            if isinstance(voter_id, str) and isinstance(county, str) and isinstance(ts, str):
                targeted_events.append({
                    "voter_id": voter_id,
                    "event": event,
                    "county": county,
                    "timestamp": ts,
                    "email": contacts.get(county, ""),
                    "expected_filename": f"{voter_id}_{event}.txt"
                })

    expected_email_filenames = {te["expected_filename"] for te in targeted_events}

    # Check emails exist and names
    emails_dir = workspace / "out" / "emails"
    email_files = list_email_txts(emails_dir)
    actual_email_names = {p.name for p in email_files}

    if expected_email_filenames:
        # Score equals 1.0 only if exact match of expected set
        scores["emails_expected_files"] = 1.0 if actual_email_names == expected_email_filenames else 0.0
    else:
        # If no expected emails because inputs missing or no targeted events, score 0.0
        scores["emails_expected_files"] = 0.0

    # Check email headers and structure
    if expected_email_filenames and email_files:
        header_checks = []
        for te in targeted_events:
            fname = te["expected_filename"]
            fpath = emails_dir / fname
            if not fpath.exists():
                header_checks.append(0.0)
                continue
            parsed = parse_email(fpath)
            if parsed is None:
                header_checks.append(0.0)
                continue
            to_ok = parsed.get("to", "").strip() == f"To: {te['email']}" and te['email'] != ""
            subj_ok = parsed.get("subject", "").strip() == f"Subject: Ballot issue for voter {te['voter_id']}: {te['event']}"
            blank_ok = parsed.get("has_blank_line", False) is True
            header_checks.append(1.0 if (to_ok and subj_ok and blank_ok) else 0.0)
        if header_checks:
            scores["emails_headers_structure"] = sum(header_checks) / len(header_checks)
        else:
            scores["emails_headers_structure"] = 0.0
    else:
        scores["emails_headers_structure"] = 0.0

    # Check email body content requirements
    if expected_email_filenames and email_files:
        body_checks = []
        for te in targeted_events:
            fname = te["expected_filename"]
            fpath = emails_dir / fname
            if not fpath.exists():
                body_checks.append(0.0)
                continue
            parsed = parse_email(fpath)
            if parsed is None:
                body_checks.append(0.0)
                continue
            body = parsed.get("body", "")
            raw = parsed.get("raw", "")
            # Requirements:
            # - Include county name
            county_ok = te["county"] in body
            # - Include timestamp
            ts_ok = te["timestamp"] in body
            # - Include exact phrase "please advise on next steps"
            phrase_ok = "please advise on next steps" in body
            # - Be 180 words or fewer
            words_ok = count_words(body) <= 180
            # - Do not contain any exclamation marks
            excl_ok = "!" not in raw
            body_checks.append(1.0 if (county_ok and ts_ok and phrase_ok and words_ok and excl_ok) else 0.0)
        if body_checks:
            scores["emails_bodies_requirements"] = sum(body_checks) / len(body_checks)
        else:
            scores["emails_bodies_requirements"] = 0.0
    else:
        scores["emails_bodies_requirements"] = 0.0

    # SMS template constraints
    sms_path = workspace / "out" / "templates" / "vbm_reassurance_sms.txt"
    sms_text = read_text_safe(sms_path)
    if sms_text is not None:
        length_ok = len(sms_text) <= 480
        has_phrase1 = "Utah vote-by-mail" in sms_text
        has_phrase2 = "check your ballot status" in sms_text
        has_placeholder = "{ballot_status_link}" in sms_text
        excl_ok = "!" not in sms_text
        scores["sms_template_constraints"] = 1.0 if (length_ok and has_phrase1 and has_phrase2 and has_placeholder and excl_ok) else 0.0
    else:
        scores["sms_template_constraints"] = 0.0

    # errors.log content
    errors_log_path = workspace / "out" / "errors.log"
    errors_text = read_text_safe(errors_log_path)
    if errors_text is not None and total_lines > 0:
        # Expected error lines for malformed input lines
        expected_error_lines = [f"line {ln}: {text}" for (ln, text) in malformed]
        actual_lines = [l.rstrip("\n") for l in errors_text.splitlines() if l.strip() != ""]
        # Check set equality and count equality
        if set(actual_lines) == set(expected_error_lines) and len(actual_lines) == len(expected_error_lines):
            scores["errors_log_format_and_content"] = 1.0
        else:
            scores["errors_log_format_and_content"] = 0.0
    else:
        # If inputs missing, we cannot validate; score 0.0
        scores["errors_log_format_and_content"] = 0.0

    # error_analysis.md checks
    analysis_path = workspace / "out" / "error_analysis.md"
    analysis_text = read_text_safe(analysis_path)
    ea_score = 0.0
    if analysis_text is not None:
        lines = analysis_text.splitlines()
        # Heading check
        heading_ok = len(lines) >= 1 and lines[0].strip() == "Error analysis"
        # malformed lines identified (line numbers from feed)
        malformed_nums = {ln for ln, _ in malformed}
        if malformed_nums:
            l5_ok = any(re.search(r"\bline\s+5\b", l, flags=re.IGNORECASE) for l in lines) if 5 in malformed_nums else True
            l8_ok = any(re.search(r"\bline\s+8\b", l, flags=re.IGNORECASE) for l in lines) if 8 in malformed_nums else True
        else:
            l5_ok = False
            l8_ok = False
        # Quote at least one exact error message line from input/error_snippet.txt
        snippet_text = read_text_safe(error_snippet_path) or ""
        snippet_lines = [l for l in snippet_text.splitlines() if l.strip() != ""]
        candidate_error_lines = [l for l in snippet_lines if l.startswith("json.decoder.JSONDecodeError")]
        if not candidate_error_lines:
            candidate_error_lines = snippet_lines
        quote_ok = any(cand in analysis_text for cand in candidate_error_lines)
        # Mentions likely causes (comma/comment) and handling (skip/ignored/handle)
        causes_ok = re.search(r"\bcomma\b", analysis_text, flags=re.IGNORECASE) is not None and re.search(r"\bcomment\b", analysis_text, flags=re.IGNORECASE) is not None
        handling_ok = any(re.search(w, analysis_text, flags=re.IGNORECASE) for w in [r"\bskip\b", r"\bskipped\b", r"\bignore\b", r"\bignored\b", r"\bhandle\b", r"\bhandled\b"])
        parts = [
            1.0 if heading_ok else 0.0,
            1.0 if l5_ok else 0.0,
            1.0 if l8_ok else 0.0,
            1.0 if quote_ok else 0.0,
            1.0 if (causes_ok and handling_ok) else 0.0
        ]
        ea_score = sum(parts) / 5.0
    scores["error_analysis_content"] = ea_score

    # summary.json checks
    summary_path = workspace / "out" / "summary.json"
    summary = load_json_safe(summary_path)
    if summary is not None and total_lines > 0:
        # lines_total and lines_malformed
        lt_ok = isinstance(summary.get("lines_total"), int) and summary.get("lines_total") == total_lines
        lm_ok = isinstance(summary.get("lines_malformed"), int) and summary.get("lines_malformed") == len(malformed)
        scores["summary_counts"] = 1.0 if (lt_ok and lm_ok) else 0.0

        # events_by_type
        ebt = summary.get("events_by_type")
        ebt_ok = isinstance(ebt, dict)
        if ebt_ok:
            per_key_ok = []
            for k, v in expected_events_by_type.items():
                per_key_ok.append(k in ebt and isinstance(ebt[k], int) and ebt[k] == v)
            # Also ensure total of ebt values equals valid records count
            ebt_sum_ok = sum(v for v in ebt.values() if isinstance(v, int)) == len(valid_records)
            ebt_overall_ok = all(per_key_ok) and ebt_sum_ok
            scores["summary_events_by_type_counts"] = 1.0 if ebt_overall_ok else 0.0
        else:
            scores["summary_events_by_type_counts"] = 0.0

        # emails_created consistency
        emails_created = summary.get("emails_created")
        expected_email_count = len(expected_email_filenames)
        actual_email_count = len(actual_email_names)
        ec_ok = isinstance(emails_created, int) and emails_created == expected_email_count == actual_email_count
        scores["summary_emails_created_consistency"] = 1.0 if ec_ok else 0.0

        # internal consistency: lines_total == lines_malformed + valid count
        internal_ok = (summary.get("lines_total") == summary.get("lines_malformed") + len(valid_records))
        scores["summary_internal_consistency"] = 1.0 if internal_ok else 0.0
    else:
        scores["summary_counts"] = 0.0
        scores["summary_events_by_type_counts"] = 0.0
        scores["summary_emails_created_consistency"] = 0.0
        scores["summary_internal_consistency"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()