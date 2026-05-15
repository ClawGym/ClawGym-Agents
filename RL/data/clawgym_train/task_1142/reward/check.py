import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        try:
            return float(s.replace(",", ""))
        except Exception:
            return None


def _to_int(val) -> Optional[int]:
    f = _to_float(val)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _parse_bool(val) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in {"true", "t", "yes", "y", "1"}:
        return True
    if s in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    else:
        return (vals[mid - 1] + vals[mid]) / 2.0


def _load_thresholds_yaml(path: Path) -> Optional[Dict]:
    """
    Minimal YAML parser for a simple structure:
    units: ug/L
    thresholds:
      analyte: value
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    units = None
    thresholds: Dict[str, float] = {}
    in_thresholds = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^\s*units\s*:\s*(.+)$", line):
            m = re.match(r"^\s*units\s*:\s*(.+)$", line)
            if m:
                units = m.group(1).strip()
            continue
        if re.match(r"^\s*thresholds\s*:\s*$", line):
            in_thresholds = True
            continue
        if in_thresholds:
            m = re.match(r"^\s+([A-Za-z0-9_.\-]+)\s*:\s*([+-]?[0-9]*\.?[0-9]+)\s*$", line)
            if m:
                name = m.group(1).strip()
                val = float(m.group(2))
                thresholds[name] = val
            else:
                if line.strip() == "":
                    continue
                return None
    if units is None or not thresholds:
        return None
    return {"units": units, "thresholds": thresholds}


def _compute_expected(workspace: Path) -> Optional[Dict]:
    samples_path = workspace / "input" / "samples.csv"
    thresholds_path = workspace / "config" / "thresholds.yaml"

    th = _load_thresholds_yaml(thresholds_path)
    if th is None:
        return None
    units = th.get("units")
    thresholds = th.get("thresholds", {})

    headers, rows = _read_csv_safe(samples_path)
    if headers is None or rows is None:
        return None

    required_input_cols = ["sample_id", "site", "date", "analyte", "value_ug_L"]
    for col in required_input_cols:
        if col not in headers:
            return None

    exceedances = []
    by_analyte: Dict[str, List[float]] = {}
    by_analyte_exceed_count: Dict[str, int] = {}
    by_site_analyte_values: Dict[Tuple[str, str], List[float]] = {}
    by_site_analyte_exceed_count: Dict[Tuple[str, str], int] = {}

    for r in rows:
        analyte = (r.get("analyte") or "").strip()
        site = (r.get("site") or "").strip()
        sample_id = (r.get("sample_id") or "").strip()
        date = (r.get("date") or "").strip()
        value = _to_float(r.get("value_ug_L"))
        if analyte == "" or site == "" or sample_id == "" or date == "" or value is None:
            return None
        thr = thresholds.get(analyte)
        if thr is None:
            return None
        exceed = value > thr
        exceed_amt = (value - thr) if exceed else 0.0
        exceedances.append({
            "sample_id": sample_id,
            "site": site,
            "date": date,
            "analyte": analyte,
            "value_ug_L": value,
            "threshold_ug_L": float(thr),
            "exceedance": exceed,
            "exceedance_amount_ug_L": exceed_amt,
        })
        by_analyte.setdefault(analyte, []).append(value)
        by_analyte_exceed_count[analyte] = by_analyte_exceed_count.get(analyte, 0) + (1 if exceed else 0)
        key = (site, analyte)
        by_site_analyte_values.setdefault(key, []).append(value)
        by_site_analyte_exceed_count[key] = by_site_analyte_exceed_count.get(key, 0) + (1 if exceed else 0)

    summary_by_analyte = []
    for analyte, values in by_analyte.items():
        n = len(values)
        mean = sum(values) / n if n > 0 else 0.0
        med = _median(values) if n > 0 else 0.0
        maxv = max(values) if n > 0 else 0.0
        n_exc = by_analyte_exceed_count.get(analyte, 0)
        pct_exc = (n_exc / n) if n > 0 else 0.0
        summary_by_analyte.append({
            "analyte": analyte,
            "n_samples": n,
            "mean_ug_L": mean,
            "median_ug_L": med,
            "max_ug_L": maxv,
            "n_exceeding": n_exc,
            "pct_exceeding": pct_exc,
        })

    summary_by_site_analyte = []
    for (site, analyte), values in by_site_analyte_values.items():
        n = len(values)
        mean = sum(values) / n if n > 0 else 0.0
        maxv = max(values) if n > 0 else 0.0
        n_exc = by_site_analyte_exceed_count.get((site, analyte), 0)
        pct_exc = (n_exc / n) if n > 0 else 0.0
        summary_by_site_analyte.append({
            "site": site,
            "analyte": analyte,
            "n_samples": n,
            "mean_ug_L": mean,
            "max_ug_L": maxv,
            "pct_exceeding": pct_exc,
        })

    return {
        "units": units,
        "thresholds": thresholds,
        "exceedances": exceedances,
        "summary_by_analyte": summary_by_analyte,
        "summary_by_site_analyte": summary_by_site_analyte,
    }


def _required_headers_exceedances() -> List[str]:
    return [
        "sample_id",
        "site",
        "date",
        "analyte",
        "value_ug_L",
        "threshold_ug_L",
        "exceedance",
        "exceedance_amount_ug_L",
    ]


def _required_headers_summary_by_analyte() -> List[str]:
    return [
        "analyte",
        "n_samples",
        "mean_ug_L",
        "median_ug_L",
        "max_ug_L",
        "n_exceeding",
        "pct_exceeding",
    ]


def _required_headers_summary_by_site_analyte() -> List[str]:
    return [
        "site",
        "analyte",
        "n_samples",
        "mean_ug_L",
        "max_ug_L",
        "pct_exceeding",
    ]


def _natural_sample_id_key(sample_id: str) -> Tuple[int, str]:
    m = re.search(r"(\d+)", sample_id or "")
    if m:
        return (int(m.group(1)), sample_id or "")
    return (0, sample_id or "")


def _sort_exceedances(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(rows, key=lambda r: _natural_sample_id_key(r.get("sample_id", "")))


def _sort_summary_by_analyte(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(rows, key=lambda r: (r.get("analyte") or ""))


def _sort_summary_by_site_analyte(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(rows, key=lambda r: (r.get("site") or "", r.get("analyte") or ""))


def _compare_rows(expected: List[Dict], actual: List[Dict[str, str]], columns: List[str],
                  numeric_cols: set, int_cols: set, bool_cols: set) -> bool:
    if len(expected) != len(actual):
        return False
    for exp_row, act_row in zip(expected, actual):
        for col in columns:
            if col in bool_cols:
                exp_bool = bool(exp_row[col])
                act_bool = _parse_bool(act_row.get(col))
                if act_bool is None or exp_bool != act_bool:
                    return False
            elif col in int_cols:
                exp_int = int(exp_row[col])
                act_int = _to_int(act_row.get(col))
                if act_int is None or exp_int != act_int:
                    return False
            elif col in numeric_cols:
                exp_float = float(exp_row[col])
                act_float = _to_float(act_row.get(col))
                if act_float is None or not _almost_equal(exp_float, act_float):
                    return False
            else:
                exp_str = str(exp_row[col])
                act_str = str(act_row.get(col, ""))
                if exp_str != act_str:
                    return False
    return True


def _extract_numbers_from_line(line: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[+-]?\d+(?:\.\d+)?", line):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def _log_contains_cli_command(text: str) -> bool:
    if not text:
        return False
    for line in text.splitlines():
        s = line.strip()
        if s == "":
            continue
        if "--data input/samples.csv" in s and "--config config/thresholds.yaml" in s and "--outdir out" in s and ("python" in s or "python3" in s):
            return True
    return False


def _log_lists_thresholds_with_units(text: str, thresholds: Dict[str, float]) -> bool:
    if not text:
        return False
    ok = True
    lines = text.splitlines()
    for analyte, expected_val in thresholds.items():
        found = False
        for line in lines:
            if analyte.lower() in line.lower() and "ug/l" in line.lower():
                nums = _extract_numbers_from_line(line)
                for num in nums:
                    if _almost_equal(num, float(expected_val)):
                        found = True
                        break
            if found:
                break
        if not found:
            ok = False
            break
    return ok


def _log_confirms_units(text: str) -> bool:
    if not text:
        return False
    for line in text.splitlines():
        l = line.lower()
        if "unit" in l and "ug/l" in l:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_present": 0.0,
        "exceedances_structure": 0.0,
        "exceedances_values_correct": 0.0,
        "summary_by_analyte_structure": 0.0,
        "summary_by_analyte_values_correct": 0.0,
        "summary_by_site_analyte_structure": 0.0,
        "summary_by_site_analyte_values_correct": 0.0,
        "log_includes_cli_command": 0.0,
        "log_lists_thresholds_with_units": 0.0,
        "log_confirms_units_match": 0.0,
    }

    out_dir = workspace / "out"
    exceedances_csv = out_dir / "exceedances.csv"
    summary_analyte_csv = out_dir / "summary_by_analyte.csv"
    summary_site_analyte_csv = out_dir / "summary_by_site_analyte.csv"
    run_log_txt = out_dir / "run_log.txt"

    if exceedances_csv.exists() and summary_analyte_csv.exists() and summary_site_analyte_csv.exists() and run_log_txt.exists():
        scores["outputs_present"] = 1.0

    ex_headers, ex_rows = _read_csv_safe(exceedances_csv) if exceedances_csv.exists() else (None, None)
    sa_headers, sa_rows = _read_csv_safe(summary_analyte_csv) if summary_analyte_csv.exists() else (None, None)
    ss_headers, ss_rows = _read_csv_safe(summary_site_analyte_csv) if summary_site_analyte_csv.exists() else (None, None)

    req_ex_headers = _required_headers_exceedances()
    if ex_headers is not None and ex_rows is not None and ex_headers == req_ex_headers:
        scores["exceedances_structure"] = 1.0

    req_sa_headers = _required_headers_summary_by_analyte()
    if sa_headers is not None and sa_rows is not None and sa_headers == req_sa_headers:
        scores["summary_by_analyte_structure"] = 1.0

    req_ss_headers = _required_headers_summary_by_site_analyte()
    if ss_headers is not None and ss_rows is not None and ss_headers == req_ss_headers:
        scores["summary_by_site_analyte_structure"] = 1.0

    expected = _compute_expected(workspace)

    if expected is not None:
        if ex_headers is not None and ex_rows is not None and ex_headers == req_ex_headers:
            expected_ex_rows = []
            for r in expected["exceedances"]:
                expected_ex_rows.append({
                    "sample_id": r["sample_id"],
                    "site": r["site"],
                    "date": r["date"],
                    "analyte": r["analyte"],
                    "value_ug_L": r["value_ug_L"],
                    "threshold_ug_L": r["threshold_ug_L"],
                    "exceedance": r["exceedance"],
                    "exceedance_amount_ug_L": r["exceedance_amount_ug_L"],
                })
            expected_ex_rows = _sort_exceedances(expected_ex_rows)
            actual_ex_rows = _sort_exceedances(ex_rows)

            if _compare_rows(
                expected_ex_rows,
                actual_ex_rows,
                req_ex_headers,
                numeric_cols={"value_ug_L", "threshold_ug_L", "exceedance_amount_ug_L"},
                int_cols=set(),
                bool_cols={"exceedance"},
            ):
                scores["exceedances_values_correct"] = 1.0

        if sa_headers is not None and sa_rows is not None and sa_headers == req_sa_headers:
            expected_sa_rows = []
            for r in expected["summary_by_analyte"]:
                expected_sa_rows.append({
                    "analyte": r["analyte"],
                    "n_samples": r["n_samples"],
                    "mean_ug_L": r["mean_ug_L"],
                    "median_ug_L": r["median_ug_L"],
                    "max_ug_L": r["max_ug_L"],
                    "n_exceeding": r["n_exceeding"],
                    "pct_exceeding": r["pct_exceeding"],
                })
            expected_sa_rows = _sort_summary_by_analyte(expected_sa_rows)
            actual_sa_rows = _sort_summary_by_analyte(sa_rows)

            if _compare_rows(
                expected_sa_rows,
                actual_sa_rows,
                req_sa_headers,
                numeric_cols={"mean_ug_L", "median_ug_L", "max_ug_L", "pct_exceeding"},
                int_cols={"n_samples", "n_exceeding"},
                bool_cols=set(),
            ):
                scores["summary_by_analyte_values_correct"] = 1.0

        if ss_headers is not None and ss_rows is not None and ss_headers == req_ss_headers:
            expected_ss_rows = []
            for r in expected["summary_by_site_analyte"]:
                expected_ss_rows.append({
                    "site": r["site"],
                    "analyte": r["analyte"],
                    "n_samples": r["n_samples"],
                    "mean_ug_L": r["mean_ug_L"],
                    "max_ug_L": r["max_ug_L"],
                    "pct_exceeding": r["pct_exceeding"],
                })
            expected_ss_rows = _sort_summary_by_site_analyte(expected_ss_rows)
            actual_ss_rows = _sort_summary_by_site_analyte(ss_rows)

            if _compare_rows(
                expected_ss_rows,
                actual_ss_rows,
                req_ss_headers,
                numeric_cols={"mean_ug_L", "max_ug_L", "pct_exceeding"},
                int_cols={"n_samples"},
                bool_cols=set(),
            ):
                scores["summary_by_site_analyte_values_correct"] = 1.0

    log_text = _read_text_safe(run_log_txt) if run_log_txt.exists() else None
    if log_text:
        if _log_contains_cli_command(log_text):
            scores["log_includes_cli_command"] = 1.0
        if expected is not None and isinstance(expected.get("thresholds"), dict):
            if _log_lists_thresholds_with_units(log_text, expected["thresholds"]):
                scores["log_lists_thresholds_with_units"] = 1.0
        if _log_confirms_units(log_text):
            scores["log_confirms_units_match"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()