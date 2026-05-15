import json
import csv
import re
import sys
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = path.read_text(encoding="utf-8")
        return data, None
    except Exception as e:
        return None, str(e)


def _load_json_safe(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_csv_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows, None
    except Exception as e:
        return None, str(e)


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_text(s: str) -> str:
    dash_variants = "\u2010\u2011\u2012\u2013\u2014\u2212"
    trans_table = {ord(ch): "-" for ch in dash_variants}
    return s.translate(trans_table).lower()


def _is_iso_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _find_section_blocks(md_text: str) -> Dict[str, List[str]]:
    lines = _normalize_newlines(md_text).split("\n")
    headings = {
        "context": None,
        "dog-join days": None,
        "excluded days": None,
        "totals": None,
        "compliance": None,
    }
    for idx, raw in enumerate(lines):
        line = _normalize_text(raw).strip()
        head = re.sub(r"^\s*#{0,6}\s*", "", line)
        if re.match(r"^context\b[:\-]?", head):
            headings["context"] = idx
        elif re.match(r"^dog-?join days\b[:\-]?", head):
            headings["dog-join days"] = idx
        elif re.match(r"^excluded days\b[:\-]?", head):
            headings["excluded days"] = idx
        elif re.match(r"^totals\b[:\-]?", head):
            headings["totals"] = idx
        elif re.search(r"\bcompliance\b", head):
            headings["compliance"] = idx

    positions = [(k, v) for k, v in headings.items() if v is not None]
    positions.sort(key=lambda x: x[1])
    blocks: Dict[str, List[str]] = {k: [] for k in headings.keys()}
    for i, (name, start) in enumerate(positions):
        end = len(lines)
        if i + 1 < len(positions):
            end = positions[i + 1][1]
        blocks[name] = lines[start + 1 : end]
    return blocks


def _extract_bullet_lines(block_lines: List[str]) -> List[str]:
    res = []
    for line in block_lines:
        if line.strip().startswith(("-", "*")):
            res.append(line)
    return res


def _run_planner_and_read(workspace: Path) -> Tuple[Optional[str], Optional[str]]:
    script = workspace / "scripts" / "safe_run_planner.py"
    plan = workspace / "input" / "runner_plan.csv"
    profile = workspace / "input" / "dog_profile.json"
    if not (script.exists() and plan.exists() and profile.exists()):
        return None, "missing script or inputs"
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "expected.csv"
            cmd = [sys.executable, str(script), str(plan), str(profile), str(out_path)]
            subprocess.run(cmd, check=True, capture_output=True)
            content = out_path.read_text(encoding="utf-8")
            return _normalize_newlines(content), None
    except Exception as e:
        return None, str(e)


def _read_workspace_shared_runs_text(workspace: Path) -> Tuple[Optional[str], Optional[str]]:
    target = workspace / "build" / "shared_runs.csv"
    if not target.exists():
        return None, "missing shared_runs.csv"
    text, err = _read_text_safe(target)
    if err:
        return None, err
    return _normalize_newlines(text), None


def _float_match_in_line(line: str, value: float) -> bool:
    val_int = int(round(value))
    if abs(value - val_int) < 1e-9:
        pattern = r"\b" + re.escape(str(val_int)) + r"(?:\.0+)?\b"
    else:
        pattern = r"\b" + re.escape(f"{value:.1f}".rstrip("0").rstrip(".")) + r"\b"
    return re.search(pattern, line) is not None


def _get_first_7_dates(plan_rows: List[Dict[str, str]]) -> List[str]:
    dates = []
    for r in plan_rows:
        d = (r.get("date") or "").strip()
        if _is_iso_date(d):
            dates.append(d)
    uniq = sorted(set(dates), key=lambda x: _parse_date(x))
    return uniq[:7]


def _get_notes_by_date(plan_rows: List[Dict[str, str]]) -> Dict[str, str]:
    m = {}
    for r in plan_rows:
        d = (r.get("date") or "").strip()
        if _is_iso_date(d):
            m[d] = (r.get("notes") or "").strip()
    return m


def _sum_distances(rows: List[Dict[str, str]], dates: List[str], field: str = "planned_distance_km") -> float:
    s = 0.0
    want = set(dates)
    for r in rows:
        d = (r.get("date") or "").strip()
        if d in want:
            try:
                s += float(r.get(field, 0) or 0)
            except Exception:
                return float("nan")
    return s


def _collect_join_excluded(rows: List[Dict[str, str]], window_dates: List[str]) -> Tuple[List[str], List[str]]:
    join = []
    excl = []
    for d in window_dates:
        match = None
        for r in rows:
            if (r.get("date") or "").strip() == d:
                match = r
                break
        if match is None:
            continue
        cj = (match.get("can_join") or "").strip().lower()
        if cj == "true":
            join.append(d)
        else:
            excl.append(d)
    return join, excl


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "shared_runs_exists": 0.0,
        "shared_runs_matches_script": 0.0,
        "weekly_status_exists": 0.0,
        "context_line_includes_profile": 0.0,
        "dog_join_days_list_complete": 0.0,
        "excluded_days_list_complete": 0.0,
        "totals_section_correct": 0.0,
        "compliance_distance_limit_check": 0.0,
        "compliance_consecutive_days_check": 0.0,
        "compliance_rest_target_check": 0.0,
        "focus_window_enforced": 0.0,
    }

    plan_path = workspace / "input" / "runner_plan.csv"
    profile_path = workspace / "input" / "dog_profile.json"
    plan_rows, _ = _load_csv_safe(plan_path) if plan_path.exists() else (None, "missing")
    profile, _ = _load_json_safe(profile_path) if profile_path.exists() else (None, "missing")

    shared_text, _ = _read_workspace_shared_runs_text(workspace)
    if shared_text is not None:
        scores["shared_runs_exists"] = 1.0
    else:
        scores["shared_runs_exists"] = 0.0

    expected_text, _ = _run_planner_and_read(workspace)
    if shared_text is not None and expected_text is not None:
        if shared_text.strip() == expected_text.strip():
            scores["shared_runs_matches_script"] = 1.0
        else:
            scores["shared_runs_matches_script"] = 0.0
    else:
        scores["shared_runs_matches_script"] = 0.0

    shared_rows, shared_csv_err = (None, None)
    if shared_text is not None:
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td) / "s.csv"
                tmp.write_text(shared_text, encoding="utf-8")
                shared_rows, shared_csv_err = _load_csv_safe(tmp)
        except Exception as e:
            shared_rows, shared_csv_err = None, str(e)
    else:
        shared_rows, shared_csv_err = None, "missing shared_runs.csv"

    status_path = workspace / "updates" / "dog_run_weekly_status.md"
    md_text, _ = _read_text_safe(status_path) if status_path.exists() else (None, "missing")
    if md_text is not None:
        scores["weekly_status_exists"] = 1.0
        blocks = _find_section_blocks(md_text)
    else:
        blocks = {}

    if plan_rows is not None:
        window_dates = _get_first_7_dates(plan_rows)
        notes_by_date = _get_notes_by_date(plan_rows)
    else:
        window_dates = []
        notes_by_date = {}

    if md_text is not None and profile is not None:
        context_block = blocks.get("context", [])
        context_ok = False
        req_name = str(profile.get("name", "")).strip()
        req_breed = str(profile.get("breed", "")).strip()
        req_age = str(profile.get("age_years", "")).strip()
        req_max = str(profile.get("max_suggested_single_run_km", "")).strip()
        for line in context_block:
            if req_name and req_breed and req_age and req_max:
                if (req_name in line and req_breed in line and
                        re.search(rf"\b{re.escape(str(req_age))}\b", line) and
                        re.search(rf"\b{re.escape(str(req_max))}\b", line)):
                    context_ok = True
                    break
        scores["context_line_includes_profile"] = 1.0 if context_ok else 0.0
    else:
        scores["context_line_includes_profile"] = 0.0

    dog_join_ok = False
    excluded_ok = False
    focus_ok = False
    if md_text is not None and shared_rows is not None and plan_rows is not None:
        dog_block = blocks.get("dog-join days", [])
        excl_block = blocks.get("excluded days", [])
        dog_bullets = _extract_bullet_lines(dog_block)
        excl_bullets = _extract_bullet_lines(excl_block)

        join_dates, excl_dates = _collect_join_excluded(shared_rows, window_dates)

        joined_dates_in_block = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", "\n".join(dog_block)))
        excluded_dates_in_block = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", "\n".join(excl_block)))
        all_block_dates = joined_dates_in_block.union(excluded_dates_in_block)
        if all_block_dates and window_dates:
            focus_ok = all(d in set(window_dates) for d in all_block_dates)
        else:
            focus_ok = False

        all_join_listed = True
        for d in join_dates:
            row = next((r for r in shared_rows if (r.get("date") or "").strip() == d), None)
            if row is None:
                all_join_listed = False
                break
            try:
                dist = float(row.get("planned_distance_km", 0) or 0)
            except Exception:
                all_join_listed = False
                break
            inten = (row.get("intensity") or "").strip()
            note = notes_by_date.get(d, "")
            found = False
            for bl in dog_bullets:
                if d in bl and _float_match_in_line(bl, dist) and (inten.lower() in _normalize_text(bl)):
                    if note:
                        if note.lower() in bl.lower():
                            found = True
                            break
                    else:
                        found = True
                        break
            if not found:
                all_join_listed = False
                break

        all_excl_listed = True
        for d in excl_dates:
            row = next((r for r in shared_rows if (r.get("date") or "").strip() == d), None)
            if row is None:
                all_excl_listed = False
                break
            try:
                dist = float(row.get("planned_distance_km", 0) or 0)
            except Exception:
                all_excl_listed = False
                break
            inten = (row.get("intensity") or "").strip()
            reason = (row.get("reason") or "").strip()
            found = False
            for bl in excl_bullets:
                if d in bl and _float_match_in_line(bl, dist) and (inten.lower() in _normalize_text(bl)) and (reason.lower() in _normalize_text(bl)):
                    found = True
                    break
            if not found:
                all_excl_listed = False
                break

        dog_join_ok = all_join_listed and len(join_dates) == len(set(join_dates))
        excluded_ok = all_excl_listed and len(excl_dates) == len(set(excl_dates))

    scores["dog_join_days_list_complete"] = 1.0 if dog_join_ok else 0.0
    scores["excluded_days_list_complete"] = 1.0 if excluded_ok else 0.0
    scores["focus_window_enforced"] = 1.0 if focus_ok else 0.0

    totals_ok = False
    if md_text is not None and shared_rows is not None and plan_rows is not None:
        totals_block = blocks.get("totals", [])
        my_total = _sum_distances(plan_rows, window_dates)
        join_dates, _ = _collect_join_excluded(shared_rows, window_dates)
        riley_total = 0.0
        for d in join_dates:
            row = next((r for r in shared_rows if (r.get("date") or "").strip() == d), None)
            if row is None:
                riley_total = float("nan")
                break
            try:
                riley_total += float(row.get("planned_distance_km", 0) or 0)
            except Exception:
                riley_total = float("nan")
                break

        if not (my_total != my_total or riley_total != riley_total):
            lines = totals_block
            my_line_ok = False
            riley_line_ok = False
            for ln in lines:
                nln = _normalize_text(ln)
                if "total" in nln and "for me" in nln and _float_match_in_line(ln, my_total):
                    my_line_ok = True
                if "total" in nln and (("riley" in nln) or ("dog" in nln)) and _float_match_in_line(ln, riley_total):
                    riley_line_ok = True
            totals_ok = my_line_ok and riley_line_ok

    scores["totals_section_correct"] = 1.0 if totals_ok else 0.0

    comp_ok_distance = False
    comp_ok_consecutive = False
    comp_ok_rest = False
    if md_text is not None and shared_rows is not None and plan_rows is not None and profile is not None:
        blocks = _find_section_blocks(md_text)
        comp_block = blocks.get("compliance", [])
        comp_text = "\n".join(comp_block)
        comp_norm = _normalize_text(comp_text)

        ordered = []
        for d in window_dates:
            row = next((r for r in shared_rows if (r.get("date") or "").strip() == d), None)
            if row is None:
                continue
            cj = (row.get("can_join") or "").strip().lower() == "true"
            try:
                dist = float(row.get("planned_distance_km", 0) or 0)
            except Exception:
                dist = 0.0
            ordered.append((d, cj, dist))

        max_km = None
        try:
            max_km = float(profile.get("max_suggested_single_run_km", 0) or 0)
        except Exception:
            max_km = None
        if max_km is not None:
            exceeding_dates = [d for (d, cj, dist) in ordered if cj and dist > max_km]
            if exceeding_dates:
                first_exceed = exceeding_dates[0]
                comp_ok_distance = (first_exceed in comp_text)
            else:
                has_within = ("within" in comp_norm and re.search(rf"\b{re.escape(str(int(max_km)))}\b", comp_norm) is not None)
                has_le = ("<=" in comp_text)
                has_no_exceed = ("no" in comp_norm and "exceed" in comp_norm)
                comp_ok_distance = bool(has_within or has_le or has_no_exceed)

        longest = 0
        current = 0
        for _, cj, _ in ordered:
            if cj:
                current += 1
                if current > longest:
                    longest = current
            else:
                current = 0
        if longest >= 3:
            comp_ok_consecutive = ("rest/skills" in comp_norm)
        else:
            comp_ok_consecutive = (("no" in comp_norm and "adjust" in comp_norm) or ("no" in comp_norm and "consecutive" in comp_norm))

        rest_days_target = None
        try:
            rest_days_target = int(profile.get("rest_days_per_week", 0))
        except Exception:
            rest_days_target = None
        if rest_days_target is not None:
            non_run_days = sum(1 for (_, cj, _) in ordered if not cj)
            if non_run_days == rest_days_target:
                comp_ok_rest = ("meets" in comp_norm)
            elif non_run_days > rest_days_target:
                comp_ok_rest = ("exceeds" in comp_norm)
            else:
                comp_ok_rest = ("falls short" in comp_norm)

    scores["compliance_distance_limit_check"] = 1.0 if comp_ok_distance else 0.0
    scores["compliance_consecutive_days_check"] = 1.0 if comp_ok_consecutive else 0.0
    scores["compliance_rest_target_check"] = 1.0 if comp_ok_rest else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()