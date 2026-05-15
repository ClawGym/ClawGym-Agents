import json
import os
import sys
import csv
from decimal import Decimal, ROUND_HALF_UP

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_reorder_list": False,
        "reorder_columns_ok": False,
        "reorder_rows_match": False,
        "reorder_sorted": False,
        "reorder_formats_ok": False,
        "has_supplier_orders": False,
        "supplier_columns_ok": False,
        "supplier_rows_ok": False,
        "supplier_sorted": False,
        "supplier_formats_ok": False,
        "has_orders_dir": False,
        "orders_files_complete": False,
        "orders_values_ok": False,
        "orders_items_sorted": False,
    }

    # Helpers
    def norm_header(h):
        return (h or "").strip().lower().replace(" ", "").replace("_", "")

    def parse_decimal(val):
        if val is None:
            return None
        s = str(val).strip()
        if s == "":
            return None
        # strip common formatting
        s = s.replace(",", "").replace("$", "")
        try:
            return Decimal(s)
        except Exception:
            try:
                return Decimal(str(float(s)))
            except Exception:
                return None

    def parse_int(val):
        d = parse_decimal(val)
        if d is None:
            return None
        # treat as integer by truncating toward zero
        return int(d)

    def q2(x):
        # Quantize to 2 decimals with HALF_UP
        return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def fmt2(x):
        return f"{q2(x):.2f}"

    def load_csv_dicts(path):
        with open(path, newline="", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            rows = []
            for r in rdr:
                # normalize cell whitespace
                clean = {k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                rows.append(clean)
            return rdr.fieldnames, rows

    # Load inputs
    inv_path = os.path.join(input_dir, "inventory.csv")
    disc_path = os.path.join(input_dir, "bulk_discounts.csv")

    try:
        inv_fields, inv_rows = load_csv_dicts(inv_path)
    except Exception:
        inv_fields, inv_rows = None, None
    try:
        disc_fields, disc_rows = load_csv_dicts(disc_path)
    except Exception:
        disc_fields, disc_rows = None, None

    # Build column mappings for inventory
    inv_map = {}
    if inv_fields:
        norm_map = {norm_header(h): h for h in inv_fields}
        # required logical columns
        need = {
            "item": ["item", "sku", "product"],
            "supplier": ["supplier", "vendor"],
            "quantity": ["quantity", "qty", "onhand"],
            "reorderpoint": ["reorderpoint", "reorder_point", "rop"],
            "unitcost": ["unitcost", "unit_cost", "unitprice", "unit_price", "cost"]
        }
        for key, candidates in need.items():
            found = None
            for c in candidates:
                if c in norm_map:
                    found = norm_map[c]
                    break
            inv_map[key] = found

    # Build discount mapping
    discounts = {}
    if disc_fields and disc_rows:
        d_norm_map = {norm_header(h): h for h in disc_fields}
        d_supplier = d_norm_map.get("supplier")
        d_threshold = d_norm_map.get("threshold")
        d_percent = d_norm_map.get("discountpercent")
        if d_supplier and d_threshold and d_percent:
            for r in disc_rows:
                sup = (r.get(d_supplier) or "").strip()
                thr = parse_decimal(r.get(d_threshold))
                pct = parse_decimal(r.get(d_percent))
                if sup != "" and thr is not None and pct is not None:
                    discounts[sup] = (q2(thr), pct)  # keep percent as provided (may be int or decimal)
    # Compute expected reorder list
    expected_reorder = []
    able_to_compute = all(inv_map.get(k) for k in ["item", "supplier", "quantity", "reorderpoint", "unitcost"]) and (inv_rows is not None)

    if able_to_compute:
        for r in inv_rows:
            item = (r.get(inv_map["item"]) or "").strip()
            supplier = (r.get(inv_map["supplier"]) or "").strip()
            quantity = parse_int(r.get(inv_map["quantity"]))
            reorder_point = parse_int(r.get(inv_map["reorderpoint"]))
            unit_cost_dec = parse_decimal(r.get(inv_map["unitcost"]))
            if item == "" or supplier == "" or quantity is None or reorder_point is None or unit_cost_dec is None:
                continue
            # filter rule
            if quantity <= reorder_point:
                target_stock = 2 * reorder_point
                order_qty = target_stock - quantity
                line_total = q2(Decimal(order_qty) * unit_cost_dec)
                expected_reorder.append({
                    "Item": item,
                    "Supplier": supplier,
                    "Quantity": quantity,
                    "ReorderPoint": reorder_point,
                    "TargetStock": target_stock,
                    "OrderQty": order_qty,
                    "UnitCost_val": q2(unit_cost_dec),
                    "UnitCost": fmt2(unit_cost_dec),
                    "LineTotal_val": line_total,
                    "LineTotal": f"{line_total:.2f}",
                })
        # sort
        expected_reorder.sort(key=lambda x: (x["Supplier"], x["Item"]))

    # Expected suppliers aggregation
    expected_suppliers = []
    expected_supplier_map = {}  # supplier -> dict with computed aggregation and items
    if expected_reorder:
        # group
        by_supplier = {}
        for row in expected_reorder:
            by_supplier.setdefault(row["Supplier"], []).append(row)
        for sup, items in by_supplier.items():
            sku_count = len(items)
            total_before = q2(sum((it["LineTotal_val"] for it in items), Decimal("0.00")))
            # get discount rule
            if sup in discounts:
                threshold, disc_pct = discounts[sup]
            else:
                threshold, disc_pct = (q2(Decimal("0")), Decimal("0"))
            # discount applied?
            disc_applied = (total_before >= threshold and threshold > Decimal("0.00"))
            if disc_applied:
                disc_amount = q2(total_before * (Decimal(disc_pct) / Decimal("100")))
            else:
                disc_amount = q2(Decimal("0"))
            net_total = q2(total_before - disc_amount)
            expected_suppliers.append({
                "Supplier": sup,
                "SKUCount": sku_count,
                "TotalBeforeDiscount_val": total_before,
                "TotalBeforeDiscount": f"{total_before:.2f}",
                "Threshold_val": threshold,
                "Threshold": f"{threshold:.2f}",
                "DiscountPercent_val": Decimal(disc_pct),
                "DiscountPercent": str(Decimal(disc_pct).normalize()) if disc_pct != 0 else "0",
                "DiscountApplied_val": "Yes" if disc_applied else "No",
                "DiscountAmount_val": disc_amount,
                "DiscountAmount": f"{disc_amount:.2f}",
                "NetTotal_val": net_total,
                "NetTotal": f"{net_total:.2f}",
            })
            # items sorted by item name
            items_sorted = sorted(items, key=lambda x: x["Item"])
            expected_supplier_map[sup] = {
                "sku_count": sku_count,
                "total_before": total_before,
                "discount_applied_bool": disc_applied,
                "discount_percent": Decimal(disc_pct),
                "discount_amount": disc_amount,
                "net_total": net_total,
                "items": [{
                    "item": it["Item"],
                    "quantity": it["OrderQty"],
                    "unit_cost_val": it["UnitCost_val"],
                    "unit_cost": it["UnitCost"],
                    "line_total_val": it["LineTotal_val"],
                    "line_total": it["LineTotal"],
                } for it in items_sorted]
            }
        expected_suppliers.sort(key=lambda x: x["Supplier"])

    # Begin validations on outputs
    # 1) reorder_list.csv
    reorder_path = os.path.join(output_dir, "reorder_list.csv")
    if os.path.isfile(reorder_path):
        checks["has_reorder_list"] = True
        try:
            out_fields, out_rows = load_csv_dicts(reorder_path)
        except Exception:
            out_fields, out_rows = None, None
        required_cols = ["Item", "Supplier", "Quantity", "ReorderPoint", "TargetStock", "OrderQty", "UnitCost", "LineTotal"]
        if out_fields == required_cols:
            checks["reorder_columns_ok"] = True
        if out_rows is not None and able_to_compute:
            # Check row count and set membership
            # Convert actual rows to normalized list
            def row_key(row):
                return (row["Supplier"], row["Item"])
            # Verify sorting
            expected_order = [(r["Supplier"], r["Item"]) for r in expected_reorder]
            actual_order = [( (r.get("Supplier") or "").strip(), (r.get("Item") or "").strip() ) for r in out_rows]
            if actual_order == expected_order:
                checks["reorder_sorted"] = True
            # Build maps for value comparison
            if len(out_rows) == len(expected_reorder):
                # compare each row by position for strict sorting and by values
                all_match = True
                formats_ok = True
                for idx, (exp, act) in enumerate(zip(expected_reorder, out_rows)):
                    # Basic identity
                    if (act.get("Item") or "").strip() != exp["Item"]:
                        all_match = False
                        break
                    if (act.get("Supplier") or "").strip() != exp["Supplier"]:
                        all_match = False
                        break
                    # numeric comparisons
                    try:
                        q = parse_int(act.get("Quantity"))
                        rp = parse_int(act.get("ReorderPoint"))
                        ts = parse_int(act.get("TargetStock"))
                        oq = parse_int(act.get("OrderQty"))
                        uc_s = (act.get("UnitCost") or "").strip()
                        lt_s = (act.get("LineTotal") or "").strip()
                        uc_d = parse_decimal(uc_s)
                        lt_d = parse_decimal(lt_s)
                    except Exception:
                        all_match = False
                        break

                    if q != exp["Quantity"] or rp != exp["ReorderPoint"] or ts != exp["TargetStock"] or oq != exp["OrderQty"]:
                        all_match = False
                        break
                    # UnitCost and LineTotal numeric matches to 2 decimals
                    if uc_d is None or lt_d is None:
                        all_match = False
                        break
                    if q2(uc_d) != exp["UnitCost_val"] or q2(lt_d) != exp["LineTotal_val"]:
                        all_match = False
                        break
                    # formatting check: exactly 2 decimals
                    if not (uc_s.count(".") == 1 and len(uc_s.split(".")[1]) == 2):
                        formats_ok = False
                    if not (lt_s.count(".") == 1 and len(lt_s.split(".")[1]) == 2):
                        formats_ok = False
                if all_match:
                    checks["reorder_rows_match"] = True
                if formats_ok and checks["reorder_rows_match"]:
                    checks["reorder_formats_ok"] = True

    # 2) supplier_orders.csv
    supplier_orders_path = os.path.join(output_dir, "supplier_orders.csv")
    if os.path.isfile(supplier_orders_path):
        checks["has_supplier_orders"] = True
        try:
            so_fields, so_rows = load_csv_dicts(supplier_orders_path)
        except Exception:
            so_fields, so_rows = None, None
        required_so_cols = ["Supplier", "SKUCount", "TotalBeforeDiscount", "Threshold", "DiscountPercent", "DiscountApplied", "DiscountAmount", "NetTotal"]
        if so_fields == required_so_cols:
            checks["supplier_columns_ok"] = True
        if so_rows is not None and expected_suppliers:
            # sort check
            actual_suppliers_order = [ (r.get("Supplier") or "").strip() for r in so_rows ]
            expected_suppliers_order = [ r["Supplier"] for r in expected_suppliers ]
            if actual_suppliers_order == expected_suppliers_order:
                checks["supplier_sorted"] = True
            # rows content
            # Ensure supplier set matches exactly
            actual_set = set(actual_suppliers_order)
            expected_set = set(expected_suppliers_order)
            if actual_set == expected_set and len(actual_suppliers_order) == len(expected_suppliers_order):
                rows_ok = True
                formats_ok = True
                # Map actual by supplier for value checks (since order validated above, we can iterate in order)
                for exp, act in zip(expected_suppliers, so_rows):
                    sup = (act.get("Supplier") or "").strip()
                    if sup != exp["Supplier"]:
                        rows_ok = False
                        break
                    # SKUCount
                    try:
                        sku_count = parse_int(act.get("SKUCount"))
                    except Exception:
                        rows_ok = False
                        break
                    if sku_count != exp["SKUCount"]:
                        rows_ok = False
                        break
                    # TotalBeforeDiscount, Threshold, DiscountAmount, NetTotal must be 2-decimal formatted and numeric equal
                    for col, exp_val in [("TotalBeforeDiscount", exp["TotalBeforeDiscount_val"]),
                                         ("Threshold", exp["Threshold_val"]),
                                         ("DiscountAmount", exp["DiscountAmount_val"]),
                                         ("NetTotal", exp["NetTotal_val"])]:
                        sval = (act.get(col) or "").strip()
                        dval = parse_decimal(sval)
                        if dval is None or q2(dval) != exp_val:
                            rows_ok = False
                            break
                        if not (sval.count(".") == 1 and len(sval.split(".")[1]) == 2):
                            formats_ok = False
                    if not rows_ok:
                        break
                    # DiscountPercent numeric equality
                    dp_s = (act.get("DiscountPercent") or "").strip()
                    dp_d = parse_decimal(dp_s)
                    if dp_d is None:
                        rows_ok = False
                        break
                    # Compare numerically (not forcing 2 decimals)
                    if Decimal(dp_d) != exp["DiscountPercent_val"]:
                        rows_ok = False
                        break
                    # DiscountApplied
                    da = (act.get("DiscountApplied") or "").strip()
                    if da not in ("Yes", "No") or da != exp["DiscountApplied_val"]:
                        rows_ok = False
                        break
                if rows_ok:
                    checks["supplier_rows_ok"] = True
                if formats_ok and checks["supplier_rows_ok"]:
                    checks["supplier_formats_ok"] = True

    # 3) per-supplier JSON orders
    orders_dir = os.path.join(output_dir, "orders")
    if os.path.isdir(orders_dir):
        checks["has_orders_dir"] = True
        if expected_supplier_map:
            # Check files exist for each supplier
            expected_files = {}
            for sup in expected_supplier_map.keys():
                filename = sup.replace(" ", "_") + ".json"
                expected_files[sup] = os.path.join(orders_dir, filename)
            files_exist = all(os.path.isfile(p) for p in expected_files.values())
            if files_exist:
                checks["orders_files_complete"] = True
                all_values_ok = True
                all_items_sorted_ok = True
                for sup, path in expected_files.items():
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        all_values_ok = False
                        all_items_sorted_ok = False
                        break
                    # Validate keys exactly as specified
                    expected_keys = {"supplier", "sku_count", "total_before_discount", "discount_applied", "discount_percent", "discount_amount", "net_total", "items"}
                    if set(data.keys()) != expected_keys:
                        all_values_ok = False
                        all_items_sorted_ok = False
                        break
                    exp = expected_supplier_map[sup]
                    # supplier
                    if data.get("supplier") != sup:
                        all_values_ok = False
                        break
                    # sku_count
                    if not isinstance(data.get("sku_count"), int) or data.get("sku_count") != exp["sku_count"]:
                        all_values_ok = False
                        break
                    # discount_applied boolean
                    if not isinstance(data.get("discount_applied"), bool) or data.get("discount_applied") != exp["discount_applied_bool"]:
                        all_values_ok = False
                        break
                    # discount_percent numeric equality
                    dp = data.get("discount_percent")
                    if not isinstance(dp, (int, float)) and not isinstance(dp, Decimal):
                        all_values_ok = False
                        break
                    if Decimal(str(dp)) != exp["discount_percent"]:
                        all_values_ok = False
                        break
                    # totals: numbers with 2 decimals (we accept numbers, check value rounded)
                    for key, exp_val in [
                        ("total_before_discount", exp["total_before"]),
                        ("discount_amount", exp["discount_amount"]),
                        ("net_total", exp["net_total"]),
                    ]:
                        v = data.get(key)
                        if not isinstance(v, (int, float)) and not isinstance(v, Decimal):
                            all_values_ok = False
                            break
                        if q2(Decimal(str(v))) != exp_val:
                            all_values_ok = False
                            break
                    if not all_values_ok:
                        break
                    # items
                    items = data.get("items")
                    if not isinstance(items, list) or len(items) != exp["sku_count"]:
                        all_values_ok = False
                        all_items_sorted_ok = False
                        break
                    # Check sorted by item name
                    item_names = [it.get("item") for it in items]
                    if item_names != sorted(item_names):
                        all_items_sorted_ok = False
                    # Validate each item details against expected items
                    # Build expected map by item
                    exp_items_map = {it["item"]: it for it in exp["items"]}
                    for it in items:
                        if set(it.keys()) != {"item", "quantity", "unit_cost", "line_total"}:
                            all_values_ok = False
                            break
                        name = it.get("item")
                        if name not in exp_items_map:
                            all_values_ok = False
                            break
                        exp_it = exp_items_map[name]
                        # quantity int equals
                        if not isinstance(it.get("quantity"), int) or it.get("quantity") != exp_it["quantity"]:
                            all_values_ok = False
                            break
                        # unit_cost numeric equality to 2 decimals
                        uc = it.get("unit_cost")
                        lt = it.get("line_total")
                        if not isinstance(uc, (int, float)) and not isinstance(uc, Decimal):
                            all_values_ok = False
                            break
                        if not isinstance(lt, (int, float)) and not isinstance(lt, Decimal):
                            all_values_ok = False
                            break
                        if q2(Decimal(str(uc))) != exp_it["unit_cost_val"]:
                            all_values_ok = False
                            break
                        if q2(Decimal(str(lt))) != exp_it["line_total_val"]:
                            all_values_ok = False
                            break
                    if not all_values_ok:
                        break
                if all_values_ok:
                    checks["orders_values_ok"] = True
                if all_items_sorted_ok and checks["orders_values_ok"]:
                    checks["orders_items_sorted"] = True

    # Compute reward
    # No-op baseline: if output dir missing or no required artifacts, reward should be 0.0 (checks already False)
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = round(passed / total_checks, 6)

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()