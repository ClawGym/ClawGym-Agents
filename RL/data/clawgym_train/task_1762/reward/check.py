import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                return None
            items.append(obj)
        return items
    except Exception:
        return None


def _parse_simple_yaml_kv(path: Path) -> Optional[Dict[str, str]]:
    """
    Minimal YAML parser for simple key: value pairs per line.
    """
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # remove possible quotes
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data


def _parse_date_str(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _identity_trio(item: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    try:
        task = item["task"]
        owner = item["owner"]
        due = item["due"]
        if not isinstance(task, str) or not isinstance(owner, str) or not isinstance(due, str):
            return None
        # Validate date format
        if _parse_date_str(due) is None:
            return None
        return (task, owner, due)
    except Exception:
        return None


def _normalize_completed(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    return None


def _compare_jsonl_expected_vs_extracted(expected: List[Dict[str, Any]], extracted: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Compute counts:
    - matched: identities present in both (by trio of (task, owner, due))
    - missing: in expected but not in extracted
    - unexpected: in extracted but not in expected
    - field_mismatches: among matched identities, number of items with differing 'completed'
    """
    exp_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for e in expected:
        key = _identity_trio(e)
        if key is None:
            # malformed expected entry, treat as unmatchable
            continue
        exp_map[key] = e
    ext_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for e in extracted:
        key = _identity_trio(e)
        if key is None:
            continue
        ext_map[key] = e

    matched = 0
    missing = 0
    unexpected = 0
    mismatches = 0

    for key, e in exp_map.items():
        if key in ext_map:
            matched += 1
            # compare other fields (completed specifically)
            exp_completed = _normalize_completed(e.get("completed"))
            ext_completed = _normalize_completed(ext_map[key].get("completed"))
            if exp_completed is None or ext_completed is None:
                # treat malformed as mismatch
                mismatches += 1
            else:
                if exp_completed != ext_completed:
                    mismatches += 1
        else:
            missing += 1

    for key in ext_map:
        if key not in exp_map:
            unexpected += 1

    return {
        "matched": matched,
        "missing": missing,
        "unexpected": unexpected,
        "field_mismatches": mismatches,
    }


def _load_sessions_expected(workspace: Path) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load expected JSONL per date from input/expected_action_items_YYYY-MM-DD.jsonl.
    """
    expected: Dict[str, List[Dict[str, Any]]] = {}
    for p in sorted((workspace / "input").glob("expected_action_items_*.jsonl")):
        m = re.match(r"expected_action_items_(\d{4}-\d{2}-\d{2})\.jsonl$", p.name)
        if not m:
            continue
        date_str = m.group(1)
        items = _load_jsonl(p)
        if items is None:
            continue
        expected[date_str] = items
    return expected


def _load_sessions_extracted(workspace: Path) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load extracted JSONL per date from output/extracted/session_YYYY-MM-DD.jsonl.
    """
    extracted: Dict[str, List[Dict[str, Any]]] = {}
    out_dir = workspace / "output" / "extracted"
    if not out_dir.exists():
        return extracted
    for p in sorted(out_dir.glob("session_*.jsonl")):
        m = re.match(r"session_(\d{4}-\d{2}-\d{2})\.jsonl$", p.name)
        if not m:
            continue
        date_str = m.group(1)
        items = _load_jsonl(p)
        if items is None:
            continue
        extracted[date_str] = items
    return extracted


def _compute_expected_stats_from_expected_items(expected_sessions: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Deduplicate across sessions by task text; keep most recent by session date.
    """
    # Collect (session_date, item)
    entries: List[Tuple[date, Dict[str, Any]]] = []
    for date_str, items in expected_sessions.items():
        d = _parse_date_str(date_str)
        if d is None:
            continue
        for item in items:
            entries.append((d, item))
    # Dedup by task
    latest_by_task: Dict[str, Tuple[date, Dict[str, Any]]] = {}
    for d, item in entries:
        task = item.get("task")
        if not isinstance(task, str):
            continue
        if task not in latest_by_task or d >= latest_by_task[task][0]:
            latest_by_task[task] = (d, item)
    dedup_items: List[Dict[str, Any]] = [v[1] for v in latest_by_task.values()]

    # Normalize fields and compute stats
    total_items = len(dedup_items)
    completed_items = 0
    open_items_list: List[Dict[str, Any]] = []
    for item in dedup_items:
        comp = _normalize_completed(item.get("completed"))
        if comp is True:
            completed_items += 1
        elif comp is False:
            open_items_list.append(item)
        else:
            # malformed, treat as open? Better: exclude from counts consistency by considering mismatch; here we treat malformed as open to avoid miscounting
            open_items_list.append(item)

    open_items = len(open_items_list)
    # items_per_owner: count only open
    items_per_owner: Dict[str, int] = {}
    for item in open_items_list:
        owner = item.get("owner")
        if isinstance(owner, str):
            items_per_owner[owner] = items_per_owner.get(owner, 0) + 1

    stats = {
        "total_items": total_items,
        "completed_items": completed_items,
        "open_items": open_items,
        "items_per_owner": items_per_owner,
        "dedup_open_items": open_items_list,  # helper for further checks
        "dedup_all_items": dedup_items,
    }
    return stats


def _load_config_dates(workspace: Path) -> Tuple[Optional[date], Optional[date]]:
    cfg = _parse_simple_yaml_kv(workspace / "input" / "config.yaml")
    if cfg is None:
        return None, None
    anchor = _parse_date_str(cfg.get("anchor_date", ""))
    next_meeting = _parse_date_str(cfg.get("next_meeting_date", ""))
    return anchor, next_meeting


def _compute_open_due_within_7_days(open_items: List[Dict[str, Any]], anchor: date) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for item in open_items:
        due_str = item.get("due")
        due = _parse_date_str(due_str) if isinstance(due_str, str) else None
        if due is None:
            continue
        if anchor <= due <= (anchor + timedelta(days=7)):
            task = item.get("task")
            owner = item.get("owner")
            if isinstance(task, str) and isinstance(owner, str):
                results.append({"task": task, "owner": owner, "due": due_str})
    return results


def _owners_with_most_open(items_per_owner: Dict[str, int]) -> List[str]:
    if not items_per_owner:
        return []
    max_count = max(items_per_owner.values())
    return sorted([k for k, v in items_per_owner.items() if v == max_count])


def _set_of_records(items: List[Dict[str, Any]]) -> set:
    s = set()
    for it in items:
        key = (it.get("task"), it.get("owner"), it.get("due"), it.get("completed"))
        s.add(key)
    return s


def _derive_expected_open_bullets(open_items: List[Dict[str, Any]]) -> List[str]:
    bullets: List[str] = []
    for item in open_items:
        task = item.get("task")
        owner = item.get("owner")
        due = item.get("due")
        if isinstance(task, str) and isinstance(owner, str) and isinstance(due, str):
            bullets.append(f"- [ ] {task} (owner: {owner}; due: {due})")
    return bullets


def _parse_validation_report(report: Any, date_str: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to extract for given date:
    - pass (bool)
    - matched (int)
    - missing (int)
    - unexpected (int)
    - field_mismatches (int)
    Accept flexible structures and key names.
    """
    entries: List[Dict[str, Any]] = []
    if isinstance(report, dict):
        # direct per-date keys
        if date_str in report and isinstance(report[date_str], dict):
            entries.append(report[date_str])
        # or nested under 'sessions' or similar
        for k in ["sessions", "dates", "results", "report"]:
            v = report.get(k)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        d = item.get("date") or item.get("session_date") or item.get("session")
                        if d == date_str:
                            entries.append(item)
        # try values scanned
        if not entries:
            # maybe values are dicts keyed by date_str as field
            for v in report.values():
                if isinstance(v, dict):
                    d = v.get("date") or v.get("session_date") or v.get("session")
                    if d == date_str:
                        entries.append(v)
    elif isinstance(report, list):
        for item in report:
            if isinstance(item, dict):
                d = item.get("date") or item.get("session_date") or item.get("session")
                if d == date_str:
                    entries.append(item)
    if not entries:
        return None
    entry = entries[0]

    def find_int(*names: str) -> Optional[int]:
        for n in names:
            if n in entry and isinstance(entry[n], int):
                return entry[n]
            if n in entry and isinstance(entry[n], list):
                return len(entry[n])
        # try case-insensitive keys
        lower_map = {k.lower(): k for k in entry.keys()}
        for n in names:
            nl = n.lower()
            if nl in lower_map:
                k = lower_map[nl]
                v = entry[k]
                if isinstance(v, int):
                    return v
                if isinstance(v, list):
                    return len(v)
        return None

    def find_pass() -> Optional[bool]:
        # check common keys
        for k in ["pass", "passed", "ok"]:
            if k in entry and isinstance(entry[k], bool):
                return entry[k]
        # status string
        for k in ["status", "result", "outcome"]:
            v = entry.get(k)
            if isinstance(v, str):
                vl = v.strip().lower()
                if vl in ("pass", "passed", "ok", "success", "true"):
                    return True
                if vl in ("fail", "failed", "error", "false"):
                    return False
        return None

    parsed = {
        "pass": find_pass(),
        "matched": find_int("matched", "matches", "matched_items"),
        "missing": find_int("missing", "missing_items"),
        "unexpected": find_int("unexpected", "unexpected_items"),
        "field_mismatches": find_int("field_mismatches", "mismatches", "mismatched_fields", "field_level_mismatches"),
    }
    return parsed


def _load_action_item_stats(path: Path) -> Optional[Dict[str, Any]]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    return data


def _compare_action_item_stats(stats_file: Path, expected_stats: Dict[str, Any], anchor: Optional[date]) -> Dict[str, float]:
    scores: Dict[str, float] = {
        "action_item_stats_counts_correct": 0.0,
        "items_per_owner_correct": 0.0,
        "open_items_due_within_7_days_correct": 0.0,
        "owners_with_most_open_items_correct": 0.0,
    }
    stats = _load_action_item_stats(stats_file)
    if stats is None:
        return scores

    # Counts check
    t_ok = isinstance(stats.get("total_items"), int) and stats.get("total_items") == expected_stats["total_items"]
    c_ok = isinstance(stats.get("completed_items"), int) and stats.get("completed_items") == expected_stats["completed_items"]
    o_ok = isinstance(stats.get("open_items"), int) and stats.get("open_items") == expected_stats["open_items"]
    if t_ok and c_ok and o_ok:
        scores["action_item_stats_counts_correct"] = 1.0

    # items_per_owner check
    ipo = stats.get("items_per_owner")
    if isinstance(ipo, dict):
        # ensure ints
        try:
            ipo_int = {str(k): int(v) for k, v in ipo.items()}
        except Exception:
            ipo_int = None
        if ipo_int is not None and ipo_int == expected_stats["items_per_owner"]:
            scores["items_per_owner_correct"] = 1.0

    # open_items_due_within_7_days check
    if anchor is not None:
        exp_within = _compute_open_due_within_7_days(expected_stats["dedup_open_items"], anchor)
        # normalize order-insensitive
        got_within = stats.get("open_items_due_within_7_days")
        def norm_list(lst):
            arr = []
            if isinstance(lst, list):
                for it in lst:
                    if isinstance(it, dict):
                        task = it.get("task"); owner = it.get("owner"); due = it.get("due")
                        if isinstance(task, str) and isinstance(owner, str) and isinstance(due, str):
                            arr.append((task, owner, due))
            return set(arr)
        if norm_list(got_within) == norm_list(exp_within):
            scores["open_items_due_within_7_days_correct"] = 1.0

    # owners_with_most_open_items
    got_owners = stats.get("owners_with_most_open_items")
    if isinstance(got_owners, list):
        got_set = set([str(x) for x in got_owners])
        exp_set = set(_owners_with_most_open(expected_stats["items_per_owner"]))
        if got_set == exp_set:
            scores["owners_with_most_open_items_correct"] = 1.0

    return scores


def _extract_bullets_from_section(lines: List[str], start_idx: int, end_idx: int) -> List[Tuple[str, str, str, str]]:
    """
    Extract bullets "- [ ] <task> (owner: <Owner>; due: <YYYY-MM-DD>)" from lines[start_idx:end_idx]
    Returns list of tuples (bullet_line, task, owner, due)
    """
    bullets: List[Tuple[str, str, str, str]] = []
    pattern = re.compile(r'^\s*-\s*\[\s\]\s*(.+?)\s*\(owner:\s*([^;()]+)\s*;\s*due:\s*(\d{4}-\d{2}-\d{2})\)\s*$')
    for i in range(start_idx, end_idx):
        line = lines[i].rstrip("\n")
        m = pattern.match(line)
        if m:
            task = m.group(1)
            owner = m.group(2)
            due = m.group(3)
            bullets.append((line.strip(), task, owner, due))
    return bullets


def _check_due_sorting_within_owner(bullets: List[Tuple[str, str, str, str]]) -> bool:
    """
    bullets: list of parsed bullets (line, task, owner, due)
    Check that for each owner, due dates appear in non-decreasing order in their appearance sequence.
    """
    per_owner_dues: Dict[str, List[date]] = {}
    for _, _, owner, due_str in bullets:
        d = _parse_date_str(due_str)
        if d is None:
            return False
        per_owner_dues.setdefault(owner, []).append(d)
    for owner, dues in per_owner_dues.items():
        if any(dues[i] > dues[i+1] for i in range(len(dues)-1)):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "extracted_2026_04_10_matches_expected": 0.0,
        "extracted_2026_04_14_matches_expected": 0.0,
        "validation_report_present": 0.0,
        "validation_report_pass_status_2026_04_10_correct": 0.0,
        "validation_report_pass_status_2026_04_14_correct": 0.0,
        "validation_report_counts_2026_04_10_correct": 0.0,
        "validation_report_counts_2026_04_14_correct": 0.0,
        "action_item_stats_counts_correct": 0.0,
        "items_per_owner_correct": 0.0,
        "open_items_due_within_7_days_correct": 0.0,
        "owners_with_most_open_items_correct": 0.0,
        "next_notes_title_date_correct": 0.0,
        "next_notes_open_items_section_correct": 0.0,
        "next_notes_follow_ups_correct": 0.0,
        "next_notes_due_sorting_within_owner_correct": 0.0,
    }

    # Load expected and extracted sessions
    expected_sessions = _load_sessions_expected(workspace)
    extracted_sessions = _load_sessions_extracted(workspace)

    # Check specific extracted files match expected
    for dt in ["2026-04-10", "2026-04-14"]:
        exp = expected_sessions.get(dt)
        ext = extracted_sessions.get(dt)
        key = f"extracted_{dt.replace('-', '_')}_matches_expected"
        if exp is None or ext is None:
            scores[key] = 0.0
        else:
            # Compare as sets of records
            try:
                exp_set = _set_of_records(exp)
                ext_set = _set_of_records(ext)
                if exp_set == ext_set:
                    scores[key] = 1.0
            except Exception:
                scores[key] = 0.0

    # Validation report checks
    validation_report_path = workspace / "output" / "validation_report.json"
    report = _load_json(validation_report_path)
    if report is not None:
        scores["validation_report_present"] = 1.0
        # Compute expected comparisons
        for dt in ["2026-04-10", "2026-04-14"]:
            exp_items = expected_sessions.get(dt)
            ext_items = extracted_sessions.get(dt)
            pass_key = f"validation_report_pass_status_{dt.replace('-', '_')}_correct"
            counts_key = f"validation_report_counts_{dt.replace('-', '_')}_correct"
            if exp_items is None or ext_items is None:
                scores[pass_key] = 0.0
                scores[counts_key] = 0.0
                continue
            counts = _compare_jsonl_expected_vs_extracted(exp_items, ext_items)
            expected_pass = (counts["missing"] == 0 and counts["unexpected"] == 0 and counts["field_mismatches"] == 0)
            entry = _parse_validation_report(report, dt)
            if entry is None:
                scores[pass_key] = 0.0
                scores[counts_key] = 0.0
            else:
                # pass status
                if entry.get("pass") is not None and entry.get("pass") == expected_pass:
                    scores[pass_key] = 1.0
                # counts
                got_matched = entry.get("matched")
                got_missing = entry.get("missing")
                got_unexpected = entry.get("unexpected")
                got_mismatches = entry.get("field_mismatches")
                if (
                    isinstance(got_matched, int) and isinstance(got_missing, int) and
                    isinstance(got_unexpected, int) and isinstance(got_mismatches, int) and
                    got_matched == counts["matched"] and
                    got_missing == counts["missing"] and
                    got_unexpected == counts["unexpected"] and
                    got_mismatches == counts["field_mismatches"]
                ):
                    scores[counts_key] = 1.0
    else:
        # leave present and other keys at 0.0
        pass

    # Compute expected stats from input expected items
    stats_expected = _compute_expected_stats_from_expected_items(expected_sessions)
    anchor_date_val, next_meeting_date_val = _load_config_dates(workspace)

    # Compare action_item_stats.json
    action_stats_path = workspace / "output" / "action_item_stats.json"
    stats_scores = _compare_action_item_stats(action_stats_path, stats_expected, anchor_date_val)
    scores.update(stats_scores)

    # next_meeting_notes.md checks
    notes_path = workspace / "output" / "next_meeting_notes.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None:
        lines = notes_text.splitlines()
        title_ok = False
        if next_meeting_date_val is not None:
            date_str = next_meeting_date_val.strftime("%Y-%m-%d")
            # Title line should include "Next Session" and the date
            for i, line in enumerate(lines[:5]):  # search in first few lines
                if "Next Session" in line and date_str in line:
                    title_ok = True
                    break
        if title_ok:
            scores["next_notes_title_date_correct"] = 1.0

        # Determine indices for sections
        # Find "Follow-ups" line index
        follow_idx = None
        for i, line in enumerate(lines):
            if "Follow-ups" in line:
                follow_idx = i
                break
        # Define pre-follow-ups region where main open items should be
        pre_start = 0
        pre_end = follow_idx if follow_idx is not None else len(lines)

        main_bullets = _extract_bullets_from_section(lines, pre_start, pre_end)
        # Expected open bullets
        expected_open_bullets = _derive_expected_open_bullets(stats_expected["dedup_open_items"])
        got_main_bullet_lines = [b[0] for b in main_bullets]
        if set(got_main_bullet_lines) == set(expected_open_bullets) and len(got_main_bullet_lines) == len(expected_open_bullets):
            scores["next_notes_open_items_section_correct"] = 1.0

        # Sorting within owner check for the main section
        if main_bullets and _check_due_sorting_within_owner(main_bullets):
            scores["next_notes_due_sorting_within_owner_correct"] = 1.0

        # Follow-ups bullets: after follow-ups line to end
        if follow_idx is not None:
            follow_bullets = _extract_bullets_from_section(lines, follow_idx + 1, len(lines))
            got_follow_lines = [b[0] for b in follow_bullets]
            # Expected follow-ups: open items with due < anchor_date
            if anchor_date_val is not None:
                expected_follow_items: List[Dict[str, Any]] = []
                for item in stats_expected["dedup_open_items"]:
                    due_str = item.get("due")
                    d = _parse_date_str(due_str) if isinstance(due_str, str) else None
                    if d is not None and d < anchor_date_val:
                        expected_follow_items.append(item)
                expected_follow_bullets = _derive_expected_open_bullets(expected_follow_items)
                if set(got_follow_lines) == set(expected_follow_bullets) and len(got_follow_lines) == len(expected_follow_bullets):
                    scores["next_notes_follow_ups_correct"] = 1.0
        else:
            # no Follow-ups section present; keep score 0.0
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()