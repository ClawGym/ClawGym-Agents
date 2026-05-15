import csv
import json
import sys
from pathlib import Path
from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, parseaddr


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return path.read_text(errors="replace")
        except Exception:
            return ""


def _read_bytes_safe(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except Exception:
        return b""


def _decode_header_value(value: str) -> str:
    if value is None:
        return ""
    try:
        # Handles encoded words per RFC 2047
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _parse_eml(path: Path):
    try:
        with path.open("rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)
        return msg
    except Exception:
        return None


def _normalize_msg_id(val: str) -> str:
    if not val:
        return ""
    s = val.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1]
    return s.strip()


def _extract_from_fields(msg) -> tuple:
    raw_from = msg.get("From", "") if msg else ""
    name, email = parseaddr(raw_from)
    name = _decode_header_value(name)
    return (name, email)


def _extract_subject(msg) -> str:
    return _decode_header_value(msg.get("Subject", "")) if msg else ""


def _extract_date_iso(msg) -> str:
    raw_date = msg.get("Date", "") if msg else ""
    try:
        dt = parsedate_to_datetime(raw_date)
        if dt is None:
            return ""
        # Ensure offset is present if available; isoformat includes offset automatically
        # Use seconds precision
        # If datetime is naive, leave as is (no offset)
        return dt.isoformat(timespec="seconds")
    except Exception:
        return ""


def _extract_message_id(msg, fallback_name: str = "") -> str:
    raw = msg.get("Message-ID", "") if msg else ""
    norm = _normalize_msg_id(raw)
    if not norm:
        norm = fallback_name
    return norm


def _get_text_from_part(part) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            # not decoded; could be str
            text = part.get_payload()
            if isinstance(text, str):
                return text
            elif text is None:
                return ""
            else:
                try:
                    return text.decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except Exception:
            # Fallback to utf-8
            return payload.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_plain_text_body(msg) -> str:
    if msg is None:
        return ""
    if msg.is_multipart():
        # Prefer text/plain
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = part.get_content_disposition()
            if ctype == "text/plain" and disp != "attachment":
                text = _get_text_from_part(part)
                if text is not None:
                    return text
        # Fallback to first part
        for part in msg.walk():
            if part.get_content_maintype() == "text":
                text = _get_text_from_part(part)
                if text is not None:
                    return text
        return ""
    else:
        if msg.get_content_maintype() == "text":
            return _get_text_from_part(msg)
        else:
            return ""


def _normalize_text(s: str) -> str:
    # Normalize newlines and strip trailing/leading whitespace
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # Keep internal whitespaces as-is but trim leading/trailing newlines/spaces
    return s.strip()


def _list_eml_files(workspace: Path):
    in_dir = workspace / "input" / "messages"
    if not in_dir.exists() or not in_dir.is_dir():
        return []
    return sorted(in_dir.glob("*.eml"))


def _expected_from_inputs(workspace: Path):
    eml_paths = _list_eml_files(workspace)
    expected = []
    for p in eml_paths:
        msg = _parse_eml(p)
        message_id = _extract_message_id(msg, p.stem)
        subject = _extract_subject(msg)
        from_name, from_email = _extract_from_fields(msg)
        date_iso = _extract_date_iso(msg)
        body = _extract_plain_text_body(msg)
        body_norm = _normalize_text(body)
        expected.append({
            "path": p,
            "message_id": message_id,
            "subject": subject,
            "from_name": from_name,
            "from_email": from_email,
            "date_iso8601": date_iso,
            "body": body_norm,
        })
    return expected


def _load_keywords(workspace: Path):
    fp = workspace / "input" / "keywords.txt"
    try:
        text = _read_text_safe(fp)
        kws = []
        for line in text.splitlines():
            t = line.strip()
            if t:
                kws.append(t.lower())
        return kws
    except Exception:
        return []


def _matched_keywords(body: str, keywords: list) -> list:
    text = body.lower()
    found = set()
    for kw in keywords:
        if kw and kw in text:
            found.add(kw)
    # deterministic order
    return sorted(found)


def _find_body_path_for_msgid(workspace: Path, msgid: str):
    out_dir = workspace / "output" / "bodies"
    candidates = []
    candidates.append(out_dir / f"{msgid}.txt")
    # also consider angle brackets literal if they used it
    candidates.append(out_dir / f"<{msgid}>.txt")
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def _read_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def _parse_summary_csv(path: Path):
    rows = _read_csv_rows(path)
    if rows is None or len(rows) == 0:
        return None, None
    header = rows[0]
    data_rows = rows[1:]
    # Build rows as dicts
    dicts = []
    for r in data_rows:
        if len(r) != len(header):
            return header, None
        dicts.append(dict(zip(header, r)))
    return header, dicts


def _strip_angle(s: str) -> str:
    return _normalize_msg_id(s)


def _get_first_name(display_name: str) -> str:
    name = (display_name or "").strip()
    if not name:
        return ""
    # Split by whitespace and take first token; strip quotes
    first = name.strip(' "\'').split()[0]
    return first


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inspection_file_exists": 0.0,
        "inspection_lines_format_correct": 0.0,
        "inspection_contents_match": 0.0,
        "first_run_log_exists": 0.0,
        "first_run_log_captured_error": 0.0,
        "research_file_exists": 0.0,
        "research_has_query_and_title": 0.0,
        "research_title_mentions_email": 0.0,
        "bodies_all_present": 0.0,
        "body_msg1_content_correct": 0.0,
        "body_msg2_content_correct": 0.0,
        "body_msg3_content_correct": 0.0,
        "summary_exists": 0.0,
        "summary_header_correct": 0.0,
        "summary_row_count_correct": 0.0,
        "summary_msg1_fields_correct": 0.0,
        "summary_msg2_fields_correct": 0.0,
        "summary_msg3_fields_correct": 0.0,
        "drafts_expected_present": 0.0,
        "draft_msg1_format_correct": 0.0,
        "draft_msg2_format_correct": 0.0,
        "no_draft_for_nonmatches": 0.0,
        "second_run_log_exists": 0.0,
        "second_run_log_mentions_command": 0.0,
    }

    # Prepare expected data from inputs
    eml_paths = _list_eml_files(workspace)
    expected_items = _expected_from_inputs(workspace)
    # Map by normalized msgid
    expected_by_id = {item["message_id"]: item for item in expected_items}
    # Pre-compute keyword matches
    keywords = _load_keywords(workspace)
    expected_matches = {}
    for item in expected_items:
        expected_matches[item["message_id"]] = _matched_keywords(item["body"], keywords)

    # 1) inspection.txt checks
    inspection_path = workspace / "output" / "inspection.txt"
    if inspection_path.exists() and inspection_path.is_file():
        scores["inspection_file_exists"] = 1.0
        content = _read_text_safe(inspection_path)
        lines = [ln for ln in content.splitlines() if ln.strip() != ""]
        # format: one file per line, name and size separated by a tab
        ok_format = True
        seen_files = set()
        listed = {}
        for ln in lines:
            parts = ln.split("\t")
            if len(parts) != 2:
                ok_format = False
                break
            fname, size_str = parts[0].strip(), parts[1].strip()
            if fname == "" or size_str == "":
                ok_format = False
                break
            try:
                size_int = int(size_str)
            except Exception:
                ok_format = False
                break
            listed[fname] = size_int
            seen_files.add(fname)
        if ok_format:
            scores["inspection_lines_format_correct"] = 1.0
            # Compare to actual input/messages/*.eml files
            actual = {}
            for p in eml_paths:
                try:
                    sz = p.stat().st_size
                except Exception:
                    sz = None
                actual[p.name] = sz
            # Check same set of files
            if set(actual.keys()) == set(listed.keys()) and all(
                (listed.get(name) == actual.get(name) and actual.get(name) is not None)
                for name in actual.keys()
            ):
                scores["inspection_contents_match"] = 1.0
    # 2) first run log
    first_log = workspace / "output" / "logs" / "first_run.log"
    if first_log.exists() and first_log.is_file():
        scores["first_run_log_exists"] = 1.0
        text = _read_text_safe(first_log)
        low = text.lower()
        # Expect some error captured due to mailparser
        if any(tok in low for tok in ["importerror", "modulenotfounderror", "traceback", "mailparser"]):
            scores["first_run_log_captured_error"] = 1.0

    # 3) research.txt
    research_path = workspace / "output" / "research.txt"
    if research_path.exists() and research_path.is_file():
        scores["research_file_exists"] = 1.0
        text = _read_text_safe(research_path)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
        if len(lines) >= 2:
            scores["research_has_query_and_title"] = 1.0
            # Title mentions email stdlib
            if any(("email" in lines[i].lower()) for i in range(len(lines))):
                scores["research_title_mentions_email"] = 1.0

    # 4) bodies files
    # Determine expected msgids from inputs
    expected_ids = [item["message_id"] for item in expected_items]
    bodies_dir = workspace / "output" / "bodies"
    bodies_present = True
    body_content_scores = {"msg1": 0.0, "msg2": 0.0, "msg3": 0.0}
    # Map filename stems from inputs to discriminators (msg1, msg2, msg3)
    stem_to_key = {}
    for item in expected_items:
        stem = item["path"].name
        # Map by specific input filenames to hand out per-message scores
        if stem.startswith("001_"):
            stem_to_key[item["message_id"]] = "msg1"
        elif stem.startswith("002_"):
            stem_to_key[item["message_id"]] = "msg2"
        elif stem.startswith("003_"):
            stem_to_key[item["message_id"]] = "msg3"

    for msgid in expected_ids:
        bp = _find_body_path_for_msgid(workspace, msgid)
        if bp is None:
            bodies_present = False
        else:
            # Compare content
            actual_text = _normalize_text(_read_text_safe(bp))
            exp_text = _normalize_text(expected_by_id[msgid]["body"])
            key = stem_to_key.get(msgid)
            if actual_text == exp_text and key is not None:
                body_content_scores[f"body_{key}_content_correct"] = 1.0
            elif key is not None:
                body_content_scores[f"body_{key}_content_correct"] = 0.0

    if bodies_present and len(expected_ids) > 0:
        scores["bodies_all_present"] = 1.0

    # assign per-message body scores
    scores["body_msg1_content_correct"] = body_content_scores.get("body_msg1_content_correct", 0.0)
    scores["body_msg2_content_correct"] = body_content_scores.get("body_msg2_content_correct", 0.0)
    scores["body_msg3_content_correct"] = body_content_scores.get("body_msg3_content_correct", 0.0)

    # 5) summary.csv checks
    summary_path = workspace / "output" / "summary.csv"
    if summary_path.exists() and summary_path.is_file():
        scores["summary_exists"] = 1.0
        header, dict_rows = _parse_summary_csv(summary_path)
        expected_header = [
            "message_id",
            "date_iso8601",
            "from_name",
            "from_email",
            "subject",
            "matched_keywords",
            "body_char_count",
        ]
        if header == expected_header:
            scores["summary_header_correct"] = 1.0
        if dict_rows is not None:
            if len(dict_rows) == len(expected_items):
                scores["summary_row_count_correct"] = 1.0
            # Build lookup by normalized message_id
            by_id = {}
            for row in dict_rows:
                mid = _strip_angle((row.get("message_id") or "").strip())
                by_id[mid] = row
            # Per message checks
            for item in expected_items:
                mid = item["message_id"]
                row = by_id.get(mid)
                # Some users may have used literal angle brackets in message_id; attempt alternate
                if row is None:
                    row = by_id.get(_strip_angle("<" + mid + ">"))
                if row is None:
                    continue
                # Fields validation
                ok = True
                # message_id acceptable if equals either normalized or with angle brackets
                rid = row.get("message_id", "")
                rid_norm = _strip_angle(rid)
                if rid_norm != mid:
                    ok = False
                # date_iso8601 exact match
                if row.get("date_iso8601", "") != item["date_iso8601"]:
                    ok = False
                # from_name exact (decoded)
                if row.get("from_name", "") != item["from_name"]:
                    ok = False
                # from_email exact
                if row.get("from_email", "") != item["from_email"]:
                    ok = False
                # subject exact
                if row.get("subject", "") != item["subject"]:
                    ok = False
                # matched_keywords: semicolon-separated, unique, lowercased; compare as sets
                mk_field = (row.get("matched_keywords") or "").strip()
                if mk_field == "":
                    student_mks = []
                else:
                    student_mks = [tok.strip().lower() for tok in mk_field.split(";") if tok.strip() != ""]
                expected_mks = expected_matches.get(mid, [])
                if set(student_mks) != set(expected_mks):
                    ok = False
                # body_char_count equals length of decoded body (normalize similarly to body files)
                exp_body = item["body"]
                # Prefer student's body file if present to align their normalization, then compare equality with their row
                body_file = _find_body_path_for_msgid(workspace, mid)
                if body_file and body_file.exists():
                    body_text_for_count = _read_text_safe(body_file)
                else:
                    body_text_for_count = exp_body
                try:
                    student_count = int(row.get("body_char_count", ""))
                except Exception:
                    ok = False
                    student_count = None
                # Count characters exactly as len of text
                if student_count is not None:
                    if student_count != len(body_text_for_count):
                        ok = False
                # Set score key
                stem = item["path"].name
                if stem.startswith("001_"):
                    scores["summary_msg1_fields_correct"] = 1.0 if ok else 0.0
                elif stem.startswith("002_"):
                    scores["summary_msg2_fields_correct"] = 1.0 if ok else 0.0
                elif stem.startswith("003_"):
                    scores["summary_msg3_fields_correct"] = 1.0 if ok else 0.0

    # 6) drafts checks
    # Determine expected which matched at least one keyword
    expected_match_ids = {mid for mid, mks in expected_matches.items() if len(mks) > 0}
    drafts_dir = workspace / "output" / "drafts"
    drafts_ok_presence = False
    if drafts_dir.exists() and drafts_dir.is_dir():
        # List all _reply.txt files
        draft_files = list(drafts_dir.glob("*_reply.txt"))
        # Build normalized ids from filenames
        student_ids = set()
        for p in draft_files:
            name = p.name
            if not name.endswith("_reply.txt"):
                continue
            core = name[:-len("_reply.txt")]
            student_ids.add(_strip_angle(core))
        # Check that student_ids equal expected_match_ids
        if student_ids == expected_match_ids:
            drafts_ok_presence = True
            scores["drafts_expected_present"] = 1.0
            scores["no_draft_for_nonmatches"] = 1.0
        else:
            # If at least all expected are present, give presence pass
            if expected_match_ids.issubset(student_ids) and len(expected_match_ids) > 0:
                scores["drafts_expected_present"] = 1.0
            # If there are extra unexpected drafts, no_draft_for_nonmatches remains 0.0
    # Per draft format checks for msg1 and msg2 if applicable
    for item in expected_items:
        mid = item["message_id"]
        if mid not in expected_match_ids:
            continue
        # find draft path
        cand1 = drafts_dir / f"{mid}_reply.txt"
        cand2 = drafts_dir / f"<{mid}>_reply.txt"
        dpath = cand1 if cand1.exists() else (cand2 if cand2.exists() else None)
        if dpath and dpath.exists():
            text = _read_text_safe(dpath)
            lines = text.splitlines()
            ok = True
            subj_line = f"Subject: Re: {item['subject']}"
            to_line = f"To: {item['from_email']}"
            if len(lines) < 2:
                ok = False
            else:
                if lines[0].strip() != subj_line:
                    ok = False
                if lines[1].strip() != to_line:
                    ok = False
                # phrase presence (case-insensitive)
                body_text = "\n".join(lines[2:]).lower() if len(lines) > 2 else ""
                if "for our family scrapbook" not in body_text:
                    ok = False
                # sender first name appears somewhere after headers
                first_name = _get_first_name(item["from_name"]).lower()
                if first_name:
                    if first_name not in body_text:
                        ok = False
            stem = item["path"].name
            if stem.startswith("001_"):
                scores["draft_msg1_format_correct"] = 1.0 if ok else 0.0
            elif stem.startswith("002_"):
                scores["draft_msg2_format_correct"] = 1.0 if ok else 0.0

    # 7) second run log
    second_log = workspace / "output" / "logs" / "second_run.log"
    if second_log.exists() and second_log.is_file():
        scores["second_run_log_exists"] = 1.0
        text = _read_text_safe(second_log).lower()
        # Check it shows the command executed; look for the script path name
        if "extract_bodies.py" in text or "python" in text:
            scores["second_run_log_mentions_command"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=None))


if __name__ == "__main__":
    main()