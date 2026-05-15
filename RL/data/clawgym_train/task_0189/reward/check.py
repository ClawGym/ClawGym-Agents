import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_run_stats(log_text):
    # Extract statistics lines like:
    #   Mean:   0.123s
    #   Median: 0.123s
    #   Min:    0.123s
    #   Max:    0.123s
    #   StdDev: 0.123s
    # Allow arbitrary spaces; anchor on line starts
    stats = {}
    patterns = {
        "mean": r"(?m)^\s*Mean:\s*([0-9]*\.?[0-9]+)s",
        "median": r"(?m)^\s*Median:\s*([0-9]*\.?[0-9]+)s",
        "min": r"(?m)^\s*Min:\s*([0-9]*\.?[0-9]+)s",
        "max": r"(?m)^\s*Max:\s*([0-9]*\.?[0-9]+)s",
        "stddev": r"(?m)^\s*StdDev:\s*([0-9]*\.?[0-9]+)s",
    }
    for key, pat in patterns.items():
        m = re.search(pat, log_text)
        if not m:
            return None
        try:
            stats[key] = float(m.group(1))
        except ValueError:
            return None
    return stats

def parse_compare_avgs(log_text):
    # Lines look like:
    #   <label>: 0.123s avg (0.100-0.150)
    # We capture in order of appearance
    avg_re = re.compile(r"(?m)^\s*.+?:\s*([0-9]*\.?[0-9]+)s avg \(")
    vals = [float(m.group(1)) for m in avg_re.finditer(log_text)]
    return vals

def fmt3(x):
    try:
        return f"{float(x):.3f}"
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    run_fast_path = os.path.join(output_dir, "raw", "run_fast.txt")
    run_slow_path = os.path.join(output_dir, "raw", "run_slow.txt")
    compare_path = os.path.join(output_dir, "raw", "compare.txt")
    report_path = os.path.join(output_dir, "report.json")
    commands_path = os.path.join(input_dir, "commands.json")

    checks = {
        "has_run_fast_file": False,
        "has_run_slow_file": False,
        "has_compare_file": False,
        "has_report_file": False,
        "run_fast_required_strings": False,
        "run_slow_required_strings": False,
        "compare_contains_header": False,
        "compare_contains_commands": False,
        "compare_avg_lines_present": False,
        "report_schema_valid": False,
        "run_fast_stats_match_report": False,
        "run_slow_stats_match_report": False,
        "compare_avgs_match_report": False,
    }

    # Existence checks
    run_fast_txt = read_text(run_fast_path)
    run_slow_txt = read_text(run_slow_path)
    compare_txt = read_text(compare_path)
    report_json = load_json(report_path)
    commands_json = load_json(commands_path)

    if run_fast_txt is not None:
        checks["has_run_fast_file"] = True
    if run_slow_txt is not None:
        checks["has_run_slow_file"] = True
    if compare_txt is not None:
        checks["has_compare_file"] = True
    if report_json is not None:
        checks["has_report_file"] = True

    # Required substrings in run logs
    required_subs = ["Benchmarking: ", "Runs: 10", "Results:", "Mean:", "Median:", "Min:", "Max:", "StdDev:"]
    if run_fast_txt is not None:
        if all(sub in run_fast_txt for sub in required_subs):
            checks["run_fast_required_strings"] = True
    if run_slow_txt is not None:
        if all(sub in run_slow_txt for sub in required_subs):
            checks["run_slow_required_strings"] = True

    # Compare content checks
    fast_cmd = None
    slow_cmd = None
    if commands_json and isinstance(commands_json, dict):
        fast_cmd = commands_json.get("fast")
        slow_cmd = commands_json.get("slow")

    if compare_txt is not None:
        if "Comparison (5 runs each):" in compare_txt:
            checks["compare_contains_header"] = True
        # Must contain exact commands strings from commands.json
        if fast_cmd and slow_cmd and isinstance(fast_cmd, str) and isinstance(slow_cmd, str):
            if (fast_cmd in compare_txt) and (slow_cmd in compare_txt):
                contains_cmds = True
            else:
                contains_cmds = False
            checks["compare_contains_commands"] = contains_cmds
        # Ensure each command line includes pattern "s avg ("
        avg_matches = re.findall(r":\s*[0-9]*\.?[0-9]+s avg \(", compare_txt)
        if len(avg_matches) >= 2:
            checks["compare_avg_lines_present"] = True

    # Validate report schema
    def validate_report_schema(rep, fast_cmd, slow_cmd):
        if not isinstance(rep, dict):
            return False
        # tool
        if rep.get("tool") != "Benchmark Tool":
            return False
        # commands
        cmds = rep.get("commands")
        if not isinstance(cmds, dict):
            return False
        if cmds.get("fast") != fast_cmd or cmds.get("slow") != slow_cmd:
            return False
        # runs_used
        runs_used = rep.get("runs_used")
        if not isinstance(runs_used, dict):
            return False
        if runs_used.get("run") != 10 or runs_used.get("compare_each") != 5:
            return False
        # run stats presence and numeric
        run_stats = rep.get("run")
        if not isinstance(run_stats, dict):
            return False
        for label in ("fast", "slow"):
            rs = run_stats.get(label)
            if not isinstance(rs, dict):
                return False
            for k in ("mean", "median", "min", "max", "stddev"):
                v = rs.get(k)
                if not is_number(v):
                    return False
        # compare avgs numeric
        comp = rep.get("compare")
        if not isinstance(comp, dict):
            return False
        for k in ("fast_avg", "slow_avg"):
            if not is_number(comp.get(k)):
                return False
        return True

    if report_json is not None and fast_cmd is not None and slow_cmd is not None:
        if validate_report_schema(report_json, fast_cmd, slow_cmd):
            checks["report_schema_valid"] = True

    # Parse run stats from logs and compare with report
    fast_log_stats = None
    slow_log_stats = None
    if run_fast_txt is not None:
        fast_log_stats = parse_run_stats(run_fast_txt)
    if run_slow_txt is not None:
        slow_log_stats = parse_run_stats(run_slow_txt)

    # Compare run_fast stats
    if checks["report_schema_valid"] and fast_log_stats is not None:
        rep_fast = report_json.get("run", {}).get("fast", {})
        ok = True
        for k in ("mean", "median", "min", "max", "stddev"):
            lv = fast_log_stats.get(k)
            rv = rep_fast.get(k)
            if lv is None or rv is None:
                ok = False
                break
            if fmt3(lv) != fmt3(rv):
                ok = False
                break
        checks["run_fast_stats_match_report"] = ok

    # Compare run_slow stats
    if checks["report_schema_valid"] and slow_log_stats is not None:
        rep_slow = report_json.get("run", {}).get("slow", {})
        ok = True
        for k in ("mean", "median", "min", "max", "stddev"):
            lv = slow_log_stats.get(k)
            rv = rep_slow.get(k)
            if lv is None or rv is None:
                ok = False
                break
            if fmt3(lv) != fmt3(rv):
                ok = False
                break
        checks["run_slow_stats_match_report"] = ok

    # Parse compare averages and compare with report
    if checks["report_schema_valid"] and compare_txt is not None:
        avgs = parse_compare_avgs(compare_txt)
        if avgs and len(avgs) >= 2:
            fast_avg_log = avgs[0]
            slow_avg_log = avgs[1]
            rep_fast_avg = report_json.get("compare", {}).get("fast_avg")
            rep_slow_avg = report_json.get("compare", {}).get("slow_avg")
            if rep_fast_avg is not None and rep_slow_avg is not None:
                if fmt3(fast_avg_log) == fmt3(rep_fast_avg) and fmt3(slow_avg_log) == fmt3(rep_slow_avg):
                    checks["compare_avgs_match_report"] = True

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if no required artifacts exist, reward must be 0.0
    required_files_exist = checks["has_run_fast_file"] or checks["has_run_slow_file"] or checks["has_compare_file"] or checks["has_report_file"]
    if not required_files_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()