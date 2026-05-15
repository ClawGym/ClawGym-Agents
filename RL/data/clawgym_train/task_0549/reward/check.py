import json
import os
import sys
import csv
import re
import string

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_hosts_csv(csv_path):
    hosts = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                hosts.append(row)
    except Exception:
        pass
    return hosts

def to_bool(val):
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    if s in ("true", "yes", "y", "1", "on"):
        return True
    if s in ("false", "no", "n", "0", "off"):
        return False
    return False

def strip_yaml_comment(line):
    # remove comments starting with # outside quotes
    if "#" not in line:
        return line
    out = []
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out)

def parse_simple_yaml(yaml_path):
    """
    Minimal YAML parser for flat key: value pairs and simple lists:
    key: value
    key:
      - item1
      - item2
    Also supports inline lists: key: [a, b, c]
    """
    data = {}
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return data

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\n")
        line = strip_yaml_comment(raw).rstrip()
        i += 1
        if not line.strip():
            continue
        # detect list block
        m_key_only = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*:\s*$", line)
        if m_key_only:
            key = m_key_only.group(1)
            items = []
            # read indented list items
            while i < len(lines):
                nxt_raw = lines[i].rstrip("\n")
                nxt = strip_yaml_comment(nxt_raw).rstrip()
                if not nxt.strip():
                    i += 1
                    continue
                if re.match(r"^\s*-\s*(.+?)\s*$", nxt):
                    item = re.match(r"^\s*-\s*(.+?)\s*$", nxt).group(1)
                    item = item.strip().strip("'").strip('"')
                    items.append(item)
                    i += 1
                    continue
                # stop if next non-list or dedent
                break
            data[key] = items
            continue

        # key: value (inline)
        m_kv = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*:\s*(.+?)\s*$", line)
        if m_kv:
            key = m_kv.group(1)
            val = m_kv.group(2).strip()
            # inline list [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if inner:
                    parts = [p.strip() for p in inner.split(",")]
                    cleaned = [p.strip().strip("'").strip('"') for p in parts if p != ""]
                else:
                    cleaned = []
                data[key] = cleaned
                continue
            # coerce types
            low = val.lower()
            if low in ("true", "false", "yes", "no", "on", "off"):
                data[key] = to_bool(val)
            else:
                # numeric?
                if re.fullmatch(r"[+-]?\d+", val):
                    try:
                        data[key] = int(val)
                    except Exception:
                        data[key] = val.strip().strip("'").strip('"')
                elif re.fullmatch(r"[+-]?\d+\.\d+", val):
                    try:
                        data[key] = float(val)
                    except Exception:
                        data[key] = val.strip().strip("'").strip('"')
                else:
                    data[key] = val.strip().strip("'").strip('"')
            continue
        # ignore other constructs
    return data

def parse_orgs_json(json_path):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # Accept 'org', 'organization', or 'cortex_org_name'
        if isinstance(obj, dict):
            for k in ("org", "organization", "cortex_org_name", "org_name", "name"):
                if k in obj and isinstance(obj[k], str):
                    return obj[k]
        # If array of orgs, take first string or dict.name
        if isinstance(obj, list) and obj:
            first = obj[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                for k in ("org", "organization", "name"):
                    if k in first and isinstance(first[k], str):
                        return first[k]
    except Exception:
        pass
    return None

def get_required_policy(yaml_data):
    """
    Normalize password policy from various possible keys.
    Returns dict with:
      min_length (int, default 12),
      require_upper, require_lower, require_digit, require_special (bools),
      require_exclamation (bool),
      required_special_chars (set of chars)
    """
    policy = {}
    # min length
    min_len = None
    for k in ("min_length", "minLength", "minimum_length", "minlen", "length_min"):
        if isinstance(yaml_data.get(k), int):
            min_len = yaml_data.get(k)
            break
        v = yaml_data.get(k)
        if isinstance(v, str) and v.isdigit():
            min_len = int(v)
            break
    if min_len is None:
        min_len = 12
    policy["min_length"] = min_len

    # boolean requirements
    def pick_bool(keys):
        for kk in keys:
            if kk in yaml_data:
                return to_bool(yaml_data.get(kk))
        return False

    policy["require_upper"] = pick_bool(["require_upper", "upper_required", "uppercase_required", "need_upper", "requireUpper"])
    policy["require_lower"] = pick_bool(["require_lower", "lower_required", "lowercase_required", "need_lower", "requireLower"])
    policy["require_digit"] = pick_bool(["require_digit", "digits_required", "numbers_required", "need_digit", "requireNumber"])
    policy["require_special"] = pick_bool(["require_special", "special_required", "need_special", "requireSpecial"])

    # required special chars list
    required_chars = set()
    for key in ("required_special_chars", "special_must_include", "must_include", "must_include_chars", "include_chars"):
        if key in yaml_data:
            v = yaml_data[key]
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        for ch in item:
                            # if a multi-char token like "!" we add as individual chars
                            required_chars.add(ch)
            elif isinstance(v, str):
                # split by comma if present, else treat as sequence of chars
                if "," in v:
                    for part in v.split(","):
                        part = part.strip().strip("'").strip('"')
                        for ch in part:
                            required_chars.add(ch)
                else:
                    for ch in v:
                        required_chars.add(ch)
    require_excl = pick_bool(["require_exclamation", "must_include_exclamation", "require_bang"])
    if require_excl:
        required_chars.add("!")
    policy["required_special_chars"] = required_chars
    policy["require_exclamation"] = ("!" in required_chars)

    return policy

def password_meets_policy(pw, policy):
    if not isinstance(pw, str):
        return False
    if len(pw) < policy.get("min_length", 12):
        return False
    # character classes
    if policy.get("require_upper", False) and not any(c.isupper() for c in pw):
        return False
    if policy.get("require_lower", False) and not any(c.islower() for c in pw):
        return False
    if policy.get("require_digit", False) and not any(c.isdigit() for c in pw):
        return False
    if policy.get("require_special", False):
        # consider ASCII punctuation as special
        if not any(c in string.punctuation for c in pw):
            return False
    # specific required special chars
    req_chars = policy.get("required_special_chars", set())
    for ch in req_chars:
        if ch.strip() == "":
            continue
        if ch not in pw:
            return False
    return True

def extract_host_from_ssh_target(ssh_target):
    """
    ssh_target expected 'user@host' or just 'host'. Extract 'host' part.
    """
    if not isinstance(ssh_target, str):
        return None
    if "@" in ssh_target:
        return ssh_target.split("@", 1)[1]
    return ssh_target

def contains_ports_list(ports_field):
    # Accept list of ints/strings; must include 9000 and 9001
    try:
        if not isinstance(ports_field, list):
            return False
        vals = set()
        for p in ports_field:
            if isinstance(p, int):
                vals.add(p)
            elif isinstance(p, str):
                # extract digits
                m = re.match(r"^\s*(\d+)\s*$", p)
                if m:
                    vals.add(int(m.group(1)))
        return (9000 in vals) and (9001 in vals)
    except Exception:
        return False

def nonempty_minlen(s, minlen):
    return isinstance(s, str) and len(s.strip()) >= minlen

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_deployment_report_json": False,
        "report_has_required_keys": False,
        "ssh_target_valid": False,
        "urls_match_host_and_ports": False,
        "ports_include_9000_and_9001": False,
        "admin_user_correct": False,
        "admin_password_policy_satisfied": False,
        "thehive_secret_length_ok": False,
        "cortex_org_name_matches": False,
        "api_keys_nonempty_min20": False,
        "integration_key_source_correct": False,
        "has_runbook_md": False,
        "runbook_mentions_rationale": False,
        "runbook_mentions_csrf_token": False,
        "runbook_mentions_password_change_endpoint": False,
        "runbook_mentions_api_status_and_ports": False,
        "runbook_has_rollback_compose_down": False,
        "runbook_has_security_hardening_section": False,
        "runbook_mentions_credentials_saved_path": False,
    }

    # Load inputs
    hosts_path = os.path.join(input_dir, "hosts.csv")
    secpol_path = os.path.join(input_dir, "security_policy.yaml")
    orgs_path = os.path.join(input_dir, "orgs.json")

    hosts_rows = parse_hosts_csv(hosts_path)
    yaml_data = parse_simple_yaml(secpol_path)
    org_name_input = parse_orgs_json(orgs_path)

    # Load outputs
    report_path = os.path.join(output_dir, "deployment_report.json")
    runbook_path = os.path.join(output_dir, "runbook.md")

    report = None
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            checks["has_deployment_report_json"] = True
        except Exception:
            report = None

    # Validate deployment_report.json content
    required_keys = [
        "ssh_target",
        "thehive_url",
        "cortex_url",
        "admin_user",
        "admin_password",
        "thehive_secret",
        "cortex_org_name",
        "ports",
        "thehive_api_key",
        "cortex_superadmin_api_key",
        "cortex_org_admin_api_key",
        "integration_key_source",
    ]
    if checks["has_deployment_report_json"]:
        if all(k in report for k in required_keys):
            checks["report_has_required_keys"] = True

        if checks["report_has_required_keys"]:
            ssh_target = report.get("ssh_target")
            thehive_url = report.get("thehive_url", "")
            cortex_url = report.get("cortex_url", "")
            admin_user = report.get("admin_user")
            admin_password = report.get("admin_password")
            thehive_secret = report.get("thehive_secret")
            cortex_org_name = report.get("cortex_org_name")
            ports_field = report.get("ports")
            thehive_api_key = report.get("thehive_api_key")
            cortex_super_key = report.get("cortex_superadmin_api_key")
            cortex_org_key = report.get("cortex_org_admin_api_key")
            integration_key_source = report.get("integration_key_source")

            # ssh_target_valid: must exactly match a target in hosts.csv that meets constraints
            # hosts.csv columns: target,user,env,docker_ready,ram_gb,notes
            valid_targets = set()
            try:
                for row in hosts_rows:
                    try:
                        env = (row.get("env") or "").strip().lower()
                        docker_ready = (row.get("docker_ready") or "").strip().lower()
                        ram = row.get("ram_gb")
                        ram_val = None
                        if isinstance(ram, (int, float)):
                            ram_val = float(ram)
                        else:
                            if ram is not None:
                                s = str(ram).strip()
                                if s:
                                    try:
                                        ram_val = float(s)
                                    except Exception:
                                        ram_val = None
                        if env == "lab" and docker_ready == "yes" and (ram_val is not None and ram_val >= 4.0):
                            tgt = (row.get("target") or "").strip()
                            # If target not present, attempt combine user@host
                            if not tgt:
                                user = (row.get("user") or "").strip()
                                host = (row.get("host") or "").strip()
                                if user and host:
                                    tgt = f"{user}@{host}"
                            if tgt:
                                valid_targets.add(tgt)
                    except Exception:
                        continue
            except Exception:
                valid_targets = set()

            if isinstance(ssh_target, str) and ssh_target in valid_targets:
                checks["ssh_target_valid"] = True

            # urls must embed host and ports
            host = extract_host_from_ssh_target(ssh_target) if isinstance(ssh_target, str) else None
            def url_contains_host_and_port(url, host, port):
                if not isinstance(url, str) or not host:
                    return False
                return (host in url) and (f":{port}" in url)

            if url_contains_host_and_port(thehive_url, host, 9000) and url_contains_host_and_port(cortex_url, host, 9001):
                checks["urls_match_host_and_ports"] = True

            # ports list includes 9000 and 9001
            if contains_ports_list(ports_field):
                checks["ports_include_9000_and_9001"] = True

            # admin_user is exactly admin@thehive.local
            if admin_user == "admin@thehive.local":
                checks["admin_user_correct"] = True

            # admin_password satisfies policy
            policy = get_required_policy(yaml_data)
            if password_meets_policy(admin_password, policy):
                checks["admin_password_policy_satisfied"] = True

            # thehive_secret length >= 32
            if nonempty_minlen(thehive_secret, 32):
                checks["thehive_secret_length_ok"] = True

            # cortex_org_name matches input org
            if isinstance(cortex_org_name, str) and isinstance(org_name_input, str) and cortex_org_name.strip() == org_name_input.strip():
                checks["cortex_org_name_matches"] = True

            # API keys non-empty and at least 20 chars
            if nonempty_minlen(thehive_api_key, 20) and nonempty_minlen(cortex_super_key, 20) and nonempty_minlen(cortex_org_key, 20):
                checks["api_keys_nonempty_min20"] = True

            # integration_key_source must equal "cortex_org_admin"
            if integration_key_source == "cortex_org_admin":
                checks["integration_key_source_correct"] = True

    # Validate runbook.md content
    runbook_text = None
    if os.path.isfile(runbook_path):
        runbook_text = read_text(runbook_path)
        if isinstance(runbook_text, str):
            checks["has_runbook_md"] = True

    if checks["has_runbook_md"] and isinstance(runbook_text, str):
        text = runbook_text

        # mentions rationale for chosen host: check contains ssh_target and 'rationale' or 'reason' or 'criteria'
        has_rationale_token = bool(re.search(r"\b(rationale|reason|criteria)\b", text, re.IGNORECASE))
        ssh_target_in_text = False
        if checks["has_deployment_report_json"] and checks["report_has_required_keys"]:
            ssh_target_val = report.get("ssh_target")
            if isinstance(ssh_target_val, str) and ssh_target_val and ssh_target_val in text:
                ssh_target_in_text = True
        # If no ssh_target available, fallback: look for 'Selected host' phrase
        if (has_rationale_token and ssh_target_in_text) or (has_rationale_token and re.search(r"selected host|host selection", text, re.IGNORECASE)):
            checks["runbook_mentions_rationale"] = True

        # Must include literal token "CORTEX-XSRF-TOKEN"
        if "CORTEX-XSRF-TOKEN" in text:
            checks["runbook_mentions_csrf_token"] = True

        # Must include "/password/change"
        if "/password/change" in text:
            checks["runbook_mentions_password_change_endpoint"] = True

        # Must include reference to API status checks and mention ports 9000 and 9001
        has_api_status = "/api/status" in text
        mentions_9000 = re.search(r"\b9000\b", text) is not None
        mentions_9001 = re.search(r"\b9001\b", text) is not None
        if has_api_status and mentions_9000 and mentions_9001:
            checks["runbook_mentions_api_status_and_ports"] = True

        # Rollback guidance mentioning "docker compose down" (case-insensitive)
        if re.search(r"docker\s+compose\s+down", text, re.IGNORECASE):
            checks["runbook_has_rollback_compose_down"] = True

        # Dedicated section or clear heading for "Security Hardening"
        if re.search(r"security\s+hardening", text, re.IGNORECASE):
            checks["runbook_has_security_hardening_section"] = True

        # Mentions credentials saved to "~/thehive-cortex/api-keys.txt"
        if "~/thehive-cortex/api-keys.txt" in text:
            checks["runbook_mentions_credentials_saved_path"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure baseline no-op yields 0.0 (if both files missing or required file missing)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    # Print single JSON line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()