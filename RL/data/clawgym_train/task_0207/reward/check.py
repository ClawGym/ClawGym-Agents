import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [dict(r) for r in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _approx_equal(a: float, b: float, atol: float = 1e-6, rtol: float = 1e-9) -> bool:
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b)))
    return False


def _coerce_normalized_row(row: Dict[str, str]) -> Dict[str, object]:
    NUMERIC_FLOAT_COLS = {"revenue", "opex", "capex", "rate_base", "authorized_roe"}
    NUMERIC_INT_COLS = {"year"}
    out: Dict[str, object] = {}
    for k, v in row.items():
        key = (k.strip().lower() if isinstance(k, str) else k)
        val = v.strip() if isinstance(v, str) else v
        if key in NUMERIC_INT_COLS:
            if val == "" or val is None:
                out[key] = ""
            else:
                try:
                    out[key] = int(val)
                except Exception:
                    try:
                        out[key] = int(float(val))
                    except Exception:
                        return {}
        elif key in NUMERIC_FLOAT_COLS:
            if val == "" or val is None:
                out[key] = ""
            else:
                try:
                    out[key] = float(val)
                except Exception:
                    return {}
        else:
            out[key] = val
    return out


def _normalize_raw_file_content(fieldnames: List[str], rows: List[Dict[str, str]]) -> Tuple[List[str], List[Dict[str, object]]]:
    norm_fields = [h.strip().lower() for h in fieldnames]
    norm_rows: List[Dict[str, object]] = []
    for raw in rows:
        temp = {}
        for h in fieldnames:
            norm_key = h.strip().lower()
            temp[norm_key] = raw.get(h, "")
        coerced = _coerce_normalized_row(temp)
        if coerced == {}:
            return norm_fields, []
        norm_rows.append(coerced)
    return norm_fields, norm_rows


def _read_processed_normalized_file(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, object]]]]:
    fieldnames, rows = _read_csv(path)
    if fieldnames is None or rows is None:
        return None, None
    coerced_rows: List[Dict[str, object]] = []
    for r in rows:
        cr = _coerce_normalized_row(r)
        if cr == {}:
            return None, None
        coerced_rows.append(cr)
    norm_fields = [h.strip().lower() for h in fieldnames]
    return norm_fields, coerced_rows


def _multiset_of_rows(rows: List[Dict[str, object]], fields: List[str]) -> Dict[Tuple[object, ...], int]:
    counts: Dict[Tuple[object, ...], int] = {}
    for r in rows:
        key = tuple(r.get(f, "") for f in fields)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _safe_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        try:
            return int(float(val))
        except Exception:
            return None


def _safe_float(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _compute_group_summaries(processed_files: List[Path]) -> Optional[Dict[Tuple[str, int, str], Dict[str, float]]]:
    groups: Dict[Tuple[str, int, str], Dict[str, float]] = {}
    for p in processed_files:
        fields, rows = _read_processed_normalized_file(p)
        if fields is None or rows is None:
            return None
        for r in rows:
            utility = str(r.get("utility", ""))
            year = r.get("year", None)
            quarter = str(r.get("quarter", ""))
            revenue = r.get("revenue", None)
            opex = r.get("opex", None)
            capex = r.get("capex", None)
            rate_base = r.get("rate_base", None)
            if not isinstance(year, int) or not isinstance(revenue, float) or not isinstance(opex, float) or not isinstance(capex, float) or not isinstance(rate_base, float):
                return None
            key = (utility, year, quarter)
            if key not in groups:
                groups[key] = {"revenue": 0.0, "opex": 0.0, "capex": 0.0, "rate_base": 0.0}
            groups[key]["revenue"] += revenue
            groups[key]["opex"] += opex
            groups[key]["capex"] += capex
            groups[key]["rate_base"] += rate_base
    return groups


def _compute_authorized_roe_means(rate_cases_path: Path) -> Optional[Dict[str, float]]:
    flds, rows = _read_csv(rate_cases_path)
    if flds is None or rows is None:
        return None
    util_sum: Dict[str, float] = {}
    util_cnt: Dict[str, int] = {}
    for r in rows:
        util = r.get("utility")
        if util is None:
            return None
        val = _safe_float(r.get("authorized_roe", ""))
        if val is None:
            return None
        util_sum[util] = util_sum.get(util, 0.0) + val
        util_cnt[util] = util_cnt.get(util, 0) + 1
    means: Dict[str, float] = {}
    for u, s in util_sum.items():
        c = util_cnt.get(u, 0)
        if c == 0:
            return None
        means[u] = s / c
    return means


def _read_output_csv(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    fields, rows = _read_csv(path)
    if fields is None or rows is None:
        return False, [], []
    return True, [h.strip() for h in fields], rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    raw_dir = workspace / "data" / "quarterly"
    processed_dir = workspace / "data" / "processed"
    rate_cases_path = workspace / "data" / "rate_cases.csv"
    reference_totals_path = workspace / "reference" / "reference_totals.csv"

    raw_files = sorted(raw_dir.glob("utility_financials_*.csv"))
    raw_files = [p for p in raw_files if not p.name.endswith("_normalized.csv")]

    expected_processed = []
    for rf in raw_files:
        stem = rf.stem
        expected_processed.append(processed_dir / f"{stem}_normalized.csv")

    actual_processed = sorted(processed_dir.glob("utility_financials_*_normalized.csv")) if processed_dir.exists() else []

    scores: Dict[str, float] = {
        "normalized_files_exist": 0.0,
        "normalized_content_correct": 0.0,
        "file_inventory_structure": 0.0,
        "file_inventory_raw_rows_correct": 0.0,
        "file_inventory_processed_rows_correct": 0.0,
        "file_inventory_totals_correct": 0.0,
        "summary_file_structure": 0.0,
        "summary_values_correct": 0.0,
        "reference_comparison_structure": 0.0,
        "reference_comparison_values_correct": 0.0,
        "top_margin_structure": 0.0,
        "top_margin_values_correct": 0.0,
    }

    if expected_processed:
        present = sum(1 for p in expected_processed if p.exists())
        scores["normalized_files_exist"] = present / float(len(expected_processed))
    else:
        scores["normalized_files_exist"] = 0.0

    all_match = True
    if expected_processed and scores["normalized_files_exist"] == 1.0:
        for rf, pf in zip(raw_files, expected_processed):
            raw_fields, raw_rows = _read_csv(rf)
            if raw_fields is None or raw_rows is None:
                all_match = False
                break
            exp_fields, exp_rows = _normalize_raw_file_content(raw_fields, raw_rows)
            if not exp_rows:
                all_match = False
                break
            got_fields, got_rows = _read_processed_normalized_file(pf)
            if got_fields is None or got_rows is None:
                all_match = False
                break
            if [h for h in got_fields] != [h for h in exp_fields]:
                all_match = False
                break
            exp_multi = _multiset_of_rows(exp_rows, exp_fields)
            got_multi = _multiset_of_rows(got_rows, got_fields)
            if exp_multi != got_multi:
                all_match = False
                break
    else:
        all_match = False
    scores["normalized_content_correct"] = 1.0 if all_match else 0.0

    inventory_path = workspace / "outputs" / "checks" / "file_inventory.csv"
    ok, inv_fields, inv_rows = _read_output_csv(inventory_path)
    if ok and inv_fields == ["dir_type", "file_name", "row_count"]:
        scores["file_inventory_structure"] = 1.0
        expected_raw = {p.name: None for p in raw_files}
        expected_processed_set = {p.name: None for p in actual_processed}
        raw_entries: Dict[str, int] = {}
        processed_entries: Dict[str, int] = {}
        raw_total_rows: List[Dict[str, str]] = []
        processed_total_rows: List[Dict[str, str]] = []
        for r in inv_rows:
            dir_type = r.get("dir_type", "")
            fname = r.get("file_name", "")
            rc = r.get("row_count", "")
            rci = _safe_int(rc)
            if rci is None:
                raw_entries = {}
                processed_entries = {}
                raw_total_rows = []
                processed_total_rows = []
                break
            if dir_type == "raw":
                raw_entries[fname] = rci
            elif dir_type == "processed":
                processed_entries[fname] = rci
            elif dir_type == "raw_total":
                raw_total_rows.append(r)
            elif dir_type == "processed_total":
                processed_total_rows.append(r)
            else:
                pass

        raw_correct = True
        if len(raw_entries) != len(expected_raw):
            raw_correct = False
        else:
            normalized_raw_entries: Dict[str, int] = {}
            for fname, cnt in raw_entries.items():
                basename = Path(fname).name
                normalized_raw_entries[basename] = cnt
            for p in raw_files:
                rf_fields, rf_rows = _read_csv(p)
                if rf_fields is None or rf_rows is None:
                    raw_correct = False
                    break
                expected_count = len(rf_rows)
                got_count = normalized_raw_entries.get(p.name)
                if got_count is None or got_count != expected_count:
                    raw_correct = False
                    break
        scores["file_inventory_raw_rows_correct"] = 1.0 if raw_correct else 0.0

        processed_correct = True
        if len(processed_entries) != len(expected_processed_set):
            processed_correct = False
        else:
            normalized_proc_entries: Dict[str, int] = {}
            for fname, cnt in processed_entries.items():
                basename = Path(fname).name
                normalized_proc_entries[basename] = cnt
            for p in actual_processed:
                pf_fields, pf_rows = _read_csv(p)
                if pf_fields is None or pf_rows is None:
                    processed_correct = False
                    break
                expected_count = len(pf_rows)
                got_count = normalized_proc_entries.get(p.name)
                if got_count is None or got_count != expected_count:
                    processed_correct = False
                    break
        scores["file_inventory_processed_rows_correct"] = 1.0 if processed_correct else 0.0

        totals_correct = True
        if len(raw_total_rows) != 1 or len(processed_total_rows) != 1:
            totals_correct = False
        else:
            raw_total_val = _safe_int(raw_total_rows[0].get("row_count", ""))
            proc_total_val = _safe_int(processed_total_rows[0].get("row_count", ""))
            if raw_total_val is None or proc_total_val is None:
                totals_correct = False
            else:
                exp_raw_sum = 0
                for p in raw_files:
                    rf_fields, rf_rows = _read_csv(p)
                    if rf_fields is None or rf_rows is None:
                        totals_correct = False
                        break
                    exp_raw_sum += len(rf_rows)
                exp_proc_sum = 0
                for p in actual_processed:
                    pf_fields, pf_rows = _read_csv(p)
                    if pf_fields is None or pf_rows is None:
                        totals_correct = False
                        break
                    exp_proc_sum += len(pf_rows)
                if totals_correct:
                    if raw_total_val != exp_raw_sum or proc_total_val != exp_proc_sum:
                        totals_correct = False
        scores["file_inventory_totals_correct"] = 1.0 if totals_correct else 0.0
    else:
        scores["file_inventory_structure"] = 0.0
        scores["file_inventory_raw_rows_correct"] = 0.0
        scores["file_inventory_processed_rows_correct"] = 0.0
        scores["file_inventory_totals_correct"] = 0.0

    groups = _compute_group_summaries(actual_processed) if actual_processed else None
    roe_means = _compute_authorized_roe_means(rate_cases_path) if rate_cases_path.exists() else None

    summary_path = workspace / "outputs" / "summary" / "quarterly_utility_financial_summary.csv"
    ok, sum_fields, sum_rows = _read_output_csv(summary_path)
    expected_summary_fields = [
        "utility",
        "year",
        "quarter",
        "revenue",
        "opex",
        "capex",
        "operating_margin",
        "capex_to_rate_base",
        "authorized_roe_case_mean",
    ]
    if ok and sum_fields == expected_summary_fields:
        scores["summary_file_structure"] = 1.0
        if groups is not None and roe_means is not None:
            expected_map: Dict[Tuple[str, int, str], Dict[str, float]] = {}
            for (util, year, quarter), vals in groups.items():
                rev = vals["revenue"]
                opx = vals["opex"]
                cpx = vals["capex"]
                rb = vals["rate_base"]
                op_margin = (rev - opx) / rev if rev != 0 else 0.0
                cpx_rb = (cpx / rb) if rb != 0 else 0.0
                roe_mean = roe_means.get(util)
                if roe_mean is None:
                    expected_map = {}
                    break
                expected_map[(util, year, quarter)] = {
                    "revenue": rev,
                    "opex": opx,
                    "capex": cpx,
                    "operating_margin": op_margin,
                    "capex_to_rate_base": cpx_rb,
                    "authorized_roe_case_mean": roe_mean,
                }
            if expected_map:
                actual_map: Dict[Tuple[str, int, str], Dict[str, float]] = {}
                for r in sum_rows:
                    util = r.get("utility", "")
                    year = _safe_int(r.get("year", ""))
                    quarter = r.get("quarter", "")
                    rev = _safe_float(r.get("revenue", ""))
                    opx = _safe_float(r.get("opex", ""))
                    cpx = _safe_float(r.get("capex", ""))
                    opm = _safe_float(r.get("operating_margin", ""))
                    cpxrb = _safe_float(r.get("capex_to_rate_base", ""))
                    roem = _safe_float(r.get("authorized_roe_case_mean", ""))
                    if not util or year is None or quarter is None or rev is None or opx is None or cpx is None or opm is None or cpxrb is None or roem is None:
                        actual_map = {}
                        break
                    actual_map[(util, year, quarter)] = {
                        "revenue": rev,
                        "opex": opx,
                        "capex": cpx,
                        "operating_margin": opm,
                        "capex_to_rate_base": cpxrb,
                        "authorized_roe_case_mean": roem,
                    }
                if actual_map and set(actual_map.keys()) == set(expected_map.keys()):
                    all_ok = True
                    for k in expected_map:
                        ev = expected_map[k]
                        av = actual_map[k]
                        for fld in ev:
                            if not _approx_equal(ev[fld], av[fld]):
                                all_ok = False
                                break
                        if not all_ok:
                            break
                    scores["summary_values_correct"] = 1.0 if all_ok else 0.0
                else:
                    scores["summary_values_correct"] = 0.0
            else:
                scores["summary_values_correct"] = 0.0
        else:
            scores["summary_values_correct"] = 0.0
    else:
        scores["summary_file_structure"] = 0.0
        scores["summary_values_correct"] = 0.0

    refcomp_path = workspace / "outputs" / "checks" / "reference_comparison.csv"
    ok, refc_fields, refc_rows = _read_output_csv(refcomp_path)
    expected_refc_fields = [
        "year",
        "quarter",
        "revenue_sum_computed",
        "revenue_sum_reference",
        "revenue_diff",
        "opex_sum_computed",
        "opex_sum_reference",
        "opex_diff",
        "capex_sum_computed",
        "capex_sum_reference",
        "capex_diff",
    ]
    if ok and refc_fields == expected_refc_fields:
        scores["reference_comparison_structure"] = 1.0
        ref_fields, ref_rows = _read_csv(reference_totals_path)
        if ref_fields is not None and ref_rows is not None and groups is not None:
            q_sums: Dict[Tuple[int, str], Dict[str, float]] = {}
            for (util, year, quarter), vals in groups.items():
                key = (year, quarter)
                if key not in q_sums:
                    q_sums[key] = {"revenue": 0.0, "opex": 0.0, "capex": 0.0}
                q_sums[key]["revenue"] += vals["revenue"]
                q_sums[key]["opex"] += vals["opex"]
                q_sums[key]["capex"] += vals["capex"]
            expected_keys = []
            ref_map: Dict[Tuple[int, str], Dict[str, float]] = {}
            for r in ref_rows:
                year = _safe_int(r.get("year", ""))
                quarter = r.get("quarter", "")
                r_rev = _safe_float(r.get("revenue_sum_reference", ""))
                r_opx = _safe_float(r.get("opex_sum_reference", ""))
                r_cpx = _safe_float(r.get("capex_sum_reference", ""))
                if year is None or not quarter or r_rev is None or r_opx is None or r_cpx is None:
                    ref_map = {}
                    break
                key = (year, quarter)
                expected_keys.append(key)
                ref_map[key] = {"revenue": r_rev, "opex": r_opx, "capex": r_cpx}
            if ref_map:
                actual_map: Dict[Tuple[int, str], Dict[str, float]] = {}
                for r in refc_rows:
                    year = _safe_int(r.get("year", ""))
                    quarter = r.get("quarter", "")
                    rev_c = _safe_float(r.get("revenue_sum_computed", ""))
                    rev_r = _safe_float(r.get("revenue_sum_reference", ""))
                    rev_d = _safe_float(r.get("revenue_diff", ""))
                    opx_c = _safe_float(r.get("opex_sum_computed", ""))
                    opx_r = _safe_float(r.get("opex_sum_reference", ""))
                    opx_d = _safe_float(r.get("opex_diff", ""))
                    cpx_c = _safe_float(r.get("capex_sum_computed", ""))
                    cpx_r = _safe_float(r.get("capex_sum_reference", ""))
                    cpx_d = _safe_float(r.get("capex_diff", ""))
                    if year is None or not quarter:
                        actual_map = {}
                        break
                    actual_map[(year, quarter)] = {
                        "rev_c": rev_c,
                        "rev_r": rev_r,
                        "rev_d": rev_d,
                        "opx_c": opx_c,
                        "opx_r": opx_r,
                        "opx_d": opx_d,
                        "cpx_c": cpx_c,
                        "cpx_r": cpx_r,
                        "cpx_d": cpx_d,
                    }
                if actual_map and set(actual_map.keys()) == set(expected_keys):
                    all_ok = True
                    for key in expected_keys:
                        cmps = q_sums.get(key, {"revenue": 0.0, "opex": 0.0, "capex": 0.0})
                        refs = ref_map[key]
                        act = actual_map[key]
                        if (
                            act["rev_c"] is None
                            or act["rev_r"] is None
                            or act["rev_d"] is None
                            or act["opx_c"] is None
                            or act["opx_r"] is None
                            or act["opx_d"] is None
                            or act["cpx_c"] is None
                            or act["cpx_r"] is None
                            or act["cpx_d"] is None
                        ):
                            all_ok = False
                            break
                        if not (_approx_equal(act["rev_c"], cmps["revenue"]) and _approx_equal(act["opx_c"], cmps["opex"]) and _approx_equal(act["cpx_c"], cmps["capex"])):
                            all_ok = False
                            break
                        if not (_approx_equal(act["rev_r"], refs["revenue"]) and _approx_equal(act["opx_r"], refs["opex"]) and _approx_equal(act["cpx_r"], refs["capex"])):
                            all_ok = False
                            break
                        if not (_approx_equal(act["rev_d"], cmps["revenue"] - refs["revenue"]) and _approx_equal(act["opx_d"], cmps["opex"] - refs["opex"]) and _approx_equal(act["cpx_d"], cmps["capex"] - refs["capex"])):
                            all_ok = False
                            break
                    scores["reference_comparison_values_correct"] = 1.0 if all_ok else 0.0
                else:
                    scores["reference_comparison_values_correct"] = 0.0
            else:
                scores["reference_comparison_values_correct"] = 0.0
        else:
            scores["reference_comparison_values_correct"] = 0.0
    else:
        scores["reference_comparison_structure"] = 0.0
        scores["reference_comparison_values_correct"] = 0.0

    top_path = workspace / "outputs" / "summary" / "top_margin_by_quarter.csv"
    ok, top_fields, top_rows = _read_output_csv(top_path)
    expected_top_fields = ["year", "quarter", "utility_with_max_margin", "operating_margin"]
    if ok and top_fields == expected_top_fields:
        scores["top_margin_structure"] = 1.0
        if groups is not None:
            per_q: Dict[Tuple[int, str], Tuple[str, float]] = {}
            margins: Dict[Tuple[str, int, str], float] = {}
            for (util, year, quarter), vals in groups.items():
                rev = vals["revenue"]
                opx = vals["opex"]
                margin = (rev - opx) / rev if rev != 0 else 0.0
                margins[(util, year, quarter)] = margin
            by_q_candidates: Dict[Tuple[int, str], List[Tuple[str, float]]] = {}
            for (util, year, quarter), m in margins.items():
                key = (year, quarter)
                by_q_candidates.setdefault(key, []).append((util, m))
            for key, lst in by_q_candidates.items():
                lst_sorted = sorted(lst, key=lambda x: (-x[1], x[0]))
                per_q[key] = lst_sorted[0]
            actual_map: Dict[Tuple[int, str], Tuple[str, float]] = {}
            for r in top_rows:
                year = _safe_int(r.get("year", ""))
                quarter = r.get("quarter", "")
                util = r.get("utility_with_max_margin", "")
                m = _safe_float(r.get("operating_margin", ""))
                if year is None or not quarter or not util or m is None:
                    actual_map = {}
                    break
                actual_map[(year, quarter)] = (util, m)
            if actual_map and set(actual_map.keys()) == set(per_q.keys()):
                all_ok = True
                for key in per_q:
                    exp_util, exp_m = per_q[key]
                    act_util, act_m = actual_map[key]
                    if exp_util != act_util or not _approx_equal(exp_m, act_m):
                        all_ok = False
                        break
                scores["top_margin_values_correct"] = 1.0 if all_ok else 0.0
            else:
                scores["top_margin_values_correct"] = 0.0
        else:
            scores["top_margin_values_correct"] = 0.0
    else:
        scores["top_margin_structure"] = 0.0
        scores["top_margin_values_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()