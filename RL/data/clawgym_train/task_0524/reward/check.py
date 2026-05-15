import json
import os
import sys
from typing import List, Dict, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def parse_yaml_front_matter(text: str) -> Tuple[bool, Dict[str, str], int]:
    """
    Returns (has_front_matter, fields, end_index)
    has_front_matter: True if starts with '---' and ends with next '---'
    fields: dict of simple key: value pairs parsed from lines with 'key: value'
    end_index: index of the line after closing '---', or 0 if not present
    """
    lines = text.splitlines()
    if not lines:
        return False, {}, 0
    if lines[0].strip() != "---":
        return False, {}, 0
    # find closing '---'
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i + 1
            break
    if end_idx is None:
        return False, {}, 0
    fields = {}
    for line in lines[1:end_idx-1]:
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip().lower()] = v.strip()
    return True, fields, end_idx

def find_headings(lines: List[str], expected_headings: List[str]) -> Tuple[bool, Dict[str, Tuple[int, int]]]:
    """
    Validate exact order of expected_headings and return section spans as a dict:
    {heading_text: (start_index_inclusive, end_index_exclusive)}
    Returns (order_ok, spans)
    """
    indices = []
    for h in expected_headings:
        try:
            idx = next(i for i, line in enumerate(lines) if line.strip() == h)
        except StopIteration:
            return False, {}
        indices.append(idx)
    # ensure strictly increasing
    if sorted(indices) != indices:
        return False, {}
    spans = {}
    for i, h in enumerate(expected_headings):
        start = indices[i] + 1
        end = indices[i+1] if i+1 < len(indices) else len(lines)
        spans[h] = (start, end)
    return True, spans

def count_blockquotes(section_lines: List[str]) -> int:
    cnt = 0
    for l in section_lines:
        if l.lstrip().startswith(">"):
            cnt += 1
    return cnt

def section_contains(section_lines: List[str], substr: str) -> bool:
    section_text = "\n".join(section_lines)
    return substr in section_text

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    manual_path = os.path.join(output_dir, "roi_field_manual.md")
    cheatsheet_path = os.path.join(output_dir, "roi_cheatsheet.txt")
    sources_path = os.path.join(output_dir, "appendix", "sources.json")

    # Initialize checks
    checks = {
        # Existence checks
        "manual_exists": False,
        "cheatsheet_exists": False,
        "sources_exists": False,

        # Manual front matter checks
        "manual_has_front_matter": False,
        "manual_front_matter_has_title_and_date": False,
        "manual_title_contains_phrase": False,

        # Manual headings and order
        "manual_headings_order_correct": False,

        # Blockquotes per section
        "section_intro_has_2_quotes": False,
        "section_quickstart_has_2_quotes": False,
        "section_patterns_has_2_quotes": False,
        "section_debugging_has_2_quotes": False,
        "section_performance_has_2_quotes": False,
        "section_security_has_2_quotes": False,
        "section_migration_has_2_quotes": False,
        "section_cheatsheet_has_2_quotes": False,

        # Required substrings in manual
        "manual_contains_intro_required": False,
        "manual_contains_quickstart_required": False,
        "manual_contains_patterns_required": False,
        "manual_contains_debugging_required": False,
        "manual_contains_performance_required": False,
        "manual_contains_security_required": False,
        "manual_contains_migration_required": False,
        "manual_contains_cheatsheet_workflows": False,

        # Checklist checks within sections
        "quickstart_has_checklist_and_steps": False,
        "migration_has_checklist_and_steps": False,

        # Cheatsheet content checks
        "cheatsheet_has_essential_commands": False,
        "cheatsheet_has_common_workflows": False,

        # Sources JSON checks
        "sources_valid_json": False,
        "sources_has_required_keys": False,
        "sources_commands_correct": False,
        "sources_quotes_counts_valid": False,
    }

    # Process manual
    if os.path.isfile(manual_path):
        checks["manual_exists"] = True
        manual_text = read_text(manual_path)
        lines = manual_text.splitlines()

        # YAML front matter
        has_fm, fm_fields, fm_end_idx = parse_yaml_front_matter(manual_text)
        checks["manual_has_front_matter"] = has_fm
        if has_fm:
            has_title = "title" in fm_fields and fm_fields["title"] != ""
            has_date = "date" in fm_fields and fm_fields["date"] != ""
            checks["manual_front_matter_has_title_and_date"] = has_title and has_date
            title_contains_phrase = False
            if has_title:
                title_contains_phrase = "Roi Field Manual" in fm_fields["title"]
            checks["manual_title_contains_phrase"] = title_contains_phrase

        # Headings and order
        expected_headings = [
            "# Intro",
            "# Quickstart",
            "# Patterns",
            "# Debugging",
            "# Performance",
            "# Security",
            "# Migration",
            "# Cheatsheet",
        ]
        order_ok, spans = find_headings(lines, expected_headings)
        checks["manual_headings_order_correct"] = order_ok

        # Per-section blockquotes and section-specific checks
        if order_ok:
            # Count blockquotes per section
            section_to_key = {
                "# Intro": "section_intro_has_2_quotes",
                "# Quickstart": "section_quickstart_has_2_quotes",
                "# Patterns": "section_patterns_has_2_quotes",
                "# Debugging": "section_debugging_has_2_quotes",
                "# Performance": "section_performance_has_2_quotes",
                "# Security": "section_security_has_2_quotes",
                "# Migration": "section_migration_has_2_quotes",
                "# Cheatsheet": "section_cheatsheet_has_2_quotes",
            }
            for h, key in section_to_key.items():
                start, end = spans[h]
                qcnt = count_blockquotes(lines[start:end])
                if qcnt >= 2:
                    checks[key] = True

            # Quickstart checklist: presence of "Checklist" and the steps
            q_start, q_end = spans["# Quickstart"]
            quick_lines = lines[q_start:q_end]
            quick_text = "\n".join(quick_lines)
            has_checklist_word = ("checklist" in quick_text.lower())
            quick_steps_ok = ("Install dependencies" in quick_text and "Verify installation" in quick_text)
            checks["quickstart_has_checklist_and_steps"] = has_checklist_word and quick_steps_ok

            # Migration checklist: presence of "Checklist" and two key steps
            m_start, m_end = spans["# Migration"]
            mig_lines = lines[m_start:m_end]
            mig_text = "\n".join(mig_lines)
            has_checklist_word_m = ("checklist" in mig_text.lower())
            mig_steps_ok = ("Prepare target environment" in mig_text and "Verify data integrity" in mig_text)
            checks["migration_has_checklist_and_steps"] = has_checklist_word_m and mig_steps_ok

        # Required substrings anywhere in the manual
        # Intro
        intro_req_1 = "Roi (roi) is a specialized tool/concept in the devtools domain."
        intro_req_2 = "Improving efficiency in devtools workflows"
        checks["manual_contains_intro_required"] = (intro_req_1 in manual_text and intro_req_2 in manual_text)

        # Quickstart
        q_req_1 = "Run the hello-world example"
        q_req_2 = "Explore available commands and options"
        checks["manual_contains_quickstart_required"] = (q_req_1 in manual_text and q_req_2 in manual_text)

        # Patterns
        p_req_1 = "Follow the principle of least privilege"
        p_req_2 = "Anti-Patterns to Avoid"
        checks["manual_contains_patterns_required"] = (p_req_1 in manual_text and p_req_2 in manual_text)

        # Debugging
        d_req = "Reproduce the issue consistently"
        checks["manual_contains_debugging_required"] = (d_req in manual_text)

        # Performance
        perf_req_1 = "Caching: Reduce redundant operations"
        perf_req_2 = "Parallel Processing: Utilize multiple cores"
        checks["manual_contains_performance_required"] = (perf_req_1 in manual_text and perf_req_2 in manual_text)

        # Security
        sec_req = "Encrypt data at rest and in transit"
        checks["manual_contains_security_required"] = (sec_req in manual_text)

        # Migration
        mig_req_1 = "Prepare target environment"
        mig_req_2 = "Switch traffic / go live"
        checks["manual_contains_migration_required"] = (mig_req_1 in manual_text and mig_req_2 in manual_text)

        # Cheatsheet workflows in the manual
        wf1 = "Setup: install → configure → verify → test"
        wf2 = "Daily: check → monitor → report → review"
        wf3 = "Issue: diagnose → isolate → fix → verify → document"
        checks["manual_contains_cheatsheet_workflows"] = (wf1 in manual_text and wf2 in manual_text and wf3 in manual_text)

    # Process cheatsheet
    if os.path.isfile(cheatsheet_path):
        checks["cheatsheet_exists"] = True
        cheat_text = read_text(cheatsheet_path)

        # Essential commands bullets
        e1 = "- help: Show available commands"
        e2 = "- version: Display version info"
        e3 = "- intro: Overview and fundamentals"
        e4 = "- troubleshooting: Common problems and fixes"
        essentials_ok = all(s in cheat_text for s in [e1, e2, e3, e4])
        checks["cheatsheet_has_essential_commands"] = essentials_ok

        # Common workflows lines
        wf1 = "Setup: install → configure → verify → test"
        wf2 = "Daily: check → monitor → report → review"
        wf3 = "Issue: diagnose → isolate → fix → verify → document"
        workflows_ok = all(s in cheat_text for s in [wf1, wf2, wf3])
        checks["cheatsheet_has_common_workflows"] = workflows_ok

    # Process sources.json
    if os.path.isfile(sources_path):
        checks["sources_exists"] = True
        try:
            with open(sources_path, "r", encoding="utf-8") as f:
                sources = json.load(f)
            checks["sources_valid_json"] = True
            required_keys = ["intro", "quickstart", "patterns", "debugging", "performance", "security", "migration", "cheatsheet"]
            has_keys = all(k in sources for k in required_keys)
            checks["sources_has_required_keys"] = has_keys
            commands_ok = True
            quotes_ok = True
            if has_keys:
                for k in required_keys:
                    v = sources.get(k)
                    if not isinstance(v, dict):
                        commands_ok = False
                        quotes_ok = False
                        break
                    # command must equal the topic string
                    if v.get("command") != k:
                        commands_ok = False
                    # quotes must be integer >= 2
                    q = v.get("quotes")
                    if not isinstance(q, int) or q < 2:
                        quotes_ok = False
            checks["sources_commands_correct"] = commands_ok
            checks["sources_quotes_counts_valid"] = quotes_ok
        except Exception:
            checks["sources_valid_json"] = False
            checks["sources_has_required_keys"] = False
            checks["sources_commands_correct"] = False
            checks["sources_quotes_counts_valid"] = False

    # Compute reward
    # No-op baseline: if any required artifact is missing, overall reward = 0.0
    required_files_exist = checks["manual_exists"] and checks["cheatsheet_exists"] and checks["sources_exists"]

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if required_files_exist and total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()