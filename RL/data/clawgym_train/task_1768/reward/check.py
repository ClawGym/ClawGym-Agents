import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

def dquant(x, q):
    return x.quantize(q, rounding=ROUND_HALF_UP)

def to_decimal(x):
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return None

def normalize_asset_type(asset_type: str) -> str:
    if not isinstance(asset_type, str):
        return ''
    at = asset_type.strip().lower()
    if at == 'etf':
        return 'stock'
    return at

def load_json(path, use_decimal=True):
    try:
        with open(path, "r", encoding="utf-8") as f:
            if use_decimal:
                return json.load(f, parse_float=Decimal, parse_int=Decimal)
            else:
                return json.load(f)
    except Exception:
        return None

def compute_expected(holdings, prices):
    # holdings: list of dicts
    # prices: dict symbol->price
    positions = []
    total_cost = Decimal('0')
    total_value = Decimal('0')

    for h in holdings:
        symbol = str(h.get("symbol", "")).upper()
        asset_type = str(h.get("asset_type", "")).lower()
        qty = to_decimal(h.get("quantity"))
        cost_per = to_decimal(h.get("cost_basis_per_unit"))
        if symbol == "" or qty is None or cost_per is None:
            continue
        curr_price = to_decimal(prices.get(symbol))
        if curr_price is None:
            # If no price, treat as zero to avoid crash (but will fail checks later)
            curr_price = Decimal('0')

        cost_total = qty * cost_per
        curr_value = qty * curr_price
        gain_abs = curr_value - cost_total
        gain_pct = Decimal('0')
        if cost_total != 0:
            gain_pct = gain_abs / cost_total

        positions.append({
            "symbol": symbol,
            "asset_type": asset_type,
            "quantity": qty,
            "cost_basis_per_unit": cost_per,
            "cost_basis_total": cost_total,
            "current_price": curr_price,
            "current_value": curr_value,
            "gain_abs": gain_abs,
            "gain_pct": gain_pct
        })
        total_cost += cost_total
        total_value += curr_value

    total_gain_abs = total_value - total_cost
    total_gain_pct = Decimal('0')
    if total_cost != 0:
        total_gain_pct = total_gain_abs / total_cost

    # Allocation by symbol (fractions of total_value)
    alloc_by_symbol = {}
    if total_value != 0:
        for p in positions:
            alloc_by_symbol[p["symbol"]] = p["current_value"] / total_value
    else:
        for p in positions:
            alloc_by_symbol[p["symbol"]] = Decimal('0')

    # Allocation by asset type (map 'etf' -> 'stock')
    alloc_by_asset_type = {}
    if total_value != 0:
        for p in positions:
            at = normalize_asset_type(p["asset_type"])
            alloc_by_asset_type.setdefault(at, Decimal('0'))
            alloc_by_asset_type[at] += p["current_value"] / total_value
    else:
        for p in positions:
            at = normalize_asset_type(p["asset_type"])
            alloc_by_asset_type.setdefault(at, Decimal('0'))

    # Best/worst by gain_pct
    top_gainer = None
    top_loser = None
    if positions:
        top_gainer = max(positions, key=lambda x: (x["gain_pct"], x["symbol"])).get("symbol")
        top_loser = min(positions, key=lambda x: (x["gain_pct"], x["symbol"])).get("symbol")

    expected = {
        "positions": positions,
        "totals": {
            "total_cost": total_cost,
            "total_value": total_value,
            "total_gain_abs": total_gain_abs,
            "total_gain_pct": total_gain_pct
        },
        "allocation_by_symbol": alloc_by_symbol,
        "allocation_by_asset_type": alloc_by_asset_type,
        "best_worst": {
            "top_gainer_by_pct": top_gainer,
            "top_loser_by_pct": top_loser
        }
    }
    return expected

def compare_monetary(val_out, val_exp):
    d_out = to_decimal(val_out)
    d_exp = to_decimal(val_exp)
    if d_out is None or d_exp is None:
        return False
    return dquant(d_out, Decimal('0.01')) == dquant(d_exp, Decimal('0.01'))

def compare_fraction(val_out, val_exp):
    d_out = to_decimal(val_out)
    d_exp = to_decimal(val_exp)
    if d_out is None or d_exp is None:
        return False
    return dquant(d_out, Decimal('0.0001')) == dquant(d_exp, Decimal('0.0001'))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_portfolio_metrics_file": False,
        "positions_coverage": False,
        "per_position_values_correct": False,
        "totals_correct": False,
        "allocation_by_symbol_correct": False,
        "allocation_by_asset_type_correct": False,
        "best_worst_correct": False,
        "has_triggered_alerts_file": False,
        "alerts_correct_set": False,
        "alerts_have_current_prices": False,
        "has_portfolio_report_file": False,
        "report_has_required_lines": False,
        "report_has_allocation_summary": False
    }

    # Load inputs
    holdings_path = os.path.join(input_dir, "holdings.json")
    prices_path = os.path.join(input_dir, "prices.json")
    alerts_path = os.path.join(input_dir, "alerts.json")

    holdings = load_json(holdings_path, use_decimal=True) or []
    prices = load_json(prices_path, use_decimal=True) or {}
    alerts = load_json(alerts_path, use_decimal=True) or []

    # Compute expected values from inputs
    expected = compute_expected(holdings, prices)

    # Additional expected constants per task description for validation
    # These are used to verify the final report strings and allocations summary.
    # Totals expected (rounded):
    expected_total_value_line = "Total current value: $80,900.00"
    expected_total_gain_line = "Total gain/loss: $26,000.00"
    # Allocation percentages in report (as substrings):
    expected_stocks_pct_str = "Stocks: 51.98%"
    expected_crypto_pct_str = "Crypto: 48.02%"

    # Load and validate portfolio_metrics.json
    portfolio_metrics_path = os.path.join(output_dir, "portfolio_metrics.json")
    pm = None
    if os.path.isfile(portfolio_metrics_path):
        pm = load_json(portfolio_metrics_path, use_decimal=True)
        if isinstance(pm, dict):
            checks["has_portfolio_metrics_file"] = True

    if checks["has_portfolio_metrics_file"]:
        # Positions coverage
        out_positions = pm.get("positions")
        if isinstance(out_positions, list) and len(out_positions) >= len(holdings):
            # Map by symbol (uppercase)
            out_map = {}
            for p in out_positions:
                sym = str(p.get("symbol", "")).upper()
                if sym:
                    out_map[sym] = p
            input_syms = [str(h.get("symbol", "")).upper() for h in holdings if h.get("symbol")]
            coverage_ok = all(s in out_map for s in input_syms)
            checks["positions_coverage"] = coverage_ok

            # Per-position numeric checks
            if coverage_ok:
                all_ok = True
                for exp_p in expected["positions"]:
                    sym = exp_p["symbol"]
                    out_p = out_map.get(sym)
                    if not isinstance(out_p, dict):
                        all_ok = False
                        break
                    # Asset type presence (allow 'etf' vs 'stock' normalization only for allocations; here just ensure it exists)
                    if "asset_type" not in out_p:
                        all_ok = False
                        break

                    # Monetary checks to 2 decimals
                    if not compare_monetary(out_p.get("cost_basis_total"), exp_p["cost_basis_total"]):
                        all_ok = False
                        break
                    if not compare_monetary(out_p.get("current_price"), exp_p["current_price"]):
                        all_ok = False
                        break
                    if not compare_monetary(out_p.get("current_value"), exp_p["current_value"]):
                        all_ok = False
                        break
                    if not compare_monetary(out_p.get("gain_abs"), exp_p["gain_abs"]):
                        all_ok = False
                        break
                    # Percentage to 4 decimals
                    if not compare_fraction(out_p.get("gain_pct"), exp_p["gain_pct"]):
                        all_ok = False
                        break
                checks["per_position_values_correct"] = all_ok

        # Totals
        totals = pm.get("totals") if isinstance(pm, dict) else None
        if isinstance(totals, dict):
            totals_ok = True
            totals_ok &= compare_monetary(totals.get("total_cost"), expected["totals"]["total_cost"])
            totals_ok &= compare_monetary(totals.get("total_value"), expected["totals"]["total_value"])
            totals_ok &= compare_monetary(totals.get("total_gain_abs"), expected["totals"]["total_gain_abs"])
            totals_ok &= compare_fraction(totals.get("total_gain_pct"), expected["totals"]["total_gain_pct"])
            checks["totals_correct"] = totals_ok

        # Allocation by symbol
        alloc_sym_out = pm.get("allocation_by_symbol") if isinstance(pm, dict) else None
        if isinstance(alloc_sym_out, dict):
            alloc_ok = True
            for sym, exp_frac in expected["allocation_by_symbol"].items():
                out_val = alloc_sym_out.get(sym)
                if out_val is None or not compare_fraction(out_val, exp_frac):
                    alloc_ok = False
                    break
            checks["allocation_by_symbol_correct"] = alloc_ok

        # Allocation by asset type
        alloc_type_out = pm.get("allocation_by_asset_type") if isinstance(pm, dict) else None
        if isinstance(alloc_type_out, dict):
            # Normalize expected
            exp_alloc_types = {}
            for at, frac in expected["allocation_by_asset_type"].items():
                nat = normalize_asset_type(at)
                exp_alloc_types[nat] = exp_alloc_types.get(nat, Decimal('0')) + frac

            # We specifically need 'stock' and 'crypto' to match to 4 decimals
            needed_keys = ["stock", "crypto"]
            alloc_type_ok = True
            for key in needed_keys:
                out_val = alloc_type_out.get(key)
                exp_val = exp_alloc_types.get(key, Decimal('0'))
                if out_val is None or not compare_fraction(out_val, exp_val):
                    alloc_type_ok = False
                    break
            checks["allocation_by_asset_type_correct"] = alloc_type_ok

        # Best/worst
        bw = pm.get("best_worst") if isinstance(pm, dict) else None
        if isinstance(bw, dict):
            tg = bw.get("top_gainer_by_pct")
            tl = bw.get("top_loser_by_pct")
            # Expected from task: NVDA top gainer, TSLA top loser
            checks["best_worst_correct"] = (str(tg).upper() == "NVDA" and str(tl).upper() == "TSLA")

    # Load and validate triggered_alerts.json
    triggered_alerts_path = os.path.join(output_dir, "triggered_alerts.json")
    ta = None
    if os.path.isfile(triggered_alerts_path):
        ta = load_json(triggered_alerts_path, use_decimal=True)
        if isinstance(ta, list):
            checks["has_triggered_alerts_file"] = True

    # Compute expected triggered alerts
    expected_triggered = []
    if isinstance(alerts, list) and isinstance(prices, dict):
        for a in alerts:
            try:
                sym = str(a.get("symbol", "")).upper()
                direction = str(a.get("direction", ""))
                target = to_decimal(a.get("target"))
                curr_price = to_decimal(prices.get(sym))
                if sym == "" or direction not in ("at_or_above", "at_or_below") or target is None or curr_price is None:
                    continue
                triggered = False
                if direction == "at_or_above" and curr_price >= target:
                    triggered = True
                if direction == "at_or_below" and curr_price <= target:
                    triggered = True
                if triggered:
                    expected_triggered.append({
                        "symbol": sym,
                        "direction": direction,
                        "target": target,
                        "current_price": curr_price
                    })
            except Exception:
                continue

    if checks["has_triggered_alerts_file"]:
        # Build normalized sets for comparison
        def norm_alert(a):
            if not isinstance(a, dict):
                return None
            sym = str(a.get("symbol", "")).upper()
            direction = str(a.get("direction", ""))
            tgt = to_decimal(a.get("target"))
            cp = to_decimal(a.get("current_price"))
            if sym == "" or direction not in ("at_or_above", "at_or_below") or tgt is None or cp is None:
                return None
            return (sym, direction, dquant(tgt, Decimal('0.01')), dquant(cp, Decimal('0.01')))

        out_alerts_norm = set()
        for item in ta:
            na = norm_alert(item)
            if na is not None:
                out_alerts_norm.add(na)

        exp_alerts_norm = set()
        for item in expected_triggered:
            exp_alerts_norm.add((
                item["symbol"],
                item["direction"],
                dquant(item["target"], Decimal('0.01')),
                dquant(item["current_price"], Decimal('0.01'))
            ))

        checks["alerts_correct_set"] = (out_alerts_norm == exp_alerts_norm)

        # Also ensure each has current_price matching prices (2 decimals)
        curr_price_ok = True
        for item in ta:
            na = norm_alert(item)
            if na is None:
                curr_price_ok = False
                break
            sym = na[0]
            cp_out = na[3]
            cp_exp = dquant(to_decimal(prices.get(sym)), Decimal('0.01'))
            if cp_exp is None or cp_out != cp_exp:
                curr_price_ok = False
                break
        checks["alerts_have_current_prices"] = curr_price_ok

    # Load and validate portfolio_report.md
    report_path = os.path.join(output_dir, "portfolio_report.md")
    report_content = None
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()
            checks["has_portfolio_report_file"] = True
        except Exception:
            report_content = None

    if checks["has_portfolio_report_file"] and isinstance(report_content, str):
        # Required exact lines (as substrings for robustness; lines may have other content)
        has_value_line = expected_total_value_line in report_content
        has_gain_line = expected_total_gain_line in report_content
        checks["report_has_required_lines"] = (has_value_line and has_gain_line)

        # Allocation summary substrings
        stocks_str_ok = expected_stocks_pct_str in report_content
        crypto_str_ok = expected_crypto_pct_str in report_content
        checks["report_has_allocation_summary"] = (stocks_str_ok and crypto_str_ok)

    # Compute reward as mean of checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or all key artifacts missing, ensure 0.0
    # If none of the main artifacts exist, force reward = 0.0
    main_artifacts_exist = any([
        checks["has_portfolio_metrics_file"],
        checks["has_triggered_alerts_file"],
        checks["has_portfolio_report_file"]
    ])
    if not main_artifacts_exist:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()