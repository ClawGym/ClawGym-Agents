import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    out_path = os.path.join(output_dir, "brief_modular.md")

    checks = {
        "file_exists": False,
        "non_empty": False,
        "headings_correct": False,
        "takeaway_all_sections": False,
        "risks_has_bullet": False,
        "next_steps_has_numbered": False,
        "has_bullet_list_global": False,
        "has_numbered_list_global": False,
        "contains_required_terms": False,
        "has_two_bold_phrases": False,
    }

    if not os.path.isfile(out_path):
        print(json.dumps({"reward": 0.0, **checks}))
        return

    checks["file_exists"] = True

    try:
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        # If we cannot read, treat as empty/missing
        print(json.dumps({"reward": 0.0, **checks}))
        return

    if content.strip():
        checks["non_empty"] = True
    else:
        print(json.dumps({"reward": 0.0, **checks}))
        return

    lines = content.splitlines()

    # Detect exactly the specified five section headings in exact order with no extras
    expected_headings = [
        "## 🧭 Overview",
        "## 📌 Current Status",
        "## 🛡️ Risks & Mitigations",
        "## ▶️ Next Steps",
        "## 📈 Metrics",
    ]

    # Collect headings that are exactly level-2 (## ) headings
    heading_regex = re.compile(r"^\s*##\s(?!!#)(.+)$")  # captures after '## '
    found_headings = []
    heading_positions = []  # (index, text)
    for idx, line in enumerate(lines):
        m = heading_regex.match(line)
        if m:
            text = line.strip()
            # Ensure exactly two hashes, not more
            if text.startswith("## ") and not text.startswith("###"):
                found_headings.append(text)
                heading_positions.append((idx, text))

    if found_headings == expected_headings:
        checks["headings_correct"] = True

    # Section boundary map for later checks
    section_ranges = {}  # title -> (start_line_idx, end_line_idx_exclusive)
    if checks["headings_correct"]:
        # Build ranges for each section
        for i, (idx, title) in enumerate(heading_positions):
            start = idx + 1
            if i + 1 < len(heading_positions):
                end = heading_positions[i + 1][0]
            else:
                end = len(lines)
            section_ranges[title] = (start, end)

        # Takeaway presence in each section
        takeaway_ok = True
        for title in expected_headings:
            s, e = section_ranges.get(title, (None, None))
            if s is None:
                takeaway_ok = False
                break
            section_lines = lines[s:e]
            has_takeaway = any(l.strip().startswith("Takeaway:") for l in section_lines)
            if not has_takeaway:
                takeaway_ok = False
                break
        checks["takeaway_all_sections"] = takeaway_ok

        # Risks section must have at least one bullet line "- "
        rs = section_ranges.get("## 🛡️ Risks & Mitigations")
        if rs:
            s, e = rs
            risks_lines = lines[s:e]
            if any(re.match(r"^\s*-\s+.+", l) for l in risks_lines):
                checks["risks_has_bullet"] = True

        # Next Steps must have at least one numbered item "1. "
        ns = section_ranges.get("## ▶️ Next Steps")
        if ns:
            s, e = ns
            next_lines = lines[s:e]
            if any(re.match(r"^\s*1\.\s+.+", l) for l in next_lines):
                checks["next_steps_has_numbered"] = True

    # Global bullet and numbered list presence
    if any(re.match(r"^\s*-\s+.+", l) for l in lines):
        checks["has_bullet_list_global"] = True
    if any(re.match(r"^\s*\d+\.\s+.+", l) for l in lines):
        checks["has_numbered_list_global"] = True

    # Required substrings check (case-sensitive exact substrings)
    required_terms = [
        "Q2 OKRs",
        "Guided Setup v2",
        "p95",
        "latency",
        "onboarding",
        "June 30",
        "380ms",
    ]
    if all(term in content for term in required_terms):
        checks["contains_required_terms"] = True

    # At least two bold phrases using Markdown **...**
    bold_matches = re.findall(r"\*\*[^*\n]+\*\*", content)
    if len(bold_matches) >= 2:
        checks["has_two_bold_phrases"] = True

    # Compute reward: zero if file missing or empty; else proportion of key checks
    key_checks = [
        "headings_correct",
        "takeaway_all_sections",
        "risks_has_bullet",
        "next_steps_has_numbered",
        "has_bullet_list_global",
        "has_numbered_list_global",
        "contains_required_terms",
        "has_two_bold_phrases",
    ]
    if not (checks["file_exists"] and checks["non_empty"]):
        reward = 0.0
    else:
        total = len(key_checks)
        passed = sum(1 for k in key_checks if checks[k])
        reward = passed / total if total > 0 else 0.0

    # Ensure reward is within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()