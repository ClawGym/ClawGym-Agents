import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_lines(path: Path) -> Optional[List[str]]:
    txt = safe_read_text(path)
    if txt is None:
        return None
    # Normalize newlines and strip trailing newline characters
    lines = [line.rstrip("\n\r") for line in txt.splitlines()]
    # Keep even empty lines for strict comparison, but downstream parsers can filter
    return lines


def parse_recipients_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Require expected columns
            if reader.fieldnames is None:
                return None
            expected = ["email", "name", "segment"]
            if [h.strip() for h in reader.fieldnames] != expected:
                # If header not exactly as expected, treat as malformed
                return None
            rows = []
            for row in reader:
                rows.append({k: (row.get(k) or "").strip() for k in expected})
            return rows
    except Exception:
        return None


def classify_email(email: str) -> Tuple[str, str]:
    # Mirror scripts/dry_run_send.py behavior
    local, _, domain = email.partition("@")
    if not local or not domain:
        return ("550", "Invalid mailbox")
    if domain in {"blockedrock.com", "loudblock.net"}:
        return ("BLOCKED", "domain policy (blocked domain)")
    if "invalid" in local:
        return ("550", "Invalid mailbox")
    if domain in {"fullbox.com"}:
        return ("552", "Mailbox full")
    if domain in {"tempfail.com", "greylist.me"}:
        return ("450", "Mailbox busy, try later")
    return ("OK", "")


def compute_expected_command_outputs(recipients_rows: List[Dict[str, str]]) -> Tuple[List[str], List[str], Dict[str, int]]:
    stdout_lines: List[str] = []
    stderr_lines: List[str] = []
    total = 0
    sent = 0
    failed = 0
    for row in recipients_rows:
        email = (row.get("email") or "").strip()
        total += 1
        code, reason = classify_email(email)
        if code == "OK":
            stdout_lines.append(f"SENT,{email}")
            sent += 1
        else:
            stderr_lines.append(f"ERROR,{code},{email},{reason}")
            failed += 1
    stdout_lines.append(f"SUMMARY,sent={sent},failed={failed},total={total}")
    return stdout_lines, stderr_lines, {"sent": sent, "failed": failed, "total": total}


def parse_captured_stdout(lines: List[str]) -> Optional[Tuple[List[str], Dict[str, int]]]:
    # Filter out empty lines
    data_lines = [ln for ln in lines if ln.strip() != ""]
    if not data_lines:
        return None
    if not data_lines[-1].startswith("SUMMARY,"):
        return None
    sent_emails: List[str] = []
    for ln in data_lines[:-1]:
        if not ln.startswith("SENT,"):
            return None
        parts = ln.split(",", 1)
        if len(parts) != 2 or parts[1].strip() == "":
            return None
        sent_emails.append(parts[1].strip())
    # Parse summary
    summary_line = data_lines[-1]
    # Expect format: SUMMARY,sent=X,failed=Y,total=Z
    parts = summary_line.split(",")
    if len(parts) != 4 or parts[0] != "SUMMARY":
        return None
    try:
        sent = int(parts[1].split("=", 1)[1])
        failed = int(parts[2].split("=", 1)[1])
        total = int(parts[3].split("=", 1)[1])
    except Exception:
        return None
    return sent_emails, {"sent": sent, "failed": failed, "total": total}


def parse_captured_stderr(lines: List[str]) -> Optional[List[Dict[str, str]]]:
    # Filter out empty lines
    data_lines = [ln for ln in lines if ln.strip() != ""]
    errors: List[Dict[str, str]] = []
    for ln in data_lines:
        if not ln.startswith("ERROR,"):
            return None
        # Format: ERROR,code,email,reason (reason may contain commas)
        parts = ln.split(",", 3)
        if len(parts) < 4:
            return None
        _, code, email, reason = parts[0], parts[1], parts[2], parts[3]
        errors.append({"code": code.strip(), "email": email.strip(), "reason": reason.strip()})
    return errors


def load_csv_with_header(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return False, None, None
            rows = [dict(row) for row in reader]
        return True, rows, reader.fieldnames
    except Exception:
        return False, None, None


def compute_category(code: str) -> Optional[str]:
    if code == "BLOCKED":
        return "blocked_domain"
    if code and code.isdigit():
        if code.startswith("5"):
            return "hard_bounce"
        if code.startswith("4"):
            return "soft_bounce"
    return None


def domain_of_email(email: str) -> Optional[str]:
    if "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower()


def compute_top_failed_domains(failures: List[Dict[str, str]], top_n: int = 3) -> List[str]:
    counts: Dict[str, int] = defaultdict(int)
    for err in failures:
        dom = domain_of_email(err.get("email", ""))
        if dom:
            counts[dom] += 1
    if not counts:
        return []
    # Sort by count desc, then domain asc
    sorted_items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [d for d, _ in sorted_items[:top_n]]


def subscribers_failed_count(failures: List[Dict[str, str]], recipients_rows: List[Dict[str, str]]) -> int:
    seg_map: Dict[str, str] = { (row.get("email") or "").strip(): (row.get("segment") or "").strip() for row in recipients_rows }
    count = 0
    for err in failures:
        email = (err.get("email") or "").strip()
        if seg_map.get(email) == "subscribers":
            count += 1
    return count


def has_apology_cta(text: str) -> bool:
    t = text.lower()
    # Accept if suggests updating email/address or adding to contacts/safe senders
    if "update" in t and ("address" in t or "email" in t):
        return True
    if "add" in t and ("contacts" in t or "contact list" in t or "address book" in t or "safe senders" in t):
        return True
    if "whitelist" in t or "allowlist" in t:
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize scores dict with all keys set to 0.0
    scores = {
        "stdout_matches_expected": 0.0,
        "stderr_matches_expected": 0.0,
        "bounce_report_exists": 0.0,
        "bounce_report_header_correct": 0.0,
        "bounce_report_content_correct": 0.0,
        "summary_json_exists": 0.0,
        "summary_json_structure_correct": 0.0,
        "summary_json_values_correct": 0.0,
        "apology_email_exists": 0.0,
        "apology_email_subject_present": 0.0,
        "apology_email_mentions_counts_and_domains": 0.0,
        "apology_email_has_call_to_action": 0.0,
        "provider_email_exists": 0.0,
        "provider_email_subject_present": 0.0,
        "provider_email_includes_exit_code_and_breakdown": 0.0,
        "provider_email_lists_blocked_domains": 0.0,
    }

    # Paths
    recipients_path = workspace / "data" / "recipients.csv"
    message_path = workspace / "data" / "message.txt"
    script_path = workspace / "scripts" / "dry_run_send.py"
    output_dir = workspace / "output"
    stdout_path = output_dir / "send_stdout.txt"
    stderr_path = output_dir / "send_stderr.txt"
    bounce_report_path = output_dir / "bounce_report.csv"
    summary_json_path = output_dir / "summary.json"
    apology_email_path = output_dir / "apology_email.txt"
    provider_email_path = output_dir / "provider_email.txt"

    # Load recipients to compute expected outputs
    recipients_rows = parse_recipients_csv(recipients_path) or []

    # Compute expected command outputs if possible
    expected_stdout_lines: Optional[List[str]] = None
    expected_stderr_lines: Optional[List[str]] = None
    expected_summary: Optional[Dict[str, int]] = None
    if recipients_rows and script_path.exists() and message_path.exists():
        exp_out, exp_err, exp_sum = compute_expected_command_outputs(recipients_rows)
        expected_stdout_lines = exp_out
        expected_stderr_lines = exp_err
        expected_summary = exp_sum

    # Load captured outputs
    captured_stdout_lines = safe_read_lines(stdout_path)
    captured_stderr_lines = safe_read_lines(stderr_path)

    # Verify stdout matches expected strictly
    if expected_stdout_lines is not None and captured_stdout_lines is not None:
        # Compare lines ignoring trailing/leading whitespace differences per line
        cap = [ln.strip() for ln in captured_stdout_lines if ln is not None]
        exp = [ln.strip() for ln in expected_stdout_lines]
        if cap == exp:
            scores["stdout_matches_expected"] = 1.0

    # Verify stderr matches expected strictly
    if expected_stderr_lines is not None and captured_stderr_lines is not None:
        cap = [ln.strip() for ln in captured_stderr_lines if ln is not None]
        exp = [ln.strip() for ln in expected_stderr_lines]
        if cap == exp:
            scores["stderr_matches_expected"] = 1.0

    # Parse captured outputs to use as authoritative for subsequent artifacts
    parsed_stdout = None
    parsed_stderr = None
    if captured_stdout_lines is not None:
        parsed_stdout = parse_captured_stdout(captured_stdout_lines)
    if captured_stderr_lines is not None:
        parsed_stderr = parse_captured_stderr(captured_stderr_lines)

    # Prepare failure list and by-category counts from captured outputs
    failures: List[Dict[str, str]] = []
    by_category_counts: Dict[str, int] = {"hard_bounce": 0, "soft_bounce": 0, "blocked_domain": 0}
    blocked_domains_set: set = set()
    if parsed_stderr is not None:
        failures = parsed_stderr
        for err in failures:
            cat = compute_category(err.get("code", ""))
            if cat in by_category_counts:
                by_category_counts[cat] += 1
            if cat == "blocked_domain":
                dom = domain_of_email(err.get("email", ""))
                if dom:
                    blocked_domains_set.add(dom)

    # Check bounce_report.csv existence
    if bounce_report_path.exists():
        scores["bounce_report_exists"] = 1.0

    # Validate bounce_report header and content
    header_ok = False
    rows_ok = False
    if bounce_report_path.exists() and parsed_stderr is not None and recipients_rows:
        ok, rows, header = load_csv_with_header(bounce_report_path)
        if ok and header is not None and rows is not None:
            expected_header = ["email", "category", "code", "reason", "segment"]
            if [h.strip() for h in header] == expected_header:
                header_ok = True
                scores["bounce_report_header_correct"] = 1.0
                # Build expected rows based on captured stderr and recipients.csv
                seg_map = { (row.get("email") or "").strip(): (row.get("segment") or "").strip() for row in recipients_rows }
                expected_rows_list: List[Tuple[str, str, str, str, str]] = []
                for err in failures:
                    email = (err.get("email") or "").strip()
                    code = (err.get("code") or "").strip()
                    reason = (err.get("reason") or "").strip()
                    category = compute_category(code)
                    segment = seg_map.get(email, "")
                    expected_rows_list.append((email, category or "", code, reason, segment))
                # Normalize actual rows
                actual_rows_list: List[Tuple[str, str, str, str, str]] = []
                for r in rows:
                    actual_rows_list.append((
                        (r.get("email") or "").strip(),
                        (r.get("category") or "").strip(),
                        (r.get("code") or "").strip(),
                        (r.get("reason") or "").strip(),
                        (r.get("segment") or "").strip(),
                    ))
                # Compare as multisets (order-agnostic)
                if Counter(expected_rows_list) == Counter(actual_rows_list):
                    rows_ok = True
                    scores["bounce_report_content_correct"] = 1.0

    # Validate summary.json
    if summary_json_path.exists():
        scores["summary_json_exists"] = 1.0

    if summary_json_path.exists():
        try:
            summary_obj = json.loads(safe_read_text(summary_json_path) or "")
            # Structure check
            structure_ok = True
            required_int_fields = ["total_recipients", "total_sent", "total_failed", "exit_code"]
            for fld in required_int_fields:
                if fld not in summary_obj or not isinstance(summary_obj[fld], int):
                    structure_ok = False
            if "by_category" not in summary_obj or not isinstance(summary_obj["by_category"], dict):
                structure_ok = False
            else:
                for key in ["hard_bounce", "soft_bounce", "blocked_domain"]:
                    if key not in summary_obj["by_category"] or not isinstance(summary_obj["by_category"][key], int):
                        structure_ok = False
            if "top_failed_domains" not in summary_obj or not isinstance(summary_obj["top_failed_domains"], list):
                structure_ok = False
            else:
                if any(not isinstance(x, str) for x in summary_obj["top_failed_domains"]):
                    structure_ok = False
                # Up to 3 domains
                if len(summary_obj["top_failed_domains"]) > 3:
                    structure_ok = False
            if "subscribers_failed_count" not in summary_obj or not isinstance(summary_obj["subscribers_failed_count"], int):
                structure_ok = False

            if structure_ok:
                scores["summary_json_structure_correct"] = 1.0

            # Values check (based on captured outputs)
            values_ok = False
            if parsed_stdout is not None and parsed_stderr is not None and recipients_rows:
                sent_emails, summary_counts = parsed_stdout
                # Totals should match summary line
                totals_match = (
                    summary_obj.get("total_recipients") == summary_counts["total"]
                    and summary_obj.get("total_sent") == summary_counts["sent"]
                    and summary_obj.get("total_failed") == summary_counts["failed"]
                )
                # Exit code: 1 if any failures else 0
                expected_exit = 1 if summary_counts["failed"] > 0 else 0
                exit_match = summary_obj.get("exit_code") == expected_exit
                # by_category match
                bc = summary_obj.get("by_category", {})
                bycat_match = all(bc.get(k) == by_category_counts.get(k, -1) for k in ["hard_bounce", "soft_bounce", "blocked_domain"])
                # top_failed_domains match computed
                expected_top = compute_top_failed_domains(failures, top_n=3)
                top_match = summary_obj.get("top_failed_domains") == expected_top
                # subscribers_failed_count match
                expected_sub_fail = subscribers_failed_count(failures, recipients_rows)
                subs_match = summary_obj.get("subscribers_failed_count") == expected_sub_fail

                if totals_match and exit_match and bycat_match and top_match and subs_match:
                    values_ok = True

            if values_ok:
                scores["summary_json_values_correct"] = 1.0
        except Exception:
            # leave as defaults
            pass

    # Validate apology_email.txt
    if apology_email_path.exists():
        scores["apology_email_exists"] = 1.0
        apology_text = safe_read_text(apology_email_path) or ""
        lines = [ln for ln in (apology_text.splitlines() if apology_text else [])]
        # Subject line must be present (first non-empty line starts with "Subject:")
        non_empty_lines = [ln for ln in lines if ln.strip() != ""]
        if non_empty_lines and non_empty_lines[0].strip().startswith("Subject:"):
            scores["apology_email_subject_present"] = 1.0
        # Mentions subscribers_failed_count and top_failed_domains
        mentions_ok = False
        if summary_json_path.exists():
            try:
                summary_obj = json.loads(safe_read_text(summary_json_path) or "")
                subs_failed = summary_obj.get("subscribers_failed_count")
                top_domains = summary_obj.get("top_failed_domains", [])
                if isinstance(subs_failed, int) and isinstance(top_domains, list):
                    text_lower = apology_text.lower()
                    subs_ok = str(subs_failed) in apology_text
                    domains_ok = all(isinstance(dom, str) and dom in apology_text for dom in top_domains)
                    if subs_ok and domains_ok:
                        mentions_ok = True
            except Exception:
                mentions_ok = False
        if mentions_ok:
            scores["apology_email_mentions_counts_and_domains"] = 1.0
        # Call-to-action present
        if apology_text and has_apology_cta(apology_text):
            scores["apology_email_has_call_to_action"] = 1.0

    # Validate provider_email.txt
    if provider_email_path.exists():
        scores["provider_email_exists"] = 1.0
        provider_text = safe_read_text(provider_email_path) or ""
        lines = [ln for ln in (provider_text.splitlines() if provider_text else [])]
        non_empty = [ln for ln in lines if ln.strip() != ""]
        if non_empty and non_empty[0].strip().startswith("Subject:"):
            scores["provider_email_subject_present"] = 1.0

        includes_ok = False
        lists_blocked_ok = False
        if summary_json_path.exists():
            try:
                summary_obj = json.loads(safe_read_text(summary_json_path) or "")
                # exit_code presence
                exit_code = summary_obj.get("exit_code")
                by_cat = summary_obj.get("by_category", {})
                if isinstance(exit_code, int) and isinstance(by_cat, dict):
                    text_lower = provider_text.lower()
                    exit_ok = ("exit" in text_lower) and (str(exit_code) in provider_text)
                    hb = by_cat.get("hard_bounce")
                    sb = by_cat.get("soft_bounce")
                    bd = by_cat.get("blocked_domain")
                    bycat_ok = all(k in provider_text for k in ["hard_bounce", "soft_bounce", "blocked_domain"])
                    # Also check that the corresponding numbers appear somewhere in text
                    nums_ok = all(isinstance(v, int) and str(v) in provider_text for v in [hb, sb, bd])
                    if exit_ok and bycat_ok and nums_ok:
                        includes_ok = True
                # blocked domains list
                blocked_domains = set()
                # Derive from captured stderr for accuracy
                if parsed_stderr is not None:
                    for err in failures:
                        if compute_category(err.get("code", "")) == "blocked_domain":
                            dom = domain_of_email(err.get("email", ""))
                            if dom:
                                blocked_domains.add(dom)
                else:
                    # Fallback: compute from recipients if needed
                    if recipients_rows:
                        for row in recipients_rows:
                            code, _ = classify_email((row.get("email") or "").strip())
                            if code == "BLOCKED":
                                dom = domain_of_email((row.get("email") or "").strip())
                                if dom:
                                    blocked_domains.add(dom)
                if provider_text and all(dom in provider_text for dom in blocked_domains):
                    lists_blocked_ok = True
            except Exception:
                pass

        if includes_ok:
            scores["provider_email_includes_exit_code_and_breakdown"] = 1.0
        if lists_blocked_ok:
            scores["provider_email_lists_blocked_domains"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()