import json
import os
import sys
import csv
import re
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

# Increase precision for intermediate Decimal operations
getcontext().prec = 28

def to_decimal(x):
    try:
        if isinstance(x, (int, float)):
            return Decimal(str(x))
        elif isinstance(x, str):
            return Decimal(x)
        else:
            return Decimal(0)
    except Exception:
        return Decimal(0)

def q2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def parse_date(s):
    try:
        return date.fromisoformat(s)
    except Exception:
        return None

def rfc3339_like(s):
    # Basic RFC3339 pattern
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})$'
    return re.match(pattern, s) is not None

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                # skip invalid lines
                continue
    return rows

def monday_of(d):
    return d - timedelta(days=d.weekday())

def week_buckets_covering(date_start, date_end):
    first_start = monday_of(date_start)
    buckets = []
    cur = first_start
    while cur <= date_end:
        buckets.append((cur, cur + timedelta(days=6)))
        cur = cur + timedelta(days=7)
    return buckets

def build_qualifying_orders(orders, cfg):
    ds = parse_date(cfg.get("date_start", ""))
    de = parse_date(cfg.get("date_end", ""))
    if ds is None or de is None:
        return [], ds, de
    qualifying = []
    for o in orders:
        od = parse_date(o.get("order_date", ""))
        if od is None:
            continue
        if od < ds or od > de:
            continue
        if str(o.get("payment_status", "")).lower() != "paid":
            continue
        if str(o.get("status", "")).lower() in {"cancelled", "void", "fraud"}:
            continue
        items = o.get("items", []) or []
        # compute order_subtotal
        order_subtotal = Decimal(0)
        item_details = []
        for it in items:
            qty = to_decimal(it.get("quantity", 0))
            price = to_decimal(it.get("unit_price", 0))
            item_subtotal = qty * price
            order_subtotal += item_subtotal
            item_details.append({
                "sku": str(it.get("sku", "")),
                "quantity": int(it.get("quantity", 0)) if isinstance(it.get("quantity", 0), int) or str(it.get("quantity", "")).isdigit() else int(to_decimal(it.get("quantity", 0))),
                "unit_price": to_decimal(it.get("unit_price", 0)),
                "item_subtotal": item_subtotal
            })
        refunded = to_decimal(o.get("refunded_amount", 0))
        net_order = order_subtotal - refunded
        qualifying.append({
            "order_id": str(o.get("order_id", "")),
            "customer_id": str(o.get("customer_id", "")),
            "order_date": od,
            "order_subtotal": order_subtotal,
            "refunded": refunded,
            "net_order": net_order,
            "items": item_details
        })
    return qualifying, ds, de

def aggregate_by_customer(orders):
    agg = {}
    for o in orders:
        cid = o["customer_id"]
        a = agg.setdefault(cid, {
            "orders_count": 0,
            "total_items": 0,
            "order_subtotal_sum": Decimal(0),
            "refunded_total_sum": Decimal(0),
            "net_revenue_sum": Decimal(0),
        })
        a["orders_count"] += 1
        total_qty = 0
        for it in o["items"]:
            q = it.get("quantity", 0)
            try:
                total_qty += int(q)
            except Exception:
                total_qty += int(to_decimal(q))
        a["total_items"] += total_qty
        a["order_subtotal_sum"] += o["order_subtotal"]
        a["refunded_total_sum"] += o["refunded"]
        a["net_revenue_sum"] += o["net_order"]
    return agg

def aggregate_by_product(orders):
    # Returns dict sku -> {"items_sold": int, "net_revenue": Decimal}
    agg = {}
    for o in orders:
        order_subtotal = o["order_subtotal"]
        refunded = o["refunded"]
        for it in o["items"]:
            sku = str(it.get("sku", ""))
            qty = 0
            try:
                qty = int(it.get("quantity", 0))
            except Exception:
                qty = int(to_decimal(it.get("quantity", 0)))
            item_subtotal = it.get("item_subtotal", Decimal(0))
            if order_subtotal == 0:
                alloc = Decimal(0)
            else:
                # proportional allocation
                alloc = refunded * (item_subtotal / order_subtotal)
            item_net = item_subtotal - alloc
            a = agg.setdefault(sku, {"items_sold": 0, "net_revenue": Decimal(0)})
            a["items_sold"] += qty
            a["net_revenue"] += item_net
    return agg

def aggregate_by_week(orders, buckets):
    # buckets: list of (start_date, end_date)
    # return mapping (start, end) -> {"orders_count": int, "net_revenue": Decimal}
    res = {(s, e): {"orders_count": 0, "net_revenue": Decimal(0)} for (s, e) in buckets}
    for o in orders:
        d = o["order_date"]
        for (s, e) in buckets:
            if s <= d <= e:
                res[(s, e)]["orders_count"] += 1
                res[(s, e)]["net_revenue"] += o["net_order"]
                break
    return res

def csv_header_exact(path, expected_header):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            first = f.readline().strip()
            return first == expected_header
    except Exception:
        return False

def money_str_two_decimals(s):
    return isinstance(s, str) and re.match(r'^-?\d+\.\d{2}$', s) is not None

def parse_csv_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows

def validate_money_value(expected: Decimal, provided):
    # Returns (value_match, formatting_ok)
    # value_match: True if provided equals expected rounded to two decimals (numeric or string)
    # formatting_ok: True if provided is a string formatted with exactly two decimals OR
    #                if provided is numeric and when formatted to two decimals matches expected
    exp2 = q2(expected)
    if isinstance(provided, (int, float)):
        pv = to_decimal(provided)
        return (q2(pv) == exp2, True)
    if isinstance(provided, str):
        if not money_str_two_decimals(provided):
            # not two-decimal string formatting
            try:
                pv = to_decimal(provided)
                return (q2(pv) == exp2, False)
            except Exception:
                return (False, False)
        # two-decimal formatted string
        try:
            pv = to_decimal(provided)
            return (q2(pv) == exp2, True)
        except Exception:
            return (False, True)
    # other types unsupported
    return (False, False)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_revenue_by_customer_csv": False,
        "csv_header_correct": False,
        "csv_rows_correct": False,
        "csv_sorted_correct": False,
        "csv_monetary_two_decimals": False,

        "has_top_products_json": False,
        "top_products_length_correct": False,
        "top_products_values_correct": False,
        "top_products_sorted_correct": False,
        "top_products_monetary_format_ok": False,

        "has_weekly_summary_json": False,
        "weekly_buckets_cover_range": False,
        "weekly_buckets_alignment_contiguous": False,
        "weekly_values_correct": False,
        "weekly_monetary_format_ok": False,

        "has_notes_md": False,
        "notes_min_words": False,
        "notes_mentions_required": False,

        "has_report_manifest_json": False,
        "manifest_generated_at_rfc3339": False,
        "manifest_sources_ok": False,
        "manifest_outputs_ok": False,
    }

    # Load inputs
    orders_path = os.path.join(input_dir, "orders.jsonl")
    customers_path = os.path.join(input_dir, "customers.jsonl")
    products_path = os.path.join(input_dir, "products.json")
    config_path = os.path.join(input_dir, "report_config.json")

    try:
        orders = read_jsonl(orders_path)
        customers = read_jsonl(customers_path)
        products = read_json(products_path)
        cfg = read_json(config_path)
    except Exception:
        # If inputs cannot be read, no positive checks should pass
        pass

    # Build lookups
    customer_name_by_id = {}
    try:
        for c in customers:
            cid = str(c.get("customer_id", ""))
            nm = c.get("name", "Unknown")
            if not cid:
                continue
            customer_name_by_id[cid] = nm if isinstance(nm, str) and nm else "Unknown"
    except Exception:
        customer_name_by_id = {}

    product_meta_by_sku = {}
    try:
        if isinstance(products, dict):
            for sku, meta in products.items():
                pn = (meta or {}).get("product_name", "Unknown")
                cat = (meta or {}).get("category", "Uncategorized")
                pn = pn if isinstance(pn, str) and pn else "Unknown"
                cat = cat if isinstance(cat, str) and cat else "Uncategorized"
                product_meta_by_sku[str(sku)] = {"product_name": pn, "category": cat}
    except Exception:
        product_meta_by_sku = {}

    # Compute expected aggregates based on inputs
    qualifying_orders, date_start, date_end = build_qualifying_orders(orders, cfg if isinstance(cfg, dict) else {})
    cust_agg = aggregate_by_customer(qualifying_orders)
    prod_agg = aggregate_by_product(qualifying_orders)
    week_buckets = week_buckets_covering(date_start, date_end) if (date_start and date_end) else []
    week_agg = aggregate_by_week(qualifying_orders, week_buckets) if week_buckets else {}

    # 1) revenue_by_customer.csv checks
    rev_csv_path = os.path.join(output_dir, "revenue_by_customer.csv")
    if os.path.isfile(rev_csv_path):
        checks["has_revenue_by_customer_csv"] = True
        expected_header = "customer_id,customer_name,orders_count,total_items,order_subtotal_sum,refunded_total_sum,net_revenue_sum"
        if csv_header_exact(rev_csv_path, expected_header):
            checks["csv_header_correct"] = True
        try:
            rows = parse_csv_rows(rev_csv_path)
            # Must have one row per customer with at least one qualifying order
            expected_customers = set(k for k, v in cust_agg.items() if v["orders_count"] > 0)
            got_customers = set(r.get("customer_id", "") for r in rows)
            # Verify sets match
            sets_match = expected_customers == got_customers

            # Validate each row contents and monetary formatting
            all_rows_ok = True
            all_money_two_dec = True
            # Also collect rows for sorting validation
            # Convert expected numeric aggregates to q2 for money fields
            expected_list = []
            for cid, a in cust_agg.items():
                if a["orders_count"] <= 0:
                    continue
                expected_list.append((
                    cid,
                    q2(a["order_subtotal_sum"]),
                    q2(a["refunded_total_sum"]),
                    q2(a["net_revenue_sum"]),
                    a["orders_count"],
                    a["total_items"],
                ))
            # Sorting expected by net_revenue_sum desc then customer_id asc
            expected_list_sorted = sorted(expected_list, key=lambda x: (-float(x[2+0]), x[0]))  # x[2] net_revenue_sum
            # Build mapping for quick check
            exp_map = {cid: (orders_count, total_items, order_subtotal_sum, refunded_total_sum, net_revenue_sum)
                       for (cid, order_subtotal_sum, refunded_total_sum, net_revenue_sum, orders_count, total_items) in expected_list}
            # Validate rows
            for r in rows:
                cid = r.get("customer_id", "")
                cname = r.get("customer_name", "")
                oc_str = r.get("orders_count", "")
                ti_str = r.get("total_items", "")
                oss = r.get("order_subtotal_sum", "")
                rfs = r.get("refunded_total_sum", "")
                nrs = r.get("net_revenue_sum", "")
                if cid not in exp_map:
                    all_rows_ok = False
                    continue
                exp_orders_count, exp_total_items, exp_oss, exp_rfs, exp_nrs = exp_map[cid]
                # customer_name match or Unknown if missing
                expected_cname = customer_name_by_id.get(cid, "Unknown")
                if cname != expected_cname:
                    all_rows_ok = False
                # integer fields
                try:
                    if int(oc_str) != exp_orders_count:
                        all_rows_ok = False
                    if int(ti_str) != exp_total_items:
                        all_rows_ok = False
                except Exception:
                    all_rows_ok = False
                # monetary fields must be two-decimal strings and equal to expected q2
                if not money_str_two_decimals(oss) or not money_str_two_decimals(rfs) or not money_str_two_decimals(nrs):
                    all_money_two_dec = False
                # value checks
                try:
                    if q2(to_decimal(oss)) != q2(exp_oss):
                        all_rows_ok = False
                    if q2(to_decimal(rfs)) != q2(exp_rfs):
                        all_rows_ok = False
                    if q2(to_decimal(nrs)) != q2(exp_nrs):
                        all_rows_ok = False
                except Exception:
                    all_rows_ok = False

            checks["csv_rows_correct"] = sets_match and all_rows_ok
            checks["csv_monetary_two_decimals"] = all_money_two_dec

            # Sorting validation using provided rows order
            try:
                # Build actual list for sort check
                actual_list = []
                for r in rows:
                    cid = r.get("customer_id", "")
                    nrs = q2(to_decimal(r.get("net_revenue_sum", "0")))
                    actual_list.append((cid, nrs))
                # expected order keys (cid, net)
                exp_sorted_keys = [(cid, q2(nr)) for (cid, _, _, nr, _, _) in expected_list_sorted]
                # Compare sequences of cids sorted by net desc then cid asc
                actual_order = [cid for (cid, _) in sorted(actual_list, key=lambda x: (-float(x[1]), x[0]))]
                output_order = [r.get("customer_id", "") for r in rows]
                checks["csv_sorted_correct"] = (output_order == actual_order)
            except Exception:
                checks["csv_sorted_correct"] = False
        except Exception:
            pass

    # 2) top_products.json checks
    top_products_path = os.path.join(output_dir, "top_products.json")
    if os.path.isfile(top_products_path):
        checks["has_top_products_json"] = True
        try:
            tp = read_json(top_products_path)
            if isinstance(tp, list):
                # Validate length equals top_n_products
                try:
                    top_n = int(cfg.get("top_n_products", 0)) if isinstance(cfg, dict) else 0
                except Exception:
                    top_n = 0
                if len(tp) == top_n:
                    checks["top_products_length_correct"] = True

                # Build expected sorted list
                exp_products = []
                for sku, a in prod_agg.items():
                    net = q2(a["net_revenue"])
                    items_sold = a["items_sold"]
                    meta = product_meta_by_sku.get(sku, {"product_name": "Unknown", "category": "Uncategorized"})
                    exp_products.append({
                        "sku": sku,
                        "product_name": meta["product_name"],
                        "category": meta["category"],
                        "items_sold": items_sold,
                        "net_revenue": net
                    })
                # sort by net_revenue desc then sku asc
                exp_products_sorted = sorted(exp_products, key=lambda x: (-float(x["net_revenue"]), x["sku"]))
                exp_top = exp_products_sorted[:top_n] if top_n > 0 else []

                # Validate values and formatting
                values_ok = True
                monetary_ok = True
                sorted_ok = True

                # Check sorting of provided list: by net_revenue desc, tie sku asc
                try:
                    provided_order = []
                    for e in tp:
                        pr_net = e.get("net_revenue", 0)
                        pr_sku = str(e.get("sku", ""))
                        pr_net_dec = q2(to_decimal(pr_net))
                        provided_order.append((pr_sku, pr_net_dec))
                    computed_sorted = [x for x in sorted(provided_order, key=lambda x: (-float(x[1]), x[0]))]
                    sorted_ok = (provided_order == computed_sorted)
                except Exception:
                    sorted_ok = False

                # Compare with expected top
                if len(tp) == len(exp_top):
                    for i, e in enumerate(tp):
                        exp = exp_top[i] if i < len(exp_top) else None
                        if exp is None:
                            values_ok = False
                            break
                        # sku
                        if str(e.get("sku", "")) != exp["sku"]:
                            values_ok = False
                        # product_name/category
                        if e.get("product_name", "") != exp["product_name"]:
                            values_ok = False
                        if e.get("category", "") != exp["category"]:
                            values_ok = False
                        # items_sold
                        try:
                            if int(e.get("items_sold", -1)) != int(exp["items_sold"]):
                                values_ok = False
                        except Exception:
                            values_ok = False
                        # net_revenue money value and formatting
                        vm, fm = validate_money_value(exp["net_revenue"], e.get("net_revenue", 0))
                        if not vm:
                            values_ok = False
                        if not fm:
                            monetary_ok = False
                else:
                    # length mismatch already handled; keep values_ok default
                    pass

                checks["top_products_values_correct"] = values_ok
                checks["top_products_sorted_correct"] = sorted_ok
                checks["top_products_monetary_format_ok"] = monetary_ok
        except Exception:
            pass

    # 3) weekly_summary.json checks
    weekly_summary_path = os.path.join(output_dir, "weekly_summary.json")
    if os.path.isfile(weekly_summary_path):
        checks["has_weekly_summary_json"] = True
        try:
            ws = read_json(weekly_summary_path)
            if isinstance(ws, dict) and isinstance(ws.get("weeks"), list):
                weeks = ws["weeks"]
                # Validate coverage, non-overlap, Monday starts, contiguous
                coverage_ok = False
                contiguous_ok = True
                monetary_ok = True
                values_ok = True
                parsed = []
                for w in weeks:
                    sd = parse_date(str(w.get("start_date", "")))
                    ed = parse_date(str(w.get("end_date", "")))
                    if sd is None or ed is None:
                        contiguous_ok = False
                        values_ok = False
                        continue
                    parsed.append((sd, ed, w))
                if parsed:
                    # Monday starts and sd<=ed
                    for (sd, ed, w) in parsed:
                        if sd.weekday() != 0:
                            contiguous_ok = False
                        if sd > ed:
                            contiguous_ok = False
                    # sorted by start_date
                    parsed_sorted = sorted(parsed, key=lambda x: x[0])
                    # contiguous and non-overlapping
                    for i in range(1, len(parsed_sorted)):
                        prev = parsed_sorted[i-1]
                        cur = parsed_sorted[i]
                        if cur[0] != prev[1] + timedelta(days=1):
                            contiguous_ok = False
                    # coverage
                    if date_start and date_end:
                        first_start = parsed_sorted[0][0]
                        last_end = parsed_sorted[-1][1]
                        if first_start <= date_start and last_end >= date_end:
                            coverage_ok = True
                    # values correctness: recompute per our buckets (based on provided buckets)
                    # Build provided bucket mapping for quick lookup
                    provided_agg = {}
                    for (sd, ed, w) in parsed_sorted:
                        provided_agg[(sd, ed)] = {
                            "orders_count": int(w.get("orders_count", 0)) if isinstance(w.get("orders_count", 0), int) or str(w.get("orders_count", "")).isdigit() else 0,
                            "net_revenue": w.get("net_revenue", 0)
                        }
                    # recompute using provided buckets as boundaries
                    recomputed = aggregate_by_week(qualifying_orders, [(sd, ed) for (sd, ed, _) in parsed_sorted])
                    # validate counts and monetary
                    for (sd, ed), vals in recomputed.items():
                        prov = provided_agg.get((sd, ed))
                        if prov is None:
                            values_ok = False
                            continue
                        if int(prov["orders_count"]) != int(vals["orders_count"]):
                            values_ok = False
                        vm, fm = validate_money_value(q2(vals["net_revenue"]), prov["net_revenue"])
                        if not vm:
                            values_ok = False
                        if not fm:
                            monetary_ok = False
                checks["weekly_buckets_cover_range"] = coverage_ok
                checks["weekly_buckets_alignment_contiguous"] = contiguous_ok
                checks["weekly_values_correct"] = values_ok
                checks["weekly_monetary_format_ok"] = monetary_ok
        except Exception:
            pass

    # 4) notes.md checks
    notes_path = os.path.join(output_dir, "notes.md")
    if os.path.isfile(notes_path):
        checks["has_notes_md"] = True
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                txt = f.read()
            # at least 150 words
            words = re.findall(r'\b\w+\b', txt)
            if len(words) >= 150:
                checks["notes_min_words"] = True
            # mentions required items
            t = txt.lower()
            mentions = True
            # date range used
            ds_str = cfg.get("date_start", "") if isinstance(cfg, dict) else ""
            de_str = cfg.get("date_end", "") if isinstance(cfg, dict) else ""
            if not ds_str or not de_str or (ds_str not in txt) or (de_str not in txt):
                mentions = False
            # payment_status and status filters
            # require mention of "payment_status" and "paid"
            if ("payment_status" not in t) or ("paid" not in t):
                mentions = False
            # require mention of excluded statuses (at least the three keywords)
            need_statuses = ["cancelled", "void", "fraud"]
            for kw in need_statuses:
                if kw not in t:
                    mentions = False
                    break
            # proportional refund allocation method: look for "proportion" or "allocate" and "refund"
            if ("refund" not in t) or (("proportion" not in t) and ("allocate" not in t) and ("allocation" not in t)):
                mentions = False
            # "Assumptions" word presence (case-insensitive)
            if "assumptions" not in t:
                mentions = False
            checks["notes_mentions_required"] = mentions
        except Exception:
            pass

    # 5) report_manifest.json checks
    manifest_path = os.path.join(output_dir, "report_manifest.json")
    if os.path.isfile(manifest_path):
        checks["has_report_manifest_json"] = True
        try:
            man = read_json(manifest_path)
            if isinstance(man, dict):
                gen = man.get("generated_at")
                if isinstance(gen, str) and rfc3339_like(gen):
                    checks["manifest_generated_at_rfc3339"] = True
                sources = man.get("sources")
                outputs = man.get("outputs")
                # sources should list exactly the basenames of input files used
                expected_sources = {"orders.jsonl", "customers.jsonl", "products.json", "report_config.json"}
                if isinstance(sources, list):
                    src_set = set([os.path.basename(str(x)) for x in sources])
                    if src_set == expected_sources and len(sources) == 4:
                        checks["manifest_sources_ok"] = True
                # outputs should list the four outputs (excluding manifest itself)
                expected_outputs = [
                    "output/revenue_by_customer.csv",
                    "output/top_products.json",
                    "output/weekly_summary.json",
                    "output/notes.md",
                ]
                if isinstance(outputs, list):
                    outs = [str(x) for x in outputs]
                    if sorted(outs) == sorted(expected_outputs):
                        # and all exist
                        all_exist = all(os.path.isfile(os.path.join(workspace_root, x)) for x in outs)
                        if all_exist:
                            checks["manifest_outputs_ok"] = True
        except Exception:
            pass

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    # Ensure baseline: if no outputs at all, reward must be 0.0
    if not any([
        checks["has_revenue_by_customer_csv"],
        checks["has_top_products_json"],
        checks["has_weekly_summary_json"],
        checks["has_notes_md"],
        checks["has_report_manifest_json"],
    ]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()