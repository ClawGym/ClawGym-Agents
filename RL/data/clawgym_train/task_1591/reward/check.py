import json
import csv
import math
import subprocess
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_float(x):
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() in {"nan", "none"}:
            return float("nan")
        return float(s)
    except Exception:
        return float("nan")


def _parse_csv(path: Path):
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(r) for r in reader]
        return header, rows
    except Exception:
        return None, None


def _parse_simple_yaml(path: Path):
    """
    Minimal parser for the provided config/scoring.yaml structure.
    Supports:
      top-level keys: weights: {key: value}, filters: {key: value}, top_n: int/float
    Assumes no lists, no special YAML features, indentation by spaces.
    """
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    data = {}
    current_map_key = None
    for raw in content:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        # detect indentation
        if not line.startswith(" "):  # top-level
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if val == "":
                    # start of nested mapping
                    current_map_key = key
                    data[key] = {}
                else:
                    # scalar at top level
                    data[key] = _parse_yaml_scalar(val)
                    current_map_key = None
        else:
            # inside a mapping (weights or filters)
            if current_map_key is None:
                # unsupported structure
                continue
            stripped = line.strip()
            if ":" not in stripped:
                continue
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip()
            data[current_map_key][k] = _parse_yaml_scalar(v)
    return data


def _parse_yaml_scalar(val: str):
    # Try to parse as int, then float, else strip quotes
    v = val.strip()
    if v == "":
        return ""
    if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
        return v[1:-1]
    try:
        if "." not in v and "e" not in v.lower():
            i = int(v)
            return i
    except Exception:
        pass
    try:
        return float(v)
    except Exception:
        return v


def _annualized_sharpe(avg_daily_return: float, std_daily_return: float) -> float:
    # Match scripts/metrics.py formula
    if std_daily_return <= 0:
        return 0.0
    return math.sqrt(252.0) * (avg_daily_return / std_daily_return)


def _cagr_from_avg_daily(avg_daily_return: float) -> float:
    # Match scripts/metrics.py formula
    return (1.0 + avg_daily_return) ** 252.0 - 1.0


def _calmar_ratio(cagr: float, max_drawdown: float) -> float:
    # Match scripts/metrics.py formula
    if max_drawdown <= 0:
        return 0.0
    return cagr / max_drawdown


def _compute_expected(stats_rows, config):
    weights = config.get("weights", {}) if config else {}
    filters = config.get("filters", {}) if config else {}
    top_n = int(config.get("top_n", 0)) if config else 0

    expected = []
    rejected = []
    for r in stats_rows:
        try:
            avg = _safe_float(r.get("avg_daily_return"))
            sd = _safe_float(r.get("std_daily_return"))
            td = int(float(r.get("trading_days")))
            mdd = _safe_float(r.get("max_drawdown"))
            ntr = int(float(r.get("n_trades")))
            exp = _safe_float(r.get("exposure"))
        except Exception:
            # Malformed row; treat as rejected with generic reason
            rej = {
                "strategy_id": r.get("strategy_id", ""),
                "strategy_name": r.get("strategy_name", ""),
                "variant": r.get("variant", ""),
                "reasons": ["malformed_row"],
            }
            rejected.append(rej)
            continue

        sharpe = _annualized_sharpe(avg, sd)
        cagr = _cagr_from_avg_daily(avg)
        calmar = _calmar_ratio(cagr, mdd)

        w_sh = _safe_float(weights.get("sharpe"))
        w_cagr = _safe_float(weights.get("cagr"))
        w_calmar = _safe_float(weights.get("calmar"))
        w_mdd = _safe_float(weights.get("max_drawdown"))

        # Composite score per formula
        comp = w_sh * sharpe + w_cagr * cagr + w_calmar * calmar + w_mdd * mdd

        # Filters
        reasons = []
        mt = filters.get("min_trades")
        if mt is not None and ntr < float(mt):
            reasons.append(f"n_trades<{int(mt) if isinstance(mt, int) or (isinstance(mt, float) and mt.is_integer()) else mt}")
        mdd_max = filters.get("max_drawdown")
        if mdd_max is not None and mdd > float(mdd_max):
            reasons.append(f"max_drawdown>{_format_num(mdd_max)}")
        min_exp = filters.get("min_exposure")
        if min_exp is not None and exp < float(min_exp):
            reasons.append(f"exposure<{_format_num(min_exp)}")
        max_exp = filters.get("max_exposure")
        if max_exp is not None and exp > float(max_exp):
            reasons.append(f"exposure>{_format_num(max_exp)}")
        msd = filters.get("min_sample_days")
        if msd is not None and td < float(msd):
            reasons.append(f"trading_days<{int(msd) if isinstance(msd, int) or (isinstance(msd, float) and msd.is_integer()) else msd}")

        rec = {
            "strategy_id": r.get("strategy_id", ""),
            "strategy_name": r.get("strategy_name", ""),
            "variant": r.get("variant", ""),
            "avg_daily_return": avg,
            "std_daily_return": sd,
            "trading_days": td,
            "max_drawdown": mdd,
            "n_trades": ntr,
            "exposure": exp,
            "sharpe": sharpe,
            "cagr": cagr,
            "calmar": calmar,
            "composite_score": comp,
        }
        if reasons:
            rec_rej = {
                "strategy_id": rec["strategy_id"],
                "strategy_name": rec["strategy_name"],
                "variant": rec["variant"],
                "reasons": reasons,
            }
            rejected.append(rec_rej)
        else:
            expected.append(rec)

    # Sort passing strategies by composite desc; tie-breakers
    expected_sorted = sorted(
        expected,
        key=lambda x: (
            -x["composite_score"],
            -x["sharpe"],
            x["max_drawdown"],
            -x["n_trades"],
        ),
    )

    # Apply top_n
    if top_n and top_n > 0 and len(expected_sorted) > top_n:
        expected_top = expected_sorted[:top_n]
    else:
        expected_top = expected_sorted

    return expected_top, expected_sorted, rejected, top_n


def _format_num(x):
    # keep canonical string for thresholds in reasons
    try:
        if isinstance(x, int):
            return str(x)
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        s = str(x)
        return s
    except Exception:
        return str(x)


def _isclose(a, b, rel=1e-6, abs_tol=1e-6):
    try:
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_tol)
    except Exception:
        return False


def _normalize_reasons(s: str):
    if s is None:
        return []
    # Split by comma and strip spaces
    parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    return parts


def _check_imports_metrics_module(path: Path) -> float:
    if not path.exists():
        return 0.0
    try:
        text = _read_text(path)
        text_low = text.lower()
        has_import = ("from scripts.metrics import" in text) or ("import scripts.metrics" in text_low)
        # also check usage of functions
        has_func_names = ("annualized_sharpe" in text) and ("cagr_from_avg_daily" in text) and ("calmar_ratio" in text)
        return 1.0 if (has_import and has_func_names) else 0.0
    except Exception:
        return 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cli_runs_successfully": 0.0,
        "leaderboard_exists_and_columns": 0.0,
        "leaderboard_topn_and_ranking_correct": 0.0,
        "leaderboard_metrics_and_scores_correct": 0.0,
        "rejected_exists_and_columns": 0.0,
        "rejected_reasons_correct": 0.0,
        "report_contains_formula": 0.0,
        "report_contains_filters": 0.0,
        "report_contains_counts": 0.0,
        "imports_metrics_module": 0.0,
    }

    # Load inputs to compute expected
    stats_path = workspace / "input" / "strategy_stats.csv"
    config_path = workspace / "config" / "scoring.yaml"

    stats_header, stats_rows = _parse_csv(stats_path)
    config = _parse_simple_yaml(config_path)

    expected_top, expected_all, expected_rej, top_n = ([], [], [], 0)
    can_compute_expected = False
    if stats_header is not None and stats_rows is not None and config is not None:
        try:
            expected_top, expected_all, expected_rej, top_n = _compute_expected(stats_rows, config)
            can_compute_expected = True
        except Exception:
            can_compute_expected = False

    # Check CLI runs successfully
    rank_script = workspace / "scripts" / "rank_strategies.py"
    if rank_script.exists():
        try:
            tmp_out_dir = workspace / ".grader_tmp_outputs"
            tmp_out_dir.mkdir(exist_ok=True, parents=True)
            out_lb = tmp_out_dir / "leaderboard.csv"
            out_rej = tmp_out_dir / "rejected.csv"
            out_rep = tmp_out_dir / "architecture.md"
            cmd = [
                sys.executable,
                str(rank_script),
                "--stats",
                str(stats_path),
                "--config",
                str(config_path),
                "--out",
                str(out_lb),
                "--rejected",
                str(out_rej),
                "--report",
                str(out_rep),
            ]
            result = subprocess.run(cmd, cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if result.returncode == 0 and out_lb.exists() and out_rej.exists() and out_rep.exists():
                scores["cli_runs_successfully"] = 1.0
            else:
                scores["cli_runs_successfully"] = 0.0
        except Exception:
            scores["cli_runs_successfully"] = 0.0
    else:
        scores["cli_runs_successfully"] = 0.0

    # Check imports of metrics module in rank_strategies.py
    scores["imports_metrics_module"] = _check_imports_metrics_module(rank_script)

    # Validate leaderboard.csv
    leaderboard_path = workspace / "output" / "leaderboard.csv"
    lb_header, lb_rows = _parse_csv(leaderboard_path)
    expected_lb_columns = [
        "rank",
        "strategy_id",
        "strategy_name",
        "variant",
        "sharpe",
        "cagr",
        "calmar",
        "max_drawdown",
        "n_trades",
        "exposure",
        "composite_score",
    ]
    if lb_header is not None and lb_rows is not None:
        if lb_header == expected_lb_columns:
            scores["leaderboard_exists_and_columns"] = 1.0
        else:
            scores["leaderboard_exists_and_columns"] = 0.0
    else:
        scores["leaderboard_exists_and_columns"] = 0.0

    # Validate ranking order and top_n
    if can_compute_expected and lb_rows is not None:
        # Check number of rows and strategy_id order
        expected_count = len(expected_top)
        actual_count = len(lb_rows)
        correct_count = (expected_count == actual_count)
        correct_order = True
        correct_ranks = True
        for idx, row in enumerate(lb_rows):
            # Check rank sequence
            try:
                rank_val = int(float(row.get("rank", "0")))
                if rank_val != idx + 1:
                    correct_ranks = False
            except Exception:
                correct_ranks = False
            exp = expected_top[idx] if idx < len(expected_top) else None
            if exp is None:
                correct_order = False
                continue
            if row.get("strategy_id", "") != exp["strategy_id"]:
                correct_order = False
        if correct_count and correct_order and correct_ranks:
            scores["leaderboard_topn_and_ranking_correct"] = 1.0
        else:
            scores["leaderboard_topn_and_ranking_correct"] = 0.0
    else:
        scores["leaderboard_topn_and_ranking_correct"] = 0.0

    # Validate leaderboard metrics and composite values
    if can_compute_expected and lb_rows is not None and lb_header == expected_lb_columns:
        metrics_ok = True
        for idx, row in enumerate(lb_rows):
            if idx >= len(expected_top):
                metrics_ok = False
                break
            exp = expected_top[idx]
            try:
                # parse floats
                sharpe = _safe_float(row.get("sharpe"))
                cagr = _safe_float(row.get("cagr"))
                calmar = _safe_float(row.get("calmar"))
                mdd = _safe_float(row.get("max_drawdown"))
                ntr = int(float(row.get("n_trades")))
                expv = _safe_float(row.get("exposure"))
                comp = _safe_float(row.get("composite_score"))
            except Exception:
                metrics_ok = False
                break
            # Tolerance comparisons
            if not _isclose(sharpe, exp["sharpe"], rel=1e-4, abs_tol=1e-4):
                metrics_ok = False
                break
            if not _isclose(cagr, exp["cagr"], rel=1e-4, abs_tol=1e-4):
                metrics_ok = False
                break
            if not _isclose(calmar, exp["calmar"], rel=1e-4, abs_tol=1e-4):
                metrics_ok = False
                break
            if not _isclose(mdd, exp["max_drawdown"], rel=1e-6, abs_tol=1e-6):
                metrics_ok = False
                break
            if ntr != exp["n_trades"]:
                metrics_ok = False
                break
            if not _isclose(expv, exp["exposure"], rel=1e-6, abs_tol=1e-6):
                metrics_ok = False
                break
            if not _isclose(comp, exp["composite_score"], rel=1e-4, abs_tol=1e-4):
                metrics_ok = False
                break
        scores["leaderboard_metrics_and_scores_correct"] = 1.0 if metrics_ok else 0.0
    else:
        scores["leaderboard_metrics_and_scores_correct"] = 0.0

    # Validate rejected.csv
    rejected_path = workspace / "output" / "rejected.csv"
    rej_header, rej_rows = _parse_csv(rejected_path)
    expected_rej_columns = ["strategy_id", "strategy_name", "variant", "reasons"]
    if rej_header is not None and rej_rows is not None and rej_header == expected_rej_columns:
        scores["rejected_exists_and_columns"] = 1.0
    else:
        scores["rejected_exists_and_columns"] = 0.0

    if can_compute_expected and rej_rows is not None and rej_header == expected_rej_columns:
        # Build map by strategy_id
        actual_map = {r.get("strategy_id", ""): r for r in rej_rows}
        expected_map = {r["strategy_id"]: r for r in expected_rej}
        # Check counts match
        reasons_ok = True
        if len(actual_map) != len(expected_map):
            reasons_ok = False
        else:
            for sid, exp in expected_map.items():
                ar = actual_map.get(sid)
                if ar is None:
                    reasons_ok = False
                    break
                actual_reasons = _normalize_reasons(ar.get("reasons", ""))
                # Normalize numbers for comparison (keep as strings)
                # Expected reasons are already formatted strings
                if set(actual_reasons) != set(exp["reasons"]):
                    reasons_ok = False
                    break
                # Check basic identity fields
                if ar.get("strategy_name", "") != exp["strategy_name"] or ar.get("variant", "") != exp["variant"]:
                    reasons_ok = False
                    break
        scores["rejected_reasons_correct"] = 1.0 if reasons_ok else 0.0
    else:
        scores["rejected_reasons_correct"] = 0.0

    # Validate architecture.md
    report_path = workspace / "output" / "architecture.md"
    report_text = _read_text(report_path)
    if report_text:
        # Formula check: ensure weights paired with metric names and mention of score/composite
        text_low = report_text.lower()
        has_score_word = ("score" in text_low) or ("composite" in text_low)
        weights = config.get("weights", {}) if config else {}
        w_checks = []
        # Check each weight appears on same line as metric name
        lines = report_text.splitlines()
        def _line_has(line, metric_key, weight_val):
            # Accept numeric repr possibly as int or float string
            met = metric_key.lower()
            if met not in line.lower():
                return False
            # Check weight presence in either exact str or simplified format
            sv = _format_num(weight_val)
            # Because floats may be formatted differently, also allow close numeric in line
            if sv in line:
                return True
            # Try to detect presence of numeric value with tolerance by extracting numbers
            nums = _extract_numbers_from_text(line)
            try:
                wv = float(weight_val)
                for n in nums:
                    if math.isclose(n, wv, rel_tol=1e-3, abs_tol=1e-3):
                        return True
            except Exception:
                pass
            return False

        if config is not None:
            w_checks.append(any(_line_has(l, "sharpe", weights.get("sharpe")) for l in lines))
            w_checks.append(any(_line_has(l, "cagr", weights.get("cagr")) for l in lines))
            w_checks.append(any(_line_has(l, "calmar", weights.get("calmar")) for l in lines))
            w_checks.append(any(_line_has(l, "max_drawdown", weights.get("max_drawdown")) for l in lines))
        formula_ok = has_score_word and all(w_checks)
        scores["report_contains_formula"] = 1.0 if formula_ok else 0.0

        # Filters check: ensure thresholds mentioned
        filt_ok = False
        if config is not None and "filters" in config:
            filt = config["filters"]
            need = [
                ("min_trades", filt.get("min_trades")),
                ("max_drawdown", filt.get("max_drawdown")),
                ("min_exposure", filt.get("min_exposure")),
                ("max_exposure", filt.get("max_exposure")),
                ("min_sample_days", filt.get("min_sample_days")),
            ]
            cnt = 0
            for key, val in need:
                if val is None:
                    continue
                if (key in text_low) and _num_appears_in_text(report_text, float(val)):
                    cnt += 1
            # All five filters must be present
            filt_ok = cnt == len([x for x in need if x[1] is not None])
        scores["report_contains_filters"] = 1.0 if filt_ok else 0.0

        # Counts of passed vs rejected
        counts_ok = False
        if can_compute_expected:
            passed_n = len(expected_all)
            rejected_n = len(expected_rej)
            # check both numbers appear in context with words pass/reject
            # We'll just ensure both numbers appear and both keywords appear
            numbers_present = (str(passed_n) in report_text) and (str(rejected_n) in report_text)
            words_present = (("pass" in text_low) or ("passed" in text_low)) and ("reject" in text_low)
            counts_ok = numbers_present and words_present
        scores["report_contains_counts"] = 1.0 if counts_ok else 0.0
    else:
        scores["report_contains_formula"] = 0.0
        scores["report_contains_filters"] = 0.0
        scores["report_contains_counts"] = 0.0

    # Ensure all scores are floats in [0,1]
    for k, v in list(scores.items()):
        try:
            fv = float(v)
            if fv < 0.0:
                fv = 0.0
            if fv > 1.0:
                fv = 1.0
            scores[k] = fv
        except Exception:
            scores[k] = 0.0

    return scores


def _extract_numbers_from_text(s: str):
    nums = []
    cur = ""
    dot_seen = False
    sign_seen = False
    for ch in s:
        if ch in "+-" and not sign_seen and (not cur or cur == ""):
            cur += ch
            sign_seen = True
        elif ch.isdigit():
            cur += ch
        elif ch == "." and not dot_seen:
            cur += ch
            dot_seen = True
        else:
            if any(c.isdigit() for c in cur):
                try:
                    nums.append(float(cur))
                except Exception:
                    pass
            cur = ""
            dot_seen = False
            sign_seen = False
    if any(c.isdigit() for c in cur):
        try:
            nums.append(float(cur))
        except Exception:
            pass
    return nums


def _num_appears_in_text(text: str, value: float) -> bool:
    nums = _extract_numbers_from_text(text)
    for n in nums:
        try:
            if math.isclose(n, float(value), rel_tol=1e-3, abs_tol=1e-3):
                return True
        except Exception:
            pass
    return False


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()