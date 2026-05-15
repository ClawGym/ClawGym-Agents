import json
import csv
import sys
from pathlib import Path
from datetime import datetime, timedelta


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_iso_date(date_str: str):
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _norm_relpath_str(p: str) -> str:
    # Normalize to forward slashes and strip whitespace
    return str(p).replace("\\", "/").strip()


def _norm_relpath(path: Path, workspace: Path) -> str:
    try:
        rel = path.relative_to(workspace)
    except Exception:
        rel = path
    return _norm_relpath_str(rel.as_posix())


def _rglob_txt_files(root: Path):
    if not root.exists() or not root.is_dir():
        return []
    return sorted(root.rglob("*.txt"))


def _parse_digest_items(text: str):
    # Parse items with fields: Date, Title, Tags, Body
    items = []
    if not text:
        return items
    lines = text.splitlines()
    curr = {}
    def _flush():
        if all(k in curr and curr[k] is not None for k in ("Date", "Title", "Tags", "Body")):
            items.append({
                "date": curr.get("Date", "").strip(),
                "title": curr.get("Title", "").strip(),
                "tags": curr.get("Tags", "").strip(),
                "body": curr.get("Body", "").strip(),
            })
        curr.clear()
    for raw in lines:
        line = raw.strip()
        if not line:
            # blank line: attempt flush
            _flush()
            continue
        if line.startswith("Date:"):
            # start new potential item; flush previous if complete
            if curr and all(k in curr for k in ("Date", "Title", "Tags", "Body")):
                _flush()
            curr["Date"] = line[len("Date:"):].strip()
        elif line.startswith("Title:"):
            curr["Title"] = line[len("Title:"):].strip()
        elif line.startswith("Tags:"):
            curr["Tags"] = line[len("Tags:"):].strip()
        elif line.startswith("Body:"):
            curr["Body"] = line[len("Body:"):].strip()
        else:
            # If body spans multiple lines (not in this dataset), append to body
            if "Body" in curr:
                curr["Body"] = (curr.get("Body", "") + " " + line).strip()
            else:
                # Unrecognized line; ignore
                pass
    # Flush at end
    _flush()
    return items


def _find_matches(text: str, patterns: list) -> set:
    # Case-insensitive substring matches; return set of matched canonical patterns
    matches = set()
    if not text:
        return matches
    tlow = text.lower()
    for p in patterns:
        try:
            if p.lower() in tlow:
                matches.add(p)
        except Exception:
            continue
    return matches


def _compute_expected_records(workspace: Path):
    # Load watchlist
    config_path = workspace / "input" / "watchlist.json"
    watchlist = _load_json(config_path)
    if not isinstance(watchlist, dict):
        return None
    companies = watchlist.get("companies")
    topics = watchlist.get("topics")
    follow_up_windows = watchlist.get("follow_up_windows")
    if not isinstance(companies, list) or not isinstance(topics, list) or not isinstance(follow_up_windows, dict):
        return None

    allowed_tags = set(follow_up_windows.keys())
    # Priority mapping must be fixed as specified
    priority_map = {"funding": 1, "partnership": 2, "product": 3, "hiring": 4}

    news_root = workspace / "input" / "news"
    files = _rglob_txt_files(news_root)

    expected = []
    for f in files:
        text = _read_text(f)
        items = _parse_digest_items(text or "")
        for it in items:
            date_str = it.get("date") or it.get("Date")
            title = it.get("title") or it.get("Title")
            tags = it.get("tags") or it.get("Tags")
            body = it.get("body") or it.get("Body")
            if not (date_str and title and tags is not None and body is not None):
                continue
            # Selection rule 2: Tags must be one of follow_up_windows keys
            if tags not in allowed_tags:
                continue
            # Selection rule 1: Title or Body contains at least one company OR at least one topic
            text_for_match = f"{title}\n{body}"
            matched_companies = _find_matches(text_for_match, companies)
            matched_topics = _find_matches(text_for_match, topics)
            if not (matched_companies or matched_topics):
                continue
            # Build expected record
            rel_path = _norm_relpath(f, workspace)
            category = tags  # derived from Tags
            priority = priority_map.get(category)
            if priority is None:
                # Tags outside mapping should be excluded already, but guard anyway
                continue
            expected.append({
                "date": date_str,
                "title": title,
                "category": category,
                "priority": priority,
                "source_file": rel_path,
                "tags": tags,
                "matched_companies": set(matched_companies),
                "matched_topics": set(matched_topics),
            })
    # Sort rows by date ascending, then title ascending
    def sort_key(rec):
        d = _parse_iso_date(rec["date"])
        return (d.toordinal() if d else float("inf"), rec["title"])
    expected.sort(key=sort_key)
    return expected


def _load_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None, None
    if not rows:
        return [], []
    header = rows[0]
    body = rows[1:]
    return header, body


def _split_semicolon_list(s: str) -> list:
    if s is None:
        return []
    s = s.strip()
    if s == "":
        return []
    parts = [p.strip() for p in s.split(";")]
    # Allow empty parts trimmed out
    return [p for p in parts if p != ""]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "relevant_csv_exists_and_header": 0.0,
        "relevant_csv_row_count_and_set": 0.0,
        "relevant_csv_sorted": 0.0,
        "relevant_csv_values_correct": 0.0,
        "relevant_csv_matched_lists_correct": 0.0,
        "followups_json_exists_and_schema": 0.0,
        "followups_count_matches_csv": 0.0,
        "followups_due_dates_and_reason": 0.0,
    }

    expected_records = _compute_expected_records(workspace)

    # Paths for outputs
    csv_path = workspace / "output" / "relevant.csv"
    json_path = workspace / "output" / "followups.json"

    # CSV existence and header
    header, body = _load_csv(csv_path)
    expected_header = ["date", "title", "category", "priority", "source_file", "tags", "matched_companies", "matched_topics"]
    if header is not None:
        if header == expected_header:
            scores["relevant_csv_exists_and_header"] = 1.0
        else:
            scores["relevant_csv_exists_and_header"] = 0.0
    else:
        scores["relevant_csv_exists_and_header"] = 0.0

    # When expected input cannot be computed, dependent checks remain 0.0
    if expected_records is None or header is None:
        # Still attempt to load followups.json schema even if we can't compute expected
        raw = _load_json(json_path)
        if isinstance(raw, list):
            # Minimal schema check
            required_keys = {"title", "due_date", "reason", "source_title", "source_date", "source_file", "category", "priority"}
            ok = True
            for elem in raw:
                if not isinstance(elem, dict):
                    ok = False
                    break
                if not required_keys.issubset(set(elem.keys())):
                    ok = False
                    break
            scores["followups_json_exists_and_schema"] = 1.0 if ok else 0.0
        else:
            scores["followups_json_exists_and_schema"] = 0.0
        return scores

    # Build expected mapping keyed by (date, title, source_file)
    expected_map = {}
    for rec in expected_records:
        key = (rec["date"], rec["title"], _norm_relpath_str(rec["source_file"]))
        expected_map[key] = rec

    # Parse actual CSV rows into records list
    actual_rows = []
    csv_parsed_ok = True
    for r in body or []:
        if len(r) != len(expected_header):
            csv_parsed_ok = False
            break
        row = dict(zip(expected_header, r))
        # Normalize fields
        row["source_file"] = _norm_relpath_str(row.get("source_file", ""))
        row["date"] = (row.get("date") or "").strip()
        row["title"] = (row.get("title") or "").strip()
        row["category"] = (row.get("category") or "").strip()
        row["tags"] = (row.get("tags") or "").strip()
        row["priority"] = (row.get("priority") or "").strip()
        row["matched_companies"] = _split_semicolon_list(row.get("matched_companies", ""))
        row["matched_topics"] = _split_semicolon_list(row.get("matched_topics", ""))
        actual_rows.append(row)

    if not csv_parsed_ok:
        # Can't proceed with CSV-dependent checks
        # But still can attempt followups schema
        raw = _load_json(json_path)
        if isinstance(raw, list):
            required_keys = {"title", "due_date", "reason", "source_title", "source_date", "source_file", "category", "priority"}
            ok = True
            for elem in raw:
                if not isinstance(elem, dict):
                    ok = False
                    break
                if not required_keys.issubset(set(elem.keys())):
                    ok = False
                    break
            scores["followups_json_exists_and_schema"] = 1.0 if ok else 0.0
        else:
            scores["followups_json_exists_and_schema"] = 0.0
        return scores

    # Row count and set equality
    actual_keys = {(row["date"], row["title"], row["source_file"]) for row in actual_rows}
    if len(actual_rows) == len(expected_records) and actual_keys == set(expected_map.keys()):
        scores["relevant_csv_row_count_and_set"] = 1.0
    else:
        scores["relevant_csv_row_count_and_set"] = 0.0

    # Sorted check by date asc then title asc
    sorted_actual = sorted(
        actual_rows,
        key=lambda x: ((_parse_iso_date(x["date"]).toordinal() if _parse_iso_date(x["date"]) else float("inf")), x["title"])
    )
    if [ (r["date"], r["title"]) for r in actual_rows ] == [ (r["date"], r["title"]) for r in sorted_actual ]:
        scores["relevant_csv_sorted"] = 1.0
    else:
        scores["relevant_csv_sorted"] = 0.0

    # Values correctness and matched lists correctness
    values_ok = True
    matched_ok = True
    # Priority mapping
    priority_map = {"funding": 1, "partnership": 2, "product": 3, "hiring": 4}
    for row in actual_rows:
        key = (row["date"], row["title"], row["source_file"])
        exp = expected_map.get(key)
        if not exp:
            values_ok = False
            matched_ok = False
            break
        # Check category and tags exact
        if row["category"] != exp["category"]:
            values_ok = False
        if row["tags"] != exp["tags"]:
            values_ok = False
        # Check priority numeric and equals expected
        try:
            pr = int(row["priority"])
        except Exception:
            pr = None
        if pr != exp["priority"]:
            values_ok = False
        # Matched companies/topics: compare case-insensitive sets; ensure uniqueness (no duplicates)
        act_companies_list = row["matched_companies"]
        act_topics_list = row["matched_topics"]
        # uniqueness check (case-insensitive)
        if len({c.lower() for c in act_companies_list}) != len(act_companies_list):
            matched_ok = False
        if len({t.lower() for t in act_topics_list}) != len(act_topics_list):
            matched_ok = False
        # Compare sets ignoring case
        act_companies_set = {c.lower() for c in act_companies_list}
        act_topics_set = {t.lower() for t in act_topics_list}
        exp_companies_set = {c.lower() for c in exp["matched_companies"]}
        exp_topics_set = {t.lower() for t in exp["matched_topics"]}
        if act_companies_set != exp_companies_set:
            matched_ok = False
        if act_topics_set != exp_topics_set:
            matched_ok = False
        # Check that category derived from tags (should match)
        if row["category"] != row["tags"]:
            values_ok = False
        # Priority mapping consistent with category
        if priority_map.get(row["category"]) != pr:
            values_ok = False

    scores["relevant_csv_values_correct"] = 1.0 if values_ok else 0.0
    scores["relevant_csv_matched_lists_correct"] = 1.0 if matched_ok else 0.0

    # Followups JSON existence and schema
    followups_raw = _load_json(json_path)
    schema_ok = False
    if isinstance(followups_raw, list):
        required_keys = {"title", "due_date", "reason", "source_title", "source_date", "source_file", "category", "priority"}
        schema_ok = True
        for elem in followups_raw:
            if not isinstance(elem, dict):
                schema_ok = False
                break
            if not required_keys.issubset(set(elem.keys())):
                schema_ok = False
                break
            # Basic type checks
            if not isinstance(elem.get("title"), str):
                schema_ok = False
                break
            if not isinstance(elem.get("due_date"), str):
                schema_ok = False
                break
            if not isinstance(elem.get("reason"), str):
                schema_ok = False
                break
            if not isinstance(elem.get("source_title"), str):
                schema_ok = False
                break
            if not isinstance(elem.get("source_date"), str):
                schema_ok = False
                break
            if not isinstance(elem.get("source_file"), str):
                schema_ok = False
                break
            if not isinstance(elem.get("category"), str):
                schema_ok = False
                break
            # priority should be int-like
            try:
                int(elem.get("priority"))
            except Exception:
                schema_ok = False
                break
    scores["followups_json_exists_and_schema"] = 1.0 if schema_ok else 0.0

    # Followups count matches CSV and cross-ref by (source_title, source_date, source_file)
    count_crossref_ok = False
    due_reason_ok = False
    if schema_ok:
        # Build mapping from triple to reminder
        followup_map = {}
        for elem in followups_raw:
            key = (_norm_relpath_str(elem.get("source_date", "").strip()),
                   elem.get("source_title", "").strip(),
                   _norm_relpath_str(elem.get("source_file", "").strip()))
            followup_map[key] = elem
        if len(followups_raw) == len(actual_rows):
            all_match = True
            for row in actual_rows:
                key = (row["date"], row["title"], row["source_file"])
                if key not in followup_map:
                    all_match = False
                    break
            count_crossref_ok = all_match
        else:
            count_crossref_ok = False

        # Due date and reason correctness for each matched item
        if count_crossref_ok:
            # Need watchlist follow_up_windows mapping for due date computation
            watchlist = _load_json(workspace / "input" / "watchlist.json")
            follow_up_windows = watchlist.get("follow_up_windows") if isinstance(watchlist, dict) else None
            if isinstance(follow_up_windows, dict):
                all_due_ok = True
                for row in actual_rows:
                    key = (row["date"], row["title"], row["source_file"])
                    rem = followup_map.get(key)
                    if not rem:
                        all_due_ok = False
                        break
                    # Category and priority in reminder should match CSV/mapping
                    rem_cat = rem.get("category")
                    try:
                        rem_pri = int(rem.get("priority"))
                    except Exception:
                        rem_pri = None
                    # Compute expected due date
                    src_date = _parse_iso_date(row["date"])
                    if src_date is None:
                        all_due_ok = False
                        break
                    offset = follow_up_windows.get(row["category"])
                    if not isinstance(offset, int):
                        all_due_ok = False
                        break
                    expected_due = (src_date + timedelta(days=offset)).strftime("%Y-%m-%d")
                    if rem.get("due_date") != expected_due:
                        all_due_ok = False
                    # Reason should be "Follow up on {category}"
                    expected_reason = f"Follow up on {row['category']}"
                    if rem.get("reason") != expected_reason:
                        all_due_ok = False
                    # Category consistency
                    if rem_cat != row["category"]:
                        all_due_ok = False
                    # Priority consistency
                    priority_map = {"funding": 1, "partnership": 2, "product": 3, "hiring": 4}
                    if rem_pri != priority_map.get(row["category"]):
                        all_due_ok = False
                due_reason_ok = all_due_ok
            else:
                due_reason_ok = False
        else:
            due_reason_ok = False

    scores["followups_count_matches_csv"] = 1.0 if count_crossref_ok else 0.0
    scores["followups_due_dates_and_reason"] = 1.0 if due_reason_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()