import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    rows: List[Dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return False, []
            for row in reader:
                rows.append(dict(row))
        return True, rows
    except Exception:
        return False, []


def _to_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _compute_group_aggregates(rows: List[Dict[str, str]]) -> Dict[Tuple[int, int], Dict[str, float]]:
    groups: Dict[Tuple[int, int], Dict[str, float]] = {}
    for r in rows:
        d = _to_int(r.get("pipe_diameter_mm", ""))
        p = _to_int(r.get("pressure_class_bar", ""))
        up = _to_float(r.get("unit_price_usd", ""))
        lt = _to_int(r.get("lead_time_days", ""))
        cf = str(r.get("compliance_flag", "")).strip()
        if d is None or p is None or up is None or lt is None:
            continue
        key = (d, p)
        bucket = groups.setdefault(key, {
            "offers": 0,
            "sum_unit_price": 0.0,
            "min_unit_price": None,
            "max_unit_price": None,
            "sum_lead_time": 0.0,
            "compliant_offers": 0
        })
        bucket["offers"] += 1
        bucket["sum_unit_price"] += up
        bucket["sum_lead_time"] += lt
        bucket["min_unit_price"] = up if bucket["min_unit_price"] is None else min(bucket["min_unit_price"], up)
        bucket["max_unit_price"] = up if bucket["max_unit_price"] is None else max(bucket["max_unit_price"], up)
        if cf == "Y":
            bucket["compliant_offers"] += 1
    finalized: Dict[Tuple[int, int], Dict[str, float]] = {}
    for key, b in groups.items():
        offers = b["offers"]
        if offers <= 0:
            continue
        finalized[key] = {
            "offers": offers,
            "avg_unit_price_usd": b["sum_unit_price"] / offers,
            "min_unit_price_usd": b["min_unit_price"] if b["min_unit_price"] is not None else 0.0,
            "max_unit_price_usd": b["max_unit_price"] if b["max_unit_price"] is not None else 0.0,
            "avg_lead_time_days": b["sum_lead_time"] / offers,
            "compliant_offers": b["compliant_offers"],
        }
    return finalized


def _compute_claim_truths(rows: List[Dict[str, str]]) -> List[str]:
    avg_600_16 = None
    vals_600_16 = []
    for r in rows:
        d = _to_int(r.get("pipe_diameter_mm", ""))
        p = _to_int(r.get("pressure_class_bar", ""))
        up = _to_float(r.get("unit_price_usd", ""))
        if d == 600 and p == 16 and up is not None:
            vals_600_16.append(up)
    if vals_600_16:
        avg_600_16 = sum(vals_600_16) / len(vals_600_16)
    c1 = "Confirmed" if (avg_600_16 is not None and avg_600_16 <= 245.0) else "Refuted"

    vals_1000_16 = []
    for r in rows:
        d = _to_int(r.get("pipe_diameter_mm", ""))
        p = _to_int(r.get("pressure_class_bar", ""))
        up = _to_float(r.get("unit_price_usd", ""))
        if d == 1000 and p == 16 and up is not None:
            vals_1000_16.append(up)
    min_1000_16 = min(vals_1000_16) if vals_1000_16 else None
    c2 = "Confirmed" if (min_1000_16 is not None and min_1000_16 < 400.0) else "Refuted"

    max_lead = None
    for r in rows:
        lt = _to_int(r.get("lead_time_days", ""))
        if lt is None:
            continue
        max_lead = lt if max_lead is None else max(max_lead, lt)
    c3 = "Confirmed" if (max_lead is not None and max_lead <= 100) else "Refuted"

    pn10_rows = [r for r in rows if _to_int(r.get("pressure_class_bar", "")) == 10]
    all_pn10_compliant = all(str(r.get("compliance_flag", "")).strip() == "Y" for r in pn10_rows) if pn10_rows else False
    c4 = "Confirmed" if all_pn10_compliant else "Refuted"

    all_prices = [_to_float(r.get("unit_price_usd", "")) for r in rows if _to_float(r.get("unit_price_usd", "")) is not None]
    overall_avg = (sum(all_prices) / len(all_prices)) if all_prices else None
    c5 = "Confirmed" if (overall_avg is not None and overall_avg < 300.0) else "Refuted"

    return [c1, c2, c3, c4, c5]


def _parse_verification_report(path: Path) -> Tuple[List[str], List[bool], List[bool]]:
    text = _read_text_safe(path)
    if text is None:
        return [], [], []
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    chunks: List[List[str]] = []
    current: List[str] = []
    for ln in lines:
        if ln.strip() == "":
            if current:
                chunks.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        chunks.append(current)
    statuses: List[str] = []
    has_filter: List[bool] = []
    has_computed: List[bool] = []
    for chunk in chunks:
        joined = "\n".join(chunk)
        m = re.search(r'[Ss]tatus\s*:\s*(Confirmed|Refuted)', joined)
        if m:
            status = m.group(1)
            statuses.append(status)
            has_filter.append(bool(re.search(r'\b[Ff]ilter\b\s*:', joined)))
            has_computed.append(bool(re.search(r'\b[Cc]omputed\b\s*:', joined)))
        if len(statuses) >= 5:
            break
    return statuses, has_filter, has_computed


def _parse_metrics_csv(path: Path) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    ok, rows = _read_csv_dicts_safe(path)
    if not ok:
        return False, [], []
    headers = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            headers = next(reader, [])
    except Exception:
        headers = list(rows[0].keys()) if rows else []
    return True, rows, headers


def _build_group_key_from_metrics_row(row: Dict[str, str]) -> Optional[Tuple[int, int]]:
    d = _to_int(row.get("pipe_diameter_mm", ""))
    p = _to_int(row.get("pressure_class_bar", ""))
    if d is None or p is None:
        return None
    return (d, p)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metrics_file_exists": 0.0,
        "metrics_required_columns_present": 0.0,
        "metrics_groups_complete": 0.0,
        "metrics_values_correct": 0.0,
        "verification_report_exists": 0.0,
        "verification_report_has_5_claims": 0.0,
        "verification_report_statuses_correct": 0.0,
        "verification_report_contains_filters_and_computed": 0.0,
        "validation_script_exists": 0.0,
        "validation_log_exists": 0.0,
        "validation_log_pass_coverage": 0.0,
        "email_exists": 0.0,
        "email_has_subject_and_artifact_paths": 0.0,
        "email_claims_status_summary": 0.0,
    }

    offers_csv = workspace / "input" / "offers.csv"
    claims_md = workspace / "input" / "claims.md"
    schema_json = workspace / "input" / "schema.json"
    metrics_csv = workspace / "artifacts" / "metrics.csv"
    verification_report = workspace / "artifacts" / "verification_report.md"
    validation_script = workspace / "tests" / "validate_offers.py"
    validation_log = workspace / "artifacts" / "validation.log"
    email_file = workspace / "deliverables" / "email_to_procurement.txt"

    input_ok, input_rows = _read_csv_dicts_safe(offers_csv)

    if metrics_csv.exists():
        scores["metrics_file_exists"] = 1.0
        required_cols = {
            "pipe_diameter_mm",
            "pressure_class_bar",
            "offers",
            "avg_unit_price_usd",
            "min_unit_price_usd",
            "max_unit_price_usd",
            "avg_lead_time_days",
            "compliant_offers",
        }
        m_ok, m_rows, m_headers = _parse_metrics_csv(metrics_csv)
        if m_ok and m_headers:
            if required_cols.issubset(set(m_headers)):
                scores["metrics_required_columns_present"] = 1.0
            if input_ok:
                expected_groups = _compute_group_aggregates(input_rows)
                found_groups: Dict[Tuple[int, int], Dict[str, str]] = {}
                for r in m_rows:
                    key = _build_group_key_from_metrics_row(r)
                    if key is None:
                        continue
                    found_groups[key] = r
                if set(found_groups.keys()) == set(expected_groups.keys()):
                    scores["metrics_groups_complete"] = 1.0
                all_ok = True
                for key, exp in expected_groups.items():
                    row = found_groups.get(key)
                    if not row:
                        all_ok = False
                        break
                    offers_val = _to_int(row.get("offers", ""))
                    comp_val = _to_int(row.get("compliant_offers", ""))
                    if offers_val is None or comp_val is None:
                        all_ok = False
                        break
                    if offers_val != int(exp["offers"]) or comp_val != int(exp["compliant_offers"]):
                        all_ok = False
                        break
                    avg_up = _to_float(row.get("avg_unit_price_usd", ""))
                    min_up = _to_float(row.get("min_unit_price_usd", ""))
                    max_up = _to_float(row.get("max_unit_price_usd", ""))
                    avg_lt = _to_float(row.get("avg_lead_time_days", ""))
                    if None in (avg_up, min_up, max_up, avg_lt):
                        all_ok = False
                        break
                    if not (_float_equal(avg_up, float(exp["avg_unit_price_usd"])) and
                            _float_equal(min_up, float(exp["min_unit_price_usd"])) and
                            _float_equal(max_up, float(exp["max_unit_price_usd"])) and
                            _float_equal(avg_lt, float(exp["avg_lead_time_days"]))):
                        all_ok = False
                        break
                if all_ok and scores["metrics_groups_complete"] == 1.0:
                    scores["metrics_values_correct"] = 1.0

    if verification_report.exists():
        scores["verification_report_exists"] = 1.0
        statuses, has_filter_list, has_computed_list = _parse_verification_report(verification_report)
        if len(statuses) >= 5:
            scores["verification_report_has_5_claims"] = 1.0
            if input_ok:
                expected_statuses = _compute_claim_truths(input_rows)
                if statuses[:5] == expected_statuses:
                    scores["verification_report_statuses_correct"] = 1.0
            if len(has_filter_list) >= 5 and len(has_computed_list) >= 5:
                if all(has_filter_list[:5]) and all(has_computed_list[:5]):
                    scores["verification_report_contains_filters_and_computed"] = 1.0

    if validation_script.exists():
        scores["validation_script_exists"] = 1.0
    if validation_log.exists():
        scores["validation_log_exists"] = 1.0
        log_text = _read_text_safe(validation_log) or ""
        lines = [ln for ln in log_text.splitlines() if ln.strip()]
        cat_pass = {
            "schema": False,
            "ranges": False,
            "unique": False,
            "invariants": False,
        }
        for ln in lines:
            ln_lower = ln.lower()
            if "pass" in ln_lower:
                if any(k in ln_lower for k in ["required", "column", "type", "schema"]):
                    cat_pass["schema"] = True
                if any(k in ln_lower for k in ["allowed", "range", "min", "max"]):
                    cat_pass["ranges"] = True
                if any(k in ln_lower for k in ["unique", "duplicate"]):
                    cat_pass["unique"] = True
                if any(k in ln_lower for k in ["invariant", "unit_price", "lead_time", "compliance_flag"]):
                    cat_pass["invariants"] = True
        if all(cat_pass.values()):
            scores["validation_log_pass_coverage"] = 1.0

    if email_file.exists():
        scores["email_exists"] = 1.0
        email_text = _read_text_safe(email_file) or ""
        has_subject = bool(re.search(r'^\s*Subject\s*:', email_text, flags=re.IGNORECASE | re.MULTILINE))
        has_paths = all(p in email_text for p in ["artifacts/metrics.csv", "artifacts/verification_report.md", "artifacts/validation.log"])
        if has_subject and has_paths:
            scores["email_has_subject_and_artifact_paths"] = 1.0
        found_claims = set()
        for ln in email_text.splitlines():
            m = re.search(r'Claim\s*([1-5])\b.*?(Confirmed|Refuted)', ln, flags=re.IGNORECASE)
            if m:
                found_claims.add(int(m.group(1)))
        if len(found_claims) == 5:
            scores["email_claims_status_summary"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()