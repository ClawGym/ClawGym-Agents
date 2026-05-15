import sys
import json
import csv
import re
import html as html_module
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set
from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timezone


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _strip_html(html: str) -> str:
    # Remove script/style
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    # Remove tags
    text = re.sub(r"(?s)<[^>]+>", "", html)
    # Unescape entities
    text = html_module.unescape(text)
    return text


def _decode_mime_header(value: Optional[str]) -> str:
    if value is None:
        return ""
    try:
        dh = decode_header(value)
        return str(make_header(dh))
    except Exception:
        # Fallback: return raw
        return value


def _parse_filters_yaml(path: Path) -> Optional[Dict[str, List[str]]]:
    """
    Minimal YAML parser for the provided simple structure:
    categories:
      category1:
        - keyword1
        - keyword2
      category2:
        - keywordA
    Returns dict {category: [keywords...]} all lowercased and stripped.
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    state = "start"
    categories: Dict[str, List[str]] = {}
    current_category: Optional[str] = None
    try:
        for raw_line in lines:
            line = raw_line.rstrip()
            if not line.strip():
                continue
            if state == "start":
                # Expect "categories:"
                if re.match(r"^\s*categories\s*:\s*$", line):
                    state = "in_categories"
                    continue
                else:
                    # If file begins directly with categories mapping, be lenient
                    if re.match(r"^\s*[A-Za-z0-9_\-]+\s*:\s*$", line):
                        # Assume it is the first category (missing "categories:"), but the provided file has it.
                        # To stay robust, switch to in_categories and handle as category next iterations.
                        state = "in_categories"
                        # fall through to handle as category
                    else:
                        # Unexpected
                        return None
            if state == "in_categories":
                # Category line: two-space indent + name + colon (be lenient on indent)
                m = re.match(r"^\s{0,4}([A-Za-z0-9_\-]+)\s*:\s*$", line)
                if m:
                    current_category = m.group(1).strip().lower()
                    categories[current_category] = []
                    continue
                # Keyword item line: dash with optional indent
                m2 = re.match(r"^\s*-\s*(.+?)\s*$", line)
                if m2 and current_category is not None:
                    kw = m2.group(1).strip().lower()
                    if kw:
                        categories[current_category].append(kw)
                    continue
                # Otherwise ignore unknown line types to be robust
                # but if it's a new key not under the categories block, continue
                # For simplicity, we won't support deeper nesting
        if not categories:
            return None
        # Deduplicate keywords per category and preserve insertion order (but order not critical)
        for cat, kws in list(categories.items()):
            seen: Set[str] = set()
            deduped: List[str] = []
            for k in kws:
                if k not in seen:
                    seen.add(k)
                    deduped.append(k)
            categories[cat] = deduped
        return categories
    except Exception:
        return None


def _parse_eml(path: Path) -> Optional[Dict[str, Any]]:
    data = _read_bytes(path)
    if data is None:
        return None
    try:
        msg = BytesParser(policy=policy.default).parsebytes(data)
    except Exception:
        return None
    try:
        # Headers
        raw_subject = msg["Subject"]
        subject = _decode_mime_header(raw_subject)
        raw_from = msg["From"]
        name, addr = parseaddr(raw_from if raw_from is not None else "")
        from_name = _decode_mime_header(name)
        from_email = addr or ""
        raw_msg_id = msg["Message-ID"] or ""
        message_id = raw_msg_id.strip()
        raw_date = msg["Date"]
        dt = None
        if raw_date:
            try:
                dt = parsedate_to_datetime(raw_date)
                if dt is not None:
                    if dt.tzinfo is None:
                        # Assume UTC if no timezone present
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt = dt.astimezone(timezone.utc)
            except Exception:
                dt = None

        # Body extraction
        body_text = ""
        if msg.is_multipart():
            # Prefer text/plain
            text_part = None
            html_part = None
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain" and text_part is None:
                    text_part = part
                elif ctype == "text/html" and html_part is None:
                    html_part = part
            if text_part is not None:
                try:
                    body_text = text_part.get_content()
                except Exception:
                    payload = text_part.get_payload(decode=True) or b""
                    body_text = payload.decode(text_part.get_content_charset() or "utf-8", errors="replace")
            elif html_part is not None:
                try:
                    html_content = html_part.get_content()
                except Exception:
                    payload = html_part.get_payload(decode=True) or b""
                    html_content = payload.decode(html_part.get_content_charset() or "utf-8", errors="replace")
                body_text = _strip_html(html_content)
            else:
                # Fallback to entire payload as string
                body_text = msg.get_body(preferencelist=("plain", "html")).get_content() if msg.get_body() else ""
        else:
            ctype = msg.get_content_type()
            try:
                content = msg.get_content()
            except Exception:
                payload = msg.get_payload(decode=True) or b""
                content = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if ctype == "text/html":
                body_text = _strip_html(content)
            else:
                body_text = content

        # Normalize line endings
        if not isinstance(body_text, str):
            body_text = str(body_text)
        body_text = body_text.replace("\r\n", "\n").replace("\r", "\n")

        return {
            "message_id": message_id,
            "date_dt_utc": dt,
            "from_name": from_name,
            "from_email": from_email,
            "subject": subject,
            "body_text": body_text,
        }
    except Exception:
        return None


def _format_iso_utc(dt: datetime) -> str:
    # Return ISO8601 UTC with Z
    return dt.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso_datetime_utc(s: str) -> Optional[datetime]:
    # Accept formats with Z or offset
    try:
        if s.endswith("Z"):
            # Replace Z with +00:00 for fromisoformat
            s2 = s[:-1] + "+00:00"
            return datetime.fromisoformat(s2).astimezone(timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        # Try common variants without seconds
        try:
            # If it lacks timezone info, assume UTC
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None


def _collect_emails(workspace: Path) -> List[Path]:
    emails_dir = workspace / "input" / "emails"
    if not emails_dir.exists():
        return []
    return sorted(p for p in emails_dir.glob("*.eml") if p.is_file())


def _compute_expected(workspace: Path) -> Tuple[int, Dict[str, Dict[str, Any]]]:
    """
    Returns:
      total_count (int),
      included_by_message_id (dict of message_id -> expected fields dict)
    """
    filters_path = workspace / "input" / "filters.yaml"
    filters = _parse_filters_yaml(filters_path)
    eml_paths = _collect_emails(workspace)
    total_count = len(eml_paths)
    included: Dict[str, Dict[str, Any]] = {}
    if filters is None:
        # Cannot compute expected included set without filters
        return total_count, included

    # Build flat keyword->categories map for quick lookup
    category_by_keyword: Dict[str, Set[str]] = {}
    all_keywords: Set[str] = set()
    for cat, kw_list in filters.items():
        for kw in kw_list:
            all_keywords.add(kw)
            category_by_keyword.setdefault(kw, set()).add(cat)

    for p in eml_paths:
        parsed = _parse_eml(p)
        if parsed is None:
            # Skip malformed files for inclusion purposes; still count as processed
            continue
        subject = parsed["subject"]
        body = parsed["body_text"]
        combined = (subject + "\n" + body).lower()
        matched_kws: Set[str] = set()
        matched_cats: Set[str] = set()
        for kw in all_keywords:
            if kw in combined:
                matched_kws.add(kw.lower())
                for cat in category_by_keyword.get(kw, set()):
                    matched_cats.add(cat)
        if matched_kws:
            msg_id = parsed["message_id"]
            dt: Optional[datetime] = parsed["date_dt_utc"]
            date_iso = _format_iso_utc(dt) if isinstance(dt, datetime) else ""
            # Prepare categories and matched keywords sorted and formatted
            cats_sorted = sorted(matched_cats)
            kws_sorted = sorted({k.lower() for k in matched_kws})
            body_text = parsed["body_text"]
            snippet = body_text[:200]
            included[msg_id] = {
                "message_id": msg_id,
                "date_iso": date_iso,
                "from_name": parsed["from_name"],
                "from_email": parsed["from_email"],
                "subject": subject,
                "categories_list": cats_sorted,
                "matched_keywords_list": kws_sorted,
                "categories_str": ",".join(cats_sorted),
                "matched_keywords_str": ",".join(kws_sorted),
                "snippet": snippet,
                "message_id_stripped": msg_id.strip("<>"),
            }
    return total_count, included


def _load_csv_records(csv_path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not csv_path.exists():
        return None, None
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = [row for row in reader]
        return header, rows
    except Exception:
        return None, None


def _split_commas_normalized(s: str) -> List[str]:
    parts = [p.strip() for p in s.split(",")] if s else []
    parts = [p for p in parts if p != ""]
    return parts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inquiries_csv_exists": 0.0,
        "inquiries_csv_header_correct": 0.0,
        "inquiries_csv_included_message_ids_correct": 0.0,
        "inquiries_csv_content_correct": 0.0,
        "replies_files_exist": 0.0,
        "replies_content_correct": 0.0,
        "summary_counts_correct": 0.0,
    }

    # Compute expected
    total_count, expected_included = _compute_expected(workspace)

    # Check inquiries.csv
    inquiries_csv = workspace / "output" / "inquiries.csv"
    header, rows = _load_csv_records(inquiries_csv)
    if header is not None and rows is not None:
        scores["inquiries_csv_exists"] = 1.0
        expected_header = [
            "message_id",
            "date",
            "from_name",
            "from_email",
            "subject",
            "categories",
            "matched_keywords",
            "snippet",
        ]
        if header == expected_header:
            scores["inquiries_csv_header_correct"] = 1.0

        # Compare included message_ids
        actual_ids = [r.get("message_id", "") for r in rows]
        actual_id_set = set(actual_ids)
        expected_id_set = set(expected_included.keys())
        if actual_id_set == expected_id_set:
            scores["inquiries_csv_included_message_ids_correct"] = 1.0

        # Validate row-by-row content
        content_ok = True
        # Build map for quick lookup
        actual_by_id: Dict[str, Dict[str, str]] = {r.get("message_id", ""): r for r in rows}
        for msg_id, exp in expected_included.items():
            row = actual_by_id.get(msg_id)
            if row is None:
                content_ok = False
                break
            # date
            exp_date_dt = _parse_iso_datetime_utc(exp["date_iso"]) if exp["date_iso"] else None
            got_date_str = row.get("date", "") or ""
            got_date_dt = _parse_iso_datetime_utc(got_date_str)
            if not (exp_date_dt and got_date_dt and exp_date_dt == got_date_dt):
                content_ok = False
                break
            # from_name, from_email, subject
            if (row.get("from_name", "") or "") != exp["from_name"]:
                content_ok = False
                break
            if (row.get("from_email", "") or "") != exp["from_email"]:
                content_ok = False
                break
            if (row.get("subject", "") or "") != exp["subject"]:
                content_ok = False
                break
            # categories: allow optional spaces after comma, ensure alphabetical and exact membership
            got_cats_list = _split_commas_normalized(row.get("categories", "") or "")
            if got_cats_list != sorted(got_cats_list):
                content_ok = False
                break
            if got_cats_list != exp["categories_list"]:
                content_ok = False
                break
            # matched_keywords: must be lowercase, unique, alphabetical
            got_kws_list = _split_commas_normalized(row.get("matched_keywords", "") or "")
            if got_kws_list != sorted(got_kws_list):
                content_ok = False
                break
            if any(k != k.lower() for k in got_kws_list):
                content_ok = False
                break
            if got_kws_list != exp["matched_keywords_list"]:
                content_ok = False
                break
            # snippet: must equal first 200 chars
            if (row.get("snippet", "") or "") != exp["snippet"]:
                content_ok = False
                break
        # Also ensure there are no unexpected extra rows (already checked ids set equality)
        if content_ok and actual_id_set == set(expected_included.keys()):
            scores["inquiries_csv_content_correct"] = 1.0

    # Check replies for each included email
    replies_dir = workspace / "output" / "replies"
    replies_exist_ok = True
    replies_content_ok = True
    # Load CSV-derived authoritative values when available; else use expected
    csv_authoritative: Dict[str, Dict[str, str]] = {}
    if rows is not None:
        for r in rows:
            mid = r.get("message_id", "")
            if mid:
                csv_authoritative[mid] = r

    for msg_id, exp in expected_included.items():
        fname = exp["message_id_stripped"] + ".txt"
        reply_path = replies_dir / fname
        content = _read_text(reply_path)
        if content is None:
            replies_exist_ok = False
            replies_content_ok = False
            continue
        # Content checks: placeholders filled, fields inserted
        # Prefer CSV values to ensure consistency with what they wrote
        source = csv_authoritative.get(msg_id, {})
        subj = source.get("subject", exp["subject"])
        recip = source.get("from_name", exp["from_name"])
        cats_str = source.get("categories", exp["categories_str"])
        snip = source.get("snippet", exp["snippet"])

        lines = content.splitlines()
        # First line check
        expected_first_line = f"Subject: Re: {subj}"
        if not lines:
            replies_content_ok = False
        else:
            if lines[0].strip() != expected_first_line:
                replies_content_ok = False
        # Greeting line
        greeting_found = False
        for ln in lines[1:6]:
            if ln.strip() == f"Hi {recip},":
                greeting_found = True
                break
        if not greeting_found:
            replies_content_ok = False
        # Categories presence in template context
        if cats_str not in content:
            replies_content_ok = False
        # Snippet presence (quoted in the template, but we accept presence of snippet)
        if snip and snip not in content:
            replies_content_ok = False
        # No unreplaced placeholders like {{...}}
        if "{{" in content or "}}" in content:
            replies_content_ok = False

    if expected_included:
        if replies_exist_ok:
            scores["replies_files_exist"] = 1.0
        if replies_content_ok:
            scores["replies_content_correct"] = 1.0
    else:
        # If no expected included, define replies checks as pass if no reply files exist
        if not (replies_dir.exists() and any(replies_dir.glob("*.txt"))):
            scores["replies_files_exist"] = 1.0
            scores["replies_content_correct"] = 1.0

    # Check summary.txt
    summary_path = workspace / "output" / "summary.txt"
    summary_text = _read_text(summary_path)
    if summary_text is not None:
        lines = [ln.strip() for ln in summary_text.splitlines()]
        # Spec: two lines: total processed and number included in CSV
        if len(lines) >= 2:
            # Extract first integer from each line
            def _extract_first_int(s: str) -> Optional[int]:
                m = re.search(r"-?\d+", s)
                return int(m.group(0)) if m else None

            total_val = _extract_first_int(lines[0])
            included_val = _extract_first_int(lines[1])
            expected_total = total_count
            expected_included_count = len(expected_included)
            if total_val == expected_total and included_val == expected_included_count:
                scores["summary_counts_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()