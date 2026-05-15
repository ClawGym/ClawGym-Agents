import json
import os
import sys
import csv
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "commands_exists": False,
        "commands_line_count_ok": False,
        "commands_targets_ok": False,
        "commands_timeout_ok": False,
        "commands_http_flag_ok": False,
        "plan_exists": False,
        "plan_json_valid": False,
        "plan_groups_set_ok": False,
        "plan_fields_ok": False,
        "plan_counts_ok": False,
        "plan_targets_ok": False,
        "readme_exists": False,
        "readme_mentions_ok": False,
    }

    # Helpers
    def unquote(s: str) -> str:
        s2 = s.strip()
        if len(s2) >= 2 and ((s2[0] == '"' and s2[-1] == '"') or (s2[0] == "'" and s2[-1] == "'")):
            return s2[1:-1]
        return s2

    def parse_config_yaml(path):
        timeout = None
        groups = []
        in_groups = False
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return None, None
        for raw in lines:
            # Remove comments
            line_nl = raw.rstrip("\n")
            # Remove inline comments starting with #
            if "#" in line_nl:
                idx = line_nl.find("#")
                if idx != -1:
                    before = line_nl[:idx]
                else:
                    before = line_nl
            else:
                before = line_nl
            line = before.rstrip()
            if not line.strip():
                continue

            # Top-level keys
            m_timeout = re.match(r"^\s*timeout\s*:\s*(.+?)\s*$", line)
            if m_timeout:
                val = m_timeout.group(1).strip()
                # Strip quotes
                val = unquote(val)
                if re.fullmatch(r"\d+", val):
                    try:
                        timeout = int(val)
                    except Exception:
                        pass
                in_groups = False
                continue

            m_groups = re.match(r"^\s*groups\s*:\s*(.*)$", line)
            if m_groups:
                after = m_groups.group(1).strip()
                if after.startswith("[") and after.endswith("]"):
                    inside = after[1:-1].strip()
                    if inside:
                        items = [unquote(x.strip()) for x in inside.split(",") if x.strip()]
                        groups.extend(items)
                    in_groups = False
                else:
                    in_groups = True
                continue

            if in_groups:
                m_item = re.match(r"^\s*-\s*(.+?)\s*$", line)
                if m_item:
                    groups.append(unquote(m_item.group(1).strip()))
                    continue
                # If we see another top-level key, stop groups
                if re.match(r"^\s*\w+\s*:\s*.*$", line):
                    in_groups = False
                    # Do not process this other key further
                    continue

        return timeout, groups

    def parse_services_csv(path, config_groups):
        # Returns ordered mapping per group and counts
        expected_targets_by_group = {g: [] for g in config_groups}
        http_count_by_group = {g: 0 for g in config_groups}
        tcp_count_by_group = {g: 0 for g in config_groups}
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Normalize keys to lowercase
                    row_norm = { (k or "").strip().lower(): (v if v is not None else "") for k, v in row.items() }
                    g = (row_norm.get("group", "") or "").strip()
                    host = (row_norm.get("host", "") or "").strip()
                    port = (row_norm.get("port", "") or "").strip()
                    protocol = (row_norm.get("protocol", "") or "").strip().lower()
                    if g in expected_targets_by_group:
                        # Construct host:port exactly as trimmed from CSV
                        target = f"{host}:{port}"
                        expected_targets_by_group[g].append(target)
                        if protocol == "http":
                            http_count_by_group[g] += 1
                        elif protocol == "tcp":
                            tcp_count_by_group[g] += 1
                        else:
                            # Unknown protocol does not count towards http/tcp, but still included in targets if present.
                            pass
        except Exception:
            return None, None, None
        return expected_targets_by_group, http_count_by_group, tcp_count_by_group

    # Load inputs
    config_yaml_path = os.path.join(input_dir, "config.yaml")
    services_csv_path = os.path.join(input_dir, "services.csv")

    timeout, groups = parse_config_yaml(config_yaml_path)
    expected_targets_by_group = None
    http_count_by_group = None
    tcp_count_by_group = None
    if timeout is not None and groups is not None:
        expected_targets_by_group, http_count_by_group, tcp_count_by_group = parse_services_csv(services_csv_path, groups if groups is not None else [])

    # Prepare expected data only if inputs parsed correctly
    inputs_ok = (
        timeout is not None and
        groups is not None and
        expected_targets_by_group is not None and
        http_count_by_group is not None and
        tcp_count_by_group is not None
    )

    # 1) Validate commands.txt
    commands_path = os.path.join(output_dir, "commands.txt")
    if os.path.isfile(commands_path):
        checks["commands_exists"] = True
        try:
            with open(commands_path, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
            # Non-empty lines only (strip whitespace)
            lines = [ln.strip() for ln in raw_lines if ln.strip() != ""]
        except Exception:
            lines = []
        if inputs_ok:
            # Check line count equals number of groups (preserve order)
            if len(lines) == len(groups):
                checks["commands_line_count_ok"] = True
            # For per-line checks, require line count ok
            if checks["commands_line_count_ok"]:
                hostport_re = re.compile(r"^[^:\s]+:\d+$")
                all_targets_ok = True
                all_timeout_ok = True
                all_http_ok = True
                for i, grp in enumerate(groups):
                    line = lines[i]
                    tokens = line.split()
                    # Extract host:port tokens in order
                    line_targets = [t for t in tokens if hostport_re.match(t)]
                    expected_targets = expected_targets_by_group.get(grp, []) if expected_targets_by_group is not None else []
                    if line_targets != expected_targets:
                        all_targets_ok = False
                    # Timeout flag pair
                    expected_timeout_str = str(timeout) if timeout is not None else None
                    found_timeout_pair = False
                    for j in range(len(tokens) - 1):
                        if tokens[j] == "--timeout" and expected_timeout_str is not None and tokens[j + 1] == expected_timeout_str:
                            found_timeout_pair = True
                            break
                    if not found_timeout_pair:
                        all_timeout_ok = False
                    # HTTP flag presence
                    has_http_flag = "--http" in tokens
                    expected_has_http_flag = (http_count_by_group.get(grp, 0) if http_count_by_group is not None else 0) > 0
                    if has_http_flag != expected_has_http_flag:
                        all_http_ok = False
                checks["commands_targets_ok"] = all_targets_ok
                checks["commands_timeout_ok"] = all_timeout_ok
                checks["commands_http_flag_ok"] = all_http_ok
    # 2) Validate plan.json
    plan_path = os.path.join(output_dir, "plan.json")
    plan_data = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
            if isinstance(plan_data, list):
                checks["plan_json_valid"] = True
        except Exception:
            plan_data = None

        if inputs_ok and isinstance(plan_data, list):
            # Group set check
            groups_set = set(groups)
            if len(plan_data) == len(groups):
                found_groups = []
                type_and_fields_ok = True
                counts_ok = True
                targets_ok = True
                # Build map by group for comparison
                plan_by_group = {}
                for item in plan_data:
                    if not isinstance(item, dict):
                        type_and_fields_ok = False
                        continue
                    # Required fields
                    req_fields = ["group", "total", "http_count", "tcp_count", "targets"]
                    if any(field not in item for field in req_fields):
                        type_and_fields_ok = False
                        continue
                    if not isinstance(item["group"], str):
                        type_and_fields_ok = False
                    if not isinstance(item["total"], int):
                        type_and_fields_ok = False
                    if not isinstance(item["http_count"], int):
                        type_and_fields_ok = False
                    if not isinstance(item["tcp_count"], int):
                        type_and_fields_ok = False
                    if not isinstance(item["targets"], list):
                        type_and_fields_ok = False
                    else:
                        # Ensure all targets are strings of host:port form
                        hp_re = re.compile(r"^[^:\s]+:\d+$")
                        for t in item["targets"]:
                            if not isinstance(t, str) or not hp_re.match(t):
                                type_and_fields_ok = False
                                break
                    grp = item.get("group")
                    found_groups.append(grp)
                    # Store latest occurrence; duplicates handled below
                    plan_by_group[grp] = item
                # Groups set must match and duplicates must not exist
                if set(found_groups) == groups_set and len(found_groups) == len(groups_set):
                    checks["plan_groups_set_ok"] = True
                else:
                    checks["plan_groups_set_ok"] = False

                # Validate counts and targets per group
                for grp in groups:
                    if grp not in plan_by_group:
                        counts_ok = False
                        targets_ok = False
                        type_and_fields_ok = False
                        continue
                    item = plan_by_group[grp]
                    exp_http = http_count_by_group.get(grp, 0)
                    exp_tcp = tcp_count_by_group.get(grp, 0)
                    exp_total = exp_http + exp_tcp
                    if not (item.get("http_count") == exp_http and item.get("tcp_count") == exp_tcp and item.get("total") == exp_total):
                        counts_ok = False
                    exp_targets = expected_targets_by_group.get(grp, [])
                    if item.get("targets") != exp_targets:
                        targets_ok = False

                checks["plan_fields_ok"] = type_and_fields_ok
                checks["plan_counts_ok"] = counts_ok
                checks["plan_targets_ok"] = targets_ok
            else:
                # Wrong length -> groups set check fails
                checks["plan_groups_set_ok"] = False

    # 3) Validate README.md
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_text = f.read()
            if ("commands.txt" in readme_text) and ("plan.json" in readme_text):
                checks["readme_mentions_ok"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks (output-dependent only)
    scoring_keys = [
        "commands_exists",
        "commands_line_count_ok",
        "commands_targets_ok",
        "commands_timeout_ok",
        "commands_http_flag_ok",
        "plan_exists",
        "plan_json_valid",
        "plan_groups_set_ok",
        "plan_fields_ok",
        "plan_counts_ok",
        "plan_targets_ok",
        "readme_exists",
        "readme_mentions_ok",
    ]
    passed = sum(1 for k in scoring_keys if checks.get(k, False))
    total = len(scoring_keys)
    reward = (passed / total) if total > 0 else 0.0

    # Enforce baseline: if output directory missing or all three artifacts missing -> reward 0.0
    artifacts_present = any(os.path.isfile(os.path.join(output_dir, fname)) for fname in ["commands.txt", "plan.json", "README.md"])
    if not artifacts_present:
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()