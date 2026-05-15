import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_config_yaml_fields(text: str) -> Dict[str, object]:
    """
    Minimal YAML extractor tailored to provided config structure.
    Extracts:
      - date_range.start, date_range.end (ISO date strings)
      - include_environments (list of strings from inline list)
      - thresholds.redness_high, thresholds.itch_high, thresholds.breakout_rate_high (floats)
      - suspect_rule (string)
    """
    data = {
        "date_range_start": None,
        "date_range_end": None,
        "include_environments": None,
        "thresholds": {},
        "suspect_rule": None,
    }
    # thresholds
    m = re.search(r"redness_high\s*:\s*([0-9.]+)", text)
    if m:
        try:
            data["thresholds"]["redness_high"] = float(m.group(1))
        except Exception:
            pass
    m = re.search(r"itch_high\s*:\s*([0-9.]+)", text)
    if m:
        try:
            data["thresholds"]["itch_high"] = float(m.group(1))
        except Exception:
            pass
    m = re.search(r"breakout_rate_high\s*:\s*([0-9.]+)", text)
    if m:
        try:
            data["thresholds"]["breakout_rate_high"] = float(m.group(1))
        except Exception:
            pass
    # date_range
    ms = re.search(r"^\s*date_range\s*:\s*$", text, re.MULTILINE)
    if ms:
        # Find block under date_range
        block_match = re.search(r"date_range\s*:\s*\n((?:[ \t].*\n?)*)", text)
        if block_match:
            block = block_match.group(1)
            mstart = re.search(r"^\s*start\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", block, re.MULTILINE)
            mend = re.search(r"^\s*end\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", block, re.MULTILINE)
            if mstart:
                data["date_range_start"] = mstart.group(1)
            if mend:
                data["date_range_end"] = mend.group(1)
    # Fallback independent extraction if block parsing fails
    if not data["date_range_start"]:
        mstart = re.search(r"^\s*start\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", text, re.MULTILINE)
        if mstart:
            data["date_range_start"] = mstart.group(1)
    if not data["date_range_end"]:
        mend = re.search(r"^\s*end\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", text, re.MULTILINE)
        if mend:
            data["date_range_end"] = mend.group(1)

    # include_environments: inline list e.g., ["home", "photoshoot", "outdoor"]
    m = re.search(r"include_environments\s*:\s*\[(.*?)\]", text, re.DOTALL)
    if m:
        inner = m.group(1)
        items = []
        for part in inner.split(","):
            s = part.strip()
            s = s.strip('"').strip("'")
            if s:
                items.append(s)
        data["include_environments"] = items
    # suspect_rule
    m = re.search(r"suspect_rule\s*:\s*['\"]?([A-Za-z_]+)['\"]?", text)
    if m:
        data["suspect_rule"] = m.group(1)
    return data


def _compute_expected_metrics(
    logs: List[Dict[str, str]],
    start_date: Optional[str],
    end_date: Optional[str],
    include_envs: Optional[List[str]],
    thresholds: Dict[str, float],
    suspect_rule: str = "any",
) -> Tuple[Dict[str, dict], int, int]:
    """
    Compute expected metrics from input logs and provided filtering and thresholds.
    Returns:
      - metrics_by_product: dict product_name -> metrics dict
      - total_rows_analyzed: int
      - total_products: int
    """
    def parse_date(s: str) -> Optional[datetime]:
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d")
        except Exception:
            return None

    start_dt = parse_date(start_date) if start_date else None
    end_dt = parse_date(end_date) if end_date else None
    include_set = set(include_envs) if include_envs else None

    filtered = []
    for r in logs:
        d = parse_date(r.get("date", ""))
        if d is None:
            continue
        if start_dt and d < start_dt:
            continue
        if end_dt and d > end_dt:
            continue
        env = (r.get("environment") or "").strip()
        if include_set is not None and env not in include_set:
            continue
        filtered.append(r)

    totals = {}
    for r in filtered:
        p = (r.get("product_name") or "").strip()
        if not p:
            continue
        entry = totals.setdefault(p, {"count": 0, "red_sum": 0.0, "itch_sum": 0.0, "break_count": 0})
        entry["count"] += 1
        try:
            entry["red_sum"] += float(r.get("redness_score", "0") or 0.0)
        except Exception:
            entry["red_sum"] += 0.0
        try:
            entry["itch_sum"] += float(r.get("itch_score", "0") or 0.0)
        except Exception:
            entry["itch_sum"] += 0.0
        try:
            br = r.get("breakout", "0")
            brs = str(br).strip()
            brn = 1 if brs == "1" else 0
            entry["break_count"] += brn
        except Exception:
            pass

    metrics = {}
    th_red = thresholds.get("redness_high", float("inf"))
    th_itch = thresholds.get("itch_high", float("inf"))
    th_brk = thresholds.get("breakout_rate_high", float("inf"))
    suspect_any = str(suspect_rule or "").lower() == "any"
    suspect_all = str(suspect_rule or "").lower() == "all"
    for p, agg in totals.items():
        uses = agg["count"]
        avg_r = (agg["red_sum"] / uses) if uses else 0.0
        avg_i = (agg["itch_sum"] / uses) if uses else 0.0
        br_rate = (agg["break_count"] / uses) if uses else 0.0
        exceed_r = avg_r > th_red
        exceed_i = avg_i > th_itch
        exceed_b = br_rate > th_brk
        if suspect_all:
            is_sus = (exceed_r and exceed_i and exceed_b)
        else:  # default "any"
            is_sus = (exceed_r or exceed_i or exceed_b)
        metrics[p] = {
            "product_name": p,
            "count_uses": uses,
            "avg_redness": avg_r,
            "avg_itch": avg_i,
            "breakout_rate": br_rate,
            "is_suspect": is_sus,
            "exceeded": {
                "avg_redness": exceed_r,
                "avg_itch": exceed_i,
                "breakout_rate": exceed_b,
            },
        }

    return metrics, len(filtered), len(metrics)


def _float_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _parse_metrics_csv(path: Path) -> Optional[Dict[str, dict]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None
    result = {}
    for r in rows:
        p = r.get("product_name")
        if p is None:
            return None
        try:
            cu = int(str(r.get("count_uses", "")).strip())
            ar = float(str(r.get("avg_redness", "")).strip())
            ai = float(str(r.get("avg_itch", "")).strip())
            br = float(str(r.get("breakout_rate", "")).strip())
        except Exception:
            return None
        is_s = r.get("is_suspect", "")
        if isinstance(is_s, str):
            is_s_lower = is_s.strip().lower()
            if is_s_lower not in ("true", "false"):
                is_s_lower = is_s_lower  # keep for format check
            is_s_bool = (is_s_lower == "true")
        else:
            return None
        result[p] = {
            "product_name": p,
            "count_uses": cu,
            "avg_redness": ar,
            "avg_itch": ai,
            "breakout_rate": br,
            "is_suspect_str": is_s_lower,
            "is_suspect_bool": is_s_bool,
        }
    return result


def _csv_headers_exact(path: Path, expected_headers: List[str]) -> bool:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return False
            return header == expected_headers
    except Exception:
        return False


def _parse_metrics_json(path: Path) -> Optional[Dict[str, dict]]:
    data = _safe_read_json(path)
    if not isinstance(data, list):
        return None
    result = {}
    for item in data:
        if not isinstance(item, dict):
            return None
        p = item.get("product_name")
        if p is None:
            return None
        try:
            cu = int(item.get("count_uses"))
            ar = float(item.get("avg_redness"))
            ai = float(item.get("avg_itch"))
            br = float(item.get("breakout_rate"))
        except Exception:
            return None
        is_s = item.get("is_suspect")
        if not isinstance(is_s, bool):
            return None
        result[p] = {
            "product_name": p,
            "count_uses": cu,
            "avg_redness": ar,
            "avg_itch": ai,
            "breakout_rate": br,
            "is_suspect_bool": is_s,
        }
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "refactored_script_present": 0.0,
        "refactored_script_uses_config_indicators": 0.0,
        "config_thresholds_updated": 0.0,
        "config_other_fields_intact": 0.0,
        "metrics_csv_headers_correct": 0.0,
        "metrics_csv_values_correct": 0.0,
        "metrics_csv_boolean_format": 0.0,
        "metrics_json_values_correct": 0.0,
        "metrics_files_consistent": 0.0,
        "suspects_expected_set": 0.0,
        "derm_notes_summary_line_present": 0.0,
        "derm_notes_suspect_list_with_thresholds": 0.0,
        "derm_notes_action_items_present": 0.0,
        "derm_notes_next_steps_present": 0.0,
        "status_update_improvements_count": 0.0,
        "status_update_results_summary_present": 0.0,
    }

    # Paths
    input_logs_path = workspace / "input" / "product_logs.csv"
    input_config_path = workspace / "input" / "config.yaml"
    refactored_script_path = workspace / "src" / "analysis_refactored.py"
    metrics_csv_path = workspace / "reports" / "metrics.csv"
    metrics_json_path = workspace / "reports" / "metrics.json"
    derm_notes_path = workspace / "reports" / "derm_meeting_notes.md"
    status_update_path = workspace / "reports" / "status_update.md"

    # Expected parameters from task
    expected_thresholds = {
        "redness_high": 2.5,
        "itch_high": 1.5,
        "breakout_rate_high": 0.2,
    }
    expected_start = "2026-03-01"
    expected_end = "2026-03-03"
    expected_envs = ["home", "photoshoot", "outdoor"]
    suspect_rule = "any"

    # Load logs (if present)
    raw_logs = _safe_read_csv_dicts(input_logs_path) or []

    # Compute expected metrics
    expected_metrics, expected_rows, expected_products_count = _compute_expected_metrics(
        raw_logs, expected_start, expected_end, expected_envs, expected_thresholds, suspect_rule
    )
    expected_suspects = sorted([p for p, m in expected_metrics.items() if m["is_suspect"]])

    # Check refactored script presence and indicators
    if refactored_script_path.exists():
        scores["refactored_script_present"] = 1.0
        script_text = _read_text(refactored_script_path) or ""
        indicators = 0
        if "input/config.yaml" in script_text or "config.yaml" in script_text:
            indicators += 1
        if "thresholds" in script_text:
            indicators += 1
        if "include_environments" in script_text:
            indicators += 1
        if "date_range" in script_text:
            indicators += 1
        if "suspect_rule" in script_text:
            indicators += 1
        if "metrics.csv" in script_text and "metrics.json" in script_text:
            indicators += 1
        if ("config.yaml" in script_text or "input/config.yaml" in script_text) and indicators >= 4:
            scores["refactored_script_uses_config_indicators"] = 1.0

    # Config checks
    cfg_text = _read_text(input_config_path) or ""
    cfg_fields = _parse_config_yaml_fields(cfg_text) if cfg_text else {}
    th = cfg_fields.get("thresholds") or {}

    thresholds_updated = (
        isinstance(th.get("redness_high"), float)
        and isinstance(th.get("itch_high"), float)
        and isinstance(th.get("breakout_rate_high"), float)
        and _float_equal(th.get("redness_high"), 2.5)
        and _float_equal(th.get("itch_high"), 1.5)
        and _float_equal(th.get("breakout_rate_high"), 0.2)
    )
    if thresholds_updated:
        scores["config_thresholds_updated"] = 1.0

    # Other fields intact: gate this so it does not award points for the unmodified scaffold config
    include_envs = cfg_fields.get("include_environments")
    drs = cfg_fields.get("date_range_start")
    dre = cfg_fields.get("date_range_end")
    intact = (
        isinstance(include_envs, list)
        and set(include_envs) == set(expected_envs)
        and drs == expected_start
        and dre == expected_end
    )
    if thresholds_updated and intact:
        scores["config_other_fields_intact"] = 1.0

    # Metrics CSV checks
    expected_headers = ["product_name", "count_uses", "avg_redness", "avg_itch", "breakout_rate", "is_suspect"]
    if metrics_csv_path.exists() and _csv_headers_exact(metrics_csv_path, expected_headers):
        scores["metrics_csv_headers_correct"] = 1.0

    csv_records = _parse_metrics_csv(metrics_csv_path) if metrics_csv_path.exists() else None
    if csv_records is not None:
        # boolean format check
        bool_format_ok = all(v.get("is_suspect_str") in ("true", "false") for v in csv_records.values())
        if bool_format_ok:
            scores["metrics_csv_boolean_format"] = 1.0

        # values correct
        products_csv = set(csv_records.keys())
        products_expected = set(expected_metrics.keys())
        values_ok = products_csv == products_expected
        if values_ok:
            for p in products_expected:
                rec = csv_records[p]
                exp = expected_metrics[p]
                if rec["count_uses"] != exp["count_uses"]:
                    values_ok = False
                    break
                if not _float_equal(rec["avg_redness"], exp["avg_redness"]):
                    values_ok = False
                    break
                if not _float_equal(rec["avg_itch"], exp["avg_itch"]):
                    values_ok = False
                    break
                if not _float_equal(rec["breakout_rate"], exp["breakout_rate"]):
                    values_ok = False
                    break
                if rec["is_suspect_bool"] != exp["is_suspect"]:
                    values_ok = False
                    break
        if values_ok:
            scores["metrics_csv_values_correct"] = 1.0

        # suspects expected set (from CSV)
        suspects_csv = sorted([p for p, r in csv_records.items() if r.get("is_suspect_bool")])
        if suspects_csv == expected_suspects:
            scores["suspects_expected_set"] = 1.0

    # Metrics JSON checks
    json_records = _parse_metrics_json(metrics_json_path) if metrics_json_path.exists() else None
    if json_records is not None:
        products_json = set(json_records.keys())
        products_expected = set(expected_metrics.keys())
        json_ok = products_json == products_expected
        if json_ok:
            for p in products_expected:
                rec = json_records[p]
                exp = expected_metrics[p]
                if rec["count_uses"] != exp["count_uses"]:
                    json_ok = False
                    break
                if not _float_equal(rec["avg_redness"], exp["avg_redness"]):
                    json_ok = False
                    break
                if not _float_equal(rec["avg_itch"], exp["avg_itch"]):
                    json_ok = False
                    break
                if not _float_equal(rec["breakout_rate"], exp["breakout_rate"]):
                    json_ok = False
                    break
                if rec["is_suspect_bool"] != exp["is_suspect"]:
                    json_ok = False
                    break
        if json_ok:
            scores["metrics_json_values_correct"] = 1.0

    # Consistency between CSV and JSON
    if csv_records is not None and json_records is not None:
        consistent = set(csv_records.keys()) == set(json_records.keys())
        if consistent:
            for p in csv_records.keys():
                c = csv_records[p]
                j = json_records[p]
                if c["count_uses"] != j["count_uses"]:
                    consistent = False
                    break
                if not _float_equal(c["avg_redness"], j["avg_redness"]):
                    consistent = False
                    break
                if not _float_equal(c["avg_itch"], j["avg_itch"]):
                    consistent = False
                    break
                if not _float_equal(c["breakout_rate"], j["breakout_rate"]):
                    consistent = False
                    break
                if c["is_suspect_bool"] != j["is_suspect_bool"]:
                    consistent = False
                    break
        if consistent:
            scores["metrics_files_consistent"] = 1.0

    # Derm meeting notes checks
    derm_text = _read_text(derm_notes_path) or ""
    if derm_text:
        lines = [ln.strip() for ln in derm_text.splitlines() if ln.strip()]
        tlower = derm_text.lower()

        # summary line: contains "Analyzed", both dates, and at least one environment name
        summary_ok = False
        for ln in lines[:10]:
            lnl = ln.lower()
            if ("analyz" in lnl and expected_start in ln and expected_end in ln and
               (("home" in lnl) or ("photoshoot" in lnl) or ("outdoor" in lnl))):
                summary_ok = True
                break
        if summary_ok:
            scores["derm_notes_summary_line_present"] = 1.0

        # suspect list with thresholds exceeded
        thresholds_tokens = ["avg_redness", "avg_itch", "breakout_rate"]
        suspects_thresholds_ok = True
        for p in expected_suspects:
            found = False
            for ln in lines:
                if p in ln and ">" in ln and any(tok in ln for tok in thresholds_tokens):
                    found = True
                    break
            if not found:
                suspects_thresholds_ok = False
                break
        if suspects_thresholds_ok and expected_suspects:
            scores["derm_notes_suspect_list_with_thresholds"] = 1.0

        # action items for each suspect
        action_keywords = ["pause", "patch", "ingredient"]
        actions_ok = True
        for p in expected_suspects:
            found = False
            for ln in lines:
                if p in ln and any(k in ln.lower() for k in action_keywords):
                    found = True
                    break
            if not found:
                actions_ok = False
                break
        if actions_ok and expected_suspects:
            scores["derm_notes_action_items_present"] = 1.0

        # closing note with next steps
        if ("next steps" in tlower) or ("follow-up" in tlower) or ("follow up" in tlower):
            scores["derm_notes_next_steps_present"] = 1.0

    # Status update checks
    status_text = _read_text(status_update_path) or ""
    if status_text:
        slines = [ln.rstrip() for ln in status_text.splitlines()]
        # Count bullet/numbered improvements
        improvements = 0
        for ln in slines:
            if re.match(r"^\s*[-*]\s+.+", ln) or re.match(r"^\s*\d+\.\s+.+", ln):
                improvements += 1
        if improvements >= 3:
            scores["status_update_improvements_count"] = 1.0

        # results summary: expect numbers 18 (rows/apps), 7 (products), 2 (suspects)
        stl = status_text.lower()
        has_rows_apps = ("rows" in stl or "applications" in stl) and ("18" in status_text)
        has_products = ("product" in stl) and ("7" in status_text)
        has_suspects = ("suspect" in stl) and ("2" in status_text)
        if has_rows_apps and has_products and has_suspects:
            scores["status_update_results_summary_present"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()