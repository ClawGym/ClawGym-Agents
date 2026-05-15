import json
import os
import re
import sys

def contains_cjk(text):
    # Detect common CJK ranges (Chinese, Japanese, Korean)
    ranges = [
        (0x3040, 0x30FF),  # Hiragana, Katakana
        (0x31F0, 0x31FF),  # Katakana Phonetic Extensions
        (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
        (0x4E00, 0x9FFF),  # CJK Unified Ideographs
        (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
        (0xAC00, 0xD7AF),  # Hangul Syllables
        (0x1100, 0x11FF),  # Hangul Jamo
        (0x3130, 0x318F),  # Hangul Compatibility Jamo
        (0xFF66, 0xFF9D),  # Halfwidth Katakana
    ]
    for ch in text:
        code = ord(ch)
        for lo, hi in ranges:
            if lo <= code <= hi:
                return True
    return False

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_config_models_and_presets(config_text):
    # Crude YAML parser for top-level 'models:' and nested 'presets:'
    models = []
    presets = {}
    if config_text is None:
        return models, presets
    lines = config_text.splitlines()

    def strip_inline_comment(s):
        # remove inline comments starting with # preceded by space or at start
        if "#" in s:
            # find first unescaped '#' that starts a comment
            idx = s.find("#")
            if idx != -1:
                return s[:idx].rstrip()
        return s.rstrip()

    i = 0
    while i < len(lines):
        line = lines[i]
        raw = line
        line = line.rstrip("\n")
        # Skip empty or comment-only lines
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue

        # Top-level models
        m_models = re.match(r'^(\s*)models\s*:\s*$', line)
        if m_models:
            base_indent = len(m_models.group(1))
            i += 1
            while i < len(lines):
                l2 = lines[i]
                if not l2.strip() or l2.lstrip().startswith("#"):
                    i += 1
                    continue
                indent = len(l2) - len(l2.lstrip(' '))
                if indent <= base_indent and ":" in l2 and not l2.lstrip().startswith('-'):
                    break
                m_item = re.match(r'^\s*-\s*(.+?)\s*$', l2)
                if m_item:
                    item = strip_inline_comment(m_item.group(1)).strip()
                    if item:
                        models.append(item)
                i += 1
            continue

        # presets
        m_presets = re.match(r'^(\s*)presets\s*:\s*$', line)
        if m_presets:
            presets_indent = len(m_presets.group(1))
            i += 1
            current_preset = None
            current_preset_indent = None
            while i < len(lines):
                l2 = lines[i]
                if not l2.strip() or l2.lstrip().startswith("#"):
                    i += 1
                    continue
                indent2 = len(l2) - len(l2.lstrip(' '))
                if indent2 <= presets_indent and ":" in l2 and not l2.lstrip().startswith('-'):
                    # End presets block
                    break
                # Detect preset name:
                m_name = re.match(r'^(\s*)([A-Za-z0-9_\-]+)\s*:\s*$', l2)
                if m_name and len(m_name.group(1)) > presets_indent:
                    current_preset = m_name.group(2)
                    current_preset_indent = len(m_name.group(1))
                    if current_preset not in presets:
                        presets[current_preset] = []
                    i += 1
                    continue
                # Inside a preset list
                if current_preset is not None:
                    m_item = re.match(r'^\s*-\s*(.+?)\s*$', l2)
                    if m_item:
                        item = strip_inline_comment(m_item.group(1)).strip()
                        if item:
                            presets[current_preset].append(item)
                        i += 1
                        continue
                    else:
                        # If indentation shrinks to presets block or another sibling preset, continue loop to evaluate
                        i += 1
                        continue
                i += 1
            continue

        i += 1

    return models, presets

def first_non_empty_line(lines):
    for line in lines:
        if line.strip():
            return line.strip()
    return ""

def find_section(lines, header_text):
    # Find '## <header_text>' exact match (trimmed)
    header = f"## {header_text}"
    start_idx = None
    for idx, l in enumerate(lines):
        if l.strip() == header:
            start_idx = idx
            break
    if start_idx is None:
        return None, []
    # Find next '## ' header
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end_idx = j
            break
    # Return content lines between
    return start_idx, lines[start_idx+1:end_idx]

def count_bullets(lines):
    return sum(1 for l in lines if l.strip().startswith("- "))

def parse_participating_models(line_after_colon):
    # Parse "model-id (status)" entries separated by commas
    entries_text = line_after_colon.strip()
    # Split by comma
    parts = [p.strip() for p in entries_text.split(",") if p.strip()]
    mapping = {}
    pattern = re.compile(r'^(.+?)\s*\((success|failed|timed_out|degenerate)\)$')
    for part in parts:
        m = pattern.match(part)
        if not m:
            return None
        model_id = m.group(1).strip()
        status = m.group(2)
        if model_id in mapping:
            return None
        mapping[model_id] = status
    return mapping

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected paths
    out_base = os.path.join(output_dir, "ask_run")
    packed_path = os.path.join(out_base, "packed_question.md")
    models_path = os.path.join(out_base, "models.json")
    report_path = os.path.join(out_base, "report.md")
    config_path = os.path.join(input_dir, "config.yaml")

    checks = {
        "packed_exists": False,
        "packed_order": False,
        "packed_question_mark": False,
        "packed_english": False,

        "models_json_exists": False,
        "models_json_valid_structure": False,
        "models_mode_preset": False,
        "models_used_len_ge3": False,
        "models_used_in_config": False,
        "results_cover_models": False,
        "results_status_values_valid": False,
        "results_at_least_two_success": False,

        "report_exists": False,
        "report_english": False,
        "report_h1_firstline": False,
        "report_question_line": False,
        "report_consensus_bullet": False,
        "report_unique_insights_bullets": False,
        "report_conflicts_ok": False,
        "report_synthesis_best_judgment": False,
        "report_synthesis_uncertainty_labels_valid": False,
        "report_synthesis_information_gaps": False,
        "report_synthesis_next_steps_bullets": False,
        "report_participating_models_line_ok": False
    }

    # Load input config
    config_text = read_text(config_path)
    config_models, config_presets = parse_config_models_and_presets(config_text or "")
    allowed_models = set(config_models)
    for lst in config_presets.values():
        allowed_models.update(lst)

    # 1) packed_question.md
    if os.path.isfile(packed_path):
        checks["packed_exists"] = True
        packed_text = read_text(packed_path) or ""
        # English-only check
        checks["packed_english"] = not contains_cjk(packed_text)

        lines = packed_text.splitlines()
        # find indices of required headings in exact order
        idx_bg = idx_eq = idx_as = None
        for i, l in enumerate(lines):
            if l.startswith("Background:") and idx_bg is None:
                idx_bg = i
            elif l.startswith("Explicit question:") and idx_eq is None:
                idx_eq = i
            elif l.startswith("Assumptions:") and idx_as is None:
                idx_as = i
        if idx_bg is not None and idx_eq is not None and idx_as is not None and (idx_bg < idx_eq < idx_as):
            checks["packed_order"] = True
            # question mark check: the explicit question line must include a '?'
            eq_line = lines[idx_eq]
            if "?" in eq_line:
                checks["packed_question_mark"] = True
            else:
                # allow if any '?' appears later in the document after explicit question
                later_text = "\n".join(lines[idx_eq+1:]) if idx_eq+1 < len(lines) else ""
                if "?" in later_text:
                    checks["packed_question_mark"] = True

    # 2) models.json
    used_models = []
    results = []
    if os.path.isfile(models_path):
        checks["models_json_exists"] = True
        try:
            with open(models_path, "r", encoding="utf-8") as f:
                models_data = json.load(f)
            # Validate structure
            if (
                isinstance(models_data, dict) and
                "used_models" in models_data and
                "mode" in models_data and
                "preset" in models_data and
                "synthesis_model" in models_data and
                "results" in models_data and
                isinstance(models_data["used_models"], list) and
                isinstance(models_data["mode"], str) and
                isinstance(models_data["preset"], str) and
                isinstance(models_data["results"], list)
            ):
                # Ensure used_models are strings
                if all(isinstance(m, str) for m in models_data["used_models"]):
                    used_models = models_data["used_models"]
                    results = models_data["results"]
                    checks["models_json_valid_structure"] = True
            # Mode and preset
            if checks["models_json_valid_structure"]:
                if models_data.get("mode") == "normal" and models_data.get("preset") == "deep":
                    checks["models_mode_preset"] = True
                # used_models len >= 3
                if len(used_models) >= 3:
                    checks["models_used_len_ge3"] = True
                # used_models in config
                if used_models and allowed_models:
                    if all(m in allowed_models for m in used_models):
                        checks["models_used_in_config"] = True
                # results cover models and length >= used_models length
                if isinstance(results, list):
                    # Validate result items
                    valid_statuses = {"success", "failed", "timed_out", "degenerate"}
                    status_values_ok = True
                    result_models = []
                    for item in results:
                        if not isinstance(item, dict):
                            status_values_ok = False
                            break
                        m = item.get("model")
                        s = item.get("status")
                        if not isinstance(m, str) or s not in valid_statuses:
                            status_values_ok = False
                            break
                        result_models.append(m)
                    if status_values_ok:
                        checks["results_status_values_valid"] = True
                        covers_all = all(m in result_models for m in used_models)
                        if covers_all and len(results) >= len(used_models):
                            # Also ensure that each result model belongs to used_models (stricter, but safe)
                            if all(m in used_models for m in result_models):
                                checks["results_cover_models"] = True
                        # count success
                        success_count = sum(1 for item in results if item.get("status") == "success")
                        if success_count >= 2:
                            checks["results_at_least_two_success"] = True
        except Exception:
            pass

    # 3) report.md
    report_lines = []
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_text = read_text(report_path) or ""
        # English-only
        checks["report_english"] = not contains_cjk(report_text)
        report_lines = report_text.splitlines()
        # First non-empty line must be exactly "# Ask-More Consultation Report"
        first_line = first_non_empty_line(report_lines)
        if first_line == "# Ask-More Consultation Report":
            checks["report_h1_firstline"] = True
        # A line starting with "Question:" that contains a question mark
        q_line_ok = False
        for l in report_lines:
            lt = l.strip()
            if lt.startswith("Question:") and "?" in lt:
                q_line_ok = True
                break
        if q_line_ok:
            checks["report_question_line"] = True

        # Consensus section: at least 1 bullet
        _, consensus_section = find_section(report_lines, "Consensus")
        if consensus_section:
            if count_bullets(consensus_section) >= 1:
                checks["report_consensus_bullet"] = True

        # Unique Insights: at least 2 bullets "- [model-id]: ..." with ids in used_models and at least two different models
        _, ui_section = find_section(report_lines, "Unique Insights")
        if ui_section and used_models:
            bullet_ids = []
            for l in ui_section:
                if l.strip().startswith("- ["):
                    m = re.match(r'^\s*-\s*\[([^\]]+)\]\s*:\s+.+$', l.strip())
                    if m:
                        mid = m.group(1).strip()
                        bullet_ids.append(mid)
            # Filter those present in used_models
            matched = [mid for mid in bullet_ids if mid in used_models]
            if len(set(matched)) >= 2:
                checks["report_unique_insights_bullets"] = True

        # Conflicts section
        _, conflicts_section = find_section(report_lines, "Conflicts")
        if conflicts_section is not None:
            # If literal "None" anywhere in section, accept
            has_none = any(l.strip() == "None" for l in conflicts_section if l.strip())
            if has_none:
                checks["report_conflicts_ok"] = True
            else:
                # Else require at least one bullet with " vs " or "versus"
                ok = False
                for l in conflicts_section:
                    if l.strip().startswith("- "):
                        if " vs " in l or "versus" in l:
                            ok = True
                            break
                if ok:
                    checks["report_conflicts_ok"] = True

        # Synthesis section
        _, syn_section = find_section(report_lines, "Synthesis")
        if syn_section:
            # Best judgment line
            best_ok = False
            labels_ok = False
            gaps_ok = False
            next_steps_ok = False
            # Gather markers
            allowed_labels = {"High agreement", "Assumption-sensitive", "Weak evidence", "Value disagreement", "More info needed"}
            # We need to find 'Recommended next steps:' and count bullets after it within this section
            rns_index = None
            for idx, l in enumerate(syn_section):
                lt = l.strip()
                if lt.startswith("Best judgment:"):
                    rest = lt[len("Best judgment:"):].strip()
                    # At least 10 non-space characters
                    if len(rest.replace(" ", "")) >= 10:
                        best_ok = True
                elif lt.startswith("Uncertainty labels:"):
                    rest = lt[len("Uncertainty labels:"):].strip()
                    if rest:
                        parts = [p.strip() for p in rest.split(",") if p.strip()]
                        if parts and all(p in allowed_labels for p in parts):
                            labels_ok = True
                elif lt.startswith("Information gaps:"):
                    rest = lt[len("Information gaps:"):].strip()
                    if len(rest.replace(" ", "")) >= 10:
                        gaps_ok = True
                elif lt.strip() == "Recommended next steps:":
                    rns_index = idx
            if rns_index is not None:
                # Count bullets after this line until end of synthesis section
                bullets = 0
                for l in syn_section[rns_index+1:]:
                    if l.strip().startswith("- "):
                        bullets += 1
                if bullets >= 2:
                    next_steps_ok = True
            checks["report_synthesis_best_judgment"] = best_ok
            checks["report_synthesis_uncertainty_labels_valid"] = labels_ok
            checks["report_synthesis_information_gaps"] = gaps_ok
            checks["report_synthesis_next_steps_bullets"] = next_steps_ok

        # Participating models line
        # Must list every used model exactly once with matching status from models.json
        if used_models and results:
            results_map = {item.get("model"): item.get("status") for item in results if isinstance(item, dict)}
            part_line_ok = False
            for l in report_lines:
                lt = l.strip()
                if lt.startswith("Participating models:"):
                    after = lt[len("Participating models:"):].strip()
                    mapping = parse_participating_models(after)
                    if mapping is None:
                        continue
                    # Check exactly the used_models set, statuses match
                    if set(mapping.keys()) == set(used_models):
                        statuses_match = True
                        for m in used_models:
                            if mapping.get(m) != results_map.get(m):
                                statuses_match = False
                                break
                        if statuses_match:
                            part_line_ok = True
                    break
            if part_line_ok:
                checks["report_participating_models_line_ok"] = True

    # Compute reward
    required_files_exist = os.path.isfile(packed_path) and os.path.isfile(models_path) and os.path.isfile(report_path)
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_files_exist:
        reward = 0.0
    else:
        # Fraction of checks passed
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Output final JSON
    output = {"reward": round(reward, 6)}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()