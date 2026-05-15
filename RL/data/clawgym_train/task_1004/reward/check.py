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

def first_nonempty_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""

def count_words(text):
    return len(re.findall(r"\b\w+\b", text))

def find_header_section(content, header_name):
    # Return the content of the section starting at a header that matches header_name (case-insensitive)
    # until the next header or end of content.
    if content is None:
        return None
    pattern = re.compile(rf"^\s{{0,3}}#{1,6}\s*{re.escape(header_name)}\s*$", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(content)
    if not m:
        return None
    start = m.end()
    # Find next header after start
    next_header = re.compile(r"^\s{0,3}#{1,6}\s+.+$", re.MULTILINE)
    m2 = next_header.search(content, pos=start)
    end = m2.start() if m2 else len(content)
    return content[start:end]

def header_exists(content, header_name):
    if content is None:
        return False
    pattern = re.compile(rf"^\s{{0,3}}#{1,6}\s*{re.escape(header_name)}\s*$", re.IGNORECASE | re.MULTILINE)
    return bool(pattern.search(content))

def has_string(content, s):
    if content is None:
        return False
    return s.lower() in content.lower()

def validate_top5_schema(arr):
    # Must be array of exactly 5 objects, each with required keys and types
    if not isinstance(arr, list):
        return (False, False, False)
    length_ok = (len(arr) == 5)
    schema_ok_overall = True
    for obj in arr:
        if not isinstance(obj, dict):
            schema_ok_overall = False
            break
        # Required keys
        req = ["title", "authors", "year", "citations", "doi"]
        if not all(k in obj for k in req):
            schema_ok_overall = False
            break
        if not isinstance(obj["title"], str):
            schema_ok_overall = False
            break
        if not isinstance(obj["authors"], list) or not all(isinstance(a, str) for a in obj["authors"]):
            schema_ok_overall = False
            break
        if not isinstance(obj["year"], int):
            schema_ok_overall = False
            break
        if not isinstance(obj["citations"], int):
            schema_ok_overall = False
            break
        if not (isinstance(obj["doi"], str) or obj["doi"] is None):
            schema_ok_overall = False
            break
    return (True, length_ok, schema_ok_overall)

def count_doi_indicators(text):
    if text is None:
        return 0
    c1 = len(re.findall(r"https?://doi\.org/", text, flags=re.IGNORECASE))
    c2 = len(re.findall(r"\bDOI\s*:", text, flags=re.IGNORECASE))
    return c1 + c2

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    lit_path = os.path.join(output_dir, "research", "literature_review.md")
    top5_path = os.path.join(output_dir, "research", "top5.json")
    gdb_summary_path = os.path.join(output_dir, "research", "gamedevbench_summary.txt")
    gtm_path = os.path.join(output_dir, "gtm", "gtm_plan.md")
    meeting_path = os.path.join(output_dir, "meeting-notes", "2026-04-18_project-sync.md")

    checks = {
        # Literature review
        "lit_exists": False,
        "lit_title_heading": False,
        "lit_has_overview": False,
        "lit_has_most_cited": False,
        "lit_has_thematic": False,
        "lit_has_bibliography": False,
        "lit_has_3plus_doi": False,
        # Top5 JSON
        "top5_exists": False,
        "top5_json_valid": False,
        "top5_array_len_5": False,
        "top5_schema_ok": False,
        # GameDevBench summary
        "gdb_summary_exists": False,
        "gdb_summary_mentions_name": False,
        "gdb_summary_wordcount_ok": False,
        # GTM plan
        "gtm_exists": False,
        "gtm_has_target_customer_profile": False,
        "gtm_has_positioning_statement": False,
        "gtm_has_competitive_landscape": False,
        "gtm_has_channel_strategy_matrix": False,
        "gtm_has_selected_channels": False,
        "gtm_has_pricing_or_packaging": False,
        "gtm_has_launch_timeline": False,
        "gtm_has_success_metrics": False,
        "gtm_has_kill_criteria": False,
        "gtm_kill_criteria_has_60_days": False,
        # Meeting notes
        "meeting_exists": False,
        "meeting_has_summary": False,
        "meeting_has_action_items": False,
        "meeting_has_checklist_item": False,
        "meeting_has_decisions": False,
        "meeting_has_raw_notes": False,
    }

    # Literature review checks
    if os.path.isfile(lit_path):
        checks["lit_exists"] = True
        lit = read_text(lit_path)
        if lit is not None:
            first_line = first_nonempty_line(lit)
            if first_line.startswith("# Literature Review:"):
                checks["lit_title_heading"] = True
            if "## Overview" in lit:
                checks["lit_has_overview"] = True
            if "### Most Cited Works" in lit:
                checks["lit_has_most_cited"] = True
            if "## Thematic Analysis" in lit:
                checks["lit_has_thematic"] = True
            if "## Full Bibliography" in lit:
                checks["lit_has_bibliography"] = True
            if count_doi_indicators(lit) >= 3:
                checks["lit_has_3plus_doi"] = True

    # Top5 JSON checks
    if os.path.isfile(top5_path):
        checks["top5_exists"] = True
        try:
            with open(top5_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["top5_json_valid"] = True
            valid_arr, length_ok, schema_ok = validate_top5_schema(data)
            if valid_arr:
                checks["top5_array_len_5"] = length_ok
                checks["top5_schema_ok"] = schema_ok
        except Exception:
            # leave as False
            pass

    # GameDevBench summary checks
    if os.path.isfile(gdb_summary_path):
        checks["gdb_summary_exists"] = True
        summary = read_text(gdb_summary_path)
        if summary is not None:
            if has_string(summary, "GameDevBench"):
                checks["gdb_summary_mentions_name"] = True
            wc = count_words(summary)
            if 80 <= wc <= 200:
                checks["gdb_summary_wordcount_ok"] = True

    # GTM plan checks
    if os.path.isfile(gtm_path):
        checks["gtm_exists"] = True
        gtm = read_text(gtm_path)
        if gtm is not None:
            if has_string(gtm, "Target Customer Profile"):
                checks["gtm_has_target_customer_profile"] = True
            if has_string(gtm, "Positioning Statement"):
                checks["gtm_has_positioning_statement"] = True
            if has_string(gtm, "Competitive Landscape"):
                checks["gtm_has_competitive_landscape"] = True
            if has_string(gtm, "Channel Strategy Matrix"):
                checks["gtm_has_channel_strategy_matrix"] = True
            if has_string(gtm, "Selected Channels"):
                checks["gtm_has_selected_channels"] = True
            # Pricing or Pricing & Packaging
            if has_string(gtm, "Pricing & Packaging") or has_string(gtm, "Pricing"):
                checks["gtm_has_pricing_or_packaging"] = True
            if has_string(gtm, "Launch Timeline"):
                checks["gtm_has_launch_timeline"] = True
            if has_string(gtm, "Success Metrics"):
                checks["gtm_has_success_metrics"] = True
            # Kill Criteria header and "60 days" in the section
            if header_exists(gtm, "Kill Criteria"):
                checks["gtm_has_kill_criteria"] = True
                kc = find_header_section(gtm, "Kill Criteria")
                if kc and "60 days" in kc.lower():
                    checks["gtm_kill_criteria_has_60_days"] = True

    # Meeting notes checks
    if os.path.isfile(meeting_path):
        checks["meeting_exists"] = True
        mtxt = read_text(meeting_path)
        if mtxt is not None:
            if "## Summary" in mtxt:
                checks["meeting_has_summary"] = True
            if "## Action Items" in mtxt:
                checks["meeting_has_action_items"] = True
            if re.search(r"^- \[ \]", mtxt, flags=re.MULTILINE):
                checks["meeting_has_checklist_item"] = True
            if "## Decisions" in mtxt:
                checks["meeting_has_decisions"] = True
            if "Raw Notes" in mtxt:
                checks["meeting_has_raw_notes"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()