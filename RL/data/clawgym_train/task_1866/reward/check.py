import json
import sys
import csv
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        # Ensure header exists
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _fmt2(x: Optional[float]) -> Optional[str]:
    if x is None:
        return None
    try:
        return f"{round(x + 0.0, 2):.2f}"
    except Exception:
        return None


def _compute_metrics(workspace: Path) -> Optional[Dict[str, object]]:
    # Load required CSVs
    p2021 = workspace / "input" / "credit_survey_2021.csv"
    p2022 = workspace / "input" / "credit_survey_2022.csv"
    pprog = workspace / "input" / "program_participation_2022.csv"
    pineq = workspace / "input" / "inequality_metrics.csv"

    rows2021 = _read_csv_rows(p2021)
    rows2022 = _read_csv_rows(p2022)
    rowsprog = _read_csv_rows(pprog)
    rowsineq = _read_csv_rows(pineq)

    if any(r is None for r in [rows2021, rows2022, rowsprog, rowsineq]):
        return None

    # Extract literacy scores
    scores2021: List[float] = []
    for r in rows2021:
        val = _safe_float(r.get("literacy_score", ""))
        if val is None:
            return None
        scores2021.append(val)

    scores2022: List[float] = []
    for r in rows2022:
        val = _safe_float(r.get("literacy_score", ""))
        if val is None:
            return None
        scores2022.append(val)

    mean2021 = _mean(scores2021)
    mean2022 = _mean(scores2022)
    if mean2021 is None or mean2022 is None:
        return None
    yoy = mean2022 - mean2021

    # Quartile means 2022
    quartile_scores: Dict[int, List[float]] = {1: [], 2: [], 3: [], 4: []}
    for r in rows2022:
        qraw = r.get("income_quartile", "")
        try:
            q = int(qraw)
        except Exception:
            return None
        if q not in quartile_scores:
            return None
        val = _safe_float(r.get("literacy_score", ""))
        if val is None:
            return None
        quartile_scores[q].append(val)

    quartile_means: Dict[int, float] = {}
    for q in [1, 2, 3, 4]:
        if not quartile_scores[q]:
            return None
        m = _mean(quartile_scores[q])
        if m is None:
            return None
        quartile_means[q] = m

    # Join with program participation
    participation: Dict[str, int] = {}
    for r in rowsprog:
        rid = r.get("respondent_id", "")
        try:
            flag = int(r.get("participated", ""))
        except Exception:
            return None
        participation[str(rid)] = flag

    part_scores: List[float] = []
    nonpart_scores: List[float] = []
    for r in rows2022:
        rid = str(r.get("respondent_id", ""))
        if rid not in participation:
            return None
        score = _safe_float(r.get("literacy_score", ""))
        if score is None:
            return None
        if participation[rid] == 1:
            part_scores.append(score)
        else:
            nonpart_scores.append(score)
    if not part_scores or not nonpart_scores:
        return None
    mean_part = _mean(part_scores)
    mean_non = _mean(nonpart_scores)
    if mean_part is None or mean_non is None:
        return None
    part_diff = mean_part - mean_non

    # Inequality metrics: Gini for 2022
    gini_2022: Optional[float] = None
    for r in rowsineq:
        yr = r.get("year", "")
        if str(yr) == "2022":
            g = _safe_float(r.get("gini_coefficient", ""))
            if g is None:
                return None
            gini_2022 = g
            break
    if gini_2022 is None:
        return None

    return {
        "mean_2021": mean2021,
        "mean_2022": mean2022,
        "yoy": yoy,
        "quartile_means": quartile_means,  # int->float
        "mean_participants": mean_part,
        "mean_nonparticipants": mean_non,
        "participants_diff": part_diff,
        "gini_2022": gini_2022,
        "formatted": {
            "mean_2021": _fmt2(mean2021),
            "mean_2022": _fmt2(mean2022),
            "yoy": _fmt2(yoy),
            "quartile_1": _fmt2(quartile_means[1]),
            "quartile_2": _fmt2(quartile_means[2]),
            "quartile_3": _fmt2(quartile_means[3]),
            "quartile_4": _fmt2(quartile_means[4]),
            "mean_participants": _fmt2(mean_part),
            "mean_nonparticipants": _fmt2(mean_non),
            "participants_diff": _fmt2(part_diff),
            "gini_2022": _fmt2(gini_2022),
        },
    }


def _find_section_ranges(text: str, titles_in_order: List[str]) -> Optional[Dict[str, Tuple[int, int]]]:
    positions: Dict[str, int] = {}
    start_idx = 0
    for title in titles_in_order:
        idx = text.find(title, start_idx)
        if idx == -1:
            return None
        positions[title] = idx
        start_idx = idx + 1
    # Build ranges
    ranges: Dict[str, Tuple[int, int]] = {}
    for i, title in enumerate(titles_in_order):
        s = positions[title]
        if i + 1 < len(titles_in_order):
            e = positions[titles_in_order[i + 1]]
        else:
            e = len(text)
        ranges[title] = (s, e)
    return ranges


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "weekly_update_sections_order": 0.0,
        "weekly_update_key_metrics_numbers": 0.0,
        "weekly_update_yoy_section_numbers": 0.0,
        "weekly_update_program_impact_numbers": 0.0,
        "weekly_update_gini_in_context": 0.0,
        "weekly_update_data_sources_paths_listed": 0.0,
        "grant_summary_placeholders_replaced_and_values_correct": 0.0,
        "email_draft_fields_and_metrics_present": 0.0,
        "cron_schedule_valid": 0.0,
        "runner_script_executable_and_log_exists": 0.0,
    }

    # Compute expected metrics
    metrics = _compute_metrics(workspace)
    # Paths for outputs
    p_weekly = workspace / "output" / "weekly_update.md"
    p_grant_updated = workspace / "output" / "grant_summary_updated.md"
    p_email = workspace / "output" / "email_draft_to_team.txt"
    p_cron = workspace / "output" / "schedule" / "weekly_finlit.cron"
    p_runner = workspace / "scripts" / "run_weekly_update.sh"
    p_log = workspace / "output" / "logs" / "weekly_run.log"

    # Weekly update checks
    weekly_text = _read_text(p_weekly)
    section_titles = [
        "Overview",
        "Key Metrics",
        "Year-over-year change",
        "Program impact snapshot",
        "Inequality context",
        "Data sources",
    ]
    if weekly_text is not None:
        ranges = _find_section_ranges(weekly_text, section_titles)
        if ranges is not None:
            scores["weekly_update_sections_order"] = 1.0

            # Only proceed if metrics available
            if metrics is not None:
                f = metrics["formatted"]
                # Key Metrics section must include quartiles and overall mean
                key_sec = weekly_text[ranges["Key Metrics"][0]:ranges["Key Metrics"][1]]
                need_key = [
                    f["quartile_1"],
                    f["quartile_2"],
                    f["quartile_3"],
                    f["quartile_4"],
                    f["mean_2022"],
                ]
                if all(val is not None and val in key_sec for val in need_key):
                    scores["weekly_update_key_metrics_numbers"] = 1.0

                # Year-over-year change section: 2021 mean and difference
                yoy_sec = weekly_text[ranges["Year-over-year change"][0]:ranges["Year-over-year change"][1]]
                need_yoy = [
                    f["mean_2021"],
                    f["yoy"],
                ]
                if all(val is not None and val in yoy_sec for val in need_yoy):
                    scores["weekly_update_yoy_section_numbers"] = 1.0

                # Program impact snapshot: participants, non-participants means and difference
                prog_sec = weekly_text[ranges["Program impact snapshot"][0]:ranges["Program impact snapshot"][1]]
                need_prog = [
                    f["mean_participants"],
                    f["mean_nonparticipants"],
                    f["participants_diff"],
                ]
                if all(val is not None and val in prog_sec for val in need_prog):
                    scores["weekly_update_program_impact_numbers"] = 1.0

                # Inequality context: gini
                ineq_sec = weekly_text[ranges["Inequality context"][0]:ranges["Inequality context"][1]]
                if f["gini_2022"] is not None and f["gini_2022"] in ineq_sec:
                    scores["weekly_update_gini_in_context"] = 1.0

            # Data sources: list input files by path
            data_sec = weekly_text[ranges["Data sources"][0]:ranges["Data sources"][1]]
            required_paths = [
                "input/credit_survey_2021.csv",
                "input/credit_survey_2022.csv",
                "input/program_participation_2022.csv",
                "input/inequality_metrics.csv",
                "input/grant_summary_draft.md",
            ]
            if all(p in data_sec for p in required_paths):
                scores["weekly_update_data_sources_paths_listed"] = 1.0

    # Grant summary updated checks
    grant_text = _read_text(p_grant_updated)
    if grant_text is not None and metrics is not None:
        f = metrics["formatted"]
        placeholders_present = ("{{" in grant_text) or ("}}" in grant_text)
        needed_vals = [
            "2022",
            f["mean_2022"],
            f["yoy"],
            f["gini_2022"],
            f["participants_diff"],
        ]
        if (not placeholders_present) and all(val is not None and val in grant_text for val in needed_vals):
            scores["grant_summary_placeholders_replaced_and_values_correct"] = 1.0

    # Email draft checks
    email_text = _read_text(p_email)
    if email_text is not None and metrics is not None:
        f = metrics["formatted"]
        # To field
        to_ok = "To: research-team@example.edu" in email_text
        # Subject
        subj_match = False
        for line in email_text.splitlines():
            if line.strip().lower().startswith("subject:"):
                if "weekly automated update — financial literacy and inequality" in line.strip().lower():
                    subj_match = True
                break
        # Numbers required in body (anywhere in file)
        nums_needed = [
            f["mean_2022"],
            f["yoy"],
            f["quartile_1"],
            f["quartile_2"],
            f["quartile_3"],
            f["quartile_4"],
            f["mean_participants"],
            f["mean_nonparticipants"],
            f["participants_diff"],
            f["gini_2022"],
        ]
        nums_ok = all(val is not None and val in email_text for val in nums_needed)
        # Mentions of regenerated files
        regen_ok = ("output/weekly_update.md" in email_text) and ("output/grant_summary_updated.md" in email_text)
        if to_ok and subj_match and nums_ok and regen_ok:
            scores["email_draft_fields_and_metrics_present"] = 1.0

    # Cron schedule checks
    cron_text = _read_text(p_cron)
    if cron_text is not None:
        # Consider non-empty lines only
        lines = [ln for ln in cron_text.splitlines() if ln.strip() != ""]
        if len(lines) == 1:
            line = lines[0].strip()
            parts = re.split(r"\s+", line, maxsplit=5)
            if len(parts) >= 6:
                minute, hour, dom, month, dow = parts[0], parts[1], parts[2], parts[3], parts[4]
                cmd = parts[5]
                minute_ok = minute == "15"
                hour_ok = hour in {"7", "07"}
                dom_ok = dom == "*"
                month_ok = month == "*"
                dow_ok = dow == "1"
                cmd_has_runner = "scripts/run_weekly_update.sh" in cmd
                cmd_has_redirect = (">>" in cmd) and ("output/logs/weekly_run.log" in cmd) and ("2>&1" in cmd)
                redirect_order_ok = ("scripts/run_weekly_update.sh" in cmd) and (cmd.find(">>") < cmd.find("output/logs/weekly_run.log") < cmd.find("2>&1") if ("2>&1" in cmd and "output/logs/weekly_run.log" in cmd and ">>" in cmd) else False)
                if minute_ok and hour_ok and dom_ok and month_ok and dow_ok and cmd_has_runner and cmd_has_redirect and redirect_order_ok:
                    scores["cron_schedule_valid"] = 1.0

    # Runner script and log checks
    runner_ok = False
    log_ok = False
    try:
        if p_runner.exists() and os.access(str(p_runner), os.X_OK):
            runner_ok = True
    except Exception:
        runner_ok = False
    log_text = _read_text(p_log) if p_log.exists() else None
    if log_text is not None and len(log_text.strip()) > 0:
        # Check it indicates completion (case-insensitive)
        if re.search(r"completed", log_text, re.IGNORECASE):
            log_ok = True
    if runner_ok and log_ok:
        scores["runner_script_executable_and_log_exists"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()