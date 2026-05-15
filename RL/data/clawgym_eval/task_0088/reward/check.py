import json
import os
import sys
import csv
from math import isfinite

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def approx_equal(a, b, tol=1e-6):
    try:
        if a is None or b is None:
            return False
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def parse_float(x, default=0.0):
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() == "null":
            return default
        return float(s)
    except Exception:
        return default

def safe_outcome_str(x):
    if x is None:
        return None
    s = str(x).strip()
    return s if s != "" else None

def normalize_outcome(x):
    if x is None:
        return None
    return str(x).strip().lower()

def parse_markets_json(markets_json):
    # Expect either a list of events or an object with 'events' or 'data'
    if isinstance(markets_json, list):
        return markets_json
    if isinstance(markets_json, dict):
        if isinstance(markets_json.get("events"), list):
            return markets_json["events"]
        if isinstance(markets_json.get("data"), list):
            return markets_json["data"]
    return []

def get_yes_price_from_market(market):
    prices = market.get("outcomePrices")
    if prices is None:
        return 0.0
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            return 0.0
    if isinstance(prices, list) and len(prices) >= 1:
        try:
            return float(prices[0])
        except Exception:
            return 0.0
    return 0.0

def get_market_title(market):
    return market.get("groupItemTitle") or market.get("question") or ""

def find_event_by_slug(events, slug):
    for e in events:
        if str(e.get("slug", "")).lower() == str(slug).lower():
            return e
    return None

def select_market_for_outcome(event, outcome):
    markets = event.get("markets", []) or []
    if not markets:
        return None
    if outcome:
        outcome_l = outcome.lower()
        for m in markets:
            title = (m.get("groupItemTitle") or "").lower()
            if title == outcome_l:
                return m
    # Fallback to first
    return markets[0]

def event_has_politics_tag(event):
    tags = event.get("tags") or []
    for t in tags:
        label = t.get("label") if isinstance(t, dict) else t
        if isinstance(label, str) and label.lower() == "politics":
            return True
    return False

def compute_watchlist_expected(events, watchlist_spec):
    expected = []
    for item in watchlist_spec:
        slug = item.get("slug")
        outcome = safe_outcome_str(item.get("outcome"))
        baseline_price = parse_float(item.get("baseline_price"), default=0.0)
        alert_at_pct = item.get("alert_at_pct")
        alert_change_pct = item.get("alert_change_pct")
        alert_at_pct_val = parse_float(alert_at_pct, default=None) if alert_at_pct is not None else None
        alert_change_pct_val = parse_float(alert_change_pct, default=None) if alert_change_pct is not None else None

        event = find_event_by_slug(events, slug)
        current_price = 0.0
        if event is not None:
            market = select_market_for_outcome(event, outcome)
            if market is not None:
                current_price = get_yes_price_from_market(market)

        reasons = []
        # alert_at logic
        if alert_at_pct_val is not None:
            threshold = alert_at_pct_val / 100.0
            if current_price >= threshold:
                reasons.append("alert_at")
        # alert_change logic
        if alert_change_pct_val is not None and baseline_price and baseline_price != 0:
            change_ratio = abs((current_price - baseline_price) / baseline_price)
            if change_ratio >= (alert_change_pct_val / 100.0):
                reasons.append("alert_change")

        triggered = len(reasons) > 0

        expected.append({
            "slug": slug,
            "outcome": outcome if outcome is not None else None,
            "baseline_price": baseline_price,
            "current_price": current_price,
            "alert_at_pct": alert_at_pct_val if alert_at_pct is not None else None,
            "alert_change_pct": alert_change_pct_val if alert_change_pct is not None else None,
            "triggered": triggered,
            "reasons": reasons
        })
    return expected

def compare_watchlist(actual, expected):
    # Compare item by slug + outcome (case-insensitive for outcome)
    if not isinstance(actual, list) or not isinstance(expected, list):
        return False
    if len(actual) != len(expected):
        return False
    # Build mapping for expected
    exp_map = {}
    for e in expected:
        key = (str(e["slug"]).lower(), normalize_outcome(e.get("outcome")))
        exp_map[key] = e
    matched = 0
    for a in actual:
        slug = a.get("slug")
        outcome = safe_outcome_str(a.get("outcome"))
        key = (str(slug).lower(), normalize_outcome(outcome))
        if key not in exp_map:
            return False
        e = exp_map[key]
        # Check numeric fields
        if not approx_equal(parse_float(a.get("baseline_price")), e["baseline_price"], tol=1e-6):
            return False
        if not approx_equal(parse_float(a.get("current_price")), e["current_price"], tol=1e-6):
            return False
        # alert_at_pct
        a_alert_at = a.get("alert_at_pct")
        e_alert_at = e.get("alert_at_pct")
        if (a_alert_at is None) != (e_alert_at is None):
            return False
        if a_alert_at is not None and not approx_equal(parse_float(a_alert_at), e_alert_at, tol=1e-6):
            return False
        # alert_change_pct
        a_alert_change = a.get("alert_change_pct")
        e_alert_change = e.get("alert_change_pct")
        if (a_alert_change is None) != (e_alert_change is None):
            return False
        if a_alert_change is not None and not approx_equal(parse_float(a_alert_change), e_alert_change, tol=1e-6):
            return False
        # triggered
        a_trig = bool(a.get("triggered", False))
        if a_trig != e["triggered"]:
            return False
        # reasons set equality (order-insensitive)
        a_reasons = a.get("reasons") or []
        e_reasons = e.get("reasons") or []
        if set(a_reasons) != set(e_reasons):
            return False
        matched += 1
    return matched == len(expected)

def compute_alerts_expected(expected_watchlist):
    alerts = []
    for e in expected_watchlist:
        if e.get("triggered"):
            alerts.append({
                "slug": e["slug"],
                "outcome": e["outcome"],
                "current_price": e["current_price"],
                "reasons": e["reasons"]
            })
    return alerts

def compare_alerts(actual, expected):
    if not isinstance(actual, list) or not isinstance(expected, list):
        return False
    if len(actual) != len(expected):
        return False
    # Build map by slug + outcome lower
    exp_map = {(str(e["slug"]).lower(), normalize_outcome(e.get("outcome"))): e for e in expected}
    for a in actual:
        key = (str(a.get("slug")).lower(), normalize_outcome(safe_outcome_str(a.get("outcome"))))
        if key not in exp_map:
            return False
        e = exp_map[key]
        if not approx_equal(parse_float(a.get("current_price")), e["current_price"], tol=1e-6):
            return False
        if set(a.get("reasons") or []) != set(e.get("reasons") or []):
            return False
    return True

def compute_digest_politics(events):
    politics_events = [e for e in events if event_has_politics_tag(e)]
    politics_events.sort(key=lambda ev: parse_float(ev.get("volume24hr")), reverse=True)
    top = politics_events[:3]
    result = []
    for e in top:
        markets = e.get("markets", []) or []
        if markets:
            best_market = max(markets, key=lambda m: get_yes_price_from_market(m))
            yes_price = get_yes_price_from_market(best_market)
            one_day = parse_float(best_market.get("oneDayPriceChange"))
            result.append({
                "slug": e.get("slug"),
                "event_title": e.get("title"),
                "top_market_title": get_market_title(best_market),
                "yes_price": yes_price,
                "oneDayPriceChange": one_day,
                "volume24hr": parse_float(e.get("volume24hr"))
            })
        else:
            # Edge case: no markets
            result.append({
                "slug": e.get("slug"),
                "event_title": e.get("title"),
                "top_market_title": "",
                "yes_price": 0.0,
                "oneDayPriceChange": 0.0,
                "volume24hr": parse_float(e.get("volume24hr"))
            })
    return result

def compare_digest(actual, expected):
    if not isinstance(actual, list) or not isinstance(expected, list):
        return False
    if len(actual) != len(expected):
        return False
    for i in range(len(expected)):
        a = actual[i]
        e = expected[i]
        if str(a.get("slug")) != str(e.get("slug")):
            return False
        if str(a.get("event_title")) != str(e.get("event_title")):
            return False
        if str(a.get("top_market_title")) != str(e.get("top_market_title")):
            return False
        if not approx_equal(parse_float(a.get("yes_price")), e.get("yes_price"), tol=1e-6):
            return False
        if not approx_equal(parse_float(a.get("oneDayPriceChange")), e.get("oneDayPriceChange"), tol=1e-6):
            return False
        if not approx_equal(parse_float(a.get("volume24hr")), e.get("volume24hr"), tol=1e-6):
            return False
    return True

def compute_movers_24h(events):
    rows = []
    for e in events:
        vol24 = parse_float(e.get("volume24hr"))
        if vol24 >= 10000.0:
            markets = e.get("markets", []) or []
            for m in markets:
                change = parse_float(m.get("oneDayPriceChange"))
                abs_change = abs(change)
                rows.append({
                    "event_slug": e.get("slug"),
                    "event_title": e.get("title"),
                    "market_title": get_market_title(m),
                    "yes_price": get_yes_price_from_market(m),
                    "oneDayPriceChange": change,
                    "volume24hr": vol24,
                    "abs_change": abs_change
                })
    rows.sort(key=lambda r: r["abs_change"], reverse=True)
    top5 = rows[:5]
    return top5

def parse_csv_with_header(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None

def compare_movers_csv(actual_path, expected_rows):
    header, rows = parse_csv_with_header(actual_path)
    if header is None or rows is None:
        return False
    expected_header = ["event_slug", "event_title", "market_title", "yes_price", "oneDayPriceChange", "volume24hr"]
    if header != expected_header:
        return False
    if len(rows) != len(expected_rows):
        return False
    for i, exp in enumerate(expected_rows):
        a = rows[i]
        if a.get("event_slug") != exp["event_slug"]:
            return False
        if a.get("event_title") != exp["event_title"]:
            return False
        if a.get("market_title") != exp["market_title"]:
            return False
        if not approx_equal(parse_float(a.get("yes_price")), exp["yes_price"], tol=1e-6):
            return False
        if not approx_equal(parse_float(a.get("oneDayPriceChange")), exp["oneDayPriceChange"], tol=1e-6):
            return False
        if not approx_equal(parse_float(a.get("volume24hr")), exp["volume24hr"], tol=1e-6):
            return False
    return True

def compute_portfolio_expected(events, seed, trades):
    # Build current price lookup by (slug, outcome_norm) -> price
    price_map = {}
    for e in events:
        slug = e.get("slug")
        markets = e.get("markets", []) or []
        if not markets:
            continue
        # Map first market as None outcome
        first_market = markets[0]
        price_map[(str(slug).lower(), None)] = get_yes_price_from_market(first_market)
        # Map by outcome title
        for m in markets:
            title = get_market_title(m)
            outcome_norm = normalize_outcome(title)
            price_map[(str(slug).lower(), outcome_norm)] = get_yes_price_from_market(m)

    cash = parse_float(seed.get("cash"), default=0.0)
    positions = {}
    for p in seed.get("positions", []) or []:
        p_slug = p.get("slug")
        p_outcome = safe_outcome_str(p.get("outcome"))
        key = (str(p_slug).lower(), normalize_outcome(p_outcome))
        shares = parse_float(p.get("shares"), default=0.0)
        # Keep shares only; price will be current
        if key in positions:
            positions[key]["shares"] += shares
        else:
            positions[key] = {"slug": p_slug, "outcome": p_outcome, "shares": shares}

    # Apply trades
    for t in trades:
        action = (t.get("action") or "").strip().lower()
        slug = (t.get("slug") or "").strip()
        outcome = safe_outcome_str(t.get("outcome"))
        amount_type = (t.get("amount_type") or "").strip().lower()
        amount_value = parse_float(t.get("amount_value"), default=0.0)
        key = (slug.lower(), normalize_outcome(outcome))
        # Determine current price for this slug/outcome
        # Prefer exact outcome match, otherwise if outcome is None use None key
        price = None
        if key in price_map:
            price = price_map[key]
        elif (slug.lower(), None) in price_map:
            price = price_map[(slug.lower(), None)]
        else:
            price = 0.0

        if action == "buy" and amount_type == "usd":
            if price > 0:
                shares = amount_value / price
            else:
                shares = 0.0
            cash -= amount_value
            if key in positions:
                positions[key]["shares"] += shares
            else:
                positions[key] = {"slug": slug, "outcome": outcome, "shares": shares}
        elif action == "sell" and amount_type == "fraction":
            frac = amount_value
            if key not in positions:
                # Nothing to sell; skip
                continue
            existing_shares = positions[key]["shares"]
            shares_to_sell = existing_shares * frac
            proceeds = shares_to_sell * price
            cash += proceeds
            positions[key]["shares"] = existing_shares - shares_to_sell
            if positions[key]["shares"] <= 1e-12:
                # Remove near-zero positions
                del positions[key]
        else:
            # Unsupported; ignore
            continue

    # Build final positions list with current prices
    final_positions = []
    for key, pos in positions.items():
        slug_lower, outcome_norm = key
        slug = pos["slug"]
        outcome = pos["outcome"]
        price = None
        if key in price_map:
            price = price_map[key]
        elif (slug_lower, None) in price_map:
            price = price_map[(slug_lower, None)]
        else:
            price = 0.0
        final_positions.append({
            "slug": slug,
            "outcome": outcome if outcome is not None else None,
            "shares": pos["shares"],
            "price": price
        })

    # Compute total value
    total_value = cash + sum(p["shares"] * p["price"] for p in final_positions)
    return cash, final_positions, total_value

def parse_trades_csv(path):
    header, rows = parse_csv_with_header(path)
    if header is None:
        return []
    # Normalize keys expected: action,slug,outcome,amount_type,amount_value
    trades = []
    for r in rows:
        trades.append({
            "action": r.get("action"),
            "slug": r.get("slug"),
            "outcome": r.get("outcome"),
            "amount_type": r.get("amount_type"),
            "amount_value": r.get("amount_value")
        })
    return trades

def compare_portfolio_after(actual, exp_cash, exp_positions, exp_total_value, cash_tol=1e-2, pos_tol=1e-2, total_tol=1e-2):
    if not isinstance(actual, dict):
        return False
    if not approx_equal(parse_float(actual.get("cash")), exp_cash, tol=cash_tol):
        return False
    if "positions" not in actual or not isinstance(actual["positions"], list):
        return False
    # Build mapping for expected positions by slug+outcome
    exp_map = {(str(p["slug"]).lower(), normalize_outcome(p.get("outcome"))): p for p in exp_positions}
    act_map = {(str(p.get("slug")).lower(), normalize_outcome(safe_outcome_str(p.get("outcome")))): p for p in actual["positions"]}
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for key, ep in exp_map.items():
        ap = act_map[key]
        if not approx_equal(parse_float(ap.get("shares")), ep["shares"], tol=pos_tol):
            return False
        if not approx_equal(parse_float(ap.get("price")), ep["price"], tol=pos_tol):
            return False
    if not approx_equal(parse_float(actual.get("total_value")), exp_total_value, tol=total_tol):
        return False
    return True

def compare_portfolio_positions_csv(csv_path, exp_positions, tol=1e-2):
    header, rows = parse_csv_with_header(csv_path)
    if header is None or rows is None:
        return False
    expected_header = ["slug", "outcome", "shares", "current_price", "market_value"]
    if header != expected_header:
        return False
    # Build expected map
    exp_map = {(str(p["slug"]).lower(), normalize_outcome(p.get("outcome"))): p for p in exp_positions}
    # Build actual map
    act_map = {}
    for r in rows:
        slug = r.get("slug")
        outcome = safe_outcome_str(r.get("outcome"))
        key = (str(slug).lower(), normalize_outcome(outcome))
        act_map[key] = r
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for key, ep in exp_map.items():
        ar = act_map[key]
        a_shares = parse_float(ar.get("shares"))
        a_price = parse_float(ar.get("current_price"))
        a_value = parse_float(ar.get("market_value"))
        if not approx_equal(a_shares, ep["shares"], tol=tol):
            return False
        if not approx_equal(a_price, ep["price"], tol=tol):
            return False
        if not approx_equal(a_value, ep["shares"] * ep["price"], tol=tol):
            return False
    return True

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "watchlist_json_ok": False,
        "alerts_json_ok": False,
        "digest_politics_ok": False,
        "movers_csv_ok": False,
        "portfolio_after_ok": False,
        "portfolio_positions_csv_ok": False,
    }

    # Load inputs
    markets_path = os.path.join(input_dir, "markets.json")
    watchlist_spec_path = os.path.join(input_dir, "watchlist_spec.json")
    portfolio_seed_path = os.path.join(input_dir, "portfolio_seed.json")
    trades_csv_path = os.path.join(input_dir, "trades.csv")

    markets_json = load_json_file(markets_path)
    watchlist_spec = load_json_file(watchlist_spec_path)
    portfolio_seed = load_json_file(portfolio_seed_path)
    trades_rows = parse_trades_csv(trades_csv_path)

    events = parse_markets_json(markets_json if markets_json is not None else [])

    # 1) Watchlist + Alerts
    try:
        expected_watchlist = compute_watchlist_expected(events, watchlist_spec or [])
        wl_out_path = os.path.join(output_dir, "watchlist.json")
        alerts_out_path = os.path.join(output_dir, "alerts.json")
        if os.path.isfile(wl_out_path):
            wl_out = load_json_file(wl_out_path)
            if wl_out is not None and compare_watchlist(wl_out, expected_watchlist):
                checks["watchlist_json_ok"] = True
        if os.path.isfile(alerts_out_path):
            alerts_out = load_json_file(alerts_out_path)
            expected_alerts = compute_alerts_expected(expected_watchlist)
            if alerts_out is not None and compare_alerts(alerts_out, expected_alerts):
                checks["alerts_json_ok"] = True
    except Exception:
        pass

    # 2) Category Digest (politics)
    try:
        expected_digest = compute_digest_politics(events)
        digest_out_path = os.path.join(output_dir, "digest_politics.json")
        if os.path.isfile(digest_out_path):
            digest_out = load_json_file(digest_out_path)
            if digest_out is not None and compare_digest(digest_out, expected_digest):
                checks["digest_politics_ok"] = True
    except Exception:
        pass

    # 3) 24h Movers Report
    try:
        expected_movers = compute_movers_24h(events)
        movers_out_path = os.path.join(output_dir, "movers_24h.csv")
        if os.path.isfile(movers_out_path):
            if compare_movers_csv(movers_out_path, expected_movers):
                checks["movers_csv_ok"] = True
    except Exception:
        pass

    # 4) Paper Trading Simulation
    try:
        exp_cash, exp_positions, exp_total_value = compute_portfolio_expected(events, portfolio_seed or {"cash": 0, "positions": []}, trades_rows or [])
        portfolio_after_path = os.path.join(output_dir, "portfolio_after.json")
        portfolio_positions_path = os.path.join(output_dir, "portfolio_positions.csv")
        if os.path.isfile(portfolio_after_path):
            portfolio_after_out = load_json_file(portfolio_after_path)
            if portfolio_after_out is not None and compare_portfolio_after(portfolio_after_out, exp_cash, exp_positions, exp_total_value, cash_tol=1e-2, pos_tol=1e-2, total_tol=1e-2):
                checks["portfolio_after_ok"] = True
        if os.path.isfile(portfolio_positions_path):
            if compare_portfolio_positions_csv(portfolio_positions_path, exp_positions, tol=1e-2):
                checks["portfolio_positions_csv_ok"] = True
    except Exception:
        pass

    # Compute reward as fraction of checks passed
    passed = sum(1 for k, v in checks.items() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0
    # Enforce baseline: if all false or outputs missing, reward 0.0 is already ensured
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()