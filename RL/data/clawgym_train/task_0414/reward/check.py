import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml_map(text: str) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        if val.lower() in ("true", "false"):
            cfg[key] = (val.lower() == "true")
        else:
            # Try numeric conversion, else leave as string
            try:
                if "." in val:
                    cfg[key] = float(val)
                else:
                    cfg[key] = int(val)
            except Exception:
                cfg[key] = val
    return cfg


def _read_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    try:
        return _parse_simple_yaml_map(text)
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames or []
            return header, rows
    except Exception:
        return None


def _to_int(val: Optional[str]) -> Optional[int]:
    try:
        if val is None or val == "":
            return 0
        return int(val)
    except Exception:
        try:
            return int(float(val))
        except Exception:
            return None


def _to_float(val: Optional[str]) -> Optional[float]:
    try:
        if val is None or val == "":
            return 0.0
        return float(val)
    except Exception:
        return None


def _parse_date(val: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(val)
    except Exception:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(val, fmt)
            except Exception:
                continue
        return None


def _compute_expected_aggregation(data_rows: List[Dict[str, str]], player: Optional[str]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for row in data_rows:
        if player and row.get("player") != player:
            continue
        drill = row.get("drill")
        if drill is None:
            drill = ""
        reps = _to_int(row.get("reps", "0"))
        makes = _to_int(row.get("makes", "0"))
        misses = _to_int(row.get("misses", "0"))
        minutes = _to_int(row.get("minutes", "0"))
        if None in (reps, makes, misses, minutes):
            # Malformed numeric data -> return empty expected to trigger failure
            return {}
        if drill not in groups:
            groups[drill] = {
                "total_reps": 0,
                "total_makes": 0,
                "total_misses": 0,
                "total_minutes": 0,
            }
        g = groups[drill]
        g["total_reps"] += reps or 0
        g["total_makes"] += makes or 0
        g["total_misses"] += misses or 0
        g["total_minutes"] += minutes or 0
    for g in groups.values():
        denom = g["total_makes"] + g["total_misses"]
        g["fg_pct"] = (g["total_makes"] / denom) if denom != 0 else 0.0
    return groups


def _read_report_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, Any]]]]:
    parsed = _read_csv_rows(path)
    if parsed is None:
        return None
    header, rows = parsed
    out_rows: List[Dict[str, Any]] = []
    for r in rows:
        conv: Dict[str, Any] = dict(r)
        for k in ["total_reps", "total_makes", "total_misses", "total_minutes"]:
            if k in conv:
                iv = _to_int(conv[k])
                if iv is None:
                    return None
                conv[k] = iv
        if "fg_pct" in conv:
            fv = _to_float(conv["fg_pct"])
            if fv is None:
                return None
            conv["fg_pct"] = fv
        out_rows.append(conv)
    return header, out_rows


def _floats_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _get_section(text: str, header: str) -> Optional[str]:
    headers = ["Bug summary", "Fix summary", "Practice insights", "Action items"]
    lines = text.splitlines()
    indices: Dict[str, int] = {}
    for h in headers:
        idx: Optional[int] = None
        for i, ln in enumerate(lines):
            # Accept "Header:" line, or line containing the exact header phrase alone
            if re.search(rf"^\s*{re.escape(h)}\s*[:\-]?\s*$", ln, flags=re.IGNORECASE):
                idx = i
                break
        if idx is not None:
            indices[h.lower()] = idx
    h_lower = header.lower()
    if h_lower not in indices:
        return None
    start = indices[h_lower]
    next_indices = [i for k, i in indices.items() if i > start]
    end = min(next_indices) if next_indices else len(lines)
    return "\n".join(lines[start:end])


def _count_bullets(section_text: str) -> int:
    count = 0
    for ln in section_text.splitlines():
        s = ln.strip()
        if s.startswith("- ") or s.startswith("* "):
            count += 1
    return count


def _detect_date_parsing_uses_config(script_text: str) -> bool:
    # Accept either: df[date_col] = pd.to_datetime(df[date_col])
    pat1 = re.search(r"df\[\s*date_col\s*\]\s*=\s*pd\.to_datetime\(\s*df\[\s*date_col\s*\]\s*\)", script_text)
    # Or: df\['date'\] = pd.to_datetime(df[date_col])
    pat2 = re.search(r"df\[\s*['\"][^'\"]+['\"]\s*\]\s*=\s*pd\.to_datetime\(\s*df\[\s*date_col\s*\]\s*\)", script_text)
    # Or use parse_dates with date_col in read_csv
    pat3 = re.search(r"read_csv\([^)]*parse_dates\s*=\s*\[\s*date_col\s*\][^)]*\)", script_text)
    # Ensure they are not still hard-coding 'date' in both positions
    hardcoded = re.search(r"pd\.to_datetime\(\s*df\[\s*['\"]date['\"]\s*\]\s*\)", script_text)
    if (pat1 or pat2 or pat3) and not hardcoded:
        return True
    # Also accept if they directly reference cfg.get('date_column', ...) in to_datetime
    pat4 = re.search(r"pd\.to_datetime\(\s*df\[\s*cfg\.get\(\s*['\"]date_column['\"].*?\)\s*\]\s*\)", script_text)
    if pat4 and not hardcoded:
        return True
    return False


def _detect_ensures_output_directory(script_text: str) -> bool:
    # Look for ensuring 'out' directory or parent of output path exists with exist_ok=True
    has_out_ref = ("out/" in script_text) or ("'out'" in script_text) or ('"out"' in script_text)
    uses_makedirs = ("os.makedirs" in script_text and "exist_ok=True" in script_text)
    uses_mkdir = (".mkdir(" in script_text and "exist_ok=True" in script_text)
    return has_out_ref and (uses_makedirs or uses_mkdir)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "date_parsing_uses_config": 0.0,
        "ensures_output_directory": 0.0,
        "report_generated": 0.0,
        "report_columns_and_order": 0.0,
        "report_values_correct": 0.0,
        "fg_pct_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections": 0.0,
        "bug_summary_references_error": 0.0,
        "fix_summary_covers_changes": 0.0,
        "practice_insights_top3_and_date_range": 0.0,
        "action_items_requirements": 0.0,
    }

    script_path = workspace / "scripts" / "generate_practice_report.py"
    config_path = workspace / "config" / "report.yml"
    data_path = workspace / "data" / "workouts.csv"
    report_path = workspace / "out" / "practice_report.csv"
    notes_path = workspace / "out" / "meeting_notes.md"
    log_path = workspace / "logs" / "last_run_error.txt"

    # Static code checks for robustness requirements
    script_text = _read_text_safe(script_path)
    if script_text is not None:
        if _detect_date_parsing_uses_config(script_text):
            scores["date_parsing_uses_config"] = 1.0
        if _detect_ensures_output_directory(script_text):
            scores["ensures_output_directory"] = 1.0

    # Report presence and schema
    report_parsed = None
    if report_path.exists():
        scores["report_generated"] = 1.0
        report_parsed = _read_report_csv(report_path)

    expected_cols = ["drill", "total_reps", "total_makes", "total_misses", "fg_pct", "total_minutes"]
    if report_parsed is not None:
        header, _rows = report_parsed
        if header == expected_cols:
            scores["report_columns_and_order"] = 1.0

    # Value correctness checks based on provided inputs
    cfg = _read_yaml_config(config_path) if config_path.exists() else None
    data_parsed = _read_csv_rows(data_path) if data_path.exists() else None
    if report_parsed is not None and cfg is not None and data_parsed is not None:
        _, data_rows = data_parsed
        player = cfg.get("player") if isinstance(cfg.get("player"), str) else None
        expected_groups = _compute_expected_aggregation(data_rows, player)
        if expected_groups:
            _, report_rows = report_parsed
            # Build actual map by drill
            actual_map: Dict[str, Dict[str, Any]] = {}
            all_required_present = True
            for r in report_rows:
                drill = r.get("drill", "")
                actual_map[drill] = r
                for k in ["total_reps", "total_makes", "total_misses", "total_minutes", "fg_pct"]:
                    if k not in r:
                        all_required_present = False
                        break
                if not all_required_present:
                    break
            if all_required_present and set(actual_map.keys()) == set(expected_groups.keys()):
                totals_match = True
                for drill, exp in expected_groups.items():
                    act = actual_map.get(drill, {})
                    if act.get("total_reps") != exp["total_reps"]:
                        totals_match = False
                        break
                    if act.get("total_makes") != exp["total_makes"]:
                        totals_match = False
                        break
                    if act.get("total_misses") != exp["total_misses"]:
                        totals_match = False
                        break
                    if act.get("total_minutes") != exp["total_minutes"]:
                        totals_match = False
                        break
                if totals_match:
                    scores["report_values_correct"] = 1.0

                fg_ok = True
                for drill, exp in expected_groups.items():
                    act = actual_map.get(drill, {})
                    try:
                        act_fg = float(act.get("fg_pct", -1.0))
                    except Exception:
                        fg_ok = False
                        break
                    if not _floats_close(act_fg, float(exp["fg_pct"])):
                        fg_ok = False
                        break
                if fg_ok:
                    scores["fg_pct_correct"] = 1.0

    # Meeting notes checks
    notes_text = _read_text_safe(notes_path)
    if notes_text is not None:
        scores["meeting_notes_exists"] = 1.0

        has_bug = _get_section(notes_text, "Bug summary") is not None
        has_fix = _get_section(notes_text, "Fix summary") is not None
        has_insights = _get_section(notes_text, "Practice insights") is not None
        has_actions = _get_section(notes_text, "Action items") is not None
        if has_bug and has_fix and has_insights and has_actions:
            scores["meeting_notes_sections"] = 1.0

        bug_sec = _get_section(notes_text, "Bug summary")
        if bug_sec:
            bug_lower = bug_sec.lower()
            referenced_error = False
            # Must reference observed error from logs: KeyError: 'date'
            if "keyerror" in bug_lower and ("'date'" in bug_sec or "keyerror: 'date'" in bug_lower or "keyerror: \"date\"" in bug_lower):
                # And describe cause related to date_column/session_date or hard-coded date
                if ("date_column" in bug_lower) or ("session_date" in bug_lower) or ("hard-coded" in bug_lower) or ("hardcoded" in bug_lower):
                    referenced_error = True
            if referenced_error:
                scores["bug_summary_references_error"] = 1.0

        fix_sec = _get_section(notes_text, "Fix summary")
        if fix_sec:
            fix_lower = fix_sec.lower()
            has_script_path = "scripts/generate_practice_report.py" in fix_sec
            mentions_out_dir = ("output directory" in fix_lower or "out/" in fix_lower or "os.makedirs" in fix_lower or "mkdir" in fix_lower or "ensure directory" in fix_lower or "ensure the directory exists" in fix_lower)
            if has_script_path and mentions_out_dir:
                scores["fix_summary_covers_changes"] = 1.0

        insights_sec = _get_section(notes_text, "Practice insights")
        if insights_sec and report_parsed is not None:
            _, report_rows = report_parsed
            if len(report_rows) >= 1:
                def _safe_makes(r: Dict[str, Any]) -> int:
                    iv = _to_int(str(r.get("total_makes", 0)))
                    return iv if iv is not None else -10**9

                sorted_by_makes = sorted(report_rows, key=lambda r: (-_safe_makes(r), r.get("drill", "")))
                top3 = [r.get("drill", "") for r in sorted_by_makes[:3]]
                has_all_top3 = all(d and (d in insights_sec) for d in top3)

                min_date_str = None
                max_date_str = None
                if cfg is not None and data_parsed is not None:
                    date_col = str(cfg.get("date_column", "date"))
                    player_cfg = cfg.get("player") if isinstance(cfg.get("player"), str) else None
                    _, data_rows2 = data_parsed
                    dates: List[datetime] = []
                    for row in data_rows2:
                        if player_cfg and row.get("player") != player_cfg:
                            continue
                        dval = row.get(date_col)
                        if dval:
                            d = _parse_date(dval)
                            if d is not None:
                                dates.append(d)
                    if dates:
                        min_date = min(dates)
                        max_date = max(dates)
                        min_date_str = min_date.date().isoformat()
                        max_date_str = max_date.date().isoformat()
                date_range_ok = False
                if min_date_str and max_date_str:
                    if (min_date_str in insights_sec) and (max_date_str in insights_sec):
                        date_range_ok = True

                if has_all_top3 and date_range_ok:
                    scores["practice_insights_top3_and_date_range"] = 1.0

        actions_sec = _get_section(notes_text, "Action items")
        if actions_sec and report_parsed is not None:
            bullets_count = _count_bullets(actions_sec)
            _, report_rows = report_parsed
            low_drills = [r.get("drill", "") for r in report_rows if _to_float(str(r.get("fg_pct", "0"))) is not None and float(r["fg_pct"]) < 0.5]
            mentions_all_low = all((d in actions_sec) for d in low_drills if d)
            if bullets_count >= 3 and mentions_all_low:
                scores["action_items_requirements"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()