import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _safe_parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _safe_parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _load_baby_log_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    rows = []
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                d = _safe_parse_date((r.get("date") or "").strip())
                feeds = _safe_parse_int((r.get("feeds") or "").strip())
                oz = _safe_parse_int((r.get("oz") or "").strip())
                sleep_hours = _safe_parse_float((r.get("sleep_hours") or "").strip())
                if d is None or feeds is None or oz is None or sleep_hours is None:
                    return None
                rows.append(
                    {
                        "date": d.date(),
                        "feeds": feeds,
                        "oz": oz,
                        "sleep_hours": sleep_hours,
                        "notes": (r.get("notes") or "").strip(),
                    }
                )
    except Exception:
        return None
    return rows


def _monday_of_week(date_obj: datetime.date) -> datetime.date:
    # Monday is 0
    delta = date_obj.weekday()
    return date_obj - timedelta(days=delta)


def _round1(x: float) -> float:
    # Round to one decimal as per task
    return round(x + 1e-12, 1)


def _compute_expected_week_metrics(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Group by Monday-starting week
    groups: Dict[datetime.date, List[Dict[str, Any]]] = {}
    for r in rows:
        ws = _monday_of_week(r["date"])
        groups.setdefault(ws, []).append(r)
    expected = []
    # Sort weeks by week_start ascending
    for ws in sorted(groups.keys()):
        days = groups[ws]
        n = len(days)
        sum_feeds = sum(d["feeds"] for d in days)
        sum_oz = sum(d["oz"] for d in days)
        sum_sleep = sum(d["sleep_hours"] for d in days)
        avg_feeds = _round1(sum_feeds / n) if n > 0 else 0.0
        avg_oz = _round1(sum_oz / n) if n > 0 else 0.0
        avg_sleep = _round1(sum_sleep / n) if n > 0 else 0.0
        # anomalies per day
        anomalies_map: Dict[str, List[str]] = {}
        for d in days:
            reasons = []
            if d["oz"] < 18:
                reasons.append("low_oz")
            if d["sleep_hours"] < 12:
                reasons.append("low_sleep")
            if reasons:
                anomalies_map[d["date"].isoformat()] = reasons
        anomalies = [{"date": k, "reasons": v} for k, v in sorted(anomalies_map.items())]
        expected.append(
            {
                "week_start": ws.isoformat(),
                "days": n,
                "avg_feeds_per_day": avg_feeds,
                "avg_oz_per_day": avg_oz,
                "avg_sleep_hours_per_day": avg_sleep,
                "anomalies": anomalies,
            }
        )
    return expected


def _load_required_sections_from_checklist(path: Path) -> Optional[List[str]]:
    if not path.exists():
        return None
    try:
        sections = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*-\s*(.+?)\s*$", line)
                if m:
                    sections.append(m.group(1).strip())
        return sections if sections else None
    except Exception:
        return None


def _extract_markdown_sections(md_text: str) -> Dict[str, str]:
    # Map headings to content until next heading
    sections: Dict[str, str] = {}
    lines = md_text.splitlines()
    current_name = None
    buffer: List[str] = []
    heading_re = re.compile(r"^\s*#+\s*(.+?)\s*$")
    for line in lines:
        m = heading_re.match(line)
        if m:
            # save previous section
            if current_name is not None:
                sections[current_name] = "\n".join(buffer).strip()
            current_name = m.group(1).strip()
            buffer = []
        else:
            if current_name is not None:
                buffer.append(line)
    if current_name is not None:
        sections[current_name] = "\n".join(buffer).strip()
    return sections


def _find_data_highlights_checks(section_text: str, expected_weeks: List[Dict[str, Any]]) -> bool:
    # Verify that for each week we see week_start, avg oz and avg sleep numbers, and anomaly dates
    if not section_text:
        return False
    ok = True
    for wk in expected_weeks:
        ws = wk["week_start"]
        if ws not in section_text:
            ok = False
            break
        # Check avg numbers presence as one-decimal strings
        oz_str = f"{wk['avg_oz_per_day']:.1f}"
        sleep_str = f"{wk['avg_sleep_hours_per_day']:.1f}"
        if oz_str not in section_text or sleep_str not in section_text:
            ok = False
            break
        # Check anomaly dates are mentioned
        for an in wk["anomalies"]:
            if an["date"] not in section_text:
                ok = False
                break
        if not ok:
            break
    # Also ensure metrics reference literal somewhere in Data Highlights as requested preferable location
    if "output/metrics.json" not in section_text:
        # They might include it elsewhere, but preference is here; we do not fail solely on this
        pass
    return ok


def _count_bullets(text: str) -> int:
    if not text:
        return 0
    cnt = 0
    for line in text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            cnt += 1
    return cnt


def _parse_validator_log_summary(log_text: str) -> Optional[Dict[str, int]]:
    if not log_text:
        return None
    # Find the last SUMMARY line
    summaries = re.findall(r"SUMMARY:\s*passes=(\d+),\s*fails=(\d+)", log_text)
    if not summaries:
        return None
    last = summaries[-1]
    try:
        passes = int(last[0])
        fails = int(last[1])
        return {"passes": passes, "fails": fails}
    except Exception:
        return None


def _extract_validation_summary_from_report(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    # Find passes and fails numbers as in "passes=X, fails=Y"
    m = re.search(r"passes\s*=\s*(\d+)\s*,\s*fails\s*=\s*(\d+)", text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        passes = int(m.group(1))
        fails = int(m.group(2))
    except Exception:
        return None
    # Find "Validator exit code: X" exact line
    m2 = re.search(r"^Validator exit code:\s*(\d+)\s*$", text, flags=re.MULTILINE)
    if not m2:
        return None
    try:
        exit_code = int(m2.group(1))
    except Exception:
        return None
    return {"passes": passes, "fails": fails, "exit_code": exit_code}


def _compare_anomalies(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> bool:
    # Compare by mapping date -> set(reasons)
    def to_map(anoms: List[Dict[str, Any]]) -> Optional[Dict[str, set]]:
        out = {}
        try:
            for item in anoms:
                date = item["date"]
                reasons = item["reasons"]
                if not isinstance(reasons, list):
                    return None
                out[date] = set(reasons)
        except Exception:
            return None
        return out

    em = to_map(expected)
    am = to_map(actual)
    if em is None or am is None:
        return False
    return em == am


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_json_parseable": 0.0,
        "metrics_week_structure_correct": 0.0,
        "metrics_averages_correct": 0.0,
        "metrics_anomalies_correct": 0.0,
        "report_sections_present_and_metrics_reference": 0.0,
        "data_highlights_references_weeks_and_anomalies": 0.0,
        "what_we_tried_mentions_from_notes": 0.0,
        "evidence_check_points_from_notes": 0.0,
        "next_week_plan_bullet_count": 0.0,
        "validator_log_structure_and_pass": 0.0,
        "report_validation_summary_consistency": 0.0,
    }

    # Paths
    input_csv = workspace / "input" / "baby_log.csv"
    input_notes = workspace / "input" / "reading_notes.md"
    input_checklist = workspace / "input" / "checklist.yml"
    tools_validator = workspace / "tools" / "validate_report.py"
    output_metrics = workspace / "output" / "metrics.json"
    output_report = workspace / "output" / "monthly_update.md"
    output_validator_log = workspace / "output" / "validator_log.txt"

    # Load inputs and recompute expected metrics
    rows = _load_baby_log_csv(input_csv)
    expected_weeks: Optional[List[Dict[str, Any]]] = None
    if rows is not None:
        expected_weeks = _compute_expected_week_metrics(rows)

    # Load metrics.json
    metrics = _safe_load_json(output_metrics)
    if isinstance(metrics, list):
        metrics_ok_parse = True
    else:
        metrics_ok_parse = False

    if metrics_ok_parse:
        scores["metrics_json_parseable"] = 1.0

    # Compare metrics structure
    if metrics_ok_parse and expected_weeks is not None:
        # Check number of weeks and week_start values
        try:
            actual_weeks_map = {item["week_start"]: item for item in metrics if isinstance(item, dict)}
        except Exception:
            actual_weeks_map = {}
        expected_week_starts = [w["week_start"] for w in expected_weeks]
        if len(actual_weeks_map) == len(expected_weeks) and all(ws in actual_weeks_map for ws in expected_week_starts):
            scores["metrics_week_structure_correct"] = 1.0

        # Check days and averages
        avg_ok = True
        for wk in expected_weeks:
            aw = actual_weeks_map.get(wk["week_start"])
            if not isinstance(aw, dict):
                avg_ok = False
                break
            # days
            if aw.get("days") != wk["days"]:
                avg_ok = False
                break
            # avg fields within strict one-decimal rounding
            def eq1(a, b):
                if not isinstance(a, (int, float)):
                    return False
                return abs(float(a) - float(b)) < 0.051

            if not eq1(aw.get("avg_feeds_per_day"), wk["avg_feeds_per_day"]):
                avg_ok = False
                break
            if not eq1(aw.get("avg_oz_per_day"), wk["avg_oz_per_day"]):
                avg_ok = False
                break
            if not eq1(aw.get("avg_sleep_hours_per_day"), wk["avg_sleep_hours_per_day"]):
                avg_ok = False
                break
        if avg_ok:
            scores["metrics_averages_correct"] = 1.0

        # Check anomalies correctness
        anomalies_ok = True
        for wk in expected_weeks:
            aw = actual_weeks_map.get(wk["week_start"])
            if not isinstance(aw, dict) or "anomalies" not in aw or not isinstance(aw["anomalies"], list):
                anomalies_ok = False
                break
            if not _compare_anomalies(wk["anomalies"], aw["anomalies"]):
                anomalies_ok = False
                break
        if anomalies_ok:
            scores["metrics_anomalies_correct"] = 1.0

    # Report checks
    report_text = _safe_read_text(output_report) or ""
    checklist_sections = _load_required_sections_from_checklist(input_checklist)
    sections_present = False
    metrics_literal_present = False
    if report_text and checklist_sections is not None:
        # Check required section headings and metrics reference literal
        for s in checklist_sections:
            pattern = r"^\s*#+\s*" + re.escape(s) + r"\s*$"
            if re.search(pattern, report_text, flags=re.MULTILINE) is None:
                sections_present = False
                break
        else:
            sections_present = True
        metrics_literal_present = ("output/metrics.json" in report_text)
        if sections_present and metrics_literal_present:
            scores["report_sections_present_and_metrics_reference"] = 1.0

    # Data Highlights content checks
    if report_text and expected_weeks is not None:
        sections = _extract_markdown_sections(report_text)
        dh_text = sections.get("Data Highlights", "")
        if dh_text:
            if _find_data_highlights_checks(dh_text, expected_weeks):
                scores["data_highlights_references_weeks_and_anomalies"] = 1.0

    # What We Tried mentions interventions from reading notes
    if report_text:
        sections = _extract_markdown_sections(report_text)
        wwt_text = sections.get("What We Tried", "")
        if wwt_text:
            # Keywords drawn from notes
            keywords = [
                "bedtime routine",
                "responsive feeding",
                "tummy time",
                "dream feed",
            ]
            if any(kw.lower() in wwt_text.lower() for kw in keywords):
                scores["what_we_tried_mentions_from_notes"] = 1.0

    # Evidence Check mentions 2-3 relevant points (check for at least two different keywords)
    if report_text:
        sections = _extract_markdown_sections(report_text)
        ec_text = sections.get("Evidence Check", "")
        if ec_text:
            topics = [
                "responsive feeding",
                "safe sleep",
                "tummy time",
                "introducing solids",
                "bedtime routine",
                "dream feed",
            ]
            found = set()
            low = ec_text.lower()
            for t in topics:
                if t in low:
                    found.add(t)
            if len(found) >= 2:
                scores["evidence_check_points_from_notes"] = 1.0

    # Next Week Plan bullet count 3-5
    if report_text:
        sections = _extract_markdown_sections(report_text)
        nwp_text = sections.get("Next Week Plan", "")
        bullets = _count_bullets(nwp_text)
        if 3 <= bullets <= 5:
            scores["next_week_plan_bullet_count"] = 1.0

    # Validator log checks
    validator_log_text = _safe_read_text(output_validator_log)
    if validator_log_text:
        # Must contain expected lines and final summary with passes and fails
        has_start = "Validation start..." in validator_log_text
        has_checks = "CHECK: " in validator_log_text
        summary = _parse_validator_log_summary(validator_log_text)
        if has_start and has_checks and summary is not None and summary.get("fails", 1) == 0:
            # Optionally check passes equals required sections + metrics reference
            ok_pass_count = True
            if checklist_sections is not None:
                expected_passes = len(checklist_sections) + 1  # + metrics reference check
                if summary.get("passes") != expected_passes:
                    ok_pass_count = False
            if ok_pass_count:
                scores["validator_log_structure_and_pass"] = 1.0

    # Validation Summary consistency between report and log
    if report_text and validator_log_text:
        sections = _extract_markdown_sections(report_text)
        vs_text = sections.get("Validation Summary", "")
        rep_vals = _extract_validation_summary_from_report(vs_text)
        log_vals = _parse_validator_log_summary(validator_log_text)
        if rep_vals is not None and log_vals is not None:
            # Compute expected exit code from log
            expected_exit = 0 if log_vals["fails"] == 0 else 1
            if (
                rep_vals["passes"] == log_vals["passes"]
                and rep_vals["fails"] == log_vals["fails"]
                and rep_vals["exit_code"] == expected_exit
            ):
                scores["report_validation_summary_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()