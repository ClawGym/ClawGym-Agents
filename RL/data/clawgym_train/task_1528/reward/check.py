import csv
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows, None
    except Exception as e:
        return None, f"read_error: {e}"


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _count_data_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
            if not lines:
                return 0
            return max(0, len(lines) - 1)
    except Exception:
        return 0


def _compute_returns_and_stats(prices_rows: List[Dict[str, str]]) -> Tuple[Dict[str, List[Tuple[str, float]]], Dict[str, Dict[str, object]]]:
    by_symbol: Dict[str, List[Tuple[datetime, str, float]]] = {}
    for r in prices_rows:
        d = _parse_iso_date(r.get("date", ""))
        sym = r.get("symbol", "")
        close = _safe_float(r.get("close", ""))
        if d is None or sym is None or sym == "" or close is None:
            continue
        by_symbol.setdefault(sym, []).append((d, r["date"], close))
    returns_by_symbol: Dict[str, List[Tuple[str, float]]] = {}
    stats: Dict[str, Dict[str, object]] = {}
    for sym, series in by_symbol.items():
        series_sorted = sorted(series, key=lambda x: x[0])
        dates = [dstr for (_, dstr, _) in series_sorted]
        closes = [c for (_, _, c) in series_sorted]
        sym_returns: List[Tuple[str, float]] = []
        for i in range(1, len(closes)):
            prev_c = closes[i - 1]
            curr_c = closes[i]
            if prev_c != 0:
                r = (curr_c / prev_c) - 1.0
            else:
                r = 0.0
            sym_returns.append((dates[i], r))
        returns_by_symbol[sym] = sym_returns
        n_prices = len(closes)
        start_date = dates[0] if dates else ""
        end_date = dates[-1] if dates else ""
        n_returns = len(sym_returns)
        if n_returns > 0:
            mean_r = sum(r for _, r in sym_returns) / n_returns
            if n_returns >= 2:
                mean = mean_r
                var = sum((r - mean) ** 2 for _, r in sym_returns) / (n_returns - 1)
                std = math.sqrt(var)
            else:
                std = 0.0
        else:
            mean_r = 0.0
            std = 0.0
        ann_vol = std * math.sqrt(252.0)
        max_peak = -math.inf
        max_dd = 0.0
        for c in closes:
            if c > max_peak:
                max_peak = c
            if max_peak > 0:
                dd = (c / max_peak) - 1.0
                if dd < max_dd:
                    max_dd = dd
        stats[sym] = {
            "trading_days": n_prices,
            "start_date": start_date,
            "end_date": end_date,
            "mean_daily_return": mean_r,
            "std_daily_return": std,
            "annualized_volatility": ann_vol,
            "max_drawdown": max_dd,
        }
    return returns_by_symbol, stats


def _compute_correlation(returns_a: List[Tuple[str, float]], returns_b: List[Tuple[str, float]]) -> Optional[float]:
    map_a = {d: r for d, r in returns_a}
    map_b = {d: r for d, r in returns_b}
    common_dates = sorted(set(map_a.keys()) & set(map_b.keys()))
    n = len(common_dates)
    if n < 2:
        return None
    xs = [map_a[d] for d in common_dates]
    ys = [map_b[d] for d in common_dates]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / (n - 1)
    var_x = sum((x - mean_x) ** 2 for x in xs) / (n - 1)
    var_y = sum((y - mean_y) ** 2 for y in ys) / (n - 1)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _load_output_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    rows, err = _read_csv_dicts(path)
    if err is not None or rows is None:
        return None, None, err or "read_error"
    headers = []
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
    except Exception as e:
        return None, None, f"header_error: {e}"
    return rows, headers, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "good_run_log_present": 0.0,
        "bad_run_log_present": 0.0,
        "bad_run_log_has_validation_hint": 0.0,
        "good_run_log_no_error_keyword": 0.0,
        "asset_stats_structure": 0.0,
        "asset_stats_trading_days": 0.0,
        "asset_stats_dates": 0.0,
        "asset_stats_mean_std_vol": 0.0,
        "asset_stats_max_drawdown": 0.0,
        "asset_stats_correlation": 0.0,
        "daily_returns_structure": 0.0,
        "daily_returns_values": 0.0,
        "error_summary_structure": 0.0,
        "error_summary_status_and_rows": 0.0,
        "error_summary_error_snippet_matches_log": 0.0,
    }

    input_good = workspace / "input" / "crypto_prices.csv"
    input_bad = workspace / "input" / "crypto_prices_bad.csv"
    input_bench = workspace / "input" / "bench_prices.csv"
    asset_stats_path = workspace / "output" / "summary" / "asset_stats.csv"
    daily_returns_path = workspace / "output" / "derived" / "daily_returns.csv"
    good_log_path = workspace / "output" / "cli_logs" / "good_run.log"
    bad_log_path = workspace / "output" / "cli_logs" / "bad_run.log"
    error_summary_path = workspace / "output" / "error_summary.csv"

    try:
        if good_log_path.exists() and good_log_path.is_file() and good_log_path.stat().st_size > 0:
            scores["good_run_log_present"] = 1.0
            try:
                txt = good_log_path.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"\berror\b", txt, flags=re.IGNORECASE) is None:
                    scores["good_run_log_no_error_keyword"] = 1.0
            except Exception:
                pass
        if bad_log_path.exists() and bad_log_path.is_file() and bad_log_path.stat().st_size > 0:
            scores["bad_run_log_present"] = 1.0
            try:
                txt = bad_log_path.read_text(encoding="utf-8", errors="ignore")
                hint = re.search(r"(date|symbol|close|error)", txt, flags=re.IGNORECASE)
                if hint is not None:
                    scores["bad_run_log_has_validation_hint"] = 1.0
            except Exception:
                pass
    except Exception:
        pass

    crypto_rows, crypto_err = _read_csv_dicts(input_good)
    bench_rows, bench_err = _read_csv_dicts(input_bench)
    expected_returns_by_symbol: Dict[str, List[Tuple[str, float]]] = {}
    expected_stats: Dict[str, Dict[str, object]] = {}
    expected_corr: Dict[str, Optional[float]] = {}
    if crypto_rows is not None and bench_rows is not None:
        exp_returns, exp_stats = _compute_returns_and_stats(crypto_rows)
        expected_returns_by_symbol = exp_returns
        expected_stats = exp_stats
        bench_returns_by_symbol, _ = _compute_returns_and_stats(bench_rows)
        spy_returns = bench_returns_by_symbol.get("SPY", [])
        for sym, ret_list in expected_returns_by_symbol.items():
            expected_corr[sym] = _compute_correlation(ret_list, spy_returns)

    rows, header, err = _load_output_csv(asset_stats_path)
    expected_header_asset = [
        "symbol",
        "start_date",
        "end_date",
        "trading_days",
        "mean_daily_return",
        "std_daily_return",
        "annualized_volatility",
        "max_drawdown",
        "correlation_vs_SPY",
    ]
    if err is None and rows is not None and header is not None:
        if header == expected_header_asset and len(rows) >= 1:
            expected_symbols = set(expected_stats.keys())
            found_symbols = [r.get("symbol", "") for r in rows]
            if set(found_symbols) == expected_symbols and len(found_symbols) == len(expected_symbols):
                scores["asset_stats_structure"] = 1.0

            by_sym_out = {r.get("symbol", ""): r for r in rows if r.get("symbol", "")}
            tol = 5e-4
            td_checks = 0
            td_total = max(1, len(expected_symbols))
            for sym, est in expected_stats.items():
                out = by_sym_out.get(sym)
                if not out:
                    continue
                td_out = out.get("trading_days")
                try:
                    td_int = int(float(td_out))
                except Exception:
                    td_int = None
                if td_int == est["trading_days"]:
                    td_checks += 1
            scores["asset_stats_trading_days"] = td_checks / td_total if td_total > 0 else 0.0

            date_checks = 0
            date_total = max(1, len(expected_symbols) * 2)
            for sym, est in expected_stats.items():
                out = by_sym_out.get(sym)
                if not out:
                    continue
                if out.get("start_date") == est["start_date"]:
                    date_checks += 1
                if out.get("end_date") == est["end_date"]:
                    date_checks += 1
            scores["asset_stats_dates"] = date_checks / date_total if date_total > 0 else 0.0

            msv_checks = 0
            msv_total = max(1, len(expected_symbols) * 3)
            for sym, est in expected_stats.items():
                out = by_sym_out.get(sym)
                if not out:
                    continue
                m_out = _safe_float(out.get("mean_daily_return", ""))
                if m_out is not None and abs(m_out - float(est["mean_daily_return"])) <= tol:
                    msv_checks += 1
                s_out = _safe_float(out.get("std_daily_return", ""))
                if s_out is not None and abs(s_out - float(est["std_daily_return"])) <= tol:
                    msv_checks += 1
                a_out = _safe_float(out.get("annualized_volatility", ""))
                if a_out is not None and (abs(a_out - float(est["annualized_volatility"])) <= tol * math.sqrt(252.0) or abs(a_out - float(est["annualized_volatility"])) <= 1e-3):
                    msv_checks += 1
            scores["asset_stats_mean_std_vol"] = msv_checks / msv_total if msv_total > 0 else 0.0

            dd_checks = 0
            dd_total = max(1, len(expected_symbols))
            for sym, est in expected_stats.items():
                out = by_sym_out.get(sym)
                if not out:
                    continue
                dd_out = _safe_float(out.get("max_drawdown", ""))
                if dd_out is None:
                    continue
                if abs(abs(dd_out) - abs(float(est["max_drawdown"]))) <= tol:
                    dd_checks += 1
            scores["asset_stats_max_drawdown"] = dd_checks / dd_total if dd_total > 0 else 0.0

            corr_checks = 0
            corr_total = max(1, len(expected_symbols))
            for sym in expected_symbols:
                out = by_sym_out.get(sym)
                if not out:
                    continue
                c_out_raw = out.get("correlation_vs_SPY", "")
                c_out = _safe_float(c_out_raw)
                c_exp = expected_corr.get(sym)
                if c_out is None or c_exp is None:
                    continue
                if abs(c_out - c_exp) <= 5e-4:
                    corr_checks += 1
            scores["asset_stats_correlation"] = corr_checks / corr_total if corr_total > 0 else 0.0

    dr_rows, dr_header, dr_err = _load_output_csv(daily_returns_path)
    expected_dr_header = ["date", "symbol", "daily_return"]
    if dr_err is None and dr_rows is not None and dr_header is not None:
        if dr_header == expected_dr_header and len(dr_rows) >= 1:
            scores["daily_returns_structure"] = 1.0
        expected_map: Dict[Tuple[str, str], float] = {}
        expected_symbols = set(expected_returns_by_symbol.keys())
        for sym, lst in expected_returns_by_symbol.items():
            for d, r in lst:
                expected_map[(d, sym)] = r
        observed_map: Dict[Tuple[str, str], float] = {}
        extra_symbols: set = set()
        for r in dr_rows:
            d = r.get("date", "")
            s = r.get("symbol", "")
            v = _safe_float(r.get("daily_return", ""))
            if s and d and v is not None:
                observed_map[(d, s)] = v
                if s not in expected_symbols:
                    extra_symbols.add(s)
        tol_dr = 5e-4
        total = max(1, len(expected_map))
        correct = 0
        if len(observed_map) == len(expected_map) and not extra_symbols:
            for k, v in expected_map.items():
                ov = observed_map.get(k)
                if ov is None:
                    continue
                if abs(ov - v) <= tol_dr:
                    correct += 1
        scores["daily_returns_values"] = correct / total if total > 0 else 0.0

    es_rows, es_header, es_err = _load_output_csv(error_summary_path)
    expected_es_header = ["input_file", "status", "error_message_snippet", "rows_in_input", "notes"]
    if es_err is None and es_rows is not None and es_header is not None:
        if es_header == expected_es_header and len(es_rows) >= 2:
            scores["error_summary_structure"] = 1.0
        def _basename(p: str) -> str:
            return Path(p).name

        row_by_base = {}
        for row in es_rows:
            row_by_base[_basename(row.get("input_file", ""))] = row

        good_row = row_by_base.get("crypto_prices.csv")
        bad_row = row_by_base.get("crypto_prices_bad.csv")

        status_checks = 0
        status_total = 2
        if good_row:
            if good_row.get("status") == "OK":
                status_checks += 1
            try:
                rows_in_input_good = int(float(good_row.get("rows_in_input", "").strip()))
            except Exception:
                rows_in_input_good = None
            expected_rows_good = _count_data_rows(input_good)
            if rows_in_input_good == expected_rows_good and expected_rows_good > 0:
                status_checks += 1
        if bad_row:
            if bad_row.get("status") == "ERROR":
                status_checks += 1
            try:
                rows_in_input_bad = int(float(bad_row.get("rows_in_input", "").strip()))
            except Exception:
                rows_in_input_bad = None
            expected_rows_bad = _count_data_rows(input_bad)
            if rows_in_input_bad == expected_rows_bad and expected_rows_bad > 0:
                status_checks += 1
        scores["error_summary_status_and_rows"] = status_checks / 4.0

        snippet_checks = 0
        snippet_total = 2
        try:
            bad_log_txt = bad_log_path.read_text(encoding="utf-8", errors="ignore") if bad_log_path.exists() else ""
        except Exception:
            bad_log_txt = ""
        if good_row:
            snippet = (good_row.get("error_message_snippet") or "").strip()
            if snippet == "":
                snippet_checks += 1
        if bad_row:
            snippet = (bad_row.get("error_message_snippet") or "").strip()
            if snippet and (snippet.lower() in bad_log_txt.lower()):
                snippet_checks += 1
        scores["error_summary_error_snippet_matches_log"] = snippet_checks / snippet_total

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()