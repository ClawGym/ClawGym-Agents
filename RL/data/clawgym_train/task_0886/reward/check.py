import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        # Ensure header exists
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _to_float(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, int):
            return val
        s = str(val).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _to_bool(val: Any) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("true", "t", "1", "yes"):
        return True
    if s in ("false", "f", "0", "no"):
        return False
    return None


def _approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= tol
    return False


def _normalize_minmax(values: List[float], invert: bool = False) -> List[float]:
    # values: list for eligible items only
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        return [0.5 for _ in values]
    res = []
    for v in values:
        if invert:
            # lower is better: (max - v) / (max - min)
            res.append((vmax - v) / (vmax - vmin))
        else:
            # higher is better: (v - min) / (max - min)
            res.append((v - vmin) / (vmax - vmin))
    return res


def _parse_components(rows: List[Dict[str, str]]) -> Optional[List[Dict[str, Any]]]:
    out = []
    for r in rows:
        try:
            item = {
                "category": r.get("category"),
                "part_number": r.get("part_number"),
                "manufacturer": r.get("manufacturer"),
                "supplier": r.get("supplier"),
                "unit_cost_usd": _to_float(r.get("unit_cost_usd")),
                "lead_time_days": _to_int(r.get("lead_time_days")),
                "failure_rate_fit": _to_float(r.get("failure_rate_fit")),
                "temp_max_C": _to_int(r.get("temp_max_C")),
                "rohs": _to_bool(r.get("rohs")),
                "lifecycle_status": r.get("lifecycle_status"),
                "stock_qty": _to_int(r.get("stock_qty")),
                "moq": _to_int(r.get("moq")),
            }
            # Basic presence checks
            if item["part_number"] is None or item["supplier"] is None:
                return None
            if None in (
                item["unit_cost_usd"],
                item["lead_time_days"],
                item["failure_rate_fit"],
                item["temp_max_C"],
                item["rohs"],
                item["lifecycle_status"],
                item["stock_qty"],
                item["moq"],
            ):
                return None
            out.append(item)
        except Exception:
            return None
    return out


def _aggregate_test_results(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, float]]]:
    agg: Dict[str, Dict[str, float]] = {}
    for r in rows:
        pn = r.get("part_number")
        if pn is None:
            return None
        dh = _to_float(r.get("device_hours"))
        fo = _to_int(r.get("failures_observed"))
        if dh is None or fo is None:
            return None
        a = agg.setdefault(pn, {"device_hours": 0.0, "failures_observed": 0.0})
        a["device_hours"] += dh
        a["failures_observed"] += float(fo)
    return agg


def _parse_supplier_ratings(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, float]]]:
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        supplier = r.get("supplier")
        on_time = _to_float(r.get("on_time_delivery_pct"))
        rma = _to_float(r.get("rma_rate_pct"))
        if supplier is None or on_time is None or rma is None:
            return None
        out[supplier] = {"on_time_delivery_pct": on_time, "rma_rate_pct": rma}
    return out


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Read inputs
    comp_path = workspace / "input" / "components.csv"
    test_path = workspace / "input" / "test_results.csv"
    supplier_path = workspace / "input" / "supplier_ratings.csv"

    comp_rows = _read_csv_dicts(comp_path)
    test_rows = _read_csv_dicts(test_path)
    supplier_rows = _read_csv_dicts(supplier_path)
    if comp_rows is None or test_rows is None or supplier_rows is None:
        return None

    components = _parse_components(comp_rows)
    test_agg = _aggregate_test_results(test_rows)
    supplier_ratings = _parse_supplier_ratings(supplier_rows)
    if components is None or test_agg is None or supplier_ratings is None:
        return None

    # Compute empirical and blended FIT, eligibility, reasons
    expected_per_part: Dict[str, Dict[str, Any]] = {}
    for item in components:
        pn = item["part_number"]
        reasons = []
        if not item["rohs"]:
            reasons.append("rohs=false")
        if item["lifecycle_status"] != "Active":
            reasons.append("lifecycle_status!=Active")
        if item["stock_qty"] is None or item["moq"] is None or item["stock_qty"] < item["moq"]:
            reasons.append("stock<moq")
        if item["temp_max_C"] is None or item["temp_max_C"] < 85:
            reasons.append("temp_max_C<85")
        eligible = len(reasons) == 0
        # empirical fit
        empirical_fit = None
        agg = test_agg.get(pn)
        if agg is not None and agg["device_hours"] > 0:
            empirical_fit = (agg["failures_observed"] / agg["device_hours"]) * 1e9
        # blended
        if empirical_fit is not None:
            blended_fit = 0.6 * empirical_fit + 0.4 * item["failure_rate_fit"]
        else:
            blended_fit = item["failure_rate_fit"]
        expected_per_part[pn] = {
            "category": item["category"],
            "manufacturer": item["manufacturer"],
            "supplier": item["supplier"],
            "unit_cost_usd": item["unit_cost_usd"],
            "lead_time_days": item["lead_time_days"],
            "failure_rate_fit": item["failure_rate_fit"],
            "empirical_fit": empirical_fit,
            "blended_fit": blended_fit,
            "eligible": eligible,
            "reasons": reasons,
        }

    # Compute normalization across eligible parts
    eligible_parts = [pn for pn, data in expected_per_part.items() if data["eligible"]]
    costs = [expected_per_part[pn]["unit_cost_usd"] for pn in eligible_parts]
    leads = [expected_per_part[pn]["lead_time_days"] for pn in eligible_parts]
    fits = [expected_per_part[pn]["blended_fit"] for pn in eligible_parts]
    # Supplier on-time per eligible part
    on_times = []
    for pn in eligible_parts:
        sup = expected_per_part[pn]["supplier"]
        rating = supplier_ratings.get(sup)
        if rating is None:
            on_times.append(None)
        else:
            on_times.append(rating["on_time_delivery_pct"])
    # If any missing supplier rating for eligible, we cannot compute expected reliably
    if None in on_times and eligible_parts:
        return None

    cost_norms = _normalize_minmax(costs, invert=True) if eligible_parts else []
    lead_norms = _normalize_minmax(leads, invert=True) if eligible_parts else []
    rel_norms = _normalize_minmax(fits, invert=True) if eligible_parts else []
    on_time_norms = _normalize_minmax(on_times, invert=False) if eligible_parts else []

    # Attach norms and score
    for idx, pn in enumerate(eligible_parts):
        cn = cost_norms[idx]
        ln = lead_norms[idx]
        rn = rel_norms[idx]
        sn = on_time_norms[idx]
        score = 0.3 * cn + 0.2 * ln + 0.4 * rn + 0.1 * sn
        expected_per_part[pn]["cost_norm"] = cn
        expected_per_part[pn]["lead_norm"] = ln
        expected_per_part[pn]["reliability_norm"] = rn
        expected_per_part[pn]["supplier_on_time_norm"] = sn
        expected_per_part[pn]["score"] = score

    # Fill placeholders for ineligible (norms/score undefined)
    for pn, data in expected_per_part.items():
        if not data["eligible"]:
            data.setdefault("cost_norm", None)
            data.setdefault("lead_norm", None)
            data.setdefault("reliability_norm", None)
            data.setdefault("supplier_on_time_norm", None)
            data.setdefault("score", None)

    # Expected top choices by category
    # Create list of eligible items with metrics
    eligible_items: List[Dict[str, Any]] = []
    for pn, d in expected_per_part.items():
        if d["eligible"]:
            eligible_items.append({
                "category": d["category"],
                "part_number": pn,
                "score": d["score"],
                "blended_fit": d["blended_fit"],
                "lead_time_days": d["lead_time_days"],
                "unit_cost_usd": d["unit_cost_usd"],
                "supplier": d["supplier"],
            })
    # Sort by score desc, tie-breakers: lower blended_fit, then shorter lead_time_days, then part_number
    eligible_items_sorted = sorted(
        eligible_items,
        key=lambda x: (
            -x["score"],
            x["blended_fit"],
            x["lead_time_days"],
            x["part_number"],
        ),
    )
    # Group by category and take top 2
    top_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for item in eligible_items_sorted:
        cat = item["category"]
        lst = top_by_category.setdefault(cat, [])
        if len(lst) < 2:
            lst.append(item)

    # Expected supplier summary over eligible parts
    # Aggregate by supplier
    supplier_aggs: Dict[str, Dict[str, Any]] = {}
    for pn, d in expected_per_part.items():
        if not d["eligible"]:
            continue
        sup = d["supplier"]
        a = supplier_aggs.setdefault(sup, {"eligible_part_numbers": [], "sum_cost": 0.0, "sum_lead": 0.0, "sum_score": 0.0, "sum_blended_fit": 0.0})
        a["eligible_part_numbers"].append(pn)
        a["sum_cost"] += d["unit_cost_usd"]
        a["sum_lead"] += d["lead_time_days"]
        a["sum_score"] += d["score"]
        a["sum_blended_fit"] += d["blended_fit"]

    supplier_summary_expected: Dict[str, Dict[str, Any]] = {}
    for sup, ag in supplier_aggs.items():
        count = len(ag["eligible_part_numbers"])
        avg_cost = ag["sum_cost"] / count if count > 0 else 0.0
        avg_lead = ag["sum_lead"] / count if count > 0 else 0.0
        avg_score = ag["sum_score"] / count if count > 0 else 0.0
        avg_blended = ag["sum_blended_fit"] / count if count > 0 else 0.0
        on_time = supplier_ratings.get(sup, {}).get("on_time_delivery_pct")
        supplier_summary_expected[sup] = {
            "supplier": sup,
            "eligible_part_count": count,
            "avg_unit_cost_usd": avg_cost,
            "avg_lead_time_days": avg_lead,
            "avg_score": avg_score,
            "avg_blended_fit": avg_blended,  # for tie-breaking
            "on_time_delivery_pct": on_time,
        }

    # Compute supplier ranks: by avg_score desc, tie by lower avg_blended_fit, then shorter avg_lead_time_days, then supplier name
    suppliers_sorted = sorted(
        supplier_summary_expected.values(),
        key=lambda x: (-x["avg_score"], x["avg_blended_fit"], x["avg_lead_time_days"], x["supplier"]),
    )
    for rank, entry in enumerate(suppliers_sorted, start=1):
        supplier_summary_expected[entry["supplier"]]["supplier_rank"] = rank

    return {
        "components": components,
        "expected_per_part": expected_per_part,
        "top_by_category": top_by_category,  # dict category -> list of up to 2 dicts with fields
        "supplier_summary_expected": supplier_summary_expected,
    }


def _read_output_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(path)


def _parse_reasons(s: str) -> List[str]:
    if s is None:
        return []
    parts = [p.strip() for p in str(s).split(";")]
    parts = [p for p in parts if p]
    return parts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "component_scores_file_structure": 0.0,
        "component_scores_row_coverage": 0.0,
        "component_scores_eligibility_and_reasons": 0.0,
        "component_scores_blended_fit_correct": 0.0,
        "component_scores_norms_and_score": 0.0,
        "top_choices_by_category_correct": 0.0,
        "supplier_summary_correct": 0.0,
    }

    expected = _compute_expected(workspace)
    # If inputs missing or malformed, we cannot grade; return zeros
    if expected is None:
        return scores

    expected_per_part: Dict[str, Dict[str, Any]] = expected["expected_per_part"]
    expected_parts_set = set(expected_per_part.keys())

    # Component scores file checks
    comp_scores_path = workspace / "output" / "component_scores.csv"
    comp_scores_rows = _read_output_csv(comp_scores_path)
    required_columns_cs = [
        "part_number",
        "category",
        "manufacturer",
        "supplier",
        "unit_cost_usd",
        "lead_time_days",
        "blended_fit",
        "cost_norm",
        "lead_norm",
        "reliability_norm",
        "supplier_on_time_norm",
        "score",
        "eligible",
        "reasons_excluded",
    ]
    if comp_scores_rows is not None and len(comp_scores_rows) >= 0:
        # Verify columns
        try:
            with comp_scores_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
        except Exception:
            fieldnames = []
        has_all = all(c in fieldnames for c in required_columns_cs)
        if has_all:
            scores["component_scores_file_structure"] = 1.0

    if comp_scores_rows is not None:
        # Build a map by part_number
        actual_by_pn: Dict[str, Dict[str, str]] = {}
        for r in comp_scores_rows:
            pn = r.get("part_number")
            if pn is None:
                continue
            actual_by_pn[pn] = r

        # Coverage score
        actual_parts_set = set(actual_by_pn.keys())
        expected_count = len(expected_parts_set)
        correct_present = len(expected_parts_set & actual_parts_set)
        extras = len(actual_parts_set - expected_parts_set)
        coverage_score = 0.0
        if expected_count > 0:
            base = correct_present / expected_count
            penalty = extras / expected_count
            coverage_score = max(0.0, min(1.0, base - penalty))
        scores["component_scores_row_coverage"] = coverage_score

        # Eligibility and reasons
        eligible_checks = 0
        eligible_correct = 0
        for pn in expected_parts_set:
            if pn not in actual_by_pn:
                continue
            row = actual_by_pn[pn]
            eligible_checks += 1
            exp_eligible = expected_per_part[pn]["eligible"]
            act_eligible = _to_bool(row.get("eligible"))
            # Reasons
            exp_reasons_set = set(expected_per_part[pn]["reasons"])
            act_reasons = _parse_reasons(row.get("reasons_excluded", ""))
            act_reasons_set = set(act_reasons)
            el_ok = (act_eligible is not None and act_eligible == exp_eligible)
            reasons_ok = False
            if exp_eligible:
                # expect empty reasons
                reasons_ok = len(act_reasons_set) == 0
            else:
                # Compare sets exactly in allowed domain
                reasons_ok = act_reasons_set == exp_reasons_set
            if el_ok and reasons_ok:
                eligible_correct += 1
        if eligible_checks > 0:
            scores["component_scores_eligibility_and_reasons"] = eligible_correct / eligible_checks

        # Blended fit checks for all parts
        bf_checks = 0
        bf_correct = 0
        for pn in expected_parts_set:
            if pn not in actual_by_pn:
                continue
            row = actual_by_pn[pn]
            exp_bf = expected_per_part[pn]["blended_fit"]
            act_bf = _to_float(row.get("blended_fit"))
            bf_checks += 1
            if _approx_equal(exp_bf, act_bf):
                bf_correct += 1
        if bf_checks > 0:
            scores["component_scores_blended_fit_correct"] = bf_correct / bf_checks

        # Norms and score checks for eligible parts only
        norm_checks = 0
        norm_correct = 0
        for pn in expected_parts_set:
            if not expected_per_part[pn]["eligible"]:
                continue
            if pn not in actual_by_pn:
                continue
            row = actual_by_pn[pn]
            checks_ok = True
            exp_cn = expected_per_part[pn]["cost_norm"]
            exp_ln = expected_per_part[pn]["lead_norm"]
            exp_rn = expected_per_part[pn]["reliability_norm"]
            exp_sn = expected_per_part[pn]["supplier_on_time_norm"]
            exp_sc = expected_per_part[pn]["score"]
            act_cn = _to_float(row.get("cost_norm"))
            act_ln = _to_float(row.get("lead_norm"))
            act_rn = _to_float(row.get("reliability_norm"))
            act_sn = _to_float(row.get("supplier_on_time_norm"))
            act_sc = _to_float(row.get("score"))
            # Each eligible row counts as 1 check; all fields must match within tolerance
            checks_ok = (
                _approx_equal(exp_cn, act_cn)
                and _approx_equal(exp_ln, act_ln)
                and _approx_equal(exp_rn, act_rn)
                and _approx_equal(exp_sn, act_sn)
                and _approx_equal(exp_sc, act_sc)
            )
            norm_checks += 1
            if checks_ok:
                norm_correct += 1
        if norm_checks > 0:
            scores["component_scores_norms_and_score"] = norm_correct / norm_checks

    # Top choices by category checks
    top_path = workspace / "output" / "top_choices_by_category.csv"
    top_rows = _read_output_csv(top_path)
    required_columns_top = ["category", "rank", "part_number", "score", "blended_fit", "lead_time_days", "unit_cost_usd", "supplier"]
    if top_rows is not None:
        try:
            with top_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                top_fields = reader.fieldnames or []
        except Exception:
            top_fields = []
        has_all = all(c in top_fields for c in required_columns_top)
        if has_all:
            # Build expected entries: for each category in expected top_by_category, ranks 1..len
            expected_top_entries: Dict[Tuple[str, int], Dict[str, Any]] = {}
            for cat, lst in expected["top_by_category"].items():
                for idx, item in enumerate(lst, start=1):
                    expected_top_entries[(cat, idx)] = {
                        "category": cat,
                        "rank": idx,
                        "part_number": item["part_number"],
                        "score": item["score"],
                        "blended_fit": item["blended_fit"],
                        "lead_time_days": item["lead_time_days"],
                        "unit_cost_usd": item["unit_cost_usd"],
                        "supplier": item["supplier"],
                    }
            # Build actual entries mapping
            actual_top_entries: Dict[Tuple[str, int], Dict[str, str]] = {}
            for r in top_rows:
                cat = r.get("category")
                rank = _to_int(r.get("rank"))
                if cat is None or rank is None:
                    continue
                actual_top_entries[(cat, rank)] = r
            # Score based on proportion of expected entries matched exactly (ignoring row order)
            total_expected = len(expected_top_entries)
            if total_expected > 0:
                correct = 0
                for key, exp in expected_top_entries.items():
                    act = actual_top_entries.get(key)
                    if act is None:
                        continue
                    ok = True
                    ok = ok and (str(exp["category"]) == str(act.get("category")))
                    ok = ok and (str(exp["part_number"]) == str(act.get("part_number")))
                    ok = ok and (str(exp["supplier"]) == str(act.get("supplier")))
                    ok = ok and _approx_equal(exp["score"], _to_float(act.get("score")))
                    ok = ok and _approx_equal(exp["blended_fit"], _to_float(act.get("blended_fit")))
                    ok = ok and _approx_equal(float(exp["lead_time_days"]), _to_float(act.get("lead_time_days")))
                    ok = ok and _approx_equal(float(exp["unit_cost_usd"]), _to_float(act.get("unit_cost_usd")))
                    if ok:
                        correct += 1
                scores["top_choices_by_category_correct"] = correct / total_expected

    # Supplier summary checks
    supplier_path = workspace / "output" / "supplier_summary.csv"
    supplier_rows = _read_output_csv(supplier_path)
    required_columns_supplier = ["supplier", "eligible_part_count", "avg_unit_cost_usd", "avg_lead_time_days", "avg_score", "on_time_delivery_pct", "supplier_rank"]
    if supplier_rows is not None:
        try:
            with supplier_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                supplier_fields = reader.fieldnames or []
        except Exception:
            supplier_fields = []
        has_all = all(c in supplier_fields for c in required_columns_supplier)
        if has_all:
            expected_sup = expected["supplier_summary_expected"]
            # Filter to suppliers with eligible_part_count > 0
            expected_sup = {k: v for k, v in expected_sup.items() if v["eligible_part_count"] > 0}
            total_expected = len(expected_sup)
            if total_expected > 0:
                # Build actual map by supplier
                actual_by_sup: Dict[str, Dict[str, str]] = {}
                for r in supplier_rows:
                    sup = r.get("supplier")
                    if sup is not None:
                        actual_by_sup[sup] = r
                correct = 0
                for sup, exp in expected_sup.items():
                    act = actual_by_sup.get(sup)
                    if act is None:
                        continue
                    ok = True
                    ok = ok and _approx_equal(float(exp["eligible_part_count"]), _to_float(act.get("eligible_part_count")))
                    ok = ok and _approx_equal(float(exp["avg_unit_cost_usd"]), _to_float(act.get("avg_unit_cost_usd")))
                    ok = ok and _approx_equal(float(exp["avg_lead_time_days"]), _to_float(act.get("avg_lead_time_days")))
                    ok = ok and _approx_equal(float(exp["avg_score"]), _to_float(act.get("avg_score")))
                    ok = ok and _approx_equal(float(exp["on_time_delivery_pct"]), _to_float(act.get("on_time_delivery_pct")))
                    ok = ok and _approx_equal(float(exp["supplier_rank"]), _to_float(act.get("supplier_rank")))
                    if ok:
                        correct += 1
                scores["supplier_summary_correct"] = correct / total_expected

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()