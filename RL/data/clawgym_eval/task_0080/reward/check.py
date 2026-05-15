import json
import os
import sys
import csv
import math

def parse_simple_yaml(path):
    data = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    continue
                # Remove inline comments only if they start the line or value is unquoted
                # For simplicity assume no inline comments within quoted strings
                if '#' in line:
                    hash_idx = line.find('#')
                    if hash_idx == 0:
                        continue
                    line = line[:hash_idx].rstrip()
                if not line:
                    continue
                if ':' not in line:
                    continue
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()
                # Remove surrounding quotes if present
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                # Try to parse integers
                v = val
                try:
                    if v.lower().startswith('0x'):
                        v = int(v, 16)
                    else:
                        v = int(v)
                except Exception:
                    v = val
                data[key] = v
    except FileNotFoundError:
        return {}
    return data

def read_processes_csv(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            row = {}
            # Required headers: pid,ppid,owner,age_seconds,rss_kb,cmdline,parent_cmdline
            try:
                row['pid'] = int(r['pid'])
            except Exception:
                continue
            try:
                row['ppid'] = int(r['ppid'])
            except Exception:
                row['ppid'] = None
            row['owner'] = (r.get('owner') or '').strip()
            try:
                row['age_seconds'] = int(r['age_seconds'])
            except Exception:
                row['age_seconds'] = 0
            try:
                row['rss_kb'] = int(r['rss_kb'])
            except Exception:
                row['rss_kb'] = 0
            row['cmdline'] = r.get('cmdline') or ''
            row['parent_cmdline'] = r.get('parent_cmdline') or ''
            rows.append(row)
    return rows

def compute_expected(processes, user, pattern, min_age):
    # Identify OpenClaw-launched browsers:
    # owner == user, cmdline contains pattern, cmdline contains one of browser identifiers
    browser_substrings = ['chrome', 'chromium', 'brave', 'msedge', 'firefox']
    def is_browser_cmd(cmd):
        return any(sub in cmd for sub in browser_substrings)

    openclaw_browsers = []
    for proc in processes:
        if proc['owner'] != user:
            continue
        if pattern not in proc['cmdline']:
            continue
        if not is_browser_cmd(proc['cmdline']):
            continue
        openclaw_browsers.append(proc)

    total_openclaw_browsers = len(openclaw_browsers)

    zombies = []
    for proc in openclaw_browsers:
        orphan = (proc['ppid'] == 1) or ('systemd --user' in (proc['parent_cmdline'] or ''))
        age_ok = proc['age_seconds'] >= min_age
        if orphan and age_ok:
            zombies.append(proc)

    zombie_count = len(zombies)
    sum_rss_kb = sum(p['rss_kb'] for p in zombies)
    zombie_memory_mb = sum_rss_kb // 1024

    # Build expected zombies list of dicts with exact fields
    expected_zombie_entries = []
    for z in zombies:
        expected_zombie_entries.append({
            'pid': z['pid'],
            'ppid': z['ppid'],
            'age_seconds': z['age_seconds'],
            'rss_kb': z['rss_kb'],
            'cmdline': z['cmdline'],
        })

    return {
        'total_openclaw_browsers': total_openclaw_browsers,
        'zombie_count': zombie_count,
        'zombie_memory_mb': zombie_memory_mb,
        'zombies': expected_zombie_entries,
    }

def load_report_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def read_kill_list(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.splitlines()
    return lines

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    processes_csv = os.path.join(input_dir, "processes.csv")
    policy_yaml = os.path.join(input_dir, "policy.yaml")
    report_json_path = os.path.join(output_dir, "report.json")
    kill_list_path = os.path.join(output_dir, "kill_list.txt")

    checks = {
        "report_exists": False,
        "kill_list_exists": False,
        "report_schema_valid": False,
        "report_values_correct": False,
        "kill_list_content_correct": False
    }

    # Load inputs for expected computation
    policy = parse_simple_yaml(policy_yaml)
    user = policy.get('user', '')
    pattern = policy.get('pattern', '')
    try:
        min_age = int(policy.get('min_age', 0))
    except Exception:
        min_age = 0

    # Read processes
    processes = []
    try:
        processes = read_processes_csv(processes_csv)
    except Exception:
        processes = []

    expected = compute_expected(processes, user, pattern, min_age)

    # Check presence of outputs
    if os.path.isfile(report_json_path):
        checks["report_exists"] = True
    if os.path.isfile(kill_list_path):
        checks["kill_list_exists"] = True

    # Parse and validate report.json schema
    report_obj = None
    if checks["report_exists"]:
        try:
            report_obj = load_report_json(report_json_path)
            if isinstance(report_obj, dict):
                required_keys = {"total_openclaw_browsers", "zombie_count", "zombie_memory_mb", "zombies"}
                obj_keys = set(report_obj.keys())
                # Enforce exact keys as per spec
                if obj_keys == required_keys:
                    # Type checks
                    if (
                        isinstance(report_obj.get("total_openclaw_browsers"), int)
                        and isinstance(report_obj.get("zombie_count"), int)
                        and isinstance(report_obj.get("zombie_memory_mb"), int)
                        and isinstance(report_obj.get("zombies"), list)
                    ):
                        # Validate each zombie entry has exactly required fields with correct types
                        per_item_ok = True
                        for item in report_obj["zombies"]:
                            if not isinstance(item, dict):
                                per_item_ok = False
                                break
                            item_keys = set(item.keys())
                            if item_keys != {"pid", "ppid", "age_seconds", "rss_kb", "cmdline"}:
                                per_item_ok = False
                                break
                            if not (
                                isinstance(item.get("pid"), int)
                                and isinstance(item.get("ppid"), int)
                                and isinstance(item.get("age_seconds"), int)
                                and isinstance(item.get("rss_kb"), int)
                                and isinstance(item.get("cmdline"), str)
                            ):
                                per_item_ok = False
                                break
                        if per_item_ok:
                            checks["report_schema_valid"] = True
        except Exception:
            checks["report_schema_valid"] = False

    # Validate report values against expected
    if checks["report_schema_valid"]:
        try:
            values_ok = True

            if report_obj["total_openclaw_browsers"] != expected["total_openclaw_browsers"]:
                values_ok = False
            if report_obj["zombie_count"] != expected["zombie_count"]:
                values_ok = False
            if report_obj["zombie_memory_mb"] != expected["zombie_memory_mb"]:
                values_ok = False
            # zombies length must equal zombie_count
            if len(report_obj["zombies"]) != report_obj["zombie_count"]:
                values_ok = False

            # Compare zombies content as a set of tuples for exact match
            def zombie_tuple_list(zlist):
                tuples = []
                for z in zlist:
                    tuples.append((z["pid"], z["ppid"], z["age_seconds"], z["rss_kb"], z["cmdline"]))
                return sorted(tuples)

            expected_tuples = zombie_tuple_list(expected["zombies"])
            reported_tuples = zombie_tuple_list(report_obj["zombies"])
            if expected_tuples != reported_tuples:
                values_ok = False

            checks["report_values_correct"] = bool(values_ok)
        except Exception:
            checks["report_values_correct"] = False

    # Validate kill_list.txt content
    if checks["kill_list_exists"]:
        try:
            lines = read_kill_list(kill_list_path)
            # No blank lines and no trailing spaces in any line
            no_blank_and_trimmed = all((ln != "" and ln == ln.strip()) for ln in lines) or (len(lines) == 0)
            # If expected zombies is zero, allow empty file (no lines)
            expected_pids = sorted([z["pid"] for z in expected["zombies"]])
            if len(expected_pids) == 0:
                # For zero expected, file may be empty; ensure no content or if content ensure matches empty list
                if len(lines) == 0:
                    checks["kill_list_content_correct"] = True
                else:
                    # If non-empty but zero expected, must be incorrect
                    checks["kill_list_content_correct"] = False
            else:
                # Must have same number of lines as expected pids
                if not no_blank_and_trimmed:
                    checks["kill_list_content_correct"] = False
                else:
                    if len(lines) != len(expected_pids):
                        checks["kill_list_content_correct"] = False
                    else:
                        # All lines must be digits only
                        digits_only = all(ln.isdigit() for ln in lines)
                        if not digits_only:
                            checks["kill_list_content_correct"] = False
                        else:
                            line_pids = [int(ln) for ln in lines]
                            # Must be strictly ascending sorted and equal to expected
                            if line_pids != sorted(line_pids):
                                checks["kill_list_content_correct"] = False
                            elif line_pids != expected_pids:
                                checks["kill_list_content_correct"] = False
                            else:
                                checks["kill_list_content_correct"] = True
        except Exception:
            checks["kill_list_content_correct"] = False

    # Determine reward
    # Gate: if any required artifact is missing, overall reward must be 0.0
    if not (checks["report_exists"] and checks["kill_list_exists"]):
        reward = 0.0
    else:
        # Weighted scoring
        weight = {
            "report_exists": 0.1,
            "kill_list_exists": 0.1,
            "report_schema_valid": 0.25,
            "report_values_correct": 0.35,
            "kill_list_content_correct": 0.2,
        }
        reward = 0.0
        for k, w in weight.items():
            reward += (w if checks.get(k, False) else 0.0)
        # If schema invalid, values cannot be correct; ensure consistency
        if not checks["report_schema_valid"]:
            checks["report_values_correct"] = False
        # Ensure reward bounded
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()