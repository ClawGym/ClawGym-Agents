import json
import sys
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


DATE_FMT = "%Y-%m-%d"
ALLOWED_LEVELS = {"High", "Medium", "Low"}


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return (reader.fieldnames, rows)
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), DATE_FMT)
    except Exception:
        return None


def _compute_days(start_s: str, end_s: str) -> Optional[int]:
    sd = _parse_iso_date(start_s)
    ed = _parse_iso_date(end_s)
    if sd is None or ed is None:
        return None
    if ed < sd:
        return None
    return (ed - sd).days + 1


def _normalize_from_input_csv(workspace: Path) -> Optional[List[Dict[str, object]]]:
    """Replicate tools/normalize_events.py logic deterministically without modifying workspace."""
    input_path = workspace / "input" / "events.csv"
    header_rows = _load_csv_dicts(input_path)
    if header_rows is None:
        return None
    fieldnames, rows = header_rows
    required = {"name", "tradition", "start_date", "end_date", "observance_level", "notes"}
    if not required.issubset(set(fieldnames or [])):
        return None
    records = []
    for idx, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        tradition = (row.get("tradition") or "").strip()
        start_raw = (row.get("start_date") or "").strip()
        end_raw = (row.get("end_date") or "").strip()
        level = (row.get("observance_level") or "").strip()
        notes = (row.get("notes") or "").strip()
        if level not in ALLOWED_LEVELS:
            return None
        sd = _parse_iso_date(start_raw)
        ed = _parse_iso_date(end_raw)
        if sd is None or ed is None:
            return None
        if ed < sd:
            return None
        days = (ed - sd).days + 1
        rec = {
            "name": name,
            "tradition": tradition,
            "start_date": sd.strftime(DATE_FMT),
            "end_date": ed.strftime(DATE_FMT),
            "observance_level": level,
            "days": days,
            "notes": notes,
        }
        records.append(rec)
    # Deduplicate by (name.lower(), start_date, end_date), preserving first occurrence
    seen = set()
    unique = []
    for r in records:
        key = (r["name"].lower(), r["start_date"], r["end_date"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _load_normalized_json(workspace: Path) -> Optional[List[Dict[str, object]]]:
    p = workspace / "output" / "events_normalized.json"
    data = _load_json(p)
    if not isinstance(data, list):
        return None
    # Validate structure
    req_keys = {"name", "tradition", "start_date", "end_date", "observance_level", "days", "notes"}
    out = []
    for item in data:
        if not isinstance(item, dict):
            return None
        if not req_keys.issubset(set(item.keys())):
            return None
        # Validate types
        if not isinstance(item["name"], str):
            return None
        if not isinstance(item["tradition"], str):
            return None
        if not isinstance(item["start_date"], str):
            return None
        if not isinstance(item["end_date"], str):
            return None
        if not isinstance(item["observance_level"], str):
            return None
        if not isinstance(item["days"], int):
            return None
        if not isinstance(item["notes"], str):
            return None
        # Validate fields consistency
        if item["observance_level"] not in ALLOWED_LEVELS:
            return None
        if _parse_iso_date(item["start_date"]) is None or _parse_iso_date(item["end_date"]) is None:
            return None
        computed_days = _compute_days(item["start_date"], item["end_date"])
        if computed_days is None or computed_days != item["days"]:
            return None
        out.append(item)
    return out


def _overlaps(win_start: datetime, win_end: datetime, start_s: str, end_s: str) -> bool:
    sd = _parse_iso_date(start_s)
    ed = _parse_iso_date(end_s)
    if sd is None or ed is None:
        return False
    return ed >= win_start and sd <= win_end


def _level_rank(level: str) -> int:
    order = {"High": 0, "Medium": 1, "Low": 2}
    return order.get(level, 99)


def _compute_expected_ranked(normalized: List[Dict[str, object]], prefs: Dict[str, object]) -> Optional[List[Dict[str, str]]]:
    if not isinstance(prefs, dict):
        return None
    tw = prefs.get("time_window") or {}
    tw_start_s = tw.get("start")
    tw_end_s = tw.get("end")
    if not isinstance(tw_start_s, str) or not isinstance(tw_end_s, str):
        return None
    win_start = _parse_iso_date(tw_start_s)
    win_end = _parse_iso_date(tw_end_s)
    if win_start is None or win_end is None:
        return None
    prioritized_traditions = prefs.get("prioritized_traditions") or []
    if not isinstance(prioritized_traditions, list):
        prioritized_traditions = []
    prioritized_set = set([str(t) for t in prioritized_traditions])

    filtered = [
        rec for rec in normalized
        if _overlaps(win_start, win_end, rec["start_date"], rec["end_date"])
    ]
    # Sort by (level rank, prioritized flag, start_date asc, name asc for tie)
    def sort_key(rec):
        prio_flag = 0 if rec["tradition"] in prioritized_set else 1
        return (_level_rank(rec["observance_level"]), prio_flag, rec["start_date"], rec["name"])
    filtered_sorted = sorted(filtered, key=sort_key)

    # Build expected CSV rows (strings)
    expected_rows = []
    for i, rec in enumerate(filtered_sorted, start=1):
        expected_rows.append({
            "start_date": rec["start_date"],
            "end_date": rec["end_date"],
            "name": rec["name"],
            "tradition": rec["tradition"],
            "observance_level": rec["observance_level"],
            "days": str(rec["days"]),
            "notes": rec["notes"],
            "priority_rank": str(i),
        })
    return expected_rows


def _compare_normalized(expected: Optional[List[Dict[str, object]]], actual: Optional[List[Dict[str, object]]]) -> bool:
    if expected is None or actual is None:
        return False
    # Exact sequence equality on list of dicts with the same keys/values
    if len(expected) != len(actual):
        return False
    for e, a in zip(expected, actual):
        if e != a:
            return False
    return True


def _load_preferences(workspace: Path) -> Optional[Dict[str, object]]:
    p = workspace / "input" / "preferences.json"
    data = _load_json(p)
    if not isinstance(data, dict):
        return None
    return data


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)


def _contains_all(text: str, substrs: List[str]) -> bool:
    t = text.lower()
    return all(sub.lower() in t for sub in substrs)


def _any_contains(text: str, substrs: List[str]) -> bool:
    t = text.lower()
    return any(sub.lower() in t for sub in substrs)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "events_normalized_json_valid": 0.0,
        "normalization_matches_script_logic": 0.0,
        "normalize_log_success_and_count": 0.0,
        "normalize_log_contains_errors": 0.0,
        "ranked_csv_exact_match": 0.0,
        "announcements_exist": 0.0,
        "long_word_count_150_200": 0.0,
        "short_word_count_leq_75": 0.0,
        "long_includes_top_names": 0.0,
        "long_includes_top_dates_iso": 0.0,
        "short_points_to_ranked_list": 0.0,
        "announcements_avoid_biased_phrases": 0.0,
        "diagnostics_includes_errors_quotes": 0.0,
        "diagnostics_corrections_documented": 0.0,
        "diagnostics_counts_correct": 0.0,
    }

    # Load normalized JSON
    normalized = _load_normalized_json(workspace)
    if isinstance(normalized, list):
        scores["events_normalized_json_valid"] = 1.0

    # Compare normalization to expected computed from input
    expected_normalized = _normalize_from_input_csv(workspace)
    if normalized is not None and expected_normalized is not None and _compare_normalized(expected_normalized, normalized):
        scores["normalization_matches_script_logic"] = 1.0

    # Check normalize.log for success and errors
    normalize_log_path = workspace / "output" / "normalize.log"
    log_text = _read_text(normalize_log_path) or ""
    if normalized is not None and log_text:
        # Success line should contain "Wrote {len(normalized)} normalized records to output/events_normalized.json"
        success_pattern = re.compile(r"Wrote\s+(\d+)\s+normalized records to output/events_normalized\.json")
        m = success_pattern.search(log_text)
        if m:
            try:
                count_logged = int(m.group(1))
                if count_logged == len(normalized):
                    scores["normalize_log_success_and_count"] = 1.0
            except Exception:
                pass
    if "ERROR:" in log_text:
        scores["normalize_log_contains_errors"] = 1.0

    # Ranked CSV exact match to expected computed from normalized and preferences
    prefs = _load_preferences(workspace)
    expected_ranked = None
    if normalized is not None and prefs is not None:
        expected_ranked = _compute_expected_ranked(normalized, prefs)
    ranked_csv_path = workspace / "output" / "q2_observances_ranked.csv"
    ranked_loaded = _load_csv_dicts(ranked_csv_path)
    if expected_ranked is not None and ranked_loaded is not None:
        header, rows = ranked_loaded
        expected_header = ["start_date", "end_date", "name", "tradition", "observance_level", "days", "notes", "priority_rank"]
        # Strict header equality
        if header == expected_header:
            # Convert all row values to str for comparison
            actual_rows = []
            ok = True
            for r in rows:
                try:
                    actual_rows.append({
                        "start_date": r["start_date"],
                        "end_date": r["end_date"],
                        "name": r["name"],
                        "tradition": r["tradition"],
                        "observance_level": r["observance_level"],
                        "days": str(int(r["days"])),  # ensure numeric string
                        "notes": r["notes"],
                        "priority_rank": str(int(r["priority_rank"])),
                    })
                except Exception:
                    ok = False
                    break
            if ok and actual_rows == expected_ranked:
                scores["ranked_csv_exact_match"] = 1.0

    # Announcements existence and basic checks
    long_path = workspace / "output" / "announcements" / "long.md"
    short_path = workspace / "output" / "announcements" / "short.md"
    long_text = _read_text(long_path) or ""
    short_text = _read_text(short_path) or ""
    if long_text and short_text:
        scores["announcements_exist"] = 1.0

    # Word count checks
    if long_text:
        wc_long = _word_count(long_text)
        if 150 <= wc_long <= 200:
            scores["long_word_count_150_200"] = 1.0
    if short_text:
        wc_short = _word_count(short_text)
        if wc_short <= 75:
            scores["short_word_count_leq_75"] = 1.0

    # Long includes top-ranked names (from student's ranked CSV if available)
    top_names = []
    top_dates = {}
    if ranked_loaded is not None:
        _, rows = ranked_loaded
        # Ensure rows are sorted by priority_rank ascending
        try:
            rows_sorted = sorted(rows, key=lambda r: int(r.get("priority_rank", "999999")))
        except Exception:
            rows_sorted = rows
        for r in rows_sorted[:5]:
            n = r.get("name", "")
            top_names.append(n)
            top_dates[n] = (r.get("start_date", ""), r.get("end_date", ""))
    # Check that long.md mentions at least the top 3 names, and dates in ISO for those
    if long_text and top_names:
        top3 = top_names[:3]
        present_names = [n for n in top3 if n and n in long_text]
        if len(present_names) == 3:
            scores["long_includes_top_names"] = 1.0
        # Dates check: require at least the start_date of each of the top 3 events present in ISO format
        date_ok = True
        for n in top3:
            sd = top_dates.get(n, ("", ""))[0]
            if not sd or sd not in long_text:
                date_ok = False
                break
        if date_ok:
            scores["long_includes_top_dates_iso"] = 1.0

    # Short points to ranked list
    if short_text:
        if ("ranked" in short_text.lower()) and ("output/q2_observances_ranked.csv" in short_text or "ranked list" in short_text.lower()):
            scores["short_points_to_ranked_list"] = 1.0

    # Announcements tone basic neutrality check (avoid biased phrase from draft)
    banned_phrases = ["non-christian", "endorse", "favor", "prefer", "preference for", "priority to"]
    if long_text and short_text:
        if not _any_contains(long_text, banned_phrases) and not _any_contains(short_text, banned_phrases):
            scores["announcements_avoid_biased_phrases"] = 1.0

    # Diagnostics checks
    diagnostics_path = workspace / "output" / "diagnostics.md"
    diag_text = _read_text(diagnostics_path) or ""
    # (a) includes initial errors quoted (look for "ERROR:" occurrences)
    if diag_text and "ERROR:" in diag_text:
        scores["diagnostics_includes_errors_quotes"] = 1.0
    # (b) exact input corrections documented (before → after snippets): check for specific corrections
    # 2026/04/03 -> 2026-04-03, Apr 09 2026 -> 2026-04-09, low -> Low
    if diag_text:
        corr1_before = "2026/04/03" in diag_text and "2026-04-03" in diag_text
        corr2_before = "Apr 09 2026" in diag_text and "2026-04-09" in diag_text
        # ensure low->Low in the context of International Day of Yoga line
        corr3_before = ("low" in diag_text or "Low" in diag_text) and ("International Day of Yoga" in diag_text)
        if corr1_before and corr2_before and corr3_before:
            scores["diagnostics_corrections_documented"] = 1.0
    # (c) final counts from normalized JSON (total normalized; count within Q2)
    if diag_text and normalized is not None and prefs is not None:
        total_norm = len(normalized)
        expected_ranked_rows = _compute_expected_ranked(normalized, prefs) or []
        q2_count = len(expected_ranked_rows)
        # Try to find lines indicating counts
        found_total = False
        found_q2 = False
        for line in diag_text.splitlines():
            l = line.lower()
            if ("total" in l and "normalized" in l and "event" in l):
                nums = re.findall(r"\d+", line)
                if any(int(n) == total_norm for n in nums):
                    found_total = True
            if ("q2" in l or "time_window" in l) and ("count" in l or "events" in l):
                nums = re.findall(r"\d+", line)
                if any(int(n) == q2_count for n in nums):
                    found_q2 = True
        if found_total and found_q2:
            scores["diagnostics_counts_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()