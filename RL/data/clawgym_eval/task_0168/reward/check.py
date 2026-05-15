import csv
import json
import math
import re
import sys
from pathlib import Path
from statistics import median as stat_median
from typing import Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: v for k, v in row.items()}) for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _to_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _round2(x: float) -> float:
    return round(x + 0.0, 2)


def _median(values: List[float]) -> float:
    if not values:
        return float("nan")
    return stat_median(values)


def _compute_region_avg_price(prices_rows: List[Dict[str, str]]) -> Dict[str, float]:
    by_region: Dict[str, List[float]] = {}
    for r in prices_rows:
        region = (r.get("region") or "").strip()
        p = _to_float((r.get("price_per_kg") or "").strip())
        if not region or p is None:
            continue
        by_region.setdefault(region, []).append(p)
    avg_by_region: Dict[str, float] = {}
    for region, vals in by_region.items():
        if vals:
            avg_by_region[region] = sum(vals) / len(vals)
    return avg_by_region


def _compute_expected_consumption(fleet_rows: List[Dict[str, str]], avg_price: Dict[str, float]) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    groups: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    for r in fleet_rows:
        vehicle_id = (r.get("vehicle_id") or "").strip()
        region = (r.get("region") or "").strip()
        route_type = (r.get("route_type") or "").strip()
        d = _to_float((r.get("distance_km") or "").strip())
        h = _to_float((r.get("hydrogen_kg_used") or "").strip())
        if not vehicle_id or not region or not route_type or d is None or h is None:
            continue
        if d == 0:
            continue
        k = (vehicle_id, region, route_type)
        entry = groups.setdefault(k, {"trips": 0, "sum_d": 0.0, "sum_h": 0.0, "rates": []})
        entry["trips"] = int(entry["trips"]) + 1
        entry["sum_d"] = float(entry["sum_d"]) + d
        entry["sum_h"] = float(entry["sum_h"]) + h
        rate = h / d * 100.0
        entry["rates"] = list(entry["rates"]) + [rate]
    expected: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    for k, entry in groups.items():
        vehicle_id, region, route_type = k
        trips = int(entry["trips"])
        sum_d = float(entry["sum_d"])
        sum_h = float(entry["sum_h"])
        rates = list(entry["rates"])
        avg_rate = sum(rates) / len(rates) if rates else float("nan")
        med_rate = _median(rates)
        reg_price = avg_price.get(region)
        est_cost = avg_rate * reg_price if (reg_price is not None and not math.isnan(avg_rate)) else float("nan")
        expected[k] = {
            "trips": trips,
            "total_distance_km": _round2(sum_d),
            "total_hydrogen_kg": _round2(sum_h),
            "avg_kg_per_100km": _round2(avg_rate),
            "median_kg_per_100km": _round2(med_rate),
            "est_cost_per_100km": _round2(est_cost),
        }
    return expected


def _compute_expected_region_costs(fleet_rows: List[Dict[str, str]], avg_price: Dict[str, float]) -> Dict[str, Dict[str, float]]:
    by_region_sums: Dict[str, Dict[str, float]] = {}
    for r in fleet_rows:
        region = (r.get("region") or "").strip()
        d = _to_float((r.get("distance_km") or "").strip())
        h = _to_float((r.get("hydrogen_kg_used") or "").strip())
        if not region or d is None or h is None:
            continue
        if d == 0:
            continue
        ent = by_region_sums.setdefault(region, {"sum_d": 0.0, "sum_h": 0.0})
        ent["sum_d"] += d
        ent["sum_h"] += h
    expected: Dict[str, Dict[str, float]] = {}
    for region, sums in by_region_sums.items():
        sum_d = sums["sum_d"]
        sum_h = sums["sum_h"]
        if sum_d == 0:
            continue
        avg_p = avg_price.get(region)
        if avg_p is None:
            continue
        fleet_w = (sum_h / sum_d) * 100.0
        est_cost = fleet_w * avg_p
        expected[region] = {
            "avg_price_per_kg": _round2(avg_p),
            "fleet_weighted_kg_per_100km": _round2(fleet_w),
            "estimated_cost_per_100km": _round2(est_cost),
        }
    return expected


def _parse_numbers_from_text(text: str) -> List[float]:
    nums: List[float] = []
    for m in re.finditer(r'(?<![\w.])[-+]?\d+(?:\.\d+)?', text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def _has_two_decimal_format(value: str) -> bool:
    v = (value or "").strip()
    m = re.match(r'^-?\d+\.\d{2}$', v)
    return m is not None


def _get_section_bullets(markdown: str, heading_name: str, next_heading_name: Optional[str] = None) -> List[str]:
    lines = markdown.splitlines()

    def is_heading_line(idx: int, name: str) -> bool:
        s = lines[idx].strip()
        s_clean = re.sub(r'^#{1,6}\s*', '', s).strip().rstrip(':').lower()
        return s_clean == name.lower()

    start_idx = None
    for i in range(len(lines)):
        if is_heading_line(i, heading_name):
            start_idx = i
            break
    if start_idx is None:
        return []

    end_idx = len(lines)
    if next_heading_name:
        for j in range(start_idx + 1, len(lines)):
            if is_heading_line(j, next_heading_name):
                end_idx = j
                break

    bullets: List[str] = []
    for k in range(start_idx + 1, end_idx):
        line = lines[k].rstrip()
        if re.match(r'^\s*[-*]\s+', line):
            bullets.append(line.strip())
    return bullets


def _headings_present(markdown: str) -> bool:
    lines = markdown.splitlines()
    found_key = False
    found_action = False
    for line in lines:
        s = line.strip()
        s_clean = re.sub(r'^#{1,6}\s*', '', s).strip().rstrip(':').lower()
        if s_clean == "key findings":
            found_key = True
        if s_clean == "action items":
            found_action = True
    return found_key and found_action


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "consumption_summary_exists_and_columns": 0.0,
        "consumption_summary_groups_complete": 0.0,
        "consumption_summary_values_correct": 0.0,
        "consumption_summary_numeric_format_2dp": 0.0,
        "region_cost_exists_and_columns": 0.0,
        "region_cost_values_correct": 0.0,
        "region_cost_numeric_format_2dp": 0.0,
        "meeting_notes_headings": 0.0,
        "meeting_notes_key_findings_content": 0.0,
        "meeting_notes_action_items_count": 0.0,
        "exec_email_exists": 0.0,
        "exec_email_word_limit_and_metric_reference": 0.0,
        "exec_email_tone_neutral_confident": 0.0,
    }

    fleet_path = workspace / "input" / "fleet_runs.csv"
    price_path = workspace / "input" / "hydrogen_prices.csv"
    cons_path = workspace / "output" / "consumption_summary.csv"
    region_cost_path = workspace / "output" / "region_cost_estimates.csv"
    notes_path = workspace / "output" / "meeting_notes.md"
    email_path = workspace / "output" / "exec_email_rewrite.txt"

    fleet_header, fleet_rows = _safe_read_csv(fleet_path)
    price_header, price_rows = _safe_read_csv(price_path)

    if not fleet_rows or not price_rows:
        return scores

    avg_price_by_region = _compute_region_avg_price(price_rows)
    expected_consumption = _compute_expected_consumption(fleet_rows, avg_price_by_region)
    expected_region_costs = _compute_expected_region_costs(fleet_rows, avg_price_by_region)

    expected_numbers: List[float] = []
    for v in expected_consumption.values():
        expected_numbers.append(v["avg_kg_per_100km"])
        expected_numbers.append(v["median_kg_per_100km"])
        expected_numbers.append(v["est_cost_per_100km"])
    for v in expected_region_costs.values():
        expected_numbers.append(v["avg_price_per_kg"])
        expected_numbers.append(v["fleet_weighted_kg_per_100km"])
        expected_numbers.append(v["estimated_cost_per_100km"])

    cons_header, cons_rows = _safe_read_csv(cons_path)
    required_cons_header = [
        "vehicle_id",
        "region",
        "route_type",
        "trips",
        "total_distance_km",
        "total_hydrogen_kg",
        "avg_kg_per_100km",
        "median_kg_per_100km",
        "est_cost_per_100km",
    ]
    if cons_rows is not None and cons_header == required_cons_header:
        scores["consumption_summary_exists_and_columns"] = 1.0

        student_map: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for row in cons_rows:
            k = (row.get("vehicle_id", "").strip(), row.get("region", "").strip(), row.get("route_type", "").strip())
            student_map[k] = row

        if set(student_map.keys()) == set(expected_consumption.keys()) and len(student_map) == len(expected_consumption):
            scores["consumption_summary_groups_complete"] = 1.0

        values_ok = True
        for k, exp_vals in expected_consumption.items():
            row = student_map.get(k)
            if not row:
                values_ok = False
                break
            comp_cols = ["trips", "total_distance_km", "total_hydrogen_kg", "avg_kg_per_100km", "median_kg_per_100km", "est_cost_per_100km"]
            for col in comp_cols:
                sval = (row.get(col) or "").strip()
                if sval == "":
                    values_ok = False
                    break
                f = _to_float(sval)
                if f is None:
                    values_ok = False
                    break
                if col == "trips":
                    if int(round(f)) != int(exp_vals[col]):
                        values_ok = False
                        break
                else:
                    if abs(f - float(exp_vals[col])) > 0.01:
                        values_ok = False
                        break
            if not values_ok:
                break
        if values_ok:
            scores["consumption_summary_values_correct"] = 1.0

        format_ok = True
        num_cols_2dp = ["total_distance_km", "total_hydrogen_kg", "avg_kg_per_100km", "median_kg_per_100km", "est_cost_per_100km"]
        for row in cons_rows:
            for col in num_cols_2dp:
                sval = (row.get(col) or "").strip()
                if not _has_two_decimal_format(sval):
                    format_ok = False
                    break
            if not format_ok:
                break
        if format_ok:
            scores["consumption_summary_numeric_format_2dp"] = 1.0

    rc_header, rc_rows = _safe_read_csv(region_cost_path)
    required_rc_header = ["region", "avg_price_per_kg", "fleet_weighted_kg_per_100km", "estimated_cost_per_100km"]
    if rc_rows is not None and rc_header == required_rc_header:
        scores["region_cost_exists_and_columns"] = 1.0

        rc_map: Dict[str, Dict[str, str]] = {}
        for row in rc_rows:
            rc_map[(row.get("region") or "").strip()] = row

        rc_ok = True
        if set(rc_map.keys()) != set(expected_region_costs.keys()):
            rc_ok = False
        else:
            for reg, exp in expected_region_costs.items():
                row = rc_map.get(reg)
                if not row:
                    rc_ok = False
                    break
                for col in ["avg_price_per_kg", "fleet_weighted_kg_per_100km", "estimated_cost_per_100km"]:
                    sval = (row.get(col) or "").strip()
                    f = _to_float(sval)
                    if f is None or abs(f - float(exp[col])) > 0.01:
                        rc_ok = False
                        break
                if not rc_ok:
                    break
        if rc_ok:
            scores["region_cost_values_correct"] = 1.0

        format_ok2 = True
        for row in rc_rows:
            for col in ["avg_price_per_kg", "fleet_weighted_kg_per_100km", "estimated_cost_per_100km"]:
                sval = (row.get(col) or "").strip()
                if not _has_two_decimal_format(sval):
                    format_ok2 = False
                    break
            if not format_ok2:
                break
        if format_ok2:
            scores["region_cost_numeric_format_2dp"] = 1.0

    notes_text = _safe_read_text(notes_path) or ""
    if notes_text:
        if _headings_present(notes_text):
            scores["meeting_notes_headings"] = 1.0

        kf_bullets = _get_section_bullets(notes_text, "Key findings", "Action items")
        ai_bullets = _get_section_bullets(notes_text, "Action items", None)

        kf_count_ok = 3 <= len(kf_bullets) <= 5
        kf_metric_ok = False
        regions = set(expected_region_costs.keys())
        route_types = set(["Urban", "Highway", "Mixed"])
        expected_set = expected_numbers[:]
        for b in kf_bullets:
            has_region = any(r.lower() in b.lower() for r in regions)
            has_route = any(rt.lower() in b.lower() for rt in route_types)
            nums = _parse_numbers_from_text(b)
            num_matches = False
            for n in nums:
                if any(abs(n - en) <= 0.01 for en in expected_set):
                    num_matches = True
                    break
            if has_region and has_route and num_matches:
                kf_metric_ok = True
                break
        if kf_count_ok and kf_metric_ok:
            scores["meeting_notes_key_findings_content"] = 1.0

        if len(ai_bullets) >= 3:
            scores["meeting_notes_action_items_count"] = 1.0

    email_text = _safe_read_text(email_path)
    if email_text is not None:
        scores["exec_email_exists"] = 1.0
        words = re.findall(r'\S+', email_text.strip())
        word_limit_ok = len(words) <= 120 and len(words) > 0

        nums = _parse_numbers_from_text(email_text)
        has_metric_ref = False
        for n in nums:
            if any(abs(n - en) <= 0.01 for en in expected_numbers):
                has_metric_ref = True
                break
        if word_limit_ok and has_metric_ref:
            scores["exec_email_word_limit_and_metric_reference"] = 1.0

        bad_terms = ["sorry", "rambl", "not sure", "jumble", "apolog"]
        tone_ok = True
        lower_email = email_text.lower()
        for t in bad_terms:
            if t in lower_email:
                tone_ok = False
                break
        if tone_ok:
            scores["exec_email_tone_neutral_confident"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()