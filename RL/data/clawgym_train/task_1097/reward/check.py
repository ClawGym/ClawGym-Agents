import csv
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_csv(path: Path) -> Tuple[List[Dict[str, str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, None
    except Exception as e:
        return [], f"csv_read_error:{e}"


def _safe_read_text(path: Path) -> Tuple[str, Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return "", f"text_read_error:{e}"


def _safe_read_json(path: Path) -> Tuple[Any, Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"json_read_error:{e}"


def _parse_product_catalog_yaml(yaml_text: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """
    Minimal YAML parser for the expected product catalog format:
    products:
      - name: "..."
        category: "..."
    Returns mapping: name -> category
    """
    lines = yaml_text.splitlines()
    products_section = False
    items: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    try:
        for raw in lines:
            line = raw.rstrip("\n")
            if not products_section:
                if line.strip() == "products:":
                    products_section = True
                continue
            # Inside products section
            if line.strip() == "":
                continue
            if line.startswith("  - "):
                # Start a new item
                if current:
                    items.append(current)
                current = {}
                rest = line[4:].strip()
                if rest:
                    # Expect key: "value"
                    if ":" in rest:
                        key, val = rest.split(":", 1)
                        key = key.strip()
                        val = val.strip()
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                        elif val.startswith("'") and val.endswith("'"):
                            val = val[1:-1]
                        current[key] = val
            elif line.startswith("    "):
                # continuation key under current item
                if current is None:
                    # malformed structure
                    continue
                rest = line.strip()
                if ":" in rest:
                    key, val = rest.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    elif val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    current[key] = val
            else:
                # Out of products list
                pass
        if current:
            items.append(current)
        mapping: Dict[str, str] = {}
        for it in items:
            name = it.get("name")
            category = it.get("category")
            if name is None or category is None:
                return None, "yaml_missing_fields"
            mapping[name] = category
        return mapping, None
    except Exception as e:
        return None, f"yaml_parse_error:{e}"


def _dynamic_import_pricing_rules(py_path: Path):
    try:
        spec = importlib.util.spec_from_file_location("pricing_rules_module", str(py_path))
        if spec is None or spec.loader is None:
            return None, "import_spec_error"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        # Validate expected attributes
        if not hasattr(module, "VALID_CODES") or not hasattr(module, "discount_amount") or not hasattr(module, "processing_fee"):
            return None, "import_missing_attributes"
        return module, None
    except Exception as e:
        return None, f"import_exception:{e}"


def _to_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, int):
            return val
        s = str(val).strip()
        return int(s)
    except Exception:
        try:
            f = float(str(val).strip())
            if abs(f - round(f)) < 1e-9:
                return int(round(f))
        except Exception:
            return None
    return None


def _to_float_2dec(val: Any) -> Optional[float]:
    try:
        f = float(str(val).strip())
        return round(f, 2)
    except Exception:
        return None


def _round2(x: float) -> float:
    return round(float(x), 2)


def _parse_transactions(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    required_cols = [
        "transaction_id",
        "date",
        "client_id",
        "product_name",
        "unit_price",
        "quantity",
        "discount_code",
        "payment_method",
        "status",
    ]
    if not rows:
        return [], "empty_or_unreadable_csv"
    # Verify headers include required columns
    missing = [c for c in required_cols if c not in rows[0]]
    if missing:
        return [], "missing_columns:" + ",".join(missing)
    parsed: List[Dict[str, Any]] = []
    try:
        for r in rows:
            unit_price = float(r["unit_price"])
            quantity = int(r["quantity"])
            d = {
                "transaction_id": r["transaction_id"],
                "date": r["date"],
                "client_id": r["client_id"],
                "product_name": r["product_name"],
                "unit_price": unit_price,
                "quantity": quantity,
                "discount_code": r["discount_code"].strip() if r.get("discount_code") is not None else "",
                "payment_method": r["payment_method"],
                "status": r["status"],
            }
            parsed.append(d)
        return parsed, None
    except Exception as e:
        return [], f"transactions_parse_error:{e}"


def _compute_expected(transactions: List[Dict[str, Any]], catalog_map: Dict[str, str], rules_module) -> Dict[str, Any]:
    # unknown products
    unknown_products = [t["transaction_id"] for t in transactions if t["product_name"] not in catalog_map]
    # unknown discount codes
    present_codes = set()
    for t in transactions:
        code = (t.get("discount_code") or "").strip()
        if code != "":
            present_codes.add(code)
    valid_codes = set(getattr(rules_module, "VALID_CODES", set()))
    unknown_discount_codes = sorted(list(present_codes - valid_codes))

    # Filter known products
    known_tx = [t for t in transactions if t["product_name"] in catalog_map]
    # Category aggregations
    cat_aggs: Dict[str, Dict[str, Any]] = {}
    # Client aggregations
    cli_aggs: Dict[str, Dict[str, Any]] = {}

    def ensure_cat(cat: str) -> Dict[str, Any]:
        if cat not in cat_aggs:
            cat_aggs[cat] = {
                "category": cat,
                "total_transactions": 0,
                "completed_transactions": 0,
                "refunded_transactions": 0,
                "gross_completed": 0.0,
                "discounts_applied": 0.0,
                "processing_fees": 0.0,
                "net_completed_revenue": 0.0,
                "refunded_gross": 0.0,
                "net_revenue_after_refunds": 0.0,
                "avg_order_value_completed": 0.0,
            }
        return cat_aggs[cat]

    def ensure_cli(cid: str) -> Dict[str, Any]:
        if cid not in cli_aggs:
            cli_aggs[cid] = {
                "client_id": cid,
                "sessions_completed": 0,
                "gross_completed": 0.0,
                "discounts_applied": 0.0,
                "processing_fees": 0.0,
                "net_completed_revenue": 0.0,
                "refunds_count": 0,
                "refunds_gross": 0.0,
                "avg_net_per_completed_session": 0.0,
            }
        return cli_aggs[cid]

    for t in known_tx:
        category = catalog_map[t["product_name"]]
        status = t["status"]
        code = (t.get("discount_code") or "").strip()
        unit_price = float(t["unit_price"])
        qty = int(t["quantity"])
        payment_method = t["payment_method"]
        gross = unit_price * qty

        cat = ensure_cat(category)
        cli = ensure_cli(t["client_id"])

        cat["total_transactions"] += 1
        if status == "completed":
            cat["completed_transactions"] += 1
            cli["sessions_completed"] += 1

            if code in valid_codes:
                discount = float(rules_module.discount_amount(category, unit_price, qty, code))
            else:
                discount = 0.0
            post_discount = gross - discount
            fee = float(rules_module.processing_fee(post_discount, payment_method))

            cat["gross_completed"] += gross
            cat["discounts_applied"] += discount
            cat["processing_fees"] += fee
            net = gross - discount - fee
            cat["net_completed_revenue"] += net

            cli["gross_completed"] += gross
            cli["discounts_applied"] += discount
            cli["processing_fees"] += fee
            cli["net_completed_revenue"] += net
        elif status == "refunded":
            cat["refunded_transactions"] += 1
            cat["refunded_gross"] += gross
            cli["refunds_count"] += 1
            cli["refunds_gross"] += gross
        else:
            # Any other statuses are counted in total but not in metrics unless specified; not specified here
            pass

    # Finalize derived metrics and rounding
    for cat in cat_aggs.values():
        cat["gross_completed"] = _round2(cat["gross_completed"])
        cat["discounts_applied"] = _round2(cat["discounts_applied"])
        cat["processing_fees"] = _round2(cat["processing_fees"])
        cat["net_completed_revenue"] = _round2(cat["net_completed_revenue"])
        cat["refunded_gross"] = _round2(cat["refunded_gross"])
        cat["net_revenue_after_refunds"] = _round2(cat["net_completed_revenue"] - cat["refunded_gross"])
        comp = cat["completed_transactions"]
        if comp > 0:
            cat["avg_order_value_completed"] = _round2(cat["net_completed_revenue"] / comp)
        else:
            cat["avg_order_value_completed"] = 0.0

    for cli in cli_aggs.values():
        cli["gross_completed"] = _round2(cli["gross_completed"])
        cli["discounts_applied"] = _round2(cli["discounts_applied"])
        cli["processing_fees"] = _round2(cli["processing_fees"])
        cli["net_completed_revenue"] = _round2(cli["net_completed_revenue"])
        cli["refunds_gross"] = _round2(cli["refunds_gross"])
        sess = cli["sessions_completed"]
        if sess > 0:
            cli["avg_net_per_completed_session"] = _round2(cli["net_completed_revenue"] / sess)
        else:
            cli["avg_net_per_completed_session"] = 0.0

    expected = {
        "unknown_products": sorted(unknown_products),
        "unknown_discount_codes": sorted(unknown_discount_codes),
        "category_rows": list(cat_aggs.values()),
        "client_rows": list(cli_aggs.values()),
    }
    return expected


def _read_output_csv(path: Path, expected_columns: List[str]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    rows, err = _safe_read_csv(path)
    if err:
        return None, err
    # Check columns exactly match order
    header = rows[0].keys() if rows else expected_columns
    if list(header) != expected_columns:
        return None, "header_mismatch"
    return rows, None


def _normalize_category_rows(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Dict[str, Any]]]:
    result: Dict[str, Dict[str, Any]] = {}
    try:
        for r in rows:
            cat = r["category"]
            total_transactions = _to_int(r["total_transactions"])
            completed_transactions = _to_int(r["completed_transactions"])
            refunded_transactions = _to_int(r["refunded_transactions"])
            gross_completed = _to_float_2dec(r["gross_completed"])
            discounts_applied = _to_float_2dec(r["discounts_applied"])
            processing_fees = _to_float_2dec(r["processing_fees"])
            net_completed_revenue = _to_float_2dec(r["net_completed_revenue"])
            refunded_gross = _to_float_2dec(r["refunded_gross"])
            net_revenue_after_refunds = _to_float_2dec(r["net_revenue_after_refunds"])
            avg_order_value_completed = _to_float_2dec(r["avg_order_value_completed"])
            if None in [
                total_transactions,
                completed_transactions,
                refunded_transactions,
                gross_completed,
                discounts_applied,
                processing_fees,
                net_completed_revenue,
                refunded_gross,
                net_revenue_after_refunds,
                avg_order_value_completed,
            ]:
                return None
            result[cat] = {
                "category": cat,
                "total_transactions": int(total_transactions),  # type: ignore[arg-type]
                "completed_transactions": int(completed_transactions),  # type: ignore[arg-type]
                "refunded_transactions": int(refunded_transactions),  # type: ignore[arg-type]
                "gross_completed": float(gross_completed),  # type: ignore[arg-type]
                "discounts_applied": float(discounts_applied),  # type: ignore[arg-type]
                "processing_fees": float(processing_fees),  # type: ignore[arg-type]
                "net_completed_revenue": float(net_completed_revenue),  # type: ignore[arg-type]
                "refunded_gross": float(refunded_gross),  # type: ignore[arg-type]
                "net_revenue_after_refunds": float(net_revenue_after_refunds),  # type: ignore[arg-type]
                "avg_order_value_completed": float(avg_order_value_completed),  # type: ignore[arg-type]
            }
        return result
    except Exception:
        return None


def _normalize_client_rows(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Dict[str, Any]]]:
    result: Dict[str, Dict[str, Any]] = {}
    try:
        for r in rows:
            cid = r["client_id"]
            sessions_completed = _to_int(r["sessions_completed"])
            gross_completed = _to_float_2dec(r["gross_completed"])
            discounts_applied = _to_float_2dec(r["discounts_applied"])
            processing_fees = _to_float_2dec(r["processing_fees"])
            net_completed_revenue = _to_float_2dec(r["net_completed_revenue"])
            refunds_count = _to_int(r["refunds_count"])
            refunds_gross = _to_float_2dec(r["refunds_gross"])
            avg_net_per_completed_session = _to_float_2dec(r["avg_net_per_completed_session"])
            if None in [
                sessions_completed,
                gross_completed,
                discounts_applied,
                processing_fees,
                net_completed_revenue,
                refunds_count,
                refunds_gross,
                avg_net_per_completed_session,
            ]:
                return None
            result[cid] = {
                "client_id": cid,
                "sessions_completed": int(sessions_completed),  # type: ignore[arg-type]
                "gross_completed": float(gross_completed),  # type: ignore[arg-type]
                "discounts_applied": float(discounts_applied),  # type: ignore[arg-type]
                "processing_fees": float(processing_fees),  # type: ignore[arg-type]
                "net_completed_revenue": float(net_completed_revenue),  # type: ignore[arg-type]
                "refunds_count": int(refunds_count),  # type: ignore[arg-type]
                "refunds_gross": float(refunds_gross),  # type: ignore[arg-type]
                "avg_net_per_completed_session": float(avg_net_per_completed_session),  # type: ignore[arg-type]
            }
        return result
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "category_summary_exists_and_header": 0.0,
        "category_summary_values_correct": 0.0,
        "client_summary_exists_and_header": 0.0,
        "client_summary_values_correct": 0.0,
        "consistency_report_exists_and_schema": 0.0,
        "consistency_report_values_correct": 0.0,
    }

    # Paths
    tx_path = workspace / "input" / "transactions.csv"
    catalog_path = workspace / "input" / "product_catalog.yaml"
    pricing_path = workspace / "input" / "pricing_rules.py"

    out_cat_path = workspace / "outputs" / "category_summary.csv"
    out_cli_path = workspace / "outputs" / "client_summary.csv"
    out_consistency_path = workspace / "outputs" / "consistency_report.json"

    # Read inputs
    tx_rows, tx_err = _safe_read_csv(tx_path)
    cat_text, cat_err = _safe_read_text(catalog_path)
    rules_module, rules_err = _dynamic_import_pricing_rules(pricing_path)

    # Guard: if any essential input missing or malformed, we can still attempt existence/header checks on outputs
    parsed_tx: List[Dict[str, Any]] = []
    catalog_map: Optional[Dict[str, str]] = None
    if not tx_err:
        parsed_tx, parsed_tx_err = _parse_transactions(tx_rows)
        if parsed_tx_err:
            tx_err = parsed_tx_err
    if not cat_err:
        catalog_map, cat_parse_err = _parse_product_catalog_yaml(cat_text)
        if cat_parse_err:
            cat_err = cat_parse_err

    # Expected results
    expected: Optional[Dict[str, Any]] = None
    if (not tx_err) and (not cat_err) and (rules_err is None) and catalog_map is not None:
        expected = _compute_expected(parsed_tx, catalog_map, rules_module)
    # Output: category_summary.csv
    cat_expected_columns = [
        "category",
        "total_transactions",
        "completed_transactions",
        "refunded_transactions",
        "gross_completed",
        "discounts_applied",
        "processing_fees",
        "net_completed_revenue",
        "refunded_gross",
        "net_revenue_after_refunds",
        "avg_order_value_completed",
    ]
    cat_rows_read, cat_out_err = _read_output_csv(out_cat_path, cat_expected_columns)
    if not cat_out_err:
        scores["category_summary_exists_and_header"] = 1.0

    # Output: client_summary.csv
    cli_expected_columns = [
        "client_id",
        "sessions_completed",
        "gross_completed",
        "discounts_applied",
        "processing_fees",
        "net_completed_revenue",
        "refunds_count",
        "refunds_gross",
        "avg_net_per_completed_session",
    ]
    cli_rows_read, cli_out_err = _read_output_csv(out_cli_path, cli_expected_columns)
    if not cli_out_err:
        scores["client_summary_exists_and_header"] = 1.0

    # Output: consistency_report.json
    consistency_obj, consistency_err = _safe_read_json(out_consistency_path)
    if consistency_err is None and isinstance(consistency_obj, dict):
        # schema validation
        up = consistency_obj.get("unknown_products")
        ud = consistency_obj.get("unknown_discount_codes")
        if isinstance(up, list) and isinstance(ud, list) and all(isinstance(x, str) for x in up) and all(isinstance(x, str) for x in ud):
            scores["consistency_report_exists_and_schema"] = 1.0

    # Values correctness if we have expected
    if expected is not None:
        # Category rows
        if cat_rows_read is not None:
            norm_out = _normalize_category_rows(cat_rows_read)
            if norm_out is not None:
                # Build expected map
                exp_map: Dict[str, Dict[str, Any]] = {}
                for r in expected["category_rows"]:
                    # ensure currency fields are 2-dec rounded
                    exp_map[r["category"]] = {
                        "category": r["category"],
                        "total_transactions": r["total_transactions"],
                        "completed_transactions": r["completed_transactions"],
                        "refunded_transactions": r["refunded_transactions"],
                        "gross_completed": _round2(r["gross_completed"]),
                        "discounts_applied": _round2(r["discounts_applied"]),
                        "processing_fees": _round2(r["processing_fees"]),
                        "net_completed_revenue": _round2(r["net_completed_revenue"]),
                        "refunded_gross": _round2(r["refunded_gross"]),
                        "net_revenue_after_refunds": _round2(r["net_revenue_after_refunds"]),
                        "avg_order_value_completed": _round2(r["avg_order_value_completed"]),
                    }
                if set(norm_out.keys()) == set(exp_map.keys()):
                    ok = True
                    for k in exp_map.keys():
                        eo = exp_map[k]
                        ao = norm_out[k]
                        # compare integers
                        if eo["total_transactions"] != ao["total_transactions"]:
                            ok = False
                            break
                        if eo["completed_transactions"] != ao["completed_transactions"]:
                            ok = False
                            break
                        if eo["refunded_transactions"] != ao["refunded_transactions"]:
                            ok = False
                            break
                        # compare floats
                        float_fields = [
                            "gross_completed",
                            "discounts_applied",
                            "processing_fees",
                            "net_completed_revenue",
                            "refunded_gross",
                            "net_revenue_after_refunds",
                            "avg_order_value_completed",
                        ]
                        for ff in float_fields:
                            if _round2(float(eo[ff])) != _round2(float(ao[ff])):
                                ok = False
                                break
                        if not ok:
                            break
                    if ok:
                        scores["category_summary_values_correct"] = 1.0

        # Client rows
        if cli_rows_read is not None:
            norm_out = _normalize_client_rows(cli_rows_read)
            if norm_out is not None:
                exp_map: Dict[str, Dict[str, Any]] = {}
                for r in expected["client_rows"]:
                    exp_map[r["client_id"]] = {
                        "client_id": r["client_id"],
                        "sessions_completed": r["sessions_completed"],
                        "gross_completed": _round2(r["gross_completed"]),
                        "discounts_applied": _round2(r["discounts_applied"]),
                        "processing_fees": _round2(r["processing_fees"]),
                        "net_completed_revenue": _round2(r["net_completed_revenue"]),
                        "refunds_count": r["refunds_count"],
                        "refunds_gross": _round2(r["refunds_gross"]),
                        "avg_net_per_completed_session": _round2(r["avg_net_per_completed_session"]),
                    }
                if set(norm_out.keys()) == set(exp_map.keys()):
                    ok = True
                    for k in exp_map.keys():
                        eo = exp_map[k]
                        ao = norm_out[k]
                        if eo["sessions_completed"] != ao["sessions_completed"]:
                            ok = False
                            break
                        if eo["refunds_count"] != ao["refunds_count"]:
                            ok = False
                            break
                        float_fields = [
                            "gross_completed",
                            "discounts_applied",
                            "processing_fees",
                            "net_completed_revenue",
                            "refunds_gross",
                            "avg_net_per_completed_session",
                        ]
                        for ff in float_fields:
                            if _round2(float(eo[ff])) != _round2(float(ao[ff])):
                                ok = False
                                break
                        if not ok:
                            break
                    if ok:
                        scores["client_summary_values_correct"] = 1.0

        # Consistency report values
        if consistency_err is None and isinstance(consistency_obj, dict):
            up = consistency_obj.get("unknown_products")
            ud = consistency_obj.get("unknown_discount_codes")
            if isinstance(up, list) and isinstance(ud, list) and all(isinstance(x, str) for x in up) and all(isinstance(x, str) for x in ud):
                exp_up = sorted(expected["unknown_products"])
                exp_ud = sorted(expected["unknown_discount_codes"])
                if sorted(up) == exp_up and sorted(ud) == exp_ud:
                    scores["consistency_report_values_correct"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()