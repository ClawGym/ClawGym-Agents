import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _to_float(val: str) -> Optional[float]:
    try:
        if val is None:
            return None
        v = str(val).strip()
        if v == "" or v.lower() == "none" or v.lower() == "nan":
            return None
        return float(v)
    except Exception:
        return None


def _compute_expected_outputs(workspace: Path) -> Optional[dict]:
    input_dir = workspace / "input"
    parcels_p = input_dir / "parcels.csv"
    heritage_p = input_dir / "heritage_register.csv"
    roi_p = input_dir / "roi_estimates.csv"

    parcels_h, parcels_rows = _safe_read_csv(parcels_p)
    heritage_h, heritage_rows = _safe_read_csv(heritage_p)
    roi_h, roi_rows = _safe_read_csv(roi_p)

    if any(x is None for x in [parcels_h, parcels_rows, heritage_h, heritage_rows, roi_h, roi_rows]):
        return None

    parcels_by_id = {r["parcel_id"]: r for r in parcels_rows if "parcel_id" in r}
    roi_by_id = {r["parcel_id"]: r for r in roi_rows if "parcel_id" in r}

    heritage_by_parcel: Dict[str, List[Dict[str, str]]] = {}
    for r in heritage_rows:
        pid = r.get("parcel_id")
        if not pid:
            continue
        heritage_by_parcel.setdefault(pid, []).append(r)

    def highest_level(levels: List[str]) -> Optional[str]:
        rank = {"A": 3, "B": 2, "C": 1}
        best = None
        best_rank = -1
        for lv in levels:
            if lv in rank and rank[lv] > best_rank:
                best = lv
                best_rank = rank[lv]
        return best

    allowed_zoning = {"Commercial", "Mixed Use", "Industrial"}

    excluded_heritage = []
    candidates = []

    excluded_by_flood = set()
    excluded_by_zoning = set()
    excluded_by_heritage_set = set()

    for pid, prow in parcels_by_id.items():
        if pid not in roi_by_id:
            continue

        flood_risk = prow.get("flood_risk", "").strip()
        zoning = prow.get("zoning", "").strip()
        if flood_risk == "High":
            excluded_by_flood.add(pid)
            continue
        if zoning not in allowed_zoning:
            excluded_by_zoning.add(pid)
            continue

        h_records = heritage_by_parcel.get(pid, [])
        levels = [rec.get("protection_level", "").strip() for rec in h_records]
        h_sites_count = len(h_records)
        hi = highest_level(levels) if h_sites_count > 0 else None

        if hi in ("A", "B"):
            excluded_by_heritage_set.add(pid)
            excluded_heritage.append({
                "parcel_id": pid,
                "highest_protection_level": hi,
                "heritage_sites_count": h_sites_count,
            })
            continue

        roi = roi_by_id[pid]
        est = _to_float(roi.get("est_roi_score", ""))
        infra = _to_float(roi.get("infra_upgrade_cost_million", ""))
        acq = _to_float(roi.get("acquisition_cost_million", ""))

        if est is None or infra is None or acq is None:
            continue

        heritage_penalty = 15.0 if ("C" in levels and hi == "C") else 0.0
        priority_score = est - 0.5 * infra - 0.2 * acq - heritage_penalty

        candidate = {
            "parcel_id": pid,
            "district": prow.get("district", ""),
            "zoning": zoning,
            "area_sq_m": _to_float(prow.get("area_sq_m", "")),
            "est_roi_score": est,
            "infra_upgrade_cost_million": infra,
            "acquisition_cost_million": acq,
            "heritage_sites_count": h_sites_count,
            "highest_protection_level": hi if hi is not None else "None",
            "flood_risk": flood_risk,
            "priority_score": priority_score,
        }
        candidates.append(candidate)

    candidates.sort(key=lambda r: (-r["priority_score"], r["parcel_id"]))
    for idx, r in enumerate(candidates, start=1):
        r["rank"] = idx

    top5_ids = [r["parcel_id"] for r in candidates[:5]]

    return {
        "parcels_headers": parcels_h,
        "heritage_headers": heritage_h,
        "roi_headers": roi_h,
        "parcels_rows": parcels_rows,
        "heritage_rows": heritage_rows,
        "roi_rows": roi_rows,
        "candidates": candidates,
        "excluded_due_to_heritage": excluded_heritage,
        "top5_ids": top5_ids,
        "excluded_counts": {
            "flood": len(excluded_by_flood),
            "zoning": len(excluded_by_zoning),
            "heritage": len(excluded_by_heritage_set),
        },
    }


def _approx_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def _contains_keywords(text: str, *keywords: str) -> bool:
    t = text.lower()
    return all(k.lower() in t for k in keywords)


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validator_script_present": 0.0,
        "validation_file_present": 0.0,
        "validation_reports_required_columns": 0.0,
        "validation_reports_uniqueness": 0.0,
        "validation_reports_allowed_protection_levels": 0.0,
        "validation_reports_join_coverage": 0.0,
        "validation_reports_numeric_parseability": 0.0,
        "excluded_csv_structure": 0.0,
        "excluded_csv_contents": 0.0,
        "priority_candidates_structure": 0.0,
        "priority_candidates_values": 0.0,
        "priority_candidates_sorted_and_ranked": 0.0,
        "executive_update_present_and_under_400w": 0.0,
        "executive_update_mentions_validation_and_coverage": 0.0,
        "executive_update_states_filtering_rules": 0.0,
        "executive_update_reports_exclusion_counts": 0.0,
        "executive_update_lists_top5": 0.0,
    }

    expected = _compute_expected_outputs(workspace)
    output_dir = workspace / "output"

    validate_script = workspace / "tools" / "validate.py"
    if validate_script.exists() and validate_script.is_file():
        scores["validator_script_present"] = 1.0

    validation_p = output_dir / "validation.txt"
    validation_text = _safe_read_text(validation_p)
    if validation_text is not None and validation_text.strip() != "":
        scores["validation_file_present"] = 1.0

        if _contains_keywords(validation_text, "required", "columns"):
            scores["validation_reports_required_columns"] = 1.0

        if ("parcel_id" in validation_text) and re.search(r"\bunique(ness)?\b", validation_text.lower()):
            scores["validation_reports_uniqueness"] = 1.0

        plc_ok = False
        for line in validation_text.splitlines():
            if "protection_level" in line.lower():
                if re.search(r"\bA\b", line) and re.search(r"\bB\b", line) and re.search(r"\bC\b", line):
                    plc_ok = True
                    break
                if "{A,B,C}" in line or "{A, B, C}" in line or "A,B,C" in line:
                    plc_ok = True
                    break
        if plc_ok:
            scores["validation_reports_allowed_protection_levels"] = 1.0

        jc_ok = False
        if _contains_keywords(validation_text, "coverage") and "%" in validation_text and re.search(r"orphan", validation_text.lower()):
            if re.search(r"roi", validation_text.lower()) and re.search(r"heritage", validation_text.lower()):
                jc_ok = True
        if jc_ok:
            scores["validation_reports_join_coverage"] = 1.0

        np_ok = False
        if re.search(r"numeric|parse", validation_text.lower()):
            need_cols = ["area_sq_m", "est_roi_score", "infra_upgrade_cost_million", "acquisition_cost_million"]
            if all(col in validation_text for col in need_cols):
                np_ok = True
        if np_ok:
            scores["validation_reports_numeric_parseability"] = 1.0

    excluded_p = output_dir / "excluded_due_to_heritage.csv"
    ex_h, ex_rows = _safe_read_csv(excluded_p)
    if ex_h is not None and ex_rows is not None:
        expected_headers = ["parcel_id", "highest_protection_level", "heritage_sites_count"]
        if ex_h == expected_headers:
            scores["excluded_csv_structure"] = 1.0

        if expected is not None:
            exp_map = {e["parcel_id"]: (e["highest_protection_level"], e["heritage_sites_count"]) for e in expected["excluded_due_to_heritage"]}
            act_map = {}
            try:
                for r in ex_rows:
                    pid = r.get("parcel_id")
                    hpl = r.get("highest_protection_level")
                    hsc = r.get("heritage_sites_count")
                    if pid is None or hpl is None or hsc is None:
                        raise ValueError
                    act_map[pid] = (hpl, int(float(hsc)))
                if set(act_map.keys()) == set(exp_map.keys()):
                    values_ok = True
                    for pid, (hpl, hsc) in act_map.items():
                        exp_hpl, exp_hsc = exp_map[pid]
                        if hpl != exp_hpl or hsc != exp_hsc:
                            values_ok = False
                            break
                    if values_ok:
                        scores["excluded_csv_contents"] = 1.0
            except Exception:
                pass

    candidates_p = output_dir / "priority_candidates.csv"
    cand_h, cand_rows = _safe_read_csv(candidates_p)
    if cand_h is not None and cand_rows is not None:
        expected_cand_headers = [
            "parcel_id",
            "district",
            "zoning",
            "area_sq_m",
            "est_roi_score",
            "infra_upgrade_cost_million",
            "acquisition_cost_million",
            "heritage_sites_count",
            "highest_protection_level",
            "flood_risk",
            "priority_score",
            "rank",
        ]
        if cand_h == expected_cand_headers:
            scores["priority_candidates_structure"] = 1.0

        if expected is not None:
            exp_list = expected["candidates"]
            exp_map = {r["parcel_id"]: r for r in exp_list}
            ok_values = True
            cand_ids = [r.get("parcel_id") for r in cand_rows]
            if set(cand_ids) != set(exp_map.keys()):
                ok_values = False
            else:
                for r in cand_rows:
                    pid = r.get("parcel_id")
                    if pid not in exp_map:
                        ok_values = False
                        break
                    er = exp_map[pid]
                    if r.get("district") != er["district"]:
                        ok_values = False
                        break
                    if r.get("zoning") != er["zoning"]:
                        ok_values = False
                        break
                    if r.get("flood_risk") != er["flood_risk"]:
                        ok_values = False
                        break
                    af_area = _to_float(r.get("area_sq_m", ""))
                    af_est = _to_float(r.get("est_roi_score", ""))
                    af_infra = _to_float(r.get("infra_upgrade_cost_million", ""))
                    af_acq = _to_float(r.get("acquisition_cost_million", ""))
                    af_ps = _to_float(r.get("priority_score", ""))
                    try:
                        af_rank = int(float(r.get("rank", "")))
                    except Exception:
                        af_rank = None
                    if not _approx_equal(af_area or 0.0, er["area_sq_m"] or 0.0, tol=1e-6):
                        ok_values = False
                        break
                    if not _approx_equal(af_est or 0.0, er["est_roi_score"] or 0.0, tol=1e-6):
                        ok_values = False
                        break
                    if not _approx_equal(af_infra or 0.0, er["infra_upgrade_cost_million"] or 0.0, tol=1e-6):
                        ok_values = False
                        break
                    if not _approx_equal(af_acq or 0.0, er["acquisition_cost_million"] or 0.0, tol=1e-6):
                        ok_values = False
                        break
                    if not _approx_equal(af_ps or 0.0, er["priority_score"] or 0.0, tol=5e-2):
                        ok_values = False
                        break
                    try:
                        af_hsc = int(float(r.get("heritage_sites_count", "")))
                    except Exception:
                        ok_values = False
                        break
                    if af_hsc != er["heritage_sites_count"]:
                        ok_values = False
                        break
                    if r.get("highest_protection_level") != er["highest_protection_level"]:
                        ok_values = False
                        break
                if ok_values:
                    scores["priority_candidates_values"] = 1.0

            try:
                ps_list = []
                rank_list = []
                for row in cand_rows:
                    ps = _to_float(row.get("priority_score", ""))
                    rk = int(float(row.get("rank", "")))
                    ps_list.append(ps)
                    rank_list.append(rk)
                sorted_desc = all(ps_list[i] >= ps_list[i + 1] - 1e-9 for i in range(len(ps_list) - 1))
                ranks_ok = rank_list == list(range(1, len(rank_list) + 1))
                if sorted_desc and ranks_ok:
                    scores["priority_candidates_sorted_and_ranked"] = 1.0
            except Exception:
                pass

    exec_p = output_dir / "executive_update.md"
    exec_text = _safe_read_text(exec_p)
    if exec_text is not None and exec_text.strip() != "":
        wc = _count_words(exec_text)
        if wc <= 420:
            scores["executive_update_present_and_under_400w"] = 1.0

        if (_contains_keywords(exec_text, "validation") or _contains_keywords(exec_text, "validated")) and _contains_keywords(exec_text, "coverage"):
            scores["executive_update_mentions_validation_and_coverage"] = 1.0

        if _contains_keywords(exec_text, "flood") and _contains_keywords(exec_text, "zoning") and _contains_keywords(exec_text, "heritage"):
            scores["executive_update_states_filtering_rules"] = 1.0

        def _has_kw_with_number(t: str, kw: str) -> bool:
            lines = t.splitlines()
            for line in lines:
                if kw.lower() in line.lower() and re.search(r"\d", line):
                    return True
            return False

        if _has_kw_with_number(exec_text, "flood") and _has_kw_with_number(exec_text, "zoning") and _has_kw_with_number(exec_text, "heritage"):
            scores["executive_update_reports_exclusion_counts"] = 1.0

        if expected is not None:
            top5_ids = expected["top5_ids"]
            ids_ok = all(idv in exec_text for idv in top5_ids)
            lines = exec_text.splitlines()
            per_id_ok = True
            bullet_lines = [ln for ln in lines if re.match(r"^\s*[-*]\s+", ln)]
            bullets_ok = len(bullet_lines) >= min(5, len(top5_ids))
            for pid in top5_ids:
                ok_line = False
                for ln in lines:
                    if pid in ln:
                        er = next((r for r in expected["candidates"] if r["parcel_id"] == pid), None)
                        if er is None:
                            continue
                        if er["district"] in ln and er["zoning"] in ln:
                            if ("None" in ln or " C" in ln or "(C" in ln or " C)" in ln):
                                if re.search(r"\d", ln):
                                    ok_line = True
                                    break
                if not ok_line:
                    per_id_ok = False
                    break
            if ids_ok and per_id_ok and bullets_ok:
                scores["executive_update_lists_top5"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()