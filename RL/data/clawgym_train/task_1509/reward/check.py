import sys
import json
import csv
import re
import subprocess
from pathlib import Path
from io import StringIO


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json_safe(path: Path):
    try:
        text = _read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _read_csv_safe(path: Path):
    try:
        text = _read_text_safe(path)
        if text is None:
            return None, None
        sio = StringIO(text)
        reader = csv.reader(sio)
        rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def _run_parser(workspace: Path, input_rel: str):
    parser = workspace / "tools" / "incident_parser.py"
    input_path = workspace / input_rel
    if not parser.exists() or not input_path.exists():
        return None, None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(parser), str(input_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(workspace),
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception:
        return None, None, None


def _parse_log_diagnostics(log_text: str):
    """
    Returns dict with keys parsed_records, total_lines, errors, warnings if present, else None.
    """
    if not log_text:
        return None
    info_line = None
    for line in log_text.splitlines():
        if "parsed_records=" in line and "total_lines=" in line and "warnings=" in line:
            info_line = line
            break
    if info_line is None:
        return None
    di = {}
    for key in ["parsed_records", "total_lines", "errors", "warnings"]:
        m = re.search(rf"{key}\s*=\s*(\d+)", info_line)
        if not m:
            return None
        di[key] = int(m.group(1))
    return di


def _extract_error_lines(log_text: str):
    if not log_text:
        return []
    errs = []
    for line in log_text.splitlines():
        if line.startswith("ERROR "):
            errs.append(line)
    return errs


def _parse_contacts_yaml(path: Path):
    """
    Minimal YAML parser for the specific contacts.yaml structure.
    Returns dict with keys: research_group, departmental_list, students -> list of emails.
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    sections = {"research_group": [], "departmental_list": [], "students": []}
    current = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        msec = re.match(r"^([A-Za-z_]+)\s*:\s*$", line)
        if msec:
            key = msec.group(1)
            if key in sections:
                current = key
            else:
                current = None
            continue
        if current is None:
            continue
        memail = re.search(r"email\s*:\s*(.+)$", line)
        if memail:
            val = memail.group(1).strip()
            if val.endswith(","):
                val = val[:-1].strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            sections[current].append(val)
    return sections


def _parse_email_file(email_text: str):
    """
    Returns dict: {"to": str or None, "bcc": str or None, "subject": str or None, "body": str}
    """
    result = {"to": None, "bcc": None, "subject": None, "body": ""}
    if email_text is None:
        return result
    lines = email_text.splitlines()
    body_lines = []
    header_done = False
    for line in lines:
        if not header_done:
            lstrip = line.lstrip()
            if lstrip.lower().startswith("to:"):
                result["to"] = lstrip.split(":", 1)[1].strip()
                continue
            if lstrip.lower().startswith("bcc:"):
                result["bcc"] = lstrip.split(":", 1)[1].strip()
                continue
            if lstrip.lower().startswith("subject:"):
                result["subject"] = lstrip.split(":", 1)[1].strip()
                continue
            if lstrip == "" or not any(lstrip.lower().startswith(prefix) for prefix in ("to:", "bcc:", "subject:")):
                header_done = True
                body_lines.append(line)
        else:
            body_lines.append(line)
    result["body"] = "\n".join(body_lines).strip()
    return result


def _severity_counts_from_csv(header, rows):
    if header is None or rows is None:
        return None
    try:
        idx = {name: i for i, name in enumerate(header)}
        sidx = idx["severity"]
    except Exception:
        return None
    counts = {}
    for r in rows:
        if len(r) <= sidx:
            return None
        sev = r[sidx]
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def _line_contains_label_and_count(text: str, label: str, count: int) -> bool:
    if not text:
        return False
    for line in text.splitlines():
        if label in line:
            if re.search(rf"(?<!\d){count}(?!\d)", line):
                return True
    return False


def _csv_text_to_rows(csv_text: str):
    try:
        reader = csv.reader(StringIO(csv_text))
        return list(reader)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    # Initialize scores with alphabetical keys to match CLI sorted output
    scores = {
        "csv_file_valid": 0.0,
        "csv_matches_parser": 0.0,
        "email_body_counts_by_severity": 0.0,
        "email_body_incident_summary": 0.0,
        "email_recipients_correct": 0.0,
        "email_subject_diagnostics_prefix": 0.0,
        "log_diagnostics_present": 0.0,
        "state_file_lists_processed": 0.0,
        "summary_counts_by_severity_correct": 0.0,
        "summary_diagnostics_completeness": 0.0,
        "summary_incident_list_includes_all": 0.0,
        "summary_sections_present": 0.0,
    }

    # Paths
    csv_path = workspace / "out" / "data" / "parsed_incidents_2024Q4.csv"
    log_path = workspace / "out" / "logs" / "2024Q4_parser.log"
    summary_path = workspace / "out" / "summary_2024Q4.md"
    email_path = workspace / "out" / "email_draft_2024Q4.txt"
    state_path = workspace / "out" / "state" / "processed_files.json"
    contacts_path = workspace / "input" / "contacts.yaml"

    # CSV validity
    header, rows = _read_csv_safe(csv_path)
    expected_header = ["plant", "date", "type", "severity", "status", "summary"]
    csv_score = 0.0
    if header is not None and rows is not None:
        if header == expected_header:
            csv_score += 0.5
        if len(rows) == 3:
            csv_score += 0.5
    scores["csv_file_valid"] = csv_score

    # Log diagnostics presence
    log_text = _read_text_safe(log_path)
    log_score = 0.0
    if log_text is not None:
        if re.search(r"INFO:\s*parsed_records=\d+\s+total_lines=\d+\s+errors=\d+\s+warnings=\d+", log_text):
            log_score += 0.5
        if "ERROR line 4: invalid JSON" in log_text:
            log_score += 0.5
    scores["log_diagnostics_present"] = log_score

    # Compare CSV with running the parser directly
    rc, parser_stdout, parser_stderr = _run_parser(workspace, "input/incidents_2024Q4.jsonl")
    if rc is not None and parser_stdout is not None and header is not None and rows is not None:
        got = _read_text_safe(csv_path)
        if got is not None:
            out_rows = _csv_text_to_rows(got)
            ref_rows = _csv_text_to_rows(parser_stdout)
            if out_rows is not None and ref_rows is not None and out_rows == ref_rows:
                scores["csv_matches_parser"] = 1.0

    # Summary checks
    summary_text = _read_text_safe(summary_path)
    if summary_text is not None:
        sections = [
            "Overview",
            "Counts by severity",
            "Incident list",
            "Parser diagnostics",
        ]
        found = 0
        for sec in sections:
            if sec.lower() in summary_text.lower():
                found += 1
        scores["summary_sections_present"] = found / len(sections)

        diag = _parse_log_diagnostics(log_text or "")
        diag_items = ["parsed_records", "total_lines", "errors", "warnings"]
        present_count = 0
        total_checks = 0
        if diag is not None:
            for key in diag_items:
                total_checks += 1
                label_ok = key in summary_text
                val_ok = re.search(rf"(?<!\d){diag[key]}(?!\d)", summary_text) is not None
                if label_ok and val_ok:
                    present_count += 1
        total_checks += 1
        error_line_present = "ERROR line 4: invalid JSON" in (summary_text or "")
        if error_line_present:
            present_count += 1
        csv_row_count = len(rows) if rows is not None else None
        if csv_row_count is not None:
            total_checks += 1
            if re.search(rf"(?<!\d){csv_row_count}(?!\d)", summary_text or ""):
                present_count += 1
        scores["summary_diagnostics_completeness"] = (present_count / total_checks) if total_checks > 0 else 0.0

        inc_score = 0.0
        inc_total = 0
        if header is not None and rows is not None:
            idx = {name: i for i, name in enumerate(header)}
            fields_to_check = ["date", "plant", "type", "severity", "status", "summary"]
            for r in rows:
                inc_total += 1
                parts = []
                for f in fields_to_check:
                    try:
                        parts.append(r[idx[f]])
                    except Exception:
                        parts.append("")
                if all(part == "" or part in summary_text for part in parts):
                    inc_score += 1.0
            if inc_total > 0:
                scores["summary_incident_list_includes_all"] = inc_score / inc_total

        sev_counts = _severity_counts_from_csv(header, rows)
        sev_score = 0.0
        sev_total = 0
        if sev_counts is not None:
            for sev, cnt in sev_counts.items():
                sev_total += 1
                if _line_contains_label_and_count(summary_text, sev, cnt):
                    sev_score += 1.0
            if sev_total > 0:
                scores["summary_counts_by_severity_correct"] = sev_score / sev_total

    # Email checks
    email_text = _read_text_safe(email_path)
    email_info = _parse_email_file(email_text) if email_text is not None else {"to": None, "bcc": None, "subject": None, "body": ""}
    contacts_path = workspace / "input" / "contacts.yaml"
    contacts = _parse_contacts_yaml(contacts_path) if contacts_path.exists() else None

    recipients_score = 0.0
    if contacts is not None and email_info.get("to") is not None:
        to_line = email_info["to"]
        required_to = set(contacts.get("research_group", [])) | set(contacts.get("departmental_list", []))
        to_ok = all(addr in to_line for addr in required_to) and len(required_to) > 0
    else:
        to_ok = False
    if contacts is not None and email_info.get("bcc") is not None:
        bcc_line = email_info["bcc"]
        required_bcc = set(contacts.get("students", []))
        bcc_ok = all(addr in bcc_line for addr in required_bcc) and len(required_bcc) > 0
    else:
        bcc_ok = False
    if to_ok and bcc_ok:
        recipients_score = 1.0
    elif to_ok or bcc_ok:
        recipients_score = 0.5
    else:
        recipients_score = 0.0
    scores["email_recipients_correct"] = recipients_score

    subject = email_info.get("subject") or ""
    diag = _parse_log_diagnostics(log_text or "") if log_text is not None else None
    if diag is not None:
        if diag.get("errors", 0) > 0:
            scores["email_subject_diagnostics_prefix"] = 1.0 if subject.startswith("[Diagnostics: errors present]") else 0.0
        else:
            scores["email_subject_diagnostics_prefix"] = 1.0 if not subject.startswith("[Diagnostics: errors present]") else 0.0
    else:
        scores["email_subject_diagnostics_prefix"] = 0.0

    body = email_info.get("body") or ""
    body_inc_score = 0.0
    body_inc_total = 0
    if header is not None and rows is not None:
        idx = {name: i for i, name in enumerate(header)}
        fields_to_check = ["date", "plant", "type", "severity", "status"]
        for r in rows:
            body_inc_total += 1
            ok = True
            for f in fields_to_check:
                try:
                    val = r[idx[f]]
                except Exception:
                    val = ""
                if val and (val not in body):
                    ok = False
                    break
            if ok:
                body_inc_score += 1.0
        if body_inc_total > 0:
            scores["email_body_incident_summary"] = body_inc_score / body_inc_total

    email_counts_score = 0.0
    email_counts_total = 0
    sev_counts = _severity_counts_from_csv(header, rows) if header is not None and rows is not None else None
    if sev_counts is not None:
        for sev, cnt in sev_counts.items():
            email_counts_total += 1
            if _line_contains_label_and_count(body, sev, cnt):
                email_counts_score += 1.0
        if email_counts_total > 0:
            scores["email_body_counts_by_severity"] = email_counts_score / email_counts_total

    state_obj = _read_json_safe(state_path)
    state_ok = 0.0
    if isinstance(state_obj, list):
        found = False
        for entry in state_obj:
            if isinstance(entry, str) and entry.endswith("incidents_2024Q4.jsonl"):
                found = True
                break
        if found:
            state_ok = 1.0
    scores["state_file_lists_processed"] = state_ok

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()