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

def parse_csv_services(path):
    services = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            sniffer = csv.Sniffer()
            sample = f.read(2048)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample) if sniffer.has_header(sample) else csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            if reader.fieldnames is None:
                return []
            # map headers case-insensitively
            headers = {h.strip().lower(): h for h in reader.fieldnames}
            service_key = None
            for k in headers:
                if k == "service":
                    service_key = headers[k]
                    break
            if not service_key:
                # try alternative names
                for k in headers:
                    if "service" in k:
                        service_key = headers[k]
                        break
            if not service_key:
                return []
            for row in reader:
                val = (row.get(service_key) or "").strip()
                if val:
                    services.append(val)
    except Exception:
        return []
    return services

def extract_h2_sections(lines):
    # Return list of (index, title) for H2 lines starting with "## "
    sections = []
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            title = line[3:].strip()
            sections.append((idx, title))
    return sections

def find_section_block(lines, section_title):
    # Find content block for "## <section_title>" until next H2 or end
    start_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            title = line[3:].strip()
            if title == section_title:
                start_idx = i + 1
                break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])

def find_table_with_header(lines, required_headers):
    # Find a markdown table where the header row contains all required_headers (case-sensitive match per requirement, but we'll be generous with whitespace)
    tables = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" in line and all(h in line for h in required_headers):
            # Possible header
            header_idx = i
            # Next line should be separator like |---|---|
            sep_idx = i + 1
            if sep_idx < len(lines) and "|" in lines[sep_idx] and re.search(r"-", lines[sep_idx]):
                # Collect rows until a blank line or a line without '|'
                rows = [lines[header_idx], lines[sep_idx]]
                k = sep_idx + 1
                while k < len(lines) and "|" in lines[k] and lines[k].strip() != "":
                    rows.append(lines[k])
                    k += 1
                tables.append(rows)
                i = k
                continue
        i += 1
    return tables

def parse_table_rows(table_lines):
    # Return (headers, rows) where headers is list of header names, and rows is list of lists of cell texts
    if len(table_lines) < 2:
        return ([], [])
    header = [c.strip() for c in table_lines[0].split("|")]
    # Remove possible leading/trailing empty from split due to starting/ending pipe
    if header and header[0] == "":
        header = header[1:]
    if header and header[-1] == "":
        header = header[:-1]
    rows = []
    for rowline in table_lines[2:]:
        cells = [c.strip() for c in rowline.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if any(cells):
            rows.append(cells)
    return (header, rows)

def extract_company_name(company_profile):
    # Expect keys company_name or name
    if not isinstance(company_profile, dict):
        return None
    if "company_name" in company_profile and isinstance(company_profile["company_name"], str) and company_profile["company_name"].strip():
        return company_profile["company_name"].strip()
    if "name" in company_profile and isinstance(company_profile["name"], str) and company_profile["name"].strip():
        return company_profile["name"].strip()
    # Try nested
    for key in ["company", "org", "profile"]:
        if key in company_profile and isinstance(company_profile[key], dict):
            inner = company_profile[key]
            for k in ["company_name", "name"]:
                if k in inner and isinstance(inner[k], str) and inner[k].strip():
                    return inner[k].strip()
    return None

def parse_policy_yaml_content(content):
    # Lightweight parser targeted to required keys. Handles simple key: value, nested under security, and lists both inline [a, b] and dash lists.
    result = {}
    current_top = None
    current_list_key = None
    indent_stack = [0]
    lines = content.splitlines()

    def normalize_inline_list(val):
        s = val.strip()
        if s.startswith("[") and s.endswith("]"):
            inside = s[1:-1]
            parts = [p.strip().strip("\"'") for p in inside.split(",") if p.strip() != ""]
            return parts
        return None

    i = 0
    while i < len(lines):
        line = lines[i]
        raw = line
        # strip comments (#...) if present
        stripped = re.split(r'\s+#', raw, maxsplit=1)[0].rstrip("\n")
        if not stripped.strip():
            i += 1
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        l = stripped.strip()
        if l.startswith("- "):
            # list item for current_list_key under current_top or top-level list
            item = l[2:].strip()
            if current_list_key:
                # add to result[current_list_key]
                parent = result if current_top is None else result.get(current_top)
                if current_top and not isinstance(parent, dict):
                    result[current_top] = {}
                    parent = result[current_top]
                if current_top:
                    lst = parent.get(current_list_key)
                    if not isinstance(lst, list):
                        lst = []
                        parent[current_list_key] = lst
                    lst.append(item)
                else:
                    lst = result.get(current_list_key)
                    if not isinstance(lst, list):
                        lst = []
                        result[current_list_key] = lst
                    lst.append(item)
            i += 1
            continue

        # key: value or key:
        if ":" in l:
            key, val = l.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Determine nesting by indent: indent 0 => top-level
            if indent == 0:
                current_top = key
                current_list_key = None
                if val == "":
                    # start of mapping or list block
                    if key not in result:
                        result[key] = {}
                else:
                    inline_list = normalize_inline_list(val)
                    if inline_list is not None:
                        result[key] = inline_list
                    else:
                        result[key] = val
            else:
                # nested under current_top
                if current_top is None:
                    current_top = key  # unexpected, but set
                    result[current_top] = {}
                if not isinstance(result.get(current_top), dict):
                    result[current_top] = {}
                if val == "":
                    # nested block, might be list
                    result[current_top][key] = []
                    current_list_key = key
                else:
                    inline_list = normalize_inline_list(val)
                    if inline_list is not None:
                        result[current_top][key] = inline_list
                    else:
                        result[current_top][key] = val
                        current_list_key = None
        i += 1
    # Normalize: if some keys were set to {}, keep as dict
    return result

def verify_policy_yaml(path):
    content = read_text(path)
    if content is None:
        return None
    data = None
    # Try PyYAML if available
    try:
        import yaml  # type: ignore
        try:
            data = yaml.safe_load(content)
        except Exception:
            data = None
    except Exception:
        data = None
    if data is None or not isinstance(data, dict):
        # Fallback lightweight parse
        data = parse_policy_yaml_content(content)
    return data if isinstance(data, dict) else None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # guide.md checks
        "guide_exists": False,
        "guide_has_h1": False,
        "guide_has_sections_ordered": False,
        "guide_includes_company_name": False,
        "guide_has_services_table_header": False,
        "guide_table_includes_all_services": False,
        "security_section_mentions_rbac": False,
        "security_section_mentions_encryption_in_transit": False,
        "security_section_mentions_encryption_at_rest": False,
        # policy.yaml checks
        "policy_exists": False,
        "policy_parses_yaml": False,
        "policy_has_required_keys": False,
        "policy_security_authorization_rbac": False,
        "policy_security_encryption_contains_both": False,
        "policy_versioning_semver": False,
        "policy_review_contains_both": False,
        "policy_style_guide_contains_both": False,
        # checklist.json checks
        "checklist_exists": False,
        "checklist_parses_json_array": False,
        "checklist_length_ge_8": False,
        "checklist_items_have_fields": False,
        "checklist_has_security_task": False,
        "checklist_has_performance_task": False,
        "checklist_has_migration_task": False,
        "checklist_has_debug_task": False,
    }

    # Paths
    guide_path = os.path.join(output_dir, "swagger_adoption", "guide.md")
    policy_path = os.path.join(output_dir, "swagger_adoption", "policy.yaml")
    checklist_path = os.path.join(output_dir, "swagger_adoption", "checklist.json")

    # Inputs
    company_profile_path = os.path.join(input_dir, "company_profile.json")
    api_inventory_path = os.path.join(input_dir, "api_inventory.csv")

    company_profile = read_json(company_profile_path)
    company_name = extract_company_name(company_profile) if company_profile else None
    csv_services = parse_csv_services(api_inventory_path)

    # guide.md validations
    guide_content = read_text(guide_path)
    if guide_content is not None:
        checks["guide_exists"] = True
        lines = guide_content.splitlines()
        # H1
        for l in lines:
            if l.strip().startswith("# Swagger Adoption Guide"):
                checks["guide_has_h1"] = True
                break
        # H2 sections order and uniqueness
        required_sections = [
            "Overview",
            "Quickstart",
            "Patterns & Anti-Patterns",
            "Security",
            "Performance",
            "Migration Plan",
            "Debugging",
            "Cheatsheet",
        ]
        h2s = extract_h2_sections(lines)
        h2_titles = [t for _, t in h2s]
        indices = []
        unique_ok = True
        order_ok = True
        for sec in required_sections:
            count = sum(1 for _, t in h2s if t == sec)
            if count != 1:
                unique_ok = False
                break
            # find index of this section among lines
            for idx, t in h2s:
                if t == sec:
                    indices.append(idx)
                    break
        if unique_ok and all(indices[i] < indices[i+1] for i in range(len(indices)-1)):
            checks["guide_has_sections_ordered"] = True

        # Company name appears
        if company_name:
            if company_name in guide_content:
                checks["guide_includes_company_name"] = True

        # Security section phrases
        security_block = find_section_block(lines, "Security")
        sec_lower = security_block.lower()
        if "role-based access control" in sec_lower:
            checks["security_section_mentions_rbac"] = True
        if "encryption in transit" in sec_lower:
            checks["security_section_mentions_encryption_in_transit"] = True
        if "encryption at rest" in sec_lower:
            checks["security_section_mentions_encryption_at_rest"] = True

        # Services table header and inclusion
        tables = find_table_with_header(lines, ["Service", "Owner"])
        if tables:
            checks["guide_has_services_table_header"] = True
            # Check services included
            all_services_found = True
            # For each found table, parse header and rows, find 'Service' column index
            found_services = set()
            for tbl in tables:
                header, rows = parse_table_rows(tbl)
                # find 'Service' column
                try:
                    service_col_idx = [h.strip() for h in header].index("Service")
                except ValueError:
                    continue
                for row in rows:
                    if service_col_idx < len(row):
                        svc = row[service_col_idx].strip()
                        if svc:
                            found_services.add(svc)
            # Verify each service from CSV appears in found_services
            for s in csv_services:
                if s not in found_services:
                    all_services_found = False
                    break
            if csv_services and all_services_found:
                checks["guide_table_includes_all_services"] = True
            # If csv is empty or couldn't be parsed, do not pass inclusion check

    # policy.yaml validations
    if os.path.isfile(policy_path):
        checks["policy_exists"] = True
        policy_data = verify_policy_yaml(policy_path)
        if isinstance(policy_data, dict):
            checks["policy_parses_yaml"] = True
            # Required keys
            required_keys = ["security", "versioning", "review", "style_guide"]
            has_keys = all(k in policy_data for k in required_keys)
            if has_keys:
                checks["policy_has_required_keys"] = True
            # security.authorization == role_based_access_control
            try:
                auth = None
                if isinstance(policy_data.get("security"), dict):
                    auth = policy_data["security"].get("authorization")
                if auth == "role_based_access_control":
                    checks["policy_security_authorization_rbac"] = True
            except Exception:
                pass
            # security.encryption contains both
            try:
                enc = None
                if isinstance(policy_data.get("security"), dict):
                    enc = policy_data["security"].get("encryption")
                if isinstance(enc, list):
                    if "in_transit" in enc and "at_rest" in enc:
                        checks["policy_security_encryption_contains_both"] = True
            except Exception:
                pass
            # versioning == semver
            if policy_data.get("versioning") == "semver":
                checks["policy_versioning_semver"] = True
            # review includes both
            rv = policy_data.get("review")
            if isinstance(rv, list):
                if "spec review" in rv and "code quality review" in rv:
                    checks["policy_review_contains_both"] = True
            # style_guide includes both
            sg = policy_data.get("style_guide")
            if isinstance(sg, list):
                if "no hardcoded credentials" in sg and "document all custom configurations" in sg:
                    checks["policy_style_guide_contains_both"] = True

    # checklist.json validations
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        checklist = read_json(checklist_path)
        if isinstance(checklist, list):
            checks["checklist_parses_json_array"] = True
            if len(checklist) >= 8:
                checks["checklist_length_ge_8"] = True
            # Validate items fields
            items_ok = True
            has_security = False
            has_perf = False
            has_migration = False
            has_debug = False
            for item in checklist:
                if not isinstance(item, dict):
                    items_ok = False
                    break
                id_ok = isinstance(item.get("id"), str)
                title_ok = isinstance(item.get("title"), str)
                status_ok = isinstance(item.get("status"), str)
                if not (id_ok and title_ok and status_ok):
                    items_ok = False
                    break
                title_lower = item.get("title", "").lower()
                if "security" in title_lower:
                    has_security = True
                if "performance" in title_lower:
                    has_perf = True
                if "migration" in title_lower or "migrate" in title_lower:
                    has_migration = True
                if "debug" in title_lower or "debugging" in title_lower:
                    has_debug = True
            if items_ok:
                checks["checklist_items_have_fields"] = True
            if has_security:
                checks["checklist_has_security_task"] = True
            if has_perf:
                checks["checklist_has_performance_task"] = True
            if has_migration:
                checks["checklist_has_migration_task"] = True
            if has_debug:
                checks["checklist_has_debug_task"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if output dir missing or none of the three required files exist, reward = 0.0
    required_files_exist = any([checks["guide_exists"], checks["policy_exists"], checks["checklist_exists"]])
    if not required_files_exist:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()