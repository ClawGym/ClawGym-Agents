import json
import sys
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_config_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the specific config.yaml structure provided.
    Supports:
      - simple scalar keys: output_base_dir, tone, max_words, schedule_time
      - list under 'checklist'
      - bracket list under 'summary_sections'
    """
    text = _read_text(path)
    if text is None:
        return None
    cfg: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if re.match(r"^\s*checklist:\s*$", line):
            i += 1
            items: List[str] = []
            while i < n:
                l2 = lines[i]
                if re.match(r"^\s{2}-\s", l2):
                    items.append(re.sub(r"^\s{2}-\s", "", l2).rstrip())
                    i += 1
                else:
                    break
            cfg["checklist"] = items
            continue
        m = re.match(r"^\s*([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            # Strip quotes if quoted
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            if key == "max_words":
                try:
                    cfg[key] = int(val)
                except Exception:
                    return None
            elif key == "summary_sections":
                # expect format like: ["date", "checklist", "schedule", "conflicts"]
                sec = []
                if val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if inner:
                        parts = [p.strip() for p in inner.split(",")]
                        for p in parts:
                            if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                                sec.append(p[1:-1])
                            else:
                                sec.append(p)
                cfg[key] = sec
            else:
                cfg[key] = val
        i += 1
    # Basic presence checks
    required_keys = ["output_base_dir", "tone", "max_words", "schedule_time", "checklist", "summary_sections"]
    for k in required_keys:
        if k not in cfg:
            return None
    return cfg


def _time_to_minutes(t: str) -> Optional[int]:
    m = re.match(r"^(\d{2}):(\d{2})$", t)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    return h * 60 + mi


def _detect_conflicts(entries: List[Dict[str, str]], target_date: str) -> List[Tuple[str, str, str, str]]:
    """
    Returns list of conflicts as tuples: (activity_id_1, activity_id_2, range1, range2)
    With ids sorted lexicographically in each tuple to keep determinism.
    range format uses en-dash: HH:MM–HH:MM
    """
    on_date = [e for e in entries if e.get("date") == target_date]
    conflicts: List[Tuple[str, str, str, str]] = []
    for i in range(len(on_date)):
        for j in range(i + 1, len(on_date)):
            e1 = on_date[i]
            e2 = on_date[j]
            s1 = _time_to_minutes(e1["start_time"])
            e1t = _time_to_minutes(e1["end_time"])
            s2 = _time_to_minutes(e2["start_time"])
            e2t = _time_to_minutes(e2["end_time"])
            if None in (s1, e1t, s2, e2t):
                continue
            if s1 < e2t and s2 < e1t:
                id1, id2 = e1["activity_id"], e2["activity_id"]
                range1 = f'{e1["start_time"]}\u2013{e1["end_time"]}'
                range2 = f'{e2["start_time"]}\u2013{e2["end_time"]}'
                if id1 <= id2:
                    conflicts.append((id1, id2, range1, range2))
                else:
                    conflicts.append((id2, id1, range2, range1))
    # Deduplicate if any (shouldn't be duplicates with above iteration)
    seen = set()
    uniq = []
    for c in conflicts:
        key = (c[0], c[1])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def _parse_summary_sections(text: str) -> Optional[Dict[str, Any]]:
    """
    Parses summary markdown into sections by headers starting lines with:
    'Date:', 'Checklist:', 'Schedule:', 'Conflicts:'.
    Returns dict with keys: order (list of headers seen in order),
    and content mapping header -> list of lines (content lines).
    """
    lines = text.splitlines()
    headers = ["Date:", "Checklist:", "Schedule:", "Conflicts:"]
    indices = []
    for idx, line in enumerate(lines):
        for h in headers:
            if line.strip().startswith(h):
                indices.append((idx, h))
                break
    if not indices:
        return None
    # Ensure unique and in order as they appear
    # Build mapping
    order = [h for _, h in indices]
    content: Dict[str, List[str]] = {}
    for k in headers:
        content[k] = []
    for idx, (start_idx, h) in enumerate(indices):
        end_idx = indices[idx + 1][0] if idx + 1 < len(indices) else len(lines)
        # Content lines are after the header line up to end_idx
        section_lines = lines[start_idx:end_idx]
        # Keep entire header line and content for checking
        content[h] = section_lines
    return {"order": order, "content": content}


def _split_words(text: str) -> List[str]:
    # Split on any whitespace, keep punctuation attached as part of word
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _first_n_words(text: str, n: int) -> str:
    words = _split_words(text)
    return " ".join(words[:n])


def _load_expected(schedule_rows: List[Dict[str, str]], target_date: str) -> Dict[str, Dict[str, str]]:
    """
    Build mapping activity_id -> dict with keys:
      start_time, end_time, child, activity, location, notes, range
    for the target date only.
    """
    expected: Dict[str, Dict[str, str]] = {}
    for r in schedule_rows:
        if r.get("date") != target_date:
            continue
        aid = r.get("activity_id", "")
        expected[aid] = {
            "start_time": r.get("start_time", ""),
            "end_time": r.get("end_time", ""),
            "child": r.get("child", ""),
            "activity": r.get("activity", ""),
            "location": r.get("location", ""),
            "notes": r.get("notes", ""),
            "range": f'{r.get("start_time","")}\u2013{r.get("end_time","")}',
        }
    return expected


def _cron_time_match(line: str, expected_time: str) -> bool:
    """
    Validate cron line matches expected_time "HH:MM" and calls scripts/generate_daily_outputs $(date +%F)
    Accepts 1 or 2 digit hour/minute fields. Ensures * * * for dom, mon, dow.
    """
    # Normalize spaces
    l = re.sub(r"\s+", " ", line.strip())
    parts = l.split(" ")
    if len(parts) < 6:
        return False
    # Extract time fields
    try:
        minute_str = parts[0]
        hour_str = parts[1]
        dom = parts[2]
        mon = parts[3]
        dow = parts[4]
    except Exception:
        return False
    if dom != "*" or mon != "*" or dow != "*":
        return False
    # Compare times by integer equality
    mexp, hexp = expected_time.split(":")
    try:
        if int(minute_str) != int(mexp) or int(hour_str) != int(hexp):
            return False
    except Exception:
        return False
    # Command and args
    cmd = " ".join(parts[5:])
    # Allow /bin/date or date
    pattern = r"^scripts/generate_daily_outputs\s+\$\((?:/bin/)?date \+\%F\)$"
    if re.match(pattern, cmd) is None:
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_present_executable": 0.0,
        "summary_file_exists": 0.0,
        "summary_sections_order_and_date": 0.0,
        "checklist_items_match": 0.0,
        "schedule_entries_complete_and_count": 0.0,
        "conflicts_section_correct": 0.0,
        "revised_messages_file_exists_and_structure": 0.0,
        "revised_messages_count_and_ids": 0.0,
        "revised_messages_excerpts_tone_wordcount": 0.0,
        "revised_messages_reference_schedule": 0.0,
        "cron_line_valid": 0.0,
        "run_log_counts_and_command": 0.0,
    }

    target_date = "2026-04-16"

    # Load inputs
    schedule_path = workspace / "input" / "kids_schedule.csv"
    messages_path = workspace / "input" / "message_drafts.json"
    config_path = workspace / "input" / "config.yaml"

    schedule_rows = _read_csv_dicts(schedule_path) or []
    config = _parse_config_yaml(config_path)
    messages = _read_json(messages_path)

    expected_map = _load_expected(schedule_rows, target_date)
    expected_ids = sorted(expected_map.keys())
    expected_conflicts = _detect_conflicts(schedule_rows, target_date)

    # 1) Script presence and executable
    script_path = workspace / "scripts" / "generate_daily_outputs"
    try:
        if script_path.is_file():
            # Check executable (best effort); if not executable but exists, still partial? Requirement says invokable from shell.
            # We'll require executable bit for full credit on this check.
            import os
            if os.access(str(script_path), os.X_OK):
                scores["script_present_executable"] = 1.0
            else:
                scores["script_present_executable"] = 0.0
    except Exception:
        pass

    # 2) Daily summary report checks
    summary_path = workspace / "outputs" / "daily" / f"summary_{target_date}.md"
    summary_text = _read_text(summary_path)
    if summary_text is not None:
        scores["summary_file_exists"] = 1.0
        summary_parsed = _parse_summary_sections(summary_text)
        if summary_parsed is not None and config is not None:
            order = summary_parsed["order"]
            content = summary_parsed["content"]
            # Check order must be Date, Checklist, Schedule, Conflicts in that order
            expected_order = ["Date:", "Checklist:", "Schedule:", "Conflicts:"]
            # Extract unique order preserving first occurrence
            # Ensure expected sequence occurs in this exact order
            def _indices_of(seq, headers):
                idxs = []
                for h in headers:
                    try:
                        idxs.append(seq.index(h))
                    except ValueError:
                        return None
                return idxs

            idxs = _indices_of(order, expected_order)
            order_ok = idxs is not None and idxs == sorted(idxs)
            # Also ensure the Date line contains the target date
            date_lines = content.get("Date:", [])
            date_ok = any(target_date in ln for ln in date_lines)
            if order_ok and date_ok:
                scores["summary_sections_order_and_date"] = 1.0

            # Checklist match
            checklist_expected = config.get("checklist", []) if config else []
            checklist_lines = content.get("Checklist:", [])[1:]  # skip header line itself
            # Normalize checklist lines: strip bullets and whitespace, keep non-empty
            normalized_items: List[str] = []
            for ln in checklist_lines:
                s = ln.strip()
                s = re.sub(r"^[\-\*\u2022]\s*", "", s)  # remove -, *, • bullets
                if s:
                    normalized_items.append(s)
            if normalized_items == checklist_expected:
                scores["checklist_items_match"] = 1.0

            # Schedule entries
            schedule_lines = content.get("Schedule:", [])[1:]  # skip header
            # Remove empty lines
            schedule_lines = [ln for ln in schedule_lines if ln.strip()]
            # Count must match number of expected activities on target date
            count_ok = len(schedule_lines) == len(expected_ids)
            # For each expected activity, there must be a line that includes all required fields
            all_found = True
            for aid in expected_ids:
                exp = expected_map[aid]
                tokens = [
                    aid,
                    exp["range"],  # en-dash range
                    exp["child"],
                    exp["activity"],
                    exp["location"],
                    exp["notes"],
                ]
                found_line = False
                for ln in schedule_lines:
                    if all(tok in ln for tok in tokens):
                        found_line = True
                        break
                if not found_line:
                    all_found = False
                    break
            if count_ok and all_found:
                scores["schedule_entries_complete_and_count"] = 1.0

            # Conflicts section
            conflicts_lines = content.get("Conflicts:", [])[1:]  # skip header
            conflicts_text = "\n".join(conflicts_lines).strip()
            if expected_conflicts:
                # Must not say None; must include both activity_ids and their time ranges
                if conflicts_text and "None" not in conflicts_text and "none" not in conflicts_text.lower():
                    # For each expected conflict, check presence
                    conflict_ok = True
                    for (id1, id2, range1, range2) in expected_conflicts:
                        # Look for a line that contains both ids and both ranges
                        found = False
                        for ln in conflicts_lines:
                            if (id1 in ln and id2 in ln and range1 in ln and range2 in ln):
                                found = True
                                break
                        # As a fallback, allow spread across lines: ensure all tokens present in the whole section
                        if not found:
                            if all(tok in conflicts_text for tok in [id1, id2, range1, range2]):
                                found = True
                        if not found:
                            conflict_ok = False
                            break
                    if conflict_ok:
                        scores["conflicts_section_correct"] = 1.0
            else:
                # No conflicts expected; section should contain "None"
                none_ok = any("None" == ln.strip() or ln.strip().lower() == "none" for ln in conflicts_lines if ln.strip())
                if none_ok:
                    scores["conflicts_section_correct"] = 1.0

    # 3) Revised messages JSON checks
    revised_path = workspace / "outputs" / "messages" / f"revised_messages_{target_date}.json"
    revised = _read_json(revised_path)
    # Determine messages that reference the target date via related activity ids
    # Criterion: any related_activity_id is in the set of activities on target_date
    target_ids_set = set(expected_ids)
    expected_message_ids: List[str] = []
    if isinstance(messages, list):
        for m in messages:
            if not isinstance(m, dict):
                continue
            rel_ids = m.get("related_activity_ids", [])
            if isinstance(rel_ids, list) and any(rid in target_ids_set for rid in rel_ids):
                expected_message_ids.append(m.get("message_id", ""))
    expected_message_ids = [mid for mid in expected_message_ids if mid]
    expected_message_ids_sorted = sorted(expected_message_ids)

    if isinstance(revised, list):
        scores["revised_messages_file_exists_and_structure"] = 1.0
        # Count and IDs
        # Build mapping message_id -> object
        id_list = []
        id_to_obj = {}
        for obj in revised:
            if isinstance(obj, dict) and "message_id" in obj:
                mid = obj.get("message_id")
                id_list.append(mid)
                id_to_obj[mid] = obj
        if sorted(id_list) == expected_message_ids_sorted and len(revised) == len(expected_message_ids_sorted):
            scores["revised_messages_count_and_ids"] = 1.0

        # Validate excerpts, tone, wordcount
        excerpts_ok = True
        tone_word_ok = True
        refs_ok = True
        tone_expected = config.get("tone") if config else None
        max_words = config.get("max_words") if config else None

        # Build helper map from original messages for verification
        orig_by_id: Dict[str, Dict[str, Any]] = {}
        if isinstance(messages, list):
            for m in messages:
                if isinstance(m, dict) and "message_id" in m:
                    orig_by_id[m["message_id"]] = m

        for mid in expected_message_ids_sorted:
            obj = id_to_obj.get(mid)
            orig = orig_by_id.get(mid)
            if obj is None or orig is None:
                excerpts_ok = False
                tone_word_ok = False
                refs_ok = False
                continue
            # Fields presence
            required_fields = [
                "message_id",
                "recipient",
                "subject",
                "child",
                "related_activity_ids",
                "original_body_excerpt",
                "revised_body",
                "tone_applied",
                "word_count",
            ]
            if any(f not in obj for f in required_fields):
                excerpts_ok = False
                tone_word_ok = False
                refs_ok = False
                continue
            # Check structural fields match originals
            for k in ["recipient", "subject", "child", "related_activity_ids"]:
                if obj.get(k) != orig.get(k):
                    excerpts_ok = False
            # original_body_excerpt
            draft_body = orig.get("draft_body", "")
            expected_excerpt = _first_n_words(draft_body, 30)
            if obj.get("original_body_excerpt") != expected_excerpt:
                excerpts_ok = False
            # tone_applied equals config tone
            if tone_expected is None or obj.get("tone_applied") != tone_expected:
                tone_word_ok = False
            # word_count equals number of words in revised_body and <= max_words
            revised_body = obj.get("revised_body", "")
            wc_calc = len(_split_words(revised_body))
            wc_reported = obj.get("word_count")
            if not isinstance(wc_reported, int) or wc_reported != wc_calc:
                tone_word_ok = False
            if max_words is None or wc_calc > max_words:
                tone_word_ok = False
            # reference schedule items by time and activity name for related_activity_ids
            rel_ids = obj.get("related_activity_ids", [])
            if not isinstance(rel_ids, list):
                refs_ok = False
            else:
                # For each related id, ensure activity name appears and at least one of the times appears in revised_body
                rb_lower = revised_body.lower()
                ok_for_all = True
                for rid in rel_ids:
                    exp = expected_map.get(rid)
                    if not exp:
                        ok_for_all = False
                        break
                    activity_name = exp["activity"]
                    # time tokens to search
                    start_t = exp["start_time"]
                    end_t = exp["end_time"]
                    range_dash = f'{start_t}\u2013{end_t}'
                    range_hyphen = f'{start_t}-{end_t}'
                    # Check activity name present (case-insensitive)
                    if activity_name.lower() not in rb_lower:
                        ok_for_all = False
                        break
                    # Check presence of time: either start or end or a range with dash or hyphen
                    time_present = (
                        start_t in revised_body
                        or end_t in revised_body
                        or range_dash in revised_body
                        or range_hyphen in revised_body
                    )
                    if not time_present:
                        ok_for_all = False
                        break
                if not ok_for_all:
                    refs_ok = False

        if excerpts_ok and tone_word_ok:
            scores["revised_messages_excerpts_tone_wordcount"] = 1.0
        if refs_ok:
            scores["revised_messages_reference_schedule"] = 1.0

    # 4) Scheduler snippet check
    cron_path = workspace / "outputs" / "schedule" / "cron_example.txt"
    cron_text = _read_text(cron_path)
    if cron_text is not None and config is not None:
        # Must be a single cron line (allow trailing newline)
        cron_lines = [ln for ln in cron_text.splitlines() if ln.strip() != ""]
        if len(cron_lines) == 1 and _cron_time_match(cron_lines[0], config.get("schedule_time", "")):
            scores["cron_line_valid"] = 1.0

    # 5) Run log checks
    run_log_path = workspace / "outputs" / "logs" / f"run_{target_date}.txt"
    run_text = _read_text(run_log_path)
    if run_text is not None:
        lines = [ln.strip() for ln in run_text.splitlines() if ln.strip() != ""]
        expected_lines_count = 4
        if len(lines) == expected_lines_count:
            parsed: Dict[str, str] = {}
            ok_parse = True
            for ln in lines:
                if ":" not in ln:
                    ok_parse = False
                    break
                key, val = ln.split(":", 1)
                parsed[key.strip()] = val.strip()
            if ok_parse:
                # Compute expected numbers
                activities_count = len(expected_ids)
                # messages revised count
                messages_count = len(expected_message_ids_sorted)
                conflicts_count = len(expected_conflicts)
                # Validate
                try:
                    act_ok = int(parsed.get("activities_in_summary", "-1")) == activities_count
                    msg_ok = int(parsed.get("messages_revised", "-1")) == messages_count
                    conf_ok = int(parsed.get("conflicts_detected", "-1")) == conflicts_count
                    cmd_ok = parsed.get("command_run") == f"scripts/generate_daily_outputs {target_date}"
                    if act_ok and msg_ok and conf_ok and cmd_ok:
                        scores["run_log_counts_and_command"] = 1.0
                except Exception:
                    pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()