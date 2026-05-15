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

def is_ascii_no_spaces(name):
    try:
        name.encode("ascii")
    except Exception:
        return False
    return " " not in name

def find_section(text, start_heading, end_heading=None):
    # Return content between start_heading (line) and end_heading (line) or to end
    if text is None:
        return None
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == start_heading:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    if end_heading:
        for j in range(start_idx, len(lines)):
            if lines[j].strip() == end_heading:
                end_idx = j
                break
    return "\n".join(lines[start_idx:end_idx])

def strip_set_of_lines(block):
    # Return a set of non-empty stripped lines from block
    if block is None:
        return set()
    res = set()
    for line in block.splitlines():
        s = line.strip()
        if s != "":
            res.add(s)
    return res

def filename_matches_process_strict(name):
    # Strict pattern allowing 6 or 7 blocks (note block optional)
    # YYYYMMDD__process__title__vX.Y.Z__tags__source[__note].yaml
    if not name.endswith(".yaml"):
        return False
    if not is_ascii_no_spaces(name):
        return False
    base = os.path.basename(name)
    pat = re.compile(r'^(\d{8})__process__([a-z0-9\-]+)__v\d+\.\d+\.\d+__([a-z0-9\.\-]+)__([a-z0-9\.\-]+)(?:__([a-z0-9\.\-]+))?\.yaml$')
    m = pat.match(base)
    return m is not None

def filename_matches_snapshot(name):
    # YYYYMMDD-HHMMSS__snapshot__topic.jsonl
    if not name.endswith(".jsonl"):
        return False
    if not is_ascii_no_spaces(name):
        return False
    base = os.path.basename(name)
    pat = re.compile(r'^\d{8}-\d{6}__snapshot__([a-z0-9\.\-]+)\.jsonl$')
    return pat.match(base) is not None

def parse_yaml_like_for_keys(yaml_text):
    # Minimal YAML-like checks using line scanning (no external deps)
    result = {
        "has_process_id": False,
        "has_description": False,
        "stages_count_ok": False,
        "stages_have_fields": False,
        "has_checkpoint": False,
    }
    if not yaml_text:
        return result

    lines = yaml_text.splitlines()

    # process_id and description presence with non-empty value
    for ln in lines:
        if not result["has_process_id"]:
            m = re.match(r'^\s*process_id:\s*(.+)$', ln)
            if m and m.group(1).strip() != "":
                result["has_process_id"] = True
        if not result["has_description"]:
            m = re.match(r'^\s*description:\s*(.+)$', ln)
            if m and m.group(1).strip() != "":
                result["has_description"] = True
        if result["has_process_id"] and result["has_description"]:
            break

    # Count stages via occurrences of "- id:" under any "stages:" section
    # and check role, task, and inputs or outputs in the same item block
    indices_id = []
    for idx, ln in enumerate(lines):
        if re.match(r'^\s*-+\s*id:\s*.+', ln) or re.match(r'^\s*-\s+id:\s*.+', ln):
            indices_id.append(idx)

    # If no "- id:" from general scan, try scanning specifically after "stages:"
    # but usually the above is enough.
    stages_valid_blocks = 0
    for i, idx in enumerate(indices_id):
        # Determine block end (next '- ' at same or lesser indentation or end)
        cur_indent = len(lines[idx]) - len(lines[idx].lstrip(' '))
        next_idx = len(lines)
        for j in range(idx + 1, len(lines)):
            if lines[j].lstrip(' ').startswith('- '):
                # New list item; check indent
                indent_j = len(lines[j]) - len(lines[j].lstrip(' '))
                if indent_j == cur_indent:
                    next_idx = j
                    break
        block = "\n".join(lines[idx:next_idx])
        has_role = re.search(r'^\s*role:\s*.+', block, flags=re.MULTILINE) is not None
        has_task = re.search(r'^\s*task:\s*.+', block, flags=re.MULTILINE) is not None
        has_in_or_out = (re.search(r'^\s*inputs:\s*', block, flags=re.MULTILINE) is not None) or (re.search(r'^\s*outputs:\s*', block, flags=re.MULTILINE) is not None)
        if has_role and has_task and has_in_or_out:
            stages_valid_blocks += 1

    if len(indices_id) >= 3:
        result["stages_count_ok"] = True
    if stages_valid_blocks >= 3:
        result["stages_have_fields"] = True

    # Check checkpoints list has at least one item
    # Find 'checkpoints:' line and count subsequent list items
    checkpoints_idx = None
    for i, ln in enumerate(lines):
        if re.match(r'^\s*checkpoints:\s*$', ln):
            checkpoints_idx = i
            break
    if checkpoints_idx is not None:
        count_items = 0
        for j in range(checkpoints_idx + 1, len(lines)):
            s = lines[j]
            # Stop if next top-level key (no indent and ends with :)
            if re.match(r'^[A-Za-z0-9_]+\s*:\s*', s):
                break
            if re.match(r'^\s*-\s+\S+', s):
                count_items += 1
        if count_items >= 1:
            result["has_checkpoint"] = True

    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # Translation file checks
        "trans_file_exists": False,
        "trans_headings_present": False,
        "trans_original_contains_input_lines": False,
        "trans_translation_no_red_flags": False,
        "trans_translation_has_contraction": False,
        # Process YAML checks
        "process_file_exists": False,
        "process_filename_strict_pattern": False,
        "process_yaml_has_keys": False,
        "process_yaml_stages_count": False,
        "process_yaml_stages_have_fields": False,
        "process_yaml_has_checkpoint": False,
        "process_yaml_references_translation": False,
        # Audit JSONL checks
        "audit_file_exists": False,
        "audit_filename_snapshot_pattern": False,
        "audit_has_min_lines": False,
        "audit_all_lines_json": False,
        "audit_contains_required_events": False,
        "audit_events_allowed_only": False,
        # Cheatsheet checks
        "cheat_file_exists": False,
        "cheat_mentions_strict_pattern": False,
        "cheat_mentions_stable_template": False,
        "cheat_includes_all_filenames": False,
    }

    # Paths
    trans_rel = os.path.join("output", "lyric__beralio__galau-di-malam.md")
    process_rel = os.path.join("output", "20260419__process__lyric-translation__v1.0.0__lyrics.qa__workspace.yaml")
    audit_rel = os.path.join("output", "20260419-120000__snapshot__translation-audit.jsonl")
    cheat_rel = os.path.join("output", "doc__workspace__metadata-naming-cheatsheet.md")

    trans_path = os.path.join(workspace_root, trans_rel)
    process_path = os.path.join(workspace_root, process_rel)
    audit_path = os.path.join(workspace_root, audit_rel)
    cheat_path = os.path.join(workspace_root, cheat_rel)

    # 1) Translation checks
    trans_text = None
    if os.path.isfile(trans_path):
        checks["trans_file_exists"] = True
        trans_text = read_text(trans_path)

        # Headings presence exactly as specified (line exact match)
        if trans_text is not None:
            lines = [ln.strip() for ln in trans_text.splitlines()]
            if ("### Original (Indonesian)" in lines and
                "### Translation (English)" in lines and
                "### Notes" in lines):
                checks["trans_headings_present"] = True

        # Original section must include all non-empty lines from input/lyrics.md
        inp_path = os.path.join(input_dir, "lyrics.md")
        inp_text = read_text(inp_path)
        if inp_text is not None and trans_text is not None:
            orig_section = find_section(
                trans_text,
                "### Original (Indonesian)",
                "### Translation (English)"
            )
            original_line_set = strip_set_of_lines(orig_section)
            all_included = True
            for line in inp_text.splitlines():
                s = line.strip()
                if s == "":
                    continue
                if s not in original_line_set:
                    all_included = False
                    break
            if all_included and len(original_line_set) > 0:
                checks["trans_original_contains_input_lines"] = True

        # Translation section checks: no red-flag words; include at least one contraction
        if trans_text is not None:
            trans_section = find_section(
                trans_text,
                "### Translation (English)",
                "### Notes"
            )
            if trans_section is None:
                # If Notes missing, get till end
                trans_section = find_section(trans_text, "### Translation (English)", None)

            if trans_section is not None:
                lc = trans_section.lower()
                # Red-flag words check (word boundaries for singular forms)
                red_flags = ["tapestry", "symphony", "delve", "journey", "illuminating", "entirety", "radiant"]
                has_red = False
                for w in red_flags:
                    # word boundary for alphabetic words
                    if re.search(r'\b' + re.escape(w) + r'\b', lc):
                        has_red = True
                        break
                checks["trans_translation_no_red_flags"] = not has_red

                # Contraction presence (handle ASCII ' and curly ’)
                tnorm = trans_section.replace("’", "'")
                contractions = ["I'm", "don't", "can't", "won't", "you're"]
                has_contraction = False
                for c in contractions:
                    if c in tnorm or c.lower() in tnorm.lower():
                        has_contraction = True
                        break
                checks["trans_translation_has_contraction"] = has_contraction

    # 2) Process YAML checks
    process_text = None
    if os.path.isfile(process_path):
        checks["process_file_exists"] = True
        if filename_matches_process_strict(process_path):
            checks["process_filename_strict_pattern"] = True
        process_text = read_text(process_path)
        if process_text is not None:
            parsed = parse_yaml_like_for_keys(process_text)
            checks["process_yaml_has_keys"] = parsed["has_process_id"] and parsed["has_description"]
            checks["process_yaml_stages_count"] = parsed["stages_count_ok"]
            checks["process_yaml_stages_have_fields"] = parsed["stages_have_fields"]
            checks["process_yaml_has_checkpoint"] = parsed["has_checkpoint"]
            # Reference to translation artifact path
            if "output/lyric__beralio__galau-di-malam.md" in process_text:
                checks["process_yaml_references_translation"] = True

    # 3) Audit JSONL checks
    audit_lines = []
    if os.path.isfile(audit_path):
        checks["audit_file_exists"] = True
        if filename_matches_snapshot(audit_path):
            checks["audit_filename_snapshot_pattern"] = True

        text = read_text(audit_path)
        if text is not None:
            # Split into non-empty lines
            audit_lines = [ln for ln in text.splitlines() if ln.strip() != ""]
            if len(audit_lines) >= 6:
                checks["audit_has_min_lines"] = True
            # Validate each line JSON and event allowed
            allowed_events = {
                "process_started",
                "task_started",
                "task_completed",
                "checkpoint_waiting",
                "checkpoint_approved",
                "checkpoint_rejected",
                "process_completed",
            }
            all_json = True
            all_allowed = True
            has_started = False
            has_completed = False
            for ln in audit_lines:
                try:
                    obj = json.loads(ln)
                    ev = obj.get("event")
                    if ev == "process_started":
                        has_started = True
                    if ev == "process_completed":
                        has_completed = True
                    if ev not in allowed_events:
                        all_allowed = False
                except Exception:
                    all_json = False
                    all_allowed = False
                    break
            if all_json:
                checks["audit_all_lines_json"] = True
            if has_started and has_completed:
                checks["audit_contains_required_events"] = True
            if all_allowed:
                checks["audit_events_allowed_only"] = True

    # 4) Cheatsheet checks
    cheat_text = None
    if os.path.isfile(cheat_path):
        checks["cheat_file_exists"] = True
        cheat_text = read_text(cheat_path)
        if cheat_text is not None:
            if "YYYYMMDD[-HHMMSS]__prefix__title__version__tags__source__note.ext" in cheat_text:
                checks["cheat_mentions_strict_pattern"] = True
            if "<data_type>__<source_name>__<slug>.md" in cheat_text:
                checks["cheat_mentions_stable_template"] = True
            # Filenames present (accept with or without "output/" prefix)
            needed = [
                "lyric__beralio__galau-di-malam.md",
                "20260419__process__lyric-translation__v1.0.0__lyrics.qa__workspace.yaml",
                "20260419-120000__snapshot__translation-audit.jsonl",
            ]
            has_all = True
            for n in needed:
                if (n not in cheat_text) and (("output/" + n) not in cheat_text):
                    has_all = False
                    break
            checks["cheat_includes_all_filenames"] = has_all

    # Compute reward: fraction of passed checks among all checks, with no-op baseline
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if output dir missing or none of the artifact-dependent checks passed, reward 0.0
    if not os.path.isdir(output_dir) or passed == 0:
        reward = 0.0
    else:
        reward = passed / total

    # Print exactly one JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()