import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _parse_number_scalar(s: str) -> Any:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except Exception:
            pass
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            return float(s)
        except Exception:
            pass
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


def _load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader for the specific constraints.yaml structure.
    Supports:
      - top-level simple key: scalar
      - nested mapping with consistent indentation (spaces)
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
            indent += 2
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val == "":
            new_map: Dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent, new_map))
        else:
            current[key] = _parse_number_scalar(val)
    return root


def _parse_tracks_csv(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: Dict[str, Dict[str, Any]] = {}
            for row in reader:
                try:
                    track_id = row["track_id"].strip()
                    record = {
                        "track_id": track_id,
                        "title": row["title"].strip(),
                        "artist": row["artist"].strip(),
                        "year": int(row["year"]),
                        "genre": row["genre"].strip(),
                        "bpm": int(row["bpm"]),
                        "duration_sec": int(row["duration_sec"]),
                        "energy": int(row["energy"]),
                    }
                    records[track_id] = record
                except Exception:
                    return None
            return records
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _compute_setlist_metrics(items: List[Dict[str, Any]], constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    n = len(items)
    total_duration_sec = sum(int(item.get("duration_sec", 0)) for item in items)
    total_duration_min_rounded = int(round(total_duration_sec / 60.0)) if n > 0 else 0
    avg_bpm = round(sum(float(item.get("bpm", 0)) for item in items) / n, 1) if n > 0 else 0.0
    house_track_count = sum(1 for item in items if str(item.get("genre", "")).lower() == "house")
    house_share = (house_track_count / n) if n > 0 else 0.0

    early_range_start = None
    early_range_end = None
    if constraints and isinstance(constraints.get("early_2000s_pop_year_range"), dict):
        early_range_start = constraints["early_2000s_pop_year_range"].get("start")
        early_range_end = constraints["early_2000s_pop_year_range"].get("end")

    def is_early2000_pop(it: Dict[str, Any]) -> bool:
        if str(it.get("genre", "")).lower() != "pop":
            return False
        y = int(it.get("year", 0))
        if early_range_start is None or early_range_end is None:
            return False
        return int(early_range_start) <= y <= int(early_range_end)

    early2000s_pop_count = sum(1 for it in items if is_early2000_pop(it))

    max_adjacent_bpm_diff = 0.0
    max_adjacent_energy_diff = 0
    max_genre_streak_observed = 0
    if n > 0:
        current_genre = str(items[0].get("genre", "")).lower()
        current_streak = 1
        max_genre_streak_observed = 1
        for i in range(1, n):
            g = str(items[i].get("genre", "")).lower()
            if g == current_genre:
                current_streak += 1
            else:
                current_genre = g
                current_streak = 1
            if current_streak > max_genre_streak_observed:
                max_genre_streak_observed = current_streak
        for i in range(1, n):
            try:
                d_bpm = abs(float(items[i]["bpm"]) - float(items[i - 1]["bpm"]))
                if d_bpm > max_adjacent_bpm_diff:
                    max_adjacent_bpm_diff = d_bpm
            except Exception:
                pass
            try:
                d_energy = abs(int(items[i]["energy"]) - int(items[i - 1]["energy"]))
                if d_energy > max_adjacent_energy_diff:
                    max_adjacent_energy_diff = d_energy
            except Exception:
                pass
    start_energy = int(items[0].get("energy", 0)) if n > 0 else None
    end_energy = int(items[-1].get("energy", 0)) if n > 0 else None

    return {
        "total_duration_sec": int(total_duration_sec),
        "total_duration_min_rounded": int(total_duration_min_rounded),
        "avg_bpm": float(avg_bpm),
        "house_track_count": int(house_track_count),
        "house_share": float(house_share),
        "early2000s_pop_count": int(early2000s_pop_count),
        "max_genre_streak_observed": int(max_genre_streak_observed),
        "max_adjacent_bpm_diff_observed": float(max_adjacent_bpm_diff),
        "max_adjacent_energy_diff_observed": int(max_adjacent_energy_diff),
        "start_energy": start_energy if start_energy is not None else None,
        "end_energy": end_energy if end_energy is not None else None,
    }


def _check_setlist_matches_catalog(items: List[Dict[str, Any]], catalog: Dict[str, Dict[str, Any]]) -> bool:
    seen_ids = set()
    for it in items:
        tid = it.get("track_id")
        if not isinstance(tid, str):
            return False
        if tid in seen_ids:
            return False
        seen_ids.add(tid)
        cat = catalog.get(tid)
        if not cat:
            return False
        for field in ["title", "artist", "year", "genre", "bpm", "duration_sec", "energy"]:
            if field not in it:
                return False
            v_set = it[field]
            v_cat = cat[field]
            try:
                if field in ("year", "bpm", "duration_sec", "energy"):
                    if int(v_set) != int(v_cat):
                        return False
                else:
                    if str(v_set) != str(v_cat):
                        return False
            except Exception:
                return False
    return True


def _check_positions_and_cumulative(items: List[Dict[str, Any]]) -> bool:
    cum = 0
    for idx, it in enumerate(items, start=1):
        try:
            pos = int(it.get("position"))
            dur = int(it.get("duration_sec"))
            cum += dur
            cum_field = int(it.get("cumulative_duration_sec"))
        except Exception:
            return False
        if pos != idx:
            return False
        if cum_field != cum:
            return False
    return True


def _extract_overall_validation_line(report_text: str) -> Optional[str]:
    for line in report_text.splitlines():
        if re.fullmatch(r"\s*VALIDATION:\s+(PASS|FAIL)\s*", line):
            return line.strip()
    return None


def _count_per_constraint_pass_fail_lines(report_text: str, overall_line: Optional[str]) -> int:
    count = 0
    for line in report_text.splitlines():
        s = line.strip()
        if not s:
            continue
        if overall_line and s == overall_line:
            continue
        if re.search(r"\b(PASS|FAIL)\b", s):
            count += 1
    return count


def _email_first_paragraph(text: str) -> str:
    parts = re.split(r"\n\s*\n", text.strip(), maxsplit=1)
    return parts[0] if parts else ""


def _contains_all(text: str, substrings: List[str]) -> bool:
    t = text.lower()
    return all(sub.lower() in t for sub in substrings)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "setlist_json_valid": 0.0,
        "setlist_items_match_catalog": 0.0,
        "setlist_positions_and_cumulative_valid": 0.0,
        "metrics_json_valid": 0.0,
        "metrics_consistent_with_setlist": 0.0,
        "constraint_duration_range_satisfied": 0.0,
        "constraint_house_share_satisfied": 0.0,
        "constraint_early2000s_pop_count_satisfied": 0.0,
        "constraint_genre_streak_satisfied": 0.0,
        "constraint_adjacent_bpm_diff_satisfied": 0.0,
        "constraint_adjacent_energy_diff_satisfied": 0.0,
        "constraint_start_energy_satisfied": 0.0,
        "constraint_end_energy_satisfied": 0.0,
        "validation_overall_status_present": 0.0,
        "validation_overall_matches_computed": 0.0,
        "validation_per_constraint_summary_present": 0.0,
        "last_validation_command_recorded": 0.0,
        "email_overview_and_paths_and_status": 0.0,
        "email_metrics_listed_and_consistent": 0.0,
        "meeting_notes_sections_and_bullets": 0.0,
        "meeting_notes_metrics_consistent": 0.0,
        "meeting_notes_action_items_sufficient": 0.0,
    }

    tracks_csv = workspace / "input" / "tracks.csv"
    constraints_yaml = workspace / "input" / "constraints.yaml"
    setlist_json_path = workspace / "outputs" / "setlist.json"
    metrics_json_path = workspace / "outputs" / "metrics.json"
    validation_report_path = workspace / "outputs" / "validation_report.md"
    last_validation_cmd_path = workspace / "outputs" / "last_validation_command.txt"
    email_path = workspace / "outputs" / "email_to_editor.txt"
    meeting_notes_path = workspace / "outputs" / "meeting_notes.md"

    catalog = _parse_tracks_csv(tracks_csv)
    constraints = _load_simple_yaml(constraints_yaml)

    setlist_data = _load_json(setlist_json_path)
    metrics_data = _load_json(metrics_json_path)
    validation_report_text = _read_text(validation_report_path)
    last_validation_cmd_text = _read_text(last_validation_cmd_path)
    email_text = _read_text(email_path)
    meeting_notes_text = _read_text(meeting_notes_path)

    items: List[Dict[str, Any]] = []
    if isinstance(setlist_data, list) and len(setlist_data) > 0:
        required_fields = [
            "track_id",
            "title",
            "artist",
            "year",
            "genre",
            "bpm",
            "duration_sec",
            "energy",
            "position",
            "cumulative_duration_sec",
        ]
        ok = True
        for it in setlist_data:
            if not isinstance(it, dict):
                ok = False
                break
            for f in required_fields:
                if f not in it:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            items = setlist_data  # type: ignore
            scores["setlist_json_valid"] = 1.0
        else:
            scores["setlist_json_valid"] = 0.0
    else:
        scores["setlist_json_valid"] = 0.0

    if items and isinstance(catalog, dict):
        if _check_setlist_matches_catalog(items, catalog):
            scores["setlist_items_match_catalog"] = 1.0

    if items:
        if _check_positions_and_cumulative(items):
            scores["setlist_positions_and_cumulative_valid"] = 1.0

    if isinstance(metrics_data, dict) and metrics_data:
        required_metrics = [
            "total_duration_sec",
            "total_duration_min_rounded",
            "avg_bpm",
            "house_track_count",
            "house_share",
            "early2000s_pop_count",
            "max_genre_streak_observed",
            "max_adjacent_bpm_diff_observed",
            "max_adjacent_energy_diff_observed",
            "start_energy",
            "end_energy",
        ]
        if all(k in metrics_data for k in required_metrics):
            scores["metrics_json_valid"] = 1.0

    if items and isinstance(constraints, dict) and isinstance(metrics_data, dict):
        computed = _compute_setlist_metrics(items, constraints)
        consistent = True
        for k in [
            "total_duration_sec",
            "total_duration_min_rounded",
            "house_track_count",
            "early2000s_pop_count",
            "max_genre_streak_observed",
            "max_adjacent_energy_diff_observed",
        ]:
            if k in metrics_data:
                try:
                    if int(metrics_data[k]) != int(computed[k]):  # type: ignore
                        consistent = False
                except Exception:
                    consistent = False
            else:
                consistent = False
        for k in ["avg_bpm", "house_share", "max_adjacent_bpm_diff_observed"]:
            if k in metrics_data:
                try:
                    if not _approx_equal(float(metrics_data[k]), float(computed[k])):  # type: ignore
                        consistent = False
                except Exception:
                    consistent = False
            else:
                consistent = False
        for k in ["start_energy", "end_energy"]:
            if k in metrics_data:
                try:
                    if (metrics_data[k] is None) != (computed[k] is None):
                        consistent = False
                    elif metrics_data[k] is not None and int(metrics_data[k]) != int(computed[k]):  # type: ignore
                        consistent = False
                except Exception:
                    consistent = False
            else:
                consistent = False
        if consistent:
            scores["metrics_consistent_with_setlist"] = 1.0

    if items and isinstance(constraints, dict):
        dm_min = constraints.get("duration_minutes_min")
        dm_max = constraints.get("duration_minutes_max")
        min_house_share = constraints.get("min_house_share")
        min_early_pop = constraints.get("min_early2000s_pop_count")
        max_same_genre_streak = constraints.get("max_same_genre_streak")
        max_adj_bpm = constraints.get("max_adjacent_bpm_diff")
        max_adj_energy = constraints.get("max_adjacent_energy_diff")
        start_energy_max = constraints.get("start_energy_max")
        end_energy_min = constraints.get("end_energy_min")

        computed = _compute_setlist_metrics(items, constraints)

        if isinstance(dm_min, (int, float)) and isinstance(dm_max, (int, float)):
            total_minutes = computed["total_duration_sec"] / 60.0
            if (total_minutes >= float(dm_min)) and (total_minutes <= float(dm_max)):
                scores["constraint_duration_range_satisfied"] = 1.0

        if isinstance(min_house_share, (int, float)):
            if computed["house_share"] >= float(min_house_share):
                scores["constraint_house_share_satisfied"] = 1.0

        if isinstance(min_early_pop, (int, float)):
            if computed["early2000s_pop_count"] >= int(min_early_pop):
                scores["constraint_early2000s_pop_count_satisfied"] = 1.0

        if isinstance(max_same_genre_streak, (int, float)):
            if computed["max_genre_streak_observed"] <= int(max_same_genre_streak):
                scores["constraint_genre_streak_satisfied"] = 1.0

        if isinstance(max_adj_bpm, (int, float)):
            if computed["max_adjacent_bpm_diff_observed"] <= float(max_adj_bpm) + 1e-9:
                scores["constraint_adjacent_bpm_diff_satisfied"] = 1.0

        if isinstance(max_adj_energy, (int, float)):
            if computed["max_adjacent_energy_diff_observed"] <= int(max_adj_energy):
                scores["constraint_adjacent_energy_diff_satisfied"] = 1.0

        if isinstance(start_energy_max, (int, float)):
            start_energy = computed["start_energy"]
            if start_energy is not None and int(start_energy) <= int(start_energy_max):
                scores["constraint_start_energy_satisfied"] = 1.0

        if isinstance(end_energy_min, (int, float)):
            end_energy = computed["end_energy"]
            if end_energy is not None and int(end_energy) >= int(end_energy_min):
                scores["constraint_end_energy_satisfied"] = 1.0

    overall_line = None
    if isinstance(validation_report_text, str):
        overall_line = _extract_overall_validation_line(validation_report_text)
        if overall_line:
            scores["validation_overall_status_present"] = 1.0
        per_constraint_lines = _count_per_constraint_pass_fail_lines(validation_report_text, overall_line)
        if per_constraint_lines >= 8:
            scores["validation_per_constraint_summary_present"] = 1.0

    if overall_line is not None and items and isinstance(constraints, dict):
        all_constraints = [
            scores["constraint_duration_range_satisfied"],
            scores["constraint_house_share_satisfied"],
            scores["constraint_early2000s_pop_count_satisfied"],
            scores["constraint_genre_streak_satisfied"],
            scores["constraint_adjacent_bpm_diff_satisfied"],
            scores["constraint_adjacent_energy_diff_satisfied"],
            scores["constraint_start_energy_satisfied"],
            scores["constraint_end_energy_satisfied"],
        ]
        all_ok = all(val >= 1.0 for val in all_constraints)
        expected = "VALIDATION: PASS" if all_ok else "VALIDATION: FAIL"
        if overall_line.strip() == expected:
            scores["validation_overall_matches_computed"] = 1.0

    if isinstance(last_validation_cmd_text, str):
        cmd = last_validation_cmd_text.strip()
        if cmd:
            scores["last_validation_command_recorded"] = 1.0

    if isinstance(email_text, str) and isinstance(validation_report_text, str) and isinstance(metrics_data, dict):
        ok_overview = False
        first_para = _email_first_paragraph(email_text)
        # Require tying house flow to early-2000s pop, and mention of BPM and energy
        if first_para and _contains_all(first_para, ["house", "pop", "2000"]) and _contains_all(email_text, ["bpm", "energy"]):
            ok_overview = True

        overall_line_in_report = _extract_overall_validation_line(validation_report_text)
        has_overall_line_in_email = False
        if overall_line_in_report and overall_line_in_report in email_text:
            has_overall_line_in_email = True

        has_paths = ("outputs/setlist.json" in email_text) and ("outputs/metrics.json" in email_text)

        if ok_overview and has_overall_line_in_email and has_paths:
            scores["email_overview_and_paths_and_status"] = 1.0

        needed_keys = ["total_duration_min_rounded", "house_track_count", "early2000s_pop_count", "avg_bpm"]
        if all(k in metrics_data for k in needed_keys):
            m_ok = True
            for k in needed_keys:
                val = metrics_data[k]
                if isinstance(val, float):
                    if k == "avg_bpm":
                        val_str = f"{float(val):.1f}"
                    else:
                        val_str = str(val)
                else:
                    val_str = str(val)
                if val_str not in email_text:
                    m_ok = False
                    break
            if m_ok:
                scores["email_metrics_listed_and_consistent"] = 1.0

    if isinstance(meeting_notes_text, str) and isinstance(metrics_data, dict):
        text = meeting_notes_text
        sections = {
            "Agenda": [],
            "Decisions": [],
            "Discussion Points": [],
            "Action Items": [],
        }
        current_section = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            matched_header = False
            for sec in list(sections.keys()):
                if re.fullmatch(fr"(?i){re.escape(sec)}:?", stripped):
                    current_section = sec
                    matched_header = True
                    break
            if matched_header:
                continue
            if current_section is not None and re.match(r"^(\-|\*|•)\s+", stripped):
                sections[current_section].append(stripped)

        has_all_sections = all(len(sections[sec]) >= 1 for sec in sections.keys())
        if has_all_sections:
            scores["meeting_notes_sections_and_bullets"] = 1.0

        needed_keys_notes = ["total_duration_min_rounded", "avg_bpm", "house_share", "early2000s_pop_count"]
        m_ok = True
        for k in needed_keys_notes:
            if k not in metrics_data:
                m_ok = False
                break
            val = metrics_data[k]
            if isinstance(val, float):
                val_candidates = {str(val), f"{val:.2f}", f"{val:.1f}"}
            else:
                val_candidates = {str(val)}
            if not any(candidate in text for candidate in val_candidates):
                m_ok = False
                break
        if m_ok:
            scores["meeting_notes_metrics_consistent"] = 1.0

        action_bullets = sections.get("Action Items", [])
        if len(action_bullets) >= 3:
            keywords = ["setlist", "track", "house", "pop", "transition", "license", "licence", "licens", "poll"]
            contextual_count = 0
            for b in action_bullets:
                if any(kw in b.lower() for kw in keywords):
                    contextual_count += 1
            if contextual_count >= 2:
                scores["meeting_notes_action_items_sufficient"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()