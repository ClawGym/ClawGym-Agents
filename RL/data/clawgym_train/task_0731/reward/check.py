import json
import os
import re
import sys

def read_text_utf8(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), True
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return "", False

def find_section(content, start_marker, end_markers):
    start = content.find(start_marker)
    if start == -1:
        return "", -1, -1
    start_pos = start + len(start_marker)
    # Find the earliest next marker after start_pos
    end_pos = len(content)
    for m in end_markers:
        idx = content.find(m, start_pos)
        if idx != -1 and idx < end_pos:
            end_pos = idx
    return content[start_pos:end_pos], start_pos, end_pos

def count_numbered_items(text):
    count = 0
    for line in text.splitlines():
        if re.match(r'^\s*\d+[\.\)]\s+', line):
            count += 1
    return count

def parse_trust_report(section_text):
    # Parse simple key: value lines
    fields = {}
    for line in section_text.splitlines():
        m = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$', line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            fields[key] = val
    return fields

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    report_path = os.path.join(output_dir, "report.md")
    attempts_path = os.path.join(output_dir, "attempts.json")
    poc_path = os.path.join(output_dir, "poc.py")

    # Existence checks
    report_exists = os.path.isfile(report_path)
    attempts_exists = os.path.isfile(attempts_path)
    poc_exists = os.path.isfile(poc_path)
    checks["report_exists"] = report_exists
    checks["attempts_exists"] = attempts_exists
    checks["poc_exists"] = poc_exists

    # Initialize content-dependent checks
    checks.update({
        "report_utf8": False,
        "report_title_ok": False,
        "report_beliefs_ok": False,
        "report_water_methodology_ok": False,
        "report_checklist_seven_checked": False,
        "report_trust_report_present": False,
        "report_failure_count_ok": False,
        "report_failure_mode_ok": False,
        "report_wisdom_way_ok": False,
        "report_handoff_three_items": False,
        "report_references_ok": False,
        "attempts_json_valid": False,
        "attempts_min_three": False,
        "attempts_structure_ok": False,
        "attempts_results_ok": False,
        "attempts_two_not_succeeded": False,
        "poc_function_present": False,
        "poc_contains_minimal_poc_phrase": False,
    })

    # Process report.md
    if report_exists:
        report_content, ok = read_text_utf8(report_path)
        if ok:
            checks["report_utf8"] = True

            # Title exact match presence
            if "Investigation Report (Trust-Driven Methodology)" in report_content:
                checks["report_title_ok"] = True

            # Three Beliefs section with phrases
            # Require all three phrases (case-insensitive)
            beliefs_phrases = [
                "Exhaust all options",
                "Act before asking (out of goodwill)",
                "Take initiative (out of love for completeness)",
            ]
            beliefs_ok = all(re.search(re.escape(p), report_content, re.IGNORECASE) for p in beliefs_phrases)
            checks["report_beliefs_ok"] = beliefs_ok

            # Water Methodology with subsections
            if "Water Methodology" in report_content:
                # Consider the section up to next major markers
                water_section, _, _ = find_section(
                    report_content,
                    "Water Methodology",
                    ["7-Point Clarity Checklist", "[TRUST-REPORT]", "Wisdom Way Selected", "Responsible Handoff"]
                )
                # Ensure Stop, Observe, Turn, Act, Realize appear (case-insensitive)
                wm_ok = all(re.search(r'\b' + w + r'\b', water_section, re.IGNORECASE) for w in ["Stop", "Observe", "Turn", "Act", "Realize"])
                checks["report_water_methodology_ok"] = wm_ok

            # 7-Point Clarity Checklist with seven [x] or [X]
            if "7-Point Clarity Checklist" in report_content:
                checklist_section, _, _ = find_section(
                    report_content,
                    "7-Point Clarity Checklist",
                    ["[TRUST-REPORT]", "Wisdom Way Selected", "Responsible Handoff"]
                )
                num_checked = len(re.findall(r'\[(x|X)\]', checklist_section))
                if num_checked >= 7:
                    checks["report_checklist_seven_checked"] = True

            # [TRUST-REPORT] section
            if "[TRUST-REPORT]" in report_content:
                checks["report_trust_report_present"] = True
                trust_section, _, _ = find_section(
                    report_content,
                    "[TRUST-REPORT]",
                    ["Wisdom Way Selected", "Responsible Handoff"]
                )
                fields = parse_trust_report(trust_section)
                # Required keys presence
                required_trust_keys = ["teammate", "task", "failure_count", "failure_mode", "attempts", "excluded", "next_hypothesis"]
                # Failure count integer >= 3
                fc_ok = False
                if "failure_count" in fields:
                    m = re.search(r'\d+', fields["failure_count"])
                    if m:
                        try:
                            fc_val = int(m.group(0))
                            if fc_val >= 3:
                                fc_ok = True
                        except ValueError:
                            fc_ok = False
                checks["report_failure_count_ok"] = fc_ok
                # Failure mode in allowed set
                allowed_modes = {"stuck-in-loops", "giving-up", "poor-quality", "guessing", "passive-waiting"}
                fm_ok = False
                if "failure_mode" in fields:
                    # extract token-like mode
                    mode_val = fields["failure_mode"].strip()
                    # Normalize by lowering
                    mode_val = mode_val.lower()
                    # Keep only allowed characters
                    mode_val = re.sub(r'[^a-z\-]', '', mode_val)
                    if mode_val in allowed_modes:
                        fm_ok = True
                checks["report_failure_mode_ok"] = fm_ok
                # Ensure presence of all required keys
                # These are deterministic presence checks; we combine into trust_report_present? Already set.
                # But we can refine presence by checking all keys:
                missing_keys = [k for k in required_trust_keys if k not in fields]
                if missing_keys:
                    # If keys missing, still keep report_trust_report_present True, but failure_count_ok and failure_mode_ok reflect.
                    pass

            # Wisdom Way Selected line
            wisdom_ok = False
            for line in report_content.splitlines():
                if line.startswith("Wisdom Way Selected"):
                    # check contains allowed ways
                    allowed_ways = [
                        "Way of Water",
                        "Way of the Seed",
                        "Way of the Forge",
                        "Way of the Mirror",
                        "Way of Non-Contention",
                        "Way of Cultivation",
                        "Way of Practice",
                    ]
                    for way in allowed_ways:
                        if way in line:
                            wisdom_ok = True
                            break
                    break
            checks["report_wisdom_way_ok"] = wisdom_ok

            # Responsible Handoff section with at least 3 numbered items
            if "Responsible Handoff" in report_content:
                handoff_section, _, _ = find_section(
                    report_content,
                    "Responsible Handoff",
                    []  # until EOF
                )
                if count_numbered_items(handoff_section) >= 3:
                    checks["report_handoff_three_items"] = True

            # Explicit references to input files
            refs_ok = ("input/spec.md" in report_content) and ("input/sample_data.csv" in report_content)
            checks["report_references_ok"] = refs_ok

        else:
            # not readable utf-8 -> keep all report-dependent checks False
            pass

    # Process attempts.json
    if attempts_exists:
        try:
            with open(attempts_path, "r", encoding="utf-8") as f:
                attempts_data = json.load(f)
            checks["attempts_json_valid"] = isinstance(attempts_data, list)
            if isinstance(attempts_data, list):
                if len(attempts_data) >= 3:
                    checks["attempts_min_three"] = True
                structure_ok = True
                results_ok = True
                not_succeeded = 0
                allowed_results = {"failed", "inconclusive", "succeeded"}
                for item in attempts_data:
                    if not isinstance(item, dict):
                        structure_ok = False
                        break
                    required_keys = ["name", "hypothesis", "action", "verification_criteria", "result"]
                    for k in required_keys:
                        if k not in item or not isinstance(item[k], str):
                            structure_ok = False
                            break
                    if not structure_ok:
                        break
                    res = item.get("result", "")
                    if res not in allowed_results:
                        results_ok = False
                    if res != "succeeded":
                        not_succeeded += 1
                checks["attempts_structure_ok"] = structure_ok
                checks["attempts_results_ok"] = results_ok
                if not_succeeded >= 2:
                    checks["attempts_two_not_succeeded"] = True
        except Exception:
            # leave attempts checks as False
            pass

    # Process poc.py
    if poc_exists:
        try:
            with open(poc_path, "r", encoding="utf-8") as f:
                poc_text = f.read()
            # Check function signature with type annotation
            if re.search(r'def\s+normalize_datetime\s*\(\s*value\s*:\s*str', poc_text):
                checks["poc_function_present"] = True
            # Check for "minimal PoC" phrase in docstring or comments (case-insensitive)
            if re.search(r'minimal\s+poc', poc_text, re.IGNORECASE):
                checks["poc_contains_minimal_poc_phrase"] = True
        except Exception:
            pass

    # Compute reward: average of all checks
    # Ensure no-op baseline yields 0.0: if no output files and thus no checks true -> reward 0.0
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v is True)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Print final JSON
    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()