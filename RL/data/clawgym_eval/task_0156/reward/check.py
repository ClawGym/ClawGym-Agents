import csv
import json
import math
import sys
from pathlib import Path
from datetime import datetime
from statistics import median


def _read_csv_dicts(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _parse_date_ymd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _month_from_date_str(s: str):
    d = _parse_date_ymd(s)
    if d is None:
        return None
    return f"{d.year:04d}-{d.month:02d}"


def _format_money(amount: float) -> str:
    return f"{amount:.2f}"


def _format_pct_one_decimal(p: float) -> str:
    # Standard rounding to one decimal
    return f"{round(p, 1):.1f}"


def _is_two_decimals(s: str) -> bool:
    if not isinstance(s, str):
        return False
    parts = s.split(".")
    if len(parts) != 2:
        return False
    if not parts[0].lstrip("-").isdigit():
        return False
    return len(parts[1]) == 2 and parts[1].isdigit()


def _safe_float(s):
    try:
        return float(s)
    except Exception:
        return None


def _sum_by_date(rows, date_key: str, value_key: str):
    sums = {}
    for r in rows:
        date = r.get(date_key, "")
        try:
            val = float(r.get(value_key, 0))
        except Exception:
            return None
        if date not in sums:
            sums[date] = 0.0
        sums[date] += val
    return sums


def _compute_expected_per_match(match_rows, travel_rows):
    # travel: sum cost for same date
    travel_map = _sum_by_date(travel_rows, "date", "cost_chf") if travel_rows is not None else {}
    if travel_map is None:
        return None
    expected = []
    for r in match_rows:
        date = r.get("date", "")
        op = r.get("opponent", "")
        ha = r.get("home_away", "")
        ticket_str = r.get("ticket_chf", "")
        t_val = _safe_float(ticket_str)
        if date == "" or op == "" or ha == "" or t_val is None:
            return None
        travel_cost = travel_map.get(date, 0.0)
        per_total = t_val + travel_cost
        expected.append({
            "date": date,
            "opponent": op,
            "home_away": ha,
            "ticket_chf": _format_money(t_val),
            "travel_same_day_chf": _format_money(travel_cost),
            "per_match_total_chf": _format_money(per_total),
        })
    # sort ascending by date
    expected.sort(key=lambda x: x["date"])
    return expected


def _compute_expected_monthly(match_rows, travel_rows, merch_rows):
    # tickets by month
    tickets_by_month = {}
    for r in match_rows or []:
        m = _month_from_date_str(r.get("date", ""))
        v = _safe_float(r.get("ticket_chf", ""))
        if m is None or v is None:
            return None
        tickets_by_month[m] = tickets_by_month.get(m, 0.0) + v
    # travel by month
    travel_by_month = {}
    for r in travel_rows or []:
        m = _month_from_date_str(r.get("date", ""))
        v = _safe_float(r.get("cost_chf", ""))
        if m is None or v is None:
            return None
        travel_by_month[m] = travel_by_month.get(m, 0.0) + v
    # merch by month
    merch_by_month = {}
    for r in merch_rows or []:
        m = _month_from_date_str(r.get("date", ""))
        v = _safe_float(r.get("price_chf", ""))
        if m is None or v is None:
            return None
        merch_by_month[m] = merch_by_month.get(m, 0.0) + v
    all_months = sorted(set(list(tickets_by_month.keys()) + list(travel_by_month.keys()) + list(merch_by_month.keys())))
    expected = []
    for m in all_months:
        t = tickets_by_month.get(m, 0.0)
        tr = travel_by_month.get(m, 0.0)
        me = merch_by_month.get(m, 0.0)
        total = t + tr + me
        expected.append({
            "month": m,
            "tickets_chf": _format_money(t),
            "travel_chf": _format_money(tr),
            "merch_chf": _format_money(me),
            "total_chf": _format_money(total),
        })
    return expected


def _compute_expected_season(match_rows, travel_rows, merch_rows, expected_per_match, expected_monthly):
    if match_rows is None or travel_rows is None or merch_rows is None or expected_per_match is None or expected_monthly is None:
        return None
    # totals
    total_tickets = 0.0
    tickets_list = []
    for r in match_rows:
        v = _safe_float(r.get("ticket_chf", ""))
        if v is None:
            return None
        total_tickets += v
        tickets_list.append(v)
    total_travel = 0.0
    for r in travel_rows:
        v = _safe_float(r.get("cost_chf", ""))
        if v is None:
            return None
        total_travel += v
    total_merch = 0.0
    for r in merch_rows:
        v = _safe_float(r.get("price_chf", ""))
        if v is None:
            return None
        total_merch += v
    overall_total = total_tickets + total_travel + total_merch
    matches_attended = len(match_rows)
    # average per match from expected per match totals
    per_totals = []
    for r in expected_per_match:
        v = _safe_float(r.get("per_match_total_chf", ""))
        if v is None:
            return None
        per_totals.append(v)
    avg_per_match = sum(per_totals) / len(per_totals) if per_totals else 0.0
    # median ticket
    med_ticket = float(median(tickets_list)) if tickets_list else 0.0
    # top months (by total_chf descending, then month ascending for determinism)
    monthly_totals = [(r["month"], _safe_float(r["total_chf"])) for r in expected_monthly]
    if any(v is None for _, v in monthly_totals):
        return None
    monthly_totals.sort(key=lambda x: (-x[1], x[0]))
    top1 = monthly_totals[0][0] if monthly_totals else ""
    top2 = monthly_totals[1][0] if len(monthly_totals) > 1 else ""
    # shares
    if overall_total > 0:
        tickets_share = total_tickets / overall_total * 100.0
        travel_share = total_travel / overall_total * 100.0
        merch_share = total_merch / overall_total * 100.0
    else:
        tickets_share = travel_share = merch_share = 0.0
    # top home opponents by ticket
    home_rows = [r for r in match_rows if r.get("home_away", "") == "home"]
    # sort by ticket desc then opponent asc
    home_sorted = sorted(
        home_rows,
        key=lambda r: (-_safe_float(r.get("ticket_chf", "0")) if _safe_float(r.get("ticket_chf", "0")) is not None else 0.0,
                       r.get("opponent", ""))
    )
    top_home = [r.get("opponent", "") for r in home_sorted[:2]]
    top_home_str = ";".join(top_home)

    expected = {
        "total_tickets_chf": _format_money(total_tickets),
        "total_travel_chf": _format_money(total_travel),
        "total_merch_chf": _format_money(total_merch),
        "overall_total_chf": _format_money(overall_total),
        "matches_attended": str(matches_attended),
        "average_per_match_chf": _format_money(avg_per_match),
        "median_ticket_chf": _format_money(med_ticket),
        "top_month_1": top1,
        "top_month_2": top2,
        "tickets_share_pct": _format_pct_one_decimal(tickets_share),
        "travel_share_pct": _format_pct_one_decimal(travel_share),
        "merch_share_pct": _format_pct_one_decimal(merch_share),
        "top_home_opponents_by_ticket": top_home_str,
    }
    return expected


def _read_output_csv_rows(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def _round_to_nearest_10_half_up(x: float) -> int:
    # For positive numbers, half-up rounding to nearest 10
    return int(math.floor((x + 5) / 10.0) * 10)


def _ceil_to_next_multiple(x: float, base: int) -> int:
    return int(math.ceil(x / base) * base)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "per_match_costs_exists_and_structure": 0.0,
        "per_match_costs_values_and_sort": 0.0,
        "monthly_breakdown_correct": 0.0,
        "season_summary_metrics_complete": 0.0,
        "season_summary_values_correct": 0.0,
        "fan_budget_report_placeholders_and_values": 0.0,
        "fan_budget_recommendations": 0.0,
    }

    # Load inputs
    match_path = workspace / "input" / "match_attendance.csv"
    travel_path = workspace / "input" / "travel.csv"
    merch_path = workspace / "input" / "merch.csv"
    draft_path = workspace / "input" / "draft_budget.md"

    match_rows, match_fields = _read_csv_dicts(match_path) if match_path.exists() else (None, None)
    travel_rows, travel_fields = _read_csv_dicts(travel_path) if travel_path.exists() else (None, None)
    merch_rows, merch_fields = _read_csv_dicts(merch_path) if merch_path.exists() else (None, None)

    # Compute expected structures only if inputs are present and parseable
    expected_per_match = None
    expected_monthly = None
    expected_season = None
    if match_rows is not None and travel_rows is not None and merch_rows is not None:
        expected_per_match = _compute_expected_per_match(match_rows, travel_rows)
        expected_monthly = _compute_expected_monthly(match_rows, travel_rows, merch_rows)
        if expected_per_match is not None and expected_monthly is not None:
            expected_season = _compute_expected_season(match_rows, travel_rows, merch_rows, expected_per_match, expected_monthly)

    # 1) per_match_costs.csv checks
    per_match_out = workspace / "output" / "per_match_costs.csv"
    per_rows = _read_output_csv_rows(per_match_out) if per_match_out.exists() else None
    expected_header_per = ["date", "opponent", "home_away", "ticket_chf", "travel_same_day_chf", "per_match_total_chf"]
    if per_rows is not None and len(per_rows) >= 1:
        header = per_rows[0]
        structure_ok = header == expected_header_per
        values_ok = False
        if structure_ok and expected_per_match is not None:
            # Compare row counts and values
            data_rows = per_rows[1:]
            if len(data_rows) == len(expected_per_match):
                # Build parsed rows as dicts
                rows_ok = True
                # Check order by date ascending
                dates_in_file = [r[0] if len(r) >= 1 else "" for r in data_rows]
                if dates_in_file != sorted(dates_in_file):
                    rows_ok = False
                # Compare each row with expected
                for i, exp in enumerate(expected_per_match):
                    row = data_rows[i] if i < len(data_rows) else None
                    if row is None or len(row) != 6:
                        rows_ok = False
                        break
                    comp = {
                        "date": row[0],
                        "opponent": row[1],
                        "home_away": row[2],
                        "ticket_chf": row[3],
                        "travel_same_day_chf": row[4],
                        "per_match_total_chf": row[5],
                    }
                    if comp != exp:
                        rows_ok = False
                        break
                    # Check numeric format for numeric columns
                    if not (_is_two_decimals(comp["ticket_chf"]) and _is_two_decimals(comp["travel_same_day_chf"]) and _is_two_decimals(comp["per_match_total_chf"])):
                        rows_ok = False
                        break
                values_ok = rows_ok
        if structure_ok:
            scores["per_match_costs_exists_and_structure"] = 1.0
        if values_ok:
            scores["per_match_costs_values_and_sort"] = 1.0

    # 2) monthly_breakdown.csv
    monthly_out = workspace / "output" / "monthly_breakdown.csv"
    mon_rows = _read_output_csv_rows(monthly_out) if monthly_out.exists() else None
    expected_header_monthly = ["month", "tickets_chf", "travel_chf", "merch_chf", "total_chf"]
    if mon_rows is not None and len(mon_rows) >= 1:
        header = mon_rows[0]
        if header == expected_header_monthly and expected_monthly is not None:
            # Build map from month -> row dict
            got_map = {}
            ok = True
            for row in mon_rows[1:]:
                if len(row) != 5:
                    ok = False
                    break
                m = row[0]
                got_map[m] = {
                    "month": row[0],
                    "tickets_chf": row[1],
                    "travel_chf": row[2],
                    "merch_chf": row[3],
                    "total_chf": row[4],
                }
            exp_map = {r["month"]: r for r in expected_monthly}
            if set(got_map.keys()) != set(exp_map.keys()):
                ok = False
            else:
                for m, exp in exp_map.items():
                    g = got_map.get(m)
                    if g != exp:
                        ok = False
                        break
                    # numeric formatting check
                    if not (_is_two_decimals(g["tickets_chf"]) and _is_two_decimals(g["travel_chf"]) and _is_two_decimals(g["merch_chf"]) and _is_two_decimals(g["total_chf"])):
                        ok = False
                        break
            if ok:
                scores["monthly_breakdown_correct"] = 1.0

    # 3) season_summary.csv
    season_out = workspace / "output" / "season_summary.csv"
    season_rows = _read_output_csv_rows(season_out) if season_out.exists() else None
    expected_metrics_set = {
        "total_tickets_chf",
        "total_travel_chf",
        "total_merch_chf",
        "overall_total_chf",
        "matches_attended",
        "average_per_match_chf",
        "median_ticket_chf",
        "top_month_1",
        "top_month_2",
        "tickets_share_pct",
        "travel_share_pct",
        "merch_share_pct",
        "top_home_opponents_by_ticket",
    }
    if season_rows is not None and len(season_rows) >= 1:
        header = season_rows[0]
        if header == ["metric", "value"]:
            # Build map
            got = {}
            for row in season_rows[1:]:
                if len(row) != 2:
                    got = None
                    break
                got[row[0]] = row[1]
            if got is not None:
                if set(got.keys()) == expected_metrics_set:
                    scores["season_summary_metrics_complete"] = 1.0
                if expected_season is not None and set(got.keys()) == expected_metrics_set:
                    # Validate values with formatting rules
                    values_ok = True
                    # Amounts: two decimals
                    amount_keys_two_dec = [
                        "total_tickets_chf",
                        "total_travel_chf",
                        "total_merch_chf",
                        "overall_total_chf",
                        "average_per_match_chf",
                        "median_ticket_chf",
                    ]
                    for k in amount_keys_two_dec:
                        if got.get(k) != expected_season[k] or not _is_two_decimals(got.get(k, "")):
                            values_ok = False
                            break
                    # Percentages: one decimal equality
                    if values_ok:
                        pct_keys = ["tickets_share_pct", "travel_share_pct", "merch_share_pct"]
                        for k in pct_keys:
                            # Expect exactly one decimal place
                            v = got.get(k, "")
                            exp = expected_season[k]
                            # Check one decimal formatting
                            try:
                                parts = v.split(".")
                                if len(parts) != 2 or len(parts[1]) != 1 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit():
                                    values_ok = False
                                    break
                            except Exception:
                                values_ok = False
                                break
                            if v != exp:
                                values_ok = False
                                break
                    # Matches attended: accept any numeric string representing integer
                    if values_ok:
                        v = got.get("matches_attended", "")
                        try:
                            vi = int(float(v))
                            if str(vi) != expected_season["matches_attended"]:
                                values_ok = False
                        except Exception:
                            values_ok = False
                    # Top months and opponents exact
                    if values_ok:
                        if got.get("top_month_1") != expected_season["top_month_1"]:
                            values_ok = False
                        if got.get("top_month_2") != expected_season["top_month_2"]:
                            values_ok = False
                        if got.get("top_home_opponents_by_ticket") != expected_season["top_home_opponents_by_ticket"]:
                            values_ok = False
                    if values_ok:
                        scores["season_summary_values_correct"] = 1.0

    # 4) fan_budget_report.md
    report_out = workspace / "output" / "fan_budget_report.md"
    report_text = None
    if report_out.exists():
        try:
            report_text = report_out.read_text(encoding="utf-8")
        except Exception:
            report_text = None
    if report_text is not None:
        # placeholders replaced: No '{{' present
        placeholders_ok = "{{" not in report_text and "}}" not in report_text
        values_ok = False
        if expected_season is not None:
            # Check presence of expected values
            tokens = [
                expected_season["total_tickets_chf"],
                expected_season["total_travel_chf"],
                expected_season["total_merch_chf"],
                expected_season["overall_total_chf"],
                expected_season["average_per_match_chf"],
                expected_season["median_ticket_chf"],
                expected_season["top_month_1"],
                expected_season["top_month_2"],
            ]
            # matches_attended token
            tokens.append(expected_season["matches_attended"])
            values_ok = all(t in report_text for t in tokens)
        if placeholders_ok and values_ok:
            scores["fan_budget_report_placeholders_and_values"] = 1.0

        # Recommendations section and numbers:
        # - Must have a "Recommendations" section marker (case-insensitive)
        # - At least two bullet points following somewhere
        # - Include monthly cap (median monthly total rounded to nearest 10 CHF, 0.5 up)
        # - Include per-match budget (avg per match rounded up to next multiple of 5)
        rec_ok = False
        if expected_monthly is not None and expected_season is not None:
            # compute median monthly total
            monthly_totals = [_safe_float(r["total_chf"]) for r in expected_monthly]
            if monthly_totals and all(v is not None for v in monthly_totals):
                med_val = float(median(monthly_totals))
                monthly_cap = _round_to_nearest_10_half_up(med_val)
                avg_per_match = _safe_float(expected_season["average_per_match_chf"]) or 0.0
                per_match_cap = _ceil_to_next_multiple(avg_per_match, 5)
                # parse recommendations
                lower = report_text.lower()
                rec_idx = lower.find("recommendations")
                if rec_idx != -1:
                    # Count bullets in entire file (simple heuristic)
                    bullets = [line for line in report_text.splitlines() if line.strip().startswith(("-", "*"))]
                    has_two_bullets = len(bullets) >= 2
                    # numbers present (as integers)
                    has_numbers = (str(monthly_cap) in report_text) and (str(per_match_cap) in report_text)
                    if has_two_bullets and has_numbers:
                        rec_ok = True
        if rec_ok:
            scores["fan_budget_recommendations"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()