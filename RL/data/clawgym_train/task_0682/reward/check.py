import json
import os
import sys
import re
import csv

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def extract_urls_from_text(text):
    if not text:
        return []
    # Regex per task spec / reward summary
    pattern = re.compile(r'https?://[^ "\'<>()]+')
    return pattern.findall(text)

def compute_expected_urls(input_dir):
    site_md_path = os.path.join(input_dir, "site_pages.md")
    landing_html_path = os.path.join(input_dir, "landing.html")
    site_md = read_file_text(site_md_path)
    landing_html = read_file_text(landing_html_path)
    urls = []
    urls += extract_urls_from_text(site_md or "")
    urls += extract_urls_from_text(landing_html or "")
    # Deduplicate and sort lexicographically
    unique = sorted(set(urls))
    return unique

def parse_checks_csv(csv_path):
    urls_set = set()
    header_valid = False
    rows_sufficient = False
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = ",".join(rows[0]) if isinstance(rows[0], list) else rows[0]
            header_valid = (header == "url,status_code,status_label,checked_at")
            data_rows = rows[1:] if len(rows) > 1 else []
            for row in data_rows:
                if len(row) >= 1:
                    urls_set.add(row[0])
            rows_sufficient = len(data_rows) >= 1
        else:
            header_valid = False
            rows_sufficient = False
    except Exception:
        header_valid = False
        rows_sufficient = False
        urls_set = set()
    return header_valid, rows_sufficient, urls_set

def validate_broken_md(md_text):
    checks = {
        "broken_md_exists": False,
        "broken_md_min_words": False,
        "broken_md_has_title": False,
        "broken_md_has_4xx_section": False,
        "broken_md_has_5xx_section": False,
        "broken_md_has_timeout_or_error_section": False,
        "broken_md_has_redirect_section": False,
        "broken_md_has_remediation_language": False,
    }
    if md_text is None:
        return checks
    checks["broken_md_exists"] = True
    lower = md_text.lower()
    # Word count
    words = re.findall(r'\S+', md_text)
    checks["broken_md_min_words"] = len(words) >= 100
    # Title presence
    checks["broken_md_has_title"] = ("broken links triage" in lower)
    # Sections
    checks["broken_md_has_4xx_section"] = ("4xx" in lower)
    checks["broken_md_has_5xx_section"] = ("5xx" in lower)
    checks["broken_md_has_timeout_or_error_section"] = ("timeout" in lower) or ("error" in lower)
    checks["broken_md_has_redirect_section"] = ("redirect" in lower)
    # Remediation language
    checks["broken_md_has_remediation_language"] = any(w in lower for w in ["update", "remove", "replace", "fix"])
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Prepare checks dict with all booleans initialized to False
    checks = {
        # urls.json validations
        "urls_json_exists": False,
        "urls_json_valid": False,
        "urls_json_array_strings": False,
        "urls_json_exact_match": False,
        # checks.json validations
        "checks_json_exists": False,
        "checks_json_valid": False,
        "checks_json_array_objects": False,
        "checks_json_required_fields": False,
        "checks_json_labels_valid": False,
        "checks_json_includes_all_expected": False,
        # checks.csv validations
        "checks_csv_exists": False,
        "checks_csv_header_valid": False,
        "checks_csv_rows_sufficient": False,
        "checks_csv_includes_all_expected": False,
        # cross-artifact consistency
        "all_expected_urls_present_in_all_outputs": False,
        # broken-links.md validations (filled by helper)
        "broken_md_exists": False,
        "broken_md_min_words": False,
        "broken_md_has_title": False,
        "broken_md_has_4xx_section": False,
        "broken_md_has_5xx_section": False,
        "broken_md_has_timeout_or_error_section": False,
        "broken_md_has_redirect_section": False,
        "broken_md_has_remediation_language": False,
    }

    # Compute expected URLs from inputs
    expected_urls = compute_expected_urls(input_dir)
    expected_set = set(expected_urls)

    # Validate urls.json
    urls_json_path = os.path.join(output_dir, "urls.json")
    urls_json_data = None
    if os.path.isfile(urls_json_path):
        checks["urls_json_exists"] = True
        urls_json_data = load_json(urls_json_path)
        if urls_json_data is not None:
            checks["urls_json_valid"] = True
            if isinstance(urls_json_data, list) and all(isinstance(x, str) for x in urls_json_data):
                checks["urls_json_array_strings"] = True
                urls_set = set(urls_json_data)
                # Exact set match required
                if urls_set == expected_set:
                    checks["urls_json_exact_match"] = True
            else:
                checks["urls_json_array_strings"] = False

    # Validate checks.json
    checks_json_path = os.path.join(output_dir, "checks.json")
    checks_json_data = None
    checks_json_urls_set = set()
    allowed_labels = {"OK", "REDIRECT", "CLIENT_ERROR", "SERVER_ERROR", "TIMEOUT", "ERROR"}
    if os.path.isfile(checks_json_path):
        checks["checks_json_exists"] = True
        checks_json_data = load_json(checks_json_path)
        if checks_json_data is not None:
            checks["checks_json_valid"] = True
            if isinstance(checks_json_data, list):
                checks["checks_json_array_objects"] = all(isinstance(o, dict) for o in checks_json_data) and len(checks_json_data) > 0
                req_fields_ok = True
                labels_ok = True
                for o in checks_json_data if isinstance(checks_json_data, list) else []:
                    # Required fields presence and type
                    for k in ("url", "status_code", "status_label", "checked_at"):
                        if k not in o or not isinstance(o[k], str) or o[k] == "":
                            req_fields_ok = False
                    # Label values
                    if "status_label" in o and isinstance(o["status_label"], str):
                        if o["status_label"] not in allowed_labels:
                            labels_ok = False
                    # Collect URLs
                    if "url" in o and isinstance(o["url"], str):
                        checks_json_urls_set.add(o["url"])
                checks["checks_json_required_fields"] = req_fields_ok and checks["checks_json_array_objects"]
                checks["checks_json_labels_valid"] = labels_ok and checks["checks_json_array_objects"]
                # Must include all expected URLs (extras allowed)
                if expected_set and expected_set.issubset(checks_json_urls_set):
                    checks["checks_json_includes_all_expected"] = True

    # Validate checks.csv
    checks_csv_path = os.path.join(output_dir, "checks.csv")
    checks_csv_urls_set = set()
    if os.path.isfile(checks_csv_path):
        checks["checks_csv_exists"] = True
        header_ok, rows_sufficient_any, urls_set_csv = parse_checks_csv(checks_csv_path)
        checks["checks_csv_header_valid"] = header_ok
        # We require at least as many data rows as number of expected URLs
        # parse_checks_csv only told us if there was at least 1; we need full count
        try:
            with open(checks_csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                all_rows = list(reader)
            data_rows = all_rows[1:] if len(all_rows) > 1 else []
            checks["checks_csv_rows_sufficient"] = len(data_rows) >= len(expected_set)
        except Exception:
            checks["checks_csv_rows_sufficient"] = False
        checks_csv_urls_set = urls_set_csv
        if expected_set and expected_set.issubset(checks_csv_urls_set):
            checks["checks_csv_includes_all_expected"] = True

    # Cross-artifact consistency: each expected URL appears in urls.json, checks.json, and checks.csv
    urls_json_set = set(urls_json_data) if isinstance(urls_json_data, list) and all(isinstance(x, str) for x in (urls_json_data or [])) else set()
    if expected_set:
        if expected_set.issubset(urls_json_set) and expected_set.issubset(checks_json_urls_set) and expected_set.issubset(checks_csv_urls_set):
            checks["all_expected_urls_present_in_all_outputs"] = True

    # Validate broken-links.md
    broken_md_path = os.path.join(output_dir, "broken-links.md")
    broken_md_text = read_file_text(broken_md_path)
    broken_checks = validate_broken_md(broken_md_text)
    checks.update(broken_checks)

    # Compute reward as fraction of passed checks
    # Ensure no-op baseline: if none of the four required output files exist, reward must be 0.0
    required_paths = [
        urls_json_path,
        checks_json_path,
        checks_csv_path,
        broken_md_path,
    ]
    any_required_exists = any(os.path.isfile(p) for p in required_paths)

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not any_required_exists:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # Bound between 0 and 1
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)

    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()