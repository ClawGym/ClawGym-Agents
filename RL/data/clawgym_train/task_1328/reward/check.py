import json
import os
import sys
import csv
from decimal import Decimal, ROUND_HALF_UP

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def safe_decimal(x):
    try:
        if isinstance(x, (int, float)):
            return Decimal(str(x))
        if isinstance(x, str):
            s = x.strip()
            if s == "":
                return None
            return Decimal(s)
        return None
    except Exception:
        return None

def quantize_cents(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def extract_primary_keyword(csv_path):
    # Robust extraction from CSV
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None
    # Try DictReader first
    try:
        from io import StringIO
        sio = StringIO(content)
        dr = csv.DictReader(sio)
        if dr.fieldnames:
            fields_lower = [h.lower() for h in dr.fieldnames]
            rows = list(dr)
            # 1) 'primary_keyword' column
            if 'primary_keyword' in fields_lower:
                idx = fields_lower.index('primary_keyword')
                for row in rows:
                    val = list(row.values())[idx] if isinstance(row, dict) else None
                    if val and str(val).strip():
                        return str(val).strip()
            # 2) 'primary' or 'is_primary' true row with 'keyword'
            truthy = {'1', 'true', 'yes', 'y', 't'}
            for flag in ('primary', 'is_primary'):
                if flag in fields_lower:
                    flag_idx = fields_lower.index(flag)
                    # Determine keyword column
                    kw_idx = None
                    for name in fields_lower:
                        if name in ('keyword', 'key', 'term'):
                            kw_idx = fields_lower.index(name)
                            break
                    for row in rows:
                        vals = list(row.values())
                        flag_val = str(vals[flag_idx]).strip().lower() if flag_idx is not None else ''
                        if flag_val in truthy:
                            if kw_idx is not None:
                                kw = str(vals[kw_idx]).strip()
                                if kw:
                                    return kw
                            else:
                                # Fallback: first non-empty value in this row
                                for v in vals:
                                    if str(v).strip():
                                        return str(v).strip()
            # 3) 'keyword' column first row
            if 'keyword' in fields_lower:
                idx = fields_lower.index('keyword')
                for row in rows:
                    val = list(row.values())[idx]
                    if val and str(val).strip():
                        return str(val).strip()
            # 4) first non-empty cell in first row
            if rows:
                vals = list(rows[0].values())
                for v in vals:
                    if str(v).strip():
                        return str(v).strip()
    except Exception:
        pass
    # Fallback to reader
    try:
        from io import StringIO
        sio2 = StringIO(content)
        rr = csv.reader(sio2)
        for row in rr:
            for cell in row:
                if str(cell).strip():
                    return str(cell).strip()
    except Exception:
        pass
    return None

def find_value_by_keys(obj, keys):
    # Recursively find first value for any key name in keys (case-insensitive)
    # Return the first found numeric (Decimal-convertible) or string for brand
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k is not None and str(k).lower() in [kk.lower() for kk in keys]:
                return v
        for v in obj.values():
            res = find_value_by_keys(v, keys)
            if res is not None:
                return res
    elif isinstance(obj, list):
        for it in obj:
            res = find_value_by_keys(it, keys)
            if res is not None:
                return res
    return None

def extract_brand(brief):
    # Try common brand keys
    val = find_value_by_keys(brief, ['brand', 'brand_name', 'brandName'])
    if isinstance(val, str):
        return val.strip()
    return None

def get_platform_value(brief, platform, key_candidates):
    # Try nested under 'platforms' then under platform name, else flat names like f"{platform}_{key}"
    # key_candidates is a list of candidate key names like ['fixed_fee','fixedFee',...]
    platform_obj = None
    if isinstance(brief, dict):
        if 'platforms' in brief and isinstance(brief['platforms'], dict):
            plat = brief['platforms'].get(platform)
            if isinstance(plat, dict):
                platform_obj = plat
        # direct platform key
        if platform_obj is None and platform in brief and isinstance(brief[platform], dict):
            platform_obj = brief[platform]
    # Search in platform_obj
    if isinstance(platform_obj, dict):
        val = find_value_by_keys(platform_obj, key_candidates)
        if val is not None:
            return val
    # Try flat keys like 'amazon_fixed_fee'
    flat_keys = []
    for kc in key_candidates:
        flat_keys.append(f"{platform}_{kc}")
        flat_keys.append(f"{platform}{kc[0].upper()}{kc[1:]}" if kc else kc)
    val = find_value_by_keys(brief, flat_keys)
    if val is not None:
        return val
    return None

def to_number(val):
    d = safe_decimal(val)
    if d is None:
        return None
    return d

def compute_price(base_cost, shipping_cost, fixed_fee, var_percent, margin_percent):
    try:
        b = to_number(base_cost)
        s = to_number(shipping_cost)
        f = to_number(fixed_fee)
        vp = to_number(var_percent)
        mp = to_number(margin_percent)
        if None in (b, s, f, vp, mp):
            return None
        denom = Decimal("1") - (vp + mp) / Decimal("100")
        if denom == Decimal("0"):
            return None
        res = (b + s + f) / denom
        return quantize_cents(res)
    except Exception:
        return None

def extract_prohibited_chars_from_yaml(yaml_text):
    # Attempt to pull a list of prohibited characters from YAML heuristically
    if not yaml_text:
        return None
    lines = yaml_text.splitlines()
    # Inline list pattern
    import re
    pattern_inline = re.compile(r'(?i)(title_prohibited_characters|prohibited_title_characters|prohibited_characters)\s*:\s*\[(.*?)\]')
    m = pattern_inline.search(yaml_text)
    if m:
        inner = m.group(2)
        parts = [p.strip() for p in inner.split(',')]
        chars = []
        for p in parts:
            # strip quotes
            if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                p = p[1:-1]
            if p:
                chars.append(p)
        return ''.join(chars)
    # Block list pattern
    start_idx = None
    key_regex = re.compile(r'(?i)^\s*(title_prohibited_characters|prohibited_title_characters|prohibited_characters)\s*:\s*$')
    for i, line in enumerate(lines):
        if key_regex.match(line):
            start_idx = i + 1
            break
    if start_idx is not None:
        chars = []
        for j in range(start_idx, len(lines)):
            l = lines[j]
            if not l.strip():
                continue
            # list item
            if l.strip().startswith('-'):
                item = l.strip()[1:].strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                if item:
                    chars.append(item)
            else:
                # end of list block
                break
        if chars:
            return ''.join(chars)
    return None

def utf8_len(s):
    try:
        return len(s.encode('utf-8'))
    except Exception:
        return None

def starts_with_exact(s, prefix):
    if s is None or prefix is None:
        return False
    return s.startswith(prefix)

def load_inputs(input_dir):
    brief = read_json(os.path.join(input_dir, "product_brief.json"))
    keywords_csv = os.path.join(input_dir, "keywords.csv")
    rules_text = read_text(os.path.join(input_dir, "rules.yaml"))
    primary_keyword = extract_primary_keyword(keywords_csv) if os.path.isfile(keywords_csv) else None
    prohibited_chars = extract_prohibited_chars_from_yaml(rules_text) if rules_text else None
    if not prohibited_chars:
        # Default from known Amazon 2025 rules
        prohibited_chars = "!${}?"
    return brief, primary_keyword, prohibited_chars

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Initialize checks
    checks = {
        "pricing_file_exists": False,
        "pricing_json_valid": False,
        "pricing_values_correct": False,

        "amazon_file_exists": False,
        "amazon_title_starts_primary": False,
        "amazon_title_len_ok": False,
        "amazon_title_no_prohibited_chars": False,
        "amazon_bullets_count_5": False,
        "amazon_each_bullet_len_range": False,
        "amazon_total_bullets_len_ok": False,
        "amazon_backend_terms_byte_len_ok": False,
        "amazon_backend_terms_no_commas": False,
        "amazon_backend_terms_no_brand": False,

        "etsy_file_exists": False,
        "etsy_title_starts_primary": False,
        "etsy_title_len_ok": False,
        "etsy_tags_count_13": False,
        "etsy_tags_first_primary": False,
        "etsy_description_len_ok": False,
    }

    brief, primary_keyword, prohibited_chars = load_inputs(input_dir)
    brand_name = extract_brand(brief) if isinstance(brief, dict) else None

    # Expected pricing computation (using standard formula from task spec)
    # Price = (base_cost + shipping_cost + platform_fixed_fee) / (1 - (platform_variable_fee_percent + desired_margin_percent)/100)
    base_cost = None
    shipping_cost = None
    desired_margin_percent = None
    if isinstance(brief, dict):
        base_cost = find_value_by_keys(brief, ['base_cost', 'baseCost'])
        shipping_cost = find_value_by_keys(brief, ['shipping_cost', 'shippingCost'])
        desired_margin_percent = find_value_by_keys(brief, ['desired_margin_percent', 'desired_margin', 'margin_percent', 'desiredMarginPercent'])

    amazon_fixed = get_platform_value(brief or {}, 'amazon', ['fixed_fee', 'fixedFee', 'fixed_fees', 'fixed'])
    amazon_var = get_platform_value(brief or {}, 'amazon', ['variable_fee_percent', 'variableFeePercent', 'variable_percent', 'referral_fee_percent', 'referralPercent', 'referral_percent'])
    etsy_fixed = get_platform_value(brief or {}, 'etsy', ['fixed_fee', 'fixedFee', 'fixed_fees', 'fixed'])
    etsy_var = get_platform_value(brief or {}, 'etsy', ['variable_fee_percent', 'variableFeePercent', 'variable_percent', 'transaction_fee_percent', 'transactionPercent'])

    expected_amazon_price = compute_price(base_cost, shipping_cost, amazon_fixed, amazon_var, desired_margin_percent)
    expected_etsy_price = compute_price(base_cost, shipping_cost, etsy_fixed, etsy_var, desired_margin_percent)

    # Read outputs
    pricing_path = os.path.join(output_dir, "pricing.json")
    amazon_path = os.path.join(output_dir, "amazon_listing.json")
    etsy_path = os.path.join(output_dir, "etsy_listing.json")

    # Pricing checks
    if os.path.isfile(pricing_path):
        checks["pricing_file_exists"] = True
        pricing = read_json(pricing_path)
        if isinstance(pricing, dict) and "amazon_price" in pricing and "etsy_price" in pricing:
            # Validate numeric presence
            ap = pricing.get("amazon_price")
            ep = pricing.get("etsy_price")
            ap_dec = safe_decimal(ap)
            ep_dec = safe_decimal(ep)
            if ap_dec is not None and ep_dec is not None:
                checks["pricing_json_valid"] = True
                # Compare with expected if we computed expectations
                if expected_amazon_price is not None and expected_etsy_price is not None:
                    ap_q = quantize_cents(ap_dec)
                    ep_q = quantize_cents(ep_dec)
                    if ap_q == expected_amazon_price and ep_q == expected_etsy_price:
                        checks["pricing_values_correct"] = True

    # Amazon listing checks
    if os.path.isfile(amazon_path):
        checks["amazon_file_exists"] = True
        al = read_json(amazon_path)
        if isinstance(al, dict):
            title = al.get("title")
            bullets = al.get("bullets")
            backend = al.get("backend_search_terms")

            # Title checks
            if isinstance(title, str):
                if primary_keyword:
                    if starts_with_exact(title, primary_keyword):
                        checks["amazon_title_starts_primary"] = True
                if len(title) <= 200:
                    checks["amazon_title_len_ok"] = True
                # Prohibited characters
                no_prohibited = True
                for ch in prohibited_chars:
                    if ch and ch in title:
                        no_prohibited = False
                        break
                if no_prohibited:
                    checks["amazon_title_no_prohibited_chars"] = True

            # Bullets checks
            if isinstance(bullets, list):
                if len(bullets) == 5:
                    checks["amazon_bullets_count_5"] = True
                all_len_ok = True
                total_len = 0
                all_strings = True
                for b in bullets:
                    if not isinstance(b, str):
                        all_strings = False
                        all_len_ok = False
                        break
                    blen = len(b)
                    total_len += blen
                    if not (200 <= blen <= 250):
                        all_len_ok = False
                if all_strings and all_len_ok:
                    checks["amazon_each_bullet_len_range"] = True
                if all_strings and total_len <= 1000:
                    checks["amazon_total_bullets_len_ok"] = True

            # Backend search terms
            if isinstance(backend, str):
                blen = utf8_len(backend)
                if blen is not None and blen <= 250:
                    checks["amazon_backend_terms_byte_len_ok"] = True
                if ',' not in backend:
                    checks["amazon_backend_terms_no_commas"] = True
                # brand exclusion
                if brand_name:
                    if brand_name.strip().lower() not in backend.strip().lower():
                        checks["amazon_backend_terms_no_brand"] = True
                else:
                    # If no brand provided, consider it passes brand exclusion
                    checks["amazon_backend_terms_no_brand"] = True

    # Etsy listing checks
    if os.path.isfile(etsy_path):
        checks["etsy_file_exists"] = True
        el = read_json(etsy_path)
        if isinstance(el, dict):
            title = el.get("title")
            tags = el.get("tags")
            desc = el.get("description")

            # Title checks
            if isinstance(title, str):
                if primary_keyword:
                    if starts_with_exact(title, primary_keyword):
                        checks["etsy_title_starts_primary"] = True
                if len(title) <= 140:
                    checks["etsy_title_len_ok"] = True

            # Tags checks
            if isinstance(tags, list):
                if len(tags) == 13 and all(isinstance(t, str) for t in tags):
                    checks["etsy_tags_count_13"] = True
                    if primary_keyword and len(tags) >= 1:
                        if tags[0] == primary_keyword:
                            checks["etsy_tags_first_primary"] = True

            # Description length
            if isinstance(desc, str):
                if len(desc) >= 160:
                    checks["etsy_description_len_ok"] = True

    # Compute reward
    # Only count checks that depend on output artifacts (exclude existence flags)
    scored_keys = [
        "pricing_json_valid",
        "pricing_values_correct",

        "amazon_title_starts_primary",
        "amazon_title_len_ok",
        "amazon_title_no_prohibited_chars",
        "amazon_bullets_count_5",
        "amazon_each_bullet_len_range",
        "amazon_total_bullets_len_ok",
        "amazon_backend_terms_byte_len_ok",
        "amazon_backend_terms_no_commas",
        "amazon_backend_terms_no_brand",

        "etsy_title_starts_primary",
        "etsy_title_len_ok",
        "etsy_tags_count_13",
        "etsy_tags_first_primary",
        "etsy_description_len_ok",
    ]
    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output directory missing or empty -> reward 0.0
    try:
        if (not os.path.isdir(output_dir)) or (len(os.listdir(output_dir)) == 0):
            reward = 0.0
    except Exception:
        pass

    out = {"reward": float(reward)}
    out.update({k: bool(v) for k, v in checks.items()})
    print(json.dumps(out))

if __name__ == "__main__":
    main()