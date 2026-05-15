import json
import os
import sys
import math

def parse_requirements_yaml(path):
    sample_count = None
    interval_ms = None
    thermal_throttle_temp_c = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                # very simple YAML key: value parser
                if ":" in s:
                    key, val = s.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    # remove quotes if any
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    if key == "sample_count":
                        try:
                            sample_count = int(val)
                        except:
                            pass
                    elif key == "interval_ms":
                        try:
                            interval_ms = int(val)
                        except:
                            pass
                    elif key == "thermal_throttle_temp_c":
                        try:
                            thermal_throttle_temp_c = float(val)
                        except:
                            pass
    except FileNotFoundError:
        pass
    return sample_count, interval_ms, thermal_throttle_temp_c

def is_number_like(x):
    if isinstance(x, bool):
        return False
    if isinstance(x, (int, float)):
        return math.isfinite(float(x))
    if isinstance(x, str):
        try:
            v = float(x.strip())
            return math.isfinite(v)
        except:
            return False
    return False

def to_float(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            v = float(x.strip())
            return v
        except:
            return None
    return None

def approx_equal(a, b, tol):
    return abs(a - b) <= tol

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def count_words(text):
    if not text:
        return 0
    return len(text.split())

def find_section_indices(lines, section_word):
    # returns list of indices where line contains section_word (case-insensitive)
    idxs = []
    sw = section_word.lower()
    for i, line in enumerate(lines):
        if sw in line.lower():
            idxs.append(i)
    return idxs

def count_bullets_after(lines, start_idx, stop_words):
    count = 0
    n = len(lines)
    stop_words_lower = [w.lower() for w in stop_words]
    for i in range(start_idx + 1, n):
        l = lines[i].strip()
        # stop if new section encountered
        ll = l.lower()
        if any(sw in ll for sw in stop_words_lower):
            break
        if l.startswith("-") or l.startswith("*"):
            count += 1
    return count

def validate_raw_sample(obj):
    # required structure and types
    # timestamp: string
    if "timestamp" not in obj or not isinstance(obj["timestamp"], str):
        return False
    # cpu_usage, gpu_usage numbers
    if "cpu_usage" not in obj or not is_number_like(obj["cpu_usage"]):
        return False
    if "gpu_usage" not in obj or not is_number_like(obj["gpu_usage"]):
        return False
    # memory object with Total, Used, Available numbers
    mem = obj.get("memory")
    if not isinstance(mem, dict):
        return False
    for k in ("Total", "Used", "Available"):
        if k not in mem or not is_number_like(mem[k]):
            return False
    # soc_metrics with CPUPower, GPUPower, TotalPower, SocTemp numbers
    sm = obj.get("soc_metrics")
    if not isinstance(sm, dict):
        return False
    for k in ("CPUPower", "GPUPower", "TotalPower", "SocTemp"):
        if k not in sm or not is_number_like(sm[k]):
            return False
    # thermal_state string
    if "thermal_state" not in obj or not isinstance(obj["thermal_state"], str):
        return False
    # system_info with Name string and CoreCount number
    si = obj.get("system_info")
    if not isinstance(si, dict):
        return False
    if "Name" not in si or not isinstance(si["Name"], str):
        return False
    if "CoreCount" not in si or not is_number_like(si["CoreCount"]):
        return False
    return True

def compute_stats(samples):
    cpu = []
    gpu = []
    mem_used_gb = []
    total_power = []
    thermal_states = []
    system_info = None
    for obj in samples:
        cpu_v = to_float(obj["cpu_usage"])
        gpu_v = to_float(obj["gpu_usage"])
        used_b = to_float(obj["memory"]["Used"])
        total_power_v = to_float(obj["soc_metrics"]["TotalPower"])
        thermal_states.append(obj["thermal_state"])
        if system_info is None:
            si = obj.get("system_info", {})
            # take first sample's system_info for reporting purposes
            system_info = {"Name": si.get("Name"), "CoreCount": to_float(si.get("CoreCount"))}
        if cpu_v is not None:
            cpu.append(cpu_v)
        if gpu_v is not None:
            gpu.append(gpu_v)
        if used_b is not None:
            mem_used_gb.append(used_b / 1073741824.0)
        if total_power_v is not None:
            total_power.append(total_power_v)
    def agg(arr):
        if not arr:
            return None, None, None
        return sum(arr)/len(arr), min(arr), max(arr)
    cpu_avg, cpu_min, cpu_max = agg(cpu)
    gpu_avg, gpu_min, gpu_max = agg(gpu)
    mem_avg, mem_min, mem_max = agg(mem_used_gb)
    tp_avg, tp_min, tp_max = agg(total_power)
    return {
        "cpu": {"avg": cpu_avg, "min": cpu_min, "max": cpu_max},
        "gpu": {"avg": gpu_avg, "min": gpu_min, "max": gpu_max},
        # mem_min not required by spec; mem_max required; include avg and max
        "mem": {"avg": mem_avg, "max": mem_max},
        "tp": {"avg": tp_avg, "max": tp_max},
        "thermal_states": sorted(list(set(thermal_states))),
        "system_info": system_info
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # initialize checks
    checks = {
        "has_raw_samples": False,
        "raw_samples_count_matches_requirements": False,
        "raw_samples_valid_structure": False,
        "summary_exists": False,
        "summary_fields_and_types_valid": False,
        "summary_params_match_requirements": False,
        "summary_stats_consistent": False,
        "summary_thermal_states_consistent": False,
        "report_exists": False,
        "report_min_length": False,
        "report_has_sections": False,
        "report_insights_bullets": False,
        "report_recommendations_bullets": False,
        "report_mentions_key_terms": False,
        "no_users_paths_in_outputs": False,
        "raw_count_matches_summary_sample_count": False,
        "thermal_throttling_discussed_if_exceeded": False
    }

    req_path = os.path.join(input_dir, "requirements.yaml")
    sample_count_req, interval_ms_req, thermal_throttle_temp_c = parse_requirements_yaml(req_path)

    # Paths
    raw_path = os.path.join(output_dir, "raw_samples.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")
    report_path = os.path.join(output_dir, "report.md")

    # Read and validate raw samples
    samples = []
    raw_lines = []
    if os.path.isfile(raw_path):
        checks["has_raw_samples"] = True
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        raw_lines.append(line.rstrip("\n"))
            # line count must match requirements
            if sample_count_req is not None and len(raw_lines) == sample_count_req:
                checks["raw_samples_count_matches_requirements"] = True
            # parse JSONL and validate each object
            all_valid = True
            for ln in raw_lines:
                try:
                    obj = json.loads(ln)
                    if not isinstance(obj, dict):
                        all_valid = False
                        break
                    if not validate_raw_sample(obj):
                        all_valid = False
                        break
                    samples.append(obj)
                except:
                    all_valid = False
                    break
            if all_valid and len(samples) == len(raw_lines) and len(samples) > 0:
                checks["raw_samples_valid_structure"] = True
        except:
            pass

    # Validate summary.json
    summary_obj = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_obj = json.load(f)
            # Check required fields and types
            def has_num(d, k):
                return isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)
            fields_ok = True
            # top-level params
            if not has_num(summary_obj, "sample_count"):
                fields_ok = False
            if not has_num(summary_obj, "interval_ms"):
                fields_ok = False
            # cpu_usage avg/min/max
            cu = summary_obj.get("cpu_usage")
            gu = summary_obj.get("gpu_usage")
            mug = summary_obj.get("memory_used_gb")
            tpw = summary_obj.get("total_power_w")
            if not isinstance(cu, dict) or not all(has_num(cu, k) for k in ("avg", "min", "max")):
                fields_ok = False
            if not isinstance(gu, dict) or not all(has_num(gu, k) for k in ("avg", "min", "max")):
                fields_ok = False
            if not isinstance(mug, dict) or not all(has_num(mug, k) for k in ("avg", "max")):
                fields_ok = False
            if not isinstance(tpw, dict) or not all(has_num(tpw, k) for k in ("avg", "max")):
                fields_ok = False
            # thermal_states array of strings
            ts = summary_obj.get("thermal_states")
            if not isinstance(ts, list) or not all(isinstance(x, str) for x in ts):
                fields_ok = False
            # system_info with Name string CoreCount number
            si = summary_obj.get("system_info")
            if not isinstance(si, dict) or not isinstance(si.get("Name"), str) or not has_num(si, "CoreCount"):
                fields_ok = False
            checks["summary_fields_and_types_valid"] = fields_ok

            # sample_count and interval_ms must match requirements
            if sample_count_req is not None and interval_ms_req is not None:
                if int(summary_obj.get("sample_count")) == int(sample_count_req) and int(summary_obj.get("interval_ms")) == int(interval_ms_req):
                    checks["summary_params_match_requirements"] = True

            # raw count must match summary sample_count
            if checks["has_raw_samples"] and summary_obj and isinstance(summary_obj.get("sample_count"), (int, float)):
                if int(summary_obj.get("sample_count")) == len(raw_lines) and len(raw_lines) > 0:
                    checks["raw_count_matches_summary_sample_count"] = True

            # recompute stats and compare with tolerances
            if checks["raw_samples_valid_structure"] and summary_obj:
                stats = compute_stats(samples)
                cu_chk = (stats["cpu"]["avg"] is not None and
                          approx_equal(stats["cpu"]["avg"], float(cu["avg"]), 0.2) and
                          approx_equal(stats["cpu"]["min"], float(cu["min"]), 0.2) and
                          approx_equal(stats["cpu"]["max"], float(cu["max"]), 0.2))
                gu_chk = (stats["gpu"]["avg"] is not None and
                          approx_equal(stats["gpu"]["avg"], float(gu["avg"]), 0.2) and
                          approx_equal(stats["gpu"]["min"], float(gu["min"]), 0.2) and
                          approx_equal(stats["gpu"]["max"], float(gu["max"]), 0.2))
                mug_chk = (stats["mem"]["avg"] is not None and
                           approx_equal(stats["mem"]["avg"], float(mug["avg"]), 0.1) and
                           approx_equal(stats["mem"]["max"], float(mug["max"]), 0.1))
                tpw_chk = (stats["tp"]["avg"] is not None and
                           approx_equal(stats["tp"]["avg"], float(tpw["avg"]), 0.2) and
                           approx_equal(stats["tp"]["max"], float(tpw["max"]), 0.2))
                if cu_chk and gu_chk and mug_chk and tpw_chk:
                    checks["summary_stats_consistent"] = True

                # thermal_states set equality
                try:
                    raw_set = set(stats["thermal_states"])
                    sum_set = set(summary_obj.get("thermal_states", []))
                    if raw_set == sum_set:
                        checks["summary_thermal_states_consistent"] = True
                except:
                    pass

        except:
            pass

    # Validate report.md
    report_text = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_text = read_text(report_path)
        if report_text is not None:
            # min 150 words
            if count_words(report_text) >= 150:
                checks["report_min_length"] = True
            # has "Summary", "Insights", "Recommendations"
            has_sections = all(w.lower() in report_text.lower() for w in ["summary", "insights", "recommendations"])
            if has_sections:
                checks["report_has_sections"] = True
            # count bullets under Insights and Recommendations
            lines = report_text.splitlines()
            insight_idxs = find_section_indices(lines, "Insights")
            reco_idxs = find_section_indices(lines, "Recommendations")
            # choose first occurrence for each
            insight_bullets_ok = False
            reco_bullets_ok = False
            if insight_idxs:
                i_start = insight_idxs[0]
                insight_bullets = count_bullets_after(lines, i_start, stop_words=["Recommendations", "Summary", "Conclusion", "Analysis"])
                if insight_bullets >= 3:
                    insight_bullets_ok = True
            if reco_idxs:
                r_start = reco_idxs[0]
                reco_bullets = count_bullets_after(lines, r_start, stop_words=["Summary", "Insights", "Conclusion", "Analysis"])
                if reco_bullets >= 3:
                    reco_bullets_ok = True
            if insight_bullets_ok:
                checks["report_insights_bullets"] = True
            if reco_bullets_ok:
                checks["report_recommendations_bullets"] = True
            # mentions at least two of terms: CPU, GPU, power, thermal, temperature, RAM
            terms = ["cpu", "gpu", "power", "thermal", "temperature", "ram"]
            present = set()
            low = report_text.lower()
            for t in terms:
                if t in low:
                    present.add(t)
            if len(present) >= 2:
                checks["report_mentions_key_terms"] = True

    # No "/Users/" paths in any outputs (only check when all three outputs exist)
    if checks["has_raw_samples"] and checks["summary_exists"] and checks["report_exists"]:
        bad = False
        for p in (raw_path, summary_path, report_path):
            txt = read_text(p)
            if txt is not None and "/Users/" in txt:
                bad = True
                break
        if not bad:
            checks["no_users_paths_in_outputs"] = True

    # Thermal throttling discussion check: if any SocTemp exceeds threshold, ensure report mentions throttling
    exceeded = False
    mention_ok = False
    if thermal_throttle_temp_c is not None and checks["raw_samples_valid_structure"]:
        try:
            for obj in samples:
                st = to_float(obj["soc_metrics"]["SocTemp"])
                if st is not None and st > float(thermal_throttle_temp_c):
                    exceeded = True
                    break
        except:
            exceeded = False
    if exceeded:
        if report_text is not None and ("throttl" in report_text.lower() or "thermal throttling" in report_text.lower()):
            mention_ok = True
    else:
        # If not exceeded, this check is considered satisfied (no discussion required)
        mention_ok = True
    checks["thermal_throttling_discussed_if_exceeded"] = mention_ok

    # Compute reward as proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure baseline: if output directory missing or empty, reward must be 0.0
    if not os.path.isdir(output_dir) or (not os.path.isfile(raw_path) and not os.path.isfile(summary_path) and not os.path.isfile(report_path)):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()