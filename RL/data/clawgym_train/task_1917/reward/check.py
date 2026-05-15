import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple nested mappings using spaces indentation.
    Supports keys with scalar values and nested dicts. Converts integers where possible.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]

    def coerce_value(val: str) -> Any:
        v = val.strip()
        # strip surrounding quotes if present
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        # try int
        if re.fullmatch(r"-?\d+", v):
            try:
                return int(v)
            except Exception:
                return v
        # try float (not needed but safe)
        if re.fullmatch(r"-?\d+\.\d+", v):
            try:
                return float(v)
            except Exception:
                return v
        # booleans
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        return v

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        # adjust stack for current indent
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            # malformed indentation
            return None
        current = stack[-1][1]
        # parse key: value
        if ":" not in line:
            return None
        key_part, value_part = line.lstrip().split(":", 1)
        key = key_part.strip()
        value = value_part.strip()
        if value == "":
            # nested dict
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent + 2, new_dict))
        else:
            current[key] = coerce_value(value)
    return root


def parse_csv_strict(path: Path, expected_headers: List[str]) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return None
            if headers != expected_headers:
                return None
            rows: List[Dict[str, str]] = []
            for row in reader:
                if len(row) != len(expected_headers):
                    return None
                rows.append({h: v for h, v in zip(headers, row)})
            return rows
    except Exception:
        return None


def parse_csv_loose(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            dr = csv.DictReader(f)
            if dr.fieldnames is None:
                return None
            rows = [dict(r) for r in dr]
            return rows
    except Exception:
        return None


def time_to_minutes(t: str) -> Optional[int]:
    if not isinstance(t, str):
        return None
    if not re.fullmatch(r"\d{2}:\d{2}", t):
        return None
    hh = int(t[:2])
    mm = int(t[3:])
    if hh < 0 or hh >= 24 or mm < 0 or mm >= 60:
        return None
    return hh * 60 + mm


def intervals_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    # [start, end) style intervals
    return not (a_end <= b_start or b_end <= a_start)


def violates_quiet_hours(start_min: int, end_min: int, quiet_start: int, quiet_end: int) -> bool:
    """
    Return True if interval [start_min, end_min) intersects quiet hours.
    Quiet hours may wrap over midnight: if quiet_start > quiet_end.
    """
    if quiet_start < 0 or quiet_end < 0:
        return True
    if quiet_start < quiet_end:
        # simple interval
        return intervals_overlap(start_min, end_min, quiet_start, quiet_end)
    else:
        # wraps over midnight: [quiet_start, 24h) U [0, quiet_end)
        return intervals_overlap(start_min, end_min, quiet_start, 24 * 60) or intervals_overlap(start_min, end_min, 0, quiet_end)


def compute_deep_work_counts(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts = {d: 0 for d in DAYS}
    for r in rows:
        day = r.get("day", "")
        if day in counts and r.get("category", "") == "Deep Work (Dissertation)":
            counts[day] += 1
    return counts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "final_md_exists_and_rewritten": 0.0,
        "final_md_includes_fixed_commitments_descriptions": 0.0,
        "final_md_mentions_quiet_hours_or_bounds": 0.0,
        "final_md_mentions_adjustments": 0.0,
        "csv_structure_correct": 0.0,
        "csv_includes_fixed_commitments": 0.0,
        "csv_days_valid": 0.0,
        "csv_times_valid": 0.0,
        "csv_categories_allowed": 0.0,
        "csv_no_overlaps": 0.0,
        "csv_respects_day_bounds": 0.0,
        "csv_respects_quiet_hours": 0.0,
        "csv_min_block_length": 0.0,
        "csv_deep_work_blocks_within_limit": 0.0,
        "validation_json_fields_and_types": 0.0,
        "validation_json_consistent": 0.0,
        "validation_json_valid_true": 0.0,
        "advisor_notes_sections_present": 0.0,
        "advisor_notes_actions_per_milestone": 0.0,
        "advisor_notes_references_schedule": 0.0,
    }

    # Load inputs
    fixed_commitments_path = workspace / "input" / "fixed_commitments.csv"
    calendar_config_path = workspace / "config" / "calendar_config.json"
    productivity_yaml_path = workspace / "config" / "productivity.yaml"
    milestones_json_path = workspace / "input" / "milestones.json"
    draft_md_path = workspace / "input" / "weekly_routine_draft.md"
    advisor_outline_path = workspace / "docs" / "advisor_meeting_outline.md"

    fixed_rows = None
    if fixed_commitments_path.exists():
        fixed_rows = parse_csv_loose(fixed_commitments_path)

    config = load_json(calendar_config_path)
    prod = parse_simple_yaml(productivity_yaml_path)
    milestones = load_json(milestones_json_path)
    draft_text = read_text(draft_md_path)
    outline_text = read_text(advisor_outline_path)

    # Extract config values (guard for missing)
    allowed_categories = set()
    quiet_start_min = quiet_end_min = -1
    day_bounds_start_min = day_bounds_end_min = -1
    if isinstance(config, dict):
        ac = config.get("allowed_categories")
        if isinstance(ac, list):
            allowed_categories = set(map(str, ac))
        qh = config.get("quiet_hours", {})
        if isinstance(qh, dict):
            quiet_start_min = time_to_minutes(qh.get("start", "")) or -1
            quiet_end_min = time_to_minutes(qh.get("end", "")) or -1
        db = config.get("day_bounds", {})
        if isinstance(db, dict):
            day_bounds_start_min = time_to_minutes(db.get("start", "")) or -1
            day_bounds_end_min = time_to_minutes(db.get("end", "")) or -1

    max_deep_work_per_day = None
    min_block_minutes = None
    if isinstance(prod, dict):
        constraints = prod.get("constraints", {})
        if isinstance(constraints, dict):
            max_deep_work_per_day = constraints.get("max_deep_work_blocks_per_day")
            min_block_minutes = constraints.get("min_block_minutes")

    # Load outputs
    final_md_path = workspace / "output" / "weekly_routine_final.md"
    schedule_csv_path = workspace / "output" / "weekly_routine.csv"
    validation_json_path = workspace / "output" / "schedule_validation.json"
    advisor_notes_path = workspace / "output" / "advisor_meeting_notes.md"

    final_md_text = read_text(final_md_path)
    advisor_notes_text = read_text(advisor_notes_path)

    # Check final md exists and rewritten
    if final_md_text is not None and draft_text is not None:
        if final_md_text.strip() and final_md_text.strip() != draft_text.strip():
            scores["final_md_exists_and_rewritten"] = 1.0

    # Check final md mentions all fixed commitment descriptions
    if final_md_text is not None and isinstance(fixed_rows, list):
        ok = True
        for r in fixed_rows:
            desc = (r.get("description") or "").strip()
            if not desc or (desc not in final_md_text):
                ok = False
                break
        scores["final_md_includes_fixed_commitments_descriptions"] = 1.0 if ok and len(fixed_rows) > 0 else 0.0

    # Check final md mentions quiet hours or bounds explicitly
    if final_md_text is not None:
        mentions_times = False
        if quiet_start_min >= 0 and quiet_end_min >= 0:
            # reconstruct HH:MM strings from config for matching
            def min_to_str(mn: int) -> str:
                return f"{mn // 60:02d}:{mn % 60:02d}"
            qs = min_to_str(quiet_start_min)
            qe = min_to_str(quiet_end_min)
            if qs in final_md_text or qe in final_md_text:
                mentions_times = True
        mentions_phrase = re.search(r"quiet hours", final_md_text, re.IGNORECASE) is not None
        mentions_bounds_phrase = re.search(r"day bounds", final_md_text, re.IGNORECASE) is not None
        if mentions_times or mentions_phrase or mentions_bounds_phrase:
            scores["final_md_mentions_quiet_hours_or_bounds"] = 1.0

    # Check final md mentions adjustments
    if final_md_text is not None:
        if re.search(r"adjust", final_md_text, re.IGNORECASE) or re.search(r"overlap", final_md_text, re.IGNORECASE) or re.search(r"normalize", final_md_text, re.IGNORECASE):
            scores["final_md_mentions_adjustments"] = 1.0

    # Parse schedule CSV strictly
    schedule_rows = None
    if schedule_csv_path.exists():
        schedule_rows = parse_csv_strict(schedule_csv_path, ["day", "start", "end", "category", "description"])

    # CSV structure check
    if isinstance(schedule_rows, list):
        scores["csv_structure_correct"] = 1.0

    # CSV includes fixed commitments exactly
    if isinstance(schedule_rows, list) and isinstance(fixed_rows, list):
        # Build set of tuples for matching
        schedule_tuple_set = set()
        for r in schedule_rows:
            schedule_tuple_set.add((r.get("day", ""), r.get("start", ""), r.get("end", ""), r.get("category", ""), r.get("description", "")))
        all_present = True
        for fr in fixed_rows:
            tup = (fr.get("day", ""), fr.get("start", ""), fr.get("end", ""), fr.get("category", ""), fr.get("description", ""))
            if tup not in schedule_tuple_set:
                all_present = False
                break
        if all_present and len(fixed_rows) > 0:
            scores["csv_includes_fixed_commitments"] = 1.0

    # CSV days valid, times valid, categories allowed, overlaps, bounds, quiet hours, min block length, deep work blocks limit
    days_valid = True
    times_valid = True
    categories_valid = True
    no_overlaps = True
    respects_day_bounds = True
    respects_quiet_hours = True
    min_block_ok = True
    deep_work_limit_ok = True

    deep_work_counts = {d: 0 for d in DAYS}
    day_to_intervals: Dict[str, List[Tuple[int, int, Dict[str, str]]]] = {d: [] for d in DAYS}

    if isinstance(schedule_rows, list):
        for r in schedule_rows:
            day = r.get("day", "")
            start = r.get("start", "")
            end = r.get("end", "")
            cat = r.get("category", "")
            if day not in DAYS:
                days_valid = False
            sm = time_to_minutes(start)
            em = time_to_minutes(end)
            if sm is None or em is None or sm >= em:
                times_valid = False
            if allowed_categories and cat not in allowed_categories:
                categories_valid = False
            if day in day_to_intervals and sm is not None and em is not None:
                day_to_intervals[day].append((sm, em, r))
            if cat == "Deep Work (Dissertation)" and day in deep_work_counts:
                deep_work_counts[day] += 1

        # Overlaps and bounds/quiet checks
        for d in DAYS:
            intervals = sorted(day_to_intervals.get(d, []), key=lambda x: x[0])
            # overlaps
            for i in range(1, len(intervals)):
                prev = intervals[i - 1]
                curr = intervals[i]
                if intervals_overlap(prev[0], prev[1], curr[0], curr[1]):
                    no_overlaps = False
                    break
            # bounds and quiet hours
            for sm, em, _ in intervals:
                # day bounds
                if day_bounds_start_min >= 0 and day_bounds_end_min >= 0:
                    if not (sm >= day_bounds_start_min and em <= day_bounds_end_min):
                        respects_day_bounds = False
                else:
                    # if bounds missing from config, fail this check deterministically
                    respects_day_bounds = False
                # quiet hours
                if quiet_start_min >= 0 and quiet_end_min >= 0:
                    if violates_quiet_hours(sm, em, quiet_start_min, quiet_end_min):
                        respects_quiet_hours = False
                else:
                    respects_quiet_hours = False
                # min block length
                if isinstance(min_block_minutes, int):
                    if (em - sm) < min_block_minutes:
                        min_block_ok = False
                else:
                    min_block_ok = False

        # deep work per day limit
        if isinstance(max_deep_work_per_day, int):
            for d in DAYS:
                if deep_work_counts[d] > max_deep_work_per_day:
                    deep_work_limit_ok = False
                    break
        else:
            deep_work_limit_ok = False

    # Set CSV-related scores
    if isinstance(schedule_rows, list):
        scores["csv_days_valid"] = 1.0 if days_valid else 0.0
        scores["csv_times_valid"] = 1.0 if times_valid else 0.0
        scores["csv_categories_allowed"] = 1.0 if categories_valid else 0.0
        scores["csv_no_overlaps"] = 1.0 if no_overlaps else 0.0
        scores["csv_respects_day_bounds"] = 1.0 if respects_day_bounds else 0.0
        scores["csv_respects_quiet_hours"] = 1.0 if respects_quiet_hours else 0.0
        scores["csv_min_block_length"] = 1.0 if min_block_ok else 0.0
        scores["csv_deep_work_blocks_within_limit"] = 1.0 if deep_work_limit_ok else 0.0

    # Validation JSON checks
    validation_data = load_json(validation_json_path) if validation_json_path.exists() else None
    required_validation_keys = [
        "allowed_categories_check",
        "quiet_hours_check",
        "overlaps_check",
        "included_fixed_commitments",
        "min_block_length_check",
        "deep_work_blocks_per_day",
        "valid",
        "summary",
    ]
    fields_and_types_ok = False
    consistent = False
    valid_true_ok = False

    if isinstance(validation_data, dict):
        # Fields and types
        has_all_fields = all(k in validation_data for k in required_validation_keys)
        types_ok = (
            isinstance(validation_data.get("allowed_categories_check"), bool) and
            isinstance(validation_data.get("quiet_hours_check"), bool) and
            isinstance(validation_data.get("overlaps_check"), bool) and
            isinstance(validation_data.get("included_fixed_commitments"), bool) and
            isinstance(validation_data.get("min_block_length_check"), bool) and
            isinstance(validation_data.get("deep_work_blocks_per_day"), dict) and
            isinstance(validation_data.get("valid"), bool) and
            isinstance(validation_data.get("summary"), str) and
            len(validation_data.get("summary")) >= 0
        )
        fields_and_types_ok = has_all_fields and types_ok

        # Recompute values for consistency
        if isinstance(schedule_rows, list) and isinstance(fixed_rows, list):
            recomputed = {
                "allowed_categories_check": categories_valid,
                "quiet_hours_check": respects_quiet_hours,
                "overlaps_check": no_overlaps,
                "included_fixed_commitments": scores["csv_includes_fixed_commitments"] == 1.0,
                "min_block_length_check": min_block_ok,
                "deep_work_blocks_per_day": {d: deep_work_counts.get(d, 0) for d in DAYS},
            }
            # Compare booleans
            booleans_match = (
                validation_data.get("allowed_categories_check") == recomputed["allowed_categories_check"] and
                validation_data.get("quiet_hours_check") == recomputed["quiet_hours_check"] and
                validation_data.get("overlaps_check") == recomputed["overlaps_check"] and
                validation_data.get("included_fixed_commitments") == recomputed["included_fixed_commitments"] and
                validation_data.get("min_block_length_check") == recomputed["min_block_length_check"]
            )
            # Compare deep work mapping equality on DAYS
            v_dw = validation_data.get("deep_work_blocks_per_day")
            mapping_match = isinstance(v_dw, dict) and \
                {d: int(v_dw.get(d, 0)) for d in DAYS} == recomputed["deep_work_blocks_per_day"]
            consistent = booleans_match and mapping_match

            # valid must be true only if all checks pass
            all_checks_pass = all([
                recomputed["allowed_categories_check"],
                recomputed["quiet_hours_check"],
                recomputed["overlaps_check"],
                recomputed["included_fixed_commitments"],
                recomputed["min_block_length_check"],
            ])
            # Additionally ensure csv structural checks that affect validity are true
            all_checks_pass = all_checks_pass and all([
                scores["csv_structure_correct"] == 1.0,
                scores["csv_days_valid"] == 1.0,
                scores["csv_times_valid"] == 1.0,
                scores["csv_respects_day_bounds"] == 1.0,
                scores["csv_deep_work_blocks_within_limit"] == 1.0,
            ])
            valid_true_ok = validation_data.get("valid") is True and all_checks_pass
        else:
            consistent = False
            valid_true_ok = False

    scores["validation_json_fields_and_types"] = 1.0 if fields_and_types_ok else 0.0
    scores["validation_json_consistent"] = 1.0 if consistent else 0.0
    scores["validation_json_valid_true"] = 1.0 if valid_true_ok else 0.0

    # Advisor notes checks
    # Sections present: Context, Proposed weekly routine summary, Key decisions to discuss, Questions, Action items
    sections_ok = False
    if advisor_notes_text is not None:
        text_lower = advisor_notes_text.lower()
        has_context = "context" in text_lower
        has_proposed_summary = ("proposed" in text_lower and "summary" in text_lower) or "proposed weekly routine summary" in text_lower
        has_key_decisions = "key decisions" in text_lower
        has_questions = "questions" in text_lower
        has_action_items = "action items" in text_lower
        sections_ok = all([has_context, has_proposed_summary, has_key_decisions, has_questions, has_action_items])
    scores["advisor_notes_sections_present"] = 1.0 if sections_ok else 0.0

    # Advisor notes actions per milestone with owner and due day aligned
    actions_ok = False
    if advisor_notes_text is not None and isinstance(milestones, dict):
        ms = milestones.get("milestones", [])
        if isinstance(ms, list) and len(ms) > 0:
            lines = advisor_notes_text.splitlines()
            per_milestone_ok = []
            for m in ms:
                title = (m.get("title") or "").strip()
                target_dow = (m.get("target_day_of_week") or "").strip()
                found = False
                for idx, line in enumerate(lines):
                    if title and title in line:
                        # search window around this line for Owner and Due
                        window = lines[max(0, idx - 3): min(len(lines), idx + 4)]
                        owner_ok = any(re.search(r"\bowner\s*:\s*(me|advisor)\b", w, re.IGNORECASE) for w in window)
                        due_ok = any(re.search(r"\bdue\s*:\s*.*\b" + re.escape(target_dow) + r"\b", w, re.IGNORECASE) for w in window)
                        if owner_ok and due_ok:
                            found = True
                            break
                per_milestone_ok.append(found)
            actions_ok = all(per_milestone_ok)
    scores["advisor_notes_actions_per_milestone"] = 1.0 if actions_ok else 0.0

    # Advisor notes reference schedule: mention at least one category from CSV and include some numeric count
    references_ok = False
    if advisor_notes_text is not None and isinstance(schedule_rows, list):
        used_categories = sorted(set(r.get("category", "") for r in schedule_rows if r.get("category")))
        mentions_category = any(cat and (cat in advisor_notes_text) for cat in used_categories)
        has_number = re.search(r"\b\d+\b", advisor_notes_text) is not None
        references_ok = mentions_category and has_number
    scores["advisor_notes_references_schedule"] = 1.0 if references_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()