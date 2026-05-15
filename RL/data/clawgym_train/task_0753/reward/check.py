import json
import csv
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _load_quotes_jsonl(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    # Loads quotes.jsonl into a dict keyed by quote_id with the full record
    if not path.is_file():
        return None
    quotes: Dict[str, Dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                qid = obj.get("quote_id")
                if not isinstance(qid, str):
                    return None
                quotes[qid] = obj
    except Exception:
        return None
    return quotes


def _sha256_hex(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not path.is_file():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return [], []
            rows_list: List[Dict[str, str]] = []
            for row in reader:
                # Pad or trim to header length
                if len(row) < len(header):
                    row = row + [""] * (len(header) - len(row))
                elif len(row) > len(header):
                    row = row[: len(header)]
                rows_list.append(dict(zip(header, row)))
        return header, rows_list
    except Exception:
        return None, None


def _extract_hashtags_from_text(text: str) -> List[str]:
    # Hashtags as tokens starting with # and followed by non-space and not another '#'
    return re.findall(r"#\S+", text, flags=re.UNICODE)


def _parse_hashtags_field(field: str) -> List[str]:
    if field is None:
        return []
    # Extract tokens that start with #
    return re.findall(r"#\S+", field, flags=re.UNICODE)


def _casefold(s: str) -> str:
    return s.casefold() if hasattr(s, "casefold") else s.lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize all score keys to 0.0
    scores: Dict[str, float] = {
        "script_present": 0.0,
        "posts_csv_header_valid": 0.0,
        "posts_row_count": 0.0,
        "per_event_platforms_correct": 0.0,
        "char_limits_respected": 0.0,
        "char_count_correct": 0.0,
        "date_inclusion_correct": 0.0,
        "keyword_inclusion_present": 0.0,
        "quote_id_valid": 0.0,
        "quote_text_and_format_valid": 0.0,
        "hashtags_count_and_format_valid": 0.0,
        "hashtags_derived_from_event": 0.0,
        "usage_report_fields_valid": 0.0,
        "usage_report_counts_match": 0.0,
        "input_checksums_match": 0.0,
    }

    # Paths
    script_path = workspace / "scripts" / "make_posts.py"
    posts_csv_path = workspace / "outputs" / "posts.csv"
    usage_report_path = workspace / "outputs" / "usage_report.json"
    events_json_path = workspace / "input" / "events.json"
    quotes_jsonl_path = workspace / "input" / "quotes.jsonl"

    # Check script presence
    if script_path.is_file():
        scores["script_present"] = 1.0

    # Load inputs
    events_obj = _load_json(events_json_path)
    quotes_dict = _load_quotes_jsonl(quotes_jsonl_path)

    # Prepare event mappings
    event_map: Dict[str, Dict[str, Any]] = {}
    event_ids: List[str] = []
    if isinstance(events_obj, dict) and isinstance(events_obj.get("events"), list):
        for ev in events_obj["events"]:
            if isinstance(ev, dict) and isinstance(ev.get("event_id"), str):
                event_map[ev["event_id"]] = ev
                event_ids.append(ev["event_id"])

    # Load posts CSV
    header, rows = _load_csv(posts_csv_path)

    expected_header = ["event_id", "date", "platform", "quote_id", "hashtags", "char_count", "post_text"]
    if header is not None and rows is not None and header == expected_header:
        scores["posts_csv_header_valid"] = 1.0

    # Posts row count: must be 2 per event
    if rows is not None and event_ids:
        if len(rows) == 2 * len(event_ids):
            scores["posts_row_count"] = 1.0

    # per_event_platforms_correct: exactly one X and one Facebook per event
    per_event_ok = True
    if rows is None or not event_ids:
        per_event_ok = False
    else:
        # group by event_id
        by_event: Dict[str, List[Dict[str, str]]] = {eid: [] for eid in event_ids}
        for r in rows:
            eid = r.get("event_id", "")
            if eid in by_event:
                by_event[eid].append(r)
        for eid in event_ids:
            lst = by_event.get(eid, [])
            platforms = [r.get("platform", "") for r in lst]
            if len(lst) != 2 or sorted(platforms) != ["Facebook", "X"]:
                per_event_ok = False
                break
    if per_event_ok:
        scores["per_event_platforms_correct"] = 1.0

    # Char limits and char_count correctness
    char_limits_ok = True
    char_count_ok = True
    if rows is None:
        char_limits_ok = False
        char_count_ok = False
    else:
        for r in rows:
            platform = r.get("platform", "")
            text = r.get("post_text", "")
            try:
                cc = int(r.get("char_count", ""))
            except Exception:
                char_count_ok = False
                cc = None  # type: ignore
            if cc is None or cc != len(text):
                char_count_ok = False
            if platform == "X":
                if len(text) > 280:
                    char_limits_ok = False
            elif platform == "Facebook":
                if len(text) > 600:
                    char_limits_ok = False
            else:
                # Unknown platform fails the limits check
                char_limits_ok = False
    if char_limits_ok:
        scores["char_limits_respected"] = 1.0
    if char_count_ok:
        scores["char_count_correct"] = 1.0

    # Date inclusion and keyword inclusion
    date_inclusion_ok = True
    keyword_inclusion_ok = True
    if rows is None or not event_map:
        date_inclusion_ok = False
        keyword_inclusion_ok = False
    else:
        for r in rows:
            eid = r.get("event_id", "")
            date_csv = r.get("date", "")
            text = r.get("post_text", "")
            ev = event_map.get(eid)
            if not ev or "date" not in ev:
                date_inclusion_ok = False
                keyword_inclusion_ok = False
                continue
            expected_date = ev["date"]
            # CSV date matches event date
            if date_csv != expected_date:
                date_inclusion_ok = False
            # post text contains date
            if expected_date not in text:
                date_inclusion_ok = False
            # keyword inclusion: at least one keyword from event is present (case-insensitive)
            kwds = ev.get("keywords", [])
            text_cf = _casefold(text)
            if not isinstance(kwds, list) or not kwds:
                keyword_inclusion_ok = False
            else:
                found_kw = False
                for kw in kwds:
                    if isinstance(kw, str) and _casefold(kw) in text_cf:
                        found_kw = True
                        break
                if not found_kw:
                    keyword_inclusion_ok = False
    if date_inclusion_ok:
        scores["date_inclusion_correct"] = 1.0
    if keyword_inclusion_ok:
        scores["keyword_inclusion_present"] = 1.0

    # Quote checks
    quote_id_valid_ok = True
    quote_text_and_format_ok = True
    if rows is None or quotes_dict is None:
        quote_id_valid_ok = False
        quote_text_and_format_ok = False
    else:
        for r in rows:
            qid = r.get("quote_id", "")
            text = r.get("post_text", "")
            # quote_id must exist
            if qid not in quotes_dict:
                quote_id_valid_ok = False
                quote_text_and_format_ok = False
                continue
            quote_text = quotes_dict[qid].get("text", None)
            if not isinstance(quote_text, str):
                quote_id_valid_ok = False
                quote_text_and_format_ok = False
                continue
            # exactly one pair of Polish quotation marks „ … ”
            open_count = text.count("„")
            close_count = text.count("”")
            if open_count != 1 or close_count != 1:
                quote_text_and_format_ok = False
                continue
            try:
                start = text.index("„")
                end = text.rindex("”")
            except ValueError:
                quote_text_and_format_ok = False
                continue
            if start >= end:
                quote_text_and_format_ok = False
                continue
            quoted = text[start + 1 : end]
            # quoted text must match quote_text exactly
            if quoted != quote_text:
                quote_text_and_format_ok = False
            # post must end with [quote_id] tag
            if not text.rstrip().endswith(f"[{qid}]"):
                quote_text_and_format_ok = False
    if quote_id_valid_ok:
        scores["quote_id_valid"] = 1.0
    if quote_text_and_format_ok:
        scores["quote_text_and_format_valid"] = 1.0

    # Hashtags checks
    hashtags_count_and_format_ok = True
    hashtags_derived_ok = True
    if rows is None or not event_map:
        hashtags_count_and_format_ok = False
        hashtags_derived_ok = False
    else:
        for r in rows:
            eid = r.get("event_id", "")
            text = r.get("post_text", "")
            hs_field = r.get("hashtags", "")
            ev = event_map.get(eid)
            if not ev:
                hashtags_count_and_format_ok = False
                hashtags_derived_ok = False
                continue
            themes = [t for t in ev.get("themes", []) if isinstance(t, str)]
            keywords = [k for k in ev.get("keywords", []) if isinstance(k, str)]
            expected_terms_cf = [_casefold(x) for x in (themes + keywords)]
            # Extract hashtags from post_text
            hs_in_text = _extract_hashtags_from_text(text)
            # Extract hashtags from csv field
            hs_in_field = _parse_hashtags_field(hs_field)
            # Count between 2 and 3
            if not (2 <= len(hs_in_text) <= 3):
                hashtags_count_and_format_ok = False
            # Ensure each hashtag has no spaces and starts with #
            for h in hs_in_text:
                if not h.startswith("#") or (" " in h):
                    hashtags_count_and_format_ok = False
            # Compare sets from field and text
            if set(hs_in_text) != set(hs_in_field):
                hashtags_count_and_format_ok = False
            # Derived from themes/keywords: each hashtag base contains at least one term (case-insensitive)
            for h in hs_in_text:
                base = _casefold(h.lstrip("#"))
                if not any(term in base for term in expected_terms_cf if term):
                    hashtags_derived_ok = False
    if hashtags_count_and_format_ok:
        scores["hashtags_count_and_format_valid"] = 1.0
    if hashtags_derived_ok:
        scores["hashtags_derived_from_event"] = 1.0

    # Usage report checks
    usage_obj = _load_json(usage_report_path)
    usage_fields_ok = True
    usage_counts_ok = True
    checksums_ok = True

    if not isinstance(usage_obj, dict):
        usage_fields_ok = False
        usage_counts_ok = False
        checksums_ok = False
    else:
        # Validate required keys existence and basic types
        total_posts = usage_obj.get("total_posts")
        per_platform = usage_obj.get("per_platform")
        per_quote = usage_obj.get("per_quote")
        per_event = usage_obj.get("per_event")
        input_checksums = usage_obj.get("input_checksums")

        if not isinstance(total_posts, int):
            usage_fields_ok = False
        if not (isinstance(per_platform, dict) and "X" in per_platform and "Facebook" in per_platform):
            usage_fields_ok = False
        else:
            if not (isinstance(per_platform.get("X"), int) and isinstance(per_platform.get("Facebook"), int)):
                usage_fields_ok = False
        if not isinstance(per_quote, dict):
            usage_fields_ok = False
        else:
            for k, v in per_quote.items():
                if not isinstance(k, str) or not isinstance(v, int):
                    usage_fields_ok = False
                    break
        if not isinstance(per_event, dict):
            usage_fields_ok = False
        else:
            for eid, obj in per_event.items():
                if not isinstance(eid, str) or not isinstance(obj, dict):
                    usage_fields_ok = False
                    break
                if not ("x_quote_id" in obj and "facebook_quote_id" in obj):
                    usage_fields_ok = False
                    break
                if not (isinstance(obj["x_quote_id"], str) and isinstance(obj["facebook_quote_id"], str)):
                    usage_fields_ok = False
                    break
        if not isinstance(input_checksums, dict):
            usage_fields_ok = False
        else:
            # basic presence and hex format
            for key in ["input/events.json", "input/quotes.jsonl"]:
                val = input_checksums.get(key)
                if not (isinstance(val, str) and len(val) == 64 and all(c in "0123456789abcdef" for c in val.lower())):
                    usage_fields_ok = False

        # Counts match check only if posts csv rows are loaded
        if rows is None:
            usage_counts_ok = False
        else:
            # total posts
            if isinstance(total_posts, int):
                if total_posts != len(rows):
                    usage_counts_ok = False
            else:
                usage_counts_ok = False
            # per platform counts
            if isinstance(per_platform, dict):
                count_x = sum(1 for r in rows if r.get("platform") == "X")
                count_fb = sum(1 for r in rows if r.get("platform") == "Facebook")
                if per_platform.get("X") != count_x or per_platform.get("Facebook") != count_fb:
                    usage_counts_ok = False
            else:
                usage_counts_ok = False
            # per quote counts
            if isinstance(per_quote, dict):
                computed_per_quote: Dict[str, int] = {}
                for r in rows:
                    qid = r.get("quote_id", "")
                    computed_per_quote[qid] = computed_per_quote.get(qid, 0) + 1
                # All keys and counts must match exactly
                if set(computed_per_quote.keys()) != set(per_quote.keys()):
                    usage_counts_ok = False
                else:
                    for qid, cnt in computed_per_quote.items():
                        if per_quote.get(qid) != cnt:
                            usage_counts_ok = False
                            break
            else:
                usage_counts_ok = False
            # per event mapping
            if isinstance(per_event, dict):
                # build expected mapping from posts
                expected_map: Dict[str, Dict[str, str]] = {}
                for r in rows:
                    eid = r.get("event_id", "")
                    plat = r.get("platform", "")
                    qid = r.get("quote_id", "")
                    if eid not in expected_map:
                        expected_map[eid] = {}
                    if plat == "X":
                        expected_map[eid]["x_quote_id"] = qid
                    elif plat == "Facebook":
                        expected_map[eid]["facebook_quote_id"] = qid
                # Ensure for each event in rows, both entries present and match usage report
                for eid, sub in expected_map.items():
                    usage_sub = per_event.get(eid)
                    if not isinstance(usage_sub, dict):
                        usage_counts_ok = False
                        break
                    if usage_sub.get("x_quote_id") != sub.get("x_quote_id"):
                        usage_counts_ok = False
                        break
                    if usage_sub.get("facebook_quote_id") != sub.get("facebook_quote_id"):
                        usage_counts_ok = False
                        break
            else:
                usage_counts_ok = False

        # Checksums match
        if isinstance(input_checksums, dict):
            ev_sha = _sha256_hex(events_json_path)
            q_sha = _sha256_hex(quotes_jsonl_path)
            if ev_sha is None or q_sha is None:
                checksums_ok = False
            else:
                if input_checksums.get("input/events.json") != ev_sha:
                    checksums_ok = False
                if input_checksums.get("input/quotes.jsonl") != q_sha:
                    checksums_ok = False
        else:
            checksums_ok = False

    if usage_fields_ok:
        scores["usage_report_fields_valid"] = 1.0
    if usage_counts_ok:
        scores["usage_report_counts_match"] = 1.0
    if checksums_ok:
        scores["input_checksums_match"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()