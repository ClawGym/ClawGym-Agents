import sys
import json
import csv
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = [dict(r) for r in rdr]
            # Ensure fieldnames exist
            if rdr.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _round_half_up(value: float, ndigits: int) -> float:
    q = Decimal(str(value)).quantize(Decimal("1." + "0" * ndigits), rounding=ROUND_HALF_UP)
    return float(q)


def _format_one_decimal(value: float) -> str:
    return f"{_round_half_up(value, 1):.1f}"


def _format_two_decimals(value: float) -> str:
    return f"{_round_half_up(value, 2):.2f}"


def _median_int(values: List[int]) -> int:
    if not values:
        return 0
    v = sorted(values)
    n = len(v)
    mid = n // 2
    if n % 2 == 1:
        return int(v[mid])
    else:
        return int((v[mid - 1] + v[mid]) / 2)


def _mean_round_int(values: List[int]) -> int:
    if not values:
        return 0
    avg = sum(values) / len(values)
    # Standard half-up rounding to integer
    return int(Decimal(str(avg)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _classify_result(gf: int, ga: int) -> str:
    if gf > ga:
        return "W"
    elif gf == ga:
        return "D"
    else:
        return "L"


def _parse_matches(rows: List[Dict[str, str]]) -> Optional[List[Dict[str, object]]]:
    parsed = []
    required_cols = ["date", "opponent", "venue", "goals_for", "goals_against", "attendance"]
    # Validate header presence
    if not rows:
        return None
    for col in required_cols:
        if col not in rows[0]:
            return None
    try:
        for r in rows:
            date = r["date"].strip()
            opponent = r["opponent"].strip()
            venue = r["venue"].strip()
            gf = int(r["goals_for"])
            ga = int(r["goals_against"])
            att = int(r["attendance"])
            res = _classify_result(gf, ga)
            parsed.append({
                "date": date,
                "opponent": opponent,
                "venue": venue,
                "goals_for": gf,
                "goals_against": ga,
                "attendance": att,
                "result": res,
            })
        return parsed
    except Exception:
        return None


def _compute_summary_by_scope(matches: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    def scope_filter(scope: str):
        if scope == "overall":
            return matches
        elif scope == "home":
            return [m for m in matches if m["venue"] == "H"]
        elif scope == "away":
            return [m for m in matches if m["venue"] == "A"]
        else:
            return []

    summary = {}
    for scope in ["overall", "home", "away"]:
        ms = scope_filter(scope)
        n = len(ms)
        wins = sum(1 for m in ms if m["result"] == "W")
        draws = sum(1 for m in ms if m["result"] == "D")
        losses = sum(1 for m in ms if m["result"] == "L")
        win_rate_pct = 0.0 if n == 0 else (wins / n) * 100.0
        points = wins * 3 + draws * 1
        ppg = 0.0 if n == 0 else points / n
        gf_sum = sum(int(m["goals_for"]) for m in ms) if n > 0 else 0
        ga_sum = sum(int(m["goals_against"]) for m in ms) if n > 0 else 0
        gf_avg = 0.0 if n == 0 else gf_sum / n
        ga_avg = 0.0 if n == 0 else ga_sum / n
        gd_avg = gf_avg - ga_avg
        atts = [int(m["attendance"]) for m in ms]
        avg_att = _mean_round_int(atts) if n > 0 else 0
        med_att = _median_int(atts) if n > 0 else 0

        summary[scope] = {
            "matches": n,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "win_rate_pct": _format_one_decimal(win_rate_pct),
            "ppg": _format_two_decimals(ppg),
            "avg_goals_for": _format_two_decimals(gf_avg),
            "avg_goals_against": _format_two_decimals(ga_avg),
            "avg_goal_diff": _format_two_decimals(gd_avg),
            "avg_attendance": str(avg_att),
            "median_attendance": str(med_att),
        }
    return summary


def _load_summary_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = [dict(r) for r in rdr]
            if rdr.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _validate_summary(workspace: Path, expected: Dict[str, Dict[str, object]]) -> Tuple[float, float, float]:
    """
    Returns three scores:
    - columns check
    - scopes and counts check
    - metrics values check
    """
    target = workspace / "outputs" / "stats" / "summary_by_scope.csv"
    required_cols = [
        "scope",
        "matches",
        "wins",
        "draws",
        "losses",
        "win_rate_pct",
        "ppg",
        "avg_goals_for",
        "avg_goals_against",
        "avg_goal_diff",
        "avg_attendance",
        "median_attendance",
    ]
    rows = _load_summary_csv(target)
    if rows is None:
        return 0.0, 0.0, 0.0

    # Validate columns/header strictness by reading the first line
    try:
        with target.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
    except Exception:
        header_line = ""
    columns_ok = 1.0 if header_line == ",".join(required_cols) else 0.0

    # Check presence of exactly 3 rows and expected scopes regardless of order
    if len(rows) != 3:
        return columns_ok, 0.0, 0.0

    scopes_found = set()
    scopes_ok = True
    values_ok = True
    for r in rows:
        scope = r.get("scope", "")
        scopes_found.add(scope)
        exp = expected.get(scope)
        if exp is None:
            scopes_ok = False
            values_ok = False
            continue
        # Check integer fields as integers matching
        int_fields = ["matches", "wins", "draws", "losses", "avg_attendance", "median_attendance"]
        for fld in int_fields:
            val = r.get(fld, None)
            if val is None:
                values_ok = False
                break
            # must be integer string
            try:
                iv = int(val)
            except Exception:
                values_ok = False
                break
            if str(iv) != str(exp[fld]):
                values_ok = False
        # Check decimal formats and exact strings
        dec1_fields = ["win_rate_pct"]
        for fld in dec1_fields:
            val = r.get(fld, "")
            if not re.fullmatch(r"\d{1,3}\.\d", val):
                values_ok = False
            if val != exp[fld]:
                values_ok = False
        dec2_fields = ["ppg", "avg_goals_for", "avg_goals_against", "avg_goal_diff"]
        for fld in dec2_fields:
            val = r.get(fld, "")
            if not re.fullmatch(r"-?\d+\.\d{2}", val):
                values_ok = False
            if val != exp[fld]:
                values_ok = False

    scopes_ok = scopes_ok and scopes_found == {"overall", "home", "away"}
    return columns_ok, (1.0 if scopes_ok else 0.0), (1.0 if values_ok else 0.0)


def _validate_top3(workspace: Path, matches: List[Dict[str, object]]) -> Tuple[float, float, float]:
    """
    Returns three scores:
    - columns check
    - rows and order check
    - results classification check
    """
    target = workspace / "outputs" / "stats" / "top3_attendance.csv"
    rows = _load_summary_csv(target)
    required_cols = ["date", "opponent", "venue", "attendance", "goals_for", "goals_against", "result"]
    if rows is None:
        return 0.0, 0.0, 0.0

    # Validate header
    try:
        with target.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
    except Exception:
        header_line = ""
    columns_ok = 1.0 if header_line == ",".join(required_cols) else 0.0

    if len(rows) != 3:
        return columns_ok, 0.0, 0.0

    # Compute expected top3 by attendance descending
    expected_sorted = sorted(matches, key=lambda m: (-int(m["attendance"]), m["date"]))
    expected_top3 = expected_sorted[:3]

    # Validate order and values
    order_ok = True
    result_ok = True
    for i, r in enumerate(rows):
        try:
            att = int(r["attendance"])
            gf = int(r["goals_for"])
            ga = int(r["goals_against"])
        except Exception:
            order_ok = False
            result_ok = False
            break
        # Check result classification
        if r.get("result") != _classify_result(gf, ga):
            result_ok = False
        exp = expected_top3[i]
        # Must match expected record values
        if not (
            r.get("date") == exp["date"]
            and r.get("opponent") == exp["opponent"]
            and r.get("venue") == exp["venue"]
            and att == int(exp["attendance"])
            and gf == int(exp["goals_for"])
            and ga == int(exp["goals_against"])
        ):
            order_ok = False

    return columns_ok, (1.0 if order_ok else 0.0), (1.0 if result_ok else 0.0)


def _find_section(text: str, title: str) -> Optional[str]:
    # Try to find markdown heading for section by title, content until next heading
    lines = text.splitlines()
    indices = []
    for i, line in enumerate(lines):
        if re.match(rf"^\s*#{1,6}\s*{re.escape(title)}\s*$", line):
            indices.append(i)
        elif re.match(rf"^\s*{re.escape(title)}\s*$", line):
            indices.append(i)
    if not indices:
        return None
    start = indices[0] + 1
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^\s*#{1,6}\s*\S+", lines[j]):
            end = j
            break
        # Also consider plain uppercase/lowercase headings lines as section separators if needed
        if re.match(r"^\s*[A-Za-z].*\s*$", lines[j]) and lines[j].strip() in {"Decisions", "Action Items", "Next Meeting"}:
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def _extract_table(section_text: str) -> Optional[List[List[str]]]:
    # Extract first markdown table in section. Expect header and separator and data rows.
    lines = [ln for ln in section_text.splitlines() if ln.strip() != ""]
    table_started = False
    table_lines = []
    for ln in lines:
        if "|" in ln:
            table_lines.append(ln.strip())
            table_started = True
        elif table_started:
            break
    if not table_lines:
        return None
    # Normalize by ensuring each line starts and ends with |
    norm = []
    for ln in table_lines:
        s = ln
        if not s.startswith("|"):
            s = "|" + s
        if not s.endswith("|"):
            s = s + "|"
        norm.append(s)
    # Split lines into cells
    rows = []
    for ln in norm:
        parts = [p.strip() for p in ln.strip().split("|")[1:-1]]
        rows.append(parts)
    # Expect at least header + separator + 1 row
    if len(rows) < 3:
        return None
    return rows


def _validate_meeting_notes(workspace: Path, summary_rows: Optional[List[Dict[str, str]]]) -> Tuple[float, float, float, float]:
    """
    Returns four scores:
    - headings and sections presence
    - decision uses percentages and correct prioritization
    - action items table validity
    - next meeting details included
    """
    path = workspace / "outputs" / "meeting_notes.md"
    txt = _read_text_safe(path)
    if txt is None:
        return 0.0, 0.0, 0.0, 0.0

    # Headings presence
    has_decisions = bool(re.search(r"^\s*#{1,6}\s*Decisions\s*$", txt, flags=re.M))
    has_actions = bool(re.search(r"^\s*#{1,6}\s*Action Items\s*$", txt, flags=re.M))
    has_next = bool(re.search(r"^\s*#{1,6}\s*Next Meeting\s*$", txt, flags=re.M))
    headings_ok = 1.0 if (has_decisions and has_actions and has_next) else 0.0

    # Decision section content and Data snapshot line
    decisions_sec = _find_section(txt, "Decisions") or ""
    data_snapshot_present = "Data snapshot" in txt
    decision_ok = False
    # Determine expected prioritization from summary_by_scope.csv
    home_pct = None
    away_pct = None
    if summary_rows:
        try:
            # Build map
            smap = {r["scope"]: r for r in summary_rows if "scope" in r}
            home_pct = smap.get("home", {}).get("win_rate_pct")
            away_pct = smap.get("away", {}).get("win_rate_pct")
        except Exception:
            home_pct = None
            away_pct = None
    if home_pct is not None and away_pct is not None:
        # Check both percentages appear in decisions or overall notes
        contains_pcts = (home_pct in txt) and (away_pct in txt)
        # Expected decision: prioritize home if home >= away else away
        exp_home_priority = float(home_pct) >= float(away_pct)
        mentions_home_watch = bool(re.search(r"\bhome watch parties\b", decisions_sec, flags=re.I))
        mentions_away_trips = bool(re.search(r"\baway trips\b", decisions_sec, flags=re.I))
        if exp_home_priority:
            priority_ok = mentions_home_watch and not mentions_away_trips
        else:
            priority_ok = mentions_away_trips and not mentions_home_watch
        decision_ok = contains_pcts and priority_ok and data_snapshot_present
    decision_score = 1.0 if decision_ok else 0.0

    # Action items table validation
    actions_sec = _find_section(txt, "Action Items") or ""
    table = _extract_table(actions_sec)
    actions_ok = False
    if table:
        header = [h.strip() for h in table[0]]
        # Expect exact header order
        if [h.lower() for h in header] == ["owner", "task", "due_date", "status"]:
            # Skip separator line (second)
            data_rows = table[2:]
            # Validate there are 4 tasks
            if len(data_rows) == 4:
                due_dates = set()
                owners = set()
                status_all_open = True
                due_date_format_ok = True
                tasks_nonempty = True
                for row in data_rows:
                    if len(row) != 4:
                        actions_ok = False
                        break
                    owner, task, due_date, status = row
                    owners.add(owner.strip())
                    if not task.strip():
                        tasks_nonempty = False
                    # due date ISO
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_date.strip()):
                        due_date_format_ok = False
                    due_dates.add(due_date.strip())
                    if status.strip().lower() != "open":
                        status_all_open = False
                if status_all_open and due_date_format_ok and tasks_nonempty:
                    # Expected due dates from input
                    exp_due = {"2025-05-12", "2025-05-07", "2025-05-20", "2025-05-06"}
                    # Expected owners include at least these names
                    actions_ok = (due_dates == exp_due) and {"Anna", "Ben", "Carl"}.issubset(owners)
    actions_score = 1.0 if actions_ok else 0.0

    # Next meeting details
    next_sec = _find_section(txt, "Next Meeting") or ""
    # Must include date/time and location found in input notes
    next_ok = all([
        "2025-05-15" in next_sec,
        "19:00" in next_sec,
        "Fanhaus" in next_sec
    ])
    next_score = 1.0 if next_ok else 0.0

    return headings_ok, decision_score, actions_score, next_score


def _validate_fan_message(workspace: Path, summary_rows: Optional[List[Dict[str, str]]], agenda_txt: Optional[str]) -> Tuple[float, float, float]:
    """
    Returns three scores:
    - length and tone (contains Aue and call-to-action hint)
    - includes required info (RSVP deadline exact string and next meeting date/time)
    - percentages sentence matches summary_by_scope.csv
    """
    path = workspace / "outputs" / "fan_message.txt"
    txt = _read_text_safe(path)
    if txt is None:
        return 0.0, 0.0, 0.0

    # Length <= 120 words
    words = re.findall(r"\b\w+\b", txt)
    length_ok = len(words) <= 120
    # Tone: supportive of Aue and clear call to action (check presence of 'Aue' and 'RSVP' or 'join')
    supportive = ("Aue" in txt) or ("Erzgebirge Aue" in txt)
    cta = ("RSVP" in txt) or ("join" in txt.lower()) or ("come" in txt.lower()) or ("support" in txt.lower())
    length_tone_score = 1.0 if (length_ok and supportive and cta) else 0.0

    # Includes required info
    # RSVP exact string
    rsvp_ok = "RSVP deadline for members: 2025-05-10" in txt
    # Next meeting date/time exact as in input: "Thursday 2025-05-15 19:00"
    next_dt_ok = "Thursday 2025-05-15 19:00" in txt
    includes_info_score = 1.0 if (rsvp_ok and next_dt_ok) else 0.0

    # Percentages sentence matches summary_by_scope.csv (one-decimal)
    pcts_ok = False
    if summary_rows:
        try:
            smap = {r["scope"]: r for r in summary_rows if "scope" in r}
            home_pct = smap.get("home", {}).get("win_rate_pct", None)
            away_pct = smap.get("away", {}).get("win_rate_pct", None)
            if home_pct is not None and away_pct is not None:
                pattern = re.escape(f"Home win rate: {home_pct}%, Away: {away_pct}%")
                pcts_ok = re.search(pattern, txt) is not None
        except Exception:
            pcts_ok = False
    percentages_score = 1.0 if pcts_ok else 0.0

    return length_tone_score, includes_info_score, percentages_score


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "summary_present_correct_columns": 0.0,
        "summary_scopes_and_counts_correct": 0.0,
        "summary_metrics_values_correct": 0.0,
        "top3_present_correct_columns": 0.0,
        "top3_correct_rows_and_order": 0.0,
        "top3_results_classification_correct": 0.0,
        "meeting_notes_headings_and_sections": 0.0,
        "meeting_notes_decision_uses_percentages": 0.0,
        "meeting_notes_action_items_table_valid": 0.0,
        "meeting_notes_next_meeting_included": 0.0,
        "fan_message_length_and_tone": 0.0,
        "fan_message_includes_required_info": 0.0,
        "fan_message_percentages_match_summary": 0.0,
    }

    # Load inputs
    matches_path = workspace / "input" / "matches.csv"
    agenda_path = workspace / "input" / "agenda_notes.txt"
    matches_rows = _read_csv_safe(matches_path)
    agenda_txt = _read_text_safe(agenda_path)

    if matches_rows is None:
        # Without inputs, we cannot validate most outputs; return zeros as initialized
        return scores

    matches = _parse_matches(matches_rows)
    if matches is None:
        return scores

    expected_summary = _compute_summary_by_scope(matches)
    # Validate summary_by_scope.csv
    sum_cols, sum_scopes, sum_vals = _validate_summary(workspace, expected_summary)
    scores["summary_present_correct_columns"] = sum_cols
    scores["summary_scopes_and_counts_correct"] = sum_scopes
    scores["summary_metrics_values_correct"] = sum_vals

    # Load summary rows for reuse (to validate percentages echoed elsewhere)
    summary_rows = _load_summary_csv(workspace / "outputs" / "stats" / "summary_by_scope.csv")

    # Validate top3 attendance
    top_cols, top_rows, top_res = _validate_top3(workspace, matches)
    scores["top3_present_correct_columns"] = top_cols
    scores["top3_correct_rows_and_order"] = top_rows
    scores["top3_results_classification_correct"] = top_res

    # Validate meeting notes
    m_head, m_decision, m_actions, m_next = _validate_meeting_notes(workspace, summary_rows)
    scores["meeting_notes_headings_and_sections"] = m_head
    scores["meeting_notes_decision_uses_percentages"] = m_decision
    scores["meeting_notes_action_items_table_valid"] = m_actions
    scores["meeting_notes_next_meeting_included"] = m_next

    # Validate fan message
    f_len_tone, f_info, f_pcts = _validate_fan_message(workspace, summary_rows, agenda_txt)
    scores["fan_message_length_and_tone"] = f_len_tone
    scores["fan_message_includes_required_info"] = f_info
    scores["fan_message_percentages_match_summary"] = f_pcts

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()