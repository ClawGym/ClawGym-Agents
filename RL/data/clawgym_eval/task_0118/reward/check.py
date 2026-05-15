import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def parse_yaml_config(path: Path) -> Dict[str, Any]:
    # Minimal parser tailored to the provided YAML
    cfg: Dict[str, Any] = {
        "sign_off": None,
        "recipients": {},
        "subject_prefixes": set(),
        "group_subject_prefix": None,
        "individual_subject_prefix": None,
    }
    text = safe_read_text(path)
    if text is None:
        return cfg

    lines = text.splitlines()
    in_recipients = False
    rec_indent_level = None
    context_stack: List[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        m_signoff = re.match(r"^\s*sign_off:\s*(.+)$", line)
        if m_signoff:
            val = m_signoff.group(1).strip()
            val = val.strip("'\"")
            cfg["sign_off"] = val

        if re.match(r"^\s*recipients:\s*$", line):
            in_recipients = True
            rec_indent_level = len(line) - len(line.lstrip(" "))
            continue

        if re.match(r"^\s*reply_templates:\s*$", line):
            context_stack = ["reply_templates"]
            continue

        if context_stack and context_stack[-1] == "reply_templates":
            m_group = re.match(r"^\s*group:\s*$", line)
            m_individual = re.match(r"^\s*individual:\s*$", line)
            if m_group:
                context_stack = ["reply_templates", "group"]
                continue
            if m_individual:
                context_stack = ["reply_templates", "individual"]
                continue
            m_subj = re.match(r"^\s*subject_prefix:\s*(.+)$", line)
            if m_subj and len(context_stack) == 2:
                val = m_subj.group(1).strip()
                val = val.strip("'\"")
                if context_stack[-1] == "group":
                    cfg["group_subject_prefix"] = val
                elif context_stack[-1] == "individual":
                    cfg["individual_subject_prefix"] = val
                cfg["subject_prefixes"].add(val)

        if in_recipients:
            current_indent = len(line) - len(line.lstrip(" "))
            if stripped == "" or (rec_indent_level is not None and current_indent <= rec_indent_level and not re.match(r"^\s*recipients:\s*$", line)):
                in_recipients = False
            else:
                m_rec = re.match(r'^\s+["\']?(.+?)["\']?\s*:\s*["\']?(.+?)["\']?\s*$', line)
                if m_rec:
                    key = m_rec.group(1)
                    val = m_rec.group(2)
                    cfg["recipients"][key] = val

    return cfg


def parse_message_file(path: Path) -> Optional[Dict[str, str]]:
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    headers = {}
    body_lines: List[str] = []
    in_body = False
    for line in lines:
        if in_body:
            body_lines.append(line)
        else:
            if line.startswith("Body:"):
                in_body = True
                continue
            m = re.match(r"^(From|To|Timestamp|Subject):\s*(.*)$", line)
            if m:
                headers[m.group(1)] = m.group(2).strip()
    required = ["From", "To", "Timestamp", "Subject"]
    if not all(k in headers for k in required):
        return None
    body = "\n".join(body_lines).strip()
    return {
        "From": headers["From"],
        "To": headers["To"],
        "Timestamp": headers["Timestamp"],
        "Subject": headers["Subject"],
        "Body": body,
    }


def count_words(text: str) -> int:
    if not text:
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def parse_reply_file(path: Path) -> Optional[Dict[str, Any]]:
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    if len(lines) < 2:
        return None
    to_line = lines[0].strip()
    subj_line = lines[1].strip()
    if not to_line.startswith("To: ") or not subj_line.startswith("Subject: "):
        return None
    to_value = to_line[len("To: "):].strip()
    subject_value = subj_line[len("Subject: "):].strip()
    body = "\n".join(lines[2:]).strip()
    return {"to": to_value, "subject": subject_value, "body": body}


def parse_index_csv(path: Path) -> Optional[Tuple[bool, List[Dict[str, str]]]]:
    text = safe_read_text(path)
    if text is None:
        return None
    try:
        rows: List[List[str]] = []
        rdr = csv.reader(text.splitlines())
        for r in rdr:
            if r:
                rows.append(r)
        if not rows:
            return (False, [])
        expected_headers = ["input_file", "from", "to", "timestamp", "reply_file", "summary_file", "send_status_file", "send_status"]
        header_present = False
        start_idx = 0
        if rows and len(rows[0]) == 8 and [c.strip() for c in rows[0]] == expected_headers:
            header_present = True
            start_idx = 1
        records: List[Dict[str, str]] = []
        for r in rows[start_idx:]:
            if len(r) != 8:
                return None
            record = dict(zip(expected_headers, [c.strip() for c in r]))
            records.append(record)
        return (header_present, records)
    except Exception:
        return None


def summary_preserves_details(text: str, required_at_least: int, tokens: List[str]) -> bool:
    low = text.lower()
    count = 0
    for t in tokens:
        if t.lower() in low:
            count += 1
    return count >= required_at_least


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tool_script_present": 0.0,
        "ledger_exists_and_no_duplicates": 0.0,
        "ledger_has_two_rows_for_inbox": 0.0,
        "ledger_rows_match_fields_and_paths": 0.0,
        "emily_summary_header_and_limits": 0.0,
        "emily_summary_details_preserved": 0.0,
        "daniel_summary_header_and_limits": 0.0,
        "daniel_summary_details_preserved": 0.0,
        "emily_reply_headers_and_subject": 0.0,
        "emily_reply_body_limits_and_signoff": 0.0,
        "daniel_reply_headers_and_subject": 0.0,
        "daniel_reply_body_limits_and_signoff": 0.0,
        "emily_send_status_ok_and_consistent": 0.0,
        "daniel_send_status_ok_and_consistent": 0.0,
        "ledger_paths_and_status_consistent_with_outputs": 0.0,
    }

    # Check tool script existence
    tool_script = workspace / "tools" / "auto_respond.py"
    if tool_script.is_file():
        try:
            if tool_script.read_text(encoding="utf-8").strip():
                scores["tool_script_present"] = 1.0
        except Exception:
            pass

    # Load config
    config_path = workspace / "input" / "config.yaml"
    config = parse_yaml_config(config_path)

    # Inbox files (expected)
    inbox_dir = workspace / "input" / "inbox"
    inbox_files = [
        inbox_dir / "2026-04-10_emily_group.txt",
        inbox_dir / "2026-04-12_daniel_individual.txt",
    ]
    messages: Dict[str, Dict[str, str]] = {}
    for p in inbox_files:
        msg = parse_message_file(p)
        if msg:
            messages[p.name] = msg

    # Paths expectations
    def expected_paths_for(inbox_file: Path) -> Dict[str, Path]:
        base = inbox_file.stem
        return {
            "summary": workspace / "output" / "cleaned" / f"{base}_summary.txt",
            "reply": workspace / "output" / "replies" / f"{base}_reply.txt",
            "send_status": workspace / "output" / "send_status" / f"{base}.json",
        }

    # Parse index.csv
    index_path = workspace / "output" / "index.csv"
    index_parsed = parse_index_csv(index_path)
    if index_parsed is not None:
        header_present, records = index_parsed
        input_files_list = [rec.get("input_file", "") for rec in records]
        if all(r.get("input_file") for r in records) and len(set(input_files_list)) == len(input_files_list):
            scores["ledger_exists_and_no_duplicates"] = 1.0

        expected_inputs = {str(Path("input") / "inbox" / p.name) for p in inbox_files}
        found_inputs = set(input_files_list)
        if expected_inputs.issubset(found_inputs):
            scores["ledger_has_two_rows_for_inbox"] = 1.0

        fields_ok = True
        paths_ok = True
        for p in inbox_files:
            msg = messages.get(p.name)
            expected_input_str = str(Path("input") / "inbox" / p.name)
            recs = [r for r in records if r.get("input_file") == expected_input_str]
            if not recs:
                fields_ok = False
                paths_ok = False
                continue
            rec = recs[0]
            if msg is None:
                fields_ok = False
            else:
                if rec.get("from") != msg["From"] or rec.get("to") != msg["To"] or rec.get("timestamp") != msg["Timestamp"]:
                    fields_ok = False
            exp_paths = expected_paths_for(p)
            try:
                summary_rel = str(exp_paths["summary"].relative_to(workspace))
                reply_rel = str(exp_paths["reply"].relative_to(workspace))
                send_rel = str(exp_paths["send_status"].relative_to(workspace))
            except Exception:
                paths_ok = False
                continue
            if rec.get("summary_file") != summary_rel:
                paths_ok = False
            if rec.get("reply_file") != reply_rel:
                paths_ok = False
            if rec.get("send_status_file") != send_rel:
                paths_ok = False
            if not exp_paths["summary"].is_file() or not exp_paths["reply"].is_file() or not exp_paths["send_status"].is_file():
                paths_ok = False

        if fields_ok:
            scores["ledger_rows_match_fields_and_paths"] = 1.0

        if paths_ok:
            scores["ledger_paths_and_status_consistent_with_outputs"] = 1.0

    # Summary checks
    for p in inbox_files:
        exp_paths = expected_paths_for(p)
        summary_path = exp_paths["summary"]
        msg = messages.get(p.name)
        if not summary_path.is_file() or msg is None:
            continue
        text = safe_read_text(summary_path) or ""
        lines = text.splitlines()
        if not lines:
            continue
        header_expected = f"Summary for {msg['From']} at {msg['Timestamp']}"
        body_text = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        words = count_words(body_text)
        header_ok = (lines[0].strip() == header_expected)
        limit_ok = (words > 0 and words <= 120)
        if p.name == "2026-04-10_emily_group.txt":
            if header_ok and limit_ok:
                scores["emily_summary_header_and_limits"] = 1.0
            tokens = ["Riverside Park", "Saturday", "12:30", "11:45", "front lobby", "ride", "sandwiches", "checkerboard"]
            if summary_preserves_details(text, 2, tokens):
                scores["emily_summary_details_preserved"] = 1.0
        elif p.name == "2026-04-12_daniel_individual.txt":
            if header_ok and limit_ok:
                scores["daniel_summary_header_and_limits"] = 1.0
            tokens = ["Wednesday", "muffins", "printer", "ink", "tonight", "afternoon", "tai chi"]
            if summary_preserves_details(text, 1, tokens):
                scores["daniel_summary_details_preserved"] = 1.0

    # Reply checks
    recipients_map = config.get("recipients", {}) if isinstance(config.get("recipients"), dict) else {}
    sign_off = config.get("sign_off")
    subj_prefixes = set()
    if config.get("group_subject_prefix"):
        subj_prefixes.add(config["group_subject_prefix"])
    if config.get("individual_subject_prefix"):
        subj_prefixes.add(config["individual_subject_prefix"])
    if not subj_prefixes and config.get("subject_prefixes"):
        subj_prefixes = set(config["subject_prefixes"])

    for p in inbox_files:
        exp_paths = expected_paths_for(p)
        reply_path = exp_paths["reply"]
        msg = messages.get(p.name)
        rep = parse_reply_file(reply_path) if reply_path.is_file() else None
        if msg is None or rep is None:
            continue
        expected_to_name = msg["To"]
        expected_recipient_email = recipients_map.get(expected_to_name)
        allowed_subjects = set()
        if subj_prefixes:
            for pr in subj_prefixes:
                allowed_subjects.add(f"{pr}{msg['Subject']}")
        else:
            allowed_subjects.add(f"Re: {msg['Subject']}")

        headers_ok = True
        if expected_recipient_email:
            headers_ok = headers_ok and (rep["to"] == expected_recipient_email)
        else:
            headers_ok = False
        headers_ok = headers_ok and (rep["subject"] in allowed_subjects)

        body = rep["body"].strip()
        word_ok = count_words(body) <= 120 and count_words(body) > 0
        signoff_ok = False
        if isinstance(sign_off, str):
            body_lines = [ln for ln in body.splitlines() if ln.strip() != ""]
            if body_lines:
                signoff_ok = (body_lines[-1].strip() == sign_off.strip())

        if p.name == "2026-04-10_emily_group.txt":
            if headers_ok:
                scores["emily_reply_headers_and_subject"] = 1.0
            if word_ok and signoff_ok:
                scores["emily_reply_body_limits_and_signoff"] = 1.0
        elif p.name == "2026-04-12_daniel_individual.txt":
            if headers_ok:
                scores["daniel_reply_headers_and_subject"] = 1.0
            if word_ok and signoff_ok:
                scores["daniel_reply_body_limits_and_signoff"] = 1.0

    # Send status checks
    for p in inbox_files:
        exp_paths = expected_paths_for(p)
        status_path = exp_paths["send_status"]
        msg = messages.get(p.name)
        st = safe_load_json(status_path) if status_path.is_file() else None
        if msg is None or st is None:
            continue
        recipients_map = config.get("recipients", {}) if isinstance(config.get("recipients"), dict) else {}
        expected_recipient_email = recipients_map.get(msg["To"])
        expected_input_str = str(Path("input") / "inbox" / p.name)
        base_ok = (
            isinstance(st, dict)
            and st.get("input_file") == expected_input_str
            and st.get("recipient") == expected_recipient_email
            and "status" in st
            and "reason" in st
            and "exit_code" in st
            and "stdout" in st
            and "stderr" in st
        )
        if not base_ok:
            continue

        status = st.get("status")
        reason = st.get("reason", "")
        exit_code = st.get("exit_code")
        stdout = st.get("stdout", "")
        stderr = st.get("stderr", "")

        # Determine expected outcome based on simulate_send.sh logic
        # bounce or invalid -> error; otherwise ok assuming headers and size limits are satisfied
        ok_expected = True
        if isinstance(expected_recipient_email, str) and ("bounce" in expected_recipient_email or "invalid" in expected_recipient_email):
            ok_expected = False

        status_ok = False
        if ok_expected:
            # Expect success: exit_code 0, stdout with OK:, reason mentions queued
            status_ok = (status == "ok" and exit_code == 0 and "OK:" in stdout and "queued" in reason)
        else:
            # Expect error: non-zero exit, stderr with ERROR:, reason reflects error message
            status_ok = (status == "error" and isinstance(exit_code, int) and exit_code != 0 and "ERROR:" in stderr and len(reason.strip()) > 0)

        if p.name == "2026-04-10_emily_group.txt":
            if base_ok and status_ok:
                scores["emily_send_status_ok_and_consistent"] = 1.0
        elif p.name == "2026-04-12_daniel_individual.txt":
            if base_ok and status_ok:
                scores["daniel_send_status_ok_and_consistent"] = 1.0

    # Cross-check ledger send_status matches JSON
    if index_parsed is not None:
        _, records = index_parsed
        all_consistent = True
        for p in inbox_files:
            exp_paths = expected_paths_for(p)
            status_path = exp_paths["send_status"]
            st = safe_load_json(status_path) if status_path.is_file() else None
            if st is None:
                all_consistent = False
                continue
            expected_input_str = str(Path("input") / "inbox" / p.name)
            recs = [r for r in records if r.get("input_file") == expected_input_str]
            if not recs:
                all_consistent = False
                continue
            rec = recs[0]
            if rec.get("send_status") != st.get("status"):
                all_consistent = False
        if all_consistent:
            scores["ledger_paths_and_status_consistent_with_outputs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()