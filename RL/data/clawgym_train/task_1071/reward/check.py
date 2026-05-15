import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _write_debug(msg: str) -> None:
    # Placeholder for potential debugging; intentionally does nothing in final grader.
    return


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _nearly_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def _nearly_equal_relaxed(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _compute_team_totals(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    # Aggregates across quarters
    numeric_cols = ["FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB", "TOV", "PF", "PTS"]
    totals: Dict[str, Dict[str, float]] = {}
    for r in rows:
        team = r.get("team", "").strip()
        if not team:
            continue
        if team not in totals:
            totals[team] = {k: 0.0 for k in numeric_cols}
        for k in numeric_cols:
            try:
                totals[team][k] += float(r.get(k, "0") or 0)
            except Exception:
                totals[team][k] += 0.0
    return totals


def _compute_quarter_points(rows: List[Dict[str, str]]) -> Dict[str, List[int]]:
    # Returns team -> [Q1, Q2, Q3, Q4] points
    per_team_quarters: Dict[str, Dict[str, int]] = {}
    for r in rows:
        team = r.get("team", "").strip()
        q = str(r.get("quarter", "")).strip()
        pts = r.get("PTS", "")
        try:
            pts_val = int(pts)
        except Exception:
            continue
        if team not in per_team_quarters:
            per_team_quarters[team] = {}
        per_team_quarters[team][q] = pts_val
    result: Dict[str, List[int]] = {}
    for team, qmap in per_team_quarters.items():
        try:
            result[team] = [qmap.get(str(i), None) for i in range(1, 5)]
            if any(v is None for v in result[team]):
                # If missing any quarter, drop team from result
                del result[team]
            else:
                # Convert to int list (already ints)
                result[team] = [int(v) for v in result[team]]
        except Exception:
            continue
    return result


def _compute_expected_metrics(rows: List[Dict[str, str]]) -> Tuple[List[str], Dict[str, Dict[str, float]]]:
    totals = _compute_team_totals(rows)
    expected: Dict[str, Dict[str, float]] = {}
    teams = sorted(totals.keys())
    for team in teams:
        t = totals[team]
        total_pts = t["PTS"]
        total_fgm = t["FGM"]
        total_fga = t["FGA"]
        total_3pm = t["3PM"]
        total_3pa = t["3PA"]
        total_ftm = t["FTM"]
        total_fta = t["FTA"]
        oreb = t["OREB"]
        dreb = t["DREB"]
        tov = t["TOV"]

        est_possessions = total_fga + 0.44 * total_fta - oreb + tov
        efg_pct = (total_fgm + 0.5 * total_3pm) / total_fga if total_fga != 0 else 0.0
        ts_den = 2 * (total_fga + 0.44 * total_fta)
        ts_pct = (total_pts / ts_den) if ts_den != 0 else 0.0

        expected[team] = {
            "total_pts": float(total_pts),
            "total_fgm": float(total_fgm),
            "total_fga": float(total_fga),
            "total_3pm": float(total_3pm),
            "total_3pa": float(total_3pa),
            "total_ftm": float(total_ftm),
            "total_fta": float(total_fta),
            "oreb": float(oreb),
            "dreb": float(dreb),
            "tov": float(tov),
            "est_possessions": est_possessions,
            "efg_pct": efg_pct,
            "ts_pct": ts_pct,
        }
    return teams, expected


def _parse_metrics_csv(path: Path) -> Tuple[bool, List[str], Dict[str, Dict[str, str]], List[str]]:
    """
    Returns (ok, columns, by_team_row, team_order)
    by_team_row maps team -> raw string values for each column.
    """
    rows = _read_csv_dicts(path)
    if rows is None:
        return False, [], {}, []
    columns = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            columns = next(reader)
    except Exception:
        return False, [], {}, []
    by_team: Dict[str, Dict[str, str]] = {}
    order: List[str] = []
    for r in rows:
        team = (r.get("team") or "").strip()
        if not team:
            continue
        order.append(team)
        by_team[team] = r
    return True, columns, by_team, order


def _extract_section_ranges(text: str, section_names: List[str]) -> Dict[str, Tuple[int, int]]:
    """
    Find sections by exact title line (case-insensitive) with optional leading hashes and optional trailing colon.
    Returns mapping from normalized section name to (start_index, end_index) line indices (content only, excluding header).
    """
    lines = text.splitlines()
    headers: Dict[str, int] = {}
    normalized_map = {name.lower(): name for name in section_names}
    for i, raw in enumerate(lines):
        line = raw.strip()
        # Strip leading markdown hashes
        line_clean = line.lstrip("#").strip()
        line_clean_no_colon = line_clean[:-1] if line_clean.endswith(":") else line_clean
        key = line_clean_no_colon.lower()
        if key in normalized_map:
            headers[normalized_map[key]] = i
    ranges: Dict[str, Tuple[int, int]] = {}
    # Determine end boundaries by next header occurrence
    header_positions = sorted([(i, name) for name, i in headers.items()])
    total_lines = len(lines)
    for idx, (i, name) in enumerate(header_positions):
        start = i + 1
        end = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else total_lines
        ranges[name] = (start, end)
    return ranges


def _word_count(text: str) -> int:
    # Count words by splitting on whitespace and punctuation boundaries
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)


def _find_numbers(text: str) -> List[str]:
    # Extract numbers including percentages and decimals; returns as found (string)
    # Patterns: integers, decimals, percentages like 51.2%
    pattern = r"(?<![\w])([0-9]+(?:\.[0-9]+)?%?)(?![\w])"
    return re.findall(pattern, text)


def _parse_key_numbers_section(text: str) -> List[str]:
    # Return bullet lines in Key Numbers section
    lines = [ln.strip() for ln in text.splitlines()]
    bullets = [ln for ln in lines if ln.startswith(("-", "*", "•"))]
    return bullets


def _numbers_in_line(line: str) -> List[float]:
    nums = []
    for tok in _find_numbers(line):
        if tok.endswith("%"):
            try:
                nums.append(float(tok[:-1]))  # percentage numeric part
            except Exception:
                continue
        else:
            try:
                nums.append(float(tok))
            except Exception:
                continue
    return nums


def _has_value_with_possible_formats(value: float, nums: List[float], tol: float = 1e-2) -> bool:
    # Accept either raw value (rounded to 3 dec typical) or percent value *100 (rounded as presented)
    for n in nums:
        if _nearly_equal_relaxed(n, value, tol=tol):
            return True
        if _nearly_equal_relaxed(n, value * 100.0, tol=0.1):  # accept percent within 0.1
            return True
    return False


def _get_team_names_from_input(rows: List[Dict[str, str]]) -> List[str]:
    names = []
    for r in rows:
        t = (r.get("team") or "").strip()
        if t and t not in names:
            names.append(t)
    return names


def _get_action_items_from_transcript(text: str) -> List[Dict[str, str]]:
    """
    Extract explicit actions as in the transcript under 'Action:' bullets:
    Expects lines like: '- Alex to file the gamer ... by 2026-04-15 22:35 ET.'
    Returns list of dicts with owner and due (string).
    """
    lines = text.splitlines()
    in_action = False
    items: List[Dict[str, str]] = []
    for raw in lines:
        line = raw.strip()
        clean = line.lstrip("#").strip()
        if clean.lower().startswith("action"):
            in_action = True
            continue
        if in_action:
            if not line:
                continue
            if any(clean.lower().startswith(h) for h in ["decisions", "notes", "open question", "open questions"]):
                in_action = False
                continue
            if line.startswith("-"):
                # Try to extract owner and due date
                # Owner: first word before 'to '
                m_owner = re.match(r"-\s*([A-Za-z]+)\s+to\s+", line)
                owner = m_owner.group(1) if m_owner else ""
                m_due = re.search(r"by\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+ET)", line)
                due = m_due.group(1) if m_due else ""
                items.append({"owner": owner, "due": due, "line": line})
    return items


def _extract_section_text(text: str, start: int, end: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[start:end])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_file_exists": 0.0,
        "metrics_csv_columns_and_order": 0.0,
        "metrics_csv_two_rows_one_per_team": 0.0,
        "metrics_totals_correct": 0.0,
        "metrics_advanced_correct": 0.0,
        "metrics_rounding_3decimals_for_advanced": 0.0,
        "metrics_no_extra_columns": 0.0,
        "recap_exists": 0.0,
        "recap_word_count_300_400": 0.0,
        "recap_sections_present": 0.0,
        "recap_key_numbers_matches_metrics": 0.0,
        "recap_includes_pace_correct": 0.0,
        "recap_quarter_scoring_matches_input": 0.0,
        "recap_methodology_formulas_and_aggregation": 0.0,
        "recap_focus_narrative_themes": 0.0,
        "pitch_email_exists": 0.0,
        "pitch_email_subject_line_present": 0.0,
        "pitch_email_bullets_count_2_to_3": 0.0,
        "pitch_email_word_count_leq_120": 0.0,
        "pitch_email_mentions_both_teams": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_actions_with_owner_due_present": 0.0,
        "meeting_notes_open_question_present": 0.0,
    }

    # Paths
    input_stats_path = workspace / "input" / "team_quarter_stats.csv"
    metrics_path = workspace / "outputs" / "metrics_summary.csv"
    recap_path = workspace / "outputs" / "game_recap.md"
    pitch_path = workspace / "outputs" / "pitch_email.txt"
    notes_path = workspace / "outputs" / "meeting_notes.md"
    transcript_path = workspace / "input" / "editor_meeting_transcript.md"

    # Load input stats
    input_rows = _read_csv_dicts(input_stats_path) or []
    input_ok = bool(input_rows)

    # Compute expected metrics if possible
    teams_in_input: List[str] = []
    expected_metrics: Dict[str, Dict[str, float]] = {}
    expected_quarter_pts: Dict[str, List[int]] = {}
    if input_ok:
        teams_in_input = _get_team_names_from_input(input_rows)
        _, expected_metrics = _compute_expected_metrics(input_rows)
        expected_quarter_pts = _compute_quarter_points(input_rows)

    # 1) metrics_summary.csv checks
    if metrics_path.exists():
        scores["metrics_file_exists"] = 1.0
        ok, cols, by_team_row, team_order = _parse_metrics_csv(metrics_path)
        required_cols = [
            "team",
            "total_pts",
            "total_fgm",
            "total_fga",
            "total_3pm",
            "total_3pa",
            "total_ftm",
            "total_fta",
            "oreb",
            "dreb",
            "tov",
            "est_possessions",
            "efg_pct",
            "ts_pct",
        ]
        if ok:
            # columns and order
            if cols == required_cols:
                scores["metrics_csv_columns_and_order"] = 1.0
            # no extra columns
            if cols == required_cols:
                scores["metrics_no_extra_columns"] = 1.0
            # two rows and team names match input (if input available)
            if len(by_team_row) == 2:
                if not teams_in_input or sorted(by_team_row.keys()) == sorted(teams_in_input):
                    scores["metrics_csv_two_rows_one_per_team"] = 1.0

            # Totals correctness and advanced metrics correctness
            totals_ok = True
            adv_ok = True
            rounding_ok = True
            if input_ok:
                for team in expected_metrics:
                    row = by_team_row.get(team)
                    if not row:
                        totals_ok = False
                        adv_ok = False
                        rounding_ok = False
                        break
                    try:
                        # Totals
                        for k in [
                            "total_pts",
                            "total_fgm",
                            "total_fga",
                            "total_3pm",
                            "total_3pa",
                            "total_ftm",
                            "total_fta",
                            "oreb",
                            "dreb",
                            "tov",
                        ]:
                            v = _safe_float(row.get(k, ""))
                            if v is None or not _nearly_equal(v, expected_metrics[team][k], tol=1e-6):
                                totals_ok = False
                        # Advanced metrics (rounded to 3 decimals required)
                        for k in ["est_possessions", "efg_pct", "ts_pct"]:
                            v_str = row.get(k, "")
                            v = _safe_float(v_str)
                            if v is None:
                                adv_ok = False
                                rounding_ok = False
                                continue
                            # Check numeric value equals rounded to 3 decimals of expected
                            exp = round(expected_metrics[team][k] + 1e-12, 3)
                            if not _nearly_equal(v, exp, tol=1e-3):
                                adv_ok = False
                            # Check string has 3 decimal places
                            if "." in v_str:
                                frac = v_str.split(".", 1)[1]
                                if len(frac) != 3:
                                    rounding_ok = False
                            else:
                                rounding_ok = False
                    except Exception:
                        totals_ok = False
                        adv_ok = False
                        rounding_ok = False
                if totals_ok:
                    scores["metrics_totals_correct"] = 1.0
                if adv_ok:
                    scores["metrics_advanced_correct"] = 1.0
                if rounding_ok:
                    scores["metrics_rounding_3decimals_for_advanced"] = 1.0
            else:
                # If input missing, we cannot verify content; keep as 0.0
                pass
    else:
        # metrics file missing; keep default 0.0s for metrics checks
        pass

    # 2) game_recap.md checks
    recap_text = _read_text(recap_path)
    metrics_ok_for_recap = False
    if recap_text is not None:
        scores["recap_exists"] = 1.0
        wc = _word_count(recap_text)
        if 300 <= wc <= 400:
            scores["recap_word_count_300_400"] = 1.0

        # Sections present
        sections = ["Headline", "Key Numbers", "Quarter-by-quarter scoring", "Methodology"]
        section_ranges = _extract_section_ranges(recap_text, sections)
        if all(name in section_ranges for name in sections):
            scores["recap_sections_present"] = 1.0

        # Key Numbers parse and consistency with metrics_summary.csv
        ok_metrics_file, cols, metrics_by_team_row, team_order = _parse_metrics_csv(metrics_path) if metrics_path.exists() else (False, [], {}, [])
        if "Key Numbers" in section_ranges:
            kn_text = _extract_section_text(recap_text, *section_ranges["Key Numbers"])
            bullets = _parse_key_numbers_section(kn_text)
            if ok_metrics_file and metrics_by_team_row:
                # Check for each team: presence of eFG, TS, possessions numbers matching metrics file
                per_team_ok = True
                # Compute pace from metrics file
                try:
                    if len(metrics_by_team_row) == 2:
                        vals = []
                        for team, row in metrics_by_team_row.items():
                            est_pos = _safe_float(row.get("est_possessions", ""))
                            if est_pos is None:
                                raise ValueError
                            vals.append(est_pos)
                        pace_val = sum(vals) / 2.0
                    else:
                        pace_val = None
                except Exception:
                    pace_val = None

                for team, row in metrics_by_team_row.items():
                    efg = _safe_float(row.get("efg_pct", ""))
                    ts = _safe_float(row.get("ts_pct", ""))
                    estp = _safe_float(row.get("est_possessions", ""))
                    if efg is None or ts is None or estp is None:
                        per_team_ok = False
                        break
                    # find bullet lines related to team
                    rel_lines = [b for b in bullets if team in b]
                    # Require presence of labels in adjacent context
                    has_efg = False
                    has_ts = False
                    has_estp = False
                    for ln in rel_lines:
                        nums = _numbers_in_line(ln)
                        if re.search(r"\befg\b", ln, flags=re.I) or "eFG" in ln:
                            if _has_value_with_possible_formats(efg, nums, tol=1e-2):
                                has_efg = True
                        if re.search(r"\bts\b", ln, flags=re.I) or re.search(r"true\s+shoot", ln, flags=re.I):
                            if _has_value_with_possible_formats(ts, nums, tol=1e-2):
                                has_ts = True
                        if re.search(r"possess", ln, flags=re.I):
                            if any(_nearly_equal_relaxed(n, estp, tol=0.1) for n in nums):
                                has_estp = True
                    if not (has_efg and has_ts and has_estp):
                        per_team_ok = False
                        break

                if per_team_ok:
                    scores["recap_key_numbers_matches_metrics"] = 1.0

                # Check pace number present and correct
                pace_ok = False
                if pace_val is not None:
                    # Find any bullet line mentioning pace
                    pace_lines = [b for b in bullets if re.search(r"\bpace\b", b, flags=re.I)]
                    for ln in pace_lines:
                        nums = _numbers_in_line(ln)
                        if any(_nearly_equal_relaxed(n, pace_val, tol=0.1) for n in nums):
                            pace_ok = True
                            break
                if pace_ok:
                    scores["recap_includes_pace_correct"] = 1.0

        # Quarter-by-quarter scoring check
        if "Quarter-by-quarter scoring" in section_ranges and input_ok:
            qtext = _extract_section_text(recap_text, *section_ranges["Quarter-by-quarter scoring"])
            # For each team from input, find a line mentioning team with Q1..Q4 numbers
            q_ok = True
            for team, qpts in expected_quarter_pts.items():
                # find a line containing team and Q1..Q4 labels
                lines = [ln.strip() for ln in qtext.splitlines() if team in ln]
                found = False
                for ln in lines:
                    if all(lbl in ln for lbl in ["Q1", "Q2", "Q3", "Q4"]):
                        nums = [int(n) for n in re.findall(r"\b(\d+)\b", ln)]
                        # There might be other numbers; attempt to map to Q1..Q4 by order
                        # Extract after each Q label if possible
                        m_q1 = re.search(r"Q1[^0-9]*(\d+)", ln)
                        m_q2 = re.search(r"Q2[^0-9]*(\d+)", ln)
                        m_q3 = re.search(r"Q3[^0-9]*(\d+)", ln)
                        m_q4 = re.search(r"Q4[^0-9]*(\d+)", ln)
                        if m_q1 and m_q2 and m_q3 and m_q4:
                            vals = [int(m_q1.group(1)), int(m_q2.group(1)), int(m_q3.group(1)), int(m_q4.group(1))]
                            if vals == qpts:
                                found = True
                                break
                if not found:
                    q_ok = False
                    break
            if q_ok:
                scores["recap_quarter_scoring_matches_input"] = 1.0

        # Methodology section: 2–3 sentences stating formulas and data source aggregation
        if "Methodology" in section_ranges:
            mtext = _extract_section_text(recap_text, *section_ranges["Methodology"]).strip()
            # Count sentences
            sentences = [s.strip() for s in re.split(r"[.!?]\s+", mtext) if s.strip()]
            if 2 <= len(sentences) <= 3:
                # Check mentions of formulas and aggregation
                has_poss = bool(re.search(r"(estimated\s+possessions|est_possessions)", mtext, re.I)) and ("0.44" in mtext)
                has_efg = bool(re.search(r"\befg\b|effective\s+field\s+goal", mtext, re.I))
                has_ts = bool(re.search(r"\bts\b|true\s+shoot", mtext, re.I))
                has_agg = bool(re.search(r"(aggregat|sum|mined from|derived from|from the per-quarter file|per-?quarter)", mtext, re.I))
                if has_poss and has_efg and has_ts and has_agg:
                    scores["recap_methodology_formulas_and_aggregation"] = 1.0

        # Narrative focus keywords
        text_lower = recap_text.lower()
        has_shot = ("shot profile" in text_lower) or ("shot" in text_lower)
        has_turnover = ("turnover" in text_lower) or ("turnovers" in text_lower)
        has_late = ("late-game" in text_lower) or ("late game" in text_lower)
        has_execution = ("execution" in text_lower) or ("executed" in text_lower)
        if has_shot and has_turnover and has_late and has_execution:
            scores["recap_focus_narrative_themes"] = 1.0

    # 3) pitch_email.txt checks
    pitch_text = _read_text(pitch_path)
    if pitch_text is not None:
        scores["pitch_email_exists"] = 1.0
        lines = pitch_text.splitlines()
        # Subject line present (line starting with 'Subject:')
        subject_present = any(ln.strip().lower().startswith("subject:") for ln in lines if ln.strip())
        if subject_present:
            scores["pitch_email_subject_line_present"] = 1.0
        # 2–3 bullet highlights (lines starting with '-', '*', or '•')
        bullet_lines = [ln for ln in lines if ln.strip().startswith(("-", "*", "•"))]
        if 2 <= len(bullet_lines) <= 3:
            scores["pitch_email_bullets_count_2_to_3"] = 1.0
        # <= 120 words
        if _word_count(pitch_text) <= 120:
            scores["pitch_email_word_count_leq_120"] = 1.0
        # Mentions both teams
        if re.search(r"rivertown", pitch_text, re.I) and re.search(r"lakeview", pitch_text, re.I):
            scores["pitch_email_mentions_both_teams"] = 1.0

    # 4) meeting_notes.md checks
    notes_text = _read_text(notes_path)
    transcript_text = _read_text(transcript_path)
    if notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
        # Sections presence
        sections_req = ["Decisions", "Action items", "Open questions"]
        ranges_notes = _extract_section_ranges(notes_text, sections_req)
        if all(name in ranges_notes for name in sections_req):
            scores["meeting_notes_sections_present"] = 1.0

        # Action items: convert explicit actions into bullets with owner and due date
        if transcript_text is not None and "Action items" in ranges_notes:
            expected_actions = _get_action_items_from_transcript(transcript_text)
            action_text = _extract_section_text(notes_text, *ranges_notes["Action items"])
            action_bullets = [ln.strip() for ln in action_text.splitlines() if ln.strip().startswith(("-", "*", "•"))]
            # For each expected action, ensure there's a bullet containing owner and due date
            all_found = True
            for item in expected_actions:
                owner = item.get("owner", "")
                due = item.get("due", "")
                if not owner or not due:
                    all_found = False
                    break
                found = False
                for bl in action_bullets:
                    if re.search(rf"\b{re.escape(owner)}\b", bl) and due in bl:
                        found = True
                        break
                if not found:
                    all_found = False
                    break
            if all_found and len(expected_actions) > 0:
                scores["meeting_notes_actions_with_owner_due_present"] = 1.0

        # Open questions content present
        if "Open questions" in ranges_notes:
            oq_text = _extract_section_text(notes_text, *ranges_notes["Open questions"])
            if "?" in oq_text:
                scores["meeting_notes_open_question_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, ensure_ascii=False))


if __name__ == "__main__":
    main()