import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().splitlines()
    except Exception:
        return []

def find_learnings_entries(content):
    # Returns list of (header_line, entry_text)
    lines = content.splitlines()
    entries = []
    header_re = re.compile(r'^## \[LRN-[0-9]{8}-[A-Za-z0-9]{3}\]\s+[a-z_]+$')
    indices = [i for i, ln in enumerate(lines) if header_re.match(ln)]
    for idx, start in enumerate(indices):
        end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        entry_lines = lines[start:end]
        entries.append(("\n".join(entry_lines[:1]), "\n".join(entry_lines)))
    return entries

def find_error_entries(content):
    lines = content.splitlines()
    entries = []
    header_re = re.compile(r'^## \[ERR-[0-9]{8}-[A-Za-z0-9]{3}\]\s+.*$')
    indices = [i for i, ln in enumerate(lines) if header_re.match(ln)]
    for idx, start in enumerate(indices):
        end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        entry = "\n".join(lines[start:end])
        entries.append(entry)
    return entries

def find_feature_entries(content):
    lines = content.splitlines()
    entries = []
    header_re = re.compile(r'^## \[FEAT-[0-9]{8}-[A-Za-z0-9]{3}\]\s+.*$')
    indices = [i for i, ln in enumerate(lines) if header_re.match(ln)]
    for idx, start in enumerate(indices):
        end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        entry = "\n".join(lines[start:end])
        entries.append(entry)
    return entries

def contains_word(text, word):
    return re.search(r'\b' + re.escape(word) + r'\b', text, flags=re.IGNORECASE) is not None

def parse_error_block(entry_text):
    # Look for ### Error followed by a fenced code block ```
    # We require at least one line between the fences
    if "### Error" not in entry_text:
        return False
    # Find first fenced block after "### Error"
    after = entry_text.split("### Error", 1)[1]
    fences = [m.start() for m in re.finditer(r"```", after)]
    if len(fences) >= 2:
        # Ensure there is content between
        start = after.find("```")
        if start != -1:
            rest = after[start+3:]
            end = rest.find("```")
            if end > 1:  # at least one char inside
                return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "report_three_blocks": False,

        "selection_exists": False,
        "selection_valid_json": False,
        "selection_two_selected": False,
        "selection_reasons_match": False,

        "todo_exists": False,
        "todo_five_checkboxes": False,
        "todo_has_risk_section": False,

        "sec_checklist_exists": False,
        "sec_has_exec": False,
        "sec_has_network": False,
        "sec_has_filesystem": False,
        "sec_has_sensitive": False,
        "sec_has_domains": False,

        "cortex_plan_exists": False,
        "cortex_has_install_and_uninstall_or_cleanup": False,
        "cortex_has_confirmation_or_approval": False,
        "cortex_has_read_only": False,
        "cortex_has_switch_or_fallback": False,

        "learnings_exists": False,
        "learnings_two_entries": False,
        "learnings_all_entries_have_fields": False,
        "learnings_all_entries_have_sections": False,
        "learnings_has_pattern_key": False,
        "learnings_has_promoted": False,

        "errors_exists": False,
        "errors_has_entry": False,
        "errors_has_error_block": False,
        "errors_has_suggested_fix": False,

        "features_exists": False,
        "features_has_entry": False,
        "features_has_requested_capability": False,
        "features_has_user_context": False,
        "features_has_suggested_implementation": False,

        "agents_exists": False,
        "agents_has_before_scan_bullet": False
    }

    # 1) contextualized_report.md
    report_path = os.path.join(output_dir, "trends", "contextualized_report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        lines = read_lines(report_path)
        triads = 0
        i = 0
        while i < len(lines) - 2:
            if lines[i].startswith("Repository: ") and lines[i+1].startswith("Facts: ") and lines[i+2].startswith("Contextual Value: "):
                triads += 1
                i += 3
            else:
                i += 1
        if triads >= 3:
            checks["report_three_blocks"] = True

    # 2) selection.json
    selection_path = os.path.join(output_dir, "trends", "selection.json")
    sel_data = None
    if os.path.isfile(selection_path):
        checks["selection_exists"] = True
        try:
            with open(selection_path, "r", encoding="utf-8", errors="ignore") as f:
                sel_data = json.load(f)
            checks["selection_valid_json"] = True
        except Exception:
            sel_data = None
        if isinstance(sel_data, dict):
            selected = sel_data.get("selected")
            reasons = sel_data.get("reasons")
            if isinstance(selected, list) and len(selected) == 2 and all(isinstance(x, str) for x in selected):
                checks["selection_two_selected"] = True
            if isinstance(reasons, dict) and isinstance(selected, list) and len(selected) == 2:
                keys_match = set(reasons.keys()) == set(selected)
                non_empty = all(isinstance(reasons.get(k), str) and reasons.get(k).strip() for k in selected)
                if keys_match and non_empty:
                    checks["selection_reasons_match"] = True

    # 3) todo.md
    todo_path = os.path.join(output_dir, "plans", "todo.md")
    if os.path.isfile(todo_path):
        checks["todo_exists"] = True
        tlines = read_lines(todo_path)
        count_check = sum(1 for ln in tlines if ln.startswith("- [ ] "))
        if count_check >= 5:
            checks["todo_five_checkboxes"] = True
        ttext = "\n".join(tlines)
        if re.search(r"risk", ttext, flags=re.IGNORECASE):
            checks["todo_has_risk_section"] = True

    # 4) security_scan_checklist.md
    sec_path = os.path.join(output_dir, "security", "security_scan_checklist.md")
    if os.path.isfile(sec_path):
        checks["sec_checklist_exists"] = True
        sec_text = read_text(sec_path)
        if contains_word(sec_text, "Exec"):
            checks["sec_has_exec"] = True
        if contains_word(sec_text, "Network"):
            checks["sec_has_network"] = True
        if contains_word(sec_text, "Filesystem"):
            checks["sec_has_filesystem"] = True
        if contains_word(sec_text, "Sensitive"):
            checks["sec_has_sensitive"] = True
        if contains_word(sec_text, "Domains"):
            checks["sec_has_domains"] = True

    # 5) cortex_plan.md
    cortex_path = os.path.join(output_dir, "agents", "cortex_plan.md")
    if os.path.isfile(cortex_path):
        checks["cortex_plan_exists"] = True
        ctx = read_text(cortex_path).lower()
        has_install = "install" in ctx
        has_uninstall_or_cleanup = ("uninstall" in ctx) or ("cleanup" in ctx)
        if has_install and has_uninstall_or_cleanup:
            checks["cortex_has_install_and_uninstall_or_cleanup"] = True
        if ("confirmation" in ctx) or ("approval" in ctx):
            checks["cortex_has_confirmation_or_approval"] = True
        if "read-only" in ctx:
            checks["cortex_has_read_only"] = True
        if ("switch" in ctx) or ("fallback" in ctx):
            checks["cortex_has_switch_or_fallback"] = True

    # 6) .learnings/LEARNINGS.md
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    if os.path.isfile(learnings_path):
        checks["learnings_exists"] = True
        Ltxt = read_text(learnings_path)
        entries = find_learnings_entries(Ltxt)
        if len(entries) >= 2:
            checks["learnings_two_entries"] = True

        # For all entries, required fields and sections
        all_fields = True
        all_sections = True
        has_pattern_key = False
        has_promoted = False

        for header, entry_text in entries:
            # Fields
            fields_ok = True
            for req in ["**Logged**:", "**Priority**:", "**Status**:", "**Area**:"]:
                # line starting with
                found = any(ln.strip().startswith(req) for ln in entry_text.splitlines())
                if not found:
                    fields_ok = False
                    break
            if not fields_ok:
                all_fields = False

            # Sections
            sections_ok = True
            for sec in ["### Summary", "### Details", "### Suggested Action", "### Metadata"]:
                found = any(ln.strip().startswith(sec) for ln in entry_text.splitlines())
                if not found:
                    sections_ok = False
                    break
            if not sections_ok:
                all_sections = False

            # Pattern-Key line
            if any(ln.strip().startswith("- Pattern-Key:") for ln in entry_text.splitlines()):
                has_pattern_key = True

            # Promoted (status promoted or resolution block indicating promotion)
            # Check status line
            status_lines = [ln for ln in entry_text.splitlines() if ln.strip().startswith("**Status**:")]
            if any("promoted" in ln.lower() for ln in status_lines):
                has_promoted = True
            else:
                # Check resolution block presence; accept any Resolution presence as promotion indicator per spec lenience
                if "### Resolution" in entry_text:
                    # Optionally require 'promot' keyword somewhere in entry to indicate promotion
                    if re.search(r'promot', entry_text, flags=re.IGNORECASE):
                        has_promoted = True
                    else:
                        # If cannot detect, still consider as promoted per relaxed interpretation
                        has_promoted = True

        if all_fields and len(entries) >= 1:
            checks["learnings_all_entries_have_fields"] = True
        if all_sections and len(entries) >= 1:
            checks["learnings_all_entries_have_sections"] = True
        if has_pattern_key:
            checks["learnings_has_pattern_key"] = True
        if has_promoted:
            checks["learnings_has_promoted"] = True

    # 7) .learnings/ERRORS.md
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    if os.path.isfile(errors_path):
        checks["errors_exists"] = True
        Etxt = read_text(errors_path)
        e_entries = find_error_entries(Etxt)
        if len(e_entries) >= 1:
            checks["errors_has_entry"] = True
        has_error_block = False
        has_suggested_fix = False
        for ent in e_entries:
            if parse_error_block(ent):
                has_error_block = True
            if "### Suggested Fix" in ent:
                has_suggested_fix = True
        if has_error_block:
            checks["errors_has_error_block"] = True
        if has_suggested_fix:
            checks["errors_has_suggested_fix"] = True

    # 8) .learnings/FEATURE_REQUESTS.md
    features_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    if os.path.isfile(features_path):
        checks["features_exists"] = True
        Ftxt = read_text(features_path)
        f_entries = find_feature_entries(Ftxt)
        if len(f_entries) >= 1:
            checks["features_has_entry"] = True
        req_cap = any("### Requested Capability" in ent for ent in f_entries)
        user_ctx = any("### User Context" in ent for ent in f_entries)
        sugg_impl = any("### Suggested Implementation" in ent for ent in f_entries)
        if req_cap:
            checks["features_has_requested_capability"] = True
        if user_ctx:
            checks["features_has_user_context"] = True
        if sugg_impl:
            checks["features_has_suggested_implementation"] = True

    # 9) output/AGENTS.md
    agents_path = os.path.join(output_dir, "AGENTS.md")
    if os.path.isfile(agents_path):
        checks["agents_exists"] = True
        Alines = read_lines(agents_path)
        ok_line = False
        for ln in Alines:
            if ln.startswith("- "):
                if re.search(r"before", ln, flags=re.IGNORECASE) and re.search(r"scan", ln, flags=re.IGNORECASE):
                    ok_line = True
                    break
        if ok_line:
            checks["agents_has_before_scan_bullet"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # Ensure no-op baseline: if output dir missing or empty, reward must be 0.0
    # We consider empty when no files exist under output
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        any_output = False
        for _root, _dirs, files in os.walk(output_dir):
            if files:
                any_output = True
                break
        if not any_output:
            reward = 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()