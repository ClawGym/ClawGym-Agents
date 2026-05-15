import json
import os
import sys
from collections import OrderedDict

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def csv_first_nonempty_lines(path, max_lines=5):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for _ in range(max_lines):
                line = f.readline()
                if line == "":
                    break
                s = line.rstrip("\r\n")
                if s.strip() != "":
                    lines.append(s)
    except Exception:
        return []
    return lines

def strip_bom(s):
    if s and s.startswith("\ufeff"):
        return s.lstrip("\ufeff")
    return s

def check_trades_header(path):
    lines = csv_first_nonempty_lines(path, max_lines=1)
    if not lines:
        return False
    header = strip_bom(lines[0]).strip()
    expected = "entry_time,exit_time,entry_price,exit_price,direction,size,pnl,pnl_pct,duration"
    return header == expected

def check_equity_file(path):
    lines = csv_first_nonempty_lines(path, max_lines=5)
    if not lines:
        return False
    header = strip_bom(lines[0]).strip()
    if header != "date,equity":
        return False
    # At least one data row after header
    return len(lines) >= 2

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not used for scoring but defined for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    checks = OrderedDict()

    # 1) summary.json validations
    summary_path = os.path.join(output_dir, "reports", "summary.json")
    summary = load_json(summary_path)
    checks["summary_exists"] = summary is not None
    checks["summary_is_array"] = isinstance(summary, list) if summary is not None else False
    checks["summary_len_gte_4"] = (len(summary) >= 4) if isinstance(summary, list) else False

    required_pairs = [
        ("sma_crossover", "BTC-USD"),
        ("sma_crossover", "ETH-USD"),
        ("rsi_reversal", "BTC-USD"),
        ("rsi_reversal", "ETH-USD"),
    ]
    summary_has_pairs = False
    summary_fields_ok = False

    if isinstance(summary, list):
        # Build map from (strategy, symbol) to first object
        pair_map = {}
        for obj in summary:
            if isinstance(obj, dict):
                strat = obj.get("strategy")
                sym = obj.get("symbol")
                if isinstance(strat, str) and isinstance(sym, str):
                    key = (strat, sym)
                    if key not in pair_map:
                        pair_map[key] = obj

        # Check coverage
        summary_has_pairs = all(pair in pair_map for pair in required_pairs)

        # Check required fields and types for required pairs only
        def obj_fields_ok(obj):
            # strategy, symbol, period (strings)
            if not isinstance(obj.get("strategy"), str):
                return False
            if not isinstance(obj.get("symbol"), str):
                return False
            if not isinstance(obj.get("period"), str):
                return False
            # numeric fields
            numeric_keys = [
                "capital",
                "commission",
                "slippage",
                "total_return",
                "cagr",
                "sharpe",
                "sortino",
                "max_drawdown",
                "win_rate",
                "profit_factor",
            ]
            for k in numeric_keys:
                if not is_number(obj.get(k)):
                    return False
            return True

        if summary_has_pairs:
            summary_fields_ok = all(obj_fields_ok(pair_map[p]) for p in required_pairs)
        else:
            summary_fields_ok = False

    checks["summary_has_required_pairs"] = summary_has_pairs
    checks["summary_required_fields_types_ok"] = summary_fields_ok

    # 2) best_params.json validations
    best_params_path = os.path.join(output_dir, "reports", "best_params.json")
    best_params = load_json(best_params_path)
    checks["best_params_exists"] = best_params is not None

    strategy_correct = False
    tested_len_ok = False
    tested_entries_valid = False
    best_valid = False

    if isinstance(best_params, dict):
        strategy_correct = best_params.get("strategy") == "sma_crossover"
        grid_search = best_params.get("grid_search")
        tested = None
        if isinstance(grid_search, dict):
            tested = grid_search.get("tested")
        if isinstance(tested, list):
            tested_len_ok = len(tested) >= 3
            # Each tested entry: integers fast_period, slow_period; numeric sharpe
            def tested_ok(e):
                if not isinstance(e, dict):
                    return False
                fp = e.get("fast_period")
                sp = e.get("slow_period")
                sh = e.get("sharpe")
                if not isinstance(fp, int):
                    return False
                if not isinstance(sp, int):
                    return False
                if not is_number(sh):
                    return False
                return True
            tested_entries_valid = tested_len_ok and all(tested_ok(e) for e in tested)

        best_obj = best_params.get("best")
        if isinstance(best_obj, dict):
            fpb = best_obj.get("fast_period")
            spb = best_obj.get("slow_period")
            shb = best_obj.get("sharpe")
            best_valid = isinstance(fpb, int) and isinstance(spb, int) and is_number(shb)

    checks["best_params_strategy_correct"] = strategy_correct
    checks["best_params_tested_len_gte_3"] = tested_len_ok
    checks["best_params_tested_entries_valid"] = tested_entries_valid
    checks["best_params_best_valid"] = best_valid

    # 3) Trades CSV headers
    trades_dir = os.path.join(output_dir, "trades")
    trade_files = {
        "trades_sma_btc_header_ok": os.path.join(trades_dir, "sma_crossover_BTC-USD.csv"),
        "trades_sma_eth_header_ok": os.path.join(trades_dir, "sma_crossover_ETH-USD.csv"),
        "trades_rsi_btc_header_ok": os.path.join(trades_dir, "rsi_reversal_BTC-USD.csv"),
        "trades_rsi_eth_header_ok": os.path.join(trades_dir, "rsi_reversal_ETH-USD.csv"),
    }
    for check_name, path in trade_files.items():
        ok = False
        if os.path.isfile(path):
            ok = check_trades_header(path)
        checks[check_name] = ok

    # 4) Equity CSV files
    equity_dir = os.path.join(output_dir, "equity")
    equity_files = {
        "equity_sma_btc_ok": os.path.join(equity_dir, "sma_crossover_BTC-USD.csv"),
        "equity_sma_eth_ok": os.path.join(equity_dir, "sma_crossover_ETH-USD.csv"),
        "equity_rsi_btc_ok": os.path.join(equity_dir, "rsi_reversal_BTC-USD.csv"),
        "equity_rsi_eth_ok": os.path.join(equity_dir, "rsi_reversal_ETH-USD.csv"),
    }
    for check_name, path in equity_files.items():
        ok = False
        if os.path.isfile(path):
            ok = check_equity_file(path)
        checks[check_name] = ok

    # 5) risk_notes.md
    risk_notes_path = os.path.join(output_dir, "notes", "risk_notes.md")
    rn_text = read_text(risk_notes_path)
    risk_ok = False
    if isinstance(rn_text, str):
        has_phrase = "Past performance does not guarantee future results" in rn_text
        low = rn_text.lower()
        has_overfitting = "overfitting" in low
        has_lookahead = "look-ahead bias" in low
        has_commission = "commission" in low
        has_slippage = "slippage" in low
        long_enough = len(rn_text) >= 200
        risk_ok = all([has_phrase, has_overfitting, has_lookahead, has_commission, has_slippage, long_enough])
    checks["risk_notes_valid"] = risk_ok

    # 6) methods.md
    methods_path = os.path.join(output_dir, "notes", "methods.md")
    md_text = read_text(methods_path)
    methods_ok = False
    if isinstance(md_text, str):
        low = md_text.lower()
        required_terms = ["period", "commission", "slippage", "sharpe", "parameter", "grid"]
        terms_ok = all(term in low for term in required_terms)
        long_enough = len(md_text) >= 400
        methods_ok = terms_ok and long_enough
    checks["methods_md_valid"] = methods_ok

    # Compute reward as average of checks (no-op baseline => 0.0)
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result))

if __name__ == "__main__":
    main()