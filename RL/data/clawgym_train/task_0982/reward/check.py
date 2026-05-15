import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_bullets(lines):
    bullets = []
    bullet_re = re.compile(r'^\s*(?:[-*•]|\d+\.)\s+(.+)$')
    for ln in lines:
        m = bullet_re.match(ln)
        if m:
            bullets.append(m.group(1).strip())
    return bullets

def get_section_lines(lines, start_idx, stop_headers):
    section = []
    for i in range(start_idx + 1, len(lines)):
        ln = lines[i]
        # Stop when another header starts
        for sh in stop_headers:
            if ln.startswith(sh):
                return section
        section.append(ln)
    return section

def find_line_index(lines, prefix):
    for idx, ln in enumerate(lines):
        if ln.startswith(prefix):
            return idx
    return -1

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Existence checks
        "analysis_exists": False,
        "decision_log_exists": False,
        # Structural checks
        "has_purpose": False,
        "has_framework": False,
        "framework_valid": False,
        "has_first_impression": False,
        "has_whats_missing": False,
        "whats_missing_min3": False,
        "critical_section_present": False,
        "important_section_present": False,
        "counter_section_present": False,
        "action_section_present": False,
        "critical_bullet_count_ok": False,
        "important_bullet_count_ok": False,
        "critical_bullets_annotated": False,
        "important_bullets_annotated": False,
        "summary_present_and_len_ok": False,
        "cites_two_inputs": False,
        "action_nonempty": False,
        "decision_log_valid": False,
        "decision_counts_match": False,
        "recommendation_nonempty_json": False,
        # Rubric-like auxiliary checks (objective presence-based)
        "counter_has_item": False,
        "unknowns_look_like_questions": False,
        "has_from_input_tag": False,
        "has_inferred_tag": False,
    }

    # Paths
    analysis_path = os.path.join(output_dir, "analysis.md")
    decision_log_path = os.path.join(output_dir, "decision_log.json")

    # Read files if present
    analysis_text = None
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        analysis_text = read_text(analysis_path)

    decision_json = None
    if os.path.isfile(decision_log_path):
        checks["decision_log_exists"] = True
        try:
            with open(decision_log_path, "r", encoding="utf-8") as f:
                decision_json = json.load(f)
        except Exception:
            decision_json = None

    # If analysis exists, parse structural requirements
    critical_bullets = []
    important_bullets = []
    counter_bullets = []
    unknowns_bullets = []
    if analysis_text is not None:
        lines = analysis_text.splitlines()

        # Purpose line
        purpose_idx = find_line_index(lines, "🎯 PURPOSE:")
        if purpose_idx != -1:
            # Ensure it is on a single line with some content after colon
            purpose_line = lines[purpose_idx]
            # Accept any non-empty content after label
            parts = purpose_line.split("🎯 PURPOSE:", 1)
            if len(parts) == 2 and parts[1].strip():
                checks["has_purpose"] = True

        # Framework line
        framework_idx = find_line_index(lines, "Framework:")
        valid_frameworks = {"MECE", "Pros/Cons+", "Pre-mortem", "Steel man"}
        current_framework = None
        if framework_idx != -1:
            checks["has_framework"] = True
            m = re.match(r'^Framework:\s*(.+?)\s*$', lines[framework_idx])
            if m:
                val = m.group(1)
                if val in valid_frameworks:
                    checks["framework_valid"] = True
                    current_framework = val

        # First impression line
        if find_line_index(lines, "First impression:") != -1:
            checks["has_first_impression"] = True

        # What's missing section
        whats_missing_idx = find_line_index(lines, "What's missing:")
        header_prefixes = [
            "🎯 PURPOSE:", "Framework:", "First impression:", "What's missing:",
            "🔴 CRITICAL:", "🟡 IMPORTANT:", "⚠️ COUNTER:", "One-line summary:", "➡️ ACTION:"
        ]
        if whats_missing_idx != -1:
            checks["has_whats_missing"] = True
            whats_missing_lines = get_section_lines(lines, whats_missing_idx, header_prefixes)
            unknowns_bullets = parse_bullets(whats_missing_lines)
            if len(unknowns_bullets) >= 3:
                checks["whats_missing_min3"] = True
            # Rubric: unknown-looking items
            unknown_look_count = 0
            for b in unknowns_bullets:
                lb = b.strip().lower()
                if "?" in b or lb.startswith("we need") or lb.startswith("unknown"):
                    unknown_look_count += 1
            if unknown_look_count >= 1 and len(unknowns_bullets) >= 3:
                checks["unknowns_look_like_questions"] = True

        # Critical section
        critical_idx = find_line_index(lines, "🔴 CRITICAL:")
        if critical_idx != -1:
            checks["critical_section_present"] = True
            critical_lines = get_section_lines(lines, critical_idx, header_prefixes)
            critical_bullets = parse_bullets(critical_lines)
            if len(critical_bullets) in (1, 2):
                checks["critical_bullet_count_ok"] = True
            # All critical bullets annotated
            if critical_bullets:
                checks["critical_bullets_annotated"] = all(("[from input]" in b or "[inferred]" in b) for b in critical_bullets)

        # Important section
        important_idx = find_line_index(lines, "🟡 IMPORTANT:")
        if important_idx != -1:
            checks["important_section_present"] = True
            important_lines = get_section_lines(lines, important_idx, header_prefixes)
            important_bullets = parse_bullets(important_lines)
            if len(important_bullets) in (2, 3):
                checks["important_bullet_count_ok"] = True
            if important_bullets:
                checks["important_bullets_annotated"] = all(("[from input]" in b or "[inferred]" in b) for b in important_bullets)

        # Counter section
        counter_idx = find_line_index(lines, "⚠️ COUNTER:")
        if counter_idx != -1:
            checks["counter_section_present"] = True
            counter_lines = get_section_lines(lines, counter_idx, header_prefixes)
            counter_bullets = parse_bullets(counter_lines)
            if len(counter_bullets) >= 1:
                checks["counter_has_item"] = True

        # One-line summary
        summary_idx = find_line_index(lines, "One-line summary:")
        if summary_idx != -1:
            m = re.match(r'^One-line summary:\s*(.*)$', lines[summary_idx])
            if m:
                content = m.group(1).strip()
                if content and len(content) <= 150:
                    checks["summary_present_and_len_ok"] = True

        # Action section
        action_idx = find_line_index(lines, "➡️ ACTION:")
        if action_idx != -1:
            checks["action_section_present"] = True
            # Content can be on the same line or following lines until next header or end
            action_line = lines[action_idx]
            same_line_content = action_line.split("➡️ ACTION:", 1)[1].strip() if "➡️ ACTION:" in action_line else ""
            action_lines = get_section_lines(lines, action_idx, header_prefixes)
            any_following_content = any(ln.strip() for ln in action_lines)
            if same_line_content or any_following_content:
                checks["action_nonempty"] = True

        # Cites at least two distinct input basenames
        basenames = ["metrics.csv", "churn.csv", "customer_feedback.jsonl", "incident_report.md", "experiments.yaml"]
        present = set()
        lower_text = analysis_text.lower()
        for b in basenames:
            if b.lower() in lower_text:
                present.add(b)
        if len(present) >= 2:
            checks["cites_two_inputs"] = True

        # Rubric tags presence across CRITICAL/IMPORTANT
        all_bullets_ci = critical_bullets + important_bullets
        if any("[from input]" in b for b in all_bullets_ci):
            checks["has_from_input_tag"] = True
        if any("[inferred]" in b for b in all_bullets_ci):
            checks["has_inferred_tag"] = True

    # Decision log validation and cross-checks
    counted_num_critical = len(critical_bullets) if critical_bullets else 0
    counted_num_important = len(important_bullets) if important_bullets else 0
    if decision_json is not None and isinstance(decision_json, dict):
        # Validate keys and types
        expected_keys = {"framework", "num_critical", "num_important", "unknowns_count", "recommendation"}
        if all(k in decision_json for k in expected_keys):
            framework_val = decision_json.get("framework")
            num_critical_val = decision_json.get("num_critical")
            num_important_val = decision_json.get("num_important")
            unknowns_count_val = decision_json.get("unknowns_count")
            recommendation_val = decision_json.get("recommendation")
            framework_ok = framework_val in {"MECE", "Pros/Cons+", "Pre-mortem", "Steel man"}
            num_crit_ok = isinstance(num_critical_val, int) and num_critical_val in (1, 2)
            num_imp_ok = isinstance(num_important_val, int) and num_important_val in (2, 3)
            unknowns_ok = isinstance(unknowns_count_val, int) and unknowns_count_val >= 3
            recommendation_ok = isinstance(recommendation_val, str) and recommendation_val.strip() != ""
            if framework_ok and num_crit_ok and num_imp_ok and unknowns_ok and recommendation_ok:
                checks["decision_log_valid"] = True
            if recommendation_ok:
                checks["recommendation_nonempty_json"] = True
            # Cross-check counts with analysis.md parsed bullets
            if num_crit_ok and num_imp_ok:
                if num_critical_val == counted_num_critical and num_important_val == counted_num_important:
                    checks["decision_counts_match"] = True

    # Determine reward
    # Deterministic checks (must ideally all pass)
    deterministic_keys = [
        "analysis_exists",
        "decision_log_exists",
        "has_purpose",
        "has_framework",
        "framework_valid",
        "has_first_impression",
        "has_whats_missing",
        "whats_missing_min3",
        "critical_section_present",
        "important_section_present",
        "counter_section_present",
        "action_section_present",
        "critical_bullet_count_ok",
        "important_bullet_count_ok",
        "critical_bullets_annotated",
        "important_bullets_annotated",
        "summary_present_and_len_ok",
        "cites_two_inputs",
        "action_nonempty",
        "decision_log_valid",
        "decision_counts_match",
        "recommendation_nonempty_json",
    ]
    rubric_keys = [
        "counter_has_item",
        "unknowns_look_like_questions",
        "has_from_input_tag",
        "has_inferred_tag",
    ]

    d_total = len(deterministic_keys)
    r_total = len(rubric_keys)

    d_passes = sum(1 for k in deterministic_keys if checks.get(k, False))
    r_passes = sum(1 for k in rubric_keys if checks.get(k, False))

    # No-op baseline and missing required artifacts handling
    # If either required file is missing, give zero reward.
    if not (checks["analysis_exists"] and checks["decision_log_exists"]):
        reward = 0.0
    else:
        # Weighted score: deterministic dominates, rubric minor boost
        reward = 0.9 * (d_passes / d_total if d_total else 0.0) + 0.1 * (r_passes / r_total if r_total else 0.0)
        # Clamp between 0 and 1
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()