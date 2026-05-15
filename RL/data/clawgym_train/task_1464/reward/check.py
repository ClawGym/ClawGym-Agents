import json
import csv
import sys
import re
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


ALLOWED_CHANNELS = {"phone", "email", "chat"}


def safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def safe_read_bytes(path: Path) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        return path.read_bytes(), None
    except Exception as e:
        return None, str(e)


def safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    text, err = safe_read_text(path)
    if err or text is None:
        return None, err or "read_error"
    try:
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def safe_load_jsonl(path: Path) -> Tuple[Optional[List[Any]], Optional[str]]:
    text, err = safe_read_text(path)
    if err or text is None:
        return None, err or "read_error"
    records = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception as e:
            return None, f"jsonl_parse_error_line_{i+1}: {e}"
    return records, None


def safe_load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames if reader.fieldnames is not None else []
            rows = list(reader)
            return header, rows, None
    except Exception as e:
        return None, None, str(e)


def compute_sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def compute_sha256_file(path: Path) -> Tuple[Optional[str], Optional[str]]:
    data, err = safe_read_bytes(path)
    if err or data is None:
        return None, err or "read_error"
    return compute_sha256_bytes(data), None


def canonicalize_path_string(p: str) -> str:
    s = p.replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    while "//" in s:
        s = s.replace("//", "/")
    return s


def extract_text_field(patterns: List[re.Pattern], text: str) -> Optional[str]:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


def parse_price_value_and_currency(text: str) -> Tuple[Optional[float], Optional[str]]:
    code_match = re.search(r'\b([A-Z]{3})\b', text)
    code = code_match.group(1) if code_match else None
    symbol = None
    if "€" in text:
        symbol = "EUR"
    elif "$" in text:
        symbol = "USD"
    num_match = re.search(r'([\d]{1,3}(?:[,]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)', text)
    value = None
    if num_match:
        num_str = num_match.group(1).replace(",", "")
        try:
            value = float(num_str)
        except:
            value = None
    currency = code if code else symbol
    return value, currency


def extract_shipping_days(text: str) -> Tuple[Optional[int], Optional[int]]:
    m = re.search(r'(\d+)\s*[-–—]\s*(\d+)\s*(?:business\s+)?days', text, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1)), int(m.group(2))
        except:
            return None, None
    m2 = re.search(r'(\d+)\s*(?:business\s+)?days', text, flags=re.IGNORECASE)
    if m2:
        try:
            v = int(m2.group(1))
            return v, v
        except:
            return None, None
    return None, None


def detect_support_channels(text: str) -> List[str]:
    channels = set()
    if re.search(r'[\w\.-]+@[\w\.-]+', text, flags=re.IGNORECASE):
        channels.add("email")
    if re.search(r'\bphone\b', text, flags=re.IGNORECASE) or re.search(r'\+\d[\d\-\s\(\)]+', text):
        channels.add("phone")
    if re.search(r'\bchat\b', text, flags=re.IGNORECASE):
        channels.add("chat")
    return sorted(channels)


def detect_returns(text: str) -> bool:
    return bool(re.search(r'\breturn', text, flags=re.IGNORECASE))


def extract_expected_from_html_file(path: Path, rel_path: str) -> Optional[Dict[str, Any]]:
    html, err = safe_read_text(path)
    if err or html is None:
        return None
    text = html
    order_id = extract_text_field([
        re.compile(r'Order\s*#:\s*([A-Z]+-\d+)\b', flags=re.IGNORECASE),
        re.compile(r'Order\s*Number\s*</dt>\s*<dd>\s*([^<]+)\s*</dd>', flags=re.IGNORECASE | re.DOTALL),
        re.compile(r'Order\s*Number\s*[:\-\s]\s*([A-Z]+-\d+)\b', flags=re.IGNORECASE),
        re.compile(r'Order\s*VM-\d+\b'),  # generic safeguard
        re.compile(r'Order\s+(?:Confirmation\s+-\s+.*?\s+Order\s+)?([A-Z]+-\d+)\b', flags=re.IGNORECASE),
    ], text)
    if order_id is None:
        # Fallback broader pattern
        m = re.search(r'\b([A-Z]{2}-\d{4,})\b', text)
        order_id = m.group(1) if m else None
    brand = extract_text_field([
        re.compile(r'Brand\s*:\s*([^<\n]+)', flags=re.IGNORECASE),
        re.compile(r'Brand\s*</dt>\s*<dd>\s*([^<]+)\s*</dd>', flags=re.IGNORECASE | re.DOTALL),
    ], text)
    product_name = extract_text_field([
        re.compile(r'(?:Item|Product)\s*:\s*([^<\n]+)', flags=re.IGNORECASE),
        re.compile(r'(?:Item|Product)\s*</dt>\s*<dd>\s*([^<]+)\s*</dd>', flags=re.IGNORECASE | re.DOTALL),
    ], text)
    price_text = extract_text_field([
        re.compile(r'Price\s*:\s*([^<\n]+)', flags=re.IGNORECASE),
        re.compile(r'Subtotal\s*</dt>\s*<dd>\s*([^<]+)\s*</dd>', flags=re.IGNORECASE | re.DOTALL),
    ], text)
    price_value = None
    currency = None
    if price_text:
        price_value, currency = parse_price_value_and_currency(price_text)
    explicit_currency = extract_text_field([
        re.compile(r'Currency\s*</dt>\s*<dd>\s*([^<]+)\s*</dd>', flags=re.IGNORECASE | re.DOTALL),
        re.compile(r'Currency\s*:\s*([A-Z]{3})', flags=re.IGNORECASE),
    ], text)
    if explicit_currency:
        explicit_currency = explicit_currency.strip()
        if re.fullmatch(r'[A-Z]{3}', explicit_currency):
            currency = explicit_currency
    taxes_text = extract_text_field([
        re.compile(r'Tax(?:es)?\s*:\s*([^<\n]+)', flags=re.IGNORECASE),
        re.compile(r'Tax(?:es)?\s*</dt>\s*<dd>\s*([^<]+)\s*</dd>', flags=re.IGNORECASE | re.DOTALL),
    ], text)
    taxes_value = None
    if taxes_text:
        taxes_value, _ = parse_price_value_and_currency(taxes_text)
    shipping_method = extract_text_field([
        re.compile(r'(?:Shipping\s*Method|Delivery)\s*:\s*([^<\n]+)', flags=re.IGNORECASE),
        re.compile(r'(?:Shipping\s*Method|Delivery)\s*</dt>\s*<dd>\s*([^<]+)\s*</dd>', flags=re.IGNORECASE | re.DOTALL),
    ], text)
    days_text = extract_text_field([
        re.compile(r'(?:Estimated\s*(?:Delivery|Arrival)\s*:\s*[^<\n]+)', flags=re.IGNORECASE),
        re.compile(r'(?:Estimated\s*(?:Delivery|Arrival)\s*</dt>\s*<dd>\s*[^<]+</dd>)', flags=re.IGNORECASE | re.DOTALL),
        re.compile(r'(?:\d+\s*[-–—]\s*\d+\s*(?:business\s+)?days)', flags=re.IGNORECASE),
    ], text)
    ship_min, ship_max = extract_shipping_days(days_text or text)
    support_channels = detect_support_channels(text)
    return_policy_present = detect_returns(text)
    checksum, _ = compute_sha256_file(path)
    result = {
        "order_id": order_id,
        "brand": brand,
        "product_name": product_name,
        "price_value": price_value,
        "currency": currency,
        "taxes_value": taxes_value,
        "shipping_method": shipping_method,
        "shipping_estimate_days_min": ship_min,
        "shipping_estimate_days_max": ship_max,
        "support_channels": support_channels,
        "return_policy_present": return_policy_present,
        "source_file": canonicalize_path_string(rel_path),
        "file_sha256": checksum,
    }
    return result


def coerce_float(v: Any) -> Optional[float]:
    try:
        if isinstance(v, bool):
            return None
        return float(v)
    except:
        return None


def coerce_int(v: Any) -> Optional[int]:
    try:
        if isinstance(v, bool):
            return None
        if isinstance(v, float) and abs(v - int(v)) > 1e-9:
            return None
        return int(v)
    except:
        return None


def load_state_mapping(path: Path) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    data, err = safe_load_json(path)
    if err or data is None:
        return None, err or "json_parse_error"
    mapping: Dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                mapping[canonicalize_path_string(k)] = v
            else:
                return None, "invalid_state_dict_entries"
        return mapping, None
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                return None, "invalid_state_list_item"
            p = None
            csum = None
            if "source_file" in item and "file_sha256" in item:
                p = item.get("source_file")
                csum = item.get("file_sha256")
            elif "path" in item and "sha256" in item:
                p = item.get("path")
                csum = item.get("sha256")
            if isinstance(p, str) and isinstance(csum, str):
                mapping[canonicalize_path_string(p)] = csum
            else:
                return None, "invalid_state_list_item_fields"
        return mapping, None
    else:
        return None, "invalid_state_type"


def compare_records(expected: Dict[str, Any], observed: Dict[str, Any]) -> bool:
    required_keys = [
        "order_id",
        "brand",
        "product_name",
        "price_value",
        "currency",
        "taxes_value",
        "shipping_method",
        "shipping_estimate_days_min",
        "shipping_estimate_days_max",
        "support_channels",
        "return_policy_present",
        "source_file",
        "file_sha256",
    ]
    for k in required_keys:
        if k not in observed:
            return False
    if not (isinstance(observed["order_id"], str) and observed["order_id"] == expected["order_id"]):
        return False
    if not (isinstance(observed["brand"], str) and observed["brand"] == expected["brand"]):
        return False
    if not (isinstance(observed["product_name"], str) and observed["product_name"] == expected["product_name"]):
        return False
    ov = coerce_float(observed["price_value"])
    ev = expected["price_value"]
    if ov is None or ev is None or abs(ov - ev) > 1e-6:
        return False
    if not (isinstance(observed["currency"], str) and isinstance(expected["currency"], str) and observed["currency"].upper() == expected["currency"].upper()):
        return False
    tv = coerce_float(observed["taxes_value"])
    tev = expected["taxes_value"]
    if tv is None or tev is None or abs(tv - tev) > 1e-6:
        return False
    if not (isinstance(observed["shipping_method"], str) and observed["shipping_method"] == expected["shipping_method"]):
        return False
    minv = coerce_int(observed["shipping_estimate_days_min"])
    maxv = coerce_int(observed["shipping_estimate_days_max"])
    if minv is None or maxv is None or minv != expected["shipping_estimate_days_min"] or maxv != expected["shipping_estimate_days_max"]:
        return False
    if not isinstance(observed["support_channels"], list):
        return False
    try:
        obs_channels = [str(x) for x in observed["support_channels"]]
    except Exception:
        return False
    if any(ch not in ALLOWED_CHANNELS for ch in obs_channels):
        return False
    if set(obs_channels) != set(expected["support_channels"]):
        return False
    if not isinstance(observed["return_policy_present"], bool) or observed["return_policy_present"] != expected["return_policy_present"]:
        return False
    obs_source = canonicalize_path_string(str(observed["source_file"]))
    if obs_source != expected["source_file"]:
        return False
    if not (isinstance(observed["file_sha256"], str) and len(observed["file_sha256"]) == 64 and observed["file_sha256"] == expected["file_sha256"]):
        return False
    return True


def load_sla_config(workspace: Path) -> Tuple[Optional[Dict[str, Dict[str, Dict[str, int]]]], Optional[str]]:
    sla_path = workspace / "input" / "brands_sla.json"
    data, err = safe_load_json(sla_path)
    if err or data is None:
        return None, err or "missing_sla"
    try:
        for brand, methods in data.items():
            if not isinstance(methods, dict):
                return None, "invalid_sla_structure"
            for method, bounds in methods.items():
                if not isinstance(bounds, dict):
                    return None, "invalid_sla_bounds_structure"
                if not all(k in bounds for k in ("min_days", "max_days")):
                    return None, "invalid_sla_bounds_keys"
                if not isinstance(bounds["min_days"], int) or not isinstance(bounds["max_days"], int):
                    return None, "invalid_sla_bounds_values"
        return data, None
    except Exception as e:
        return None, str(e)


def safe_extract_expected(path: Path, rel_path: str) -> Optional[Dict[str, Any]]:
    try:
        return extract_expected_from_html_file(path, rel_path)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "orders_jsonl_parsed_and_complete": 0.0,
        "orders_values_correct": 0.0,
        "orders_no_duplicate_for_same_checksum": 0.0,
        "state_json_contains_latest_checksums": 0.0,
        "alerts_json_correct": 0.0,
        "summary_by_brand_csv_correct": 0.0,
        "sla_consistency_across_outputs": 0.0,
    }

    input_orders_dir = workspace / "input" / "orders"
    maison_path = input_orders_dir / "maison_aurelia_order.html"
    valente_path = input_orders_dir / "valente_milano_order.html"

    expected_records: List[Dict[str, Any]] = []
    if maison_path.exists():
        rec = safe_extract_expected(maison_path, "input/orders/maison_aurelia_order.html")
        if rec:
            expected_records.append(rec)
    if valente_path.exists():
        rec = safe_extract_expected(valente_path, "input/orders/valente_milano_order.html")
        if rec:
            expected_records.append(rec)

    sla_config, _ = load_sla_config(workspace)
    expected_alerts: List[Dict[str, Any]] = []
    summary_by_brand: Dict[str, Dict[str, int]] = {}
    if sla_config is not None and expected_records:
        for rec in expected_records:
            brand = rec.get("brand")
            method = rec.get("shipping_method")
            est_max = rec.get("shipping_estimate_days_max")
            if not isinstance(brand, str) or not isinstance(method, str) or not isinstance(est_max, int):
                continue
            summary = summary_by_brand.setdefault(brand, {"total_orders": 0, "orders_exceeding_sla": 0, "orders_with_chat": 0, "orders_with_returns": 0})
            summary["total_orders"] += 1
            if isinstance(rec.get("support_channels"), list) and "chat" in rec.get("support_channels", []):
                summary["orders_with_chat"] += 1
            if isinstance(rec.get("return_policy_present"), bool) and rec.get("return_policy_present"):
                summary["orders_with_returns"] += 1
            allowed = sla_config.get(brand, {}).get(method)
            if allowed and isinstance(allowed.get("max_days"), int):
                allowed_max = allowed["max_days"]
                if est_max > allowed_max:
                    expected_alerts.append({
                        "order_id": rec.get("order_id"),
                        "brand": brand,
                        "shipping_method": method,
                        "estimate_max_days": est_max,
                        "allowed_max_days": allowed_max,
                        "source_file": rec.get("source_file"),
                    })
                    summary["orders_exceeding_sla"] += 1

    orders_parsed_path = workspace / "outputs" / "orders_parsed.jsonl"
    records, _ = safe_load_jsonl(orders_parsed_path) if orders_parsed_path.exists() else (None, "missing")
    if records is not None:
        expected_count = len(expected_records)
        expected_sources = set(r["source_file"] for r in expected_records)
        observed_records = []
        for r in records:
            if isinstance(r, dict) and "source_file" in r:
                sf = canonicalize_path_string(str(r.get("source_file")))
                if sf in expected_sources:
                    observed_records.append(r)
        if len(observed_records) == expected_count and expected_count > 0:
            scores["orders_jsonl_parsed_and_complete"] = 1.0
        else:
            scores["orders_jsonl_parsed_and_complete"] = 0.0

        unique_pairs = set()
        dup_free = True
        for r in records:
            if isinstance(r, dict) and "source_file" in r and "file_sha256" in r:
                sf = canonicalize_path_string(str(r.get("source_file")))
                csum = str(r.get("file_sha256"))
                key = (sf, csum)
                if key in unique_pairs:
                    dup_free = False
                    break
                unique_pairs.add(key)
        scores["orders_no_duplicate_for_same_checksum"] = 1.0 if dup_free else 0.0

        correct_all = True
        exp_map = {r["source_file"]: r for r in expected_records}
        for r in observed_records:
            sf = canonicalize_path_string(str(r.get("source_file")))
            exp = exp_map.get(sf)
            if not exp or not compare_records(exp, r):
                correct_all = False
                break
        scores["orders_values_correct"] = 1.0 if correct_all and expected_records else 0.0
    else:
        scores["orders_jsonl_parsed_and_complete"] = 0.0
        scores["orders_values_correct"] = 0.0
        scores["orders_no_duplicate_for_same_checksum"] = 0.0

    state_path = workspace / "state" / "orders_processed.json"
    mapping, _ = load_state_mapping(state_path) if state_path.exists() else (None, "missing")
    if mapping is not None and expected_records:
        ok = True
        for rec in expected_records:
            sf = rec["source_file"]
            csum_expected = rec["file_sha256"]
            csum_state = mapping.get(sf)
            if csum_state != csum_expected:
                ok = False
                break
        scores["state_json_contains_latest_checksums"] = 1.0 if ok else 0.0
    else:
        scores["state_json_contains_latest_checksums"] = 0.0

    alerts_path = workspace / "outputs" / "alerts.json"
    alerts_data, _ = safe_load_json(alerts_path) if alerts_path.exists() else (None, "missing")
    if alerts_data is not None and isinstance(alerts_data, list):
        expected_alerts_map = {(a["order_id"], a["source_file"]): a for a in expected_alerts}
        observed_alerts_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for a in alerts_data:
            if not isinstance(a, dict):
                observed_alerts_map = {}
                break
            oid = a.get("order_id")
            sf = canonicalize_path_string(str(a.get("source_file"))) if a.get("source_file") is not None else None
            if isinstance(oid, str) and isinstance(sf, str):
                observed_alerts_map[(oid, sf)] = a
        alerts_correct = True
        if len(observed_alerts_map) != len(expected_alerts_map):
            alerts_correct = False
        else:
            for key, exp in expected_alerts_map.items():
                obs = observed_alerts_map.get(key)
                if not obs:
                    alerts_correct = False
                    break
                for req in ["order_id", "brand", "shipping_method", "estimate_max_days", "allowed_max_days", "source_file"]:
                    if req not in obs:
                        alerts_correct = False
                        break
                if not alerts_correct:
                    break
                if obs["order_id"] != exp["order_id"]:
                    alerts_correct = False
                    break
                if obs["brand"] != exp["brand"]:
                    alerts_correct = False
                    break
                if obs["shipping_method"] != exp["shipping_method"]:
                    alerts_correct = False
                    break
                try:
                    if int(obs["estimate_max_days"]) != int(exp["estimate_max_days"]):
                        alerts_correct = False
                        break
                    if int(obs["allowed_max_days"]) != int(exp["allowed_max_days"]):
                        alerts_correct = False
                        break
                except Exception:
                    alerts_correct = False
                    break
                if canonicalize_path_string(str(obs["source_file"])) != exp["source_file"]:
                    alerts_correct = False
                    break
        scores["alerts_json_correct"] = 1.0 if alerts_correct else 0.0
    else:
        scores["alerts_json_correct"] = 0.0

    summary_path = workspace / "outputs" / "summary_by_brand.csv"
    header, rows, _ = safe_load_csv(summary_path) if summary_path.exists() else (None, None, "missing")
    if header is not None and rows is not None:
        expected_header = ["brand", "total_orders", "orders_exceeding_sla", "orders_with_chat", "orders_with_returns"]
        header_correct = header == expected_header
        rows_by_brand = {}
        for row in rows:
            if "brand" not in row:
                header_correct = False
                break
            brand = row.get("brand", "")
            try:
                to = int(row.get("total_orders", ""))
                oes = int(row.get("orders_exceeding_sla", ""))
                owc = int(row.get("orders_with_chat", ""))
                owr = int(row.get("orders_with_returns", ""))
            except Exception:
                header_correct = False
                break
            rows_by_brand[brand] = {
                "total_orders": to,
                "orders_exceeding_sla": oes,
                "orders_with_chat": owc,
                "orders_with_returns": owr,
            }
        expected_rows_by_brand = {}
        for brand, vals in summary_by_brand.items():
            expected_rows_by_brand[brand] = vals
        summary_correct = header_correct and (len(rows_by_brand) == len(expected_rows_by_brand)) and len(expected_rows_by_brand) > 0
        if summary_correct:
            for brand, expvals in expected_rows_by_brand.items():
                obsvals = rows_by_brand.get(brand)
                if not obsvals or obsvals != expvals:
                    summary_correct = False
                    break
        scores["summary_by_brand_csv_correct"] = 1.0 if summary_correct else 0.0
    else:
        scores["summary_by_brand_csv_correct"] = 0.0

    sla_consistent = False
    if records is not None and isinstance(records, list) and alerts_data is not None and isinstance(alerts_data, list) and header is not None and rows is not None and sla_config is not None:
        obs_summary: Dict[str, Dict[str, int]] = {}
        try:
            for row in rows:
                b = row["brand"]
                obs_summary[b] = {
                    "total_orders": int(row["total_orders"]),
                    "orders_exceeding_sla": int(row["orders_exceeding_sla"]),
                    "orders_with_chat": int(row["orders_with_chat"]),
                    "orders_with_returns": int(row["orders_with_returns"]),
                }
        except Exception:
            obs_summary = {}
        obs_alerts_set = set()
        for a in alerts_data:
            if isinstance(a, dict) and "order_id" in a and "source_file" in a:
                obs_alerts_set.add((a["order_id"], canonicalize_path_string(str(a["source_file"]))))
        exceeds_set = set()
        obs_by_brand_counts: Dict[str, Dict[str, int]] = {}
        for r in records:
            if not isinstance(r, dict):
                continue
            sf = r.get("source_file")
            if not isinstance(sf, str):
                continue
            sf = canonicalize_path_string(sf)
            if not any(sf == er["source_file"] for er in expected_records):
                continue
            brand = r.get("brand")
            method = r.get("shipping_method")
            est_max = coerce_int(r.get("shipping_estimate_days_max"))
            if not isinstance(brand, str) or not isinstance(method, str) or est_max is None:
                continue
            if brand not in obs_by_brand_counts:
                obs_by_brand_counts[brand] = {"total_orders": 0, "orders_exceeding_sla": 0, "orders_with_chat": 0, "orders_with_returns": 0}
            obs_by_brand_counts[brand]["total_orders"] += 1
            ch = r.get("support_channels")
            if isinstance(ch, list) and "chat" in ch:
                obs_by_brand_counts[brand]["orders_with_chat"] += 1
            if isinstance(r.get("return_policy_present"), bool) and r.get("return_policy_present"):
                obs_by_brand_counts[brand]["orders_with_returns"] += 1
            allowed = sla_config.get(brand, {}).get(method)
            if allowed and isinstance(allowed.get("max_days"), int) and est_max > allowed["max_days"]:
                exceeds_set.add((r.get("order_id"), sf))
                obs_by_brand_counts[brand]["orders_exceeding_sla"] += 1
        if obs_summary and obs_by_brand_counts:
            summary_match = obs_summary == obs_by_brand_counts
            alerts_match = obs_alerts_set == exceeds_set
            sla_consistent = summary_match and alerts_match
    scores["sla_consistency_across_outputs"] = 1.0 if sla_consistent else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()