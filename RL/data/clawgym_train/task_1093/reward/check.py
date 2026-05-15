import csv
import json
import math
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_yaml_simple(text: str) -> Optional[Dict[str, Any]]:
    result: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            if current_list_key is None:
                return None
            val_str = line.lstrip()[2:].strip()
            val = _parse_yaml_scalar(val_str)
            if not isinstance(result.get(current_list_key), list):
                result[current_list_key] = []
            result[current_list_key].append(val)
            continue
        if ":" in line:
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            val_str = val_part.strip()
            if not val_str:
                current_list_key = key
                result[key] = []
            else:
                current_list_key = None
                result[key] = _parse_yaml_scalar(val_str)
        else:
            return None
    return result


def _parse_yaml_scalar(s: str) -> Any:
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    try:
        if s.lower().startswith("0x"):
            raise ValueError
        i = int(s)
        return i
    except Exception:
        pass
    try:
        f = float(s)
        return f
    except Exception:
        pass
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return s


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _to_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        return float(str(s).strip())
    except Exception:
        return None


def _to_int_strict_or_float_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            if abs(s - round(s)) < 1e-9:
                return int(round(s))
            return None
        st = str(s).strip()
        if st.isdigit() or (st.startswith("-") and st[1:].isdigit()):
            return int(st)
        fv = float(st)
        if abs(fv - round(fv)) < 1e-9:
            return int(round(fv))
        return None
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= tol
    return False


def _normalize_bool_text(s: str) -> Optional[bool]:
    if not isinstance(s, str):
        return None
    sl = s.strip().lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    return None


def _compute_expected(sales_rows: List[Dict[str, str]]) -> Tuple[Dict[str, Any], Dict[str, Any], List[Tuple[str, float]]]:
    date_start = _parse_date("2025-06-01")
    date_end = _parse_date("2025-06-30")
    include_channels = {"online", "market"}
    high_margin_min = 0.15
    top_n = 3

    filtered: List[Dict[str, str]] = []
    for r in sales_rows:
        d = _parse_date(r.get("date", ""))
        if d is None:
            continue
        if d < date_start or d > date_end:
            continue
        ch = (r.get("channel") or "").strip()
        if ch not in include_channels:
            continue
        units = _to_int_strict_or_float_int(r.get("units"))
        unit_price = _to_float(r.get("unit_price"))
        cost_per_unit = _to_float(r.get("cost_per_unit"))
        if units is None or unit_price is None or cost_per_unit is None:
            continue
        filtered.append(r)

    prod_orders: Dict[str, set] = {}
    prod_units: Dict[str, int] = {}
    prod_revenue: Dict[str, float] = {}
    prod_gp: Dict[str, float] = {}
    for r in filtered:
        prod = (r.get("product") or "").strip()
        oid = (r.get("order_id") or "").strip()
        units = int(float(r.get("units")))
        unit_price = float(r.get("unit_price"))
        cost_per_unit = float(r.get("cost_per_unit"))
        rev = unit_price * units
        gp = (unit_price - cost_per_unit) * units
        prod_orders.setdefault(prod, set()).add(oid)
        prod_units[prod] = prod_units.get(prod, 0) + units
        prod_revenue[prod] = prod_revenue.get(prod, 0.0) + rev
        prod_gp[prod] = prod_gp.get(prod, 0.0) + gp

    expected_products: Dict[str, Dict[str, Any]] = {}
    for prod in prod_revenue.keys():
        revenue = prod_revenue[prod]
        gp = prod_gp.get(prod, 0.0)
        gm_pct = gp / revenue if revenue != 0 else 0.0
        is_high = gm_pct >= high_margin_min
        expected_products[prod] = {
            "product": prod,
            "orders": len(prod_orders.get(prod, set())),
            "units": prod_units.get(prod, 0),
            "revenue": revenue,
            "gross_margin_pct": gm_pct,
            "is_high_margin": is_high,
        }

    ranking = sorted(((p, expected_products[p]["revenue"]) for p in expected_products.keys()), key=lambda x: (-x[1], x[0]))

    chan_orders: Dict[str, set] = {}
    chan_units: Dict[str, int] = {}
    chan_revenue: Dict[str, float] = {}
    for r in filtered:
        ch = (r.get("channel") or "").strip()
        oid = (r.get("order_id") or "").strip()
        units = int(float(r.get("units")))
        unit_price = float(r.get("unit_price"))
        rev = unit_price * units
        chan_orders.setdefault(ch, set()).add(oid)
        chan_units[ch] = chan_units.get(ch, 0) + units
        chan_revenue[ch] = chan_revenue.get(ch, 0.0) + rev
    expected_channels: Dict[str, Dict[str, Any]] = {}
    for ch in include_channels:
        orders_count = len(chan_orders.get(ch, set()))
        revenue = chan_revenue.get(ch, 0.0)
        avg_order_value = (revenue / orders_count) if orders_count != 0 else 0.0
        expected_channels[ch] = {
            "channel": ch,
            "orders": orders_count,
            "units": chan_units.get(ch, 0),
            "revenue": revenue,
            "avg_order_value": avg_order_value,
        }

    top_products = ranking[:top_n]

    return expected_products, expected_channels, top_products


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "config_date_end_updated": 0.0,
        "config_include_channels_updated": 0.0,
        "config_top_n_updated": 0.0,
        "config_high_margin_min_updated": 0.0,
        "product_summary_exists_and_columns": 0.0,
        "product_summary_sorted_by_revenue_desc": 0.0,
        "product_summary_values_correct": 0.0,
        "channel_summary_exists_and_columns": 0.0,
        "channel_summary_values_correct": 0.0,
        "top_products_format": 0.0,
        "top_products_values_correct": 0.0,
        "used_config_matches_required": 0.0,
        "used_config_copied_from_config": 0.0,
    }

    config_path = workspace / "config" / "marketing.yaml"
    used_config_path = workspace / "output" / "used_config.yaml"
    sales_path = workspace / "input" / "sales.csv"
    product_summary_path = workspace / "output" / "product_summary.csv"
    channel_summary_path = workspace / "output" / "channel_summary.csv"
    top_products_path = workspace / "output" / "top_products.json"

    required_date_start = "2025-06-01"
    required_date_end = "2025-06-30"
    required_include_channels = ["online", "market"]
    required_top_n = 3
    required_high_margin_min = 0.15

    config_text = _read_text(config_path)
    parsed_config: Optional[Dict[str, Any]] = None
    if config_text is not None:
        parsed_config = _parse_yaml_simple(config_text) or None
    if parsed_config is not None:
        if str(parsed_config.get("date_end")) == required_date_end:
            scores["config_date_end_updated"] = 1.0
        inc = parsed_config.get("include_channels")
        if isinstance(inc, list):
            inc_strs = [str(x) for x in inc]
            if len(inc_strs) == 2 and set(inc_strs) == set(required_include_channels):
                scores["config_include_channels_updated"] = 1.0
        tn = parsed_config.get("top_n")
        if _to_int_strict_or_float_int(tn) == required_top_n:
            scores["config_top_n_updated"] = 1.0
        hmm = parsed_config.get("high_margin_min")
        hmmf = _to_float(hmm)
        if hmmf is not None and _approx_equal(hmmf, required_high_margin_min, tol=1e-9):
            scores["config_high_margin_min_updated"] = 1.0

    sales_rows = _load_csv_dicts(sales_path)

    expected_products: Optional[Dict[str, Any]] = None
    expected_channels: Optional[Dict[str, Any]] = None
    expected_top_products: Optional[List[Tuple[str, float]]] = None

    if sales_rows is not None:
        ep, ec, tp = _compute_expected(sales_rows)
        expected_products = ep
        expected_channels = ec
        expected_top_products = tp

    prod_ok_columns = False
    prod_sorted_ok = False
    prod_values_ok = False
    prod_rows = _load_csv_dicts(product_summary_path)
    expected_prod_columns = ["product", "orders", "units", "revenue", "gross_margin_pct", "is_high_margin"]
    if prod_rows is not None:
        try:
            with product_summary_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        if header == expected_prod_columns:
            prod_ok_columns = True

        if expected_products is not None and header == expected_prod_columns:
            file_products = [row["product"] for row in prod_rows]
            expected_sorted_products = [p for p, _ in sorted(
                ((p, expected_products[p]["revenue"]) for p in expected_products.keys()),
                key=lambda x: (-x[1], x[0])
            )]
            if file_products == expected_sorted_products:
                prod_sorted_ok = True

            all_values_match = True
            if len(prod_rows) != len(expected_products):
                all_values_match = False
            else:
                row_by_product = {row["product"]: row for row in prod_rows}
                for prod in expected_products.keys():
                    if prod not in row_by_product:
                        all_values_match = False
                        break
                    row = row_by_product[prod]
                    exp = expected_products[prod]
                    orders_val = _to_int_strict_or_float_int(row.get("orders"))
                    if orders_val is None or orders_val != int(exp["orders"]):
                        all_values_match = False
                        break
                    units_val = _to_int_strict_or_float_int(row.get("units"))
                    if units_val is None or units_val != int(exp["units"]):
                        all_values_match = False
                        break
                    revenue_val = _to_float(row.get("revenue"))
                    if revenue_val is None or not _approx_equal(revenue_val, float(exp["revenue"]), tol=1e-6):
                        all_values_match = False
                        break
                    gmp_val = _to_float(row.get("gross_margin_pct"))
                    if gmp_val is None or gmp_val < 0.0 or gmp_val > 1.0 or not _approx_equal(gmp_val, float(exp["gross_margin_pct"]), tol=1e-6):
                        all_values_match = False
                        break
                    ih_str = row.get("is_high_margin")
                    ih_bool = _normalize_bool_text(ih_str if ih_str is not None else "")
                    if not isinstance(ih_str, str) or ih_str.strip() not in ("true", "false"):
                        all_values_match = False
                        break
                    if ih_bool is None or ih_bool != bool(exp["is_high_margin"]):
                        all_values_match = False
                        break
            if all_values_match:
                prod_values_ok = True

    scores["product_summary_exists_and_columns"] = 1.0 if prod_ok_columns else 0.0
    scores["product_summary_sorted_by_revenue_desc"] = 1.0 if prod_sorted_ok else 0.0
    scores["product_summary_values_correct"] = 1.0 if prod_values_ok else 0.0

    chan_ok_columns = False
    chan_values_ok = False
    chan_rows = _load_csv_dicts(channel_summary_path)
    expected_chan_columns = ["channel", "orders", "units", "revenue", "avg_order_value"]
    if chan_rows is not None:
        try:
            with channel_summary_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        if header == expected_chan_columns:
            chan_ok_columns = True
        if expected_channels is not None and header == expected_chan_columns:
            row_by_channel = {row["channel"]: row for row in chan_rows}
            expected_channels_set = set(expected_channels.keys())
            if set(row_by_channel.keys()) == expected_channels_set and len(row_by_channel) == len(expected_channels_set):
                all_chan_ok = True
                for ch, exp in expected_channels.items():
                    row = row_by_channel.get(ch)
                    if row is None:
                        all_chan_ok = False
                        break
                    orders_val = _to_int_strict_or_float_int(row.get("orders"))
                    units_val = _to_int_strict_or_float_int(row.get("units"))
                    revenue_val = _to_float(row.get("revenue"))
                    aov_val = _to_float(row.get("avg_order_value"))
                    if (
                        orders_val is None
                        or units_val is None
                        or revenue_val is None
                        or aov_val is None
                    ):
                        all_chan_ok = False
                        break
                    if orders_val != int(exp["orders"]):
                        all_chan_ok = False
                        break
                    if units_val != int(exp["units"]):
                        all_chan_ok = False
                        break
                    if not _approx_equal(revenue_val, float(exp["revenue"]), tol=1e-6):
                        all_chan_ok = False
                        break
                    if not _approx_equal(aov_val, float(exp["avg_order_value"]), tol=1e-6):
                        all_chan_ok = False
                        break
                if all_chan_ok:
                    chan_values_ok = True

    scores["channel_summary_exists_and_columns"] = 1.0 if chan_ok_columns else 0.0
    scores["channel_summary_values_correct"] = 1.0 if chan_values_ok else 0.0

    tp_format_ok = False
    tp_values_ok = False
    tp_json = _safe_json_load(top_products_path)
    if isinstance(tp_json, list):
        schema_ok = True
        for item in tp_json:
            if not isinstance(item, dict):
                schema_ok = False
                break
            if "product" not in item or "revenue" not in item:
                schema_ok = False
                break
            if not isinstance(item["product"], str):
                schema_ok = False
                break
            if not isinstance(item["revenue"], (int, float)):
                schema_ok = False
                break
        if schema_ok:
            tp_format_ok = True
        if expected_top_products is not None and schema_ok:
            req_n = 3
            if len(tp_json) == req_n:
                all_ok = True
                for i, (exp_prod, exp_rev) in enumerate(expected_top_products):
                    if i >= req_n:
                        break
                    item = tp_json[i]
                    if item["product"] != exp_prod:
                        all_ok = False
                        break
                    if not _approx_equal(float(item["revenue"]), float(exp_rev), tol=1e-6):
                        all_ok = False
                        break
                if all_ok:
                    tp_values_ok = True

    scores["top_products_format"] = 1.0 if tp_format_ok else 0.0
    scores["top_products_values_correct"] = 1.0 if tp_values_ok else 0.0

    used_config_text = _read_text(used_config_path)
    parsed_used_config: Optional[Dict[str, Any]] = None
    if used_config_text is not None:
        parsed_used_config = _parse_yaml_simple(used_config_text) or None

    if parsed_used_config is not None:
        ok = True
        if str(parsed_used_config.get("date_start")) != required_date_start:
            ok = False
        if str(parsed_used_config.get("date_end")) != required_date_end:
            ok = False
        inc = parsed_used_config.get("include_channels")
        if not (isinstance(inc, list) and len(inc) == 2 and set(str(x) for x in inc) == set(required_include_channels)):
            ok = False
        tn = _to_int_strict_or_float_int(parsed_used_config.get("top_n"))
        if tn != required_top_n:
            ok = False
        hmm = _to_float(parsed_used_config.get("high_margin_min"))
        if hmm is None or not _approx_equal(hmm, required_high_margin_min, tol=1e-9):
            ok = False
        if ok:
            scores["used_config_matches_required"] = 1.0

    if parsed_config is not None and parsed_used_config is not None:
        if parsed_config == parsed_used_config:
            scores["used_config_copied_from_config"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()