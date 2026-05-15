import csv
import json
import math
import re
import sys
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames or []
    except Exception:
        return None, None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _median(nums: List[float]) -> float:
    if not nums:
        return float("nan")
    return float(median(nums))


def _nearly_equal(a: float, b: float, tol: float) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _compute_expected_from_runs(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    team_runs: Dict[str, List[Dict[str, Any]]] = {}
    total_runs = 0
    completed_runs_global: List[Dict[str, Any]] = []
    drop_counts: Dict[str, int] = {}
    for r in rows:
        team = r.get("team", "")
        ck_c = r.get("checkpoints_completed", "")
        ck_t = r.get("total_checkpoints", "")
        time_min = r.get("time_min", "")
        dist_km = r.get("distance_km", "")
        drop_at = r.get("dropped_at_checkpoint", "")

        ck_c_i = _to_float(ck_c)
        ck_t_i = _to_float(ck_t)
        t = _to_float(time_min)
        d = _to_float(dist_km)

        team_key = str(team)
        if team_key not in team_runs:
            team_runs[team_key] = []
        team_runs[team_key].append({
            "completed": (ck_c_i is not None and ck_t_i is not None and ck_c_i == ck_t_i),
            "time_min": t,
            "distance_km": d,
        })
        total_runs += 1

        if (ck_c_i is not None and ck_t_i is not None and ck_c_i == ck_t_i) and (t is not None):
            completed_runs_global.append({"time_min": t})

        drop_idx = _to_float(drop_at)
        if (drop_idx is not None) and (ck_c_i is not None and ck_t_i is not None and ck_c_i < ck_t_i):
            k = str(int(drop_idx))
            drop_counts[k] = drop_counts.get(k, 0) + 1

    team_stats: Dict[str, Dict[str, Any]] = {}
    for team, runs in team_runs.items():
        total = len(runs)
        completed = [r for r in runs if r["completed"] and (r["time_min"] is not None) and (r["distance_km"] is not None)]
        completed_count = len([r for r in runs if r["completed"]])
        completion_rate = (completed_count / total) if total > 0 else float("nan")
        times = [float(r["time_min"]) for r in completed]
        dists = [float(r["distance_km"]) for r in completed]
        paces = []
        for t, d in zip(times, dists):
            if d > 0:
                paces.append(t / d)
        avg_time = (sum(times) / len(times)) if times else float("nan")
        med_time = _median(times) if times else float("nan")
        avg_pace = (sum(paces) / len(paces)) if paces else float("nan")
        team_stats[team] = {
            "team": team,
            "total_runs": total,
            "completed_runs": completed_count,
            "completion_rate": completion_rate,
            "avg_time_min": avg_time,
            "median_time_min": med_time,
            "avg_pace_min_per_km": avg_pace,
        }

    completed_total = len([r for r in rows if _to_float(r.get("checkpoints_completed")) is not None
                           and _to_float(r.get("total_checkpoints")) is not None
                           and _to_float(r.get("checkpoints_completed")) == _to_float(r.get("total_checkpoints"))])
    overall_completion_rate = (completed_total / total_runs) if total_runs > 0 else float("nan")
    overall_avg_time = (sum([r["time_min"] for r in completed_runs_global]) / len(completed_runs_global)) if completed_runs_global else float("nan")

    expected = {
        "team_stats": team_stats,
        "drops": drop_counts,
        "total_runs": total_runs,
        "overall_completion_rate": overall_completion_rate,
        "overall_avg_time_min": overall_avg_time,
    }
    return expected


def _parse_markdown_section(text: str, header: str) -> List[str]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == header.lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    known_headers = {"objective:", "key findings:", "issues observed:", "action items:"}
    section: List[str] = []
    for j in range(start_idx, len(lines)):
        l = lines[j]
        if l.strip().lower() in known_headers:
            break
        section.append(l)
    return section


def _extract_bullet_lines(section_lines: List[str]) -> List[str]:
    return [ln for ln in section_lines if ln.strip().startswith("- ") or ln.strip().startswith("* ")]


def _split_run_log_sections(text: str) -> Dict[str, str]:
    sections = {}
    pattern = r"^===\s*(VALID RUN|MALFORMED RUN)\s*===\s*$"
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
    for i, m in enumerate(matches):
        title = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections[title] = content
    return sections


def _extract_exit_code(section_text: str) -> Optional[int]:
    m = re.search(r"exit\s*code[^-\d]*(-?\d+)", section_text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _section_contains_input_path(section_text: str, rel_path: str) -> bool:
    return rel_path in section_text


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    cli_path = workspace / "prototype" / "nav_analyzer"
    stats_csv_path = workspace / "output" / "stats_summary.csv"
    checkpoint_json_path = workspace / "output" / "checkpoint_stats.json"
    run_log_path = workspace / "output" / "run_log.txt"
    notes_md_path = workspace / "deliverables" / "briefing_notes.md"
    input_clean_path = workspace / "input" / "logs" / "nav_runs.csv"
    input_bad_path = workspace / "input" / "logs" / "nav_runs_bad.csv"

    scores: Dict[str, float] = {
        "cli_entry_point_present": 0.0,
        "output_stats_summary_exists": 0.0,
        "output_checkpoint_stats_exists": 0.0,
        "output_run_log_exists": 0.0,
        "stats_summary_structure_correct": 0.0,
        "stats_summary_values_correct": 0.0,
        "checkpoint_stats_structure_correct": 0.0,
        "checkpoint_stats_values_correct": 0.0,
        "run_log_valid_section_present_with_success_exit": 0.0,
        "run_log_malformed_section_present_with_failure_exit": 0.0,
        "run_log_malformed_includes_error_detail": 0.0,
        "briefing_notes_sections_present": 0.0,
        "briefing_key_findings_has_3_bullets": 0.0,
        "briefing_key_findings_references_outputs": 0.0,
        "briefing_issues_quotes_error_and_explains": 0.0,
        "briefing_action_items_3_to_5_with_owner_due": 0.0,
    }

    if cli_path.exists() and cli_path.is_file():
        scores["cli_entry_point_present"] = 1.0

    if stats_csv_path.exists() and stats_csv_path.is_file():
        scores["output_stats_summary_exists"] = 1.0
    if checkpoint_json_path.exists() and checkpoint_json_path.is_file():
        scores["output_checkpoint_stats_exists"] = 1.0
    if run_log_path.exists() and run_log_path.is_file():
        scores["output_run_log_exists"] = 1.0

    clean_rows, clean_headers = _load_csv(input_clean_path) if input_clean_path.exists() else (None, None)

    stats_rows, stats_headers = _load_csv(stats_csv_path) if stats_csv_path.exists() else (None, None)
    if stats_rows is not None and stats_headers is not None:
        expected_headers = [
            "team",
            "total_runs",
            "completed_runs",
            "completion_rate",
            "avg_time_min",
            "median_time_min",
            "avg_pace_min_per_km",
        ]
        if stats_headers == expected_headers:
            scores["stats_summary_structure_correct"] = 1.0

        if clean_rows is not None:
            expected = _compute_expected_from_runs(clean_rows)
            exp_team_stats = expected["team_stats"]  # type: ignore
            try:
                file_team_stats: Dict[str, Dict[str, Any]] = {}
                for r in stats_rows:
                    team = r.get("team")
                    if not team:
                        raise ValueError("missing team")
                    tr = int(float(r.get("total_runs", "nan")))
                    cr = int(float(r.get("completed_runs", "nan")))
                    comp_rate = float(r.get("completion_rate", "nan"))
                    avg_time = float(r.get("avg_time_min", "nan"))
                    med_time = float(r.get("median_time_min", "nan"))
                    avg_pace = float(r.get("avg_pace_min_per_km", "nan"))
                    file_team_stats[team] = {
                        "total_runs": tr,
                        "completed_runs": cr,
                        "completion_rate": comp_rate,
                        "avg_time_min": avg_time,
                        "median_time_min": med_time,
                        "avg_pace_min_per_km": avg_pace,
                    }
                if set(file_team_stats.keys()) == set(exp_team_stats.keys()):
                    all_ok = True
                    for team, exp in exp_team_stats.items():
                        got = file_team_stats.get(team)
                        if got is None:
                            all_ok = False
                            break
                        if got["total_runs"] != exp["total_runs"]:
                            all_ok = False
                            break
                        if got["completed_runs"] != exp["completed_runs"]:
                            all_ok = False
                            break
                        if not _nearly_equal(float(got["completion_rate"]), float(exp["completion_rate"]), 0.001):
                            all_ok = False
                            break
                        if not _nearly_equal(float(got["avg_time_min"]), float(exp["avg_time_min"]), 0.02):
                            all_ok = False
                            break
                        if not _nearly_equal(float(got["median_time_min"]), float(exp["median_time_min"]), 0.02):
                            all_ok = False
                            break
                        if not _nearly_equal(float(got["avg_pace_min_per_km"]), float(exp["avg_pace_min_per_km"]), 0.02):
                            all_ok = False
                            break
                    if all_ok:
                        scores["stats_summary_values_correct"] = 1.0
            except Exception:
                pass

    chk = _load_json(checkpoint_json_path) if checkpoint_json_path.exists() else None
    if chk is not None and isinstance(chk, dict):
        structure_ok = True
        if "overall" not in chk or not isinstance(chk["overall"], dict):
            structure_ok = False
        else:
            overall = chk["overall"]
            if "completion_rate" not in overall or "avg_time_min" not in overall:
                structure_ok = False
        if structure_ok:
            scores["checkpoint_stats_structure_correct"] = 1.0

        if clean_rows is not None:
            expected = _compute_expected_from_runs(clean_rows)
            exp_total_runs = expected["total_runs"]  # type: ignore
            exp_drops: Dict[str, int] = expected["drops"]  # type: ignore
            exp_overall_comp_rate = expected["overall_completion_rate"]  # type: ignore
            exp_overall_avg_time = expected["overall_avg_time_min"]  # type: ignore
            try:
                got_overall = chk.get("overall", {})
                got_comp = float(got_overall.get("completion_rate"))
                got_avg_time = float(got_overall.get("avg_time_min"))
                exp_comp_rounded = round(float(exp_overall_comp_rate), 3) if not math.isnan(float(exp_overall_comp_rate)) else float("nan")
                exp_time_rounded = round(float(exp_overall_avg_time), 2) if not math.isnan(float(exp_overall_avg_time)) else float("nan")
                values_ok = _nearly_equal(got_comp, exp_comp_rounded, 0.0005) and _nearly_equal(got_avg_time, exp_time_rounded, 0.005)
                drops_ok = True
                for cp_idx, drops_count in exp_drops.items():
                    node = chk.get(str(cp_idx))
                    if not isinstance(node, dict):
                        drops_ok = False
                        break
                    got_drops = node.get("drops")
                    got_total = node.get("total_runs")
                    got_rate = node.get("failure_rate")
                    try:
                        got_drops = int(got_drops)
                        got_total = int(got_total)
                        got_rate = float(got_rate)
                    except Exception:
                        drops_ok = False
                        break
                    if got_drops != drops_count:
                        drops_ok = False
                        break
                    if got_total != exp_total_runs:
                        drops_ok = False
                        break
                    exp_rate = round(drops_count / exp_total_runs, 3) if exp_total_runs > 0 else float("nan")
                    if not _nearly_equal(got_rate, exp_rate, 0.0005):
                        drops_ok = False
                        break
                if values_ok and drops_ok:
                    scores["checkpoint_stats_values_correct"] = 1.0
            except Exception:
                pass

    log_text = _read_text(run_log_path) if run_log_path.exists() else None
    if log_text is not None:
        sections = _split_run_log_sections(log_text)
        valid_sec = sections.get("valid", "")
        malformed_sec = sections.get("malformed", "")

        if valid_sec:
            has_input_path = _section_contains_input_path(valid_sec, "input/logs/nav_runs.csv")
            exit_code = _extract_exit_code(valid_sec)
            if has_input_path and exit_code == 0:
                scores["run_log_valid_section_present_with_success_exit"] = 1.0

        if malformed_sec:
            has_input_path_bad = _section_contains_input_path(malformed_sec, "input/logs/nav_runs_bad.csv")
            exit_code_bad = _extract_exit_code(malformed_sec)
            if has_input_path_bad and (exit_code_bad is not None) and (exit_code_bad != 0):
                scores["run_log_malformed_section_present_with_failure_exit"] = 1.0

            if re.search(r"row\s*[:#]?\s*\d+.*?(team|distance_km|time_min)", malformed_sec, flags=re.IGNORECASE | re.DOTALL):
                scores["run_log_malformed_includes_error_detail"] = 1.0

    notes_text = _read_text(notes_md_path) if notes_md_path.exists() else None
    if notes_text is not None:
        obj_sec = _parse_markdown_section(notes_text, "Objective:")
        kf_sec = _parse_markdown_section(notes_text, "Key Findings:")
        issues_sec = _parse_markdown_section(notes_text, "Issues Observed:")
        action_sec = _parse_markdown_section(notes_text, "Action Items:")

        if obj_sec or kf_sec or issues_sec or action_sec:
            has_all = True
            for h in ("Objective:", "Key Findings:", "Issues Observed:", "Action Items:"):
                if h.lower() not in [ln.strip().lower() for ln in notes_text.splitlines()]:
                    has_all = False
                    break
            if has_all:
                scores["briefing_notes_sections_present"] = 1.0

        kf_bullets = _extract_bullet_lines(kf_sec)
        if len(kf_bullets) >= 3:
            scores["briefing_key_findings_has_3_bullets"] = 1.0

        referenced = 0.0
        if checkpoint_json_path.exists():
            chk_json = _load_json(checkpoint_json_path)
            if isinstance(chk_json, dict):
                overall = chk_json.get("overall", {})
                comp = overall.get("completion_rate")
                avg_t = overall.get("avg_time_min")
                overall_strings = set()
                try:
                    comp_f = float(comp)
                    avg_t_f = float(avg_t)
                    overall_strings.update({
                        f"{comp_f}",
                        f"{comp_f:.3f}",
                        f"{comp_f:.2f}",
                        f"{round(comp_f,3)}",
                        f"{avg_t_f}",
                        f"{avg_t_f:.2f}",
                        f"{avg_t_f:.3f}",
                        f"{round(avg_t_f,2)}",
                    })
                except Exception:
                    pass

                team_number_bullets = 0
                for b in kf_bullets:
                    if re.search(r"\b(Alpha|Bravo|Charlie)\b", b) and re.search(r"\d", b):
                        team_number_bullets += 1
                has_overall_number = any(any(s in b for s in overall_strings) for b in kf_bullets) if overall_strings else False

                if team_number_bullets >= 1 and has_overall_number:
                    referenced = 1.0
        scores["briefing_key_findings_references_outputs"] = referenced

        issues_ok = 0.0
        if log_text is not None:
            sections = _split_run_log_sections(log_text)
            malformed_sec = sections.get("malformed", "")
            malformed_lines = [ln for ln in malformed_sec.splitlines() if re.search(r"row\s*[:#]?\s*\d+.*?(team|distance_km|time_min)", ln, flags=re.IGNORECASE)]
            issues_text = "\n".join(issues_sec)
            found_quote = False
            for ln in malformed_lines:
                if ln.strip() and ln.strip() in issues_text:
                    found_quote = True
                    break
            explains = bool(re.search(r"row\s*\d+.*?(team|distance_km|time_min)", issues_text, flags=re.IGNORECASE))
            suggestion = bool(re.search(r"(suggest|harden|validate|validation|guard|improve|checklist|error handling)", issues_text, flags=re.IGNORECASE))
            if (found_quote or explains) and suggestion:
                issues_ok = 1.0
        scores["briefing_issues_quotes_error_and_explains"] = issues_ok

        action_bullets = _extract_bullet_lines(action_sec)
        if 3 <= len(action_bullets) <= 5:
            all_with_owner_due = all(("Owner:" in b and "Due:" in b) for b in action_bullets)
            if all_with_owner_due:
                scores["briefing_action_items_3_to_5_with_owner_due"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()