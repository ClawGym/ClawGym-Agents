import json
import os
import sys
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_scope_yaml_for_domain(yaml_text):
    # Try to find explicit keys first
    domain_keys = ["root_domain", "domain", "in_scope_domain", "target_domain"]
    for line in yaml_text.splitlines():
        m = re.match(r'^\s*([A-Za-z0-9_]*domain[A-Za-z0-9_]*)\s*:\s*(.+?)\s*$', line)
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip().strip('"').strip("'")
            val_clean = re.sub(r'[^\w\.\-]', '', val)
            if key in domain_keys or any(k in key for k in ["domain"]):
                # Accept the first valid domain-like token
                if re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', val_clean):
                    return val_clean

    # Look for a list under domains or in_scope_domains
    lines = yaml_text.splitlines()
    in_list = False
    for i, line in enumerate(lines):
        if re.match(r'^\s*(in_scope_domains|domains)\s*:\s*$', line):
            in_list = True
            # Read subsequent list items
            for j in range(i+1, len(lines)):
                li = lines[j]
                if re.match(r'^\s*-\s*', li):
                    val = re.sub(r'^\s*-\s*', '', li).strip().strip('"').strip("'")
                    val_clean = re.split(r'\s|#', val)[0].strip()
                    val_clean = re.sub(r'[^\w\.\-]', '', val_clean)
                    if re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', val_clean):
                        return val_clean
                else:
                    break
            in_list = False
    return None

def is_within_scope(subdomain, root_domain):
    s = (subdomain or "").lower().strip()
    rd = (root_domain or "").lower().strip()
    if not s or not rd:
        return False
    return s == rd or s.endswith("." + rd)

def count_words(text):
    return len(re.findall(r'\b\w+\b', text))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Prepare check flags
    checks = {
        "raw_json_exists": False,
        "json_schema_ok": False,
        "json_total_found_matches": False,
        "domain_matches_scope": False,
        "subdomains_within_scope": False,
        "active_csv_valid": False,
        "checks_json_consistent": False,
        "report_valid": False,
    }

    # Paths
    subdomains_json_path = os.path.join(output_dir, "raw", "subdomains.json")
    active_csv_path = os.path.join(output_dir, "derived", "active.csv")
    qa_checks_path = os.path.join(output_dir, "qa", "checks.json")
    report_md_path = os.path.join(output_dir, "report", "attack_surface.md")
    scope_yaml_path = os.path.join(input_dir, "scope.yaml")
    authorization_txt_path = os.path.join(input_dir, "authorization.txt")

    # Load inputs for scope
    scope_yaml_text, _ = read_text(scope_yaml_path) if os.path.isfile(scope_yaml_path) else (None, "missing")
    root_domain = parse_scope_yaml_for_domain(scope_yaml_text) if scope_yaml_text else None

    # 1) Validate subdomains.json
    json_data = None
    if os.path.isfile(subdomains_json_path):
        json_data, err = load_json(subdomains_json_path)
        if json_data is not None and isinstance(json_data, dict):
            checks["raw_json_exists"] = True

            # schema: domain (str), subdomains (array), total_found (int), enumeration_time_ms (number)
            domain_ok = isinstance(json_data.get("domain"), str) and json_data.get("domain").strip() != ""
            subdomains = json_data.get("subdomains")
            subdomains_ok = isinstance(subdomains, list)
            total_found_ok_type = isinstance(json_data.get("total_found"), int)
            etime = json_data.get("enumeration_time_ms")
            etime_ok = isinstance(etime, (int, float))
            # Validate entries
            entries_ok = True
            if subdomains_ok:
                for e in subdomains:
                    if not isinstance(e, dict):
                        entries_ok = False
                        break
                    # Required keys
                    if "subdomain" not in e or "ip_address" not in e or "status" not in e:
                        entries_ok = False
                        break
                    # subdomain string
                    if not isinstance(e["subdomain"], str) or e["subdomain"].strip() == "":
                        entries_ok = False
                        break
                    # ip_address: string or None
                    if e["ip_address"] is not None and not isinstance(e["ip_address"], str):
                        entries_ok = False
                        break
                    # status: active or inactive
                    if e["status"] not in ("active", "inactive"):
                        entries_ok = False
                        break

            checks["json_schema_ok"] = all([domain_ok, subdomains_ok, total_found_ok_type, etime_ok, entries_ok])

            # total_found equals len(subdomains)
            if checks["json_schema_ok"]:
                checks["json_total_found_matches"] = (json_data["total_found"] == len(json_data["subdomains"]))

            # domain matches scope (if we have root_domain)
            if checks["json_schema_ok"] and root_domain:
                checks["domain_matches_scope"] = (json_data["domain"].strip().lower() == root_domain.strip().lower())

            # all subdomains within scope
            if checks["json_schema_ok"] and root_domain:
                checks["subdomains_within_scope"] = all(
                    is_within_scope(e["subdomain"], root_domain) for e in json_data["subdomains"]
                )

    # 2) Validate active.csv
    active_csv_rows = []
    if checks["json_schema_ok"] and os.path.isfile(active_csv_path):
        text, _ = read_text(active_csv_path)
        if text is not None:
            lines = [ln.rstrip("\n\r") for ln in text.splitlines() if ln.strip() != "" or ln == ""]  # keep empties
            if len(lines) >= 1 and lines[0].strip() == "subdomain,ip_address":
                # parse rows
                data_rows = []
                ok_rows = True
                for ln in lines[1:]:
                    if ln.strip() == "":
                        continue
                    parts = ln.split(",")
                    if len(parts) != 2:
                        ok_rows = False
                        break
                    sub = parts[0].strip()
                    ip = parts[1].strip()
                    if sub == "" or ip == "":
                        ok_rows = False
                        break
                    data_rows.append((sub, ip))
                if ok_rows:
                    # Validate against JSON: active entries with non-empty ip
                    allowed = set()
                    for e in json_data["subdomains"]:
                        ip = e.get("ip_address")
                        if e.get("status") == "active" and isinstance(ip, str) and ip.strip() != "":
                            allowed.add((e["subdomain"].strip(), ip.strip()))
                    # No duplicates in CSV
                    no_duplicates = len(data_rows) == len(set(data_rows))
                    # All rows must be in allowed set
                    all_rows_allowed = all(r in allowed for r in data_rows)
                    # Row count equals count of active entries with non-empty IP in JSON
                    count_match = len(data_rows) == len(allowed)
                    if no_duplicates and all_rows_allowed and count_match:
                        checks["active_csv_valid"] = True
                        active_csv_rows = data_rows

    # 3) Validate qa/checks.json
    if checks["json_schema_ok"] and os.path.isfile(qa_checks_path) and checks["active_csv_valid"]:
        checks_json, err = load_json(qa_checks_path)
        if isinstance(checks_json, dict):
            tf = checks_json.get("total_found")
            ac = checks_json.get("active_count")
            iac = checks_json.get("inactive_count")
            cons = checks_json.get("consistency")
            types_ok = isinstance(tf, int) and isinstance(ac, int) and isinstance(iac, int) and isinstance(cons, str)
            if types_ok:
                # Calculate expected counts
                expected_total = json_data["total_found"]
                expected_active_with_ip = 0
                for e in json_data["subdomains"]:
                    ip = e.get("ip_address")
                    if e.get("status") == "active" and isinstance(ip, str) and ip.strip() != "":
                        expected_active_with_ip += 1
                expected_inactive = expected_total - expected_active_with_ip
                csv_rows_count = len(active_csv_rows)
                cond_a = (tf == expected_total)
                cond_b = (ac == expected_active_with_ip == csv_rows_count)
                cond_c = (iac == expected_inactive)
                cond_d = (cons.lower() == "ok") if (cond_a and cond_b and cond_c) else (cons.lower() != "ok")
                # For this check to pass, we require a, b, c true and consistency exactly "ok"
                checks["checks_json_consistent"] = cond_a and cond_b and cond_c and (cons.lower() == "ok")

    # 4) Validate report/attack_surface.md
    if checks["json_schema_ok"] and os.path.isfile(report_md_path):
        report_text, _ = read_text(report_md_path)
        if report_text is not None:
            # at least 300 words
            enough_words = count_words(report_text) >= 300
            # headings
            headings_needed = ["scope", "methodology", "findings", "risks & privacy", "next steps"]
            found = {k: False for k in headings_needed}
            for line in report_text.splitlines():
                if re.match(r'^\s*#{1,6}\s+', line):
                    h = re.sub(r'^\s*#{1,6}\s+', '', line).strip().lower()
                    h = h.rstrip(':').strip()
                    for need in headings_needed:
                        if h == need:
                            found[need] = True
            headings_ok = all(found.values())
            # reference at least one discovered subdomain
            subdomains_list = [e["subdomain"] for e in (json_data.get("subdomains") or []) if isinstance(e, dict) and isinstance(e.get("subdomain"), str)]
            content_lower = report_text.lower()
            referenced = False
            for sd in subdomains_list:
                if sd and sd.lower() in content_lower:
                    referenced = True
                    break
            checks["report_valid"] = bool(enough_words and headings_ok and referenced)

    # Compute reward as fraction of checks passed; ensure 0.0 if no outputs produced
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Baseline: if output dir missing or none of the key artifacts exist, reward must be 0.0
    required_paths = [subdomains_json_path, active_csv_path, qa_checks_path, report_md_path]
    any_required_exists = any(os.path.isfile(p) for p in required_paths)
    if not any_required_exists:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print final JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()