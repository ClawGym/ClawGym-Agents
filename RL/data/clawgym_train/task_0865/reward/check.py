import sys
import json
import csv
import math
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Parse a simple YAML with top-level scalar key: value pairs.
    Supports quoted strings and numeric values.
    """
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            return None
        # Remove surrounding quotes for strings
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            unq = val[1:-1]
            data[key] = unq
        else:
            # Try int, then float, else raw string
            try:
                data[key] = int(val)
            except ValueError:
                try:
                    data[key] = float(val)
                except ValueError:
                    data[key] = val
    return data


def _time_to_minutes(hhmm: str) -> Optional[int]:
    try:
        parts = hhmm.strip().split(":")
        if len(parts) != 2:
            return None
        h = int(parts[0])
        m = int(parts[1])
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
        return h * 60 + m
    except Exception:
        return None


def _load_commute_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required_cols = {"date", "weekday", "mode", "depart", "arrive", "cost_usd"}
            # Strict exact match of header set
            if set(reader.fieldnames or []) != required_cols:
                return None
            for row in reader:
                mode = (row.get("mode") or "").strip()
                depart = (row.get("depart") or "").strip()
                arrive = (row.get("arrive") or "").strip()
                cost_str = (row.get("cost_usd") or "").strip()
                dep_min = _time_to_minutes(depart)
                arr_min = _time_to_minutes(arrive)
                if dep_min is None or arr_min is None:
                    return None
                if arr_min < dep_min:
                    return None
                try:
                    cost = float(cost_str)
                except Exception:
                    return None
                duration = float(arr_min - dep_min)
                rows.append(
                    {
                        "mode": mode,
                        "depart_min": dep_min,
                        "arrive_min": arr_min,
                        "duration_min": duration,
                        "cost_usd": cost,
                    }
                )
        return rows
    except Exception:
        return None


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    vs = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return float(vs[mid])
    else:
        return (vs[mid - 1] + vs[mid]) / 2.0


def _percentile_nearest_rank(values: List[float], p: float) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    vs = sorted(values)
    rank = int(math.ceil(p * n))
    rank = max(1, min(rank, n))
    return float(vs[rank - 1])


def _float_close(a: Any, b: Any, tol: float) -> bool:
    try:
        af = float(a)
        bf = float(b)
    except Exception:
        return False
    return abs(af - bf) <= tol


def _compute_expected(rows: List[Dict[str, Any]], prefs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        target_arrival_str = str(prefs["target_arrival_time"])
        target_arrival_min = _time_to_minutes(target_arrival_str)
        workdays_per_month = int(prefs["workdays_per_month"])
        monthly_budget_usd = float(prefs["monthly_budget_usd"])
        required_on_time_rate = float(prefs["required_on_time_rate"])
        if target_arrival_min is None:
            return None

        by_mode: Dict[str, Dict[str, Any]] = {}
        modes = sorted({r["mode"] for r in rows})
        for mode in modes:
            mrows = [r for r in rows if r["mode"] == mode]
            durations = [r["duration_min"] for r in mrows]
            costs = [r["cost_usd"] for r in mrows]
            count = len(mrows)
            if count == 0:
                continue
            avg_duration = sum(durations) / count
            med_duration = _median(durations)
            p90_duration = _percentile_nearest_rank(durations, 0.9)
            on_time = sum(1 for r in mrows if r["arrive_min"] <= target_arrival_min)
            on_time_rate = on_time / count if count > 0 else 0.0
            avg_cost = sum(costs) / count
            monthly_cost_estimate = avg_cost * 2.0 * workdays_per_month
            by_mode[mode] = {
                "count": count,
                "avg_duration_min": avg_duration,
                "median_duration_min": med_duration,
                "p90_duration_min": p90_duration,
                "avg_one_way_cost_usd": avg_cost,
                "monthly_cost_estimate_usd": monthly_cost_estimate,
                "on_time_rate": on_time_rate,
            }

        qualifiers: List[Tuple[str, float]] = []  # (mode, avg_duration_min)
        non_qualifiers: List[Tuple[str, float, float]] = []  # (mode, on_time_rate, avg_duration_min)
        for mode, stats in by_mode.items():
            meets_reliability = stats["on_time_rate"] >= required_on_time_rate
            meets_budget = stats["monthly_cost_estimate_usd"] <= monthly_budget_usd
            if meets_reliability and meets_budget:
                qualifiers.append((mode, stats["avg_duration_min"]))
            else:
                non_qualifiers.append((mode, stats["on_time_rate"], stats["avg_duration_min"]))

        if qualifiers:
            qualifiers.sort(key=lambda x: (x[1], x[0]))
            recommended = qualifiers[0][0]
        else:
            if not non_qualifiers:
                return None
            non_qualifiers.sort(key=lambda x: (-x[1], x[2], x[0]))
            recommended = non_qualifiers[0][0]

        return {
            "by_mode": by_mode,
            "target_arrival_time": target_arrival_str,
            "workdays_per_month": workdays_per_month,
            "recommended_mode": recommended,
        }
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_json_exists_and_parseable": 0.0,
        "summary_top_level_keys_exact": 0.0,
        "modes_covered_correct": 0.0,
        "mode_field_keys_exact": 0.0,
        "counts_correct": 0.0,
        "avg_duration_min_correct": 0.0,
        "median_duration_min_correct": 0.0,
        "p90_duration_min_correct": 0.0,
        "avg_cost_correct": 0.0,
        "monthly_cost_estimate_correct": 0.0,
        "on_time_rate_correct": 0.0,
        "target_and_workdays_correct": 0.0,
        "recommended_mode_correct": 0.0,
        "markdown_block_present_and_replaced": 0.0,
        "markdown_keys_and_order_correct": 0.0,
        "markdown_values_match_json": 0.0,
    }

    csv_path = workspace / "input" / "commute_log.csv"
    yaml_path = workspace / "input" / "preferences.yaml"
    md_path = workspace / "docs" / "lifestyle_goals.md"
    json_path = workspace / "output" / "commute_summary.json"

    rows = _load_commute_csv(csv_path)
    prefs = _parse_simple_yaml(yaml_path)
    out_json = _load_json(json_path)

    if out_json is not None and isinstance(out_json, dict):
        scores["summary_json_exists_and_parseable"] = 1.0

    expected = None
    if rows is not None and prefs is not None:
        expected = _compute_expected(rows, prefs)

    # Top-level JSON keys exact
    if isinstance(out_json, dict):
        expected_top = {"by_mode", "target_arrival_time", "workdays_per_month", "recommended_mode"}
        if set(out_json.keys()) == expected_top:
            scores["summary_top_level_keys_exact"] = 1.0

    # Modes and per-mode field keys
    if isinstance(out_json, dict) and isinstance(out_json.get("by_mode"), dict):
        by_mode_out = out_json["by_mode"]
        modes_out = set(by_mode_out.keys())
        if rows is not None:
            modes_expected = set(r["mode"] for r in rows)
            if modes_out == modes_expected:
                scores["modes_covered_correct"] = 1.0
        required_fields = {
            "count",
            "avg_duration_min",
            "median_duration_min",
            "p90_duration_min",
            "avg_one_way_cost_usd",
            "monthly_cost_estimate_usd",
            "on_time_rate",
        }
        fields_ok = True
        if by_mode_out:
            for mode, stats in by_mode_out.items():
                if not isinstance(stats, dict) or set(stats.keys()) != required_fields:
                    fields_ok = False
                    break
            if fields_ok:
                scores["mode_field_keys_exact"] = 1.0

    # Target and workdays check
    if expected is not None and isinstance(out_json, dict):
        ta_ok = out_json.get("target_arrival_time") == expected.get("target_arrival_time")
        wd_val = out_json.get("workdays_per_month")
        try:
            wd_ok = int(wd_val) == int(expected.get("workdays_per_month"))
        except Exception:
            wd_ok = False
        if ta_ok and wd_ok:
            scores["target_and_workdays_correct"] = 1.0

    # Per-mode metrics checks
    if expected is not None and isinstance(out_json, dict) and isinstance(out_json.get("by_mode"), dict):
        by_mode_out = out_json["by_mode"]
        by_mode_exp = expected["by_mode"]
        if set(by_mode_out.keys()) == set(by_mode_exp.keys()):
            counts_ok = True
            avg_dur_ok = True
            med_dur_ok = True
            p90_dur_ok = True
            avg_cost_ok = True
            monthly_cost_ok = True
            on_time_ok = True

            for mode in by_mode_exp.keys():
                out_stats = by_mode_out.get(mode, {})
                exp_stats = by_mode_exp.get(mode, {})
                # count
                try:
                    out_count = int(out_stats.get("count"))
                    exp_count = int(exp_stats.get("count"))
                    if out_count != exp_count:
                        counts_ok = False
                except Exception:
                    counts_ok = False
                # Avg duration
                if not _float_close(out_stats.get("avg_duration_min"), exp_stats.get("avg_duration_min"), 0.5):
                    avg_dur_ok = False
                # Median
                if not _float_close(out_stats.get("median_duration_min"), exp_stats.get("median_duration_min"), 0.5):
                    med_dur_ok = False
                # p90
                if not _float_close(out_stats.get("p90_duration_min"), exp_stats.get("p90_duration_min"), 0.5):
                    p90_dur_ok = False
                # Avg cost
                if not _float_close(out_stats.get("avg_one_way_cost_usd"), exp_stats.get("avg_one_way_cost_usd"), 0.01):
                    avg_cost_ok = False
                # Monthly
                if not _float_close(out_stats.get("monthly_cost_estimate_usd"), exp_stats.get("monthly_cost_estimate_usd"), 0.01):
                    monthly_cost_ok = False
                # On-time rate
                if not _float_close(out_stats.get("on_time_rate"), exp_stats.get("on_time_rate"), 0.01):
                    on_time_ok = False

            if counts_ok:
                scores["counts_correct"] = 1.0
            if avg_dur_ok:
                scores["avg_duration_min_correct"] = 1.0
            if med_dur_ok:
                scores["median_duration_min_correct"] = 1.0
            if p90_dur_ok:
                scores["p90_duration_min_correct"] = 1.0
            if avg_cost_ok:
                scores["avg_cost_correct"] = 1.0
            if monthly_cost_ok:
                scores["monthly_cost_estimate_correct"] = 1.0
            if on_time_ok:
                scores["on_time_rate_correct"] = 1.0

    # Recommended mode check
    if expected is not None and isinstance(out_json, dict):
        if out_json.get("recommended_mode") == expected.get("recommended_mode"):
            scores["recommended_mode_correct"] = 1.0

    # Markdown checks
    md_text = _read_text(md_path)
    md_block_ok = False
    md_order_ok = False
    md_values_ok = False
    if md_text is not None:
        start_marker = "<!-- COMMUTE_PLAN_START -->"
        end_marker = "<!-- COMMUTE_PLAN_END -->"
        start_idx = md_text.find(start_marker)
        end_idx = md_text.find(end_marker)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content_between = md_text[start_idx + len(start_marker):end_idx]
            if "TBD" not in content_between:
                md_block_ok = True
            lines = [ln.strip() for ln in content_between.strip().splitlines() if ln.strip()]
            required_order = [
                "recommended_mode",
                "avg_duration_min",
                "median_duration_min",
                "p90_duration_min",
                "monthly_cost_estimate_usd",
                "on_time_rate",
            ]
            parsed: Dict[str, str] = {}
            keys_in_order: List[str] = []
            fmt_ok = True
            if len(lines) == 6:
                for ln in lines:
                    if ":" not in ln:
                        fmt_ok = False
                        break
                    k, v = ln.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    parsed[k] = v
                    keys_in_order.append(k)
                if fmt_ok and keys_in_order == required_order:
                    md_order_ok = True

            if md_order_ok and isinstance(out_json, dict) and isinstance(out_json.get("by_mode"), dict):
                rec_mode = parsed.get("recommended_mode", "")
                if rec_mode == out_json.get("recommended_mode") and rec_mode in out_json.get("by_mode", {}):
                    stats = out_json["by_mode"][rec_mode]

                    def to_float(s: str) -> Optional[float]:
                        try:
                            return float(s)
                        except Exception:
                            return None

                    avg_d_md = to_float(parsed.get("avg_duration_min", ""))
                    med_d_md = to_float(parsed.get("median_duration_min", ""))
                    p90_d_md = to_float(parsed.get("p90_duration_min", ""))
                    m_cost_md = to_float(parsed.get("monthly_cost_estimate_usd", ""))
                    on_time_md = to_float(parsed.get("on_time_rate", ""))

                    checks = [
                        avg_d_md is not None and _float_close(avg_d_md, stats.get("avg_duration_min"), 0.5),
                        med_d_md is not None and _float_close(med_d_md, stats.get("median_duration_min"), 0.5),
                        p90_d_md is not None and _float_close(p90_d_md, stats.get("p90_duration_min"), 0.5),
                        m_cost_md is not None and _float_close(m_cost_md, stats.get("monthly_cost_estimate_usd"), 0.01),
                        on_time_md is not None and _float_close(on_time_md, stats.get("on_time_rate"), 0.01),
                    ]
                    if all(checks):
                        md_values_ok = True

    if md_block_ok:
        scores["markdown_block_present_and_replaced"] = 1.0
    if md_order_ok:
        scores["markdown_keys_and_order_correct"] = 1.0
    if md_values_ok:
        scores["markdown_values_match_json"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()