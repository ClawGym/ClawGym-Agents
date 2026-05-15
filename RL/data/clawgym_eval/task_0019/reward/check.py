import json
import os
import sys
import csv
from decimal import Decimal, ROUND_HALF_UP

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def d2(x):
    """Quantize Decimal to exactly 2 decimals with half up rounding."""
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def parse_decimal_maybe(value):
    """Parse numeric or numeric string to Decimal; return None if invalid."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None

def parse_rate_to_decimal(rate):
    """Parse rate which may be a string like '4.5%' or numeric; returns Decimal or None."""
    if rate is None:
        return None
    if isinstance(rate, str):
        s = rate.strip()
        if s.endswith("%"):
            s = s[:-1].strip()
        if not s:
            return None
        try:
            return Decimal(s)
        except Exception:
            return None
    try:
        return Decimal(str(rate))
    except Exception:
        return None

def format_rate_str(rate_dec):
    """Format Decimal percentage with exactly two decimals and a percent sign."""
    return f"{d2(rate_dec):.2f}%"

def is_valid_affiliate_url(url):
    return isinstance(url, str) and url.lower().startswith("http")

def read_input_catalog(input_path):
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, dict):
        if isinstance(data.get("queries"), list):
            return data["queries"]
        elif isinstance(data.get("data"), list):
            return data["data"]
        else:
            # Single query dict?
            if "keywords" in data and isinstance(data.get("results"), list):
                return [data]
            return []
    if isinstance(data, list):
        return data
    return []

def normalize_product(prod):
    # Title
    title = prod.get("title", "")
    # Price
    price_raw = prod.get("price")
    price_dec = parse_decimal_maybe(price_raw)
    if price_dec is None or price_dec <= 0:
        return None
    # Affiliate URL
    affiliate_url = prod.get("affiliateUrl")
    if not is_valid_affiliate_url(affiliate_url):
        return None
    # Shop
    shop = prod.get("shop") or {}
    shop_name = shop.get("name")
    shop_domain = shop.get("domain")
    if not (isinstance(shop_name, str) and shop_name.strip()) or not (isinstance(shop_domain, str) and shop_domain.strip()):
        return None

    # Cashback
    cb = prod.get("cashback") or {}
    rate_dec = parse_rate_to_decimal(cb.get("rate"))
    amount_dec = parse_decimal_maybe(cb.get("amount"))
    # Compute missing fields
    if amount_dec is None and rate_dec is not None:
        # amount = price * rate / 100
        amount_dec = d2(price_dec * rate_dec / Decimal("100"))
    elif rate_dec is None and amount_dec is not None:
        # rate = amount / price * 100
        rate_dec = d2((amount_dec / price_dec) * Decimal("100"))
    elif amount_dec is None and rate_dec is None:
        amount_dec = Decimal("0")
        rate_dec = Decimal("0")

    amount_dec = d2(amount_dec)
    rate_str = format_rate_str(rate_dec)

    effective_price = d2(price_dec - amount_dec)

    return {
        "title": str(title),
        "shop_name": str(shop_name),
        "shop_domain": str(shop_domain),
        "price_dec": price_dec,  # original price as Decimal
        "price_str": f"{d2(price_dec):.2f}",
        "cashback_amount_dec": amount_dec,
        "cashback_amount_str": f"{amount_dec:.2f}",
        "cashback_rate_str": rate_str,
        "effective_price_dec": effective_price,
        "effective_price_str": f"{effective_price:.2f}",
        "affiliate_url": affiliate_url,
    }

def compute_expected(catalog_queries):
    expected_rows = []  # list of dicts for CSV rows
    summary_queries = []  # list of per-query summaries
    all_valid_products = []  # list of tuples (query_str, normalized_prod)

    for q in catalog_queries:
        query_str = q.get("keywords")
        if query_str is None:
            query_str = q.get("query")
        if query_str is None:
            query_str = ""
        results = q.get("results")
        if not isinstance(results, list):
            results = []

        normalized = []
        for prod in results:
            norm = normalize_product(prod)
            if norm is not None:
                normalized.append(norm)
                all_valid_products.append((query_str, norm))

        # Sort for top deals: effective_price asc, cashback_amount desc, shop_name alphabetical
        sorted_norm = sorted(
            normalized,
            key=lambda p: (
                p["effective_price_dec"],
                Decimal("-1") * p["cashback_amount_dec"],  # higher cashback first
                p["shop_name"].lower(),
            ),
        )

        # Select top 3
        top_n = sorted_norm[:3]

        # Emit CSV rows
        rank = 1
        for p in top_n:
            expected_rows.append({
                "query": query_str,
                "rank": str(rank),
                "title": p["title"],
                "shop_name": p["shop_name"],
                "shop_domain": p["shop_domain"],
                "price": p["price_str"],
                "cashback_rate": p["cashback_rate_str"],
                "cashback_amount": p["cashback_amount_str"],
                "effective_price": p["effective_price_str"],
                "affiliate_url": p["affiliate_url"],
            })
            rank += 1

        # Summary per-query
        count = len(normalized)
        if count > 0:
            avg_price = d2(sum(p["price_dec"] for p in normalized) / Decimal(count))
            avg_eff = d2(sum(p["effective_price_dec"] for p in normalized) / Decimal(count))
        else:
            avg_price = d2(Decimal("0"))
            avg_eff = d2(Decimal("0"))

        # best_shop_by_count among top selection
        best_shop = ""
        if top_n:
            counts = {}
            for p in top_n:
                counts[p["shop_name"]] = counts.get(p["shop_name"], 0) + 1
            # max count, tie-breaker alphabetical
            max_count = max(counts.values())
            candidates = [name for name, c in counts.items() if c == max_count]
            best_shop = sorted(candidates, key=lambda s: s.lower())[0]

        summary_queries.append({
            "query": query_str,
            "total_results_considered": count,
            "average_price": float(avg_price),
            "average_effective_price": float(avg_eff),
            "best_shop_by_count": best_shop,
        })

    # Global lowest effective deal
    global_best = None
    if all_valid_products:
        # Sorting with same tie-breakers
        global_best = sorted(
            all_valid_products,
            key=lambda qp: (
                qp[1]["effective_price_dec"],
                Decimal("-1") * qp[1]["cashback_amount_dec"],
                qp[1]["shop_name"].lower(),
            ),
        )[0]
        gb_query, gb_prod = global_best
        global_best_obj = {
            "query": gb_query,
            "title": gb_prod["title"],
            "shop_name": gb_prod["shop_name"],
            "effective_price": float(gb_prod["effective_price_dec"]),
            "effective_price_str": gb_prod["effective_price_str"],  # for string formatting check
        }
    else:
        global_best_obj = {
            "query": "",
            "title": "",
            "shop_name": "",
            "effective_price": float(d2(Decimal("0"))),
            "effective_price_str": f"{d2(Decimal('0')):.2f}",
        }

    return expected_rows, summary_queries, global_best_obj

def validate_csv(csv_path, expected_rows):
    checks = {
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_content_ok": False,
    }
    expected_header = "query,rank,title,shop_name,shop_domain,price,cashback_rate,cashback_amount,effective_price,affiliate_url"
    if not os.path.isfile(csv_path):
        return checks, []
    checks["csv_exists"] = True

    # Read raw first line for header comparison
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            first_line = f.readline().rstrip("\n").rstrip("\r")
            checks["csv_header_ok"] = (first_line == expected_header)
    except Exception:
        return checks, []

    actual_rows = []
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Ensure header names exactly match expected when DictReader parsed
            if reader.fieldnames != expected_header.split(","):
                # If header mismatch, content cannot be ok
                return checks, []
            for row in reader:
                # Keep all fields as-is (strings)
                actual_rows.append({
                    "query": row.get("query", ""),
                    "rank": row.get("rank", ""),
                    "title": row.get("title", ""),
                    "shop_name": row.get("shop_name", ""),
                    "shop_domain": row.get("shop_domain", ""),
                    "price": row.get("price", ""),
                    "cashback_rate": row.get("cashback_rate", ""),
                    "cashback_amount": row.get("cashback_amount", ""),
                    "effective_price": row.get("effective_price", ""),
                    "affiliate_url": row.get("affiliate_url", ""),
                })
    except Exception:
        return checks, []

    # Compare exact sequence and values
    checks["csv_content_ok"] = (actual_rows == expected_rows)

    return checks, actual_rows

def validate_summary_json(json_path, expected_summary_queries, expected_global_best):
    checks = {
        "summary_exists": False,
        "summary_queries_correct": False,
        "global_best_correct": False,
        "cross_file_consistency": False,  # will be set later when CSV rows available
    }
    if not os.path.isfile(json_path):
        return checks, None
    checks["summary_exists"] = True

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return checks, None

    # Validate structure and content for queries
    queries = data.get("queries")
    if isinstance(queries, list) and len(queries) == len(expected_summary_queries):
        # Map by query string for comparison
        actual_by_query = {}
        ok = True
        for item in queries:
            if not isinstance(item, dict):
                ok = False
                break
            q = item.get("query", "")
            actual_by_query[q] = item
        # Now compare each expected
        for exp in expected_summary_queries:
            aq = actual_by_query.get(exp["query"])
            if aq is None:
                ok = False
                break
            # total_results_considered
            if aq.get("total_results_considered") != exp["total_results_considered"]:
                ok = False
                break
            # average_price and average_effective_price: numeric and equal to rounded expected
            ap = aq.get("average_price")
            aep = aq.get("average_effective_price")
            try:
                ap_num = float(ap)
                aep_num = float(aep)
            except Exception:
                ok = False
                break
            if ap_num != exp["average_price"] or aep_num != exp["average_effective_price"]:
                ok = False
                break
            # best_shop_by_count exact string match
            if aq.get("best_shop_by_count") != exp["best_shop_by_count"]:
                ok = False
                break
        checks["summary_queries_correct"] = ok
    else:
        checks["summary_queries_correct"] = False

    # Validate global lowest effective deal
    gb = data.get("global_lowest_effective_deal")
    if isinstance(gb, dict):
        gb_ok = True
        if gb.get("query") != expected_global_best["query"]:
            gb_ok = False
        if gb.get("title") != expected_global_best["title"]:
            gb_ok = False
        if gb.get("shop_name") != expected_global_best["shop_name"]:
            gb_ok = False
        # effective_price can be number or string; must equal expected value rounded to 2 decimals
        eff = gb.get("effective_price")
        eff_ok = False
        # Try number compare
        try:
            eff_num = float(eff)
            if eff_num == expected_global_best["effective_price"]:
                eff_ok = True
        except Exception:
            eff_ok = False
        # If not numeric match, try string exact two-decimal match
        if not eff_ok and isinstance(eff, str):
            if eff == expected_global_best["effective_price_str"]:
                eff_ok = True
        gb_ok = gb_ok and eff_ok
        checks["global_best_correct"] = gb_ok
    else:
        checks["global_best_correct"] = False

    return checks, gb if isinstance(gb, dict) else None

def compute_reward(checks):
    # Weighted sum; sum to 1.0
    weights = {
        "csv_exists": 0.10,
        "csv_header_ok": 0.15,
        "csv_content_ok": 0.45,
        "summary_exists": 0.10,
        "summary_queries_correct": 0.15,
        "global_best_correct": 0.05,
        # cross_file_consistency is not weighted; informative only
    }
    reward = 0.0
    for k, w in weights.items():
        if checks.get(k, False):
            reward += w
    # Ensure within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0
    return reward

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    catalog_path = os.path.join(input_dir, "catalog.json")
    csv_path = os.path.join(output_dir, "deals", "top_deals.csv")
    summary_path = os.path.join(output_dir, "deals", "summary.json")

    checks = {
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_content_ok": False,
        "summary_exists": False,
        "summary_queries_correct": False,
        "global_best_correct": False,
        "cross_file_consistency": False,
    }

    # Read input catalog (reference only)
    catalog_queries = read_input_catalog(catalog_path)
    expected_rows, expected_summary_queries, expected_global_best = compute_expected(catalog_queries)

    # Validate CSV
    csv_checks, actual_rows = validate_csv(csv_path, expected_rows)
    checks.update(csv_checks)

    # Validate summary JSON
    summary_checks, actual_gb = validate_summary_json(summary_path, expected_summary_queries, expected_global_best)
    checks.update(summary_checks)

    # Cross-file consistency: if both csv_content_ok and summary global best correct, ensure the top-1 row for that query matches the summary global best
    if checks["csv_content_ok"] and checks["global_best_correct"] and actual_gb is not None:
        # Find the top-1 row for the query in expected_rows (since actual_rows == expected_rows when csv_content_ok is True)
        target_query = actual_gb.get("query", "")
        target_title = actual_gb.get("title", "")
        target_shop = actual_gb.get("shop_name", "")
        # effective_price value comparison; get formatted string from CSV
        target_eff_value = None
        try:
            target_eff_value = float(actual_gb.get("effective_price"))
        except Exception:
            target_eff_value = None
        target_eff_str = None
        if target_eff_value is None and isinstance(actual_gb.get("effective_price"), str):
            target_eff_str = actual_gb.get("effective_price")
        else:
            # Build two-dec string from numeric
            if target_eff_value is not None:
                target_eff_str = f"{d2(Decimal(str(target_eff_value))):.2f}"

        # Locate rank 1 for query
        top1_row = None
        for row in actual_rows:
            if row.get("query") == target_query and row.get("rank") == "1":
                top1_row = row
                break
        if top1_row:
            eff_match = (top1_row.get("effective_price") == target_eff_str)
            if top1_row.get("title") == target_title and top1_row.get("shop_name") == target_shop and eff_match:
                checks["cross_file_consistency"] = True

    reward = compute_reward(checks)

    # No-op baseline: if outputs missing entirely, ensure reward is 0.0
    outputs_present = checks["csv_exists"] or checks["summary_exists"]
    if not outputs_present:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()