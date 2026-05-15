import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime

# -------------------------
# Helper functions
# -------------------------

def safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames if reader.fieldnames is not None else []
    except Exception:
        return None, None


def to_float_safe(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def canonicalize_metric(metric: str) -> str:
    # Normalize variants: Leq and LAeq → LAeq; Lmax and LAmax → LAmax; L10 → L10; SEL → SEL
    if metric is None:
        return ""
    m = metric.strip()
    mapping = {
        "Leq": "LAeq",
        "LAeq": "LAeq",
        "Lmax": "LAmax",
        "LAmax": "LAmax",
        "L10": "L10",
        "SEL": "SEL",
    }
    return mapping.get(m, m)


def build_threshold_index(threshold_rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    index: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for r in threshold_rows:
        zone = (r.get("zone") or "").strip()
        timeslot = (r.get("timeslot") or "").strip()
        canon = (r.get("canonical_metric") or "").strip()
        limit = to_float_safe(r.get("limit_dba"))
        ordinance = (r.get("ordinance_section") or "").strip()
        if zone and timeslot and canon and limit is not None:
            index[(zone, timeslot, canon)] = {
                "limit_dba": limit,
                "ordinance_section": ordinance,
            }
    return index


def compute_expected_from_inputs(workspace: Path) -> Dict[str, Any]:
    # Returns a dict with keys: ok, err, expected_standardized, thresholds_index, expected_exceedances, expected_unmapped, metrics_present
    result = {
        "ok": False,
        "error": "",
        "expected_standardized": [],
        "thresholds_index": {},
        "expected_exceedances": [],
        "expected_unmapped": [],
        "metrics_present": set(),
    }
    meas_path = workspace / "input" / "measurements_2023_q4.csv"
    thr_path = workspace / "input" / "zone_thresholds.csv"
    meas_rows, meas_header = safe_read_csv(meas_path)
    thr_rows, thr_header = safe_read_csv(thr_path)
    if meas_rows is None or thr_rows is None:
        result["error"] = "Missing or unreadable input CSVs."
        return result

    thresholds_index = build_threshold_index(thr_rows)
    expected_standardized = []
    for r in meas_rows:
        sensor_id = (r.get("sensor_id") or "").strip()
        timestamp_iso = (r.get("timestamp_iso") or "").strip()
        zone = (r.get("zone") or "").strip()
        timeslot = (r.get("timeslot") or "").strip()
        original_metric = (r.get("metric") or "").strip()
        canonical_metric = canonicalize_metric(original_metric)
        value_dba = to_float_safe(r.get("value_dba"))
        expected_standardized.append({
            "sensor_id": sensor_id,
            "timestamp_iso": timestamp_iso,
            "zone": zone,
            "timeslot": timeslot,
            "original_metric": original_metric,
            "canonical_metric": canonical_metric,
            "value_dba": value_dba,
        })
    # Compute expected exceedances and unmapped
    expected_exceedances = []
    expected_unmapped = []
    metrics_present = set()
    for r in expected_standardized:
        cm = r["canonical_metric"]
        metrics_present.add(cm)
        key = (r["zone"], r["timeslot"], cm)
        if key in thresholds_index and r["value_dba"] is not None:
            limit = thresholds_index[key]["limit_dba"]
            ordinance = thresholds_index[key]["ordinance_section"]
            if r["value_dba"] > limit:
                expected_exceedances.append({
                    "sensor_id": r["sensor_id"],
                    "timestamp_iso": r["timestamp_iso"],
                    "zone": r["zone"],
                    "timeslot": r["timeslot"],
                    "canonical_metric": cm,
                    "value_dba": r["value_dba"],
                    "limit_dba": limit,
                    "exceedance_dba": r["value_dba"] - limit,
                    "ordinance_section": ordinance,
                })
        else:
            # Unmapped if there is no threshold for this canonical metric in the zone+timeslot
            expected_unmapped.append({
                "sensor_id": r["sensor_id"],
                "timestamp_iso": r["timestamp_iso"],
                "metric": r["original_metric"],
                "value_dba": r["value_dba"],
                "zone": r["zone"],
                "timeslot": r["timeslot"],
                "canonical_metric": cm,
            })
    result["ok"] = True
    result["expected_standardized"] = expected_standardized
    result["thresholds_index"] = thresholds_index
    result["expected_exceedances"] = expected_exceedances
    result["expected_unmapped"] = expected_unmapped
    result["metrics_present"] = metrics_present
    return result


def read_output_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return safe_read_csv(path)


def headers_match_exact(actual: Optional[List[str]], expected: List[str]) -> bool:
    if actual is None:
        return False
    return actual == expected


def rows_to_set_for_standardized(rows: List[Dict[str, str]]) -> set:
    s = set()
    for r in rows:
        try:
            t = (
                (r.get("sensor_id") or "").strip(),
                (r.get("timestamp_iso") or "").strip(),
                (r.get("zone") or "").strip(),
                (r.get("timeslot") or "").strip(),
                (r.get("original_metric") or "").strip(),
                (r.get("canonical_metric") or "").strip(),
                round(to_float_safe(r.get("value_dba")) if to_float_safe(r.get("value_dba")) is not None else float("nan"), 6),
            )
            s.add(t)
        except Exception:
            # malformed row; include sentinel to cause mismatch
            s.add(("__ERR__",))
    return s


def rows_to_set_for_unmapped(rows: List[Dict[str, str]]) -> set:
    s = set()
    for r in rows:
        try:
            t = (
                (r.get("sensor_id") or "").strip(),
                (r.get("timestamp_iso") or "").strip(),
                (r.get("metric") or "").strip(),
                round(to_float_safe(r.get("value_dba")) if to_float_safe(r.get("value_dba")) is not None else float("nan"), 6),
                (r.get("zone") or "").strip(),
                (r.get("timeslot") or "").strip(),
                (r.get("canonical_metric") or "").strip(),
            )
            s.add(t)
        except Exception:
            s.add(("__ERR__",))
    return s


def expected_set_for_standardized(expected_rows: List[Dict[str, Any]]) -> set:
    s = set()
    for r in expected_rows:
        s.add((
            r["sensor_id"],
            r["timestamp_iso"],
            r["zone"],
            r["timeslot"],
            r["original_metric"],
            r["canonical_metric"],
            round(r["value_dba"] if r["value_dba"] is not None else float("nan"), 6),
        ))
    return s


def expected_set_for_unmapped(expected_rows: List[Dict[str, Any]]) -> set:
    s = set()
    for r in expected_rows:
        s.add((
            r["sensor_id"],
            r["timestamp_iso"],
            r["metric"],
            round(r["value_dba"] if r["value_dba"] is not None else float("nan"), 6),
            r["zone"],
            r["timeslot"],
            r["canonical_metric"],
        ))
    return s


def index_exceedances(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, str, str, str], Dict[str, Any]]:
    idx: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
    for r in rows:
        key = (
            (r.get("sensor_id") or "").strip(),
            (r.get("timestamp_iso") or "").strip(),
            (r.get("zone") or "").strip(),
            (r.get("timeslot") or "").strip(),
            (r.get("canonical_metric") or "").strip(),
        )
        val = {
            "value_dba": to_float_safe(r.get("value_dba")),
            "limit_dba": to_float_safe(r.get("limit_dba")),
            "exceedance_dba": to_float_safe(r.get("exceedance_dba")),
            "ordinance_section": (r.get("ordinance_section") or "").strip(),
        }
        idx[key] = val
    return idx


def iso8601_like(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    # Accept common ISO 8601 formats, including Z
    try:
        # Replace Z with +00:00 for parsing
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        # Try strict formats
        patterns = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d",
        ]
        for p in patterns:
            try:
                datetime.strptime(s, p)
                return True
            except Exception:
                continue
        return False


def domain_suffix_type(domain: str) -> Optional[str]:
    domain = domain.strip().lower()
    if domain.endswith(".gov"):
        return "gov"
    if domain.endswith(".edu"):
        return "edu"
    if domain.endswith(".org"):
        return "org"
    return None


def extract_int_from_line(line: str) -> Optional[int]:
    m = re.findall(r"(-?\d+)", line)
    if not m:
        return None
    try:
        return int(m[0])
    except Exception:
        return None


def find_line_with_keyword(lines: List[str], keyword: str) -> Optional[str]:
    kw = keyword.lower()
    for ln in lines:
        if kw in ln.lower():
            return ln
    return None


# -------------------------
# Grader
# -------------------------

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "standardized_measurements_valid": 0.0,
        "exceedances_valid": 0.0,
        "unmapped_records_valid": 0.0,
        "metric_definitions_valid": 0.0,
        "raw_html_sources_present": 0.0,
        "run_log_summary_correct": 0.0,
        "run_command_documented": 0.0,
    }

    # Compute expected data from inputs
    expected_info = compute_expected_from_inputs(workspace)
    expected_ok = expected_info.get("ok", False)

    # --- Check standardized_measurements.csv ---
    std_path = workspace / "outputs" / "standardized_measurements.csv"
    std_rows, std_header = read_output_csv(std_path)
    std_base = 0.0
    std_content = 0.0
    expected_header_std = ["sensor_id", "timestamp_iso", "zone", "timeslot", "original_metric", "canonical_metric", "value_dba"]
    if std_rows is not None and std_header is not None:
        if headers_match_exact(std_header, expected_header_std):
            std_base = 0.4
            # Content check only if we could compute expected
            if expected_ok:
                expected_set = expected_set_for_standardized(expected_info["expected_standardized"])
                actual_set = rows_to_set_for_standardized(std_rows)
                # Count and exact set comparison for deterministic checks
                if len(actual_set) == len(expected_set) and actual_set == expected_set:
                    std_content = 0.6
                else:
                    std_content = 0.0
        else:
            std_base = 0.0
    scores["standardized_measurements_valid"] = std_base + std_content

    # --- Check exceedances.csv ---
    exc_path = workspace / "outputs" / "exceedances.csv"
    exc_rows, exc_header = read_output_csv(exc_path)
    exc_base = 0.0
    exc_content = 0.0
    expected_header_exc = ["sensor_id", "timestamp_iso", "zone", "timeslot", "canonical_metric", "value_dba", "limit_dba", "exceedance_dba", "ordinance_section"]
    if exc_rows is not None and exc_header is not None:
        if headers_match_exact(exc_header, expected_header_exc):
            exc_base = 0.3
            if expected_ok:
                expected = expected_info["expected_exceedances"]
                # Build index for comparisons
                actual_idx = index_exceedances(exc_rows)
                # Build expected index
                exp_idx = {}
                for r in expected:
                    key = (r["sensor_id"], r["timestamp_iso"], r["zone"], r["timeslot"], r["canonical_metric"])
                    exp_idx[key] = {
                        "value_dba": r["value_dba"],
                        "limit_dba": r["limit_dba"],
                        "exceedance_dba": r["exceedance_dba"],
                        "ordinance_section": r["ordinance_section"],
                    }
                # Check exact keys
                keys_match = set(actual_idx.keys()) == set(exp_idx.keys())
                numeric_ok = True
                ordinance_ok = True
                if keys_match:
                    for k in exp_idx:
                        a = actual_idx[k]
                        e = exp_idx[k]
                        if not (approx_equal(to_float_safe(a["value_dba"]), e["value_dba"]) and
                                approx_equal(to_float_safe(a["limit_dba"]), e["limit_dba"]) and
                                approx_equal(to_float_safe(a["exceedance_dba"]), e["exceedance_dba"])):
                            numeric_ok = False
                            break
                        if (a.get("ordinance_section") or "").strip() != (e.get("ordinance_section") or "").strip():
                            ordinance_ok = False
                            break
                else:
                    numeric_ok = False
                    ordinance_ok = False
                # award content score if both conditions met
                if keys_match and numeric_ok and ordinance_ok:
                    exc_content = 0.7
        else:
            exc_base = 0.0
    scores["exceedances_valid"] = exc_base + exc_content

    # --- Check unmapped_records.csv ---
    unm_path = workspace / "outputs" / "unmapped_records.csv"
    unm_rows, unm_header = read_output_csv(unm_path)
    unm_base = 0.0
    unm_content = 0.0
    expected_header_unm = ["sensor_id", "timestamp_iso", "metric", "value_dba", "zone", "timeslot", "canonical_metric"]
    if unm_rows is not None and unm_header is not None:
        if headers_match_exact(unm_header, expected_header_unm):
            unm_base = 0.4
            if expected_ok:
                expected_set = expected_set_for_unmapped(expected_info["expected_unmapped"])
                actual_set = rows_to_set_for_unmapped(unm_rows)
                if len(actual_set) == len(expected_set) and actual_set == expected_set:
                    unm_content = 0.6
        else:
            unm_base = 0.0
    scores["unmapped_records_valid"] = unm_base + unm_content

    # --- Check metric_definitions.csv ---
    md_path = workspace / "outputs" / "metric_definitions.csv"
    md_rows, md_header = read_output_csv(md_path)
    md_score = 0.0
    if md_rows is not None and md_header is not None:
        # Require exact columns
        expected_md_header = ["metric_code", "definition_excerpt", "source_title", "source_domain", "source_accessed_utc", "source_type"]
        header_ok = headers_match_exact(md_header, expected_md_header)
        if header_ok:
            # Validate rows
            rows_ok = True
            domains = set()
            metrics_covered = set()
            for r in md_rows:
                metric_code = (r.get("metric_code") or "").strip()
                definition_excerpt = (r.get("definition_excerpt") or "").strip()
                source_title = (r.get("source_title") or "").strip()
                source_domain = (r.get("source_domain") or "").strip()
                source_accessed_utc = (r.get("source_accessed_utc") or "").strip()
                source_type = (r.get("source_type") or "").strip().lower()
                if not metric_code or not definition_excerpt or not source_title:
                    rows_ok = False
                    break
                stype = domain_suffix_type(source_domain)
                if stype is None:
                    rows_ok = False
                    break
                if stype != source_type:
                    rows_ok = False
                    break
                if not iso8601_like(source_accessed_utc):
                    rows_ok = False
                    break
                domains.add(source_domain.lower())
                metrics_covered.add(metric_code)
            # Coverage check
            coverage_ok = True
            if expected_ok:
                # required metrics are canonical metrics that appear in the standardized inputs; we consider LAeq, LAmax, L10, SEL if present
                expected_metrics = {canonicalize_metric(m) for m in expected_info["metrics_present"] if canonicalize_metric(m) in {"LAeq", "LAmax", "L10", "SEL"}}
                if not expected_metrics.issubset(metrics_covered):
                    coverage_ok = False
            # at least two distinct sources overall
            distinct_sources_ok = len(domains) >= 2
            if rows_ok and coverage_ok and distinct_sources_ok:
                md_score = 1.0
            else:
                md_score = 0.0
        else:
            md_score = 0.0
    else:
        md_score = 0.0
    scores["metric_definitions_valid"] = md_score

    # --- Check raw HTML sources saved ---
    raw_dir = workspace / "outputs" / "sources" / "raw_pages"
    raw_score = 0.0
    if md_rows is not None:
        required_count = len(md_rows)
        if raw_dir.exists() and raw_dir.is_dir():
            html_files = list(raw_dir.rglob("*.html"))
            if len(html_files) >= required_count and required_count > 0:
                nonempty_all = True
                for p in html_files:
                    try:
                        if p.stat().st_size <= 0:
                            nonempty_all = False
                            break
                    except Exception:
                        nonempty_all = False
                        break
                if nonempty_all:
                    raw_score = 1.0
    scores["raw_html_sources_present"] = raw_score

    # --- Check run_log.txt ---
    log_path = workspace / "outputs" / "run_log.txt"
    log_score = 0.0
    if log_path.exists():
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
            if expected_ok and std_rows is not None and exc_rows is not None and unm_rows is not None:
                # Compute expected counts
                total_input_rows = len(expected_info["expected_standardized"])
                total_standardized_rows = len(expected_info["expected_standardized"])
                number_unmapped_rows = len(expected_info["expected_unmapped"])
                number_exceedances = len(expected_info["expected_exceedances"])
                metrics_line = find_line_with_keyword(lines, "canonical metrics")
                ti_line = find_line_with_keyword(lines, "total input rows")
                ts_line = find_line_with_keyword(lines, "total standardized rows")
                um_line = find_line_with_keyword(lines, "unmapped")
                ex_line = find_line_with_keyword(lines, "exceedances")
                if all([metrics_line, ti_line, ts_line, um_line, ex_line]):
                    # parse ints
                    ti_val = extract_int_from_line(ti_line)
                    ts_val = extract_int_from_line(ts_line)
                    um_val = extract_int_from_line(um_line)
                    ex_val = extract_int_from_line(ex_line)
                    ints_ok = (ti_val == total_input_rows and
                               ts_val == total_standardized_rows and
                               um_val == number_unmapped_rows and
                               ex_val == number_exceedances)
                    # metrics presence: ensure at least the canonical ones are listed
                    # Just check substrings for each metric
                    metrics_ok = True
                    required_metrics = {m for m in expected_info["metrics_present"] if canonicalize_metric(m) in {"LAeq", "LAmax", "L10", "SEL"}}
                    for m in sorted(required_metrics):
                        if m not in metrics_line:
                            metrics_ok = False
                            break
                    if ints_ok and metrics_ok:
                        log_score = 1.0
        except Exception:
            log_score = 0.0
    scores["run_log_summary_correct"] = log_score

    # --- Check run_command.txt ---
    cmd_path = workspace / "outputs" / "run_command.txt"
    cmd_score = 0.0
    if cmd_path.exists():
        try:
            cmd_text = cmd_path.read_text(encoding="utf-8", errors="ignore").strip()
            if cmd_text:
                # Require that it's a single line command or at least contains whitespace and likely executable
                # We just ensure non-empty content as per requirement
                cmd_score = 1.0
        except Exception:
            cmd_score = 0.0
    scores["run_command_documented"] = cmd_score

    return scores


# -------------------------
# CLI Entrypoint
# -------------------------

def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()