import json
import os
import sys
import csv
import re
from urllib.parse import urlparse, parse_qs

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

def count_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            rdr = csv.reader(f)
            rows = list(rdr)
        if not rows:
            return 0, []
        header = rows[0]
        data = rows[1:] if len(rows) > 1 else []
        return len(data), rows
    except Exception:
        return None, None

def parse_csv_with_header(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            rdr = csv.reader(f)
            rows = list(rdr)
        if not rows:
            return [], []
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None

def final_url_contains_params(url, params_expected):
    try:
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        # parse_qs gives lists for values; normalize to first string
        normalized = {k: (v[0] if isinstance(v, list) and v else "") for k, v in q.items()}
        # Must contain source, medium, campaign
        required = ["utm_source", "utm_medium", "utm_campaign"]
        for r in required:
            if r not in normalized:
                return False
        # Values must match exactly for required
        for r in required:
            if normalized.get(r, "") != params_expected.get(r, ""):
                return False
        # Optional utm_content and utm_term present only if provided (non-empty)
        for opt in ["utm_content", "utm_term"]:
            if params_expected.get(opt, ""):
                if normalized.get(opt, "") != params_expected.get(opt, ""):
                    return False
        return True
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # UTM links CSV checks
        "utm_links_file_exists": False,
        "utm_links_header_correct": False,
        "utm_links_row_count_matches_input": False,
        "utm_links_values_lowercase_and_underscored": False,
        "utm_links_no_pii_chars": False,
        "utm_links_final_url_params_match": False,
        # Facebook pixel checks
        "facebook_snippet_exists": False,
        "facebook_has_init": False,
        "facebook_has_pageview": False,
        "facebook_has_purchase_value_currency": False,
        # GA4 pixel checks
        "ga4_snippet_exists": False,
        "ga4_has_loader": False,
        "ga4_has_config": False,
        "ga4_purchase_template_keys": False,
        # Attribution checks
        "attribution_file_exists": False,
        "attribution_valid_json": False,
        "attribution_model_last_touch": False,
        "attribution_lookback_30": False,
        "attribution_channels_required_groups": False,
        # Tracking plan checks
        "tracking_plan_exists": False,
        "tracking_plan_length_ok": False,
        "tracking_plan_has_keywords": False,
        # QA checklist checks
        "qa_file_exists": False,
        "qa_has_two_bullets": False,
    }

    # Input reference rows
    campaigns_csv_path = os.path.join(input_dir, "campaigns.csv")
    input_data_rows = None
    total_rows, rows_obj = count_csv_rows(campaigns_csv_path)
    if total_rows is not None:
        input_data_rows = total_rows

    # 1) Validate output/utm_links.csv
    utm_path = os.path.join(output_dir, "utm_links.csv")
    if os.path.isfile(utm_path):
        checks["utm_links_file_exists"] = True
        header, data_rows = parse_csv_with_header(utm_path)
        required_header = ["original_url", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "final_url"]
        if isinstance(header, list) and header == required_header:
            checks["utm_links_header_correct"] = True

            # Row count equals input data rows
            if input_data_rows is not None:
                if len(data_rows) == input_data_rows:
                    checks["utm_links_row_count_matches_input"] = True

            # Per-row validations
            all_values_lowercase_underscored = True
            all_values_no_pii_chars = True
            all_final_url_match = True

            allowed_re = re.compile(r"^[a-z0-9_]+$")

            # Determine column indices from header
            col_idx = {name: idx for idx, name in enumerate(header)}
            for row in data_rows:
                # Skip rows that don't have enough columns
                if len(row) < len(required_header):
                    all_values_lowercase_underscored = False
                    all_values_no_pii_chars = False
                    all_final_url_match = False
                    continue

                utm_values = {
                    "utm_source": row[col_idx["utm_source"]].strip(),
                    "utm_medium": row[col_idx["utm_medium"]].strip(),
                    "utm_campaign": row[col_idx["utm_campaign"]].strip(),
                    "utm_content": row[col_idx["utm_content"]].strip(),
                    "utm_term": row[col_idx["utm_term"]].strip(),
                }
                final_url = row[col_idx["final_url"]].strip()

                # Lowercase and underscore validation for non-empty values
                for key, val in utm_values.items():
                    if val != "":
                        if val != val.lower():
                            all_values_lowercase_underscored = False
                        if not allowed_re.match(val):
                            all_values_lowercase_underscored = False

                        # PII characters check: reject '@' or spaces
                        if "@" in val or " " in val:
                            all_values_no_pii_chars = False

                # Final URL must contain params and values must match (source, medium, campaign required)
                params_expected = {k: v for k, v in utm_values.items() if v is not None}
                if not final_url_contains_params(final_url, params_expected):
                    all_final_url_match = False

            if all_values_lowercase_underscored and len(data_rows) > 0:
                checks["utm_links_values_lowercase_and_underscored"] = True
            if all_values_no_pii_chars and len(data_rows) > 0:
                checks["utm_links_no_pii_chars"] = True
            if all_final_url_match and len(data_rows) > 0:
                checks["utm_links_final_url_params_match"] = True

    # 2) Facebook pixel snippet
    fb_path = os.path.join(output_dir, "pixels", "facebook.html")
    fb_text = read_text(fb_path)
    if fb_text is not None:
        checks["facebook_snippet_exists"] = True
        if "fbq('init'" in fb_text:
            checks["facebook_has_init"] = True
        if "fbq('track', 'PageView')" in fb_text:
            checks["facebook_has_pageview"] = True
        # Purchase with value and currency
        if "fbq('track', 'Purchase'" in fb_text and "value" in fb_text and "currency" in fb_text:
            checks["facebook_has_purchase_value_currency"] = True

    # 3) GA4 pixel snippet
    ga4_path = os.path.join(output_dir, "pixels", "ga4.html")
    ga4_text = read_text(ga4_path)
    if ga4_text is not None:
        checks["ga4_snippet_exists"] = True
        if "googletagmanager.com/gtag/js" in ga4_text:
            checks["ga4_has_loader"] = True
        if "gtag('config'" in ga4_text:
            checks["ga4_has_config"] = True
        lower = ga4_text.lower()
        if ("transaction_id" in lower and "value" in lower and "currency" in lower and "items" in lower):
            checks["ga4_purchase_template_keys"] = True

    # 4) Attribution config
    attrib_path = os.path.join(output_dir, "attribution.json")
    attrib_obj = read_json(attrib_path)
    if attrib_obj is not None:
        checks["attribution_file_exists"] = True
        # Valid JSON if read succeeded and type dict
        if isinstance(attrib_obj, dict):
            checks["attribution_valid_json"] = True
            if attrib_obj.get("attribution_model") == "last_touch":
                checks["attribution_model_last_touch"] = True
            if attrib_obj.get("lookback_window_days") == 30:
                checks["attribution_lookback_30"] = True
            channels = attrib_obj.get("channels")
            if isinstance(channels, dict):
                required_groups = ["email", "organic_social", "paid_search"]
                if all(k in channels and isinstance(channels.get(k), list) for k in required_groups):
                    checks["attribution_channels_required_groups"] = True
    else:
        # File missing or invalid
        if os.path.isfile(attrib_path):
            checks["attribution_file_exists"] = True  # file exists but not valid JSON
            # other fields remain False

        # else remains False

        pass

    # 5) Tracking plan
    tp_path = os.path.join(output_dir, "tracking_plan.md")
    tp_text = read_text(tp_path)
    if tp_text is not None:
        checks["tracking_plan_exists"] = True
        if len(tp_text) >= 200:
            checks["tracking_plan_length_ok"] = True
        lct = tp_text.lower()
        if ("utm" in lct) and (("event" in lct) or ("events" in lct)) and ("attribution" in lct):
            checks["tracking_plan_has_keywords"] = True

    # 6) QA checklist
    qa_path = os.path.join(output_dir, "qa.md")
    qa_text = read_text(qa_path)
    if qa_text is not None:
        checks["qa_file_exists"] = True
        lines = qa_text.splitlines()
        bullet_count = 0
        for line in lines:
            if line.lstrip().startswith("-"):
                bullet_count += 1
        if bullet_count >= 2:
            checks["qa_has_two_bullets"] = True

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output dir missing or empty, reward must be 0.0
    # If none of the output-dependent checks passed, reward already 0.0
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()