import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(r) for r in reader]
            return header, rows
    except Exception:
        return None, None


def _safe_load_json_array(path: Path) -> Optional[list]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _safe_load_jsonl_counts(path: Path, key: str = "category") -> Optional[Dict[str, int]]:
    try:
        counts: Dict[str, int] = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if key in obj and isinstance(obj[key], str):
                    counts[obj[key]] = counts.get(obj[key], 0) + 1
                else:
                    return None
        return counts
    except Exception:
        return None


def _parse_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        try:
            # handle floats represented as ints
            f = float(val)
            if abs(f - int(round(f))) < 1e-9:
                return int(round(f))
        except Exception:
            pass
    return None


def _parse_float(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _parse_week(week_str: str) -> Optional[Tuple[int, int]]:
    m = re.match(r"^\s*(\d{4})-W(\d{1,2})\s*$", week_str)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _week_max(weeks: List[str]) -> Optional[str]:
    parsed = []
    for w in weeks:
        t = _parse_week(w)
        if t is None:
            # fallback: use original string if malformed
            parsed.append((None, w))
        else:
            parsed.append((t, w))
    # Prefer properly parsed tuples; if any parsed None exist, compare lex on original
    valid = [p for p in parsed if p[0] is not None]
    if valid:
        max_tuple = max(valid, key=lambda x: (x[0][0], x[0][1]))
        return max_tuple[1]
    else:
        if weeks:
            return max(weeks)
    return None


def _normalize_label(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _find_section_positions(text: str, labels: List[str]) -> Dict[str, int]:
    # Find positions (index in text) of lines that start with the labels (case-insensitive)
    positions: Dict[str, int] = {}
    label_set = {_normalize_label(l) for l in labels}
    # Build regex to match headings or label lines, with optional colon
    pattern = re.compile(r"^(?P<prefix>\s*#{0,6}\s*)(?P<label>.+?)(?P<colon>\s*:)?\s*$", re.IGNORECASE)
    offset = 0
    for line in text.splitlines(True):  # keep line breaks to calculate indices
        m = pattern.match(line)
        if m:
            lab = _normalize_label(m.group("label"))
            if lab in label_set and lab not in positions:
                positions[lab] = offset
        offset += len(line)
    return positions


def _slice_section(text: str, start_idx: int, end_idx: Optional[int]) -> str:
    if end_idx is None:
        return text[start_idx:]
    return text[start_idx:end_idx]


def _get_sections(text: str, ordered_labels: List[str]) -> Dict[str, str]:
    # Return sections content keyed by normalized label between labels
    positions = _find_section_positions(text, ordered_labels)
    sections: Dict[str, str] = {}
    # Determine order by actual occurrence
    ordered_found = [(lab, positions[_normalize_label(lab)]) for lab in ordered_labels if _normalize_label(lab) in positions]
    ordered_found.sort(key=lambda x: x[1])
    for i, (lab, pos) in enumerate(ordered_found):
        next_idx = ordered_found[i + 1][1] if i + 1 < len(ordered_found) else None
        content = _slice_section(text, pos, next_idx)
        sections[_normalize_label(lab)] = content
    return sections


def _contains_number_approx(text: str, number: float, tol: float = 0.05) -> bool:
    # Look for a number in text approximately equal (for floats)
    # First quick substrings for integer-like
    s_no_commas = re.sub(r"[,\s]", "", text)
    num_str = str(int(number)) if abs(number - int(number)) < 1e-9 else None
    if num_str and num_str in s_no_commas:
        return True
    # Extract all numeric tokens
    for m in re.finditer(r"\d+(?:,\d{3})*(?:\.\d+)?", text):
        token = m.group(0)
        val = float(token.replace(",", ""))
        if abs(val - number) <= tol:
            return True
    return False


def _contains_int_number(text: str, number: int) -> bool:
    # Look for integer with or without commas
    patterns = [
        str(number),
        f"{number:,}",
    ]
    # Remove spaces to avoid mismatches in formatting
    t = text
    for p in patterns:
        if p in t:
            return True
    # Check numeric tokens
    for m in re.finditer(r"\d+(?:,\d{3})*", t):
        if int(m.group(0).replace(",", "")) == number:
            return True
    return False


def _numbers_near_project(line: str, project_name: str, nums: List[int]) -> bool:
    if project_name.lower() not in line.lower():
        return False
    return all(_contains_int_number(line, n) for n in nums)


def _top_categories_from_counts(counts: Dict[str, int], top_n: int = 3) -> List[Tuple[str, int]]:
    # Sort by count desc, then by category name asc for determinism
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:top_n]


def _category_mentioned_with_count(text: str, category: str, count: int) -> bool:
    # Accept either exact category name or humanized version with spaces
    human = category.replace("_", " ")
    # Build case-insensitive search
    idxs = []
    for pat in [category, human]:
        for m in re.finditer(re.escape(pat), text, flags=re.IGNORECASE):
            idxs.append(m.start())
    # For each occurrence, see if a count number appears within +/- 80 chars
    for idx in idxs:
        start = max(0, idx - 80)
        end = min(len(text), idx + 80)
        window = text[start:end]
        if _contains_int_number(window, count):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "progress_summary_header_and_columns": 0.0,
        "progress_summary_latest_projects_rows": 0.0,
        "progress_summary_delta_correct": 0.0,
        "progress_summary_all_row": 0.0,
        "progress_summary_row_count": 0.0,
        "missing_briefs_correct": 0.0,
        "edited_draft_includes_latest_and_totals": 0.0,
        "edited_draft_placeholders_removed": 0.0,
        "edited_draft_project_summaries": 0.0,
        "edited_draft_top_concerns": 0.0,
        "weekly_email_sections_order_and_subject": 0.0,
        "weekly_email_highlights_count_and_content": 0.0,
        "weekly_email_by_project_metrics": 0.0,
        "weekly_email_top_concerns_listed": 0.0,
    }

    # Load input data
    input_csv_path = workspace / "input" / "progress_weekly.csv"
    input_draft_path = workspace / "input" / "draft_update.md"
    input_jsonl_path = workspace / "input" / "constituent_feedback.jsonl"
    input_projects_dir = workspace / "input" / "projects"

    header, rows = _safe_load_csv(input_csv_path)
    counts = _safe_load_jsonl_counts(input_jsonl_path, key="category")
    draft_text = _safe_read_text(input_draft_path)  # not strictly needed for grading, but present

    latest_week = None
    latest_week_rows: List[Dict[str, str]] = []
    all_projects_latest: Dict[str, Dict[str, str]] = {}
    totals = {
        "tasks_completed": 0,
        "tasks_pending": 0,
        "spend_in_inr": 0,
        "co2e_avoided_tonnes": 0.0,
    }
    project_prev_week_tasks: Dict[str, Optional[int]] = {}
    project_latest_tasks: Dict[str, int] = {}
    project_names: Dict[str, str] = {}

    if header and rows:
        # Determine latest week
        weeks = [r.get("week", "") for r in rows if "week" in r]
        latest_week = _week_max(weeks)
        if latest_week:
            latest_week_rows = [r for r in rows if r.get("week") == latest_week]
            # Build per-project info
            for r in latest_week_rows:
                pid = r.get("project_id", "")
                project_names[pid] = r.get("project_name", "")
                all_projects_latest[pid] = r
                # Compute totals
                tc = _parse_int(r.get("tasks_completed", ""))
                tp = _parse_int(r.get("tasks_pending", ""))
                spend = _parse_int(r.get("spend_in_inr", ""))
                co2 = _parse_float(r.get("co2e_avoided_tonnes", ""))
                if None not in (tc, tp, spend, co2):
                    totals["tasks_completed"] += tc  # type: ignore
                    totals["tasks_pending"] += tp  # type: ignore
                    totals["spend_in_inr"] += spend  # type: ignore
                    totals["co2e_avoided_tonnes"] += co2  # type: ignore
                    project_latest_tasks[pid] = tc  # type: ignore
                else:
                    # Malformed numeric data prevents totals
                    latest_week_rows = []
                    break
            # Find previous week per project
            if latest_week_rows:
                # Parse all weeks per project and get prev week just before latest
                for pid in all_projects_latest.keys():
                    # collect weeks for that pid
                    prj_weeks = []
                    for r in rows:
                        if r.get("project_id") == pid and r.get("week") != latest_week:
                            wk = r.get("week", "")
                            t = _parse_week(wk)
                            prj_weeks.append((t, wk, r))
                    # select max week < latest
                    prev_candidates = []
                    latest_tuple = _parse_week(latest_week)
                    for t, wk, r in prj_weeks:
                        if t is not None and latest_tuple is not None:
                            if t < latest_tuple:
                                prev_candidates.append((t, r))
                        else:
                            # if parsing fails, fall back to lexicographic comparison
                            if latest_tuple is None and wk < latest_week:
                                prev_candidates.append((None, r))
                    if prev_candidates:
                        prev = sorted(prev_candidates, key=lambda x: x[0])[ -1 ][1]
                        project_prev_week_tasks[pid] = _parse_int(prev.get("tasks_completed", ""))
                    else:
                        project_prev_week_tasks[pid] = None

    # Load outputs
    out_summary_path = workspace / "output" / "progress_summary.csv"
    out_missing_path = workspace / "output" / "missing_project_briefs.json"
    out_edited_path = workspace / "output" / "edited_draft_update.md"
    out_email_path = workspace / "output" / "weekly_update_email.md"

    # Check progress_summary.csv
    out_header, out_rows = _safe_load_csv(out_summary_path)
    expected_header = [
        "project_id",
        "project_name",
        "week",
        "tasks_completed",
        "tasks_pending",
        "spend_in_inr",
        "co2e_avoided_tonnes",
        "delta_tasks_completed_vs_prev_week",
    ]
    if out_header is not None:
        if out_header == expected_header:
            scores["progress_summary_header_and_columns"] = 1.0
        else:
            scores["progress_summary_header_and_columns"] = 0.0

    if out_rows is not None and latest_week and latest_week_rows:
        # Row count check
        expected_project_ids = set([r["project_id"] for r in latest_week_rows])
        actual_project_ids = set([r["project_id"] for r in out_rows if r.get("project_id") not in (None, "") and r.get("project_id") != "ALL"])
        has_all_row = any(r.get("project_id") == "ALL" and r.get("project_name") == "ALL PROJECTS" for r in out_rows)
        if actual_project_ids == expected_project_ids and has_all_row and len(out_rows) == len(expected_project_ids) + 1:
            scores["progress_summary_row_count"] = 1.0

        # Latest project rows correctness and delta
        proj_rows_ok = True
        deltas_ok = True
        for pid in expected_project_ids:
            # find row
            match = [r for r in out_rows if r.get("project_id") == pid]
            if len(match) != 1:
                proj_rows_ok = False
                deltas_ok = False
                continue
            r = match[0]
            src = all_projects_latest[pid]
            # Check fields
            if r.get("project_name") != src.get("project_name"):
                proj_rows_ok = False
            if r.get("week") != latest_week:
                proj_rows_ok = False
            # Numerics exact
            for key in ["tasks_completed", "tasks_pending", "spend_in_inr"]:
                exp_val = _parse_int(src.get(key, ""))
                got_val = _parse_int(r.get(key, ""))
                if exp_val is None or got_val is None or exp_val != got_val:
                    proj_rows_ok = False
            exp_co2 = _parse_float(src.get("co2e_avoided_tonnes", ""))
            got_co2 = _parse_float(r.get("co2e_avoided_tonnes", ""))
            if exp_co2 is None or got_co2 is None or abs(exp_co2 - got_co2) > 1e-9:
                proj_rows_ok = False
            # Delta
            prev_tc = project_prev_week_tasks.get(pid)
            delta_field = r.get("delta_tasks_completed_vs_prev_week", "")
            if prev_tc is None:
                # Should be empty
                if delta_field not in ("", None):
                    deltas_ok = False
            else:
                exp_delta = project_latest_tasks.get(pid, 0) - prev_tc
                got_delta = _parse_int(delta_field if delta_field is not None else "")
                if got_delta is None or got_delta != exp_delta:
                    deltas_ok = False
        if proj_rows_ok:
            scores["progress_summary_latest_projects_rows"] = 1.0
        if deltas_ok:
            scores["progress_summary_delta_correct"] = 1.0

        # ALL row correctness
        all_matches = [r for r in out_rows if r.get("project_id") == "ALL" and r.get("project_name") == "ALL PROJECTS"]
        all_ok = False
        if len(all_matches) == 1:
            ar = all_matches[0]
            # Check sums
            got_tc = _parse_int(ar.get("tasks_completed", ""))
            got_tp = _parse_int(ar.get("tasks_pending", ""))
            got_spend = _parse_int(ar.get("spend_in_inr", ""))
            got_co2 = _parse_float(ar.get("co2e_avoided_tonnes", ""))
            got_delta_sum = _parse_int(ar.get("delta_tasks_completed_vs_prev_week", ""))
            if None not in (got_tc, got_tp, got_spend, got_co2, got_delta_sum):
                # compute expected delta sum
                exp_delta_sum = 0
                ok_delta_contrib = True
                for pid in expected_project_ids:
                    prev_tc = project_prev_week_tasks.get(pid)
                    if prev_tc is None:
                        # if any missing then the sum should ignore or treat as 0? Requirement: "sums the deltas."
                        # If a delta is missing for a project, it should probably be omitted; we cannot verify without value,
                        # but in our provided data, all have prev week. Proceed strictly.
                        ok_delta_contrib = False
                    else:
                        exp_delta_sum += project_latest_tasks.get(pid, 0) - prev_tc
                if ok_delta_contrib and (
                    got_tc == totals["tasks_completed"]
                    and got_tp == totals["tasks_pending"]
                    and got_spend == totals["spend_in_inr"]
                    and abs(got_co2 - totals["co2e_avoided_tonnes"]) < 1e-9
                    and got_delta_sum == exp_delta_sum
                ):
                    all_ok = True
        if all_ok:
            scores["progress_summary_all_row"] = 1.0

    # Check missing_project_briefs.json
    expected_missing: List[Dict[str, str]] = []
    if latest_week_rows:
        for r in latest_week_rows:
            pid = r.get("project_id", "")
            expected_path = str(Path("input") / "projects" / f"{pid}.md")
            proj_file = input_projects_dir / f"{pid}.md"
            if not proj_file.exists():
                expected_missing.append({"project_id": pid, "expected_path": expected_path})
    out_missing = _safe_load_json_array(out_missing_path)
    if out_missing is not None and expected_missing is not None:
        # Compare as sets of tuples
        def norm_list(lst):
            return sorted([(d.get("project_id"), d.get("expected_path")) for d in lst if isinstance(d, dict)])
        if norm_list(out_missing) == norm_list(expected_missing):
            scores["missing_briefs_correct"] = 1.0

    # Load edited draft
    edited_text = _safe_read_text(out_edited_path)
    if edited_text is not None and latest_week and latest_week_rows:
        # Presence of latest week and totals from ALL row
        all_totals_present = True
        if latest_week not in edited_text:
            all_totals_present = False
        # Find ALL row in summary to extract values
        all_tc = totals["tasks_completed"]
        all_co2 = totals["co2e_avoided_tonnes"]
        all_spend = totals["spend_in_inr"]
        if not _contains_int_number(edited_text, all_tc):
            all_totals_present = False
        if not _contains_number_approx(edited_text, all_co2, tol=0.01):
            all_totals_present = False
        if not _contains_int_number(edited_text, all_spend):
            all_totals_present = False
        if all_totals_present:
            scores["edited_draft_includes_latest_and_totals"] = 1.0

        # Placeholders removed
        placeholders = [
            "[WEEK]",
            "[X_TASKS]",
            "[Y_CO2]",
            "[SPEND_TOTAL_INR]",
            "[PROJECT_SNIPPETS_SOLAR]",
            "[PROJECT_SNIPPETS_RAIN]",
            "[PROJECT_SNIPPETS_WASTE]",
            "[TOP_CONCERNS]",
            "[MP NAME]",
        ]
        if all(ph not in edited_text for ph in placeholders):
            scores["edited_draft_placeholders_removed"] = 1.0

        # One concise sentence per project with tasks completed and pending (we check presence on a line)
        per_project_ok = True
        for r in latest_week_rows:
            pname = r.get("project_name", "")
            tc = _parse_int(r.get("tasks_completed", ""))
            tp = _parse_int(r.get("tasks_pending", ""))
            if None in (tc, tp):
                per_project_ok = False
                break
            # Find any line that mentions the project and both numbers
            found = False
            for line in edited_text.splitlines():
                if _numbers_near_project(line, pname, [tc, tp]):  # type: ignore
                    found = True
                    break
            if not found:
                per_project_ok = False
                break
        if per_project_ok:
            scores["edited_draft_project_summaries"] = 1.0

        # Top three categories with counts included
        if counts:
            top3 = _top_categories_from_counts(counts, top_n=3)
            top_ok = True
            for cat, cnt in top3:
                if not _category_mentioned_with_count(edited_text, cat, cnt):
                    top_ok = False
                    break
            if top_ok:
                scores["edited_draft_top_concerns"] = 1.0

    # Load weekly email
    email_text = _safe_read_text(out_email_path)
    if email_text is not None and latest_week and latest_week_rows and counts:
        labels = ["Subject", "Greeting", "Highlights", "By project", "Top concerns (with counts)", "Next steps", "Sign-off"]
        positions = _find_section_positions(email_text, labels)
        # Ensure all labels present and in order
        if all(_normalize_label(l) in positions for l in labels):
            ordered = [positions[_normalize_label(l)] for l in labels]
            if ordered == sorted(ordered):
                # Subject includes latest week
                # Get line at subject position
                subj_pos = positions[_normalize_label("Subject")]
                subj_end = None
                # end is next position
                idxs_sorted = sorted(positions.values())
                for pos in idxs_sorted:
                    if pos > subj_pos:
                        subj_end = pos
                        break
                subj_block = _slice_section(email_text, subj_pos, subj_end)
                subject_has_week = latest_week in subj_block
                if subject_has_week:
                    scores["weekly_email_sections_order_and_subject"] = 1.0

        # Parse sections content for further checks
        sections = _get_sections(email_text, labels)

        # Highlights bullets: 2–4 bullets; at least one with measurable progress
        hi_key = _normalize_label("Highlights")
        if hi_key in sections:
            hi_text = sections[hi_key]
            bullets = [ln for ln in hi_text.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
            if 2 <= len(bullets) <= 4:
                # At least one bullet contains total tasks or total CO2e
                has_progress = False
                for b in bullets:
                    if ("task" in b.lower() and _contains_int_number(b, totals["tasks_completed"])) or ("co2" in b.lower() and _contains_number_approx(b, totals["co2e_avoided_tonnes"], tol=0.01)):
                        has_progress = True
                        break
                if has_progress:
                    scores["weekly_email_highlights_count_and_content"] = 1.0

        # By project: one bullet per project with key metrics (tasks completed/pending)
        bp_key = _normalize_label("By project")
        if bp_key in sections:
            bp_text = sections[bp_key]
            # Build a mapping from project name to presence
            per_project_ok = True
            for r in latest_week_rows:
                pname = r.get("project_name", "")
                tc = _parse_int(r.get("tasks_completed", ""))
                tp = _parse_int(r.get("tasks_pending", ""))
                if None in (tc, tp):
                    per_project_ok = False
                    break
                # find bullet line mentioning project name and both numbers
                found = False
                for ln in bp_text.splitlines():
                    if re.match(r"^\s*[-*]\s+", ln) and pname.lower() in ln.lower() and _contains_int_number(ln, tc) and _contains_int_number(ln, tp):
                        found = True
                        break
                if not found:
                    per_project_ok = False
                    break
            if per_project_ok:
                scores["weekly_email_by_project_metrics"] = 1.0

        # Top concerns (with counts): list top three categories with counts
        tc_key = _normalize_label("Top concerns (with counts)")
        if tc_key in sections:
            tc_text = sections[tc_key]
            top3 = _top_categories_from_counts(counts, top_n=3)
            top_ok = True
            for cat, cnt in top3:
                if not _category_mentioned_with_count(tc_text, cat, cnt):
                    top_ok = False
                    break
            if top_ok:
                scores["weekly_email_top_concerns_listed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()