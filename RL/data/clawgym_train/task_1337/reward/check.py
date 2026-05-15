import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames or []
            return headers, rows
    except Exception:
        return None, None

def norm(s):
    return (s or "").strip().lower()

def get_target_markets(input_dir):
    tm_path = os.path.join(input_dir, "target_markets.csv")
    headers, rows = read_csv_rows(tm_path)
    if not headers or rows is None:
        return set()
    # find market column
    market_col = None
    for h in headers:
        if norm(h) == "market":
            market_col = h
            break
    if market_col is None:
        # fallback to first column
        market_col = headers[0]
    markets = set()
    for r in rows:
        markets.add(norm(r.get(market_col, "")))
    markets = {m for m in markets if m}
    return markets

def get_skus(input_dir):
    sku_path = os.path.join(input_dir, "sku_catalog.csv")
    headers, rows = read_csv_rows(sku_path)
    if not headers or rows is None:
        return set()
    sku_col = None
    for h in headers:
        if norm(h) == "sku":
            sku_col = h
            break
    if sku_col is None:
        return set()
    skus = set()
    for r in rows:
        sku = norm(r.get(sku_col, ""))
        if sku:
            skus.add(sku)
    return skus

def collect_markets_from_section(section_obj):
    """
    Extract a set of market names (lowercased) from a section that may be a dict or a list.
    - If dict: use keys as market names.
    - If list: try to use item['market'] or item['country'] or item['name'] or str(item).
    """
    markets = set()
    if isinstance(section_obj, dict):
        for k in section_obj.keys():
            if isinstance(k, str):
                markets.add(norm(k))
    elif isinstance(section_obj, list):
        for item in section_obj:
            name = None
            if isinstance(item, dict):
                for key in ("market", "country", "name"):
                    if key in item and isinstance(item[key], str):
                        name = item[key]
                        break
                if name is None:
                    try:
                        name = json.dumps(item)
                    except Exception:
                        name = str(item)
            elif isinstance(item, str):
                name = item
            else:
                name = str(item)
            if name:
                markets.add(norm(name))
    else:
        # Fallback: try string representation
        try:
            text = json.dumps(section_obj)
        except Exception:
            text = str(section_obj)
        # Do not add anything here; this is not structured
    return markets

def expected_currency_for_market(market_name):
    m = norm(market_name)
    # map common synonyms
    if m in ("uk", "united kingdom", "u.k.", "great britain", "gb", "gbp market"):
        return "GBP"
    if m in ("germany", "de", "deutschland"):
        return "EUR"
    if m in ("france", "fr"):
        return "EUR"
    if m in ("canada", "ca"):
        return "CAD"
    if m in ("japan", "jp"):
        return "JPY"
    return None

def is_true_str(v):
    return norm(v) == "true"

def check_charm_note(note):
    return "charm" in norm(note)

def get_field_case_insensitive(row, fieldname):
    # Return row value by matching fieldname ignoring case
    for k in row.keys():
        if norm(k) == norm(fieldname):
            return row[k]
    return None

def parse_bool_strict(v):
    s = norm(v)
    if s in ("true", "false"):
        return s == "true"
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Expansion plan checks
        "exp_file_exists": False,
        "exp_valid_json": False,
        "exp_top_keys_correct": False,
        "exp_coverage_market_entry_analysis": False,
        "exp_coverage_vat_roadmap": False,
        "exp_coverage_localization_checklist": False,
        "exp_coverage_pricing_recommendation": False,
        "exp_uk_mentions": False,
        "exp_germany_mentions": False,
        "exp_france_mentions": False,
        "exp_japan_mentions": False,
        "exp_pricing_mentions_vat_included": False,
        "exp_currency_fx_mention": False,
        "exp_launch_sequence_is_list_and_has_all_markets": False,
        "exp_launch_sequence_inventory_strategy_mention": False,
        # Tracking plan checks
        "track_file_exists": False,
        "tracking_events_present": False,
        "tracking_utm_params_present": False,
        "tracking_validation_checklist_present": False,
        "tracking_privacy_consent_no_pii": False,
        "tracking_attribution_market_sku": False,
        # Pricing checks
        "price_file_exists": False,
        "price_csv_headers_correct": False,
        "price_complete_combinations": False,
        "price_currency_by_market_correct": False,
        "price_includes_vat_rules_eu_uk": False,
        "price_ca_notes_explain_tax_for_all": False,
        "price_jp_notes_explain_consumption_tax_for_all": False,
        "price_charm_pricing_decimal_non_jpy": False,
        "price_jpy_integer": False,
        "price_notes_include_charm_per_market": False,
    }

    # Load inputs needed for coverage and pricing combination checks
    target_markets = get_target_markets(input_dir)
    skus = get_skus(input_dir)

    # 1) expansion_plan.json
    exp_path = os.path.join(output_dir, "expansion_plan.json")
    if os.path.isfile(exp_path):
        checks["exp_file_exists"] = True
        exp_data = read_json(exp_path)
        if isinstance(exp_data, dict):
            checks["exp_valid_json"] = True

            # Top-level keys exactly:
            expected_keys = {"market_entry_analysis", "vat_roadmap", "localization_checklist", "pricing_recommendation", "launch_sequence"}
            keys_set = set(exp_data.keys())
            if keys_set == expected_keys:
                checks["exp_top_keys_correct"] = True

            # Coverage checks for markets
            # Only evaluate if target_markets is available and non-empty
            if target_markets:
                try:
                    mea_markets = collect_markets_from_section(exp_data.get("market_entry_analysis"))
                    vr_markets = collect_markets_from_section(exp_data.get("vat_roadmap"))
                    lc_markets = collect_markets_from_section(exp_data.get("localization_checklist"))
                    pr_markets = collect_markets_from_section(exp_data.get("pricing_recommendation"))
                    # We require all target markets in each section
                    if all(m in mea_markets for m in target_markets):
                        checks["exp_coverage_market_entry_analysis"] = True
                    if all(m in vr_markets for m in target_markets):
                        checks["exp_coverage_vat_roadmap"] = True
                    if all(m in lc_markets for m in target_markets):
                        checks["exp_coverage_localization_checklist"] = True
                    if all(m in pr_markets for m in target_markets):
                        checks["exp_coverage_pricing_recommendation"] = True
                except Exception:
                    pass

            # Content checks by regex over serialized JSON
            try:
                exp_text = json.dumps(exp_data)
            except Exception:
                exp_text = read_text(exp_path) or ""
            exp_text_lower = exp_text.lower()

            # UK: mention of "VAT" and either "UKCA" or "CE" and "EPR"
            if ("vat" in exp_text_lower) and (("ukca" in exp_text_lower) or ("ce" in exp_text_lower)) and ("epr" in exp_text_lower):
                checks["exp_uk_mentions"] = True

            # Germany: "VAT" and ("OSS" or "One Stop Shop") and "CE" and "EPR"
            if ("germany" in exp_text_lower or "de" in exp_text_lower or True):  # global search criterion is allowed
                if ("vat" in exp_text_lower) and (("oss" in exp_text_lower) or ("one stop shop" in exp_text_lower)) and ("ce" in exp_text_lower) and ("epr" in exp_text_lower):
                    checks["exp_germany_mentions"] = True

            # France: same as Germany
            if ("france" in exp_text_lower or "fr" in exp_text_lower or True):
                if ("vat" in exp_text_lower) and (("oss" in exp_text_lower) or ("one stop shop" in exp_text_lower)) and ("ce" in exp_text_lower) and ("epr" in exp_text_lower):
                    checks["exp_france_mentions"] = True

            # Japan: "Consumption Tax" or "JCT" and "PSE"
            if (("consumption tax" in exp_text_lower) or ("jct" in exp_text_lower)) and ("pse" in exp_text_lower):
                checks["exp_japan_mentions"] = True

            # Pricing strategy mentions "VAT included" and discusses currency and exchange/FX
            if "vat included" in exp_text_lower:
                checks["exp_pricing_mentions_vat_included"] = True
            if ("currency" in exp_text_lower) and (("exchange" in exp_text_lower) or ("fx" in exp_text_lower)):
                checks["exp_currency_fx_mention"] = True

            # Launch sequence: list with all target markets present and includes EFN or Pan-European FBA or multi-country inventory
            ls = exp_data.get("launch_sequence")
            if isinstance(ls, list):
                ls_text = ""
                try:
                    ls_text = json.dumps(ls).lower()
                except Exception:
                    ls_text = str(ls).lower()
                has_all_markets = True
                if target_markets:
                    for m in target_markets:
                        if m not in ls_text:
                            has_all_markets = False
                            break
                else:
                    has_all_markets = False
                if has_all_markets:
                    checks["exp_launch_sequence_is_list_and_has_all_markets"] = True
            # Inventory strategy mention
            if ("efn" in exp_text_lower) or ("pan-european fba" in exp_text_lower) or ("multi-country inventory" in exp_text_lower):
                checks["exp_launch_sequence_inventory_strategy_mention"] = True

    # 2) tracking_plan.md
    track_path = os.path.join(output_dir, "tracking_plan.md")
    if os.path.isfile(track_path):
        checks["track_file_exists"] = True
        ttext = read_text(track_path) or ""
        tlower = ttext.lower()
        # Events
        if all(x in tlower for x in ["product_viewed", "add_to_cart", "checkout_started", "purchase_completed"]):
            checks["tracking_events_present"] = True
        # UTM params
        if all(x in tlower for x in ["utm_source", "utm_medium", "utm_campaign"]):
            checks["tracking_utm_params_present"] = True
        # Validation checklist
        if ("checklist" in tlower) and (("validate" in tlower) or ("debugview" in tlower) or ("preview" in tlower)):
            checks["tracking_validation_checklist_present"] = True
        # Privacy/consent guidance: exact phrase "no PII" and word "consent"
        if ("no pii" in tlower) and ("consent" in tlower):
            checks["tracking_privacy_consent_no_pii"] = True
        # Attribution by market and SKU
        if ("attribution" in tlower) and ("sku" in tlower):
            checks["tracking_attribution_market_sku"] = True

    # 3) pricing.csv
    price_path = os.path.join(output_dir, "pricing.csv")
    if os.path.isfile(price_path):
        checks["price_file_exists"] = True
        headers, rows = read_csv_rows(price_path)
        if headers is not None and rows is not None:
            lower_headers = [h.strip().lower() for h in headers]
            expected_header_order = ["sku", "market", "local_currency", "recommended_price", "includes_vat", "pricing_notes"]
            if lower_headers == expected_header_order:
                checks["price_csv_headers_correct"] = True

            # Only proceed with further checks if headers correct
            if checks["price_csv_headers_correct"]:
                # Combination coverage
                required_markets = target_markets
                required_skus = skus
                combo_ok = False
                if required_markets and required_skus:
                    # Build set of present combos
                    present = set()
                    for r in rows:
                        sku_v = norm(r.get("sku"))
                        market_v = norm(r.get("market"))
                        if sku_v and market_v:
                            present.add((sku_v, market_v))
                    combo_ok = all((sku, m) in present for sku in required_skus for m in required_markets)
                if combo_ok:
                    checks["price_complete_combinations"] = True

                # Currency by market
                currency_ok = True
                has_any_row = False
                for r in rows:
                    market_v = r.get("market")
                    currency = (r.get("local_currency") or "").strip().upper()
                    exp_cur = expected_currency_for_market(market_v)
                    if exp_cur:
                        has_any_row = True
                        if currency != exp_cur:
                            currency_ok = False
                            break
                if has_any_row and currency_ok:
                    checks["price_currency_by_market_correct"] = True

                # includes_vat rules for UK, Germany, France: must be true
                eu_ok = True
                eu_rows_present = False
                for r in rows:
                    m = norm(r.get("market"))
                    iv = r.get("includes_vat")
                    # Recognize EU/UK markets
                    if m in ("uk", "united kingdom", "u.k.", "great britain", "gb", "germany", "de", "deutschland", "france", "fr"):
                        eu_rows_present = True
                        if not is_true_str(iv):
                            eu_ok = False
                            break
                if eu_rows_present and eu_ok:
                    checks["price_includes_vat_rules_eu_uk"] = True

                # Canada notes include explanation mentioning tax or GST/HST/QST for all CA rows
                ca_rows = [r for r in rows if norm(r.get("market")) in ("canada", "ca")]
                if ca_rows:
                    ca_ok = True
                    for r in ca_rows:
                        notes = r.get("pricing_notes") or ""
                        ln = notes.lower()
                        if not ("tax" in ln or "gst" in ln or "hst" in ln or "qst" in ln):
                            ca_ok = False
                            break
                    if ca_ok:
                        checks["price_ca_notes_explain_tax_for_all"] = True

                # Japan notes include "consumption tax" for all JP rows
                jp_rows = [r for r in rows if norm(r.get("market")) in ("japan", "jp")]
                if jp_rows:
                    jp_ok = True
                    for r in jp_rows:
                        notes = r.get("pricing_notes") or ""
                        if "consumption tax" not in notes.lower():
                            jp_ok = False
                            break
                    if jp_ok:
                        checks["price_jp_notes_explain_consumption_tax_for_all"] = True

                # Charm pricing evidence: non-JPY rows must contain a decimal point; JPY rows must be integer
                non_jpy_rows = [r for r in rows if (r.get("local_currency") or "").strip().upper() != "JPY"]
                jpy_rows = [r for r in rows if (r.get("local_currency") or "").strip().upper() == "JPY"]
                if non_jpy_rows:
                    non_jpy_ok = True
                    for r in non_jpy_rows:
                        price = str(r.get("recommended_price", "")).strip()
                        # require a decimal point
                        if "." not in price:
                            non_jpy_ok = False
                            break
                    if non_jpy_ok:
                        checks["price_charm_pricing_decimal_non_jpy"] = True
                if jpy_rows:
                    jpy_ok = True
                    for r in jpy_rows:
                        price = str(r.get("recommended_price", "")).strip()
                        # must be an integer (no decimal point)
                        if not re.fullmatch(r"\d+", price):
                            jpy_ok = False
                            break
                    if jpy_ok:
                        checks["price_jpy_integer"] = True

                # pricing_notes must include the word "charm" for at least one row per expected market
                charm_per_market_ok = False
                if target_markets:
                    ok_all = True
                    for m in target_markets:
                        any_with_charm = False
                        for r in rows:
                            if norm(r.get("market")) == m:
                                if check_charm_note(r.get("pricing_notes") or ""):
                                    any_with_charm = True
                                    break
                        if not any_with_charm:
                            ok_all = False
                            break
                    if ok_all:
                        charm_per_market_ok = True
                if charm_per_market_ok:
                    checks["price_notes_include_charm_per_market"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure numeric between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()