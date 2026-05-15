import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import sys


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _count_nonempty_lines(path: Path) -> Optional[int]:
    try:
        count = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip() != "":
                    count += 1
        return count
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        records = []
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        records.append(obj)
                    else:
                        # Malformed record type
                        return None
                except Exception:
                    return None
        return records
    except Exception:
        return None


def _parse_yaml_keywords(path: Path) -> Optional[List[Dict[str, Any]]]:
    # Minimal YAML parser tailored for the provided structure
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    in_list = False
    items: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    try:
        for raw in lines:
            line = raw.rstrip()
            if not in_list:
                if re.match(r"^\s*heartbreak_keywords\s*:\s*$", line):
                    in_list = True
                continue
            # In list
            if re.match(r"^\s*-\s", line):
                # Start of new item
                if current is not None:
                    items.append(current)
                current = {}
                # Extract potential inline key: value pairs after "- "
                after_dash = line.split("-", 1)[1].strip()
                if after_dash:
                    # Format like: - term: "breakup"
                    m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*(.+)$', after_dash)
                    if m and current is not None:
                        key, value = m.group(1), m.group(2)
                        value = value.strip()
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        if key == "weight":
                            try:
                                current[key] = int(value)
                            except Exception:
                                return None
                        else:
                            current[key] = value
                continue
            # Continuation lines for current item
            if current is not None and re.match(r"^\s{2,}[A-Za-z0-9_]+\s*:\s*", line):
                m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+)$", line.strip())
                if m:
                    key, value = m.group(1), m.group(2)
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    if key == "weight":
                        try:
                            current[key] = int(value)
                        except Exception:
                            return None
                    else:
                        current[key] = value
            else:
                # If dedent or other section encountered, just continue
                pass
        if current is not None:
            items.append(current)
        # Validate items
        for it in items:
            if "term" not in it or "weight" not in it:
                return None
        return items
    except Exception:
        return None


def _read_do_not_contact(path: Path) -> Optional[set]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if "email" not in reader.fieldnames:
                return None
            emails = set()
            for row in reader:
                email = row.get("email", "")
                if isinstance(email, str):
                    email = email.strip()
                    if email:
                        emails.add(email)
            return emails
    except Exception:
        return None


def _compile_keyword_patterns(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns = []
    for it in items:
        term = it["term"].strip().lower()
        weight = int(it["weight"])
        # Use word boundary based regex to treat punctuation as boundaries
        # (?<!\w) and (?!\w) to ensure not part of a larger word
        pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", flags=re.IGNORECASE)
        patterns.append({"term": term, "weight": weight, "regex": pattern})
    return patterns


def _parse_received_at(dt_str: str) -> Optional[datetime]:
    try:
        # Format like 2026-04-15T21:45:00Z
        dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _compute_message_score(subject: str, body: str, patterns: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    text = f"{subject or ''} {body or ''}"
    matched_terms = []
    matched_set = set()
    for p in patterns:
        if p["term"] in matched_set:
            continue
        if p["regex"].search(text):
            matched_set.add(p["term"])
            matched_terms.append(p["term"])
    score = 0
    for p in patterns:
        if p["term"] in matched_set:
            score += p["weight"]
    return score, sorted(matched_terms)


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return rows, reader.fieldnames
    except Exception:
        return None


def _extract_first_name(full_name: str) -> str:
    if not isinstance(full_name, str) or not full_name.strip():
        return ""
    # Split by whitespace and take first token
    tokens = full_name.strip().split()
    return tokens[0] if tokens else ""


def _body_paragraphs(body: str) -> List[str]:
    # Split into paragraphs by blank lines
    parts = re.split(r"\n\s*\n", body.strip())
    return [p.strip() for p in parts if p.strip() != ""]


def _body_lines(body: str) -> List[str]:
    return [ln.rstrip("\r") for ln in body.split("\n")]


def _find_wisdom_lines(path: Path) -> Optional[List[str]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = []
    for ln in text.splitlines():
        s = ln.strip("\n\r")
        if s.strip().startswith("- "):
            lines.append(s.strip())
    return lines


def _contains_reflection(reply_body: str, message_subject: str, message_body: str) -> bool:
    # Check if reply contains at least one specific word (length >=4) from the fan's subject/body
    text = f"{message_subject or ''} {message_body or ''}".lower()
    words = re.findall(r"[A-Za-z']+", text)
    candidate_words = {w for w in words if len(w) >= 4}
    if not candidate_words:
        return False
    reply_lower = reply_body.lower()
    for w in candidate_words:
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", reply_lower):
            return True
    return False


def _get_discovered_jsonl_files(inbox_dir: Path) -> List[Path]:
    if not inbox_dir.exists():
        return []
    files = [p for p in inbox_dir.rglob("*.jsonl") if p.is_file()]
    files.sort()
    return files


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "audit_file_present": 0.0,
        "audit_lists_all_jsonl": 0.0,
        "audit_counts_correct": 0.0,
        "priority_csv_present": 0.0,
        "priority_csv_columns_correct_order": 0.0,
        "priority_csv_row_count_correct": 0.0,
        "priority_csv_sorted_correctly": 0.0,
        "priority_csv_scores_correct": 0.0,
        "priority_csv_matched_terms_correct": 0.0,
        "replies_present": 0.0,
        "replies_columns_correct_order": 0.0,
        "replies_row_count_correct": 0.0,
        "replies_to_email_matches": 0.0,
        "replies_greeting_correct": 0.0,
        "replies_wisdom_line_included_once": 0.0,
        "replies_paragraph_count_2_to_3": 0.0,
        "replies_signoff_correct": 0.0,
        "replies_reflection_present": 0.0,
        "selection_report_present": 0.0,
        "selection_report_counts_correct": 0.0,
        "selection_report_ranking_correct": 0.0,
    }

    # Expected derived data
    inbox_dir = workspace / "inbox"
    discovered_files = _get_discovered_jsonl_files(inbox_dir)
    expected_counts: Dict[str, int] = {}
    for p in discovered_files:
        cnt = _count_nonempty_lines(p)
        if cnt is None:
            # If any count cannot be read, we can't validate counts
            expected_counts = {}
            break
        rel = p.relative_to(workspace).as_posix()
        expected_counts[rel] = cnt

    # Step 2 expected selection
    fans_path = workspace / "inbox" / "fans" / "messages.jsonl"
    fans_records = _load_jsonl(fans_path)
    processed_total = len(fans_records) if fans_records is not None else 0

    dnc_path = workspace / "data" / "do_not_contact.csv"
    dnc_emails = _read_do_not_contact(dnc_path)
    if dnc_emails is None:
        dnc_emails = set()

    keywords_path = workspace / "config" / "keywords.yaml"
    kw_items = _parse_yaml_keywords(keywords_path)
    patterns = _compile_keyword_patterns(kw_items) if kw_items is not None else []

    wisdom_path = workspace / "content" / "wisdom.md"
    wisdom_lines = _find_wisdom_lines(wisdom_path)

    eligible: List[Dict[str, Any]] = []
    ranking: List[Dict[str, Any]] = []
    selected: List[Dict[str, Any]] = []

    if fans_records is not None and patterns is not None:
        # Filter out do-not-contact
        filtered = [m for m in fans_records if m.get("from_email") not in dnc_emails]
        # Compute scores and matched terms
        for m in filtered:
            subject = m.get("subject", "") or ""
            body = m.get("body", "") or ""
            score, matched_terms = _compute_message_score(subject, body, patterns)
            m["_score"] = score
            m["_matched_terms"] = matched_terms
            m["_body_len"] = len(body)
            rec_at = m.get("received_at")
            dt = _parse_received_at(rec_at) if isinstance(rec_at, str) else None
            m["_received_dt"] = dt
            if score >= 3:
                eligible.append(m)
        # Sort eligible for ranking
        def sort_key(m):
            # For any missing datetime, treat as epoch 0
            dt = m["_received_dt"]
            ts = dt.timestamp() if isinstance(dt, datetime) else 0.0
            return (-int(m["_score"]), -ts, -int(m["_body_len"]), str(m.get("from_email", "")))
        eligible_sorted = sorted(eligible, key=sort_key)
        ranking = eligible_sorted[:]
        selected = eligible_sorted[: min(5, len(eligible_sorted))]
    else:
        eligible = []
        ranking = []
        selected = []

    eligible_total = len(eligible)
    selected_count = len(selected)
    excluded_count = processed_total - (len(fans_records) if fans_records is not None else 0)
    # Correct excluded count is number of records with from_email in dnc among fan messages
    if fans_records is not None:
        excluded_count = sum(1 for m in fans_records if m.get("from_email") in dnc_emails)

    # Step 1: audit.txt checks
    audit_path = workspace / "output" / "audit.txt"
    audit_text = _read_text(audit_path)
    if audit_text is not None:
        scores["audit_file_present"] = 1.0
        lines = [ln.strip() for ln in audit_text.splitlines() if ln.strip() != ""]
        # Check all discovered jsonl files are listed
        all_listed = True
        counts_ok = True
        for rel, cnt in expected_counts.items():
            matched = [ln for ln in lines if rel in ln]
            if not matched:
                all_listed = False
                counts_ok = False
                continue
            # For counts, ensure at least one line referencing this path contains the correct integer count
            has_correct = False
            for ln in matched:
                nums = re.findall(r"(-?\d+)", ln)
                if len(nums) >= 1:
                    # Use the first integer as the count occurrence
                    try:
                        n = int(nums[0])
                        if n == cnt:
                            has_correct = True
                            break
                    except Exception:
                        pass
            if not has_correct:
                counts_ok = False
        if expected_counts:
            scores["audit_lists_all_jsonl"] = 1.0 if all_listed else 0.0
            scores["audit_counts_correct"] = 1.0 if counts_ok else 0.0
        else:
            # If no discovered files, consider listing as correct if file exists
            scores["audit_lists_all_jsonl"] = 1.0
            scores["audit_counts_correct"] = 1.0
    else:
        scores["audit_file_present"] = 0.0
        scores["audit_lists_all_jsonl"] = 0.0
        scores["audit_counts_correct"] = 0.0

    # Step 4: priority_fans_ranked.csv checks
    priority_path = workspace / "output" / "priority_fans_ranked.csv"
    priority_rows_and_fields = _safe_read_csv(priority_path)
    expected_priority_fields = ["id", "from_name", "from_email", "received_at", "score", "matched_terms", "subject"]
    if priority_rows_and_fields is not None:
        rows, fieldnames = priority_rows_and_fields
        scores["priority_csv_present"] = 1.0
        if fieldnames == expected_priority_fields:
            scores["priority_csv_columns_correct_order"] = 1.0
            # Expected rows correspond to selected messages, in sorted order
            expected_ids = [m.get("id") for m in selected]
            actual_ids = [row.get("id") for row in rows]
            if len(rows) == len(expected_ids):
                scores["priority_csv_row_count_correct"] = 1.0
            # Verify order
            scores["priority_csv_sorted_correctly"] = 1.0 if actual_ids == expected_ids else 0.0
            # Scores and matched_terms check
            scores_correct = True
            matched_terms_correct = True
            for i, row in enumerate(rows):
                try:
                    row_score = int(row.get("score", ""))
                except Exception:
                    scores_correct = False
                    break
                if i < len(selected):
                    exp_score = int(selected[i]["_score"])
                    if row_score != exp_score:
                        scores_correct = False
                        break
                    # matched_terms: semicolon-separated, unique, any order; compare case-insensitively
                    mt_str = row.get("matched_terms", "")
                    parts = [p.strip().lower() for p in mt_str.split(";") if p.strip() != ""]
                    if len(parts) != len(set(parts)):
                        matched_terms_correct = False
                        break
                    exp_terms = set(t.lower() for t in selected[i]["_matched_terms"])
                    if set(parts) != exp_terms:
                        matched_terms_correct = False
                        break
                else:
                    scores_correct = False
                    matched_terms_correct = False
                    break
            scores["priority_csv_scores_correct"] = 1.0 if scores_correct else 0.0
            scores["priority_csv_matched_terms_correct"] = 1.0 if matched_terms_correct else 0.0
        else:
            scores["priority_csv_columns_correct_order"] = 0.0
            # Without correct columns, other checks cannot be validated reliably
            scores["priority_csv_row_count_correct"] = 0.0
            scores["priority_csv_sorted_correctly"] = 0.0
            scores["priority_csv_scores_correct"] = 0.0
            scores["priority_csv_matched_terms_correct"] = 0.0
    else:
        # File missing or unreadable
        scores["priority_csv_present"] = 0.0
        scores["priority_csv_columns_correct_order"] = 0.0
        scores["priority_csv_row_count_correct"] = 0.0
        scores["priority_csv_sorted_correctly"] = 0.0
        scores["priority_csv_scores_correct"] = 0.0
        scores["priority_csv_matched_terms_correct"] = 0.0

    # Step 5: replies.csv checks
    replies_path = workspace / "output" / "replies.csv"
    replies_rows_and_fields = _safe_read_csv(replies_path)
    expected_reply_fields = ["to_email", "subject", "body"]
    if replies_rows_and_fields is not None:
        rows, fieldnames = replies_rows_and_fields
        scores["replies_present"] = 1.0
        if fieldnames == expected_reply_fields:
            scores["replies_columns_correct_order"] = 1.0
            # There should be exactly one reply per selected message
            if len(rows) == selected_count:
                scores["replies_row_count_correct"] = 1.0
            # Build mapping from to_email to row(s)
            selected_emails = [m.get("from_email", "") for m in selected]
            selected_email_set = set(selected_emails)
            to_emails = [row.get("to_email", "") for row in rows]
            # All to_emails must be subset of selected_email_set and cover all
            if len(set(to_emails)) == len(to_emails) and set(to_emails) == selected_email_set and len(to_emails) == len(selected_email_set):
                scores["replies_to_email_matches"] = 1.0
            else:
                scores["replies_to_email_matches"] = 0.0

            # Check greeting, wisdom line inclusion, paragraph count, signoff, reflection for each selected message
            greet_ok = True
            wisdom_ok = True
            para_ok = True
            signoff_ok = True
            reflect_ok = True

            # Build mapping from email to message
            email_to_msg = {m.get("from_email", ""): m for m in selected}
            wisdom_candidates = wisdom_lines if wisdom_lines is not None else []
            for row in rows:
                to_email = row.get("to_email", "")
                subject = row.get("subject", "")
                body = row.get("body", "")
                if not isinstance(body, str):
                    body = ""
                if not isinstance(subject, str):
                    subject = ""
                # Greeting
                msg = email_to_msg.get(to_email)
                if msg:
                    first_name = _extract_first_name(str(msg.get("from_name", "")))
                    # Must start with "Hi <first_name>,"
                    body_lstripped = body.lstrip()
                    if not body_lstripped.startswith(f"Hi {first_name},"):
                        greet_ok = False
                    # Wisdom line exactly one
                    if wisdom_candidates:
                        body_lines = [ln.strip() for ln in _body_lines(body)]
                        matches = sum(1 for ln in body_lines if ln in wisdom_candidates)
                        if matches != 1:
                            wisdom_ok = False
                    else:
                        wisdom_ok = False
                    # Paragraph count 2-3
                    paras = _body_paragraphs(body)
                    if not (2 <= len(paras) <= 3):
                        para_ok = False
                    # Signoff at end
                    if not body.strip().endswith("— Your singer-songwriter friend"):
                        signoff_ok = False
                    # Reflection presence (at least one message word present)
                    msg_subject = str(msg.get("subject", ""))
                    msg_body = str(msg.get("body", ""))
                    if not _contains_reflection(body, msg_subject, msg_body):
                        reflect_ok = False
                else:
                    # Missing message for this to_email
                    greet_ok = False
                    wisdom_ok = False
                    para_ok = False
                    signoff_ok = False
                    reflect_ok = False

            scores["replies_greeting_correct"] = 1.0 if greet_ok else 0.0
            scores["replies_wisdom_line_included_once"] = 1.0 if wisdom_ok else 0.0
            scores["replies_paragraph_count_2_to_3"] = 1.0 if para_ok else 0.0
            scores["replies_signoff_correct"] = 1.0 if signoff_ok else 0.0
            scores["replies_reflection_present"] = 1.0 if reflect_ok else 0.0
        else:
            scores["replies_columns_correct_order"] = 0.0
            scores["replies_row_count_correct"] = 0.0
            scores["replies_to_email_matches"] = 0.0
            scores["replies_greeting_correct"] = 0.0
            scores["replies_wisdom_line_included_once"] = 0.0
            scores["replies_paragraph_count_2_to_3"] = 0.0
            scores["replies_signoff_correct"] = 0.0
            scores["replies_reflection_present"] = 0.0
    else:
        scores["replies_present"] = 0.0
        scores["replies_columns_correct_order"] = 0.0
        scores["replies_row_count_correct"] = 0.0
        scores["replies_to_email_matches"] = 0.0
        scores["replies_greeting_correct"] = 0.0
        scores["replies_wisdom_line_included_once"] = 0.0
        scores["replies_paragraph_count_2_to_3"] = 0.0
        scores["replies_signoff_correct"] = 0.0
        scores["replies_reflection_present"] = 0.0

    # Step 6: selection_report.json checks
    report_path = workspace / "output" / "selection_report.json"
    report_data = None
    try:
        if report_path.exists():
            with report_path.open("r", encoding="utf-8") as f:
                report_data = json.load(f)
    except Exception:
        report_data = None
    if report_data is not None:
        scores["selection_report_present"] = 1.0
        # Check counts
        counts_ok = True
        if report_data.get("processed_total") != processed_total:
            counts_ok = False
        if report_data.get("excluded_do_not_contact") != excluded_count:
            counts_ok = False
        if report_data.get("eligible_total") != eligible_total:
            counts_ok = False
        if report_data.get("selected_count") != selected_count:
            counts_ok = False
        scores["selection_report_counts_correct"] = 1.0 if counts_ok else 0.0

        # Ranking array correctness
        ranking_ok = True
        ranking_list = report_data.get("ranking")
        if not isinstance(ranking_list, list):
            ranking_ok = False
        else:
            # Expected full eligible list in rank order
            expected_ranked = ranking
            if len(ranking_list) != len(expected_ranked):
                ranking_ok = False
            else:
                for idx, entry in enumerate(ranking_list, start=1):
                    if not isinstance(entry, dict):
                        ranking_ok = False
                        break
                    exp = expected_ranked[idx - 1]
                    if entry.get("id") != exp.get("id"):
                        ranking_ok = False
                        break
                    if entry.get("from_email") != exp.get("from_email"):
                        ranking_ok = False
                        break
                    if entry.get("score") != exp.get("_score"):
                        ranking_ok = False
                        break
                    if entry.get("rank") != idx:
                        ranking_ok = False
                        break
        scores["selection_report_ranking_correct"] = 1.0 if ranking_ok else 0.0
    else:
        scores["selection_report_present"] = 0.0
        scores["selection_report_counts_correct"] = 0.0
        scores["selection_report_ranking_correct"] = 0.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()