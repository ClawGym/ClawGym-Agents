import json
import os
import sys

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    items.append(obj)
                except Exception:
                    return None
        return items
    except Exception:
        return None

def domain_like(host):
    if not isinstance(host, str):
        return False
    h = host.strip()
    if "." not in h:
        return False
    for c in h:
        if c.isalpha():
            return True
    return False

def normalize_host(s):
    return s.strip().lower()

def get_required_headers_order():
    return [
        "Interfaces",
        "Listening Ports",
        "Bandwidth",
        "Latency Tests",
        "Traceroutes",
        "DNS Results",
        "WHOIS Summaries",
        "Speed Test",
        "Recommendations",
    ]

def find_headers_in_order(lines, headers):
    indices = []
    start = 0
    for h in headers:
        idx = -1
        for i in range(start, len(lines)):
            if h in lines[i]:
                idx = i
                break
        if idx == -1:
            return None
        indices.append(idx)
        start = idx + 1
    return indices

def ensure_latency_schema(latency_map, hosts_lower):
    if not isinstance(latency_map, dict):
        return False
    # allow case-insensitive keys by mapping lower-case
    lower_map = {k.lower(): v for k, v in latency_map.items()}
    for h in hosts_lower:
        if h not in lower_map:
            return False
        v = lower_map[h]
        if not isinstance(v, dict):
            return False
        if "attempted" not in v or "success" not in v or "avg_ms" not in v:
            return False
        if not isinstance(v["attempted"], bool):
            return False
        if not isinstance(v["success"], bool):
            return False
        if v["avg_ms"] is not None and not is_number(v["avg_ms"]):
            return False
    return True

def ensure_dns_schema(dns_map, hosts_lower):
    if not isinstance(dns_map, dict):
        return False
    lower_map = {k.lower(): v for k, v in dns_map.items()}
    for h in hosts_lower:
        if h not in lower_map:
            return False
        v = lower_map[h]
        if not isinstance(v, list):
            return False
    return True

def ensure_traceroute_schema(trace_map, hosts_lower):
    if not isinstance(trace_map, dict):
        return False
    lower_map = {k.lower(): v for k, v in trace_map.items()}
    for h in hosts_lower:
        if h not in lower_map:
            return False
        v = lower_map[h]
        if not isinstance(v, dict):
            return False
        for key in ("attempted", "success", "hop_count"):
            if key not in v:
                return False
        if not isinstance(v["attempted"], bool):
            return False
        if not isinstance(v["success"], bool):
            return False
        if v["hop_count"] is not None and not is_number(v["hop_count"]):
            return False
    return True

def ensure_whois_schema(whois_map, domain_hosts_lower):
    if whois_map is None or not isinstance(whois_map, dict):
        return False
    lower_map = {k.lower(): v for k, v in whois_map.items()}
    for h in domain_hosts_lower:
        if h not in lower_map:
            return False
        v = lower_map[h]
        if not isinstance(v, dict):
            return False
        for key in ("attempted", "success", "registrar"):
            if key not in v:
                return False
        if not isinstance(v["attempted"], bool):
            return False
        if not isinstance(v["success"], bool):
            return False
        if v["registrar"] is not None and not isinstance(v["registrar"], str):
            return False
    return True

def contains_any(s, keywords):
    s_low = s.lower()
    return any(k in s_low for k in keywords)

def commands_cover_categories(lines):
    # Must include at least one entry for these categories, via keywords in cmd
    cats = {
        "interfaces": ["status", "interfaces"],
        "ports": ["ports", "listening"],
        "bandwidth": ["bandwidth"],
        "speed": ["speed"],
    }
    found = {k: False for k in cats}
    for obj in lines:
        cmd = obj.get("cmd")
        if not isinstance(cmd, str):
            continue
        for k, kws in cats.items():
            if contains_any(cmd, kws):
                found[k] = True
    return all(found.values())

def commands_cover_hosts(lines, hosts):
    # For each host, require entries for latency/ping, trace/traceroute/tracepath, dns/lookup/resolve
    # For domain hosts, also require whois
    allowed_status = {"attempted", "success", "failed"}
    ok_for_all = True
    for host in hosts:
        low_host = host.lower()
        have_latency = False
        have_trace = False
        have_dns = False
        have_whois = True  # default True; only required for domains
        if domain_like(host):
            have_whois = False
        for obj in lines:
            cmd = obj.get("cmd")
            st = obj.get("status")
            if not isinstance(cmd, str) or st not in allowed_status:
                continue
            target = obj.get("target", None)
            # match if target equals host (case-insensitive) OR cmd contains host
            target_matches = isinstance(target, str) and target.lower() == low_host
            cmd_contains_host = low_host in cmd.lower()
            host_matched = target_matches or cmd_contains_host
            if not host_matched:
                continue
            if contains_any(cmd, ["latency", "ping"]):
                have_latency = True
            if contains_any(cmd, ["trace", "traceroute", "tracepath"]):
                have_trace = True
            if contains_any(cmd, ["dns", "lookup", "resolve"]):
                have_dns = True
            if domain_like(host) and contains_any(cmd, ["whois"]):
                have_whois = True
        if not (have_latency and have_trace and have_dns and have_whois):
            ok_for_all = False
            break
    return ok_for_all

def commands_jsonl_valid(lines):
    # Each line must be JSON with cmd (string), status in allowed; target may be present (string or None)
    allowed = {"attempted", "success", "failed"}
    if lines is None:
        return False
    if not isinstance(lines, list):
        return False
    if len(lines) == 0:
        # empty log cannot satisfy required categories anyway; mark invalid
        return False
    for obj in lines:
        if not isinstance(obj, dict):
            return False
        if "cmd" not in obj or "status" not in obj:
            return False
        if not isinstance(obj["cmd"], str):
            return False
        if obj["status"] not in allowed:
            return False
        if "target" in obj and obj["target"] is not None and not isinstance(obj["target"], str):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not used but kept for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "exists_network_report": False,
        "exists_metrics_json": False,
        "exists_commands_log": False,
        "commands_log_all_lines_json_and_status_valid": False,
        "report_sections_in_order": False,
        "report_has_content_line": False,
        "metrics_required_keys_present": False,
        "metrics_hosts_match_input": False,
        "metrics_latency_schema": False,
        "metrics_dns_schema": False,
        "metrics_traceroute_schema": False,
        "metrics_whois_schema": False,
        "metrics_interfaces_type": False,
        "metrics_bandwidth_type": False,
        "metrics_speed_test_schema": False,
        "commands_required_categories_present": False,
        "commands_per_host_entries_present": False,
    }

    # Load input hosts
    targets_path = os.path.join(input_dir, "targets.json")
    input_hosts = []
    if os.path.isfile(targets_path):
        try:
            data = read_json_file(targets_path)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        input_hosts.append(item.strip())
        except Exception:
            input_hosts = []
    input_hosts_lower = [normalize_host(h) for h in input_hosts]
    input_hosts_set_lower = set(input_hosts_lower)

    # Check existence of required output files
    report_path = os.path.join(output_dir, "network_report.md")
    metrics_path = os.path.join(output_dir, "metrics.json")
    commands_path = os.path.join(output_dir, "commands_run.jsonl")

    if os.path.isfile(report_path):
        checks["exists_network_report"] = True
    if os.path.isfile(metrics_path):
        checks["exists_metrics_json"] = True
    if os.path.isfile(commands_path):
        checks["exists_commands_log"] = True

    # Validate report structure
    if checks["exists_network_report"]:
        content = read_text_file(report_path)
        if content is not None and len(content.strip()) > 0:
            lines = content.splitlines()
            headers = get_required_headers_order()
            idxs = find_headers_in_order(lines, headers)
            if idxs is not None:
                checks["report_sections_in_order"] = True
                # Check at least one non-header line under any section
                has_content_under_any = False
                # Consider regions from each header to next header (or end)
                for si, start_idx in enumerate(idxs):
                    end_idx = idxs[si + 1] if si + 1 < len(idxs) else len(lines)
                    # any non-empty line between start_idx+1 and end_idx-1
                    for li in range(start_idx + 1, end_idx):
                        if lines[li].strip() != "":
                            has_content_under_any = True
                            break
                    if has_content_under_any:
                        break
                if has_content_under_any:
                    checks["report_has_content_line"] = True

    # Validate metrics.json
    metrics = None
    if checks["exists_metrics_json"]:
        metrics = read_json_file(metrics_path)
        if isinstance(metrics, dict):
            required_keys = ["tested_hosts", "timestamp", "interfaces", "latency", "dns", "traceroute", "whois", "bandwidth", "speed_test"]
            if all(k in metrics for k in required_keys):
                checks["metrics_required_keys_present"] = True

            # tested_hosts must match input hosts set (case-insensitive)
            tested_hosts = metrics.get("tested_hosts", [])
            if isinstance(tested_hosts, list):
                tested_hosts_lower = [normalize_host(h) for h in tested_hosts if isinstance(h, str)]
                if set(tested_hosts_lower) == input_hosts_set_lower and len(tested_hosts_lower) == len(input_hosts_set_lower):
                    checks["metrics_hosts_match_input"] = True

            # interfaces array
            if isinstance(metrics.get("interfaces"), list):
                checks["metrics_interfaces_type"] = True

            # bandwidth object
            if isinstance(metrics.get("bandwidth"), dict):
                checks["metrics_bandwidth_type"] = True

            # latency schema
            if checks["metrics_hosts_match_input"]:
                if ensure_latency_schema(metrics.get("latency"), tested_hosts_lower):
                    checks["metrics_latency_schema"] = True
                # dns schema
                if ensure_dns_schema(metrics.get("dns"), tested_hosts_lower):
                    checks["metrics_dns_schema"] = True
                # traceroute schema
                if ensure_traceroute_schema(metrics.get("traceroute"), tested_hosts_lower):
                    checks["metrics_traceroute_schema"] = True
                # whois schema for domain hosts only
                domain_hosts_lower = [h for h in tested_hosts_lower if domain_like(h)]
                if ensure_whois_schema(metrics.get("whois"), domain_hosts_lower):
                    checks["metrics_whois_schema"] = True

            # speed_test object schema
            st = metrics.get("speed_test")
            if isinstance(st, dict) and "attempted" in st and "success" in st and "mbps" in st:
                if isinstance(st.get("attempted"), bool) and isinstance(st.get("success"), bool):
                    mbps_val = st.get("mbps")
                    if mbps_val is None or is_number(mbps_val):
                        checks["metrics_speed_test_schema"] = True

    # Validate commands_run.jsonl
    commands_lines = None
    if checks["exists_commands_log"]:
        commands_lines = parse_jsonl(commands_path)
        if commands_lines is not None and commands_jsonl_valid(commands_lines):
            checks["commands_log_all_lines_json_and_status_valid"] = True
            # Categories coverage
            if commands_cover_categories(commands_lines):
                checks["commands_required_categories_present"] = True
            # Per host entries
            # Use input_hosts for required coverage
            if input_hosts:
                if commands_cover_hosts(commands_lines, input_hosts):
                    checks["commands_per_host_entries_present"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # No-op baseline: if output dir missing or all three required files missing -> reward 0
    if not checks["exists_network_report"] and not checks["exists_metrics_json"] and not checks["exists_commands_log"]:
        reward = 0.0

    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()