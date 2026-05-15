import json
import os
import re
import sys

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def detect_int8_paradox(deploy_json, code_text):
    # From deployment.json
    q = None
    if isinstance(deploy_json, dict):
        q = deploy_json.get("quantization")
        if isinstance(q, str):
            q = q.strip().lower()
    # From code: load_in_8bit=True without llm_int8_threshold=0.0
    code_has_int8_default = False
    if code_text:
        if re.search(r"load_in_8bit\s*=\s*True", code_text):
            # Check if explicitly setting threshold to 0.0
            # Accept both with or without spaces around '=' and ':' variants
            if re.search(r"llm_int8_threshold\s*=\s*0\.0", code_text) or re.search(r"llm_int8_threshold\s*:\s*0\.0", code_text):
                code_has_int8_default = False
            else:
                code_has_int8_default = True
    dep_int8_default = q in {"int8_default", "int8-mixed", "int8_mixed"}
    return bool(dep_int8_default or code_has_int8_default)

def detect_batch_size_waste(deploy_json):
    if not isinstance(deploy_json, dict):
        return False
    bs = deploy_json.get("batch_size")
    try:
        if bs is None:
            return False
        bs_val = int(bs)
    except Exception:
        return False
    # Consider batch size 1 as waste for production-like deployments; we do not require additional traffic flags here
    return bs_val == 1

def first_nonempty_line(text):
    if not text:
        return None
    for line in text.splitlines():
        if line.strip():
            return line.rstrip("\n")
    return None

def has_ascii_chart_lines(report_text):
    if not report_text:
        return False
    lines = report_text.splitlines()
    # Required labels (start of line)
    required_labels = ["FP16:", "Pure INT8:", "NF4:", "INT8 default:", "FP8"]
    found = {label: False for label in required_labels}
    for line in lines:
        stripped = line.lstrip()
        for label in required_labels:
            # For FP8 line, allow optional colon after FP8 due to common formatting
            if label == "FP8":
                if stripped.startswith("FP8") and ("[" in stripped and "]" in stripped) and ("$" in stripped):
                    # Ensure it is at start and matches 'FP8' optionally followed by ':' or space
                    m = re.match(r"^FP8(:|\s)", stripped)
                    # If not matched by regex, still accept exact 'FP8:' or 'FP8 ' by manual check
                    if m or stripped.startswith("FP8:") or stripped.startswith("FP8 "):
                        found[label] = True
            else:
                if stripped.startswith(label) and ("[" in stripped and "]" in stripped) and ("$" in stripped):
                    found[label] = True
    return all(found.values())

def has_markdown_comparison_table(report_text):
    if not report_text:
        return False
    # Look for a header line that contains pipes and both Throughput and Energy (case-insensitive)
    for line in report_text.splitlines():
        if "|" in line and re.search(r"throughput", line, re.IGNORECASE) and re.search(r"energy", line, re.IGNORECASE):
            return True
    return False

def has_citations(report_text):
    if not report_text:
        return False
    must = "Data: 113+ measurements"
    doi = "doi:10.5281/zenodo"
    hf = "huggingface.co/datasets/hongpingzhang/ecocompute-energy-efficiency"
    return (must in report_text) and (doi in report_text or hf in report_text)

def check_fixes_prioritized(text):
    if not text:
        return False
    nums = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)[\).\s]", line)
        if m:
            try:
                nums.append(int(m.group(1)))
            except Exception:
                pass
    # Require at least items numbered 1 and 2 as "prioritized"
    return (1 in nums) and (2 in nums)

def has_batch_size_recommendation(text):
    if not text:
        return False
    # Look for "batch size" or "BS" followed by a concrete target number (common: 4, 8, 16, 32, 64)
    patterns = [
        r"(batch size|BS)[^0-9]{0,20}(4|8|16|32|64)\b",
        r"(increase batch size|set batch size|target batch size)[^0-9]{0,20}(4|8|16|32|64)\b",
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False

def has_int8_threshold_fix(text):
    if not text:
        return False
    # Accept direct parameter or BitsAndBytesConfig line
    if re.search(r"llm_int8_threshold\s*=\s*0\.0", text):
        return True
    if re.search(r"BitsAndBytesConfig\s*\(", text) and re.search(r"llm_int8_threshold\s*=\s*0\.0", text):
        return True
    return False

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Paths
    report_path = os.path.join(output_dir, "eco_audit_report.md")
    estimates_path = os.path.join(output_dir, "estimates.json")
    fixes_path = os.path.join(output_dir, "fixes.txt")

    # Load inputs to detect required alerts
    deployment_json = load_json(os.path.join(input_dir, "deployment.json"))
    current_code_text = load_text(os.path.join(input_dir, "current_code.md"))

    int8_required = detect_int8_paradox(deployment_json, current_code_text)
    bs_required = detect_batch_size_waste(deployment_json)

    # Initialize checks
    checks = {
        "report_exists": False,
        "report_mood_tag": False,
        "report_alert_int8_required_present": False,
        "report_alert_bs_required_present": False,
        "report_fix_threshold_mentioned": False,
        "report_ascii_chart_lines": False,
        "report_comparison_table": False,
        "report_cost_and_carbon_mentions": False,
        "report_citations": False,
        "estimates_exists": False,
        "estimates_parseable": False,
        "estimates_structure": False,
        "estimates_numeric_fields": False,
        "estimates_configs_present": False,
        "estimates_optimized_cheaper": False,
        "fixes_exists": False,
        "fixes_two_prioritized": False,
        "fixes_int8_threshold_fix": False,
        "fixes_batch_size_reco": False,
    }

    # Read outputs
    report_text = load_text(report_path)
    if report_text is not None and os.path.isfile(report_path):
        checks["report_exists"] = True
        # Mood tag at first non-empty line
        first_line = first_nonempty_line(report_text)
        if first_line:
            if any(first_line.startswith(tag) for tag in ["[Green]", "[Yellow]", "[Orange]", "[Red]", "[Gray]"]):
                checks["report_mood_tag"] = True
        # Alerts
        # INT8 alert required?
        if int8_required:
            if ("Alert: INT8 Energy Paradox" in report_text) or ("INT8 Energy Paradox Alert" in report_text):
                checks["report_alert_int8_required_present"] = True
        else:
            # Not required, count as passed by default
            checks["report_alert_int8_required_present"] = True
        # Batch size waste alert
        if bs_required:
            if ("Batch Size Waste" in report_text) or ("Batch Size Waste Alert" in report_text):
                checks["report_alert_bs_required_present"] = True
        else:
            checks["report_alert_bs_required_present"] = True
        # Fix mention for threshold
        if re.search(r"llm_int8_threshold\s*=\s*0\.0", report_text) or "BitsAndBytesConfig" in report_text:
            # Require explicit threshold=0.0 if BitsAndBytesConfig is present
            if re.search(r"llm_int8_threshold\s*=\s*0\.0", report_text):
                checks["report_fix_threshold_mentioned"] = True
        # ASCII chart lines with labels and $ and [ ]
        if has_ascii_chart_lines(report_text):
            checks["report_ascii_chart_lines"] = True
        # Markdown comparison table with Throughput and Energy
        if has_markdown_comparison_table(report_text):
            checks["report_comparison_table"] = True
        # Monthly cost and carbon units in-text
        if ("$" in report_text) and ("kgCO2" in report_text):
            checks["report_cost_and_carbon_mentions"] = True
        # Citations
        if has_citations(report_text):
            checks["report_citations"] = True

    # estimates.json checks
    estimates_obj = None
    if os.path.isfile(estimates_path):
        checks["estimates_exists"] = True
        estimates_obj = load_json(estimates_path)
        if isinstance(estimates_obj, dict):
            checks["estimates_parseable"] = True
            # Structure
            has_curr = isinstance(estimates_obj.get("current"), dict)
            has_opt = isinstance(estimates_obj.get("optimized"), dict)
            has_sav = isinstance(estimates_obj.get("savings"), dict)
            if has_curr and has_opt and has_sav:
                checks["estimates_structure"] = True
            # Numeric fields
            num_ok = False
            if has_curr and has_opt:
                cur = estimates_obj.get("current", {})
                opt = estimates_obj.get("optimized", {})
                cur_ok = all(is_number(cur.get(k)) for k in ("energy_kWh", "cost_usd", "carbon_kgCO2"))
                opt_ok = all(is_number(opt.get(k)) for k in ("energy_kWh", "cost_usd", "carbon_kgCO2"))
                if cur_ok and opt_ok:
                    num_ok = True
            if num_ok:
                checks["estimates_numeric_fields"] = True
            # Configs presence
            cfg_cur = estimates_obj.get("config_current")
            cfg_opt = estimates_obj.get("config_optimized")
            cfgs_ok = (
                isinstance(cfg_cur, dict)
                and isinstance(cfg_opt, dict)
                and ("quantization" in cfg_cur)
                and ("batch_size" in cfg_cur)
                and ("quantization" in cfg_opt)
                and ("batch_size" in cfg_opt)
            )
            if cfgs_ok:
                checks["estimates_configs_present"] = True
            # Optimized cheaper than current
            try:
                if num_ok:
                    if estimates_obj["optimized"]["cost_usd"] < estimates_obj["current"]["cost_usd"]:
                        checks["estimates_optimized_cheaper"] = True
            except Exception:
                pass

    # fixes.txt checks
    fixes_text = load_text(fixes_path)
    if fixes_text is not None and os.path.isfile(fixes_path):
        checks["fixes_exists"] = True
        if check_fixes_prioritized(fixes_text):
            checks["fixes_two_prioritized"] = True
        if has_int8_threshold_fix(fixes_text):
            checks["fixes_int8_threshold_fix"] = True
        if has_batch_size_recommendation(fixes_text):
            checks["fixes_batch_size_reco"] = True

    # Compute reward: average of booleans
    # Ensure no-op baseline yields 0.0 automatically since no files -> all False
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Clamp to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()