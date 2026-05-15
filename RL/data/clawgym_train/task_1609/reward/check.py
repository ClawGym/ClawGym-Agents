import os
import sys
import json
import csv
import hashlib
import math
from datetime import datetime

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def abspath(root, *parts):
    return os.path.join(root, *parts)

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def parse_float(x):
    try:
        v = float(x)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None

def clean_header_cell(s):
    if s is None:
        return ""
    s = str(s)
    # Remove BOM if present and strip whitespace, lowercase
    s = s.replace("\ufeff", "").strip().lower()
    return s

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def dates_strictly_increasing(date_list):
    # Try to parse as ISO or epoch; if fails, fallback to lexical comparison
    def parse_date(d):
        # strip whitespace
        s = str(d).strip()
        # Try ISO formats
        try:
            return ("dt", datetime.fromisoformat(s))
        except Exception:
            pass
        # Try common date-only format
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return ("dt", datetime.strptime(s, fmt))
            except Exception:
                continue
        # Try epoch seconds or milliseconds
        try:
            fv = float(s)
            # Heuristic: if too large, assume ms and convert to seconds
            if fv > 1e12:
                fv = fv / 1000.0
            return ("ts", fv)
        except Exception:
            pass
        # Fallback to string
        return ("str", s)

    parsed = [parse_date(d) for d in date_list]
    # Compare adjacent elements; if types differ, compare by string fallback on original
    for i in range(1, len(parsed)):
        t0, v0 = parsed[i-1]
        t1, v1 = parsed[i]
        if t0 != t1:
            # Fallback to string compare on original inputs
            s0 = str(date_list[i-1])
            s1 = str(date_list[i])
            if not (s1 > s0):
                return False
        else:
            if t0 == "dt":
                if not (v1 > v0):
                    return False
            elif t0 == "ts":
                if not (v1 > v0):
                    return False
            else:
                if not (v1 > v0):
                    return False
    return True

def is_finite_number(v):
    return isinstance(v, (int, float)) and math.isfinite(float(v))

def main():
    root = get_workspace_root()
    input_dir = abspath(root, "input")
    output_dir = abspath(root, "output")

    checks = {}

    # Manifest checks
    manifest_path = abspath(output_dir, "manifest.json")
    data_path = abspath(root, "input", "BTC-USD_1d.csv")

    checks["manifest_exists"] = False
    checks["manifest_valid_sha256"] = False
    checks["manifest_data_file_correct"] = False

    manifest = None
    if os.path.isfile(manifest_path):
        checks["manifest_exists"] = True
        manifest = read_json(manifest_path)
        if isinstance(manifest, dict):
            # Validate data_file key
            if manifest.get("data_file") == "input/BTC-USD_1d.csv":
                checks["manifest_data_file_correct"] = True
            # Validate sha256
            actual_sha = sha256_file(data_path)
            msha = manifest.get("data_sha256")
            if actual_sha is not None and isinstance(msha, str) and msha.lower() == actual_sha.lower():
                checks["manifest_valid_sha256"] = True

    # Strategy checks
    strategies = ["sma_crossover", "rsi_reversal", "momentum"]
    initial_capital = 10000.0

    # For leaderboard later
    leader_sharpes = {}
    leader_cagrs = {}
    leader_mdds = {}

    for strat in strategies:
        # Trades CSV
        tpath = abspath(output_dir, f"trades_{strat}.csv")
        th_key_exist = f"trades_{strat}_exists"
        th_key_hdr = f"trades_{strat}_header_valid"
        checks[th_key_exist] = False
        checks[th_key_hdr] = False

        if os.path.isfile(tpath):
            checks[th_key_exist] = True
            rows = read_csv_rows(tpath)
            if rows and len(rows) >= 1:
                header = [clean_header_cell(c) for c in rows[0]]
                expected = ["entry_time", "exit_time", "entry_price", "exit_price", "direction", "size", "pnl", "pnl_pct", "duration"]
                if header == expected:
                    checks[th_key_hdr] = True

        # Equity CSV
        epath = abspath(output_dir, f"equity_{strat}.csv")
        ek_exist = f"equity_{strat}_exists"
        ek_hdr = f"equity_{strat}_header_valid"
        ek_min = f"equity_{strat}_min_rows"
        ek_inc = f"equity_{strat}_dates_increasing"
        ek_num = f"equity_{strat}_numeric"
        checks[ek_exist] = False
        checks[ek_hdr] = False
        checks[ek_min] = False
        checks[ek_inc] = False
        checks[ek_num] = False

        last_equity_val = None
        equity_rows_ok = False

        if os.path.isfile(epath):
            checks[ek_exist] = True
            rows = read_csv_rows(epath)
            if rows and len(rows) >= 1:
                header = [clean_header_cell(c) for c in rows[0]]
                expected = ["date", "equity"]
                if header == expected:
                    checks[ek_hdr] = True
                data_rows = rows[1:] if rows else []
                if len(data_rows) >= 2:
                    checks[ek_min] = True
                if data_rows:
                    # Extract date and equity columns
                    dates = [r[0] if len(r) > 0 else "" for r in data_rows]
                    eq_vals = []
                    numerics_ok = True
                    for r in data_rows:
                        if len(r) < 2:
                            numerics_ok = False
                            break
                        v = parse_float(r[1])
                        if v is None:
                            numerics_ok = False
                            break
                        eq_vals.append(v)
                    if numerics_ok:
                        checks[ek_num] = True
                        last_equity_val = eq_vals[-1]
                    if len(dates) >= 2 and dates_strictly_increasing(dates):
                        checks[ek_inc] = True

        # Metrics JSON
        mpath = abspath(output_dir, f"metrics_{strat}.json")
        mk_exist = f"metrics_{strat}_exists"
        mk_keys = f"metrics_{strat}_keys_valid"
        mk_vals = f"metrics_{strat}_values_finite"
        mk_match_eq = f"metrics_{strat}_final_equity_matches_equity_csv"
        mk_match_ret = f"metrics_{strat}_final_equity_matches_total_return"
        checks[mk_exist] = False
        checks[mk_keys] = False
        checks[mk_vals] = False
        checks[mk_match_eq] = False
        checks[mk_match_ret] = False

        metrics = None
        if os.path.isfile(mpath):
            checks[mk_exist] = True
            metrics = read_json(mpath)
            required_keys = ["total_return_pct", "cagr_pct", "sharpe", "sortino", "max_drawdown_pct", "win_rate_pct", "profit_factor", "final_equity"]
            if isinstance(metrics, dict) and all(k in metrics for k in required_keys):
                checks[mk_keys] = True
                # Validate finite numeric values
                vals_ok = True
                for k in required_keys:
                    if not is_finite_number(metrics.get(k)):
                        vals_ok = False
                        break
                if vals_ok:
                    checks[mk_vals] = True
                    # Store for leaderboard
                    leader_sharpes[strat] = float(metrics.get("sharpe"))
                    leader_cagrs[strat] = float(metrics.get("cagr_pct"))
                    leader_mdds[strat] = float(metrics.get("max_drawdown_pct"))
                    # Compare final equity to last equity in equity CSV
                    if last_equity_val is not None:
                        if math.isclose(float(metrics["final_equity"]), float(last_equity_val), rel_tol=0.0, abs_tol=1e-6):
                            checks[mk_match_eq] = True
                    # Compare final equity to initial capital and total return pct
                    try:
                        expected_fe = initial_capital * (1.0 + float(metrics["total_return_pct"]) / 100.0)
                        if math.isclose(float(metrics["final_equity"]), expected_fe, rel_tol=1e-6, abs_tol=1e-12):
                            checks[mk_match_ret] = True
                    except Exception:
                        pass

    # Optimization checks
    opt_path = abspath(output_dir, "opt_results.csv")
    best_path = abspath(output_dir, "best_sma.json")

    checks["opt_results_exists"] = False
    checks["opt_results_columns_valid"] = False
    checks["opt_results_has_rows"] = False
    checks["best_sma_exists"] = False
    checks["best_sma_keys_valid"] = False
    checks["best_sma_matches_opt_results"] = False

    opt_rows = None
    opt_header = None
    if os.path.isfile(opt_path):
        checks["opt_results_exists"] = True
        opt_rows = read_csv_rows(opt_path)
        if opt_rows and len(opt_rows) >= 1:
            opt_header = [clean_header_cell(c) for c in opt_rows[0]]
            expected = ["fast_period", "slow_period", "sharpe", "total_return_pct", "max_drawdown_pct"]
            if opt_header == expected:
                checks["opt_results_columns_valid"] = True
            data_rows = opt_rows[1:] if opt_rows else []
            if len(data_rows) >= 1:
                checks["opt_results_has_rows"] = True

    best = None
    if os.path.isfile(best_path):
        checks["best_sma_exists"] = True
        best = read_json(best_path)
        if isinstance(best, dict) and all(k in best for k in ["fast_period", "slow_period", "sharpe", "total_return_pct"]):
            # Validate finite
            b_ok = True
            for k in ["fast_period", "slow_period", "sharpe", "total_return_pct"]:
                if not is_finite_number(best.get(k)):
                    b_ok = False
                    break
            if b_ok:
                checks["best_sma_keys_valid"] = True

    # Cross-check best vs opt_results
    if checks.get("opt_results_has_rows") and checks.get("best_sma_keys_valid"):
        # Build list of rows with parsed values
        data_rows = opt_rows[1:]
        parsed = []
        for r in data_rows:
            # Ensure row has enough columns
            if len(r) < 5:
                continue
            fp = parse_float(r[0])
            sp = parse_float(r[1])
            sh = parse_float(r[2])
            tr = parse_float(r[3])
            md = parse_float(r[4])
            if None in (fp, sp, sh, tr, md):
                continue
            parsed.append({
                "fast_period": int(round(fp)),
                "slow_period": int(round(sp)),
                "sharpe": float(sh),
                "total_return_pct": float(tr),
                "max_drawdown_pct": float(md),
            })
        # Verify best params appear in opt_results
        best_fp = int(round(float(best["fast_period"])))
        best_sp = int(round(float(best["slow_period"])))
        # Find rows matching best fast/slow
        matching = [row for row in parsed if row["fast_period"] == best_fp and row["slow_period"] == best_sp]
        if matching:
            # Determine the correct best by max sharpe, tie-breaker total_return_pct
            finite_rows = [row for row in parsed if is_finite_number(row["sharpe"]) and is_finite_number(row["total_return_pct"])]
            best_rows = []
            if finite_rows:
                max_sharpe = max(row["sharpe"] for row in finite_rows)
                candidates = [row for row in finite_rows if math.isclose(row["sharpe"], max_sharpe, rel_tol=0.0, abs_tol=0.0)]
                # Tie-break by higher total_return_pct
                max_tr = max(row["total_return_pct"] for row in candidates)
                winners = [row for row in candidates if math.isclose(row["total_return_pct"], max_tr, rel_tol=0.0, abs_tol=0.0)]
                # There may be multiple identical winners; accept if best matches any
                for w in winners:
                    best_rows.append(w)
                # Check whether provided best matches one of winners and sharpe/return match
                for w in best_rows:
                    if (w["fast_period"] == best_fp and w["slow_period"] == best_sp and
                        math.isclose(float(best["sharpe"]), w["sharpe"], rel_tol=1e-9, abs_tol=1e-12) and
                        math.isclose(float(best["total_return_pct"]), w["total_return_pct"], rel_tol=1e-9, abs_tol=1e-12)):
                        checks["best_sma_matches_opt_results"] = True
                        break

    # Leaderboard checks
    leaderboard_path = abspath(output_dir, "leaderboard.json")
    checks["leaderboard_exists"] = False
    checks["leaderboard_structure_valid"] = False
    checks["leaderboard_sorted_desc"] = False
    checks["leaderboard_winner_correct"] = False

    if os.path.isfile(leaderboard_path):
        checks["leaderboard_exists"] = True
        ldb = read_json(leaderboard_path)
        # Determine the array of entries
        entries = None
        winner_field = None
        if isinstance(ldb, list):
            entries = ldb
        elif isinstance(ldb, dict):
            winner_field = ldb.get("winner")
            # Try common keys
            for key in ["leaderboard", "entries", "results", "strategies", "items"]:
                if key in ldb and isinstance(ldb[key], list):
                    entries = ldb[key]
                    break
            if entries is None:
                # Try to find the first list value in dict
                for v in ldb.values():
                    if isinstance(v, list):
                        entries = v
                        break
        # Validate structure
        if isinstance(entries, list) and len(entries) == 3:
            # Check required fields and strategy names
            req_fields = ["strategy", "sharpe", "cagr_pct", "max_drawdown_pct"]
            strat_names = set()
            fields_ok = True
            for item in entries:
                if not isinstance(item, dict):
                    fields_ok = False
                    break
                if not all(k in item for k in req_fields):
                    fields_ok = False
                    break
                if not (is_finite_number(item["sharpe"]) and is_finite_number(item["cagr_pct"]) and is_finite_number(item["max_drawdown_pct"])):
                    fields_ok = False
                    break
                strat_names.add(item["strategy"])
            if fields_ok and strat_names == set(["sma_crossover", "rsi_reversal", "momentum"]):
                checks["leaderboard_structure_valid"] = True
                # Check sorted by sharpe descending
                sharpes = [item["sharpe"] for item in entries]
                sorted_desc = all(sharpes[i] >= sharpes[i+1] for i in range(len(sharpes)-1))
                if sorted_desc:
                    checks["leaderboard_sorted_desc"] = True
                # Check winner
                first_strategy = entries[0]["strategy"]
                # If ldb is dict, winner must match; if ldb is list, there is no top-level winner; treat as fail in that case
                if isinstance(ldb, dict) and isinstance(ldb.get("winner"), str):
                    if ldb["winner"] == first_strategy:
                        checks["leaderboard_winner_correct"] = True

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # No-op baseline: if output is empty or required artifacts missing entirely, reward should result as 0.0 naturally
    # Ensure reward is between 0 and 1
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()