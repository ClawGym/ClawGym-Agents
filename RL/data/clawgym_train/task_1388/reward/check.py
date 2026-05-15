import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_simple_rules_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the specific rules.yaml structure:
    weekly_targets: { key: scalar }
    flexibility_focuses: [ list of strings ]
    """
    text = _read_text(path)
    if text is None:
        return None
    weekly_targets: Dict[str, Any] = {}
    flex_list: List[str] = []
    state = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # ignore comments and empty
        if not line or line.startswith("#"):
            continue
        if line.endswith(":") and (not line.startswith("-")):
            key = line[:-1].strip()
            if key == "weekly_targets":
                state = "weekly_targets"
            elif key == "flexibility_focuses":
                state = "flexibility_focuses"
            else:
                state = None
            continue
        if state == "weekly_targets":
            # expect "key: value"
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                # strip quotes if any
                if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
                    v = v[1:-1]
                # parse bool/int
                vl: Any
                lv = v.lower()
                if lv in ("true", "false"):
                    vl = (lv == "true")
                else:
                    try:
                        vl = int(v)
                    except ValueError:
                        try:
                            vl = float(v)
                        except ValueError:
                            vl = v
                weekly_targets[k] = vl
        elif state == "flexibility_focuses":
            # expect "- item"
            if line.startswith("-"):
                item = line[1:].strip()
                # strip quotes
                if item.startswith(("'", '"')) and item.endswith(("'", '"')) and len(item) >= 2:
                    item = item[1:-1]
                if item:
                    flex_list.append(item)
    if not weekly_targets or not isinstance(flex_list, list):
        return None
    return {"weekly_targets": weekly_targets, "flexibility_focuses": flex_list}


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _date_to_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _week_start(d: datetime) -> datetime:
    # Monday start
    return d - timedelta(days=d.weekday())


def _safe_float(s: str) -> float:
    try:
        return float(s)
    except Exception:
        return 0.0


def _compute_expected(inputs_dir: Path) -> Optional[Dict[str, Any]]:
    plan_path = inputs_dir / "plan.csv"
    run_path = inputs_dir / "run_log.csv"
    rules_path = inputs_dir / "rules.yaml"
    notes_path = inputs_dir / "notes.txt"
    plan_rows = _read_csv(plan_path)
    run_rows = _read_csv(run_path)
    rules = _parse_simple_rules_yaml(rules_path)
    notes_text = _read_text(notes_path)
    if plan_rows is None or run_rows is None or rules is None or notes_text is None:
        return None

    # Build date maps
    plan_by_date: Dict[str, List[Dict[str, Any]]] = {}
    all_dates: set = set()
    for r in plan_rows:
        ds = r.get("date", "").strip()
        d = _parse_date(ds)
        if not d:
            continue
        all_dates.add(ds)
        plan_by_date.setdefault(ds, []).append({
            "focus": r.get("focus", "").strip(),
            "intensity": r.get("intensity", "").strip().lower(),
            "duration_min": int(_safe_float(r.get("duration_min", "0"))),
        })
    run_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in run_rows:
        ds = r.get("date", "").strip()
        d = _parse_date(ds)
        if not d:
            continue
        all_dates.add(ds)
        run_by_date.setdefault(ds, []).append({
            "type": r.get("type", "").strip().lower(),
            "distance_km": _safe_float(r.get("distance_km", "0")),
        })

    if not all_dates:
        return None

    # Determine weeks involved based on all dates
    sorted_dates = sorted(_parse_date(d) for d in all_dates if _parse_date(d) is not None)
    min_date = sorted_dates[0]
    max_date = sorted_dates[-1]
    # Build week starts from min to max
    ws = _week_start(min_date)
    weeks: List[Dict[str, Any]] = []
    week_starts: List[datetime] = []
    curr = ws
    while curr <= max_date:
        week_starts.append(curr)
        curr = curr + timedelta(days=7)

    flex_focuses = [f.lower() for f in rules.get("flexibility_focuses", [])]
    weekly_targets = rules.get("weekly_targets", {})

    def is_run_present(ds: str) -> bool:
        items = run_by_date.get(ds, [])
        for it in items:
            t = it.get("type", "")
            if t != "rest" and _safe_float(str(it.get("distance_km", "0"))) > 0:
                return True
        return False

    # Compute weekly stats
    weeks_stats: Dict[str, Dict[str, Any]] = {}
    for ws_dt in week_starts:
        we_dt = ws_dt + timedelta(days=6)
        ws_str = _date_to_str(ws_dt)
        we_str = _date_to_str(we_dt)
        # days in week
        dates_in_week = [_date_to_str(ws_dt + timedelta(days=i)) for i in range(7)]
        # cross-training
        ct_dates = [d for d in dates_in_week if d in plan_by_date]
        cross_training_days = len(ct_dates)
        total_minutes = 0
        unique_focuses = set()
        has_flex = False
        for d in dates_in_week:
            for sess in plan_by_date.get(d, []):
                total_minutes += int(sess.get("duration_min", 0))
                f = str(sess.get("focus", "")).lower()
                unique_focuses.add(f)
                if f in flex_focuses:
                    has_flex = True
        # rest day: neither run nor cross-training
        has_rest = False
        for d in dates_in_week:
            has_plan = d in plan_by_date
            has_run = is_run_present(d)
            if (not has_plan) and (not has_run):
                has_rest = True
                break
        weeks_stats[ws_str] = {
            "week_start": ws_str,
            "week_end": we_str,
            "cross_training_days": cross_training_days,
            "total_cross_training_minutes": total_minutes,
            "unique_focuses": len(unique_focuses),
            "has_flexibility_session": has_flex,
            "has_rest_day": has_rest,
        }
        weeks.append(weeks_stats[ws_str])

    # Restrictions from notes: We'll enforce two mandated ones by semantics
    # 1) No lower-body strength within 1 day before or after a 'long' run.
    long_run_dates = set(ds for ds, items in run_by_date.items() for it in items if it.get("type") == "long")
    lb_strength_violations: List[str] = []
    for lr_ds in long_run_dates:
        d = _parse_date(lr_ds)
        if not d:
            continue
        for delta in (-1, 1):
            nd = d + timedelta(days=delta)
            nds = _date_to_str(nd)
            for sess in plan_by_date.get(nds, []):
                if str(sess.get("focus", "")).lower() == "strength_lower":
                    lb_strength_violations.append(nds)
    lb_strength_violations = sorted(set(lb_strength_violations))

    # 2) No high-intensity cross-training on the same day as 'tempo' or 'interval' runs.
    hi_conflict_violations: List[str] = []
    for ds, items in run_by_date.items():
        types = set(it.get("type") for it in items)
        if "tempo" in types or "interval" in types:
            for sess in plan_by_date.get(ds, []):
                if str(sess.get("intensity", "")).lower() == "high":
                    hi_conflict_violations.append(ds)
    hi_conflict_violations = sorted(set(hi_conflict_violations))

    # Weekly targets checks
    # Build violations per rule (weeks that fail)
    def week_range(ws_str: str) -> str:
        we_str = weeks_stats[ws_str]["week_end"]
        return f"{ws_str} to {we_str}"

    min_days = weekly_targets.get("min_days")
    max_days = weekly_targets.get("max_days")
    min_minutes = weekly_targets.get("min_minutes")
    max_minutes = weekly_targets.get("max_minutes")
    min_unique_focuses = weekly_targets.get("min_unique_focuses")
    req_flex = bool(weekly_targets.get("require_flexibility_session"))
    req_rest = bool(weekly_targets.get("require_rest_day"))

    # Determine violations
    v_min_days: List[str] = []
    v_max_days: List[str] = []
    v_min_minutes: List[str] = []
    v_max_minutes: List[str] = []
    v_min_unique: List[str] = []
    v_req_flex: List[str] = []
    v_req_rest: List[str] = []
    for ws_str, stats in weeks_stats.items():
        if isinstance(min_days, (int, float)) and stats["cross_training_days"] < int(min_days):
            v_min_days.append(week_range(ws_str))
        if isinstance(max_days, (int, float)) and stats["cross_training_days"] > int(max_days):
            v_max_days.append(week_range(ws_str))
        if isinstance(min_minutes, (int, float)) and stats["total_cross_training_minutes"] < int(min_minutes):
            v_min_minutes.append(week_range(ws_str))
        if isinstance(max_minutes, (int, float)) and stats["total_cross_training_minutes"] > int(max_minutes):
            v_max_minutes.append(week_range(ws_str))
        if isinstance(min_unique_focuses, (int, float)) and stats["unique_focuses"] < int(min_unique_focuses):
            v_min_unique.append(week_range(ws_str))
        if req_flex and not stats["has_flexibility_session"]:
            v_req_flex.append(week_range(ws_str))
        if req_rest and not stats["has_rest_day"]:
            v_req_rest.append(week_range(ws_str))

    rule_checks_expected = {
        "min_days": {"passed": len(v_min_days) == 0, "violations": v_min_days},
        "max_days": {"passed": len(v_max_days) == 0, "violations": v_max_days},
        "min_minutes": {"passed": len(v_min_minutes) == 0, "violations": v_min_minutes},
        "max_minutes": {"passed": len(v_max_minutes) == 0, "violations": v_max_minutes},
        "min_unique_focuses": {"passed": len(v_min_unique) == 0, "violations": v_min_unique},
        "require_flexibility_session": {"passed": len(v_req_flex) == 0, "violations": v_req_flex},
        "require_rest_day": {"passed": len(v_req_rest) == 0, "violations": v_req_rest},
        "notes_no_lb_strength_near_long": {"passed": len(lb_strength_violations) == 0, "violations": lb_strength_violations},
        "notes_no_high_intensity_on_tempo_or_interval": {"passed": len(hi_conflict_violations) == 0, "violations": hi_conflict_violations},
    }

    # Aggregates
    avg_days = sum(w["cross_training_days"] for w in weeks) / len(weeks) if weeks else 0.0
    avg_minutes = sum(w["total_cross_training_minutes"] for w in weeks) / len(weeks) if weeks else 0.0

    # Overall status: PASS if all required rules pass
    overall_pass = all(v.get("passed") for v in rule_checks_expected.values())
    overall_status = "PASS" if overall_pass else "FAIL"

    return {
        "weeks": weeks,
        "rule_checks": rule_checks_expected,
        "aggregates": {
            "avg_cross_training_days": float(avg_days),
            "avg_cross_training_minutes": float(avg_minutes),
        },
        "overall_status": overall_status,
        "expected_violation_dates": {
            "lb_strength": rule_checks_expected["notes_no_lb_strength_near_long"]["violations"],
            "hi_intensity": rule_checks_expected["notes_no_high_intensity_on_tempo_or_interval"]["violations"],
        },
    }


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _violation_contains_expected(violations: List[Any], expected_tokens: List[str]) -> bool:
    """
    Verify that for each expected token (date or week_start), there exists at least one violation string
    that contains that token.
    """
    if not isinstance(violations, list):
        return False
    violation_strs = [str(v) for v in violations]
    for token in expected_tokens:
        if not any(token in v for v in violation_strs):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_exist": 0.0,
        "validation_report_json_parsed": 0.0,
        "json_rule_keys_present": 0.0,
        "weeks_count_and_ranges_correct": 0.0,
        "weeks_stats_correct": 0.0,
        "json_rule_pass_flags_correct": 0.0,
        "json_rule_violations_cover_expected": 0.0,
        "json_aggregates_correct": 0.0,
        "json_overall_status_correct": 0.0,
        "summary_weeks_listed": 0.0,
        "summary_violations_listed": 0.0,
        "email_addressed_and_contains_averages_and_suggestions": 0.0,
    }

    inputs_dir = workspace / "input"
    outputs_dir = workspace / "out"
    report_path = outputs_dir / "validation_report.json"
    summary_path = outputs_dir / "summary.md"
    email_path = outputs_dir / "email_to_coach.txt"

    # Outputs exist
    if report_path.exists() and summary_path.exists() and email_path.exists():
        scores["outputs_exist"] = 1.0

    # Compute expected from inputs
    expected = _compute_expected(inputs_dir)

    # Parse JSON
    report = _load_json(report_path) if report_path.exists() else None
    if report is not None and isinstance(report, dict):
        scores["validation_report_json_parsed"] = 1.0

    # Further checks require expected and report
    if expected is None or report is None:
        return scores

    # Check rule keys present
    expected_rule_keys = [
        "min_days",
        "max_days",
        "min_minutes",
        "max_minutes",
        "min_unique_focuses",
        "require_flexibility_session",
        "require_rest_day",
        "notes_no_lb_strength_near_long",
        "notes_no_high_intensity_on_tempo_or_interval",
    ]
    rc = report.get("rule_checks")
    if isinstance(rc, dict) and all(k in rc for k in expected_rule_keys):
        scores["json_rule_keys_present"] = 1.0

    # Weeks count and ranges
    weeks_rep = report.get("weeks")
    if isinstance(weeks_rep, list):
        expected_weeks = expected["weeks"]
        if len(weeks_rep) == len(expected_weeks):
            # match by week_start
            rep_by_start = {}
            ok_ranges = True
            for w in weeks_rep:
                if not isinstance(w, dict):
                    ok_ranges = False
                    break
                ws = w.get("week_start")
                we = w.get("week_end")
                if not isinstance(ws, str) or not isinstance(we, str):
                    ok_ranges = False
                    break
                rep_by_start[ws] = w
            if ok_ranges:
                for ew in expected_weeks:
                    ws = ew["week_start"]
                    we = ew["week_end"]
                    if ws not in rep_by_start or rep_by_start[ws].get("week_end") != we:
                        ok_ranges = False
                        break
            if ok_ranges:
                scores["weeks_count_and_ranges_correct"] = 1.0

    # Weeks stats correct
    if scores["weeks_count_and_ranges_correct"] == 1.0:
        rep_by_start = {w["week_start"]: w for w in report["weeks"]}
        ok_stats = True
        for ew in expected["weeks"]:
            wrep = rep_by_start.get(ew["week_start"])
            if wrep is None:
                ok_stats = False
                break
            # exact matches on stats
            if wrep.get("cross_training_days") != ew["cross_training_days"]:
                ok_stats = False
                break
            if wrep.get("total_cross_training_minutes") != ew["total_cross_training_minutes"]:
                ok_stats = False
                break
            if wrep.get("unique_focuses") != ew["unique_focuses"]:
                ok_stats = False
                break
            if bool(wrep.get("has_flexibility_session")) != bool(ew["has_flexibility_session"]):
                ok_stats = False
                break
            if bool(wrep.get("has_rest_day")) != bool(ew["has_rest_day"]):
                ok_stats = False
                break
        if ok_stats:
            scores["weeks_stats_correct"] = 1.0

    # Rule pass flags correct
    rc_rep = report.get("rule_checks")
    rc_exp = expected["rule_checks"]
    if isinstance(rc_rep, dict):
        pass_flags_ok = True
        for key in expected_rule_keys:
            rep_entry = rc_rep.get(key)
            exp_entry = rc_exp.get(key)
            if not isinstance(rep_entry, dict) or not isinstance(exp_entry, dict):
                pass_flags_ok = False
                break
            if bool(rep_entry.get("passed")) != bool(exp_entry.get("passed")):
                pass_flags_ok = False
                break
        if pass_flags_ok:
            scores["json_rule_pass_flags_correct"] = 1.0

    # Rule violations cover expected
    if isinstance(rc_rep, dict):
        cov_ok = True
        # Weekly targets violations: use week_start tokens for weeks that failed
        # Build expected tokens per rule
        # Helper to map week_range "YYYY-MM-DD to YYYY-MM-DD" -> token "YYYY-MM-DD"
        def extract_week_starts(ranges: List[str]) -> List[str]:
            toks = []
            for s in ranges:
                if isinstance(s, str):
                    if " to " in s:
                        tok = s.split(" to ")[0].strip()
                        toks.append(tok)
                    else:
                        toks.append(s.strip())
            return sorted(set(toks))

        # Map expected violations
        for key in expected_rule_keys:
            exp_entry = rc_exp.get(key, {})
            rep_entry = rc_rep.get(key, {})
            rep_violations = rep_entry.get("violations", [])
            if key in ("notes_no_lb_strength_near_long", "notes_no_high_intensity_on_tempo_or_interval"):
                # dates list: must contain the expected dates
                expected_dates = [str(v) for v in exp_entry.get("violations", [])]
                if not _violation_contains_expected(rep_violations, expected_dates):
                    cov_ok = False
                    break
            else:
                # weekly rules: check presence of week_start tokens for failing weeks
                expected_ranges = [str(v) for v in exp_entry.get("violations", [])]
                expected_tokens = extract_week_starts(expected_ranges)
                if expected_tokens:
                    if not _violation_contains_expected(rep_violations, expected_tokens):
                        cov_ok = False
                        break
                else:
                    # if no expected violations, ensure report has empty or no violations
                    if isinstance(rep_violations, list) and len(rep_violations) == 0:
                        pass
                    else:
                        # allow extra messaging? Be strict: should have empty list
                        cov_ok = False
                        break
        if cov_ok:
            scores["json_rule_violations_cover_expected"] = 1.0

    # Aggregates correct
    aggregates_rep = report.get("aggregates")
    aggregates_exp = expected.get("aggregates")
    if isinstance(aggregates_rep, dict) and isinstance(aggregates_exp, dict):
        ad_rep = aggregates_rep.get("avg_cross_training_days")
        am_rep = aggregates_rep.get("avg_cross_training_minutes")
        ad_exp = aggregates_exp.get("avg_cross_training_days")
        am_exp = aggregates_exp.get("avg_cross_training_minutes")
        if isinstance(ad_rep, (int, float)) and isinstance(am_rep, (int, float)):
            if _approx_equal(float(ad_rep), float(ad_exp)) and _approx_equal(float(am_rep), float(am_exp)):
                scores["json_aggregates_correct"] = 1.0

    # Overall status correct
    if isinstance(report.get("overall_status"), str):
        if report["overall_status"] == expected["overall_status"]:
            scores["json_overall_status_correct"] = 1.0

    # Summary checks
    summary_text = _read_text(summary_path) if summary_path.exists() else None
    if summary_text is not None:
        # weeks listed
        try:
            w0 = expected["weeks"][0]
            w1 = expected["weeks"][1] if len(expected["weeks"]) > 1 else None
            w0_range = f'{w0["week_start"]} to {w0["week_end"]}'
            ok0 = w0_range in summary_text
            ok1 = True
            if w1:
                w1_range = f'{w1["week_start"]} to {w1["week_end"]}'
                ok1 = w1_range in summary_text
            if ok0 and ok1:
                scores["summary_weeks_listed"] = 1.0
        except Exception:
            pass

        # violations listed: expect all four violation dates if present
        expected_violation_dates = set(expected["expected_violation_dates"]["lb_strength"]) | set(
            expected["expected_violation_dates"]["hi_intensity"]
        )
        if expected_violation_dates:
            if all(date in summary_text for date in expected_violation_dates):
                scores["summary_violations_listed"] = 1.0
        else:
            # If no expected violations, ensure summary has no "violation" word, but to be lenient, mark as pass
            scores["summary_violations_listed"] = 1.0

    # Email checks
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text is not None:
        has_coach = ("coach alex" in email_text.lower())
        # Averages
        ad = expected["aggregates"]["avg_cross_training_days"]
        am = expected["aggregates"]["avg_cross_training_minutes"]
        # Allow either explicit numbers or the word "average"
        has_avg_nums = (f"{ad:.1f}" in email_text) and (f"{am:.0f}" in email_text or f"{am:.1f}" in email_text)
        has_avg_word = "average" in email_text.lower()
        has_avg = has_avg_nums or has_avg_word

        # Mentions at least one violation
        expected_violation_dates = set(expected["expected_violation_dates"]["lb_strength"]) | set(
            expected["expected_violation_dates"]["hi_intensity"]
        )
        mentions_violation = any(date in email_text for date in expected_violation_dates) or (
            ("lower-body" in email_text.lower() or "strength" in email_text.lower())
            and ("long" in email_text.lower())
        ) or (
            ("high" in email_text.lower()) and ("tempo" in email_text.lower() or "interval" in email_text.lower())
        )

        # Suggestions: action verbs
        suggestion_verbs = ["adjust", "move", "reschedule", "swap", "shift", "reduce", "lower", "skip", "rearrange"]
        has_suggestion = any(verb in email_text.lower() for verb in suggestion_verbs)

        if has_coach and has_avg and mentions_violation and has_suggestion:
            scores["email_addressed_and_contains_averages_and_suggestions"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()