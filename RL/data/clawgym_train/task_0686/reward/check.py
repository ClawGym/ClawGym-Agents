import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_pct_number(val):
    if isinstance(val, (int, float)):
        return 0 <= val <= 100
    return False

def extract_numbers_from_value(v):
    nums = []
    if isinstance(v, (int, float)):
        nums.append(v)
    elif isinstance(v, str):
        for m in re.findall(r"\d+", v):
            try:
                nums.append(int(m))
            except Exception:
                pass
    elif isinstance(v, dict):
        for vv in v.values():
            nums.extend(extract_numbers_from_value(vv))
    elif isinstance(v, (list, tuple)):
        for vv in v:
            nums.extend(extract_numbers_from_value(vv))
    return nums

def thresholds_match(matrix):
    # Accept keys 'OK','ELEVATED','WARNING','CRITICAL' present and numbers containing boundary values
    if not isinstance(matrix, dict):
        return False
    required_keys = ["OK", "ELEVATED", "WARNING", "CRITICAL"]
    for k in required_keys:
        if k not in matrix:
            return False
    ok_nums = extract_numbers_from_value(matrix.get("OK"))
    elev_nums = extract_numbers_from_value(matrix.get("ELEVATED"))
    warn_nums = extract_numbers_from_value(matrix.get("WARNING"))
    crit_nums = extract_numbers_from_value(matrix.get("CRITICAL"))
    # Matching conditions (numeric boundary presence)
    cond_ok = 60 in ok_nums
    cond_elev = (60 in elev_nums) and (75 in elev_nums)
    cond_warn = (75 in warn_nums) and (90 in warn_nums)
    cond_crit = 90 in crit_nums
    return cond_ok and cond_elev and cond_warn and cond_crit

def disk_valid(disk_obj):
    if not isinstance(disk_obj, dict):
        return False
    if "pct" in disk_obj and is_pct_number(disk_obj["pct"]):
        return True
    # alternatively check used/total present
    has_used = "used" in disk_obj
    has_total = "total" in disk_obj
    return has_used and has_total

def contains_windows_drive(text):
    return re.search(r"[A-Za-z]:\\", text) is not None

def cleanup_checks(plan_path):
    checks = {
        "has_cleanup_plan": False,
        "cleanup_has_dry_run_section": False,
        "cleanup_has_aggressive_section": False,
        "cleanup_has_risk_language": False,
        "cleanup_has_do_not_spawn_sentence": False,
        "cleanup_mentions_npm_cache": False,
        "cleanup_mentions_journal_3days": False,
        "cleanup_mentions_avoid_pip_cache": False,
        "cleanup_no_absolute_paths": False,
        "cleanup_has_relative_paths": False,
    }
    if not os.path.isfile(plan_path):
        return checks
    checks["has_cleanup_plan"] = True
    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return checks
    lower = content.lower()

    # Required phrases/sections
    checks["cleanup_has_dry_run_section"] = "dry run plan" in lower
    checks["cleanup_has_aggressive_section"] = "aggressive cleanup" in lower
    checks["cleanup_has_risk_language"] = ("risk" in lower or "risks" in lower)

    # Exact sentence
    checks["cleanup_has_do_not_spawn_sentence"] = "Do not spawn new subagents." in content

    # npm cache mention
    checks["cleanup_mentions_npm_cache"] = "npm cache" in lower

    # journal logs older than 3 days
    checks["cleanup_mentions_journal_3days"] = (("journal" in lower or "journalctl" in lower) and ("3 days" in lower or "3d" in lower or "three days" in lower))

    # pip cache avoidance language
    avoid_phrases = [
        "avoid clearing pip",
        "avoid clearing the pip cache",
        "do not clear pip cache",
        "do not clear the pip cache",
    ]
    has_pip_cache = "pip cache" in lower
    has_avoid_lang = any(p in lower for p in avoid_phrases)
    checks["cleanup_mentions_avoid_pip_cache"] = has_pip_cache and has_avoid_lang

    # Absolute path checks
    no_abs_posix = True
    for line in content.splitlines():
        if line.strip().startswith("/"):
            no_abs_posix = False
            break
    no_abs_windows = not contains_windows_drive(content)
    checks["cleanup_no_absolute_paths"] = no_abs_posix and no_abs_windows

    # Relative workspace references
    checks["cleanup_has_relative_paths"] = ("input/" in content or "output/" in content)

    return checks

def diagnostics_checks(diag_path):
    checks = {
        "has_diagnostics_json": False,
        "diagnostics_parsed": False,
        "diagnostics_alert_valid": False,
        "diagnostics_ram_pct_valid": False,
        "diagnostics_swap_pct_valid": False,
        "diagnostics_cpu_pct_valid": False,
        "diagnostics_disk_valid": False,
        "diagnostics_top_procs_valid": False,
        "diagnostics_thresholds_present": False,
        "diagnostics_thresholds_match": False,
    }
    if not os.path.isfile(diag_path):
        return checks
    checks["has_diagnostics_json"] = True
    data = read_json(diag_path)
    if data is None or not isinstance(data, dict):
        return checks
    checks["diagnostics_parsed"] = True

    # alert value
    alert = data.get("alert")
    if isinstance(alert, str) and alert in {"OK", "ELEVATED", "WARNING", "CRITICAL"}:
        checks["diagnostics_alert_valid"] = True

    # ram pct
    ram = data.get("ram")
    if isinstance(ram, dict) and "pct" in ram and is_pct_number(ram["pct"]):
        checks["diagnostics_ram_pct_valid"] = True

    # swap pct
    swap = data.get("swap")
    if isinstance(swap, dict) and "pct" in swap and is_pct_number(swap["pct"]):
        checks["diagnostics_swap_pct_valid"] = True

    # cpu pct
    cpu = data.get("cpu")
    if isinstance(cpu, dict) and "pct" in cpu and is_pct_number(cpu["pct"]):
        checks["diagnostics_cpu_pct_valid"] = True

    # disk
    disk = data.get("disk")
    if isinstance(disk, dict) and disk_valid(disk):
        checks["diagnostics_disk_valid"] = True

    # top_procs string non-empty
    tp = data.get("top_procs")
    if isinstance(tp, str) and tp.strip() != "":
        checks["diagnostics_top_procs_valid"] = True

    # thresholds
    matrix = None
    if "thresholds" in data:
        matrix = data["thresholds"]
    elif "decision_matrix" in data:
        matrix = data["decision_matrix"]
    # Accept nested path as well if needed
    if matrix is not None:
        checks["diagnostics_thresholds_present"] = isinstance(matrix, dict)
        if checks["diagnostics_thresholds_present"]:
            checks["diagnostics_thresholds_match"] = thresholds_match(matrix)

    return checks

def config_checks(cfg_path):
    checks = {
        "has_recommended_config": False,
        "config_parsed": False,
        "config_model_is_lightweight": False,
        "config_thinking_off": False,
        "config_maxConcurrent_le_2": False,
        "config_heartbeat_interval_ge_1800000": False,
        "config_modes_subagent_run": False,
    }
    if not os.path.isfile(cfg_path):
        return checks
    checks["has_recommended_config"] = True
    data = read_json(cfg_path)
    if data is None or not isinstance(data, dict):
        return checks
    checks["config_parsed"] = True

    # agents.defaults.model
    model = None
    try:
        model = data["agents"]["defaults"]["model"]
    except Exception:
        model = None
    allowed_models = {"openrouter/hunter-alpha", "z-ai/glm-4.5-air", "nvidia/z-ai/glm4.7"}
    if isinstance(model, str) and model in allowed_models:
        checks["config_model_is_lightweight"] = True

    # agents.thinking == 'off'
    thinking = None
    try:
        thinking = data["agents"]["thinking"]
    except Exception:
        thinking = None
    if thinking == "off":
        checks["config_thinking_off"] = True

    # agents.subagents.maxConcurrent <= 2
    max_conc = None
    try:
        max_conc = data["agents"]["subagents"]["maxConcurrent"]
    except Exception:
        max_conc = None
    if isinstance(max_conc, (int, float)) and max_conc <= 2:
        checks["config_maxConcurrent_le_2"] = True

    # heartbeat.intervalMs >= 1800000
    hb_int = None
    try:
        hb_int = data["heartbeat"]["intervalMs"]
    except Exception:
        hb_int = None
    if isinstance(hb_int, (int, float)) and hb_int >= 1800000:
        checks["config_heartbeat_interval_ge_1800000"] = True

    # modes.subagent == 'run'
    sub_mode = None
    try:
        sub_mode = data["modes"]["subagent"]
    except Exception:
        sub_mode = None
    if sub_mode == "run":
        checks["config_modes_subagent_run"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    diag_path = os.path.join(output_dir, "diagnostics.json")
    plan_path = os.path.join(output_dir, "cleanup_plan.md")
    cfg_path = os.path.join(output_dir, "recommended_config.json")

    checks_diag = diagnostics_checks(diag_path)
    checks_plan = cleanup_checks(plan_path)
    checks_cfg = config_checks(cfg_path)

    # Aggregate all checks
    all_checks = {}
    all_checks.update(checks_diag)
    all_checks.update(checks_plan)
    all_checks.update(checks_cfg)

    # Compute reward: proportion of passed checks
    total = len(all_checks)
    passed = sum(1 for v in all_checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output dir missing or empty, reward must be 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        try:
            if len(os.listdir(output_dir)) == 0:
                reward = 0.0
        except Exception:
            reward = 0.0

    result = {"reward": reward}
    result.update(all_checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()