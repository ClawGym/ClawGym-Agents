import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _to_int_safe(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _compute_expected_top5(requests_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    # Filter and sort as specified; return top5 with exact columns in order
    priority_rank = {"High": 3, "Medium": 2, "Low": 1}
    filtered = []
    for row in requests_rows:
        status = row.get("status", "")
        if status not in ("Open", "In Progress"):
            continue
        days_str = row.get("days_overdue", "")
        days_val = _to_int_safe(days_str)
        if days_val is None:
            # malformed numeric for a relevant row -> fail
            return None
        if days_val <= 0:
            continue
        prio = row.get("priority", "")
        if prio not in priority_rank:
            return None
        req_id = row.get("request_id", "")
        title = row.get("title", "")
        owner = row.get("owner", "")
        if not (req_id and title and owner):
            return None
        filtered.append({
            "request_id": req_id,
            "title": title,
            "priority": prio,
            "days_overdue": days_val,
            "owner": owner,
        })
    # Sort by priority (High > Medium > Low), then days_overdue desc, then request_id asc
    filtered.sort(key=lambda r: (-priority_rank[r["priority"]], -r["days_overdue"], r["request_id"]))
    # Top 5
    top5 = filtered[:5]
    # Convert days_overdue back to string for comparison with CSV content
    for r in top5:
        r["days_overdue"] = str(r["days_overdue"])
    return top5


def _list_feedback_files(feedback_dir: Path) -> List[Path]:
    if not feedback_dir.exists() or not feedback_dir.is_dir():
        return []
    files = [p for p in feedback_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
    files.sort(key=lambda p: p.name)
    return files


def _build_expected_quotes(feedback_dir: Path, request_ids: List[str]) -> Dict[str, Optional[Tuple[str, str]]]:
    files = _list_feedback_files(feedback_dir)
    result: Dict[str, Optional[Tuple[str, str]]] = {}
    for rid in request_ids:
        found: Optional[Tuple[str, str]] = None
        for f in files:
            content = _read_text_safe(f)
            if content is None:
                continue
            for raw_line in content.splitlines():
                line = raw_line.rstrip("\r\n")
                if rid in line:
                    found = (line, f.name)
                    break
            if found is not None:
                break
        result[rid] = found
    return result


def _parse_email_structure(text: str) -> Dict[str, Optional[object]]:
    lines = text.splitlines()
    # Find first non-empty line as Subject
    i = 0
    n = len(lines)
    subject_line = None
    while i < n and (lines[i].strip() == ""):
        i += 1
    if i < n:
        subject_line = lines[i]
        i += 1
    # Next non-empty line as opening
    opening_line = None
    while i < n and (lines[i].strip() == ""):
        i += 1
    if i < n:
        opening_line = lines[i]
        i += 1
    # Find bullets starting from here: contiguous lines starting with "- " or "* "
    bullets: List[str] = []
    # Skip any empty lines before bullets
    while i < n and lines[i].strip() == "":
        i += 1
    # Collect bullets
    j = i
    while j < n:
        l = lines[j]
        stripped = l.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(l)
            j += 1
        else:
            break
    # Closing lines: remaining non-empty lines after bullets
    closing_lines: List[str] = []
    k = j
    while k < n:
        if lines[k].strip() != "":
            closing_lines.append(lines[k])
        k += 1
    return {
        "subject": subject_line,
        "opening": opening_line,
        "bullets": bullets,
        "closing": closing_lines,
    }


def _extract_request_id(text: str) -> Optional[str]:
    m = re.search(r'\b(REQ-\d+)\b', text)
    if m:
        return m.group(1)
    return None


def _extract_quote_and_source(text: str) -> Optional[Tuple[str, str]]:
    # Find pattern "..." (source: filename)
    m = re.search(r'"([^"]+)"\s*\(source:\s*([^)]+)\)', text)
    if not m:
        return None
    quote = m.group(1)
    src = m.group(2).strip()
    return (quote, src)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "overdue_csv_exists": 0.0,
        "overdue_csv_header": 0.0,
        "overdue_csv_row_count": 0.0,
        "overdue_csv_content_match": 0.0,
        "email_exists": 0.0,
        "email_subject_line": 0.0,
        "email_opening_sentence": 0.0,
        "email_bullet_count": 0.0,
        "email_bullets_ids_order": 0.0,
        "email_bullet_fields": 0.0,
        "email_bullet_quotes": 0.0,
        "email_closing_eta_request": 0.0,
    }

    # Load input for expected computation
    input_csv_path = workspace / "input" / "data" / "requests.csv"
    input_rows = _load_csv_dicts(input_csv_path)
    expected_top5: Optional[List[Dict[str, str]]] = None
    if input_rows is not None:
        expected_top5 = _compute_expected_top5(input_rows)

    # Compute expected quotes for top5 request IDs
    expected_quotes: Dict[str, Optional[Tuple[str, str]]] = {}
    if expected_top5 is not None:
        req_ids = [r["request_id"] for r in expected_top5]
        expected_quotes = _build_expected_quotes(workspace / "input" / "feedback", req_ids)

    # Check overdue_top5.csv
    out_csv_path = workspace / "output" / "overdue_top5.csv"
    if out_csv_path.exists() and out_csv_path.is_file():
        scores["overdue_csv_exists"] = 1.0
        # Read and validate header and rows
        try:
            with out_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if len(rows) >= 1:
                header = rows[0]
                expected_header = ["request_id", "title", "priority", "days_overdue", "owner"]
                if header == expected_header:
                    scores["overdue_csv_header"] = 1.0
                # Validate row count equals 5
                data_rows = rows[1:]
                if len(data_rows) == 5:
                    scores["overdue_csv_row_count"] = 1.0
                # Validate content matches expected
                if expected_top5 is not None and header == expected_header and len(data_rows) == 5:
                    # Build list of dicts from actual file for comparison
                    actual_dicts = []
                    for r in data_rows:
                        if len(r) != len(expected_header):
                            actual_dicts = None  # malformed row
                            break
                        d = dict(zip(expected_header, r))
                        actual_dicts.append(d)
                    if actual_dicts is not None:
                        # Compare element-wise equality
                        match = True
                        for idx, exp in enumerate(expected_top5):
                            act = actual_dicts[idx]
                            for k in expected_header:
                                if act.get(k, "") != exp.get(k, ""):
                                    match = False
                                    break
                            if not match:
                                break
                        if match:
                            scores["overdue_csv_content_match"] = 1.0
        except Exception:
            # Leave scores as is for header/content if unreadable
            pass
    else:
        # Missing file; leave zeros
        pass

    # Check email_draft.txt
    email_path = workspace / "output" / "email_draft.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
        email_struct = _parse_email_structure(email_text)
        subject_line = email_struct.get("subject")
        opening_line = email_struct.get("opening")
        bullets: List[str] = email_struct.get("bullets") or []
        closing_lines: List[str] = email_struct.get("closing") or []

        # Subject line check: first non-empty line starts with "Subject:"
        if isinstance(subject_line, str) and subject_line.strip().startswith("Subject:"):
            scores["email_subject_line"] = 1.0

        # Opening sentence: next non-empty line exists and ends with a period
        if isinstance(opening_line, str):
            open_stripped = opening_line.strip()
            if open_stripped.endswith(".") and ('* ' not in open_stripped and '- ' not in open_stripped):
                scores["email_opening_sentence"] = 1.0

        # Bullet count: exactly 5
        if len(bullets) == 5:
            scores["email_bullet_count"] = 1.0

        # Bullets ID order and fields and quotes
        ids_order_ok = False
        fields_ok = False
        quotes_ok = False

        if expected_top5 is not None and len(bullets) == 5:
            expected_ids = [r["request_id"] for r in expected_top5]
            found_ids: List[Optional[str]] = [_extract_request_id(b) for b in bullets]
            ids_order_ok = (found_ids == expected_ids)

            # Fields present check for each bullet
            fields_ok_local = True
            quotes_ok_local = True
            for idx, b in enumerate(bullets):
                exp = expected_top5[idx]
                rid = exp["request_id"]
                title = exp["title"]
                prio = exp["priority"]
                days = exp["days_overdue"]
                owner = exp["owner"]

                # Check presence of required fields in bullet
                # ensure the bullet contains the exact request_id, title, priority, owner, and "[days] days"
                if rid not in b:
                    fields_ok_local = False
                if title not in b:
                    fields_ok_local = False
                # priority as whole word
                if not re.search(r'\b' + re.escape(prio) + r'\b', b):
                    fields_ok_local = False
                # days with word "days"
                if f"{days} days" not in b:
                    fields_ok_local = False
                if owner not in b:
                    fields_ok_local = False

                # Quote check
                extracted = _extract_quote_and_source(b)
                expected_q = expected_quotes.get(rid) if expected_quotes is not None else None
                if expected_q is None:
                    # Expect "No feedback quote found"
                    if extracted is not None:
                        quotes_ok_local = False
                    else:
                        # Ensure literal phrase appears
                        if "No feedback quote found" not in b:
                            quotes_ok_local = False
                else:
                    # Must have a quote and source file name match
                    if extracted is None:
                        quotes_ok_local = False
                    else:
                        q_text, q_src = extracted
                        exp_text, exp_src = expected_q
                        # Compare verbatim quote text and source filename
                        if q_text != exp_text or q_src != exp_src:
                            quotes_ok_local = False

            fields_ok = fields_ok_local
            quotes_ok = quotes_ok_local

        scores["email_bullets_ids_order"] = 1.0 if ids_order_ok else 0.0
        scores["email_bullet_fields"] = 1.0 if fields_ok else 0.0
        scores["email_bullet_quotes"] = 1.0 if quotes_ok else 0.0

        # Closing sentence asking owners to reply with an ETA
        closing_ok = False
        for cl in closing_lines:
            s = cl.strip()
            if s == "":
                continue
            # Look for both words "reply" and "ETA" (case-insensitive)
            if re.search(r'\breply\b', s, flags=re.IGNORECASE) and re.search(r'\bETA\b', s, flags=re.IGNORECASE):
                closing_ok = True
                break
        scores["email_closing_eta_request"] = 1.0 if closing_ok else 0.0
    else:
        # email doesn't exist
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()