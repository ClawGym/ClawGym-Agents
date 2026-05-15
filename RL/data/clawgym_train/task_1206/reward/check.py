import sys
import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from html.parser import HTMLParser
from datetime import datetime, date, timedelta


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


class _RiskTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_risk_table = False
        self.current_tag_stack: List[str] = []
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self.table_level = 0
        self.capture_text = False
        self.current_text = ""
        self.seen_tbody_or_table = False
        self._table_id_matched = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.current_tag_stack.append(tag)
        if tag == "table":
            # Check id attribute
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "risk-multipliers":
                self.in_risk_table = True
                self._table_id_matched = True
                self.table_level = len(self.current_tag_stack)
        if self.in_risk_table and tag in ("tbody", "table"):
            self.seen_tbody_or_table = True
        if self.in_risk_table and tag == "tr":
            self.current_row = []
        if self.in_risk_table and tag == "td":
            self.capture_text = True
            self.current_text = ""

    def handle_endtag(self, tag: str) -> None:
        if self.in_risk_table and tag == "td":
            self.capture_text = False
            self.current_row.append(self.current_text.strip())
            self.current_text = ""
        if self.in_risk_table and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        if tag == "table" and self._table_id_matched:
            # Leaving the matched table
            self.in_risk_table = False
            self._table_id_matched = False
        if self.current_tag_stack:
            self.current_tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.in_risk_table and self.capture_text:
            self.current_text += data


def _parse_html_multipliers(html: str) -> Optional[Dict[str, float]]:
    try:
        parser = _RiskTableParser()
        parser.feed(html)
        mapping: Dict[str, float] = {}
        for row in parser.rows:
            # Expect at least two cells: Exercise Type and Risk Multiplier
            if len(row) >= 2:
                key = row[0].strip()
                val_str = row[1].strip()
                try:
                    val = float(val_str)
                except ValueError:
                    continue
                if key:
                    mapping[key] = val
        if not mapping:
            return None
        return mapping
    except Exception:
        return None


def _percentile_linear(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    if p <= 0:
        return float(sorted(values)[0])
    if p >= 1:
        return float(sorted(values)[-1])
    arr = sorted(values)
    n = len(arr)
    # Linear interpolation method: index = (n-1)*p
    idx = (n - 1) * p
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return float(arr[lo] * (1 - frac) + arr[hi] * frac)


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        try:
            # sometimes numeric strings might be float like "100.0"
            f = float(s)
            return int(round(f))
        except Exception:
            return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _load_yaml_minimal(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader supporting simple nested mappings with scalars.
    Assumes indentation is spaces (2 or more) and consistent.
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]

    def parse_scalar(val: str) -> Any:
        v = val.strip()
        if v == "" or v.lower() == "null" or v == "~":
            return None
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        # try int
        try:
            if v.startswith("0") and v != "0" and not v.startswith("0."):
                # keep as string to avoid octal confusion
                raise ValueError
            return int(v)
        except Exception:
            pass
        # try float
        try:
            return float(v)
        except Exception:
            pass
        # strip quotes if simple
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        return v

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if ":" in content:
            key, sep, val = content.partition(":")
            key = key.strip()
            if val.strip() == "":
                # nested mapping
                # find correct parent by indentation
                while stack and indent <= stack[-1][0]:
                    stack.pop()
                parent = stack[-1][1]
                if key in parent and isinstance(parent[key], dict):
                    new_map = parent[key]
                else:
                    new_map = {}
                    parent[key] = new_map
                stack.append((indent, new_map))
            else:
                # key: value
                while stack and indent <= stack[-1][0]:
                    stack.pop()
                parent = stack[-1][1]
                parent[key] = parse_scalar(val)
        else:
            # Unsupported YAML construct; fail
            return None
    return root


def _weekday_monday_start(d: date) -> date:
    # Monday is 0 in weekday()
    return d - timedelta(days=d.weekday())


def _safe_bool_from_str(s: str) -> Optional[bool]:
    sv = str(s).strip().lower()
    if sv in ("true", "t", "1", "yes", "y"):
        return True
    if sv in ("false", "f", "0", "no", "n"):
        return False
    return None


def _round2(x: float) -> float:
    # Mitigate binary float rounding issues
    return round(x + 1e-12, 2)


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load inputs
    logs_path = workspace / "input" / "training_logs.csv"
    html_path = workspace / "input" / "risk_guidelines.html"
    cfg_path = workspace / "input" / "config.yaml"

    logs_rows = _load_csv_dicts(logs_path)
    html_text = _read_text(html_path)
    input_cfg = _load_yaml_minimal(cfg_path)

    if logs_rows is None or html_text is None or input_cfg is None:
        return None

    # Extract multipliers mapping from HTML
    mapping = _parse_html_multipliers(html_text)
    if mapping is None:
        return None

    # Collect numeric series
    hr_values: List[float] = []
    throws_values_pos: List[float] = []
    parsed_rows: List[Dict[str, Any]] = []
    for row in logs_rows:
        try:
            session_id = _parse_int(row.get("session_id", ""))
            date_str = row.get("date", "")
            exercise_type = row.get("exercise_type", "")
            duration_min = _parse_int(row.get("duration_min", ""))
            avg_hr_bpm = _parse_int(row.get("avg_hr_bpm", ""))
            rpe = _parse_int(row.get("rpe_1_10", ""))
            throws_count = _parse_int(row.get("throws_count", ""))
        except Exception:
            return None
        if None in (session_id, duration_min, avg_hr_bpm, rpe, throws_count):
            return None
        parsed_row = {
            "session_id": session_id,
            "date": date_str,
            "exercise_type": exercise_type,
            "duration_min": duration_min,
            "avg_hr_bpm": avg_hr_bpm,
            "rpe_1_10": rpe,
            "throws_count": throws_count,
        }
        parsed_rows.append(parsed_row)
        hr_values.append(float(avg_hr_bpm))
        if throws_count > 0:
            throws_values_pos.append(float(throws_count))

    # Compute percentiles as specified (linear interpolation), rounded to nearest integer
    p_hr = float(input_cfg.get("risk", {}).get("hr_percentile", 0.85))
    p_thr = float(input_cfg.get("risk", {}).get("throws_percentile", 0.95))
    hr_percentile = _percentile_linear(hr_values, p_hr)
    thr_percentile = _percentile_linear(throws_values_pos, p_thr) if throws_values_pos else None
    if hr_percentile is None or thr_percentile is None:
        return None
    # Round to nearest integer
    high_hr_cut = int(round(hr_percentile))
    high_thr_cut = int(round(thr_percentile))

    # Build resolved config
    resolved_cfg = json.loads(json.dumps(input_cfg))  # deep copy via JSON
    if "risk" not in resolved_cfg or not isinstance(resolved_cfg["risk"], dict):
        return None
    resolved_cfg["risk"]["high_hr_cutoff_bpm"] = high_hr_cut
    resolved_cfg["risk"]["high_throws_cutoff"] = high_thr_cut

    # Compute per-session risk
    risk = resolved_cfg["risk"]
    rpe_weight = float(risk.get("rpe_weight", 1.0))
    hr_weight = float(risk.get("hr_weight", 1.0))
    throw_weight = float(risk.get("throw_weight", 1.0))
    alert_threshold = float(risk.get("alert_risk_score", 0.0))
    weekly_load_warning = float(risk.get("weekly_load_warning", 0.0))

    computed_sessions: List[Dict[str, Any]] = []
    for row in parsed_rows:
        ex_type = row["exercise_type"]
        M = float(mapping.get(ex_type, 1.0))
        base = (row["rpe_1_10"] * row["duration_min"]) * rpe_weight
        hr_component = max(0, row["avg_hr_bpm"] - high_hr_cut) * hr_weight
        throws_component = (row["throws_count"] / max(1, high_thr_cut)) * 100.0 * throw_weight
        risk_score = _round2((base + hr_component + throws_component) * M)
        hr_flag = row["avg_hr_bpm"] >= high_hr_cut
        throws_flag = row["throws_count"] >= high_thr_cut
        alert = (risk_score >= alert_threshold) or hr_flag or throws_flag
        computed_sessions.append({
            "session_id": row["session_id"],
            "date": row["date"],
            "exercise_type": ex_type,
            "avg_hr_bpm": row["avg_hr_bpm"],
            "throws_count": row["throws_count"],
            "guideline_multiplier": M,
            "risk_score": risk_score,
            "hr_flag": hr_flag,
            "throws_flag": throws_flag,
            "alert": alert,
            "duration_min": row["duration_min"],
            "rpe_1_10": row["rpe_1_10"],
        })

    # Top 10 sessions by risk_score descending, tie-breaker by session_id ascending for determinism
    computed_sessions_sorted = sorted(
        computed_sessions,
        key=lambda x: (-x["risk_score"], x["session_id"])
    )
    top10 = computed_sessions_sorted[:10]

    # Weekly summary
    # Monday as start of week (ISO-8601)
    weeks: Dict[str, Dict[str, Any]] = {}
    for sess in computed_sessions:
        try:
            d = datetime.strptime(sess["date"], "%Y-%m-%d").date()
        except Exception:
            return None
        ws = _weekday_monday_start(d)
        ws_key = ws.strftime("%Y-%m-%d")
        if ws_key not in weeks:
            weeks[ws_key] = {
                "week_start_date": ws_key,
                "total_sessions": 0,
                "total_throws": 0,
                "total_duration_min": 0,
                "rpe_values": [],
                "weekly_load": 0.0,
                "high_risk_sessions": [],
            }
        w = weeks[ws_key]
        w["total_sessions"] += 1
        w["total_throws"] += int(sess["throws_count"])
        w["total_duration_min"] += int(
            next((x["duration_min"] for x in parsed_rows if x["session_id"] == sess["session_id"]), 0)
        )
        w["rpe_values"].append(
            next((x["rpe_1_10"] for x in parsed_rows if x["session_id"] == sess["session_id"]), 0)
        )
        w["weekly_load"] += float(sess["risk_score"])
        if bool(sess["alert"]):
            w["high_risk_sessions"].append(sess["session_id"])

    weekly_summary: List[Dict[str, Any]] = []
    for ws_key, agg in weeks.items():
        rpe_vals = agg["rpe_values"]
        mean_rpe = round(sum(rpe_vals) / len(rpe_vals), 2) if rpe_vals else 0.0
        weekly_load = _round2(agg["weekly_load"])
        warn = weekly_load >= weekly_load_warning
        weekly_summary.append({
            "week_start_date": ws_key,
            "total_sessions": agg["total_sessions"],
            "total_throws": agg["total_throws"],
            "total_duration_min": agg["total_duration_min"],
            "mean_rpe": mean_rpe,
            "weekly_load": weekly_load,
            "high_risk_sessions": agg["high_risk_sessions"],
            "warn": warn,
        })

    # Sort weekly summary by week_start_date ascending for expected
    weekly_summary_sorted = sorted(weekly_summary, key=lambda x: x["week_start_date"])

    return {
        "mapping": mapping,
        "high_hr_cutoff_bpm": high_hr_cut,
        "high_throws_cutoff": high_thr_cut,
        "input_cfg": input_cfg,
        "resolved_cfg_expected": resolved_cfg,
        "top10": top10,
        "weekly_summary": weekly_summary_sorted,
    }


def _compare_dicts_except(d1: Dict[str, Any], d2: Dict[str, Any], except_paths: List[Tuple[str, ...]]) -> bool:
    """
    Compare two nested dicts for equality, ignoring values at specified paths (tuples of keys).
    """
    def set_path(d: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
        cur = d
        for key in path[:-1]:
            if key not in cur or not isinstance(cur[key], dict):
                return
            cur = cur[key]
        if path and path[-1] in cur:
            cur[path[-1]] = value

    import copy
    a = copy.deepcopy(d1)
    b = copy.deepcopy(d2)
    for p in except_paths:
        set_path(a, p, None)
        set_path(b, p, None)
    return a == b


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "guidelines_extracted_json_correct": 0.0,
        "thresholds_high_hr_cutoff_correct": 0.0,
        "thresholds_high_throws_cutoff_correct": 0.0,
        "config_resolved_values_correct": 0.0,
        "config_resolved_other_keys_preserved": 0.0,
        "top_risky_sessions_structure": 0.0,
        "top_risky_sessions_values": 0.0,
        "weekly_summary_structure": 0.0,
        "weekly_summary_values": 0.0,
    }

    # Compute expected artifacts from inputs
    expected = _compute_expected_from_inputs(workspace)
    # Paths to outputs
    guidelines_json_path = workspace / "output" / "derived" / "guidelines_extracted.json"
    resolved_cfg_path = workspace / "output" / "config.resolved.yaml"
    top_csv_path = workspace / "output" / "reports" / "top_risky_sessions.csv"
    weekly_json_path = workspace / "output" / "reports" / "weekly_summary.json"

    # If we cannot compute expected due to missing inputs or parse errors, all scores remain 0.0 gracefully.
    if expected is None:
        return scores

    # 1) Guidelines extracted JSON check
    mapping_expected: Dict[str, float] = expected["mapping"]
    mapping_actual = _load_json(guidelines_json_path)
    if isinstance(mapping_actual, dict):
        # Ensure keys exactly match and values are numeric
        try:
            keys_match = set(mapping_actual.keys()) == set(mapping_expected.keys())
            values_match = True
            if keys_match:
                for k, v in mapping_actual.items():
                    try:
                        vf = float(v)
                    except Exception:
                        values_match = False
                        break
                    ve = float(mapping_expected[k])
                    # exact numeric equality acceptable with small tolerance
                    if abs(vf - ve) > 1e-9:
                        values_match = False
                        break
            else:
                values_match = False
            if keys_match and values_match:
                scores["guidelines_extracted_json_correct"] = 1.0
        except Exception:
            pass

    # 2) Thresholds computed in resolved config
    resolved_cfg = _load_yaml_minimal(resolved_cfg_path)
    if isinstance(resolved_cfg, dict):
        risk_cfg = resolved_cfg.get("risk", {}) if isinstance(resolved_cfg.get("risk", {}), dict) else {}
        hh_actual = risk_cfg.get("high_hr_cutoff_bpm", None)
        ht_actual = risk_cfg.get("high_throws_cutoff", None)
        if isinstance(hh_actual, (int, float)) and int(hh_actual) == int(expected["high_hr_cutoff_bpm"]):
            scores["thresholds_high_hr_cutoff_correct"] = 1.0
        if isinstance(ht_actual, (int, float)) and int(ht_actual) == int(expected["high_throws_cutoff"]):
            scores["thresholds_high_throws_cutoff_correct"] = 1.0

        # Config resolved values correct: both thresholds filled and match expected
        if scores["thresholds_high_hr_cutoff_correct"] == 1.0 and scores["thresholds_high_throws_cutoff_correct"] == 1.0:
            scores["config_resolved_values_correct"] = 1.0

        # Other keys preserved: compare with input config ignoring the two thresholds
        input_cfg = expected["input_cfg"]
        same_other = _compare_dicts_except(
            input_cfg,
            resolved_cfg,
            except_paths=[("risk", "high_hr_cutoff_bpm"), ("risk", "high_throws_cutoff")]
        )
        if same_other:
            scores["config_resolved_other_keys_preserved"] = 1.0

    # 3) Top risky sessions CSV
    rows_csv = _load_csv_dicts(top_csv_path)
    if rows_csv is not None and len(rows_csv) > 0:
        # Structure: header columns must be exactly as specified
        header = list(rows_csv[0].keys())
        expected_header = [
            "session_id",
            "date",
            "exercise_type",
            "avg_hr_bpm",
            "throws_count",
            "guideline_multiplier",
            "risk_score",
            "hr_flag",
            "throws_flag",
            "alert",
        ]
        if header == expected_header:
            scores["top_risky_sessions_structure"] = 1.0

        # Values: compare with expected computed top10
        try:
            # Parse candidate rows into comparable structures
            cand_rows: List[Dict[str, Any]] = []
            for r in rows_csv:
                sid = _parse_int(r.get("session_id", ""))
                date_str = r.get("date", "")
                ex = r.get("exercise_type", "")
                hr = _parse_int(r.get("avg_hr_bpm", ""))
                thr = _parse_int(r.get("throws_count", ""))
                mul = _parse_float(r.get("guideline_multiplier", ""))
                rs = _parse_float(r.get("risk_score", ""))
                hr_flag = _safe_bool_from_str(r.get("hr_flag", ""))
                th_flag = _safe_bool_from_str(r.get("throws_flag", ""))
                alert = _safe_bool_from_str(r.get("alert", ""))
                cand_rows.append({
                    "session_id": sid,
                    "date": date_str,
                    "exercise_type": ex,
                    "avg_hr_bpm": hr,
                    "throws_count": thr,
                    "guideline_multiplier": mul,
                    "risk_score": None if rs is None else _round2(rs),
                    "hr_flag": hr_flag,
                    "throws_flag": th_flag,
                    "alert": alert,
                })
            # Must be top 10, ranked by risk_score desc
            top10_expected: List[Dict[str, Any]] = expected["top10"]
            # Ensure we only take top 10 candidate rows
            cand_top10 = cand_rows[:10]
            # Check order and values match expected exactly
            match_all = True
            if len(cand_top10) != len(top10_expected):
                match_all = False
            else:
                for i, (c, e) in enumerate(zip(cand_top10, top10_expected)):
                    # Compare session_id and risk_score must match expected order
                    if c["session_id"] != e["session_id"]:
                        match_all = False
                        break
                    # date, exercise_type
                    if c["date"] != e["date"] or c["exercise_type"] != e["exercise_type"]:
                        match_all = False
                        break
                    # avg_hr_bpm, throws_count
                    if c["avg_hr_bpm"] != e["avg_hr_bpm"] or c["throws_count"] != e["throws_count"]:
                        match_all = False
                        break
                    # guideline_multiplier
                    if c["guideline_multiplier"] is None or abs(c["guideline_multiplier"] - float(e["guideline_multiplier"])) > 1e-9:
                        match_all = False
                        break
                    # risk_score
                    if c["risk_score"] is None or abs(c["risk_score"] - float(e["risk_score"])) > 1e-9:
                        match_all = False
                        break
                    # flags
                    if c["hr_flag"] is None or c["throws_flag"] is None or c["alert"] is None:
                        match_all = False
                        break
                    if bool(c["hr_flag"]) != bool(e["hr_flag"]) or bool(c["throws_flag"]) != bool(e["throws_flag"]) or bool(c["alert"]) != bool(e["alert"]):
                        match_all = False
                        break
            # Additionally verify sorted by risk_score descending
            is_sorted_desc = True
            cand_scores = [cr["risk_score"] if isinstance(cr["risk_score"], (int, float)) else -float("inf") for cr in cand_top10]
            if any(cand_scores[i] < cand_scores[i+1] for i in range(len(cand_scores)-1)):
                is_sorted_desc = False
            if match_all and is_sorted_desc:
                scores["top_risky_sessions_values"] = 1.0
        except Exception:
            pass

    # 4) Weekly summary JSON
    weekly_actual = _load_json(weekly_json_path)
    if isinstance(weekly_actual, list):
        # Basic structure check: each item is dict with required keys and types
        required_keys = {
            "week_start_date",
            "total_sessions",
            "total_throws",
            "total_duration_min",
            "mean_rpe",
            "weekly_load",
            "high_risk_sessions",
            "warn",
        }
        structure_ok = True
        for item in weekly_actual:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if set(item.keys()) != required_keys:
                structure_ok = False
                break
            # Type checks
            if not isinstance(item["week_start_date"], str):
                structure_ok = False
                break
            if not isinstance(item["total_sessions"], int):
                structure_ok = False
                break
            if not isinstance(item["total_throws"], int):
                structure_ok = False
                break
            if not isinstance(item["total_duration_min"], int):
                structure_ok = False
                break
            if not (isinstance(item["mean_rpe"], (int, float))):
                structure_ok = False
                break
            if not (isinstance(item["weekly_load"], (int, float))):
                structure_ok = False
                break
            if not isinstance(item["high_risk_sessions"], list):
                structure_ok = False
                break
            if not isinstance(item["warn"], bool):
                structure_ok = False
                break
        if structure_ok:
            scores["weekly_summary_structure"] = 1.0

        # Values correctness: compare against expected by mapping week_start_date
        try:
            expected_weeks: List[Dict[str, Any]] = expected["weekly_summary"]
            exp_map = {w["week_start_date"]: w for w in expected_weeks}
            act_map = {w["week_start_date"]: w for w in weekly_actual if isinstance(w, dict) and "week_start_date" in w}
            match_vals = True
            if set(exp_map.keys()) != set(act_map.keys()):
                match_vals = False
            else:
                for wk, e in exp_map.items():
                    a = act_map[wk]
                    # Compare numeric values with exactness for ints and rounding for floats
                    if a["total_sessions"] != e["total_sessions"]:
                        match_vals = False
                        break
                    if a["total_throws"] != e["total_throws"]:
                        match_vals = False
                        break
                    if a["total_duration_min"] != e["total_duration_min"]:
                        match_vals = False
                        break
                    # mean_rpe rounded to 2 decimals
                    if round(float(a["mean_rpe"]), 2) != round(float(e["mean_rpe"]), 2):
                        match_vals = False
                        break
                    if _round2(float(a["weekly_load"])) != _round2(float(e["weekly_load"])):
                        match_vals = False
                        break
                    # high_risk_sessions list equality (order can differ, not specified)
                    if sorted(a["high_risk_sessions"]) != sorted(e["high_risk_sessions"]):
                        match_vals = False
                        break
                    if bool(a["warn"]) != bool(e["warn"]):
                        match_vals = False
                        break
            if match_vals:
                scores["weekly_summary_values"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()