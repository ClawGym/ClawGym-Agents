import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    return []
    except Exception:
        return []
    return records


def _safe_read_csv_dicts(path: Path) -> List[Dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return []


class _GuidanceHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.current_tag_stack: List[str] = []
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self._capture_data = False
        self._td_buffer = ""

    def handle_starttag(self, tag, attrs):
        self.current_tag_stack.append(tag)
        if tag == "table":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "limits":
                self.in_table = True
        if self.in_table and tag in ("td", "th"):
            self._capture_data = True
            self._td_buffer = ""
        if self.in_table and tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag):
        if self.in_table and tag in ("td", "th"):
            self._capture_data = False
            self.current_row.append(self._td_buffer.strip())
            self._td_buffer = ""
        if self.in_table and tag == "tr":
            if len(self.current_row) == 6:
                self.rows.append(self.current_row)
            self.current_row = []
        if tag == "table" and self.in_table:
            self.in_table = False
        if self.current_tag_stack and self.current_tag_stack[-1] == tag:
            self.current_tag_stack.pop()

    def handle_data(self, data):
        if self.in_table and self._capture_data:
            self._td_buffer += data


def _parse_guidance_html(html_text: str) -> List[Dict[str, Any]]:
    parser = _GuidanceHTMLParser()
    parser.feed(html_text)
    guidance: List[Dict[str, Any]] = []
    for row in parser.rows:
        rule_id, parameter_key, threshold, unit, severity_weight, description = row
        try:
            thr = float(threshold)
        except Exception:
            continue
        try:
            sev = float(severity_weight)
        except Exception:
            continue
        guidance.append({
            "rule_id": rule_id.strip(),
            "parameter_key": parameter_key.strip(),
            "threshold": thr,
            "unit": unit.strip(),
            "severity_weight": sev,
            "description": description.strip()
        })
    return guidance


def _to_float(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    if val is None:
        return None
    if isinstance(val, str) and val.strip() != "":
        try:
            return float(val.strip())
        except Exception:
            return None
    return None


def _float_eq(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _compute_expected(workspace: Path) -> Dict[str, Any]:
    check_results_path = workspace / "input" / "check_results.jsonl"
    guidance_html_path = workspace / "input" / "nrc_guidance.html"
    inventory_csv_path = workspace / "input" / "system_inventory.csv"

    check_rows = _safe_load_jsonl(check_results_path)
    guidance_html = _safe_read_text(guidance_html_path) or ""
    inventory_rows = _safe_read_csv_dicts(inventory_csv_path)

    guidance = _parse_guidance_html(guidance_html) if guidance_html else []

    guidance_by_triple: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    guidance_by_pair_units: Dict[Tuple[str, str], List[str]] = {}
    guidance_pairs: set = set()
    for g in guidance:
        keyt = (g["rule_id"], g["parameter_key"], g["unit"])
        guidance_by_triple[keyt] = g
        pair = (g["rule_id"], g["parameter_key"])
        guidance_pairs.add(pair)
        guidance_by_pair_units.setdefault(pair, []).append(g["unit"])

    criticality_by_system: Dict[str, float] = {}
    for row in inventory_rows:
        sys_name = (row.get("system") or "").strip()
        cf = _to_float(row.get("criticality_factor"))
        if sys_name and cf is not None:
            criticality_by_system[sys_name] = cf

    tool_counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    recomputed_counts = {"PASS": 0, "FAIL": 0}
    mismatches: List[Dict[str, Any]] = []
    unit_mismatches: List[Dict[str, Any]] = []
    missing_guidance_set: set = set()
    noncompliant_rows: List[Dict[str, Any]] = []
    error_categories: Dict[str, List[Dict[str, Any]]] = {"Timeout": [], "PermissionDenied": [], "CommandNotFound": [], "Other": []}

    for r in check_rows:
        status = str(r.get("status", "")).upper()
        if status in tool_counts:
            tool_counts[status] += 1

        rule_id = str(r.get("rule_id", "")).strip()
        parameter_key = str(r.get("parameter_key", "")).strip()
        unit = str(r.get("unit", "")).strip()
        system = str(r.get("system", "")).strip()
        measured_val = _to_float(r.get("measured_value"))

        triple_key = (rule_id, parameter_key, unit)
        pair_key = (rule_id, parameter_key)

        guidance_row = guidance_by_triple.get(triple_key)
        if guidance_row is None:
            if pair_key in guidance_pairs:
                expected_units = guidance_by_pair_units.get(pair_key, [])
                unit_mismatches.append({
                    "rule_id": rule_id,
                    "parameter_key": parameter_key,
                    "unit_in_result": unit,
                    "expected_units": expected_units
                })
            else:
                missing_guidance_set.add(pair_key)

        recomputed_status: Optional[str] = None
        if guidance_row is not None and measured_val is not None:
            thr = guidance_row["threshold"]
            recomputed_status = "PASS" if measured_val <= thr else "FAIL"
            if recomputed_status in recomputed_counts:
                recomputed_counts[recomputed_status] += 1

            if recomputed_status == "FAIL":
                severity = guidance_row["severity_weight"]
                cf = criticality_by_system.get(system, 0.0)
                exceedance = measured_val / thr if thr != 0 else float("inf")
                risk = severity * cf * exceedance
                noncompliant_rows.append({
                    "timestamp": r.get("timestamp"),
                    "system": system,
                    "rule_id": rule_id,
                    "description": guidance_row.get("description", ""),
                    "parameter_key": parameter_key,
                    "measured_value": measured_val,
                    "unit": unit,
                    "threshold": thr,
                    "severity_weight": severity,
                    "criticality_factor": cf,
                    "exceedance_ratio": exceedance,
                    "risk_score": risk
                })

        if status in ("PASS", "FAIL") and recomputed_status is not None:
            if status != recomputed_status:
                mismatches.append({
                    "timestamp": r.get("timestamp"),
                    "system": system,
                    "rule_id": rule_id,
                    "parameter_key": parameter_key,
                    "tool_status": status,
                    "recomputed_status": recomputed_status
                })

        if status == "ERROR":
            stderr = str(r.get("stderr", "") or "")
            if stderr.strip() == "":
                continue
            s = stderr.lower()
            if "timeout" in s:
                cat = "Timeout"
            elif "permission denied" in s:
                cat = "PermissionDenied"
            elif "command not found" in s:
                cat = "CommandNotFound"
            else:
                cat = "Other"
            error_categories[cat].append({
                "system": system,
                "rule_id": rule_id,
                "stderr": stderr
            })

    noncompliant_rows_sorted = sorted(noncompliant_rows, key=lambda x: (-x["risk_score"], x["timestamp"] or ""))

    error_diag_expected: Dict[str, Dict[str, Any]] = {}
    for cat, items in error_categories.items():
        if not items:
            continue
        error_diag_expected[cat] = {
            "count": len(items),
            "sample_stderr": items[0]["stderr"],
            "affected": [{"system": it["system"], "rule_id": it["rule_id"]} for it in items]
        }

    expected = {
        "tool_counts": tool_counts,
        "recomputed_counts": recomputed_counts,
        "mismatches": mismatches,
        "unit_mismatches": unit_mismatches,
        "missing_guidance": sorted(list({f"{rk}/{pk}" for rk, pk in missing_guidance_set})),
        "noncompliance_rows": noncompliant_rows_sorted,
        "error_diagnostics": error_diag_expected,
    }
    return expected


def _load_output_noncompliance_csv(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows = _safe_read_csv_dicts(path)
    headers: List[str] = []
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
    except Exception:
        pass
    converted: List[Dict[str, Any]] = []
    for row in rows:
        c = dict(row)
        for k in ("measured_value", "threshold", "severity_weight", "criticality_factor", "exceedance_ratio", "risk_score"):
            if k in c:
                c[k] = _to_float(c.get(k))
            else:
                c[k] = None
        converted.append(c)
    return converted, headers


def _compare_noncompliance(expected_rows: List[Dict[str, Any]], actual_rows: List[Dict[str, Any]]) -> Dict[str, float]:
    scores = {
        "noncompliance_report_row_count": 0.0,
        "noncompliance_report_sorted_desc": 0.0,
        "noncompliance_report_values_correct": 0.0,
    }
    if not actual_rows and expected_rows:
        return scores
    if len(expected_rows) == len(actual_rows):
        scores["noncompliance_report_row_count"] = 1.0

    if actual_rows:
        rs = [r.get("risk_score") for r in actual_rows]
        sorted_desc = all(rs[i] is not None and rs[i + 1] is not None and rs[i] >= rs[i + 1] for i in range(len(rs) - 1))
        if sorted_desc:
            scores["noncompliance_report_sorted_desc"] = 1.0

    def keyfunc(r: Dict[str, Any]) -> Tuple[Any, Any, Any, Any]:
        return (r.get("timestamp"), r.get("system"), r.get("rule_id"), r.get("parameter_key"))

    exp_map = {keyfunc(r): r for r in expected_rows}
    act_map = {keyfunc(r): r for r in actual_rows}
    if set(exp_map.keys()) != set(act_map.keys()):
        return scores

    ok_all = True
    for k, exp in exp_map.items():
        act = act_map.get(k, {})
        fields_strict = [
            ("unit", lambda a, b: a == b),
            ("description", lambda a, b: (a or "").strip() == (b or "").strip()),
            ("rule_id", lambda a, b: a == b),
            ("system", lambda a, b: a == b),
            ("parameter_key", lambda a, b: a == b),
            ("timestamp", lambda a, b: a == b),
        ]
        fields_float = ["measured_value", "threshold", "severity_weight", "criticality_factor", "exceedance_ratio", "risk_score"]
        for f, cmpf in fields_strict:
            if not cmpf(act.get(f), exp.get(f)):
                ok_all = False
                break
        if not ok_all:
            break
        for f in fields_float:
            if not _float_eq(act.get(f), exp.get(f)):
                ok_all = False
                break
        if not ok_all:
            break
    if ok_all:
        scores["noncompliance_report_values_correct"] = 1.0
    return scores


def _parse_status_summary(md_text: str) -> Dict[str, Any]:
    result = {
        "pass_counts": [],
        "fail_counts": [],
        "error_counts": [],
        "mentions_mismatch_none": False,
        "mentions_unit_mismatch_none": False,
        "mentions_missing_guidance": []
    }
    text = md_text
    lines = text.splitlines()

    def find_counts(keyword: str) -> List[int]:
        out: List[int] = []
        pat = re.compile(rf"{keyword}\b[^0-9\-+]*([0-9]+)", re.IGNORECASE)
        for ln in lines:
            for m in pat.finditer(ln):
                try:
                    out.append(int(m.group(1)))
                except Exception:
                    pass
        return out

    result["pass_counts"] = find_counts("pass")
    result["fail_counts"] = find_counts("fail")
    result["error_counts"] = find_counts("error")

    for ln in lines:
        lnl = ln.lower()
        if "mismatch" in lnl and "unit" not in lnl and "none" in lnl:
            result["mentions_mismatch_none"] = True
        if ("unit mismatch" in lnl or "unit-mismatch" in lnl or ("mismatch" in lnl and "unit" in lnl)) and "none" in lnl:
            result["mentions_unit_mismatch_none"] = True

    mg: List[str] = []
    capture = False
    for ln in lines:
        if "missing guidance" in ln.lower():
            capture = True
            continue
        if capture:
            if ln.strip() == "" or re.match(r"^#+\s", ln):
                break
            mg.append(ln.strip())

    mg_items: List[str] = []
    for item in mg:
        if item and item.lower() not in ("none", "- none", "* none"):
            mg_items.append(item)
    result["mentions_missing_guidance"] = mg_items
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "noncompliance_report_present_structure": 0.0,
        "noncompliance_report_row_count": 0.0,
        "noncompliance_report_sorted_desc": 0.0,
        "noncompliance_report_values_correct": 0.0,
        "error_diagnostics_present_structure": 0.0,
        "error_diagnostics_counts_correct": 0.0,
        "error_diagnostics_affected_correct": 0.0,
        "status_summary_present": 0.0,
        "status_summary_tool_counts_correct": 0.0,
        "status_summary_recomputed_counts_correct": 0.0,
        "status_summary_mismatches_listed_or_none": 0.0,
        "status_summary_unit_mismatches_listed_or_none": 0.0,
        "status_summary_missing_guidance_note": 0.0,
        "email_present": 0.0,
        "email_subject_present": 0.0,
        "email_top3_risks_match_report": 0.0,
        "email_error_diagnostics_counts_present": 0.0,
        "email_requests_guidance_present": 0.0,
    }

    expected = _compute_expected(workspace)
    exp_noncomp_rows: List[Dict[str, Any]] = expected.get("noncompliance_rows", [])
    exp_error_diag: Dict[str, Dict[str, Any]] = expected.get("error_diagnostics", {})
    exp_tool_counts: Dict[str, int] = expected.get("tool_counts", {})
    exp_recomp_counts: Dict[str, int] = expected.get("recomputed_counts", {})
    exp_mismatches: List[Dict[str, Any]] = expected.get("mismatches", [])
    exp_unit_mismatches: List[Dict[str, Any]] = expected.get("unit_mismatches", [])
    exp_missing_guidance: List[str] = expected.get("missing_guidance", [])

    out_csv_path = workspace / "output" / "noncompliance_report.csv"
    if out_csv_path.exists():
        actual_rows, headers = _load_output_noncompliance_csv(out_csv_path)
        expected_columns = ["timestamp", "system", "rule_id", "description", "parameter_key", "measured_value", "unit", "threshold", "severity_weight", "criticality_factor", "exceedance_ratio", "risk_score"]
        if headers == expected_columns:
            scores["noncompliance_report_present_structure"] = 1.0
        comp_scores = _compare_noncompliance(exp_noncomp_rows, actual_rows)
        scores.update({k: max(scores.get(k, 0.0), v) for k, v in comp_scores.items()})

    out_errdiag_path = workspace / "output" / "error_diagnostics.json"
    if out_errdiag_path.exists():
        actual_diag = _safe_load_json(out_errdiag_path)
        if isinstance(actual_diag, dict):
            scores["error_diagnostics_present_structure"] = 1.0
            counts_ok = True
            affected_ok = True
            for cat, exp_obj in exp_error_diag.items():
                act_obj = actual_diag.get(cat)
                if not isinstance(act_obj, dict):
                    counts_ok = False
                    affected_ok = False
                    break
                if act_obj.get("count") != exp_obj.get("count"):
                    counts_ok = False
                if "sample_stderr" not in act_obj or not isinstance(act_obj["sample_stderr"], str):
                    counts_ok = False
                exp_aff = exp_obj.get("affected") or []
                act_aff = act_obj.get("affected")
                if not isinstance(act_aff, list):
                    affected_ok = False
                else:
                    exp_set = {(d.get("system"), d.get("rule_id")) for d in exp_aff}
                    try:
                        act_set = {(d.get("system"), d.get("rule_id")) for d in act_aff if isinstance(d, dict)}
                    except Exception:
                        act_set = set()
                    if exp_set != act_set:
                        affected_ok = False
            if counts_ok:
                scores["error_diagnostics_counts_correct"] = 1.0
            if affected_ok:
                scores["error_diagnostics_affected_correct"] = 1.0

    out_summary_path = workspace / "output" / "status_summary.md"
    if out_summary_path.exists():
        md_text = _safe_read_text(out_summary_path) or ""
        if md_text:
            scores["status_summary_present"] = 1.0
            parsed = _parse_status_summary(md_text)
            tool_ok = True
            if exp_tool_counts:
                if exp_tool_counts.get("PASS") not in parsed["pass_counts"]:
                    tool_ok = False
                if exp_tool_counts.get("FAIL") not in parsed["fail_counts"]:
                    tool_ok = False
                if exp_tool_counts.get("ERROR") not in parsed["error_counts"]:
                    tool_ok = False
            if tool_ok:
                scores["status_summary_tool_counts_correct"] = 1.0
            recompute_ok = True
            if exp_recomp_counts:
                if exp_recomp_counts.get("PASS") not in parsed["pass_counts"]:
                    recompute_ok = False
                if exp_recomp_counts.get("FAIL") not in parsed["fail_counts"]:
                    recompute_ok = False
            if recompute_ok:
                scores["status_summary_recomputed_counts_correct"] = 1.0
            if (len(exp_mismatches) == 0 and parsed["mentions_mismatch_none"]) or (len(exp_mismatches) > 0):
                scores["status_summary_mismatches_listed_or_none"] = 1.0
            if (len(exp_unit_mismatches) == 0 and parsed["mentions_unit_mismatch_none"]) or (len(exp_unit_mismatches) > 0):
                scores["status_summary_unit_mismatches_listed_or_none"] = 1.0
            if exp_missing_guidance:
                mg_ok = all(any(exp_item in line for line in parsed["mentions_missing_guidance"]) for exp_item in exp_missing_guidance)
                if mg_ok:
                    scores["status_summary_missing_guidance_note"] = 1.0
            else:
                scores["status_summary_missing_guidance_note"] = 1.0

    out_email_path = workspace / "output" / "email_to_commissioner.txt"
    if out_email_path.exists():
        email_text = _safe_read_text(out_email_path) or ""
        if email_text:
            scores["email_present"] = 1.0
            first_line = email_text.splitlines()[0] if email_text.splitlines() else ""
            if first_line.lower().startswith("subject:"):
                scores["email_subject_present"] = 1.0
            actual_rows, _ = _load_output_noncompliance_csv(out_csv_path) if out_csv_path.exists() else ([], [])
            actual_sorted = sorted([r for r in actual_rows if r.get("risk_score") is not None], key=lambda x: -x["risk_score"])
            top3 = actual_sorted[:3]
            top3_ok = True
            email_lower = email_text.lower()
            for row in top3:
                rid = row.get("rule_id", "")
                sysname = row.get("system", "")
                risk = row.get("risk_score", None)
                if not rid or not sysname or risk is None:
                    top3_ok = False
                    break
                if rid not in email_text or sysname not in email_text:
                    top3_ok = False
                    break
                risk_formats = {
                    f"{risk:.0f}",
                    f"{risk:.1f}",
                    f"{risk:.2f}",
                    f"{risk:.3f}",
                }
                if not any(rf in email_text for rf in risk_formats):
                    top3_ok = False
                    break
            if top3 and top3_ok:
                scores["email_top3_risks_match_report"] = 1.0

            diag_ok = True
            for cat, exp_obj in exp_error_diag.items():
                if (cat not in email_text) and (cat.lower() not in email_lower):
                    diag_ok = False
                    break
                count_str = str(exp_obj.get("count", ""))
                if count_str and (count_str not in email_text):
                    diag_ok = False
                    break
            if diag_ok and exp_error_diag:
                scores["email_error_diagnostics_counts_present"] = 1.0

            if ("guidance" in email_lower and "request" in email_lower and ("error" in email_lower or "mismatch" in email_lower)):
                scores["email_requests_guidance_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()