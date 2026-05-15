import json
import sys
import re
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json_array(path: Path) -> Optional[List[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize header keys by stripping spaces
                rows.append({k.strip(): v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_rules_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser tailored to the given accuracy_rules.yaml structure.
    Expects sections: tolerances.percent_points, tolerances.absolute, year_reference.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    mode = None  # 'tp', 'ta', 'yr'
    rules: Dict[str, Any] = {
        "tolerances": {"percent_points": {}, "absolute": {}},
        "year_reference": {},
    }
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("tolerances:"):
            mode = "tol"
            continue
        if mode == "tol" and line.startswith("percent_points:"):
            mode = "tp"
            continue
        if mode == "tol" and line.startswith("absolute:"):
            mode = "ta"
            continue
        if line.startswith("year_reference:"):
            mode = "yr"
            continue

        # Mapping entries under current mode
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip().strip('"').strip("'")
            val_raw = parts[1].strip()
            # Handle block starters like 'percent_units: "..."' but we don't need those sections
            if mode not in ("tp", "ta", "yr"):
                continue
            # Clean value: strip quotes
            val_clean: Any
            if val_raw == "" or val_raw == "{}":
                continue
            if val_raw.startswith('"') and val_raw.endswith('"'):
                val_clean = val_raw[1:-1]
            elif val_raw.startswith("'") and val_raw.endswith("'"):
                val_clean = val_raw[1:-1]
            else:
                # Try numeric
                try:
                    if "." in val_raw:
                        val_clean = float(val_raw)
                    else:
                        val_clean = int(val_raw)
                except Exception:
                    val_clean = val_raw
            if mode == "tp":
                try:
                    rules["tolerances"]["percent_points"][key] = float(val_clean)
                except Exception:
                    return None
            elif mode == "ta":
                try:
                    rules["tolerances"]["absolute"][key] = float(val_clean)
                except Exception:
                    return None
            elif mode == "yr":
                try:
                    rules["year_reference"][key] = int(val_clean)
                except Exception:
                    return None
    # Basic sanity
    if not isinstance(rules.get("tolerances"), dict):
        return None
    if not isinstance(rules["tolerances"].get("percent_points"), dict):
        return None
    if not isinstance(rules["tolerances"].get("absolute"), dict):
        return None
    if not isinstance(rules.get("year_reference"), dict):
        return None
    return rules


def _parse_context_md(path: Path) -> Optional[Dict[str, str]]:
    """
    Parses simple Key: Value lines from context.md
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    ctx: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                ctx[key.lower()] = val
    return ctx


def _normalize_unit(u: Any) -> Optional[str]:
    if u is None:
        return None
    if isinstance(u, str):
        return u.strip().lower()
    return str(u).strip().lower()


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if s == "":
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _to_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, str):
        s = x.strip()
        try:
            return int(s)
        except Exception:
            try:
                f = float(s)
                if f.is_integer():
                    return int(f)
            except Exception:
                return None
    return None


def _float_equal(a: Optional[float], b: Optional[float], eps: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= eps


def _build_official_lookup(official_rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str, int], Tuple[float, str]]:
    lookup: Dict[Tuple[str, str, int], Tuple[float, str]] = {}
    for row in official_rows:
        metric = (row.get("metric") or "").strip().strip('"')
        area = (row.get("area") or "").strip().strip('"')
        year = _to_int(row.get("year"))
        value = _to_float(row.get("value"))
        unit = _normalize_unit(row.get("unit"))
        if metric and area and year is not None and value is not None and unit:
            lookup[(metric, area, year)] = (value, unit)
    return lookup


def _compute_expected_for_claims(
    claims_rows: List[Dict[str, Any]],
    official_lookup: Dict[Tuple[str, str, int], Tuple[float, str]],
    rules: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """
    Returns mapping claim_id -> expected details:
    keys: metric, area, claim_value, claim_unit, official_year, official_value, official_unit,
          difference, tolerance, status
    """
    expected: Dict[str, Dict[str, Any]] = {}
    year_ref = rules.get("year_reference", {})
    tol_pp = rules.get("tolerances", {}).get("percent_points", {})
    tol_abs = rules.get("tolerances", {}).get("absolute", {})

    for row in claims_rows:
        claim_id = (row.get("claim_id") or "").strip()
        metric = (row.get("metric") or "").strip()
        area = (row.get("area") or "").strip()
        cval = _to_float(row.get("value"))
        cunit = _normalize_unit(row.get("unit"))
        oyear = year_ref.get(metric)
        ovalue = None
        ounit = None
        if isinstance(oyear, int):
            if (metric, area, oyear) in official_lookup:
                ovalue, ounit = official_lookup[(metric, area, oyear)]
        # Determine tolerance based on metric/unit type
        tolerance = None
        if cunit == "percent":
            if metric in tol_pp:
                tolerance = float(tol_pp.get(metric))
        else:
            # counts (e.g., 'count'); for mismatch we'll still carry metric-specific absolute tolerance if available
            if metric in tol_abs:
                tolerance = float(tol_abs.get(metric))
        # Compute difference and status
        difference = None
        status = "unclear"
        if oyear is None:
            # No year reference
            status = "unclear"
        else:
            # If units mismatch or no official value found, unclear
            if ovalue is None or cunit is None or ounit is None:
                status = "unclear"
            else:
                if cunit != ounit:
                    status = "unclear"
                else:
                    # Units match -> compute difference
                    if cval is None:
                        status = "unclear"
                    else:
                        difference = abs(cval - ovalue)
                        if tolerance is None:
                            # If tolerance missing from rules, cannot judge accurately; mark as unclear
                            status = "unclear"
                        else:
                            if difference <= tolerance:
                                status = "accurate"
                            else:
                                status = "inaccurate"
        expected[claim_id] = {
            "metric": metric,
            "area": area,
            "claim_value": cval,
            "claim_unit": cunit,
            "official_year": oyear,
            "official_value": ovalue,
            "official_unit": ounit,
            "difference": difference,
            "tolerance": tolerance,
            "status": status,
        }
    return expected


def _find_note_like_field(rec: Dict[str, Any]) -> bool:
    for k, v in rec.items():
        kl = str(k).lower()
        if any(tok in kl for tok in ["note", "explan", "reason"]):
            if isinstance(v, str) and v.strip():
                return True
    return False


def _parse_counts_from_summary(text: str) -> Optional[Dict[str, int]]:
    def find_count(label: str) -> Optional[int]:
        patterns = [
            rf"(?i)\b{label}\b\s*[:\-–—]\s*(\d+)",
            rf"(?i)\b{label}\b\s*\(\s*(\d+)\s*\)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
        return None

    acc = find_count("Accurate")
    inac = find_count("Inaccurate")
    uncl = find_count("Unclear")
    if acc is None or inac is None or uncl is None:
        return None
    return {"accurate": acc, "inaccurate": inac, "unclear": uncl}


def _extract_action_items_section(text: str) -> str:
    low = text.lower()
    idx = low.find("action items")
    if idx == -1:
        return ""
    return text[idx:]


def _claims_from_json_by_id(arr: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    m: Dict[str, Dict[str, Any]] = {}
    for rec in arr:
        cid = rec.get("claim_id")
        if isinstance(cid, str) and cid.strip():
            m[cid.strip()] = rec
    return m


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "verification_json_parses": 0.0,
        "verification_json_has_all_required_fields": 0.0,
        "verification_json_statuses_correct": 0.0,
        "verification_json_numbers_correct": 0.0,
        "verification_json_rule_applied_present": 0.0,
        "verification_json_unclear_notes_present": 0.0,
        "summary_report_counts_consistent_with_json": 0.0,
        "summary_report_mentions_metrics_and_areas": 0.0,
        "meeting_notes_sections_and_meeting_date_present": 0.0,
        "meeting_notes_action_items_cover_all_inaccurate_or_unclear": 0.0,
        "command_txt_present_and_nonempty": 0.0,
        "command_txt_seems_reproducible_command": 0.0,
    }

    # Load inputs
    claims_path = workspace / "input" / "claims.csv"
    official_path = workspace / "input" / "official_stats.csv"
    rules_path = workspace / "input" / "accuracy_rules.yaml"
    context_path = workspace / "input" / "context.md"

    claims_rows = _safe_load_csv_dicts(claims_path)
    official_rows = _safe_load_csv_dicts(official_path)
    rules = _parse_rules_yaml(rules_path)
    context = _parse_context_md(context_path)

    # Prepare expected if possible
    expected_map: Dict[str, Dict[str, Any]] = {}
    if claims_rows is not None and official_rows is not None and rules is not None:
        official_lookup = _build_official_lookup(official_rows)
        expected_map = _compute_expected_for_claims(claims_rows, official_lookup, rules)

    # Load outputs
    out_dir = workspace / "outputs"
    ver_json_path = out_dir / "verification_results.json"
    summary_md_path = out_dir / "summary_report.md"
    notes_md_path = out_dir / "meeting_notes.md"
    cmd_txt_path = out_dir / "command.txt"

    ver_arr = _safe_load_json_array(ver_json_path)
    if ver_arr is not None:
        scores["verification_json_parses"] = 1.0

    # Required fields check
    if ver_arr is not None:
        required_fields = [
            "claim_id",
            "metric",
            "area",
            "claim_value",
            "claim_unit",
            "official_year",
            "official_value",
            "official_unit",
            "difference",
            "tolerance",
            "status",
            "rule_applied",
        ]
        total = len(ver_arr)
        ok = 0
        rule_applied_ok = 0
        unclear_has_notes = 0
        unclear_count = 0
        for rec in ver_arr:
            if all(k in rec for k in required_fields):
                ok += 1
            # rule_applied non-empty short text
            ra = rec.get("rule_applied")
            if isinstance(ra, str) and ra.strip():
                rule_applied_ok += 1
            # unclear notes presence
            status = str(rec.get("status", "")).strip().lower()
            if status == "unclear":
                unclear_count += 1
                if _find_note_like_field(rec):
                    unclear_has_notes += 1
        scores["verification_json_has_all_required_fields"] = (ok / total) if total > 0 else 0.0
        scores["verification_json_rule_applied_present"] = (rule_applied_ok / total) if total > 0 else 0.0
        # If there are no unclear in the file, consider this requirement satisfied (vacuously)
        if unclear_count == 0:
            scores["verification_json_unclear_notes_present"] = 1.0
        else:
            scores["verification_json_unclear_notes_present"] = (unclear_has_notes / unclear_count) if unclear_count > 0 else 0.0

    # Verify numbers and statuses against inputs/rules
    if ver_arr is not None and expected_map:
        ver_by_id = _claims_from_json_by_id(ver_arr)
        # status correctness
        status_total = 0
        status_ok = 0
        numbers_total = 0
        numbers_ok = 0
        # Also ensure all claims present
        # We'll compute fraction correctness across present claims; missing claims will not contribute ok
        for cid, exp in expected_map.items():
            rec = ver_by_id.get(cid)
            if rec is None:
                status_total += 1
                numbers_total += 1
                continue
            # status
            status_total += 1
            status = str(rec.get("status", "")).strip().lower()
            if status == exp["status"]:
                status_ok += 1
            # numbers: metric, area, claim_value, claim_unit, official_year, official_value/unit,
            # difference, tolerance
            numbers_total += 1
            metric_ok = str(rec.get("metric", "")).strip() == exp["metric"]
            area_ok = str(rec.get("area", "")).strip() == exp["area"]
            cval_ok = _float_equal(_to_float(rec.get("claim_value")), _to_float(exp["claim_value"]))
            cunit_ok = _normalize_unit(rec.get("claim_unit")) == _normalize_unit(exp["claim_unit"])
            oyear_ok = _to_int(rec.get("official_year")) == exp["official_year"]
            # Official value/unit: if exp official_value is None (no official match), accept None; else match
            exp_ov = exp["official_value"]
            rec_ov = _to_float(rec.get("official_value"))
            if exp_ov is None:
                ovalue_ok = rec.get("official_value") in (None, "", "null")
                ounit_ok = rec.get("official_unit") in (None, "", "null")
            else:
                ovalue_ok = _float_equal(rec_ov, float(exp_ov))
                ounit_ok = _normalize_unit(rec.get("official_unit")) == _normalize_unit(exp["official_unit"])
            # Tolerance: if we can compute expected tolerance, enforce equality
            tol_ok = True
            if exp["tolerance"] is not None:
                tol_ok = _float_equal(_to_float(rec.get("tolerance")), float(exp["tolerance"]))
            # Difference: only enforce when units match and official exists and claim value is present
            diff_ok = True
            if exp["difference"] is not None:
                diff_ok = _float_equal(_to_float(rec.get("difference")), float(exp["difference"]))
            if all([metric_ok, area_ok, cval_ok, cunit_ok, oyear_ok, ovalue_ok, ounit_ok, tol_ok, diff_ok]):
                numbers_ok += 1
        scores["verification_json_statuses_correct"] = (status_ok / status_total) if status_total > 0 else 0.0
        scores["verification_json_numbers_correct"] = (numbers_ok / numbers_total) if numbers_total > 0 else 0.0

    # Summary report checks
    summary_text = _safe_read_text(summary_md_path) or ""
    if ver_arr is not None and summary_text:
        counts = {"accurate": 0, "inaccurate": 0, "unclear": 0}
        for rec in ver_arr:
            s = str(rec.get("status", "")).strip().lower()
            if s in counts:
                counts[s] += 1
        parsed_counts = _parse_counts_from_summary(summary_text)
        if parsed_counts is not None and all(parsed_counts.get(k) == counts.get(k) for k in counts.keys()):
            scores["summary_report_counts_consistent_with_json"] = 1.0
        # mentions at least one metric and one area
        metrics = set()
        areas = set()
        # Gather from claims.csv if available, else from verification JSON
        if claims_rows is not None:
            for r in claims_rows:
                if r.get("metric"):
                    metrics.add(r["metric"].strip())
                if r.get("area"):
                    areas.add(r["area"].strip())
        else:
            for rec in ver_arr:
                m = rec.get("metric")
                a = rec.get("area")
                if isinstance(m, str):
                    metrics.add(m.strip())
                if isinstance(a, str):
                    areas.add(a.strip())
        mention_metric = any(m in summary_text for m in metrics)
        mention_area = any(a in summary_text for a in areas)
        if mention_metric and mention_area:
            scores["summary_report_mentions_metrics_and_areas"] = 1.0

    # Meeting notes checks
    notes_text = _safe_read_text(notes_md_path) or ""
    if notes_text and context is not None:
        # Sections
        has_agenda = re.search(r"(?i)\bagenda\b", notes_text) is not None
        has_findings = re.search(r"(?i)\bfindings summary\b", notes_text) is not None
        has_actions = re.search(r"(?i)\baction items\b", notes_text) is not None
        # Meeting date present
        meeting_date_str = context.get("meeting_date") or context.get("meeting_date".lower())
        meeting_date_present = False
        if meeting_date_str:
            meeting_date_present = meeting_date_str in notes_text
        if has_agenda and has_findings and has_actions and meeting_date_present:
            scores["meeting_notes_sections_and_meeting_date_present"] = 1.0

        # Action items coverage for Inaccurate/Unclear
        if ver_arr is not None:
            due_ok_total = 0
            due_ok_hit = 0
            action_section = _extract_action_items_section(notes_text)
            owner = context.get("default_action_owner") or context.get("default_action_owner".lower()) or ""
            # Compute due date: meeting_date + 7 days
            due_target = None
            try:
                if meeting_date_str:
                    dt = datetime.strptime(meeting_date_str, "%Y-%m-%d").date()
                    due_target = (dt + timedelta(days=7)).isoformat()
            except Exception:
                due_target = None
            for rec in ver_arr:
                status = str(rec.get("status", "")).strip().lower()
                if status in ("inaccurate", "unclear"):
                    due_ok_total += 1
                    cid = rec.get("claim_id")
                    if not isinstance(cid, str):
                        continue
                    cid = cid.strip()
                    # Find a line that contains claim id, due date, and owner
                    found = False
                    if action_section:
                        for line in action_section.splitlines():
                            if cid in line:
                                has_due = (due_target in line) if due_target else False
                                has_owner = (owner in line) if owner else True
                                if has_due and has_owner:
                                    found = True
                                    break
                    if found:
                        due_ok_hit += 1
            if due_ok_total == 0:
                # If there are no inaccurate/unclear, this requirement is trivially satisfied
                scores["meeting_notes_action_items_cover_all_inaccurate_or_unclear"] = 1.0
            else:
                scores["meeting_notes_action_items_cover_all_inaccurate_or_unclear"] = (
                    due_ok_hit / due_ok_total
                ) if due_ok_total > 0 else 0.0

    # command.txt checks
    cmd_text = _safe_read_text(cmd_txt_path)
    if cmd_text is not None:
        content = cmd_text.strip()
        if content:
            scores["command_txt_present_and_nonempty"] = 1.0
            # Heuristic: looks like a reproducible command if contains 'python', 'bash', 'sh', or './'
            if any(token in content for token in ["python", "python3", "bash", "sh", "./"]):
                scores["command_txt_seems_reproducible_command"] = 1.0

    return scores


def main() -> None:
    ws = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], ws)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()