import json
import os
import sys
from datetime import datetime

def parse_iso8601(ts_str):
    if not isinstance(ts_str, str):
        return None
    s = ts_str.strip()
    if not s:
        return None
    # Handle Zulu suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def validate_snapshot(snap):
    required_fields = ["status", "cpu_pct", "ram_pct", "disk_pct", "timestamp"]
    for k in required_fields:
        if k not in snap:
            return False
    if snap["status"] not in {"ok", "warn", "critical"}:
        return False
    for k in ["cpu_pct", "ram_pct", "disk_pct"]:
        v = snap.get(k)
        if not isinstance(v, (int, float)):
            return False
        if v < 0 or v > 100:
            return False
    ts = parse_iso8601(snap.get("timestamp"))
    if ts is None:
        return False
    return True

def worst_status(statuses):
    order = {"ok": 0, "warn": 1, "critical": 2}
    worst = "ok"
    max_rank = -1
    for s in statuses:
        r = order.get(s, -1)
        if r > max_rank:
            max_rank = r
            worst = s
    return worst

def expected_thresholds():
    return {
        "cpu": {"warn": 70, "crit": 90},
        "ram": {"warn": 75, "crit": 90},
        "disk": {"warn": 80, "crit": 90},
        "temp": {"warn": 80, "crit": 95},
    }

def thresholds_equal(thr):
    exp = expected_thresholds()
    if not isinstance(thr, dict):
        return False
    # Compare structure and numeric values exactly
    for k in ["cpu", "ram", "disk", "temp"]:
        if k not in thr or not isinstance(thr[k], dict):
            return False
        for subk in ["warn", "crit"]:
            if subk not in thr[k]:
                return False
            val = thr[k][subk]
            exp_val = exp[k][subk]
            if not isinstance(val, (int, float)):
                return False
            if float(val) != float(exp_val):
                return False
    # Also ensure no missing keys; extra keys allowed but not required
    return True

def compute_gate_decision(statuses):
    if any(s == "critical" for s in statuses):
        return "abort"
    if all(s == "ok" for s in statuses):
        return "proceed"
    return "wait"

def find_section_indices(lines, headings):
    indices = {}
    for h in headings:
        idx = None
        for i, line in enumerate(lines):
            if line.strip() == h:
                idx = i
                break
        if idx is None:
            return None
        indices[h] = idx
    # Ensure order
    prev = -1
    for h in headings:
        if indices[h] <= prev:
            return None
        prev = indices[h]
    return indices

def count_bullets(lines, start_idx, end_idx):
    count = 0
    for i in range(start_idx + 1, end_idx):
        if lines[i].startswith("- "):
            count += 1
    return count

def count_nonempty_lines(lines, start_idx, end_idx):
    count = 0
    for i in range(start_idx + 1, end_idx):
        if lines[i].strip():
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    summary_path = os.path.join(output_dir, "preflight_summary.json")
    report_path = os.path.join(output_dir, "preflight_report.md")
    plan_path = os.path.join(input_dir, "training_plan.json")

    # Initialize checks to False
    checks["has_summary_json"] = False
    checks["summary_is_valid_json"] = False
    checks["summary_has_required_keys"] = False
    checks["summary_job_name_is_string"] = False
    checks["job_name_matches_input"] = False
    checks["summary_snapshots_len_3"] = False
    checks["snapshot_1_valid"] = False
    checks["snapshot_2_valid"] = False
    checks["snapshot_3_valid"] = False
    checks["summary_timestamps_strictly_increasing"] = False
    checks["thresholds_exact"] = False
    checks["aggregate_overall_correct"] = False
    checks["decision_mapping_correct"] = False
    checks["processes_top_cpu_len_at_least_5"] = False
    checks["processes_top_ram_len_at_least_5"] = False
    checks["processes_top_cpu_entries_valid"] = False
    checks["processes_top_ram_entries_valid"] = False

    checks["has_report_md"] = False
    checks["report_has_sections_in_order"] = False
    checks["report_top_cpu_bullets_count_at_least_5"] = False
    checks["report_top_ram_bullets_count_at_least_5"] = False
    checks["report_commands_list_at_least_3"] = False
    checks["report_includes_job_name"] = False
    checks["report_includes_gate_decision_consistent"] = False
    checks["cross_file_consistency"] = False

    # Load input training plan (reference)
    input_job_name = None
    plan = load_json_file(plan_path)
    if isinstance(plan, dict):
        # Try common keys
        if isinstance(plan.get("job_name"), str):
            input_job_name = plan.get("job_name")
        elif isinstance(plan.get("name"), str):
            input_job_name = plan.get("name")

    # Validate summary JSON
    summary = None
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        summary = load_json_file(summary_path)
        if isinstance(summary, dict):
            checks["summary_is_valid_json"] = True
            required_top_keys = {
                "job_name",
                "sampled_snapshots",
                "thresholds",
                "aggregate_overall",
                "gate_decision",
                "processes",
            }
            if required_top_keys.issubset(summary.keys()):
                checks["summary_has_required_keys"] = True

            # job_name type
            if isinstance(summary.get("job_name"), str):
                checks["summary_job_name_is_string"] = True
                # match with input job name if available
                if input_job_name and summary.get("job_name") == input_job_name:
                    checks["job_name_matches_input"] = True

            # sampled_snapshots
            snaps = summary.get("sampled_snapshots")
            if isinstance(snaps, list) and len(snaps) == 3:
                checks["summary_snapshots_len_3"] = True
                # Validate individual snapshots
                if validate_snapshot(snaps[0]):
                    checks["snapshot_1_valid"] = True
                if validate_snapshot(snaps[1]):
                    checks["snapshot_2_valid"] = True
                if validate_snapshot(snaps[2]):
                    checks["snapshot_3_valid"] = True

                # timestamps strictly increasing if all three valid
                if checks["snapshot_1_valid"] and checks["snapshot_2_valid"] and checks["snapshot_3_valid"]:
                    t0 = parse_iso8601(snaps[0]["timestamp"])
                    t1 = parse_iso8601(snaps[1]["timestamp"])
                    t2 = parse_iso8601(snaps[2]["timestamp"])
                    if t0 and t1 and t2 and (t0 < t1 < t2):
                        checks["summary_timestamps_strictly_increasing"] = True

                # thresholds exact
                if thresholds_equal(summary.get("thresholds")):
                    checks["thresholds_exact"] = True

                # aggregate_overall matches worst
                statuses = [s.get("status") for s in snaps]
                if all(isinstance(s, str) and s in {"ok", "warn", "critical"} for s in statuses):
                    expected_overall = worst_status(statuses)
                    if summary.get("aggregate_overall") == expected_overall:
                        checks["aggregate_overall_correct"] = True
                    # gate decision mapping
                    expected_decision = compute_gate_decision(statuses)
                    if summary.get("gate_decision") == expected_decision:
                        checks["decision_mapping_correct"] = True

            # processes structure
            processes = summary.get("processes")
            if isinstance(processes, dict):
                top_cpu = processes.get("top_cpu")
                top_ram = processes.get("top_ram")
                if isinstance(top_cpu, list) and len(top_cpu) >= 5:
                    checks["processes_top_cpu_len_at_least_5"] = True
                    valid_entries = True
                    for entry in top_cpu[:5]:
                        if not (isinstance(entry, dict)
                                and isinstance(entry.get("pid"), str)
                                and isinstance(entry.get("name"), str)
                                and isinstance(entry.get("cpu"), str)
                                and isinstance(entry.get("mem"), str)):
                            valid_entries = False
                            break
                    if valid_entries:
                        checks["processes_top_cpu_entries_valid"] = True
                if isinstance(top_ram, list) and len(top_ram) >= 5:
                    checks["processes_top_ram_len_at_least_5"] = True
                    valid_entries_r = True
                    for entry in top_ram[:5]:
                        if not (isinstance(entry, dict)
                                and isinstance(entry.get("pid"), str)
                                and isinstance(entry.get("name"), str)
                                and isinstance(entry.get("cpu"), str)
                                and isinstance(entry.get("mem"), str)):
                            valid_entries_r = False
                            break
                    if valid_entries_r:
                        checks["processes_top_ram_entries_valid"] = True

    # Validate markdown report
    report_text = ""
    report_lines = []
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
                report_lines = report_text.splitlines()
        except Exception:
            report_text = ""
            report_lines = []

        # headings in order
        headings = ["Overview", "Snapshots", "Top CPU processes", "Top RAM processes", "Commands Run", "Recommendations"]
        idx_map = find_section_indices(report_lines, headings)
        if idx_map is not None:
            checks["report_has_sections_in_order"] = True
            # bullets count in CPU section
            cpu_start = idx_map["Top CPU processes"]
            ram_start = idx_map["Top RAM processes"]
            cmd_start = idx_map["Commands Run"]
            rec_start = idx_map["Recommendations"]

            cpu_bullets = count_bullets(report_lines, cpu_start, ram_start)
            ram_bullets = count_bullets(report_lines, ram_start, cmd_start)
            cmds_count = count_nonempty_lines(report_lines, cmd_start, rec_start)

            if cpu_bullets >= 5:
                checks["report_top_cpu_bullets_count_at_least_5"] = True
            if ram_bullets >= 5:
                checks["report_top_ram_bullets_count_at_least_5"] = True
            if cmds_count >= 3:
                checks["report_commands_list_at_least_3"] = True

        # includes job_name and gate_decision
        if summary and isinstance(summary.get("job_name"), str):
            if summary["job_name"] in report_text:
                checks["report_includes_job_name"] = True
        if summary and isinstance(summary.get("gate_decision"), str):
            gate_dec = summary["gate_decision"]
            if gate_dec in {"proceed", "wait", "abort"} and gate_dec in report_text:
                checks["report_includes_gate_decision_consistent"] = True

        if checks["report_includes_job_name"] and checks["report_includes_gate_decision_consistent"]:
            checks["cross_file_consistency"] = True

    # Compute reward
    # If any required output file missing, reward must be 0.0
    required_outputs_exist = checks["has_summary_json"] and checks["has_report_md"]

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if required_outputs_exist:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0
    else:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()