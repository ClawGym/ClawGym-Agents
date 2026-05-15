import os
import sys
import json
import csv
import re
from typing import List, Tuple

def get_workspace_root() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def load_csv_addresses(csv_path: str) -> Tuple[List[str], List[str]]:
    raw = []
    norm = []
    if not os.path.isfile(csv_path):
        return raw, norm
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            # Use DictReader to access by headers
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            # Find an address-like column
            addr_key = None
            for fn in fieldnames:
                if fn is None:
                    continue
                if "address" in fn.lower():
                    addr_key = fn
                    break
            if addr_key is None:
                # No clear address column; try a best-effort: look for "street"
                for fn in fieldnames:
                    if fn is None:
                        continue
                    if "street" in fn.lower():
                        addr_key = fn
                        break
            if addr_key is None:
                # Cannot find address column, return empty
                return raw, norm
            for row in reader:
                val = row.get(addr_key, "")
                if val:
                    raw.append(val)
                    norm.append(norm_text(val))
    except Exception:
        # On any parsing error, return what we have (likely empty)
        return [], []
    return raw, norm

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def parse_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    json_path = os.path.join(output_dir, "valuation.json")
    report_path = os.path.join(output_dir, "valuation_report.md")
    comps_csv_path = os.path.join(input_dir, "comps.csv")

    # Load reference addresses from comps.csv
    comps_raw_addresses, comps_norm_addresses = load_csv_addresses(comps_csv_path)

    checks = {
        # valuation.json checks
        "json_exists": False,
        "json_valid": False,
        "json_has_required_fields": False,
        "json_numbers_positive": False,
        "json_numbers_order": False,
        "json_list_price_in_range": False,
        "json_scenarios_valid": False,
        "json_key_drivers_len": False,
        "json_risks_len": False,
        "json_confidence_valid": False,
        "json_comps_used_len": False,
        "json_comps_used_fields_types": False,
        "json_comps_crossref": False,

        # valuation_report.md checks
        "report_exists": False,
        "report_has_sections": False,
        "report_has_currency_amounts_and_cad": False,
        "report_mentions_two_comps": False,
        "report_has_adjustment_words": False,
        "report_mentions_market_context": False,
    }

    # --- Check valuation.json ---
    data = None
    if os.path.isfile(json_path):
        checks["json_exists"] = True
        data = parse_json(json_path)
        if isinstance(data, dict):
            checks["json_valid"] = True

            # Required fields
            required_keys = ["estimated_range", "best_estimate", "recommended_list_price", "scenarios", "key_drivers", "risks", "confidence", "comps_used"]
            has_required = all(k in data for k in required_keys)
            if has_required and isinstance(data.get("estimated_range"), dict):
                er = data.get("estimated_range", {})
                if "low" in er and "high" in er:
                    checks["json_has_required_fields"] = True

            # Numeric positivity and order
            if checks["json_has_required_fields"]:
                er = data["estimated_range"]
                low = er.get("low")
                high = er.get("high")
                best = data.get("best_estimate")
                list_price = data.get("recommended_list_price")
                if is_number(low) and is_number(high) and is_number(best) and is_number(list_price) and (low > 0 and high > 0 and best > 0 and list_price > 0):
                    checks["json_numbers_positive"] = True

                if checks["json_numbers_positive"]:
                    if low < best < high:
                        checks["json_numbers_order"] = True
                    if (list_price >= low) and (list_price <= high * 1.05):
                        checks["json_list_price_in_range"] = True

            # Scenarios
            scenarios = data.get("scenarios") if isinstance(data, dict) else None
            sc_ok = False
            if isinstance(scenarios, list) and len(scenarios) >= 2:
                sc_ok = True
                for sc in scenarios:
                    if not isinstance(sc, dict):
                        sc_ok = False
                        break
                    if "label" not in sc or "price" not in sc or "days_on_market" not in sc:
                        sc_ok = False
                        break
                    if not isinstance(sc.get("label"), str):
                        sc_ok = False
                        break
                    if not is_number(sc.get("price")) or not is_number(sc.get("days_on_market")):
                        sc_ok = False
                        break
            if sc_ok:
                checks["json_scenarios_valid"] = True

            # key_drivers
            key_drivers = data.get("key_drivers")
            if isinstance(key_drivers, list) and len(key_drivers) >= 3 and all(isinstance(x, str) for x in key_drivers):
                checks["json_key_drivers_len"] = True

            # risks
            risks = data.get("risks")
            if isinstance(risks, list) and len(risks) >= 2 and all(isinstance(x, str) for x in risks):
                checks["json_risks_len"] = True

            # confidence
            conf = data.get("confidence")
            if isinstance(conf, str) and conf.strip().lower() in {"low", "medium", "high"}:
                checks["json_confidence_valid"] = True

            # comps_used
            comps_used = data.get("comps_used")
            comps_used_ok_len = isinstance(comps_used, list) and len(comps_used) >= 3
            if comps_used_ok_len:
                checks["json_comps_used_len"] = True
                fields_ok = True
                for comp in comps_used:
                    if not isinstance(comp, dict):
                        fields_ok = False
                        break
                    addr = comp.get("address")
                    sp = comp.get("sold_price")
                    sz = comp.get("size_sqft")
                    if not isinstance(addr, str) or not addr.strip():
                        fields_ok = False
                        break
                    if not is_number(sp) or sp <= 0:
                        fields_ok = False
                        break
                    if not is_number(sz) or sz <= 0:
                        fields_ok = False
                        break
                if fields_ok:
                    checks["json_comps_used_fields_types"] = True

                # Cross-reference with input/comps.csv: at least two addresses match by substring (case-insensitive)
                # Only attempt if we have addresses from csv
                if len(comps_norm_addresses) > 0:
                    matched_used_indices = set()
                    for idx, comp in enumerate(comps_used):
                        if not isinstance(comp, dict):
                            continue
                        uaddr = norm_text(comp.get("address", ""))
                        if not uaddr:
                            continue
                        for csv_addr in comps_norm_addresses:
                            if uaddr in csv_addr or csv_addr in uaddr:
                                matched_used_indices.add(idx)
                                break
                    if len(matched_used_indices) >= 2:
                        checks["json_comps_crossref"] = True

    # --- Check valuation_report.md ---
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_text = read_text(report_path)
        report_low = report_text.lower()

        # Sections required
        # "Estimated value range", "Best estimate", "Recommended list price" (or "Suggested list price"),
        # "Scenario" (or "Sale scenarios"), "Key value drivers", "Risks" (or "Risks & uncertainties"), and "Confidence".
        sections_ok = True
        if "estimated value range" not in report_low:
            sections_ok = False
        if "best estimate" not in report_low:
            sections_ok = False
        if not ("recommended list price" in report_low or "suggested list price" in report_low):
            sections_ok = False
        if not ("sale scenarios" in report_low or "scenario" in report_low):
            sections_ok = False
        if "key value drivers" not in report_low:
            sections_ok = False
        if not ("risks & uncertainties" in report_low or "risks" in report_low):
            sections_ok = False
        if "confidence" not in report_low:
            sections_ok = False
        if sections_ok:
            checks["report_has_sections"] = True

        # Currency amounts and CAD indicator
        currency_matches = re.findall(r"\$\s*\d[\d,]*(?:\.\d+)?", report_text)
        has_cad_token = ("cad" in report_low) or ("c$" in report_low)
        if len(currency_matches) >= 3 and has_cad_token:
            checks["report_has_currency_amounts_and_cad"] = True

        # At least two addresses from comps.csv appear in the report text
        comps_in_report = 0
        seen_addresses = set()
        if comps_raw_addresses:
            for addr_raw in comps_raw_addresses:
                a = norm_text(addr_raw)
                if a and a in report_low:
                    seen_addresses.add(a)
            comps_in_report = len(seen_addresses)
        if comps_in_report >= 2:
            checks["report_mentions_two_comps"] = True

        # Adjustment words: at least two occurrences of any of the words
        # "adjust", "adjustment", "premium", or "discount".
        adj_count = len(re.findall(r"\b(adjust(?:ment|ments)?|premium|premiums|discount|discounts)\b", report_low))
        if adj_count >= 2:
            checks["report_has_adjustment_words"] = True

        # Market context mention: at least one of "inventory", "supply", "demand", "momentum", "seasonality", "trend"
        if any(word in report_low for word in ["inventory", "supply", "demand", "momentum", "seasonality", "trend"]):
            checks["report_mentions_market_context"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()