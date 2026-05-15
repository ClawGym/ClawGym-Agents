import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize whitespace in values
                rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _time_to_minutes(t: str) -> int:
    # Expect HH:MM in 24h
    parts = t.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Bad time format")
    h = int(parts[0])
    m = int(parts[1])
    return h * 60 + m


def _format_3dec(x: float) -> str:
    return f"{x:.3f}"


def _compute_expected_rows(train_rows: List[Dict[str, str]], prefs: dict) -> List[Dict[str, str]]:
    # Filter
    route = prefs.get("route")
    date = prefs.get("date")
    window = prefs.get("departure_window", {})
    earliest = window.get("earliest")
    latest = window.get("latest")
    max_duration = prefs.get("max_duration_min")
    min_on_time = prefs.get("min_on_time_pct")
    disallow_low = prefs.get("disallow_low_availability", False)
    weights = prefs.get("scoring_weights", {"on_time_pct": 0.6, "duration_min": 0.25, "fare_usd": 0.15})
    # Prepare filtered list with parsed fields
    candidates = []
    for r in train_rows:
        try:
            if r.get("route") != route:
                continue
            if r.get("date") != date:
                continue
            dep = r.get("depart_time")
            if dep is None:
                continue
            dep_min = _time_to_minutes(dep)
            if earliest is not None and dep_min < _time_to_minutes(earliest):
                continue
            if latest is not None and dep_min > _time_to_minutes(latest):
                continue
            duration = int(r.get("duration_min"))
            if max_duration is not None and duration > int(max_duration):
                continue
            on_time = int(r.get("on_time_pct"))
            if min_on_time is not None and on_time < int(min_on_time):
                continue
            seat = r.get("seat_availability", "").strip().lower()
            if disallow_low and seat == "low":
                continue
            fare = float(r.get("fare_usd"))
            transfers = int(r.get("transfers"))
            arrive = r.get("arrive_time")
            arrive_min = _time_to_minutes(arrive)
            candidates.append({
                "train_number": int(r.get("train_number")),
                "date": r.get("date"),
                "depart_time": dep,
                "arrive_time": arrive,
                "duration_min": duration,
                "transfers": transfers,
                "fare_usd": fare,
                "on_time_pct": on_time,
                "seat_availability": seat,
                "engineer_notice": r.get("engineer_notice", ""),
                "depart_min": dep_min,
                "arrive_min": arrive_min,
            })
        except Exception:
            # Any parse failure excludes the row from expected computations
            continue

    # If no candidates, return empty
    if not candidates:
        return []

    # Compute min-max for metrics across filtered set
    on_time_vals = [c["on_time_pct"] for c in candidates]
    dur_vals = [c["duration_min"] for c in candidates]
    fare_vals = [c["fare_usd"] for c in candidates]
    on_min, on_max = min(on_time_vals), max(on_time_vals)
    dur_min, dur_max = min(dur_vals), max(dur_vals)
    fare_min, fare_max = min(fare_vals), max(fare_vals)
    on_rng = on_max - on_min
    dur_rng = dur_max - dur_min
    fare_rng = fare_max - fare_min

    # Compute normalized metrics and composite score
    for c in candidates:
        if on_rng == 0:
            on_norm = 1.0
        else:
            on_norm = (c["on_time_pct"] - on_min) / on_rng
        if dur_rng == 0:
            dur_norm = 1.0
        else:
            dur_norm = (dur_max - c["duration_min"]) / dur_rng  # lower better
        if fare_rng == 0:
            fare_norm = 1.0
        else:
            fare_norm = (fare_max - c["fare_usd"]) / fare_rng  # lower better
        c["on_time_norm"] = on_norm
        c["duration_norm"] = dur_norm
        c["fare_norm"] = fare_norm
        c["composite_score"] = (
            weights.get("on_time_pct", 0.6) * on_norm
            + weights.get("duration_min", 0.25) * dur_norm
            + weights.get("fare_usd", 0.15) * fare_norm
        )

    # Rank by descending composite score; tie-breakers earliest arrival, then fewest transfers
    candidates.sort(key=lambda x: (-x["composite_score"], x["arrive_min"], x["transfers"]))

    # Build expected CSV rows with required columns and rounding to 3 decimals
    expected = []
    for idx, c in enumerate(candidates, start=1):
        expected.append({
            "rank": str(idx),
            "train_number": str(c["train_number"]),
            "date": c["date"],
            "depart_time": c["depart_time"],
            "arrive_time": c["arrive_time"],
            "duration_min": str(c["duration_min"]),
            "transfers": str(c["transfers"]),
            "fare_usd": str(int(c["fare_usd"])) if float(c["fare_usd"]).is_integer() else str(c["fare_usd"]),
            "on_time_pct": str(c["on_time_pct"]),
            "seat_availability": c["seat_availability"],
            "engineer_notice": c["engineer_notice"],
            "on_time_norm": _format_3dec(c["on_time_norm"]),
            "duration_norm": _format_3dec(c["duration_norm"]),
            "fare_norm": _format_3dec(c["fare_norm"]),
            "composite_score": _format_3dec(c["composite_score"]),
        })
    return expected


def _parse_student_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = []
            for row in reader:
                rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows, fieldnames
    except Exception:
        return None, None


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _has_date(text: str) -> bool:
    # Accept 2026-05-15, 05/15, 5/15, May 15, May 15, 2026
    patterns = [
        r"\b2026-05-15\b",
        r"\b0?5/15(?:/2026)?\b",
        r"\bMay\s+15(?:,\s*2026)?\b",
    ]
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "csv_structure": 0.0,
        "csv_rows_correct": 0.0,
        "csv_ranking_order": 0.0,
        "csv_norms_and_composite_rounding": 0.0,
        "summary_selection_criteria": 0.0,
        "summary_top3_consistency": 0.0,
        "summary_recommendation_consistency": 0.0,
        "summary_risks_notice_included": 0.0,
        "engineer_message_constraints": 0.0,
        "companion_message_constraints": 0.0,
    }

    # Load inputs to compute expected results
    input_csv_path = workspace / "input" / "train_options.csv"
    input_json_path = workspace / "input" / "trip_preferences.json"
    raw_messages_path = workspace / "input" / "raw_messages.txt"  # not used for grading but ensure existence not required

    train_rows = _read_csv(input_csv_path) or []
    prefs = _read_json(input_json_path) or {}

    expected_rows = _compute_expected_rows(train_rows, prefs)
    expected_header = [
        "rank",
        "train_number",
        "date",
        "depart_time",
        "arrive_time",
        "duration_min",
        "transfers",
        "fare_usd",
        "on_time_pct",
        "seat_availability",
        "engineer_notice",
        "on_time_norm",
        "duration_norm",
        "fare_norm",
        "composite_score",
    ]

    # Paths to deliverables
    out_csv_path = workspace / "output" / "filtered_ranked_options.csv"
    out_summary_path = workspace / "output" / "itinerary_summary.md"
    out_engineer_path = workspace / "output" / "messages" / "engineer.txt"
    out_companion_path = workspace / "output" / "messages" / "companion.txt"

    # Check CSV structure
    student_rows, student_header = _parse_student_csv(out_csv_path)
    if student_rows is not None and student_header is not None:
        if student_header == expected_header:
            scores["csv_structure"] = 1.0
        else:
            scores["csv_structure"] = 0.0
    else:
        scores["csv_structure"] = 0.0

    # CSV rows correctness and ranking order and rounding
    if student_rows is not None:
        # Map by rank for comparison
        expected_by_rank = {er["rank"]: er for er in expected_rows}
        total_expected = len(expected_rows)
        correct_rows = 0
        rounding_ok_count = 0
        rounding_total = 0
        ranking_ok = False

        if total_expected > 0 and len(student_rows) >= total_expected:
            # Check ranking order by train_number sequence
            expected_order = [er["train_number"] for er in expected_rows]
            student_order = [row.get("train_number", "").strip() for row in student_rows[:total_expected]]
            ranking_ok = (student_order == expected_order)
        else:
            ranking_ok = False

        for row in student_rows:
            rank = (row.get("rank") or "").strip()
            if rank in expected_by_rank:
                expected_row = expected_by_rank[rank]
                # Check all fields equality
                all_match = True
                for key in expected_header:
                    student_val = (row.get(key) or "").strip()
                    expected_val = (expected_row.get(key) or "").strip()
                    if student_val != expected_val:
                        all_match = False
                        break
                if all_match:
                    correct_rows += 1
                # Check rounding format for norm fields regardless of value match
                for metric_key in ["on_time_norm", "duration_norm", "fare_norm", "composite_score"]:
                    rounding_total += 1
                    sval = (row.get(metric_key) or "").strip()
                    if re.fullmatch(r"-?\d+\.\d{3}", sval) is not None:
                        rounding_ok_count += 1
        if total_expected > 0:
            scores["csv_rows_correct"] = min(1.0, correct_rows / total_expected)
        else:
            scores["csv_rows_correct"] = 0.0
        scores["csv_ranking_order"] = 1.0 if ranking_ok else 0.0
        if rounding_total > 0:
            scores["csv_norms_and_composite_rounding"] = rounding_ok_count / rounding_total
        else:
            scores["csv_norms_and_composite_rounding"] = 0.0
    else:
        scores["csv_rows_correct"] = 0.0
        scores["csv_ranking_order"] = 0.0
        scores["csv_norms_and_composite_rounding"] = 0.0

    # Summary checks
    summary_text = _read_text(out_summary_path) or ""
    if summary_text:
        # Selection criteria presence
        criteria_hits = 0
        criteria_total = 8
        # route
        if prefs.get("route") and prefs["route"] in summary_text:
            criteria_hits += 1
        # date
        if prefs.get("date") and prefs["date"] in summary_text:
            criteria_hits += 1
        # earliest
        earliest = prefs.get("departure_window", {}).get("earliest")
        if earliest and earliest in summary_text:
            criteria_hits += 1
        # latest
        latest = prefs.get("departure_window", {}).get("latest")
        if latest and latest in summary_text:
            criteria_hits += 1
        # max_duration_min
        if str(prefs.get("max_duration_min")) in summary_text:
            criteria_hits += 1
        # min_on_time_pct
        if str(prefs.get("min_on_time_pct")) in summary_text:
            criteria_hits += 1
        # disallow_low_availability
        dla = prefs.get("disallow_low_availability", False)
        if ("disallow_low_availability" in summary_text) or (("low" in summary_text.lower()) and ("availability" in summary_text.lower())):
            # Require mention of disallow low availability concept
            if dla:
                criteria_hits += 1
            else:
                criteria_hits += 1  # if not required, count as present mention
        # weights
        weights = prefs.get("scoring_weights", {})
        w_hits = 0
        for v in [weights.get("on_time_pct"), weights.get("duration_min"), weights.get("fare_usd")]:
            if v is not None and f"{v}" in summary_text:
                w_hits += 1
        if w_hits == 3:
            criteria_hits += 1
        scores["summary_selection_criteria"] = criteria_hits / criteria_total

        # Top 3 consistency with student's CSV (if parseable), otherwise with expected
        top_source = student_rows if student_rows else expected_rows
        top3 = []
        if isinstance(top_source, list) and top_source:
            # student_rows are dicts with string values from CSV; expected_rows are dicts with strings too
            # Normalize to same shape
            if top_source is student_rows:
                for r in top_source[:3]:
                    top3.append({
                        "train_number": r.get("train_number", ""),
                        "depart_time": r.get("depart_time", ""),
                        "arrive_time": r.get("arrive_time", ""),
                        "duration_min": r.get("duration_min", ""),
                        "fare_usd": r.get("fare_usd", ""),
                        "on_time_pct": r.get("on_time_pct", ""),
                        "composite_score": r.get("composite_score", ""),
                    })
            else:
                for r in top_source[:3]:
                    top3.append({
                        "train_number": r.get("train_number", ""),
                        "depart_time": r.get("depart_time", ""),
                        "arrive_time": r.get("arrive_time", ""),
                        "duration_min": r.get("duration_min", ""),
                        "fare_usd": r.get("fare_usd", ""),
                        "on_time_pct": r.get("on_time_pct", ""),
                        "composite_score": r.get("composite_score", ""),
                    })
        top_hits = 0
        top_total = max(1, len(top3))
        for item in top3:
            present_all = True
            for key in ["train_number", "depart_time", "arrive_time", "duration_min", "fare_usd", "on_time_pct", "composite_score"]:
                val = item.get(key, "")
                if not val or str(val) not in summary_text:
                    present_all = False
                    break
            if present_all:
                top_hits += 1
        scores["summary_top3_consistency"] = top_hits / top_total if top_total > 0 else 0.0

        # Recommendation consistency: ensure top two trains from CSV appear
        top_two = []
        if student_rows:
            if len(student_rows) >= 2:
                top_two = [student_rows[0].get("train_number", ""), student_rows[1].get("train_number", "")]
        elif expected_rows:
            if len(expected_rows) >= 2:
                top_two = [expected_rows[0].get("train_number", ""), expected_rows[1].get("train_number", "")]
        rec_hits = 0
        rec_total = len(top_two)
        for tn in top_two:
            if tn and tn in summary_text:
                rec_hits += 1
        scores["summary_recommendation_consistency"] = (rec_hits / rec_total) if rec_total > 0 else 0.0

        # Risks & Mitigations: include engineer_notice text for top two if present
        notice_hit = 0.0
        # Determine notices for top two from expected set (ground truth)
        tn_notice_map = {}
        for r in expected_rows[:2]:
            tn_notice_map[r["train_number"]] = r.get("engineer_notice", "")
        any_notice_texts = [n for n in tn_notice_map.values() if n and n.lower() != "none"]
        if any_notice_texts:
            # At least one notice must be mentioned
            # Accept exact notice text or key phrases contained
            found_any = False
            for n in any_notice_texts:
                # Use lenient check: presence of "slow" and "Ridgefield" or the exact substring
                if (n in summary_text) or (("slow" in summary_text.lower() and "ridgefield" in summary_text.lower())):
                    found_any = True
                    break
            notice_hit = 1.0 if found_any else 0.0
        else:
            # No notices to include; consider as satisfied
            notice_hit = 1.0
        scores["summary_risks_notice_included"] = notice_hit
    else:
        scores["summary_selection_criteria"] = 0.0
        scores["summary_top3_consistency"] = 0.0
        scores["summary_recommendation_consistency"] = 0.0
        scores["summary_risks_notice_included"] = 0.0

    # Engineer message checks
    eng_text = _read_text(out_engineer_path) or ""
    if eng_text:
        conditions = 0
        satisfied = 0
        # <= 120 words
        conditions += 1
        if _word_count(eng_text) <= 120:
            satisfied += 1
        # includes recommended train number (top of expected or student CSV)
        rec_train = None
        if student_rows and len(student_rows) >= 1:
            rec_train = student_rows[0].get("train_number", "")
        elif expected_rows and len(expected_rows) >= 1:
            rec_train = expected_rows[0].get("train_number", "")
        conditions += 1
        if rec_train and rec_train in eng_text:
            satisfied += 1
        # includes travel date (accept multiple formats)
        conditions += 1
        if _has_date(eng_text):
            satisfied += 1
        # polite tone: presence of 'please' or 'appreciate' or 'thank'
        conditions += 1
        if re.search(r"\b(please|appreciate|thank)\b", eng_text, flags=re.IGNORECASE):
            satisfied += 1
        # reference applicable notice for top two OR ask about planned work
        # If top two includes a notice (not 'none'), require mention 'slow' or 'Ridgefield'; else accept 'planned work'
        top_two_notices = []
        if student_rows and len(student_rows) >= 2:
            for r in student_rows[:2]:
                top_two_notices.append(r.get("engineer_notice", ""))
        else:
            for r in expected_rows[:2]:
                top_two_notices.append(r.get("engineer_notice", ""))
        has_any_notice = any(n and n.lower() != "none" for n in top_two_notices)
        conditions += 1
        if has_any_notice:
            if ("slow" in eng_text.lower() and "ridgefield" in eng_text.lower()) or ("slow order" in eng_text.lower()):
                satisfied += 1
        else:
            if ("planned work" in eng_text.lower()) or ("maintenance" in eng_text.lower()) or ("work" in eng_text.lower()):
                satisfied += 1
        scores["engineer_message_constraints"] = satisfied / conditions if conditions > 0 else 0.0
    else:
        scores["engineer_message_constraints"] = 0.0

    # Companion message checks
    comp_text = _read_text(out_companion_path) or ""
    if comp_text:
        conditions = 0
        satisfied = 0
        # <= 120 words
        conditions += 1
        if _word_count(comp_text) <= 120:
            satisfied += 1
        # includes recommended and backup train numbers
        rec_train = None
        backup_train = None
        if student_rows and len(student_rows) >= 2:
            rec_train = student_rows[0].get("train_number", "")
            backup_train = student_rows[1].get("train_number", "")
        elif len(expected_rows) >= 2:
            rec_train = expected_rows[0].get("train_number", "")
            backup_train = expected_rows[1].get("train_number", "")
        conditions += 1
        if rec_train and backup_train and (rec_train in comp_text) and (backup_train in comp_text):
            satisfied += 1
        # includes depart and arrive times for both
        times = []
        if student_rows and len(student_rows) >= 2:
            times = [
                student_rows[0].get("depart_time", ""), student_rows[0].get("arrive_time", ""),
                student_rows[1].get("depart_time", ""), student_rows[1].get("arrive_time", "")
            ]
        elif len(expected_rows) >= 2:
            times = [
                expected_rows[0].get("depart_time", ""), expected_rows[0].get("arrive_time", ""),
                expected_rows[1].get("depart_time", ""), expected_rows[1].get("arrive_time", "")
            ]
        conditions += 1
        if all(t and t in comp_text for t in times):
            satisfied += 1
        # includes reliability note using on_time_pct (both)
        on_times = []
        if student_rows and len(student_rows) >= 2:
            on_times = [student_rows[0].get("on_time_pct", ""), student_rows[1].get("on_time_pct", "")]
        elif len(expected_rows) >= 2:
            on_times = [expected_rows[0].get("on_time_pct", ""), expected_rows[1].get("on_time_pct", "")]
        conditions += 1
        if all(ot and str(ot) in comp_text for ot in on_times):
            satisfied += 1
        # includes cost note using fare_usd (both)
        fares = []
        if student_rows and len(student_rows) >= 2:
            fares = [student_rows[0].get("fare_usd", ""), student_rows[1].get("fare_usd", "")]
        elif len(expected_rows) >= 2:
            fares = [expected_rows[0].get("fare_usd", ""), expected_rows[1].get("fare_usd", "")]
        conditions += 1
        if all(fr and str(fr) in comp_text for fr in fares):
            satisfied += 1

        scores["companion_message_constraints"] = satisfied / conditions if conditions > 0 else 0.0
    else:
        scores["companion_message_constraints"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()