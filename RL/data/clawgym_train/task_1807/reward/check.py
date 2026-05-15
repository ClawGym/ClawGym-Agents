import json
import os
import sys
import csv
from math import isclose

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_trending_csv": False,
        "trending_header_ok": False,
        "trending_rows_ok": False,
        "has_holders_report": False,
        "holders_report_ok": False,
        "has_alerts_json": False,
        "alerts_ok": False,
    }

    # Load inputs deterministically
    config_path = os.path.join(input_dir, "config.json")
    dex_pairs_path = os.path.join(input_dir, "dex_pairs.json")
    holders_path = os.path.join(input_dir, "holders.json")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        now_ms = _to_float(config.get("now_ms"))
        if now_ms is None:
            raise ValueError("now_ms missing or invalid in config.json")
    except Exception:
        now_ms = None

    try:
        with open(dex_pairs_path, "r", encoding="utf-8") as f:
            dex_pairs_data = json.load(f)
    except Exception:
        dex_pairs_data = None

    try:
        with open(holders_path, "r", encoding="utf-8") as f:
            holders_data = json.load(f)
    except Exception:
        holders_data = None

    # Compute expected artifacts if inputs are available
    expected_trending = []
    expected_holders = {}
    expected_alerts = {"early_gem": [], "second_wave": []}

    if now_ms is not None and isinstance(dex_pairs_data, (list, dict)):
        pairs_list = _extract_pairs(dex_pairs_data)
        # Filter base chain and compute expected stats
        rows = []
        for p in pairs_list:
            if str(p.get("chainId", "")).lower() != "base":
                continue
            base_token = p.get("baseToken") or {}
            addr = str(base_token.get("address") or "").lower()
            symbol = str(base_token.get("symbol") or "")
            if not addr:
                # skip pairs without a token address
                continue
            score = _compute_score(p, now_ms)
            age_h = _compute_age_h(p, now_ms)
            age_category = _age_category(age_h)
            vol1h = _to_float(_get_nested(p, ["volume", "h1"])) or 0.0
            liq_usd = _to_float(_get_nested(p, ["liquidity", "usd"])) or 0.0
            buys = _to_float(_get_nested(p, ["txns", "h1", "buys"])) or 0.0
            sells = _to_float(_get_nested(p, ["txns", "h1", "sells"])) or 0.0
            total = buys + sells
            buy_ratio_val = (buys / total) if total > 0 else 0.0
            buy_ratio_str = f"{buy_ratio_val:.3f}"
            change_1h = _to_float(_get_nested(p, ["priceChange", "h1"])) or 0.0
            change_24h = _to_float(_get_nested(p, ["priceChange", "h24"])) or 0.0
            mcap = _to_float(p.get("marketCap"))

            rows.append({
                "address": addr,
                "symbol": symbol,
                "score": int(score),
                "age_category": age_category,
                "vol1h": vol1h,
                "liq_usd": liq_usd,
                "buy_ratio_str": buy_ratio_str,
                "change_1h": change_1h,
                "change_24h": change_24h,
                "mcap": mcap,
            })

        # Sort by score desc, then address asc
        rows.sort(key=lambda r: (-r["score"], r["address"]))
        # Build expected trending with rank
        expected_trending = []
        for i, r in enumerate(rows, start=1):
            expected_trending.append({
                "rank": i,
                **r
            })

    if isinstance(holders_data, dict):
        expected_holders = _compute_holders_report(holders_data)

    if expected_trending and expected_holders is not None:
        # Compute alerts from expected_trending and expected_holders
        early = []
        second = []
        for r in expected_trending:
            addr = r["address"]
            score = r["score"]
            age_cat = r["age_category"]
            if age_cat == "early" and score >= 60:
                early.append(addr)
            if age_cat == "second_wave" and score >= 70:
                second.append(addr)
        # Apply holder risk filters
        def passes_holder_filter(address):
            info = expected_holders.get(address)
            if not info:
                # If holder data missing for a candidate, it should not pass filter (conservative)
                return False
            if info["top5_pct"] > 40.00:
                return False
            if bool(info["any_single_gt_15"]):
                return False
            return True

        early_f = sorted([a for a in early if passes_holder_filter(a)])
        second_f = sorted([a for a in second if passes_holder_filter(a)])
        expected_alerts = {"early_gem": early_f, "second_wave": second_f}

    # Validate outputs

    # trending.csv
    trending_path = os.path.join(output_dir, "trending.csv")
    if os.path.isfile(trending_path):
        checks["has_trending_csv"] = True
        try:
            with open(trending_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows_out = list(reader)
            if rows_out:
                header = rows_out[0]
                expected_header = ["rank","address","symbol","score","age_category","vol1h","liq_usd","buy_ratio","change_1h","change_24h","mcap"]
                if header == expected_header:
                    checks["trending_header_ok"] = True
                # Validate rows
                out_data = []
                for r in rows_out[1:]:
                    if len(r) != len(expected_header):
                        out_data = None
                        break
                    # Build parsed record
                    rec = {
                        "rank": _to_int(r[0]),
                        "address": (r[1] or "").lower(),
                        "symbol": r[2],
                        "score": _to_int(r[3]),
                        "age_category": r[4],
                        "vol1h": _to_float(r[5]),
                        "liq_usd": _to_float(r[6]),
                        "buy_ratio_str": r[7],
                        "change_1h": _to_float(r[8]),
                        "change_24h": _to_float(r[9]),
                        "mcap": _to_float(r[10]) if r[10] != "" else None,
                    }
                    # If parse fails
                    if rec["rank"] is None or rec["score"] is None or rec["vol1h"] is None or rec["liq_usd"] is None or rec["change_1h"] is None or rec["change_24h"] is None:
                        out_data = None
                        break
                    out_data.append(rec)
                if out_data is not None and expected_trending is not None:
                    # Compare count and order/content
                    if len(out_data) == len(expected_trending):
                        all_ok = True
                        for got, exp in zip(out_data, expected_trending):
                            # rank sequential and matches
                            if got["rank"] != exp["rank"]:
                                all_ok = False
                                break
                            if got["address"] != exp["address"]:
                                all_ok = False
                                break
                            if got["symbol"] != exp["symbol"]:
                                all_ok = False
                                break
                            if got["score"] != exp["score"]:
                                all_ok = False
                                break
                            if got["age_category"] != exp["age_category"]:
                                all_ok = False
                                break
                            if not _num_equal(got["vol1h"], exp["vol1h"]):
                                all_ok = False
                                break
                            if not _num_equal(got["liq_usd"], exp["liq_usd"]):
                                all_ok = False
                                break
                            if got["buy_ratio_str"] != exp["buy_ratio_str"]:
                                all_ok = False
                                break
                            if not _num_equal(got["change_1h"], exp["change_1h"]):
                                all_ok = False
                                break
                            if not _num_equal(got["change_24h"], exp["change_24h"]):
                                all_ok = False
                                break
                            # mcap may be None in expected; treat None as missing/blank in CSV
                            if exp["mcap"] is None:
                                # If expected is None, CSV should be empty or None (we parsed empty to None)
                                if got["mcap"] is not None:
                                    all_ok = False
                                    break
                            else:
                                if not _num_equal(got["mcap"], exp["mcap"]):
                                    all_ok = False
                                    break
                        if all_ok:
                            checks["trending_rows_ok"] = True
        except Exception:
            pass

    # holders_report.json
    holders_report_path = os.path.join(output_dir, "holders_report.json")
    if os.path.isfile(holders_report_path):
        checks["has_holders_report"] = True
        try:
            with open(holders_report_path, "r", encoding="utf-8") as f:
                holders_out = json.load(f)
            if isinstance(holders_out, dict) and isinstance(expected_holders, dict):
                # Keys must match exactly
                out_keys = set(k.lower() for k in holders_out.keys())
                exp_keys = set(expected_holders.keys())
                if out_keys == exp_keys:
                    ok = True
                    for k in exp_keys:
                        v_out = holders_out.get(k) if k in holders_out else holders_out.get(k.upper(), None)
                        if not isinstance(v_out, dict):
                            ok = False
                            break
                        top5_pct_out = v_out.get("top5_pct")
                        any_gt15_out = v_out.get("any_single_gt_15")
                        exp_v = expected_holders[k]
                        # top5_pct numeric within rounding to 2 decimals
                        if not isinstance(any_gt15_out, bool):
                            ok = False
                            break
                        if not _num_equal_round(top5_pct_out, exp_v["top5_pct"], places=2):
                            ok = False
                            break
                        if any_gt15_out != exp_v["any_single_gt_15"]:
                            ok = False
                            break
                    if ok:
                        checks["holders_report_ok"] = True
        except Exception:
            pass

    # alerts.json
    alerts_path = os.path.join(output_dir, "alerts.json")
    if os.path.isfile(alerts_path):
        checks["has_alerts_json"] = True
        try:
            with open(alerts_path, "r", encoding="utf-8") as f:
                alerts_out = json.load(f)
            if isinstance(alerts_out, dict):
                eg = alerts_out.get("early_gem")
                sw = alerts_out.get("second_wave")
                if isinstance(eg, list) and isinstance(sw, list):
                    eg_norm = sorted([str(a).lower() for a in eg])
                    sw_norm = sorted([str(a).lower() for a in sw])
                    if eg_norm == sorted(expected_alerts.get("early_gem", [])) and sw_norm == sorted(expected_alerts.get("second_wave", [])):
                        checks["alerts_ok"] = True
        except Exception:
            pass

    # Compute reward
    # Only count checks that reflect actual validation, not mere existence
    scored_checks = [
        checks["has_trending_csv"],
        checks["trending_header_ok"],
        checks["trending_rows_ok"],
        checks["has_holders_report"],
        checks["holders_report_ok"],
        checks["has_alerts_json"],
        checks["alerts_ok"],
    ]
    passed = sum(1 for c in scored_checks if c)
    total = len(scored_checks)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output missing or invalid, ensure 0.0
    # If none of the three main files exist or nothing valid, reward should be 0
    if not (checks["trending_rows_ok"] or checks["holders_report_ok"] or checks["alerts_ok"]):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

def _extract_pairs(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("pairs"), list):
            return data["pairs"]
        # fallback: any key that contains a list of dicts
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []

def _get_nested(d, keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur

def _to_float(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        try:
            return float(x)
        except Exception:
            return None
    if isinstance(x, str):
        try:
            return float(x.strip())
        except Exception:
            return None
    return None

def _to_int(x):
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        try:
            return int(x)
        except Exception:
            return None
    if isinstance(x, str):
        try:
            return int(x.strip())
        except Exception:
            # handle float-like strings that should be ints
            try:
                f = float(x.strip())
                return int(f)
            except Exception:
                return None
    return None

def _compute_age_h(p, now_ms):
    created_ms = _to_float(p.get("pairCreatedAt"))
    if created_ms is None:
        return float("inf")
    return (now_ms - created_ms) / 3_600_000.0

def _age_category(age_h):
    # "early" if age_h < 0.75
    # "second_wave" if 0.75 <= age_h <= 3
    # "mid" if 3 < age_h <= 6
    # "late" if age_h > 6
    if age_h < 0.75:
        return "early"
    if 0.75 <= age_h <= 3:
        return "second_wave"
    if 3 < age_h <= 6:
        return "mid"
    return "late"

def _compute_score(p, now_ms):
    score = 0
    vol = _to_float(_get_nested(p, ["volume", "h1"])) or 0.0
    liq = _to_float(_get_nested(p, ["liquidity", "usd"])) or 0.0
    buys = _to_float(_get_nested(p, ["txns", "h1", "buys"])) or 0.0
    sells = _to_float(_get_nested(p, ["txns", "h1", "sells"])) or 0.0
    ch1h = _to_float(_get_nested(p, ["priceChange", "h1"])) or 0.0
    ch24h = _to_float(_get_nested(p, ["priceChange", "h24"])) or 0.0
    mcap = _to_float(p.get("marketCap")) or 0.0
    age_h = _compute_age_h(p, now_ms)

    # Volume (1h)
    if vol > 500_000:
        score += 25
    elif vol > 100_000:
        score += 15
    elif vol > 20_000:
        score += 8

    # Liquidity (USD)
    if liq > 100_000:
        score += 15
    elif liq > 30_000:
        score += 8

    # Buy pressure
    total = buys + sells
    if total > 0 and (buys / total) > 0.55:
        score += 15

    # Price momentum
    if ch1h > 20:
        score += 10
    elif ch1h > 5:
        score += 5
    if ch24h > 50:
        score += 10

    # Age window
    if 0.75 <= age_h <= 3:
        score += 15
    elif 0 <= age_h < 0.75:
        score += 10
    elif 3 < age_h <= 6:
        score += 5

    # Market cap sanity
    if 0 < mcap < 5_000_000:
        score += 5

    return int(min(score, 100))

def _compute_holders_report(holders_dict):
    # holders_dict: { token_address: [ {TokenHolderQuantity: <num>, ...}, ... ], ... }
    out = {}
    for addr, lst in holders_dict.items():
        addr_l = str(addr).lower()
        if not isinstance(lst, list):
            out[addr_l] = {"top5_pct": 0.0, "any_single_gt_15": False}
            continue
        quantities = []
        for h in lst:
            if isinstance(h, dict):
                q = h.get("TokenHolderQuantity")
                qf = _to_float(q)
                if qf is not None:
                    quantities.append(qf)
        total = sum(quantities)
        quantities_sorted = sorted(quantities, reverse=True)
        top5 = sum(quantities_sorted[:5]) if total > 0 else 0.0
        top5_pct = (top5 / total * 100.0) if total > 0 else 0.0
        # Round to 2 decimals as number
        top5_pct_rounded = round(top5_pct + 1e-12, 2)
        any_single_gt_15 = False
        if total > 0:
            for q in quantities:
                if (q / total * 100.0) > 15.0:
                    any_single_gt_15 = True
                    break
        out[addr_l] = {"top5_pct": top5_pct_rounded, "any_single_gt_15": any_single_gt_15}
    return out

def _num_equal(a, b, tol=1e-6):
    if a is None and b is None:
        return True
    if (a is None) != (b is None):
        return False
    try:
        return isclose(float(a), float(b), rel_tol=0, abs_tol=tol)
    except Exception:
        return False

def _num_equal_round(a, b, places=2):
    try:
        if a is None and b is None:
            return True
        if (a is None) != (b is None):
            return False
        ra = round(float(a), places)
        rb = round(float(b), places)
        return isclose(ra, rb, rel_tol=0, abs_tol=10**(-(places+1)))
    except Exception:
        return False

if __name__ == "__main__":
    main()