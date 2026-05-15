import sys
import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter


def _read_csv_dicts(path: Path):
    if not path.exists() or not path.is_file():
        return None, None, f"Missing file: {path}"
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None, f"No header in {path}"
            rows = [row for row in reader]
            return header, rows, None
    except Exception as e:
        return None, None, f"Failed to read {path}: {e}"


def _parse_date_iso(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _to_int(x):
    try:
        f = float(x)
        if abs(f - int(round(f))) < 1e-9:
            return int(round(f))
        return int(x)
    except Exception:
        return None


def _quarter_label(dt):
    m = dt.month
    if 1 <= m <= 3:
        return "Q1"
    elif 4 <= m <= 6:
        return "Q2"
    elif 7 <= m <= 9:
        return "Q3"
    else:
        return "Q4"


def _ensure_exact_columns(header, expected):
    if header is None:
        return False
    return list(header) == list(expected)


def _round_float(x, digits=6):
    return round(float(x), digits)


def _build_expected(workspace: Path):
    soil_p = workspace / "input" / "soil_samples.csv"
    limits_p = workspace / "input" / "regulatory_limits.csv"
    parcels_p = workspace / "input" / "parcel_info.csv"

    soil_header, soil_rows, soil_err = _read_csv_dicts(soil_p)
    limits_header, limits_rows, limits_err = _read_csv_dicts(limits_p)
    parcels_header, parcels_rows, parcels_err = _read_csv_dicts(parcels_p)

    if any([soil_err, limits_err, parcels_err]):
        return {
            "ok": False,
            "error": "; ".join([e for e in [soil_err, limits_err, parcels_err] if e]),
        }

    active_parcels = set()
    try:
        for r in parcels_rows:
            pid = r.get("parcel_id")
            status = r.get("planted_status")
            if pid is None or status is None:
                continue
            if status.strip().lower() == "active":
                active_parcels.add(pid.strip())
    except Exception:
        return {"ok": False, "error": "Failed to process parcel_info.csv"}

    limits = {}
    try:
        for r in limits_rows:
            c = (r.get("contaminant") or "").strip()
            lim = _to_float(r.get("limit_mgkg"))
            if not c or lim is None:
                continue
            limits[c] = lim
    except Exception:
        return {"ok": False, "error": "Failed to process regulatory_limits.csv"}

    filtered = []
    try:
        for r in soil_rows:
            qa = (r.get("qa_flag") or "").strip()
            st = (r.get("sample_type") or "").strip()
            pid = (r.get("parcel_id") or "").strip()
            if qa != "OK":
                continue
            if st != "soil":
                continue
            if pid not in active_parcels:
                continue
            sid = (r.get("sample_id") or "").strip()
            contaminant = (r.get("contaminant") or "").strip()
            val = _to_float(r.get("value_mgkg"))
            sd_str = (r.get("sample_date") or "").strip()
            sd = _parse_date_iso(sd_str)
            if not sid or not contaminant or val is None or sd is None:
                continue
            filtered.append({
                "sample_id": sid,
                "parcel_id": pid,
                "sample_date": sd,
                "sample_date_str": sd.isoformat(),
                "contaminant": contaminant,
                "value_mgkg": float(val),
                "year": sd.year,
                "quarter": _quarter_label(sd),
            })
    except Exception:
        return {"ok": False, "error": "Failed to process soil_samples.csv"}

    qkey_stats = defaultdict(lambda: {"sum": 0.0, "count": 0})
    for r in filtered:
        key = (r["parcel_id"], r["contaminant"], r["year"], r["quarter"])
        qkey_stats[key]["sum"] += r["value_mgkg"]
        qkey_stats[key]["count"] += 1
    expected_quarterly = []
    for (pid, contaminant, year, qlabel), stat in qkey_stats.items():
        mean = stat["sum"] / stat["count"] if stat["count"] > 0 else 0.0
        expected_quarterly.append({
            "parcel_id": pid,
            "contaminant": contaminant,
            "year": int(year),
            "quarter": qlabel,
            "mean_mgkg": float(mean),
            "n_samples_in_quarter": int(stat["count"]),
        })

    expected_exceedances = []
    for r in filtered:
        cont = r["contaminant"]
        lim = limits.get(cont)
        if lim is None:
            continue
        if r["value_mgkg"] > lim:
            exc = r["value_mgkg"] - lim
            expected_exceedances.append({
                "sample_id": r["sample_id"],
                "parcel_id": r["parcel_id"],
                "sample_date": r["sample_date_str"],
                "contaminant": cont,
                "value_mgkg": float(r["value_mgkg"]),
                "limit_mgkg": float(lim),
                "exceedance_mgkg": float(exc),
            })
    expected_exceedances.sort(key=lambda d: (-d["exceedance_mgkg"], d["sample_id"]))

    by_pc = defaultdict(list)
    for r in filtered:
        key = (r["parcel_id"], r["contaminant"])
        by_pc[key].append(r)

    qmeans_by_pc = defaultdict(list)
    for (pid, cont, year, qlabel), stat in qkey_stats.items():
        mean = stat["sum"] / stat["count"] if stat["count"] > 0 else 0.0
        qmeans_by_pc[(pid, cont)].append({
            "year": year,
            "quarter": qlabel,
            "mean": mean,
        })

    expected_trends = []
    for (pid, cont), lst in by_pc.items():
        lst_sorted = sorted(lst, key=lambda d: d["sample_date"])
        n = len(lst_sorted)
        first_date = lst_sorted[0]["sample_date_str"]
        last_date = lst_sorted[-1]["sample_date_str"]
        first_val = float(lst_sorted[0]["value_mgkg"])
        last_val = float(lst_sorted[-1]["value_mgkg"])
        delta = last_val - first_val
        mean_overall = sum(d["value_mgkg"] for d in lst_sorted) / n if n > 0 else 0.0
        qset = set((d["year"], d["quarter"]) for d in lst_sorted)
        quarters_total = len(qset)
        lim = limits.get(cont)
        quarters_above = 0
        if lim is not None:
            for qm in qmeans_by_pc[(pid, cont)]:
                if qm["mean"] > lim:
                    quarters_above += 1
        expected_trends.append({
            "parcel_id": pid,
            "contaminant": cont,
            "n_samples_used": int(n),
            "first_sample_date": first_date,
            "last_sample_date": last_date,
            "first_value_mgkg": float(first_val),
            "last_value_mgkg": float(last_val),
            "delta_mgkg": float(delta),
            "mean_mgkg_overall": float(mean_overall),
            "quarters_total": int(quarters_total),
            "quarters_above_limit": int(quarters_above),
        })

    mean_exc_by_pc = {}
    for (pid, cont), lst in by_pc.items():
        lim = limits.get(cont)
        if lim is None:
            mean_exc_by_pc[(pid, cont)] = 0.0
            continue
        ex_vals = [d["value_mgkg"] - lim for d in lst if d["value_mgkg"] > lim]
        if ex_vals:
            mean_exc_by_pc[(pid, cont)] = sum(ex_vals) / len(ex_vals)
        else:
            mean_exc_by_pc[(pid, cont)] = 0.0

    by_cont_trends = defaultdict(list)
    for tr in expected_trends:
        by_cont_trends[tr["contaminant"]].append(tr)
    expected_top_rising = []
    for cont, trs in by_cont_trends.items():
        eligible = [t for t in trs if t["n_samples_used"] >= 3 and t["delta_mgkg"] > 0]
        eligible.sort(key=lambda t: (-t["delta_mgkg"], t["parcel_id"]))
        top = eligible[:3]
        rank = 1
        for t in top:
            mean_exc = mean_exc_by_pc.get((t["parcel_id"], cont), 0.0)
            expected_top_rising.append({
                "contaminant": cont,
                "rank": int(rank),
                "parcel_id": t["parcel_id"],
                "n_samples_used": int(t["n_samples_used"]),
                "delta_mgkg": float(t["delta_mgkg"]),
                "mean_exceedance_mgkg_over_limit": float(mean_exc),
            })
            rank += 1
    expected_top_rising.sort(key=lambda d: (d["contaminant"], d["rank"]))

    return {
        "ok": True,
        "expected": {
            "quarterly_means": expected_quarterly,
            "exceedances": expected_exceedances,
            "parcel_trends": expected_trends,
            "top_rising_parcels": expected_top_rising,
        }
    }


def _normalize_quarterly_rows(rows):
    norm = []
    for r in rows:
        pid = (r.get("parcel_id") or "").strip()
        cont = (r.get("contaminant") or "").strip()
        year = _to_int(r.get("year"))
        q = (r.get("quarter") or "").strip()
        mean = _to_float(r.get("mean_mgkg"))
        n = _to_int(r.get("n_samples_in_quarter"))
        if not pid or not cont or year is None or q not in {"Q1", "Q2", "Q3", "Q4"} or mean is None or n is None:
            return None
        norm.append((pid, cont, int(year), q, _round_float(mean), int(n)))
    return norm


def _normalize_exceedances_rows(rows):
    norm = []
    for r in rows:
        sid = (r.get("sample_id") or "").strip()
        pid = (r.get("parcel_id") or "").strip()
        sd = (r.get("sample_date") or "").strip()
        cont = (r.get("contaminant") or "").strip()
        val = _to_float(r.get("value_mgkg"))
        lim = _to_float(r.get("limit_mgkg"))
        exc = _to_float(r.get("exceedance_mgkg"))
        sd_parsed = _parse_date_iso(sd)
        if not sid or not pid or not cont or sd_parsed is None or val is None or lim is None or exc is None:
            return None
        sd_norm = sd_parsed.isoformat()
        norm.append((sid, pid, sd_norm, cont, _round_float(val), _round_float(lim), _round_float(exc)))
    return norm


def _normalize_trends_rows(rows):
    norm = []
    for r in rows:
        pid = (r.get("parcel_id") or "").strip()
        cont = (r.get("contaminant") or "").strip()
        n = _to_int(r.get("n_samples_used"))
        fs = (r.get("first_sample_date") or "").strip()
        ls = (r.get("last_sample_date") or "").strip()
        fs_d = _parse_date_iso(fs)
        ls_d = _parse_date_iso(ls)
        fv = _to_float(r.get("first_value_mgkg"))
        lv = _to_float(r.get("last_value_mgkg"))
        delta = _to_float(r.get("delta_mgkg"))
        mean_overall = _to_float(r.get("mean_mgkg_overall"))
        qt = _to_int(r.get("quarters_total"))
        qa = _to_int(r.get("quarters_above_limit"))
        if (not pid or not cont or n is None or fs_d is None or ls_d is None or
                fv is None or lv is None or delta is None or mean_overall is None or
                qt is None or qa is None):
            return None
        norm.append((
            pid, cont, int(n), fs_d.isoformat(), ls_d.isoformat(),
            _round_float(fv), _round_float(lv), _round_float(delta),
            _round_float(mean_overall), int(qt), int(qa)
        ))
    return norm


def _normalize_top_rising_rows(rows):
    norm = []
    for r in rows:
        cont = (r.get("contaminant") or "").strip()
        rank = _to_int(r.get("rank"))
        pid = (r.get("parcel_id") or "").strip()
        n = _to_int(r.get("n_samples_used"))
        delta = _to_float(r.get("delta_mgkg"))
        mean_exc = _to_float(r.get("mean_exceedance_mgkg_over_limit"))
        if not cont or rank is None or not pid or n is None or delta is None or mean_exc is None:
            return None
        norm.append((cont, int(rank), pid, int(n), _round_float(delta), _round_float(mean_exc)))
    return norm


def _compare_row_multisets(expected_list, actual_list):
    return Counter(expected_list) == Counter(actual_list)


def _is_nonincreasing(values):
    for i in range(1, len(values)):
        if values[i] > values[i - 1] + 1e-9:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "quarterly_means_columns": 0.0,
        "quarterly_means_content": 0.0,
        "exceedances_columns": 0.0,
        "exceedances_sorted_and_content": 0.0,
        "parcel_trends_columns": 0.0,
        "parcel_trends_content": 0.0,
        "top_rising_parcels_columns": 0.0,
        "top_rising_parcels_sorted_and_content": 0.0,
    }

    exp = _build_expected(workspace)
    if not exp.get("ok"):
        return scores

    expected = exp["expected"]

    qm_path = workspace / "outputs" / "quarterly_means.csv"
    qm_header, qm_rows, qm_err = _read_csv_dicts(qm_path)
    expected_qm_cols = ["parcel_id", "contaminant", "year", "quarter", "mean_mgkg", "n_samples_in_quarter"]
    if qm_err is None and _ensure_exact_columns(qm_header, expected_qm_cols):
        scores["quarterly_means_columns"] = 1.0
        actual_norm = _normalize_quarterly_rows(qm_rows)
        expected_norm = _normalize_quarterly_rows([
            {k: v for k, v in row.items()} for row in expected["quarterly_means"]
        ])
        if actual_norm is not None and expected_norm is not None:
            if _compare_row_multisets(expected_norm, actual_norm):
                scores["quarterly_means_content"] = 1.0

    ex_path = workspace / "outputs" / "exceedances.csv"
    ex_header, ex_rows, ex_err = _read_csv_dicts(ex_path)
    expected_ex_cols = ["sample_id", "parcel_id", "sample_date", "contaminant", "value_mgkg", "limit_mgkg", "exceedance_mgkg"]
    if ex_err is None and _ensure_exact_columns(ex_header, expected_ex_cols):
        scores["exceedances_columns"] = 1.0
        actual_norm = _normalize_exceedances_rows(ex_rows)
        expected_norm = _normalize_exceedances_rows([
            {k: v for k, v in row.items()} for row in expected["exceedances"]
        ])
        if actual_norm is not None and expected_norm is not None:
            content_ok = _compare_row_multisets(expected_norm, actual_norm)
            try:
                exc_values = []
                for r in ex_rows:
                    v = _to_float(r.get("exceedance_mgkg"))
                    if v is None:
                        exc_values = None
                        break
                    exc_values.append(v)
                sorted_ok = exc_values is not None and _is_nonincreasing(exc_values)
            except Exception:
                sorted_ok = False
            if content_ok and sorted_ok:
                scores["exceedances_sorted_and_content"] = 1.0

    pt_path = workspace / "outputs" / "parcel_trends.csv"
    pt_header, pt_rows, pt_err = _read_csv_dicts(pt_path)
    expected_pt_cols = [
        "parcel_id", "contaminant", "n_samples_used", "first_sample_date", "last_sample_date",
        "first_value_mgkg", "last_value_mgkg", "delta_mgkg", "mean_mgkg_overall",
        "quarters_total", "quarters_above_limit"
    ]
    if pt_err is None and _ensure_exact_columns(pt_header, expected_pt_cols):
        scores["parcel_trends_columns"] = 1.0
        actual_norm = _normalize_trends_rows(pt_rows)
        expected_norm = _normalize_trends_rows([
            {k: v for k, v in row.items()} for row in expected["parcel_trends"]
        ])
        if actual_norm is not None and expected_norm is not None:
            if _compare_row_multisets(expected_norm, actual_norm):
                scores["parcel_trends_content"] = 1.0

    trp_path = workspace / "outputs" / "top_rising_parcels.csv"
    trp_header, trp_rows, trp_err = _read_csv_dicts(trp_path)
    expected_trp_cols = ["contaminant", "rank", "parcel_id", "n_samples_used", "delta_mgkg", "mean_exceedance_mgkg_over_limit"]
    if trp_err is None and _ensure_exact_columns(trp_header, expected_trp_cols):
        scores["top_rising_parcels_columns"] = 1.0
        actual_norm = _normalize_top_rising_rows(trp_rows)
        expected_norm = _normalize_top_rising_rows([
            {k: v for k, v in row.items()} for row in expected["top_rising_parcels"]
        ])
        if actual_norm is not None and expected_norm is not None:
            content_ok = _compare_row_multisets(expected_norm, actual_norm)
            try:
                sorted_ok = True
                ranks_by_cont = defaultdict(list)
                for r in trp_rows:
                    cont = (r.get("contaminant") or "").strip()
                    rank = _to_int(r.get("rank"))
                    if not cont or rank is None:
                        sorted_ok = False
                        break
                    ranks_by_cont[cont].append(rank)
                keys = [((r.get("contaminant") or "").strip(), _to_int(r.get("rank"))) for r in trp_rows]
                if any([k[0] == "" or k[1] is None for k in keys]):
                    sorted_ok = False
                else:
                    if keys != sorted(keys, key=lambda x: (x[0], x[1])):
                        sorted_ok = False
                if sorted_ok:
                    for cont, ranks in ranks_by_cont.items():
                        unique_sorted = sorted(ranks)
                        for i, rk in enumerate(unique_sorted, start=1):
                            if rk != i:
                                sorted_ok = False
                                break
                        if not sorted_ok:
                            break
            except Exception:
                sorted_ok = False
            if content_ok and sorted_ok:
                scores["top_rising_parcels_sorted_and_content"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()