import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


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


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_training_log(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    parsed = []
    dates = set()
    for r in rows:
        try:
            date = r["date"].strip()
            athlete = r["athlete"].strip()
            distance_m = int(r["distance_m"])
            times_field = r.get("times_sec", "").strip()
            times = []
            if times_field:
                parts = [p.strip() for p in times_field.split(";") if p.strip() != ""]
                for p in parts:
                    times.append(float(p))
            parsed.append({
                "date": date,
                "athlete": athlete,
                "distance_m": distance_m,
                "times": times,
            })
            dates.add(date)
        except Exception:
            # Skip malformed rows gracefully
            continue
    return parsed, sorted(dates)


def _round2(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return round(x + 1e-12, 2)


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _format_two_dec_str(x: Optional[float]) -> Optional[str]:
    if x is None:
        return None
    return f"{x:.2f}"


def _is_two_decimal_string(s: str) -> bool:
    return bool(re.fullmatch(r"-?\d+\.\d{2}", s))


def _is_integer_string(s: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", s))


def _compute_weekly_stats(
    training: List[Dict[str, Any]],
    athletes_info: Dict[str, Dict[str, float]]
) -> Dict[str, Dict[str, Any]]:
    # Initialize structure
    athlete_dates: Dict[str, set] = {name: set() for name in athletes_info.keys()}
    all_dates = set()
    times_100: Dict[str, List[float]] = {name: [] for name in athletes_info.keys()}
    times_200: Dict[str, List[float]] = {name: [] for name in athletes_info.keys()}

    for entry in training:
        name = entry["athlete"]
        date = entry["date"]
        dist = entry["distance_m"]
        tlist = entry["times"]
        all_dates.add(date)
        if name not in athletes_info:
            # Unknown athlete; ignore for strict grading based on registered athletes.json
            continue
        if tlist:
            athlete_dates[name].add(date)
            if dist == 100:
                times_100[name].extend(tlist)
            elif dist == 200:
                times_200[name].extend(tlist)

    total_session_days = len(all_dates)

    stats: Dict[str, Dict[str, Any]] = {}
    for name, baselines in athletes_info.items():
        pb100 = baselines.get("pb_100m")
        pb200 = baselines.get("pb_200m")
        # Compute metrics
        avg100 = _mean(times_100[name])
        best100 = min(times_100[name]) if times_100[name] else None
        avg200 = _mean(times_200[name])
        best200 = min(times_200[name]) if times_200[name] else None

        avg100 = _round2(avg100) if avg100 is not None else None
        best100 = _round2(best100) if best100 is not None else None
        avg200 = _round2(avg200) if avg200 is not None else None
        best200 = _round2(best200) if best200 is not None else None
        pb100_r = _round2(pb100) if pb100 is not None else None
        pb200_r = _round2(pb200) if pb200 is not None else None

        delta100 = _round2(best100 - pb100_r) if (best100 is not None and pb100_r is not None) else None
        delta200 = _round2(best200 - pb200_r) if (best200 is not None and pb200_r is not None) else None

        perc100 = None
        perc200 = None
        if best100 is not None and pb100_r and pb100_r != 0:
            perc100 = _round2((pb100_r - best100) / pb100_r * 100.0)
        if best200 is not None and pb200_r and pb200_r != 0:
            perc200 = _round2((pb200_r - best200) / pb200_r * 100.0)

        stats[name] = {
            "athlete": name,
            "sessions_attended": len(athlete_dates[name]),
            "total_session_days": total_session_days,
            "avg_100m": avg100,
            "best_100m": best100,
            "avg_200m": avg200,
            "best_200m": best200,
            "pb_100m_baseline": pb100_r,
            "pb_200m_baseline": pb200_r,
            "delta_best_100m_vs_pb": delta100,
            "delta_best_200m_vs_pb": delta200,
            "perc_improvement_100m": perc100,
            "perc_improvement_200m": perc200,
        }
    return stats


def _parse_drafts_md(md_text: str) -> Dict[str, str]:
    # Parse sections with headings starting with '## id'
    sections: Dict[str, str] = {}
    current_id: Optional[str] = None
    current_lines: List[str] = []
    for line in md_text.splitlines():
        if re.match(r"^\s*##\s+(\S+)", line):
            # Flush previous
            if current_id is not None:
                sections[current_id] = "\n".join(current_lines).strip()
            m = re.match(r"^\s*##\s+(\S+)", line)
            current_id = m.group(1)
            current_lines = []
        else:
            current_lines.append(line)
    if current_id is not None:
        sections[current_id] = "\n".join(current_lines).strip()
    return sections


def _word_count(text: str) -> int:
    # Count words by splitting on whitespace
    if not text:
        return 0
    tokens = re.findall(r"\S+", text.strip())
    return len(tokens)


def _extract_section_by_heading(md_text: str, heading: str) -> Optional[str]:
    # Extract content under a '## heading' until next '## '
    lines = md_text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*##\s+{}".format(re.escape(heading)), ln):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find next heading
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if re.match(r"^\s*##\s+", lines[j]):
            end_idx = j
            break
    content = "\n".join(lines[start_idx:end_idx]).strip()
    return content


def _first_nonempty_line(text: str) -> Optional[str]:
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "weekly_stats_file_present_and_header": 0.0,
        "weekly_stats_row_count_and_athletes": 0.0,
        "weekly_stats_numeric_values_correct": 0.0,
        "weekly_stats_two_decimal_formatting": 0.0,
        "weekly_report_title_dates": 0.0,
        "weekly_report_team_summary_fastest_and_attendance": 0.0,
        "weekly_report_top3_improvement_ordered": 0.0,
        "weekly_report_athlete_paragraphs": 0.0,
        "rewritten_messages_file_structure": 0.0,
        "rewritten_messages_meet_notice_facts": 0.0,
        "rewritten_messages_hydration_facts": 0.0,
        "rewritten_messages_word_counts_and_limits": 0.0,
    }

    # Load inputs for expected values
    training_path = workspace / "input" / "training_log.csv"
    athletes_path = workspace / "input" / "athletes.json"
    drafts_path = workspace / "input" / "drafts.md"

    training_rows = _read_csv_dicts(training_path) or []
    training_parsed, training_dates = _parse_training_log(training_rows)

    # Expected date range
    min_date = training_dates[0] if training_dates else None
    max_date = training_dates[-1] if training_dates else None

    athletes_json = _load_json(athletes_path) or {}
    athletes_list = athletes_json.get("athletes", []) if isinstance(athletes_json, dict) else []
    athletes_info: Dict[str, Dict[str, float]] = {}
    for a in athletes_list:
        try:
            name = a["name"]
            athletes_info[name] = {
                "pb_100m": float(a["pb_100m"]),
                "pb_200m": float(a["pb_200m"]),
            }
        except Exception:
            continue

    expected_stats: Dict[str, Dict[str, Any]] = {}
    if athletes_info and training_parsed:
        expected_stats = _compute_weekly_stats(training_parsed, athletes_info)

    # Prepare expected items for report checks if possible
    fastest_100m_time = None
    fastest_100m_athlete = None
    team_attendance_rate_percent_str = None
    top3_improve_pairs: List[Tuple[str, str]] = []
    if expected_stats:
        # Fastest 100m
        min_time = None
        min_name = None
        for name, st in expected_stats.items():
            b = st["best_100m"]
            if b is not None:
                if min_time is None or b < min_time:
                    min_time = b
                    min_name = name
        if min_time is not None and min_name is not None:
            fastest_100m_time = f"{min_time:.2f}"
            fastest_100m_athlete = min_name

        # Attendance rate
        total_days = None
        if len(expected_stats) > 0:
            # total_session_days is same for all
            total_days = next(iter(expected_stats.values()))["total_session_days"]
        if total_days and total_days > 0:
            rates = []
            for st in expected_stats.values():
                rates.append(st["sessions_attended"] / total_days)
            team_attendance_rate = sum(rates) / len(rates) if rates else 0.0
            team_attendance_rate_percent_str = f"{round(team_attendance_rate*100.0 + 1e-12, 1):.1f}%"

        # Top 3 improvement 100m
        improvs = []
        for name, st in expected_stats.items():
            val = st.get("perc_improvement_100m")
            if val is not None:
                improvs.append((name, val))
        improvs.sort(key=lambda x: (-x[1], x[0]))
        for name, val in improvs[:3]:
            top3_improve_pairs.append((name, f"{val:.2f}%"))

    # Check weekly_stats.csv
    weekly_stats_path = workspace / "output" / "weekly_stats.csv"
    weekly_stats_rows = _read_csv_dicts(weekly_stats_path)
    required_header = [
        "athlete",
        "sessions_attended",
        "total_session_days",
        "avg_100m",
        "best_100m",
        "avg_200m",
        "best_200m",
        "pb_100m_baseline",
        "pb_200m_baseline",
        "delta_best_100m_vs_pb",
        "delta_best_200m_vs_pb",
        "perc_improvement_100m",
        "perc_improvement_200m",
    ]
    if weekly_stats_rows is not None:
        # Header check
        try:
            with weekly_stats_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
            if header == required_header:
                scores["weekly_stats_file_present_and_header"] = 1.0
        except Exception:
            pass

        # Row count and athletes check
        try:
            out_names = [r.get("athlete", "").strip() for r in weekly_stats_rows]
            expected_names = sorted(list(athletes_info.keys()))
            if out_names and sorted(out_names) == expected_names and len(out_names) == len(expected_names):
                scores["weekly_stats_row_count_and_athletes"] = 1.0
        except Exception:
            pass

        # Numeric values and formatting checks
        values_ok = True
        formatting_ok = True
        if expected_stats and weekly_stats_rows:
            # Build dict by athlete
            out_by_name = {r.get("athlete", "").strip(): r for r in weekly_stats_rows}
            for name, exp in expected_stats.items():
                r = out_by_name.get(name)
                if not r:
                    values_ok = False
                    formatting_ok = False
                    break
                # Check integers
                try:
                    sa_str = r["sessions_attended"].strip()
                    tsd_str = r["total_session_days"].strip()
                    if not (_is_integer_string(sa_str) and _is_integer_string(tsd_str)):
                        values_ok = False
                    else:
                        if int(sa_str) != exp["sessions_attended"] or int(tsd_str) != exp["total_session_days"]:
                            values_ok = False
                except Exception:
                    values_ok = False

                # Times and percentages fields
                time_fields = [
                    "avg_100m",
                    "best_100m",
                    "avg_200m",
                    "best_200m",
                    "pb_100m_baseline",
                    "pb_200m_baseline",
                    "delta_best_100m_vs_pb",
                    "delta_best_200m_vs_pb",
                ]
                perc_fields = [
                    "perc_improvement_100m",
                    "perc_improvement_200m",
                ]

                for fld in time_fields:
                    try:
                        s = r[fld].strip()
                        if not _is_two_decimal_string(s):
                            formatting_ok = False
                        val = float(s)
                        exp_val = exp[fld]
                        # Compare within 0.005 tolerance
                        if exp_val is None or abs(val - float(exp_val)) > 0.005:
                            values_ok = False
                    except Exception:
                        values_ok = False
                        formatting_ok = False
                for fld in perc_fields:
                    try:
                        s = r[fld].strip()
                        if not _is_two_decimal_string(s):
                            formatting_ok = False
                        val = float(s)
                        exp_val = exp[fld]
                        if exp_val is None or abs(val - float(exp_val)) > 0.005:
                            values_ok = False
                    except Exception:
                        values_ok = False
                        formatting_ok = False
        else:
            values_ok = False
            formatting_ok = False

        if values_ok:
            scores["weekly_stats_numeric_values_correct"] = 1.0
        if formatting_ok:
            scores["weekly_stats_two_decimal_formatting"] = 1.0

    # Check weekly_report.md
    report_path = workspace / "output" / "weekly_report.md"
    report_text = _read_text(report_path)
    if report_text is not None and min_date and max_date:
        # Title check
        first_line = _first_nonempty_line(report_text)
        expected_title = f"U18 sprints weekly report ({min_date} to {max_date})"
        if first_line == expected_title:
            scores["weekly_report_title_dates"] = 1.0

        # Team Summary checks
        team_summary = _extract_section_by_heading(report_text, "Team Summary")
        athlete_summaries = _extract_section_by_heading(report_text, "Athlete Summaries")

        # If headings are not present, sections may be None
        team_ok = False
        top3_ok = False
        athlete_par_ok = False

        if team_summary is not None and fastest_100m_time and fastest_100m_athlete and team_attendance_rate_percent_str and top3_improve_pairs:
            ts = team_summary
            # Fastest 100m & athlete
            has_fastest = (fastest_100m_time in ts) and (fastest_100m_athlete in ts)
            # Attendance rate
            has_attendance = team_attendance_rate_percent_str in ts
            # Top 3 improvements and ordering
            # Ensure name and percentage pairs appear and in order
            indices = []
            ordered_ok = True
            for name, perc_str in top3_improve_pairs:
                # Find earliest occurrence of pattern "<name>" and "<perc_str>" in order within team_summary
                # For strictness, we check combined pair occurrence by locating first occurrence of name then percentage after
                name_idx = ts.find(name)
                perc_idx = ts.find(perc_str, name_idx + 1 if name_idx >= 0 else 0)
                if name_idx == -1 or perc_idx == -1:
                    ordered_ok = False
                    break
                indices.append((name_idx, perc_idx))
            # Check ordering by the position of names (or percentage)
            if ordered_ok:
                positions = [i[0] for i in indices]
                ordered_ok = all(positions[i] < positions[i+1] for i in range(len(positions)-1))
            team_ok = has_fastest and has_attendance
            top3_ok = ordered_ok

        # Athlete summaries
        if athlete_summaries is not None and expected_stats:
            # Split into paragraphs (blocks separated by blank lines)
            paras = [p.strip() for p in re.split(r"\n\s*\n", athlete_summaries) if p.strip()]
            per_athlete_ok = True
            for name, st in expected_stats.items():
                # find a paragraph with the athlete's name
                para_match = None
                for p in paras:
                    if name in p:
                        para_match = p
                        break
                if not para_match:
                    per_athlete_ok = False
                    break
                sessions_str = f"{st['sessions_attended']}/{st['total_session_days']}"
                best100_str = f"{st['best_100m']:.2f}" if st['best_100m'] is not None else None
                best200_str = f"{st['best_200m']:.2f}" if st['best_200m'] is not None else None
                if sessions_str not in para_match:
                    per_athlete_ok = False
                    break
                if best100_str is None or best100_str not in para_match:
                    per_athlete_ok = False
                    break
                if best200_str is None or best200_str not in para_match:
                    per_athlete_ok = False
                    break
            athlete_par_ok = per_athlete_ok

        if team_ok:
            scores["weekly_report_team_summary_fastest_and_attendance"] = 1.0
        if top3_ok:
            scores["weekly_report_top3_improvement_ordered"] = 1.0
        if athlete_par_ok:
            scores["weekly_report_athlete_paragraphs"] = 1.0

    # Check rewritten_messages.json
    rewritten_path = workspace / "output" / "rewritten_messages.json"
    rewritten_json = _load_json(rewritten_path)
    drafts_text = _read_text(drafts_path) or ""
    drafts_sections = _parse_drafts_md(drafts_text) if drafts_text else {}

    structure_ok = False
    meet_notice_ok = False
    hydration_ok = False
    word_counts_ok = False

    if isinstance(rewritten_json, list) and drafts_sections:
        # Convert to dict by id
        by_id = {}
        valid_structure = True
        for item in rewritten_json:
            if not isinstance(item, dict):
                valid_structure = False
                break
            if not all(k in item for k in ["id", "original_word_count", "rewritten_text", "rewritten_word_count"]):
                valid_structure = False
                break
            _id = item["id"]
            if _id in by_id:
                valid_structure = False
                break
            by_id[_id] = item
        # Require both ids present
        required_ids = set(drafts_sections.keys())
        if valid_structure and {"meet_notice", "hydration_note"}.issubset(set(by_id.keys())):
            structure_ok = True

        # Word counts and limits
        wc_ok = True
        for _id, item in by_id.items():
            orig_text = drafts_sections.get(_id, "")
            orig_wc_expected = _word_count(orig_text)
            # Validate original_word_count matches expected
            try:
                orig_wc_reported = int(item["original_word_count"])
            except Exception:
                wc_ok = False
                break
            if orig_wc_expected != orig_wc_reported:
                wc_ok = False
                break
            # Validate rewritten_word_count and limits
            rewritten_text = item.get("rewritten_text", "")
            rwc_expected = _word_count(rewritten_text)
            try:
                rwc_reported = int(item["rewritten_word_count"])
            except Exception:
                wc_ok = False
                break
            if rwc_reported != rwc_expected:
                wc_ok = False
                break
            # Constraints
            if not (rwc_reported < orig_wc_reported and rwc_reported <= 120):
                wc_ok = False
                break
        if wc_ok and structure_ok:
            word_counts_ok = True

        # meet_notice facts
        if "meet_notice" in by_id:
            text = by_id["meet_notice"].get("rewritten_text", "")
            required_phrases = [
                "Western Province League Meet",
                "Green Point Athletics Stadium",
                "2026-04-27",
                "08:15",
                "09:00",
                "2026-04-23 17:00",
                "SA ID or birth certificate",
                "team kit",
                "spikes",
                "water bottle",
                "sunscreen",
                "Transport not provided",
            ]
            meet_notice_ok = all(p in text for p in required_phrases)

        # hydration_note facts
        if "hydration_note" in by_id:
            text = by_id["hydration_note"].get("rewritten_text", "")
            has_daily = "2–3 litres per day" in text  # en dash
            has_between = "500 ml water between warm-up and first heat" in text
            has_avoid = "avoid energy drinks on race day" in text
            # electrolytes phrase: accept exact suggested phrase or presence of both fragments
            has_electrolytes_full = "include electrolytes if training or competing in the sun for more than 60 minutes" in text
            has_electrolytes_frag = ("include electrolytes" in text and "more than 60 minutes" in text)
            hydration_ok = has_daily and has_between and has_avoid and (has_electrolytes_full or has_electrolytes_frag)

    if structure_ok:
        scores["rewritten_messages_file_structure"] = 1.0
    if meet_notice_ok:
        scores["rewritten_messages_meet_notice_facts"] = 1.0
    if hydration_ok:
        scores["rewritten_messages_hydration_facts"] = 1.0
    if word_counts_ok:
        scores["rewritten_messages_word_counts_and_limits"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()