import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number_like(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v.strip())
            return True
        except Exception:
            return False
    return False

def contains_ascii_diagram_marker(content):
    if content is None:
        return False
    markers = ["┌", "└", "+---", "```"]
    return any(m in content for m in markers)

def count_bullet_points(content):
    if content is None:
        return 0
    count = 0
    for line in content.splitlines():
        s = line.lstrip()
        if s.startswith("-") or s.startswith("*"):
            count += 1
    return count

def has_keywords(content, keywords, min_count):
    if content is None:
        return False
    lc = content.lower()
    found = 0
    for kw in keywords:
        if kw.lower() in lc:
            found += 1
    return found >= min_count

def find_heading_indices(lines, heading_texts):
    """Return dict heading_text -> index for headings present. Heading match ignores leading # and spaces, case-insensitive."""
    indices = {}
    lower_targets = {h.lower(): h for h in heading_texts}
    for idx, line in enumerate(lines):
        normalized = line.strip()
        normalized = normalized.lstrip("#").strip().lower()
        if normalized in lower_targets and lower_targets[normalized] not in indices:
            indices[lower_targets[normalized]] = idx
    return indices

def section_has_content(lines, start_idx, end_idx):
    """Check for at least one non-empty content line between start_idx+1 and end_idx-1."""
    for i in range(start_idx + 1, end_idx):
        ln = lines[i].strip()
        if ln and not ln.startswith("#"):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    wal_path = os.path.join(output_dir, "governance", "WAL.jsonl")
    vbr_path = os.path.join(output_dir, "governance", "VBR_checks.json")
    adl_path = os.path.join(output_dir, "governance", "ADL_baseline.json")
    vfm_path = os.path.join(output_dir, "governance", "VFM_report.json")
    adr_path = os.path.join(output_dir, "architecture", "ADR-001.md")
    arch_path = os.path.join(output_dir, "architecture", "high_level_architecture.md")
    playbook_path = os.path.join(output_dir, "velocity", "10x_playbook.md")
    runbook_path = os.path.join(output_dir, "autonomy", "runbook.md")
    tools_path = os.path.join(output_dir, "memory", "TOOLS.md")

    checks = {
        "exists_WAL": False,
        "wal_min_entries": False,
        "wal_all_lines_parse": False,
        "wal_has_required_action_types": False,

        "exists_VBR": False,
        "vbr_has_checks_array": False,
        "vbr_len_at_least_3": False,
        "vbr_checks_schema_valid": False,
        "vbr_has_file_exists_adr001_and_present": False,
        "vbr_has_command_check": False,

        "exists_ADL_baseline": False,
        "adl_analysis_of_correct": False,
        "adl_numeric_fields_present": False,
        "adl_notes_nonempty": False,

        "exists_VFM_report": False,
        "vfm_entries_len_at_least_3": False,
        "vfm_entries_schema_valid": False,
        "vfm_aggregates_present": False,
        "vfm_suggestions_len_at_least_2": False,

        "exists_ADR_001": False,
        "adr_has_title": False,
        "adr_has_required_headings": False,

        "exists_high_level_arch": False,
        "arch_mentions_requirements": False,
        "arch_mentions_client_api_db": False,
        "arch_has_ascii_diagram_marker": False,

        "exists_10x_playbook": False,
        "playbook_min_bullets": False,
        "playbook_has_5_keywords": False,

        "exists_runbook": False,
        "runbook_sections_with_content": False,

        "exists_TOOLS_md": False,
        "tools_min_length": False,
        "tools_has_two_indicators": False,
        "tools_no_secret_markers": False,
    }

    # 1) Required files existence
    if os.path.isfile(wal_path):
        checks["exists_WAL"] = True

        # Validate WAL.jsonl
        try:
            with open(wal_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip() != ""]
            parsed = []
            all_parse_ok = True
            for ln in lines:
                try:
                    parsed.append(json.loads(ln))
                except Exception:
                    all_parse_ok = False
                    break
            if len(parsed) >= 3:
                checks["wal_min_entries"] = True
            # Schema per entry
            if all_parse_ok:
                checks["wal_all_lines_parse"] = True
                valid_types = {"decision", "analysis", "state_change", "correction"}
                types_present = set()
                schema_ok = True
                for e in parsed:
                    if not (isinstance(e.get("timestamp"), str) and isinstance(e.get("agent_id"), str)
                            and isinstance(e.get("action_type"), str) and isinstance(e.get("payload"), str)):
                        schema_ok = False
                        break
                    if e.get("action_type") not in valid_types:
                        schema_ok = False
                        break
                    types_present.add(e.get("action_type"))
                if schema_ok and {"decision", "analysis", "state_change"}.issubset(types_present):
                    checks["wal_has_required_action_types"] = True
        except Exception:
            pass

    if os.path.isfile(vbr_path):
        checks["exists_VBR"] = True
        vbr_obj = parse_json(vbr_path)
        if isinstance(vbr_obj, dict) and isinstance(vbr_obj.get("checks"), list):
            checks["vbr_has_checks_array"] = True
            checks_list = vbr_obj.get("checks", [])
            if len(checks_list) >= 3:
                checks["vbr_len_at_least_3"] = True
            # Validate schema
            allowed_types = {"file_exists", "file_changed", "command", "git_pushed"}
            schema_ok = True
            has_file_exists_adr = False
            has_command = False
            for c in checks_list:
                if not (isinstance(c, dict)
                        and isinstance(c.get("task_id"), str)
                        and isinstance(c.get("type"), str)
                        and isinstance(c.get("target"), str)
                        and c.get("type") in allowed_types):
                    schema_ok = False
                    break
                if c.get("type") == "command":
                    has_command = True
                if c.get("type") == "file_exists" and c.get("target") == "output/architecture/ADR-001.md":
                    # Validate file exists in output
                    if os.path.isfile(adr_path):
                        has_file_exists_adr = True
            if schema_ok:
                checks["vbr_checks_schema_valid"] = True
            if has_file_exists_adr:
                checks["vbr_has_file_exists_adr001_and_present"] = True
            if has_command:
                checks["vbr_has_command_check"] = True

    if os.path.isfile(adl_path):
        checks["exists_ADL_baseline"] = True
        adl_obj = parse_json(adl_path)
        if isinstance(adl_obj, dict):
            if adl_obj.get("analysis_of") == "input/sample_responses.jsonl":
                checks["adl_analysis_of_correct"] = True
            numeric_fields = [
                "anti_sycophancy",
                "anti_passivity",
                "anti_hedging",
                "anti_verbosity",
                "persona_direct",
                "persona_opinionated",
                "persona_action_oriented",
            ]
            nums_ok = True
            for k in numeric_fields:
                if k not in adl_obj or not is_number_like(adl_obj.get(k)):
                    nums_ok = False
                    break
            if nums_ok:
                checks["adl_numeric_fields_present"] = True
            if isinstance(adl_obj.get("notes"), str) and adl_obj.get("notes").strip():
                checks["adl_notes_nonempty"] = True

    if os.path.isfile(vfm_path):
        checks["exists_VFM_report"] = True
        vfm_obj = parse_json(vfm_path)
        if isinstance(vfm_obj, dict):
            entries = vfm_obj.get("entries")
            if isinstance(entries, list) and len(entries) >= 3:
                checks["vfm_entries_len_at_least_3"] = True
                schema_ok = True
                for e in entries:
                    if not (isinstance(e, dict)
                            and isinstance(e.get("task"), str)
                            and isinstance(e.get("model"), str)
                            and is_number_like(e.get("tokens"))
                            and is_number_like(e.get("cost_usd"))
                            and is_number_like(e.get("outcome_score"))
                            and is_number_like(e.get("vfm_score"))):
                        schema_ok = False
                        break
                if schema_ok:
                    checks["vfm_entries_schema_valid"] = True
            if is_number_like(vfm_obj.get("total_cost_usd")) and is_number_like(vfm_obj.get("avg_vfm")):
                checks["vfm_aggregates_present"] = True
            suggestions = vfm_obj.get("suggestions")
            if isinstance(suggestions, list) and len(suggestions) >= 2 and all(isinstance(s, str) for s in suggestions):
                checks["vfm_suggestions_len_at_least_2"] = True

    if os.path.isfile(adr_path):
        checks["exists_ADR_001"] = True
        adr_txt = read_text(adr_path) or ""
        # Title line beginning with '# ADR-001:'
        has_title = any(line.strip().startswith("# ADR-001:") for line in adr_txt.splitlines())
        if has_title:
            checks["adr_has_title"] = True
        req_heads = ["## Status", "## Context", "## Decision", "## Consequences", "## Alternatives", "## References"]
        if all(h in adr_txt for h in req_heads):
            checks["adr_has_required_headings"] = True

    if os.path.isfile(arch_path):
        checks["exists_high_level_arch"] = True
        arch_txt = read_text(arch_path) or ""
        # Requirements mention
        if re.search(r"requirements", arch_txt, flags=re.IGNORECASE):
            checks["arch_mentions_requirements"] = True
        # Mentions Client, API, Database
        if re.search(r"\bclient\b", arch_txt, re.IGNORECASE) and re.search(r"\bapi\b", arch_txt, re.IGNORECASE) and re.search(r"\bdatabase\b", arch_txt, re.IGNORECASE):
            checks["arch_mentions_client_api_db"] = True
        if contains_ascii_diagram_marker(arch_txt):
            checks["arch_has_ascii_diagram_marker"] = True

    if os.path.isfile(playbook_path):
        checks["exists_10x_playbook"] = True
        pb_txt = read_text(playbook_path) or ""
        if count_bullet_points(pb_txt) >= 8:
            checks["playbook_min_bullets"] = True
        keywords = [
            "trunk-based",
            "feature flags",
            "code generation",
            "vertical slicing",
            "CI/CD",
            "preview deployments",
            "test-driven development",
            "monorepo",
        ]
        if has_keywords(pb_txt, keywords, 5):
            checks["playbook_has_5_keywords"] = True

    if os.path.isfile(runbook_path):
        checks["exists_runbook"] = True
        rb_txt = read_text(runbook_path) or ""
        lines = rb_txt.splitlines()
        headings = ["Persistent Memory", "Identity", "Heartbeat"]
        idxs = find_heading_indices(lines, headings)
        all_present = all(h in idxs for h in headings)
        has_content = False
        if all_present:
            # Determine content ranges for each heading up to next heading
            # Build sorted indices of the three sections
            ordered = sorted([(idxs[h], h) for h in headings], key=lambda x: x[0])
            # Add end marker as len(lines)
            ranges = []
            for i in range(len(ordered)):
                start_idx = ordered[i][0]
                end_idx = ordered[i+1][0] if i+1 < len(ordered) else len(lines)
                ranges.append((ordered[i][1], start_idx, end_idx))
            # Check each has at least one non-empty line
            per_section_ok = []
            for _, s, e in ranges:
                per_section_ok.append(section_has_content(lines, s, e))
            has_content = all(per_section_ok)
        if all_present and has_content:
            checks["runbook_sections_with_content"] = True

    if os.path.isfile(tools_path):
        checks["exists_TOOLS_md"] = True
        tools_txt = read_text(tools_path) or ""
        if len(tools_txt.strip()) > 30:
            checks["tools_min_length"] = True
        # Indicators: 'port', 'service', 'network', 'IP', 'path', 'GPU'
        lc = tools_txt.lower()
        indicators = 0
        if re.search(r"\bport\b", lc):
            indicators += 1
        if re.search(r"\bservice\b", lc):
            indicators += 1
        if re.search(r"\bnetwork\b", lc):
            indicators += 1
        if re.search(r"\bip\b", tools_txt, flags=re.IGNORECASE):
            indicators += 1
        if re.search(r"\bpath\b", lc):
            indicators += 1
        if re.search(r"\bgpu\b", lc):
            indicators += 1
        if indicators >= 2:
            checks["tools_has_two_indicators"] = True
        # No secret markers
        if not (re.search(r"\bsecret\b", lc) or re.search(r"\btoken\b", lc) or re.search(r"\bpassword\b", lc)):
            checks["tools_no_secret_markers"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    # Ensure no-op baseline yields 0.0
    # If none of the existence checks are true, force reward = 0.0
    existence_keys = [
        "exists_WAL", "exists_VBR", "exists_ADL_baseline", "exists_VFM_report",
        "exists_ADR_001", "exists_high_level_arch", "exists_10x_playbook",
        "exists_runbook", "exists_TOOLS_md"
    ]
    if not any(checks[k] for k in existence_keys):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()