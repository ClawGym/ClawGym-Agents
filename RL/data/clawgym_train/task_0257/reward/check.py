import json
import csv
import re
import sys
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta


EXPECTED_HEADER = [
    "message_id",
    "from_email",
    "subject",
    "date_iso",
    "child_name",
    "child_age",
    "preferred_times",
    "completed_intake",
    "score",
    "rank",
    "reason_tags",
]


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


def _load_csv_dicts(path: Path):
    if not path.exists():
        return None, []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], []
        header = rows[0]
        dicts = []
        for r in rows[1:]:
            # pad or trim row to header length
            r = (r + [""] * len(header))[: len(header)]
            dicts.append({header[i]: r[i] for i in range(len(header))})
        return header, dicts
    except Exception:
        return None, []


def _extract_first_email(addr: str) -> str:
    # Try to extract email between <>
    m = re.search(r"<\s*([^>]+)\s*>", addr)
    if m:
        return m.group(1).strip()
    # Otherwise regex for email
    m = re.search(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", addr)
    if m:
        return m.group(1).strip()
    return addr.strip()


def _strip_angle_brackets(s: str) -> str:
    s = s.strip()
    if s.startswith("<") and s.endswith(">"):
        return s[1:-1].strip()
    return s


def _canonical_iso_from_date_header(date_str: str) -> str:
    try:
        dt = parsedate_to_datetime(date_str)
        if dt is None:
            return ""
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


def _normalize_student_date_iso(s: str) -> str:
    """
    Normalize a student's date string to a canonical isoformat with timezone if possible.
    Accepts:
    - ISO 8601 with timezone: 2024-04-08T10:30:00-04:00
    - ISO 8601 with timezone no colon: 2024-04-08T10:30:00-0400
    - RFC2822-like strings parsable by parsedate_to_datetime
    Returns canonical isoformat string or "" if not parseable.
    """
    s = (s or "").strip()
    if not s:
        return ""
    # Try fromisoformat directly
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # Not acceptable per spec, but normalize anyway by assuming naive -> return empty
            return ""
        return dt.isoformat()
    except Exception:
        pass
    # Try to insert colon in timezone if missing
    m = re.match(r"^(.*\d{2}:\d{2}:\d{2})([+-]\d{2})(\d{2})$", s)
    if m:
        candidate = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                return ""
            return dt.isoformat()
        except Exception:
            pass
    # Try parsedate_to_datetime for RFC 2822 formats
    try:
        dt = parsedate_to_datetime(s)
        if dt is None or dt.tzinfo is None:
            return ""
        return dt.isoformat()
    except Exception:
        return ""


def _parse_email_file(path: Path) -> dict:
    """
    Parse a plain text email file with headers and body, extract fields and intake details.
    Returns a dict with keys:
    message_id, from_email, subject, date_iso,
    child_name, child_age, preferred_times, completed_intake, body
    """
    content = _read_text_safe(path)
    lines = content.splitlines()
    headers = {}
    body_lines = []
    in_headers = True
    for line in lines:
        if in_headers:
            if line.strip() == "":
                in_headers = False
                continue
            # Simple header parse (no folded headers handling needed for provided inputs)
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines)

    message_id_raw = headers.get("message-id", "")
    message_id = _strip_angle_brackets(message_id_raw)

    from_email = _extract_first_email(headers.get("from", ""))
    subject = headers.get("subject", "")
    date_iso = _canonical_iso_from_date_header(headers.get("date", ""))

    # Intake details extraction
    child_name = ""
    child_age = ""
    preferred_times = ""
    completed_intake = ""
    # Find intake block
    start_idx = None
    end_idx = None
    for i, l in enumerate(body_lines):
        if l.strip() == "---- Intake Details ----":
            start_idx = i + 1
            break
    if start_idx is not None:
        # Find end delimiter line of dashes or stop at blank line
        for j in range(start_idx, len(body_lines)):
            if body_lines[j].strip().startswith("---"):
                end_idx = j
                break
        if end_idx is None:
            end_idx = len(body_lines)
        detail_lines = body_lines[start_idx:end_idx]
        for dl in detail_lines:
            if ":" in dl:
                key, val = dl.split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                if key == "child name":
                    child_name = val
                elif key == "age":
                    # store as integer string if possible
                    try:
                        age_int = int(val)
                        child_age = str(age_int)
                    except Exception:
                        child_age = val.strip()
                elif key == "preferred times":
                    preferred_times = val
                elif key == "completed intake":
                    completed_intake = val

    return {
        "message_id": message_id,
        "from_email": from_email,
        "subject": subject,
        "date_iso": date_iso,
        "child_name": child_name,
        "child_age": child_age,
        "preferred_times": preferred_times,
        "completed_intake": completed_intake,
        "body": body,
        "headers": headers,
    }


def _compute_expected_from_inputs(workspace: Path):
    """
    Compute expected included messages and their fields, scores, order, ranks, and top-3 ids.
    Returns list of dicts (in sorted order) and set of top3 ids.
    """
    input_dir = workspace / "input" / "emails"
    if not input_dir.exists():
        return None, None
    email_files = sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in (".txt", "")])
    parsed = []
    for p in email_files:
        parsed.append(_parse_email_file(p))

    included = []
    for item in parsed:
        subj_l = (item["subject"] or "").lower()
        auto_submitted_present = "auto-submitted" in {k for k in item.get("headers", {}).keys()}
        # exclusion rules
        excluded = False
        if (
            "out of office" in subj_l
            or "automatic reply" in subj_l
            or "delivery status notification" in subj_l
            or "mail delivery failed" in subj_l
            or auto_submitted_present
        ):
            excluded = True
        if excluded:
            continue
        # inclusion rules
        include = False
        if any(kw in subj_l for kw in ["intake", "waitlist", "evaluation"]):
            include = True
        if "---- Intake Details ----" in (item["body"] or ""):
            include = True
        if not include:
            continue

        # compute score and reason tags
        score = 0
        tags = []
        if (item.get("completed_intake") or "").strip().lower() == "yes":
            score += 3
            tags.append("has_completed_intake")
        try:
            age_int = int(item.get("child_age") or "")
            if age_int <= 7:
                score += 2
                tags.append("young_child")
        except Exception:
            pass
        if "evaluation" in subj_l:
            score += 1
            tags.append("evaluation_keyword")

        # reason_tags canonical order as defined by spec list:
        # We'll canonicalize in the order: has_completed_intake, young_child, evaluation_keyword
        tag_order = ["has_completed_intake", "young_child", "evaluation_keyword"]
        canonical_tags = [t for t in tag_order if t in tags]
        reason_tags_str = ";".join(canonical_tags)

        included.append(
            {
                "message_id": item["message_id"],
                "from_email": item["from_email"],
                "subject": item["subject"],
                "date_iso": item["date_iso"],
                "child_name": item["child_name"],
                "child_age": item["child_age"],
                "preferred_times": item["preferred_times"],
                "completed_intake": item["completed_intake"],
                "score": score,
                "reason_tags": reason_tags_str,
            }
        )

    # sort by score DESC then date_iso ASC; for date, parse iso to dt for sorting
    def sort_key(it):
        # parse canonical iso to datetime
        dt = None
        try:
            dt = datetime.fromisoformat(it["date_iso"])
        except Exception:
            dt = None
        return (-it["score"], dt)

    included_sorted = sorted(included, key=sort_key)
    # assign rank
    for i, it in enumerate(included_sorted, start=1):
        it["rank"] = i

    top3_ids = set([it["message_id"] for it in included_sorted[:3]])
    return included_sorted, top3_ids


def _split_tags_to_set(s: str):
    parts = [p.strip() for p in (s or "").split(";") if p.strip()]
    return set(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "queue_csv_exists_and_header": 0.0,
        "queue_row_count": 0.0,
        "queue_included_ids_correct": 0.0,
        "queue_fields_values": 0.0,
        "queue_scores_order_ranking": 0.0,
        "drafts_top3_presence": 0.0,
        "drafts_top3_content": 0.0,
    }

    # Compute expected from inputs
    expected_list, expected_top3_ids = _compute_expected_from_inputs(workspace)
    if expected_list is None:
        # Cannot compute expected; return zeros
        return scores

    expected_ids = [it["message_id"] for it in expected_list]
    expected_id_set = set(expected_ids)

    # Load actual CSV
    csv_path = workspace / "output" / "triage_queue.csv"
    header, rows = _load_csv_dicts(csv_path)

    # Check header
    if header is not None and header == EXPECTED_HEADER:
        scores["queue_csv_exists_and_header"] = 1.0

    # If header is wrong or missing, further checks may still proceed cautiously
    # Build actual id set
    actual_ids = []
    id_to_row = {}
    if rows:
        for r in rows:
            mid = (r.get("message_id") or "").strip()
            actual_ids.append(mid)
            id_to_row[mid] = r

    # Row count
    if rows and len(rows) == len(expected_list):
        scores["queue_row_count"] = 1.0

    # Included IDs correctness
    if rows:
        actual_id_set = set(actual_ids)
        if actual_id_set == expected_id_set:
            scores["queue_included_ids_correct"] = 1.0

    # Fields values check (excluding score, rank, reason_tags)
    fields_ok = True
    if rows and id_to_row and expected_list:
        for exp in expected_list:
            mid = exp["message_id"]
            act = id_to_row.get(mid)
            if not act:
                fields_ok = False
                break
            # from_email comparison case-insensitive
            exp_from = (exp["from_email"] or "").strip().lower()
            act_from = (act.get("from_email") or "").strip().lower()
            if exp_from != act_from:
                fields_ok = False
                break
            # subject exact
            if (act.get("subject") or "").strip() != (exp["subject"] or "").strip():
                fields_ok = False
                break
            # date_iso normalize and compare to expected
            act_date_iso_norm = _normalize_student_date_iso(act.get("date_iso") or "")
            if act_date_iso_norm != exp["date_iso"]:
                fields_ok = False
                break
            # child_name exact
            if (act.get("child_name") or "").strip() != (exp["child_name"] or "").strip():
                fields_ok = False
                break
            # child_age as string equal
            if (act.get("child_age") or "").strip() != (exp["child_age"] or "").strip():
                fields_ok = False
                break
            # preferred_times exact
            if (act.get("preferred_times") or "").strip() != (exp["preferred_times"] or "").strip():
                fields_ok = False
                break
            # completed_intake case-insensitive equality to "Yes"/"No"
            exp_ci = (exp["completed_intake"] or "").strip().lower()
            act_ci = (act.get("completed_intake") or "").strip().lower()
            if exp_ci != act_ci:
                fields_ok = False
                break
    else:
        fields_ok = False
    if fields_ok:
        scores["queue_fields_values"] = 1.0

    # Scores, ordering, ranking, reason_tags
    order_ok = True
    scores_ok = True
    ranks_ok = True
    tags_ok = True
    if rows and expected_list:
        # Verify order: actual csv order equals expected sorted order by message_id sequence
        actual_order = actual_ids
        expected_order = expected_ids
        if actual_order != expected_order:
            order_ok = False
        # Verify scores and ranks and tags per row
        for idx, mid in enumerate(expected_order):
            act = id_to_row.get(mid)
            exp = expected_list[idx]
            # score
            try:
                act_score = int(str(act.get("score") or "").strip())
            except Exception:
                scores_ok = False
                break
            if act_score != int(exp["score"]):
                scores_ok = False
                break
            # rank
            try:
                act_rank = int(str(act.get("rank") or "").strip())
            except Exception:
                ranks_ok = False
                break
            if act_rank != exp["rank"] or act_rank != (idx + 1):
                ranks_ok = False
                break
            # reason tags as set
            exp_tags_set = _split_tags_to_set(exp["reason_tags"])
            act_tags_set = _split_tags_to_set(act.get("reason_tags") or "")
            if exp_tags_set != act_tags_set:
                tags_ok = False
                break
    else:
        order_ok = scores_ok = ranks_ok = tags_ok = False

    if order_ok and scores_ok and ranks_ok and tags_ok:
        scores["queue_scores_order_ranking"] = 1.0

    # Drafts presence
    drafts_dir = workspace / "output" / "drafts"
    drafts_ok = False
    if expected_top3_ids is not None:
        if drafts_dir.exists() and drafts_dir.is_dir():
            txt_files = [p for p in drafts_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
            names = set([p.stem for p in txt_files])
            # require exactly top-3 files, no more no less
            if names == expected_top3_ids and len(txt_files) == 3:
                drafts_ok = True
    if drafts_ok:
        scores["drafts_top3_presence"] = 1.0

    # Drafts content for top-3
    content_ok = True
    if drafts_ok:
        # Build info lookup for expected top3
        exp_by_id = {it["message_id"]: it for it in expected_list}
        for mid in expected_top3_ids:
            p = drafts_dir / f"{mid}.txt"
            text = _read_text_safe(p)
            if not text:
                content_ok = False
                break
            exp = exp_by_id.get(mid, {})
            child_name = exp.get("child_name") or ""
            date_iso = exp.get("date_iso") or ""
            completed_intake = (exp.get("completed_intake") or "").strip().lower()
            t_lower = text.lower()

            # No external links or attachments
            if ("http://" in t_lower) or ("https://" in t_lower) or ("www." in t_lower) or ("attachment" in t_lower):
                content_ok = False
                break

            # Greeting: should include a greeting and the child's name
            has_greet_word = any(g in t_lower for g in ["hello", "hi", "dear", "greetings"])
            has_name = child_name and (child_name.lower() in t_lower)
            if not (has_greet_word and has_name):
                content_ok = False
                break

            # Acknowledge receipt on date
            if date_iso not in text:
                content_ok = False
                break

            if completed_intake == "yes":
                # Thank them for completing intake and note scheduling review next
                if ("thank" not in t_lower) or ("complet" not in t_lower):
                    content_ok = False
                    break
                if ("schedul" not in t_lower) and ("review" not in t_lower):
                    content_ok = False
                    break
            else:
                # If any top-3 were "No", ensure we ask to complete intake packet
                # Here all top-3 are "Yes" for provided inputs, but implement check anyway.
                if ("intake" not in t_lower) or ("packet" not in t_lower):
                    content_ok = False
                    break
                # Mention follow-up
                if ("follow-up" not in t_lower) and ("follow up" not in t_lower):
                    content_ok = False
                    break
    else:
        content_ok = False

    if content_ok:
        scores["drafts_top3_content"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()