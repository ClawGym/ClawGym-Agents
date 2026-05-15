import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _parse_int_like(s: str) -> Optional[int]:
    if s is None:
        return None
    try:
        cleaned = s.strip().replace(",", "").replace("$", "")
        if cleaned == "":
            return None
        val = float(cleaned)
        if math.isfinite(val):
            return int(round(val))
        return None
    except Exception:
        return None


def _parse_float_like(s: str) -> Optional[float]:
    if s is None:
        return None
    try:
        cleaned = s.strip().replace(",", "").replace("$", "").replace("%", "")
        if cleaned == "":
            return None
        val = float(cleaned)
        return val
    except Exception:
        return None


def _is_int_string(s: str) -> bool:
    if s is None:
        return False
    cleaned = s.strip().replace(",", "").replace("$", "")
    if cleaned == "":
        return False
    # Disallow decimals
    if "." in cleaned:
        return False
    # Allow optional leading minus for completeness
    if cleaned.startswith("-"):
        return cleaned[1:].isdigit()
    return cleaned.isdigit()


def _round_dollars(value: float) -> int:
    return int(round(value))


def _round_margin_rate(value: float) -> float:
    return round(value, 4)


def _fmt_float_4(value: float) -> str:
    return f"{value:.4f}"


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compute_expected_from_input(input_rows: List[Dict[str, str]]) -> Tuple[Dict[Tuple[str, str], dict], Dict[str, dict]]:
    expected_by_dept: Dict[Tuple[str, str], dict] = {}
    roll_sums: Dict[str, dict] = {}
    for row in input_rows:
        period = row.get("period", "").strip()
        dept = row.get("department", "").strip()
        rev = _parse_int_like(row.get("revenue", ""))
        exp = _parse_int_like(row.get("expense", ""))
        enc = _parse_int_like(row.get("encounters", ""))

        if None in (rev, exp, enc) or not period or not dept:
            continue

        margin = rev - exp
        mr = 0.0 if rev == 0 else _round_margin_rate(margin / rev)
        epe = _round_dollars(exp / enc) if enc != 0 else 0
        rpe = _round_dollars(rev / enc) if enc != 0 else 0

        expected_by_dept[(period, dept)] = {
            "period": period,
            "department": dept,
            "revenue": rev,
            "expense": exp,
            "margin": margin,
            "margin_rate": mr,
            "encounters": enc,
            "expense_per_encounter": epe,
            "revenue_per_encounter": rpe,
        }

        r = roll_sums.setdefault(period, {"revenue": 0, "expense": 0, "encounters": 0})
        r["revenue"] += rev
        r["expense"] += exp
        r["encounters"] += enc

    expected_rollup: Dict[str, dict] = {}
    for period, agg in roll_sums.items():
        total_rev = agg["revenue"]
        total_exp = agg["expense"]
        total_enc = agg["encounters"]
        total_margin = total_rev - total_exp
        mr = 0.0 if total_rev == 0 else _round_margin_rate(total_margin / total_rev)
        epe = _round_dollars(total_exp / total_enc) if total_enc != 0 else 0
        rpe = _round_dollars(total_rev / total_enc) if total_enc != 0 else 0
        expected_rollup[period] = {
            "period": period,
            "total_revenue": total_rev,
            "total_expense": total_exp,
            "total_margin": total_margin,
            "margin_rate": mr,
            "total_encounters": total_enc,
            "expense_per_encounter": epe,
            "revenue_per_encounter": rpe,
        }
    return expected_by_dept, expected_rollup


def _compute_cost_savings(input_rows: List[Dict[str, str]]) -> List[dict]:
    per: Dict[str, Dict[str, dict]] = {}
    for row in input_rows:
        period = row.get("period", "").strip()
        dept = row.get("department", "").strip()
        rev = _parse_int_like(row.get("revenue", ""))
        exp = _parse_int_like(row.get("expense", ""))
        enc = _parse_int_like(row.get("encounters", ""))
        if None in (rev, exp, enc) or not period or not dept:
            continue
        per.setdefault(period, {})[dept] = {"revenue": rev, "expense": exp, "encounters": enc}

    if not per:
        return []

    periods_sorted = sorted(per.keys())
    latest = periods_sorted[-1]
    prior = periods_sorted[-2] if len(periods_sorted) >= 2 else None
    if prior is None:
        return []

    results = []
    for dept in set(list(per[prior].keys()) + list(per[latest].keys())):
        if dept not in per[latest] or dept not in per[prior]:
            continue
        latest_enc = per[latest][dept]["encounters"]
        prior_enc = per[prior][dept]["encounters"]
        latest_exp = per[latest][dept]["expense"]
        prior_exp = per[prior][dept]["expense"]

        latest_epe = _round_dollars(latest_exp / latest_enc) if latest_enc != 0 else 0
        prior_epe = _round_dollars(prior_exp / prior_enc) if prior_enc != 0 else 0

        if latest_enc <= prior_enc and latest_epe > prior_epe:
            delta = latest_epe - prior_epe
            savings = delta * latest_enc
            if savings > 0:
                results.append({
                    "department": dept,
                    "prior_period": prior,
                    "latest_period": latest,
                    "prior_epe": prior_epe,
                    "latest_epe": latest_epe,
                    "savings": savings,
                    "delta": delta,
                })

    results.sort(key=lambda x: (x["delta"], x["savings"]), reverse=True)
    top3 = results[:3]
    return top3


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "architecture_doc_exists": 0.0,
        "architecture_solution_architecture": 0.0,
        "architecture_kpis_defined": 0.0,
        "architecture_validation_strategy": 0.0,
        "summary_by_department_exists": 0.0,
        "summary_by_department_header": 0.0,
        "summary_by_department_rows_match": 0.0,
        "summary_by_department_values_correct": 0.0,
        "rollup_by_month_exists": 0.0,
        "rollup_by_month_header": 0.0,
        "rollup_by_month_rows_match": 0.0,
        "rollup_by_month_values_correct": 0.0,
        "rollup_sums_match_department": 0.0,
        "monetary_rounding_integers": 0.0,
        "margin_rate_rounding": 0.0,
        "cost_savings_exists": 0.0,
        "cost_savings_top_departments": 0.0,
        "cost_savings_numbers_correct": 0.0,
        "analyze_script_exists": 0.0,
        "validation_report_exists": 0.0,
        "validation_status_passed": 0.0,
        "validation_run_captured": 0.0,
        "email_final_exists": 0.0,
        "email_includes_margin_rate": 0.0,
        "email_lists_savings": 0.0,
        "email_under_150_words": 0.0,
    }

    # Load input
    input_csv_path = workspace / "input" / "finance_monthly.csv"
    input_rows = _read_csv_rows(input_csv_path) or []

    # Compute expected outputs if input is valid
    expected_by_dept: Dict[Tuple[str, str], dict] = {}
    expected_rollup: Dict[str, dict] = {}
    cost_savings_expected: List[dict] = []
    if input_rows:
        expected_by_dept, expected_rollup = _compute_expected_from_input(input_rows)
        cost_savings_expected = _compute_cost_savings(input_rows)

    # 1) Documentation checks
    arch_path = workspace / "docs" / "architecture.md"
    arch_text = _safe_read_text(arch_path)
    if arch_text is not None:
        scores["architecture_doc_exists"] = 1.0
        lower = arch_text.lower()
        has_data_source = ("data source" in lower) or ("input/finance_monthly.csv" in lower) or ("input" in lower and "finance_monthly.csv" in lower)
        has_transform = ("transform" in lower) or ("compute" in lower) or ("calculation" in lower) or ("processing" in lower)
        has_outputs = ("outputs" in lower) or ("output/summary_by_department.csv" in lower) or ("output/rollup_by_month.csv" in lower)
        has_validation = ("validation" in lower) and ("report" in lower or "failure" in lower or "failed" in lower or "checks" in lower)
        mentions_monthly_local = ("monthly" in lower) and (("personal computer" in lower) or ("local" in lower))
        if has_data_source and has_transform and has_outputs and has_validation and mentions_monthly_local:
            scores["architecture_solution_architecture"] = 1.0

        has_margin_def = ("margin" in lower and "revenue - expense" in lower)
        has_margin_rate_def = ("margin_rate" in lower and ("margin/revenue" in lower or "margin / revenue" in lower))
        has_epe = ("expense_per_encounter" in lower)
        has_rpe = ("revenue_per_encounter" in lower)
        has_rollup_reconcile = ("rollup" in lower or "aggregate" in lower) and ("department" in lower or "departments" in lower) and ("reconcile" in lower or "sum" in lower or "match" in lower)
        if has_margin_def and has_margin_rate_def and has_epe and has_rpe and has_rollup_reconcile:
            scores["architecture_kpis_defined"] = 1.0

        mentions_recompute = ("recompute" in lower or "re-compute" in lower) and ("totals" in lower or "metrics" in lower)
        mentions_rollup_eq = ("rollup" in lower and ("sum" in lower or "equals" in lower or "match" in lower))
        mentions_margin_id = ("margin == revenue - expense" in lower) or ("margin equals revenue - expense" in lower) or ("margin_rate" in lower and "margin/revenue" in lower)
        mentions_report = ("validation_report.json" in lower) or ("report.json" in lower) or ("status" in lower)
        if mentions_recompute and mentions_rollup_eq and mentions_margin_id and mentions_report:
            scores["architecture_validation_strategy"] = 1.0

    # 2) Output CSVs checks
    summary_path = workspace / "output" / "summary_by_department.csv"
    rollup_path = workspace / "output" / "rollup_by_month.csv"
    summary_rows = _read_csv_rows(summary_path)
    rollup_rows = _read_csv_rows(rollup_path)

    expected_summary_header = [
        "period",
        "department",
        "revenue",
        "expense",
        "margin",
        "margin_rate",
        "encounters",
        "expense_per_encounter",
        "revenue_per_encounter",
    ]
    expected_rollup_header = [
        "period",
        "total_revenue",
        "total_expense",
        "total_margin",
        "margin_rate",
        "total_encounters",
        "expense_per_encounter",
        "revenue_per_encounter",
    ]

    # Track rounding checks
    summary_mr_exact4 = False
    rollup_mr_exact4 = False
    monetary_all_int_like = True

    if summary_rows is not None:
        scores["summary_by_department_exists"] = 1.0
        try:
            with summary_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
            if header == expected_summary_header:
                scores["summary_by_department_header"] = 1.0
        except Exception:
            pass

        if expected_by_dept:
            observed_keys = {(r.get("period", "").strip(), r.get("department", "").strip()) for r in summary_rows}
            expected_keys = set(expected_by_dept.keys())
            if observed_keys == expected_keys and "" not in [k[0] for k in observed_keys] and "" not in [k[1] for k in observed_keys]:
                scores["summary_by_department_rows_match"] = 1.0

            values_ok = True
            mr_exact_ok = True
            for r in summary_rows:
                per = r.get("period", "").strip()
                dep = r.get("department", "").strip()
                key = (per, dep)
                expd = expected_by_dept.get(key)
                if not expd:
                    values_ok = False
                    continue

                rev_v = _parse_int_like(r.get("revenue", ""))
                exp_v = _parse_int_like(r.get("expense", ""))
                mar_v = _parse_int_like(r.get("margin", ""))
                enc_v = _parse_int_like(r.get("encounters", ""))
                epe_v = _parse_int_like(r.get("expense_per_encounter", ""))
                rpe_v = _parse_int_like(r.get("revenue_per_encounter", ""))
                mr_str = (r.get("margin_rate", "") or "").strip()
                mr_v = _parse_float_like(mr_str)

                # monetary values should be integer-like strings
                for fld in ["revenue", "expense", "margin", "expense_per_encounter", "revenue_per_encounter"]:
                    sval = r.get(fld, "")
                    if not _is_int_string(sval):
                        monetary_all_int_like = False

                if None in (rev_v, exp_v, mar_v, enc_v, epe_v, rpe_v) or mr_v is None:
                    values_ok = False
                else:
                    if rev_v != expd["revenue"] or exp_v != expd["expense"] or mar_v != expd["margin"] or enc_v != expd["encounters"]:
                        values_ok = False
                    if epe_v != expd["expense_per_encounter"] or rpe_v != expd["revenue_per_encounter"]:
                        values_ok = False
                    if not _approx_equal(mr_v, expd["margin_rate"], tol=0.00005):
                        values_ok = False
                    # exact 4-decimal formatting check
                    expected_mr_str = _fmt_float_4(expd["margin_rate"])
                    if mr_str != expected_mr_str:
                        mr_exact_ok = False

            if values_ok:
                scores["summary_by_department_values_correct"] = 1.0
            if mr_exact_ok:
                summary_mr_exact4 = True

    if rollup_rows is not None:
        scores["rollup_by_month_exists"] = 1.0
        try:
            with rollup_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
            if header == expected_rollup_header:
                scores["rollup_by_month_header"] = 1.0
        except Exception:
            pass

        if expected_rollup:
            observed_periods = {r.get("period", "").strip() for r in rollup_rows}
            if observed_periods == set(expected_rollup.keys()) and "" not in observed_periods:
                scores["rollup_by_month_rows_match"] = 1.0

            values_ok = True
            mr_exact_ok = True
            for r in rollup_rows:
                per = r.get("period", "").strip()
                expd = expected_rollup.get(per)
                if not expd:
                    values_ok = False
                    continue
                tr = _parse_int_like(r.get("total_revenue", ""))
                te = _parse_int_like(r.get("total_expense", ""))
                tm = _parse_int_like(r.get("total_margin", ""))
                tec = _parse_int_like(r.get("total_encounters", ""))
                epe_v = _parse_int_like(r.get("expense_per_encounter", ""))
                rpe_v = _parse_int_like(r.get("revenue_per_encounter", ""))
                mr_str = (r.get("margin_rate", "") or "").strip()
                mr_v = _parse_float_like(mr_str)

                # monetary values should be integer-like strings
                for fld in ["total_revenue", "total_expense", "total_margin", "expense_per_encounter", "revenue_per_encounter"]:
                    sval = r.get(fld, "")
                    if not _is_int_string(sval):
                        monetary_all_int_like = False

                if None in (tr, te, tm, tec, epe_v, rpe_v) or mr_v is None:
                    values_ok = False
                else:
                    if tr != expd["total_revenue"] or te != expd["total_expense"] or tm != expd["total_margin"] or tec != expd["total_encounters"]:
                        values_ok = False
                    if epe_v != expd["expense_per_encounter"] or rpe_v != expd["revenue_per_encounter"]:
                        values_ok = False
                    if not _approx_equal(mr_v, expd["margin_rate"], tol=0.00005):
                        values_ok = False
                    expected_mr_str = _fmt_float_4(expd["margin_rate"])
                    if mr_str != expected_mr_str:
                        mr_exact_ok = False

            if values_ok:
                scores["rollup_by_month_values_correct"] = 1.0
            if mr_exact_ok:
                rollup_mr_exact4 = True

    # Combine rounding checks
    if summary_rows is not None and rollup_rows is not None and monetary_all_int_like:
        scores["monetary_rounding_integers"] = 1.0
    if summary_mr_exact4 and rollup_mr_exact4:
        scores["margin_rate_rounding"] = 1.0

    # Rollup sums match department per period
    if summary_rows is not None and rollup_rows is not None:
        try:
            sums_by_period = {}
            for r in summary_rows:
                per = r.get("period", "").strip()
                if per == "":
                    sums_by_period[per] = None
                    continue
                sums = sums_by_period.setdefault(per, {"revenue": 0, "expense": 0, "margin": 0, "encounters": 0})
                rev = _parse_int_like(r.get("revenue", ""))
                exp = _parse_int_like(r.get("expense", ""))
                mar = _parse_int_like(r.get("margin", ""))
                enc = _parse_int_like(r.get("encounters", ""))
                if None in (rev, exp, mar, enc):
                    sums_by_period[per] = None
                else:
                    if sums is not None:
                        sums["revenue"] += rev
                        sums["expense"] += exp
                        sums["margin"] += mar
                        sums["encounters"] += enc

            match_all = True
            for r in rollup_rows:
                per = r.get("period", "").strip()
                tr = _parse_int_like(r.get("total_revenue", ""))
                te = _parse_int_like(r.get("total_expense", ""))
                tm = _parse_int_like(r.get("total_margin", ""))
                tec = _parse_int_like(r.get("total_encounters", ""))
                if None in (tr, te, tm, tec) or sums_by_period.get(per) is None:
                    match_all = False
                    break
                exp_sum = sums_by_period[per]
                if tr != exp_sum["revenue"] or te != exp_sum["expense"] or tm != exp_sum["margin"] or tec != exp_sum["encounters"]:
                    match_all = False
                    break
            if match_all and len({r.get("period", "").strip() for r in rollup_rows}) == len(sums_by_period):
                scores["rollup_sums_match_department"] = 1.0
        except Exception:
            pass

    # 3) Cost savings checks
    cost_path = workspace / "output" / "cost_savings.md"
    cost_text = _safe_read_text(cost_path)
    if cost_text is not None:
        scores["cost_savings_exists"] = 1.0
        lines = [ln.strip() for ln in cost_text.splitlines() if ln.strip()]
        bullets = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
        if cost_savings_expected:
            all_present = True
            numbers_correct = True
            for item in cost_savings_expected:
                dept = item["department"]
                prior = item["prior_period"]
                latest = item["latest_period"]
                prior_epe = item["prior_epe"]
                latest_epe = item["latest_epe"]
                savings = item["savings"]
                found = False
                found_numbers_ok = False
                for b in bullets:
                    lowerb = b.lower()
                    if dept.lower() in lowerb and prior.lower() in lowerb and latest.lower() in lowerb:
                        def _contains_amount(text: str, amt: int) -> bool:
                            amt_plain = str(amt)
                            amt_commas = f"{amt:,}"
                            patterns = [
                                re.escape(amt_plain),
                                re.escape(amt_commas),
                                re.escape("$" + amt_plain),
                                re.escape("$" + amt_commas),
                            ]
                            return any(re.search(p, text) for p in patterns)
                        if _contains_amount(b, prior_epe) and _contains_amount(b, latest_epe) and _contains_amount(b, savings):
                            found_numbers_ok = True
                        found = True
                        break
                if not found:
                    all_present = False
                if not found_numbers_ok:
                    numbers_correct = False
            if all_present:
                scores["cost_savings_top_departments"] = 1.0
            if numbers_correct:
                scores["cost_savings_numbers_correct"] = 1.0
        else:
            scores["cost_savings_top_departments"] = 1.0
            scores["cost_savings_numbers_correct"] = 1.0

    # 4) Validation command/script and report checks
    analyze_script = workspace / "scripts" / "analyze.py"
    if analyze_script.exists():
        scores["analyze_script_exists"] = 1.0

    validation_report_path = workspace / "output" / "validation_report.json"
    vr = _safe_load_json(validation_report_path)
    if vr is not None and isinstance(vr, dict):
        scores["validation_report_exists"] = 1.0
        status = str(vr.get("status", "")).lower()
        if status == "passed":
            scores["validation_status_passed"] = 1.0

    validation_run_txt = workspace / "output" / "validation_run.txt"
    vr_text = _safe_read_text(validation_run_txt)
    if vr_text is not None:
        if re.search(r"\bpass(ed)?\b", vr_text, flags=re.IGNORECASE):
            scores["validation_run_captured"] = 1.0

    # 5) Email checks
    email_path = workspace / "output" / "email_final.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        scores["email_final_exists"] = 1.0
        words = re.findall(r"\b\w+\b", email_text)
        if len(words) <= 150:
            scores["email_under_150_words"] = 1.0

        if expected_rollup:
            latest_period = sorted(expected_rollup.keys())[-1]
            mr = expected_rollup[latest_period]["margin_rate"]
            mr_decimal_str = _fmt_float_4(mr)
            mr_percent_str = f"{mr * 100:.2f}%"
            if mr_decimal_str in email_text or mr_percent_str in email_text:
                scores["email_includes_margin_rate"] = 1.0

        if cost_text is not None and cost_savings_expected:
            has_all = True
            for item in cost_savings_expected:
                dept = item["department"]
                savings = item["savings"]
                savings_plain = str(savings)
                savings_commas = f"{savings:,}"
                email_lower = email_text.lower()
                if (dept.lower() in email_lower) and (savings_plain in email_text or savings_commas in email_text or ("$" + savings_plain) in email_text or ("$" + savings_commas) in email_text):
                    continue
                else:
                    has_all = False
                    break
            if has_all:
                scores["email_lists_savings"] = 1.0
        elif cost_text is not None and not cost_savings_expected:
            scores["email_lists_savings"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()