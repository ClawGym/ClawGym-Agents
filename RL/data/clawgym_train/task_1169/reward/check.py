import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def is_number(x):
    return isinstance(x, (int, float))

def approx_equal(actual, expected, rel_tol=0.05):
    # Relative tolerance comparison; avoids division by zero
    denom = abs(expected)
    if denom == 0:
        return abs(actual - expected) <= 1e-9
    return abs(actual - expected) <= rel_tol * denom

def html_allowed_only(s):
    # Allow only tags: p, br, ul, li, strong (with optional attributes)
    allowed = {"p", "br", "ul", "li", "strong"}
    # Find all tags like <tag ...> or </tag>
    for m in re.finditer(r"<\s*/?\s*([a-zA-Z0-9]+)", s):
        tag = m.group(1).lower()
        if tag not in allowed:
            return False
    return True

def bullets_headers_ok(bullets):
    # Each bullet must start with [ALL CAPS HEADER] (letters A-Z and spaces)
    # Pattern: ^\[([A-Z ]+)\]
    pat = re.compile(r"^\[[A-Z ]+\]")
    return all(isinstance(b, str) and pat.match(b or "") for b in bullets)

def bullets_length_ok(bullets, max_len=500):
    return all(isinstance(b, str) and len(b) <= max_len for b in bullets)

def title_quantity_ok(title):
    # Matches a number followed by Capsule/Capsules/Count (case-insensitive)
    return re.search(r"\b\d+\s*(Capsule|Capsules|Count)\b", title, flags=re.IGNORECASE) is not None

def backend_terms_checks(s):
    # Returns tuple: (is_string, term_count_ok, bytes_ok)
    if not isinstance(s, str):
        return False, False, False
    terms = [t.strip() for t in s.split(",")]
    terms = [t for t in terms if t]
    term_count_ok = len(terms) >= 10
    bytes_ok = len(s.encode("utf-8")) <= 250
    return True, term_count_ok, bytes_ok

def lower_contains_any(text, keywords):
    lt = text.lower()
    return any(k.lower() in lt for k in keywords)

def lower_contains(text, keyword):
    return keyword.lower() in text.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # listing.json checks
        "listing_exists": False,
        "listing_valid_json_keys": False,
        "listing_marketplace_ok": False,
        "listing_category_ok": False,
        "listing_title_len_ok": False,
        "listing_title_quantity_ok": False,
        "listing_bullets_count_ok": False,
        "listing_bullets_length_ok": False,
        "listing_bullets_headers_ok": False,
        "listing_description_allowed_tags_ok": False,
        "listing_backend_terms_count_ok": False,
        "listing_backend_terms_bytes_ok": False,
        "listing_compliance_flag_true": False,
        # compliance_checklist.md checks
        "compliance_checklist_exists": False,
        "compliance_checklist_has_fda_phrase": False,
        "compliance_checklist_has_required_keywords": False,
        # fba_prep_plan.md checks
        "fba_prep_plan_exists": False,
        "fba_prep_plan_has_fnsku": False,
        "fba_prep_plan_has_expiration": False,
        "fba_prep_plan_has_poly_bag": False,
        "fba_prep_plan_has_suffocation_warning": False,
        # pricing_analysis.json checks
        "pricing_exists": False,
        "pricing_has_required_fields": False,
        "pricing_referral_rate_ok": False,
        "pricing_referral_amount_math_ok": False,
        "pricing_net_profit_math_ok": False,
        "pricing_margin_math_ok": False,
    }

    # 1) listing.json
    listing_path = os.path.join(output_dir, "listing.json")
    listing_data = None
    if os.path.isfile(listing_path):
        checks["listing_exists"] = True
        data, err = load_json_file(listing_path)
        if isinstance(data, dict):
            required_keys = [
                "marketplace",
                "category",
                "title",
                "bullets",
                "description_html",
                "backend_search_terms",
                "compliance_disclaimer_included",
            ]
            if all(k in data for k in required_keys):
                checks["listing_valid_json_keys"] = True
                listing_data = data

                # marketplace
                if isinstance(data.get("marketplace"), str) and data["marketplace"] == "US":
                    checks["listing_marketplace_ok"] = True

                # category contains "Supplements" (case-insensitive)
                if isinstance(data.get("category"), str) and ("supplements" in data["category"].lower()):
                    checks["listing_category_ok"] = True

                # title length and quantity indicator
                title = data.get("title")
                if isinstance(title, str) and len(title) <= 200:
                    checks["listing_title_len_ok"] = True
                if isinstance(title, str) and title_quantity_ok(title):
                    checks["listing_title_quantity_ok"] = True

                # bullets: exactly 5 strings; each <= 500; each with ALL CAPS header
                bullets = data.get("bullets")
                if isinstance(bullets, list) and len(bullets) == 5 and all(isinstance(b, str) for b in bullets):
                    checks["listing_bullets_count_ok"] = True
                    if bullets_length_ok(bullets, max_len=500):
                        checks["listing_bullets_length_ok"] = True
                    if bullets_headers_ok(bullets):
                        checks["listing_bullets_headers_ok"] = True

                # description allowed tags only
                desc = data.get("description_html")
                if isinstance(desc, str) and html_allowed_only(desc):
                    checks["listing_description_allowed_tags_ok"] = True

                # backend search terms
                backend = data.get("backend_search_terms")
                is_str, terms_ok, bytes_ok = backend_terms_checks(backend)
                if is_str and terms_ok:
                    checks["listing_backend_terms_count_ok"] = True
                if is_str and bytes_ok:
                    checks["listing_backend_terms_bytes_ok"] = True

                # compliance flag
                if isinstance(data.get("compliance_disclaimer_included"), bool) and data["compliance_disclaimer_included"] is True:
                    checks["listing_compliance_flag_true"] = True

    # 2) compliance_checklist.md
    compliance_path = os.path.join(output_dir, "compliance_checklist.md")
    if os.path.isfile(compliance_path):
        checks["compliance_checklist_exists"] = True
        content, err = read_text_file(compliance_path)
        if isinstance(content, str):
            # Exact FDA phrase required (case-sensitive)
            if "These statements have not been evaluated by the Food and Drug Administration." in content:
                checks["compliance_checklist_has_fda_phrase"] = True

            # Required keywords (case-insensitive)
            required_keywords = ["Supplement Facts", "Ingredients", "Directions", "Allergen", "Manufacturer", "Expiration"]
            if all(lower_contains(content, k) for k in required_keywords):
                checks["compliance_checklist_has_required_keywords"] = True

    # 3) fba_prep_plan.md
    fba_prep_path = os.path.join(output_dir, "fba_prep_plan.md")
    if os.path.isfile(fba_prep_path):
        checks["fba_prep_plan_exists"] = True
        content, err = read_text_file(fba_prep_path)
        if isinstance(content, str):
            if lower_contains(content, "FNSKU"):
                checks["fba_prep_plan_has_fnsku"] = True
            if lower_contains(content, "expiration"):
                checks["fba_prep_plan_has_expiration"] = True
            if lower_contains_any(content, ["poly bag", "poly-bag"]):
                checks["fba_prep_plan_has_poly_bag"] = True
            if lower_contains(content, "suffocation warning"):
                checks["fba_prep_plan_has_suffocation_warning"] = True

    # 4) pricing_analysis.json
    pricing_path = os.path.join(output_dir, "pricing_analysis.json")
    pricing = None
    if os.path.isfile(pricing_path):
        checks["pricing_exists"] = True
        data, err = load_json_file(pricing_path)
        if isinstance(data, dict):
            # Required fields
            required_root_fields = [
                "chosen_price",
                "referral_fee_rate",
                "referral_fee_amount",
                "fba_fee_estimate",
                "storage_fee_estimate",
                "cog_unit_cost",
                "net_profit",
                "margin_percent",
                "competitor_summary",
            ]
            root_ok = all(k in data for k in required_root_fields)
            comp_ok = False
            if root_ok and isinstance(data["competitor_summary"], dict):
                comp = data["competitor_summary"]
                comp_ok = all(
                    k in comp and is_number(comp[k])
                    for k in ["lowest_price", "highest_price", "median_price"]
                )
            # All numeric fields present?
            numeric_ok = (
                root_ok and comp_ok and
                all(is_number(data[k]) for k in [
                    "chosen_price",
                    "referral_fee_rate",
                    "referral_fee_amount",
                    "fba_fee_estimate",
                    "storage_fee_estimate",
                    "cog_unit_cost",
                    "net_profit",
                    "margin_percent",
                ])
            )
            if numeric_ok:
                checks["pricing_has_required_fields"] = True
                pricing = data

                # referral_fee_rate bounds
                rfr = data["referral_fee_rate"]
                if 0.10 <= rfr <= 0.20:
                    checks["pricing_referral_rate_ok"] = True

                # Math checks within 5%
                chosen = data["chosen_price"]
                expected_ref = chosen * rfr
                if approx_equal(data["referral_fee_amount"], expected_ref, rel_tol=0.05):
                    checks["pricing_referral_amount_math_ok"] = True

                expected_profit = chosen - data["referral_fee_amount"] - data["fba_fee_estimate"] - data["storage_fee_estimate"] - data["cog_unit_cost"]
                if approx_equal(data["net_profit"], expected_profit, rel_tol=0.05):
                    checks["pricing_net_profit_math_ok"] = True

                expected_margin = 0.0
                if chosen != 0:
                    expected_margin = (data["net_profit"] / chosen) * 100.0
                if approx_equal(data["margin_percent"], expected_margin, rel_tol=0.05):
                    checks["pricing_margin_math_ok"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure no-op baseline: if output directory missing or empty and nothing passed, reward stays 0.0
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()