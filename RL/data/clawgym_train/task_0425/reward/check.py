import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        results = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                results.append(json.loads(line))
        return results
    except Exception:
        return None


def _parse_yaml_minimal(path: Path) -> Optional[Dict[str, Any]]:
    # Minimal YAML parser for simple key: value and nested dicts with 2-space indent
    # Supports:
    #   key:
    #     subkey: value
    #   key: value
    # Values: int, float, bool (true/false), string
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = text.splitlines()
    result: Dict[str, Any] = {}
    current_map_key: Optional[str] = None
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            # top-level
            if ":" not in line:
                return None
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # start of nested map
                result[key] = {}
                current_map_key = key
            else:
                result[key] = _coerce_yaml_value(val)
                current_map_key = None
        elif indent == 2:
            # nested under current_map_key
            if current_map_key is None:
                return None
            if ":" not in line.strip():
                return None
            key, val = line.strip().split(":", 1)
            key = key.strip()
            val = val.strip()
            if not isinstance(result.get(current_map_key), dict):
                return None
            result[current_map_key][key] = _coerce_yaml_value(val)
        else:
            # Unsupported deeper nesting
            return None
    return result


def _coerce_yaml_value(val: str) -> Any:
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    # try int
    try:
        if re.fullmatch(r"[-+]?\d+", val):
            return int(val)
    except Exception:
        pass
    # try float
    try:
        if re.fullmatch(r"[-+]?\d*\.\d+([eE][-+]?\d+)?", val) or re.fullmatch(r"[-+]?\d+([eE][-+]?\d+)", val):
            return float(val)
    except Exception:
        pass
    # strip quotes if present
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val


def _approx_equal(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def _parse_float_safe(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_int_safe(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _parse_bool_strict(s: str) -> Optional[bool]:
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        return None
    ls = s.strip().lower()
    if ls == "true":
        return True
    if ls == "false":
        return False
    return None


def _min_max_normalize(values_by_key: Dict[str, float]) -> Dict[str, float]:
    if not values_by_key:
        return {}
    vals = list(values_by_key.values())
    vmin = min(vals)
    vmax = max(vals)
    rng = vmax - vmin
    if rng == 0:
        return {k: 0.0 for k in values_by_key}
    return {k: (v - vmin) / rng for k, v in values_by_key.items()}


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load inputs
    suppliers_path = workspace / "input" / "suppliers.csv"
    purchases_path = workspace / "input" / "purchases.csv"
    audit_path = workspace / "input" / "audit_findings.jsonl"
    policy_path = workspace / "input" / "policy.yaml"

    suppliers_rows = _read_csv_dicts(suppliers_path)
    purchases_rows = _read_csv_dicts(purchases_path)
    audit_rows = _read_jsonl(audit_path)
    policy = _parse_yaml_minimal(policy_path)

    if suppliers_rows is None or purchases_rows is None or audit_rows is None or policy is None:
        return None

    # Extract policy components
    try:
        weights = policy["weights"]
        w_audit = float(weights["audit"])
        w_carbon = float(weights["carbon"])
        w_volume = float(weights["volume"])
        region_multipliers = policy["region_multipliers"]
        severity_map = policy["severity_map"]
        shortlist_threshold = float(policy["shortlist_threshold"])
        exclude_if_critical = bool(policy["exclude_if_critical"])
        exclude_if_open_findings_gt = int(policy["exclude_if_open_findings_gt"])
        emission_factors = policy["emission_factors"]
    except Exception:
        return None

    # Map suppliers
    supplier_info: Dict[str, Dict[str, str]] = {}
    for r in suppliers_rows:
        sid = r.get("supplier_id")
        name = r.get("supplier_name")
        region = r.get("region")
        if not sid or name is None or region is None:
            return None
        supplier_info[sid] = {"supplier_name": name, "region": region}

    # Build audit mapping
    audit_map: Dict[str, Dict[str, Any]] = {}
    for a in audit_rows:
        sid = a.get("supplier_id")
        sev = a.get("severity")
        of = a.get("open_findings")
        if not isinstance(sid, str) or not isinstance(sev, str) or not isinstance(of, (int, float)):
            return None
        audit_map[sid] = {"severity": sev, "open_findings": int(of)}

    # Compute totals for Q1 2024
    valid_months = {"2024-01", "2024-02", "2024-03"}
    totals_kg: Dict[str, float] = {sid: 0.0 for sid in supplier_info}
    totals_emissions: Dict[str, float] = {sid: 0.0 for sid in supplier_info}

    # Validate emission factors cover used categories
    for r in purchases_rows:
        date = (r.get("date") or "").strip()
        if date not in valid_months:
            continue
        cat = r.get("category")
        if cat not in emission_factors:
            # Unknown category referenced
            return None

    for r in purchases_rows:
        date = (r.get("date") or "").strip()
        if date not in valid_months:
            continue
        sid = r.get("supplier_id")
        cat = r.get("category")
        kg_s = r.get("kg")
        if sid not in supplier_info:
            # Unknown supplier, still process but ignore (task focuses on known suppliers)
            continue
        kg = _parse_float_safe(kg_s) if kg_s is not None else None
        if kg is None:
            return None
        ef = float(emission_factors[cat])  # already validated cat
        totals_kg[sid] += kg
        totals_emissions[sid] += kg * ef

    # Audit subscores raw
    audit_raw: Dict[str, float] = {}
    audit_severity: Dict[str, str] = {}
    audit_open: Dict[str, int] = {}
    for sid in supplier_info:
        a = audit_map.get(sid)
        if a is None:
            return None
        sev = a["severity"]
        if sev not in severity_map:
            return None
        sev_weight = float(severity_map[sev])
        of = int(a["open_findings"])
        raw = sev_weight * (1.0 + of / 10.0)
        audit_raw[sid] = raw
        audit_severity[sid] = sev
        audit_open[sid] = of

    # Normalizations
    audit_norm = _min_max_normalize(audit_raw)
    carbon_norm = _min_max_normalize(totals_emissions)
    volume_norm = _min_max_normalize(totals_kg)

    # Region multipliers per supplier
    region_multiplier: Dict[str, float] = {}
    for sid, info in supplier_info.items():
        region = info["region"]
        if region not in region_multipliers:
            return None
        try:
            region_multiplier[sid] = float(region_multipliers[region])
        except Exception:
            return None

    # Final score and flags
    final_score: Dict[str, float] = {}
    shortlisted: Dict[str, bool] = {}
    flag_reasons: Dict[str, List[str]] = {}
    for sid in supplier_info:
        fs = (w_audit * audit_norm[sid] + w_carbon * carbon_norm[sid] + w_volume * volume_norm[sid]) * region_multiplier[sid]
        final_score[sid] = fs
        reasons = []
        # Apply shortlist rules
        above = fs > shortlist_threshold
        crit_cond = exclude_if_critical and audit_severity[sid] == "critical"
        open_too_many = audit_open[sid] > exclude_if_open_findings_gt
        if crit_cond:
            reasons.append("critical_audit")
        if open_too_many:
            reasons.append("too_many_open_findings")
        if above:
            reasons.append("final_score_above_threshold")
        is_shortlisted = (fs <= shortlist_threshold) and (not crit_cond) and (not open_too_many)
        shortlisted[sid] = is_shortlisted
        flag_reasons[sid] = reasons

    # Build expected record per supplier
    expected: Dict[str, Any] = {
        "suppliers": supplier_info,
        "totals_kg": totals_kg,
        "totals_emissions": totals_emissions,
        "audit_severity": audit_severity,
        "audit_open": audit_open,
        "audit_raw": audit_raw,
        "audit_norm": audit_norm,
        "carbon_norm": carbon_norm,
        "volume_norm": volume_norm,
        "region_multiplier": region_multiplier,
        "final_score": final_score,
        "shortlisted": shortlisted,
        "flag_reasons": flag_reasons,
        "policy": {
            "weights": {"audit": w_audit, "carbon": w_carbon, "volume": w_volume},
            "region_multipliers": region_multipliers,
            "severity_map": severity_map,
            "shortlist_threshold": shortlist_threshold,
            "exclude_if_critical": exclude_if_critical,
            "exclude_if_open_findings_gt": exclude_if_open_findings_gt,
            "emission_factors": emission_factors,
        },
    }
    return expected


def _get_expected_ordered_suppliers(expected: Dict[str, Any]) -> List[Tuple[str, float]]:
    # Returns list of (supplier_id, final_score) sorted ascending by final_score
    fs = expected["final_score"]
    ordered = sorted(fs.items(), key=lambda kv: (kv[1], kv[0]))
    return ordered


def _safe_split_flags(s: str) -> List[str]:
    if s is None:
        return []
    parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    return parts


def _extract_subject_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().lower().startswith("subject:"):
            return line.strip()
    return None


def _line_contains_score_within(line: str, target: float, tol: float = 0.02) -> bool:
    # Find any float-like number in line and compare to target within tolerance
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", line)
    for n in nums:
        try:
            v = float(n)
            if abs(v - target) <= tol:
                return True
        except Exception:
            continue
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "supplier_scores_exists_and_schema": 0.0,
        "supplier_scores_row_coverage": 0.0,
        "supplier_scores_sorted_by_final_score": 0.0,
        "supplier_scores_audit_fields_correct": 0.0,
        "supplier_scores_totals_correct": 0.0,
        "supplier_scores_norms_correct": 0.0,
        "supplier_scores_region_multiplier_correct": 0.0,
        "supplier_scores_final_score_correct": 0.0,
        "shortlisted_and_flags_correct": 0.0,
        "shortlist_json_correct": 0.0,
        "summary_email_subject": 0.0,
        "summary_email_method_overview": 0.0,
        "summary_email_top3_listed": 0.0,
        "summary_email_exclusions_noted": 0.0,
        "summary_email_attachments_note": 0.0,
    }

    expected = _compute_expected(workspace)

    # Check supplier_scores.csv
    supplier_scores_path = workspace / "output" / "supplier_scores.csv"
    rows_scores = _read_csv_dicts(supplier_scores_path)
    required_columns = [
        "supplier_id",
        "supplier_name",
        "region",
        "total_purchase_kg_q1",
        "total_emissions_kgco2e_q1",
        "audit_severity",
        "open_findings",
        "audit_subscore_raw",
        "audit_subscore_norm",
        "carbon_subscore_norm",
        "volume_subscore_norm",
        "region_multiplier",
        "final_score",
        "shortlisted",
        "flag_reasons",
    ]
    if rows_scores is not None:
        # Schema check
        try:
            with supplier_scores_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
            if header == required_columns:
                scores["supplier_scores_exists_and_schema"] = 1.0
        except Exception:
            pass

    if expected is not None and rows_scores is not None:
        # Row coverage
        expected_ids = set(expected["suppliers"].keys())
        output_ids = [r.get("supplier_id") for r in rows_scores if r.get("supplier_id") is not None]
        if len(rows_scores) == len(expected_ids) and set(output_ids) == expected_ids:
            scores["supplier_scores_row_coverage"] = 1.0

        # Sorting by final_score ascending
        sort_ok = True
        prev = -float("inf")
        for r in rows_scores:
            fs = _parse_float_safe(r.get("final_score", ""))
            if fs is None:
                sort_ok = False
                break
            if fs < prev - 1e-12:
                sort_ok = False
                break
            prev = fs
        if sort_ok:
            scores["supplier_scores_sorted_by_final_score"] = 1.0

        # Audit fields correctness
        correct_count = 0
        for r in rows_scores:
            sid = r.get("supplier_id")
            if sid not in expected["suppliers"]:
                continue
            sev_ok = (r.get("audit_severity") == expected["audit_severity"][sid])
            of = _parse_int_safe(r.get("open_findings", ""))
            of_ok = (of is not None and of == expected["audit_open"][sid])
            raw = _parse_float_safe(r.get("audit_subscore_raw", ""))
            raw_ok = (raw is not None and _approx_equal(raw, expected["audit_raw"][sid]))
            if sev_ok and of_ok and raw_ok:
                correct_count += 1
        if len(rows_scores) > 0:
            scores["supplier_scores_audit_fields_correct"] = correct_count / len(rows_scores)

        # Totals correctness
        correct_count = 0
        for r in rows_scores:
            sid = r.get("supplier_id")
            tkg = _parse_float_safe(r.get("total_purchase_kg_q1", ""))
            te = _parse_float_safe(r.get("total_emissions_kgco2e_q1", ""))
            if sid in expected["suppliers"] and tkg is not None and te is not None:
                if _approx_equal(tkg, expected["totals_kg"][sid]) and _approx_equal(te, expected["totals_emissions"][sid]):
                    correct_count += 1
        if len(rows_scores) > 0:
            scores["supplier_scores_totals_correct"] = correct_count / len(rows_scores)

        # Norms correctness
        correct_count = 0
        for r in rows_scores:
            sid = r.get("supplier_id")
            an = _parse_float_safe(r.get("audit_subscore_norm", ""))
            cn = _parse_float_safe(r.get("carbon_subscore_norm", ""))
            vn = _parse_float_safe(r.get("volume_subscore_norm", ""))
            if sid in expected["suppliers"] and an is not None and cn is not None and vn is not None:
                if _approx_equal(an, expected["audit_norm"][sid]) and _approx_equal(cn, expected["carbon_norm"][sid]) and _approx_equal(vn, expected["volume_norm"][sid]):
                    correct_count += 1
        if len(rows_scores) > 0:
            scores["supplier_scores_norms_correct"] = correct_count / len(rows_scores)

        # Region multiplier correctness
        correct_count = 0
        for r in rows_scores:
            sid = r.get("supplier_id")
            rm = _parse_float_safe(r.get("region_multiplier", ""))
            if sid in expected["suppliers"] and rm is not None:
                if _approx_equal(rm, expected["region_multiplier"][sid]):
                    correct_count += 1
        if len(rows_scores) > 0:
            scores["supplier_scores_region_multiplier_correct"] = correct_count / len(rows_scores)

        # Final score correctness
        correct_count = 0
        for r in rows_scores:
            sid = r.get("supplier_id")
            fs = _parse_float_safe(r.get("final_score", ""))
            if sid in expected["suppliers"] and fs is not None:
                if _approx_equal(fs, expected["final_score"][sid]):
                    correct_count += 1
        if len(rows_scores) > 0:
            scores["supplier_scores_final_score_correct"] = correct_count / len(rows_scores)

        # Shortlisted and flags correctness
        correct_count = 0
        for r in rows_scores:
            sid = r.get("supplier_id")
            sh = r.get("shortlisted")
            sh_bool = _parse_bool_strict(sh) if sh is not None else None
            flags_out = set(_safe_split_flags(r.get("flag_reasons", "")))
            flags_exp = set(expected["flag_reasons"][sid])
            if sid in expected["suppliers"] and sh_bool is not None:
                if (sh_bool == expected["shortlisted"][sid]) and (flags_out == flags_exp):
                    correct_count += 1
        if len(rows_scores) > 0:
            scores["shortlisted_and_flags_correct"] = correct_count / len(rows_scores)

    # Check shortlist.json
    shortlist_path = workspace / "output" / "shortlist.json"
    shortlist = _read_json(shortlist_path)
    if expected is not None and isinstance(shortlist, list):
        # Expected shortlisted suppliers sorted by final_score ascending
        exp_pairs = _get_expected_ordered_suppliers(expected)
        exp_shortlisted = [(sid, fs) for sid, fs in exp_pairs if expected["shortlisted"][sid]]
        exp_ids_order = [sid for sid, _ in exp_shortlisted]
        # Validate structure and content
        ok = True
        # Check objects have required fields and are sorted ascending
        prev_fs = -float("inf")
        out_ids_order = []
        for obj in shortlist:
            if not isinstance(obj, dict):
                ok = False
                break
            for k in ("supplier_id", "supplier_name", "region", "final_score"):
                if k not in obj:
                    ok = False
                    break
            if not ok:
                break
            fs = obj["final_score"]
            try:
                fs_val = float(fs)
            except Exception:
                ok = False
                break
            if fs_val < prev_fs - 1e-12:
                ok = False
                break
            prev_fs = fs_val
            out_ids_order.append(obj["supplier_id"])
            sid = obj["supplier_id"]
            if sid not in expected["suppliers"]:
                ok = False
                break
            # Check name and region
            if obj["supplier_name"] != expected["suppliers"][sid]["supplier_name"]:
                ok = False
                break
            if obj["region"] != expected["suppliers"][sid]["region"]:
                ok = False
                break
            # Check final_score close
            if not _approx_equal(fs_val, expected["final_score"][sid]):
                ok = False
                break
        if ok and out_ids_order == exp_ids_order:
            scores["shortlist_json_correct"] = 1.0

    # Check summary_email.txt
    email_path = workspace / "output" / "summary_email.txt"
    email_text = _read_text(email_path)
    if expected is not None and email_text is not None:
        # Subject
        subj = _extract_subject_line(email_text)
        if subj is not None and "q1 2024 supplier sri shortlist".lower() in subj.lower():
            scores["summary_email_subject"] = 1.0

        # Method overview referencing policy assumptions used
        # Check for mention of 'policy' and at least one keyword among: 'weights', 'region', 'emission', 'severity', 'threshold'
        lt = email_text.lower()
        has_policy = ("policy" in lt) or ("policy.yaml" in lt)
        has_keyword = any(k in lt for k in ["weights", "region", "emission", "severity", "threshold", "multiplier", "emission factors"])
        if has_policy and has_keyword:
            scores["summary_email_method_overview"] = 1.0

        # Top 3 lowest-risk suppliers with final_score and region
        # Determine top 3 by expected final score ascending
        top3 = _get_expected_ordered_suppliers(expected)[:3]
        match_count = 0
        lines = email_text.splitlines()
        for sid, fs in top3:
            name = expected["suppliers"][sid]["supplier_name"]
            region = expected["suppliers"][sid]["region"]
            found = False
            for line in lines:
                if (name in line) and (region in line) and _line_contains_score_within(line, fs, tol=0.02):
                    found = True
                    break
            if found:
                match_count += 1
        if len(top3) == 3:
            scores["summary_email_top3_listed"] = match_count / 3.0

        # Exclusions noted
        # Require mention of "critical" and mention of "open finding"
        has_critical = ("critical" in lt)
        has_open_findings_phrase = ("open finding" in lt)
        if has_critical and has_open_findings_phrase:
            scores["summary_email_exclusions_noted"] = 1.0

        # Attachments note with both output paths
        if ("output/supplier_scores.csv" in email_text) and ("output/shortlist.json" in email_text):
            scores["summary_email_attachments_note"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()