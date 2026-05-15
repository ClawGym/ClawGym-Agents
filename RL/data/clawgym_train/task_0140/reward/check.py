import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def first_nonempty_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.rstrip("\n")
    return ""

def find_section_indices(lines, section_titles):
    # Returns a dict of section title -> first line index where it appears exactly as "## Title"
    indices = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        for title in section_titles:
            if stripped == title:
                if title not in indices:
                    indices[title] = i
    return indices

def find_section_bounds(lines, start_title):
    # Returns (start_index_inclusive, end_index_exclusive) for a "##" section
    # If start_title not found, return (None, None)
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == start_title:
            start_idx = i
            break
    if start_idx is None:
        return (None, None)
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end_idx = j
            break
    return (start_idx, end_idx)

def contains_blockquote(text):
    for line in text.splitlines():
        if re.match(r'^\s*>', line):
            return True
    return False

def header_check(text, required_phrase, persona_indicator=None):
    line = first_nonempty_line(text)
    if not line:
        return False
    if not line.startswith("# "):
        return False
    if "LogLamp - Persona:" not in line:
        return False
    if persona_indicator:
        if persona_indicator.lower() not in line.lower():
            return False
    return True

def section_order_check(text):
    lines = text.splitlines()
    required_sections = [
        "## Target User",
        "## Problems Solved",
        "## Discovery",
        "## Onboarding",
        "## User Journey",
        "## Feature Touchpoints",
    ]
    indices = find_section_indices(lines, required_sections)
    # Ensure all sections exist
    if any(title not in indices for title in required_sections):
        return False
    # Ensure order
    last_index = -1
    for title in required_sections:
        idx = indices[title]
        if idx <= last_index:
            return False
        last_index = idx
    return True

def onboarding_phrases_check(text):
    lines = text.splitlines()
    start, end = find_section_bounds(lines, "## Onboarding")
    if start is None:
        return False
    section_text = "\n".join(lines[start:end])
    lc = section_text.lower()
    return ("time to value" in lc) and ("first success moment" in lc)

def journey_subsections_check(text):
    lines = text.splitlines()
    start, end = find_section_bounds(lines, "## User Journey")
    if start is None:
        return False
    section_text = "\n".join(lines[start:end])
    required_subs = [
        "### New User (Day 1)",
        "### Returning User (Week 1)",
        "### Power User (Month 1+)",
    ]
    for sub in required_subs:
        if sub not in section_text:
            return False
    return True

def keywords_check(text):
    lc = text.lower()
    keywords = [
        "opentelemetry",
        "structured logging",
        "kubernetes",
        "alerts",
        "slis/slos",
    ]
    for kw in keywords:
        if kw not in lc:
            return False
    return True

def feature_table_check(text):
    # Check inside Feature Touchpoints section
    lines = text.splitlines()
    start, end = find_section_bounds(lines, "## Feature Touchpoints")
    if start is None:
        return False
    section_lines = lines[start:end]
    # Find header row
    header_ok = False
    for line in section_lines:
        if re.match(r'^\|\s*Feature\s*\|\s*When Encountered\s*\|\s*User Need at That Moment\s*\|\s*$', line.strip()):
            header_ok = True
            break
    if not header_ok:
        return False
    # Count data rows starting with '|' excluding header and alignment row(s)
    data_rows = 0
    for line in section_lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        # Skip header
        if re.match(r'^\|\s*Feature\s*\|\s*When Encountered\s*\|\s*User Need at That Moment\s*\|\s*$', s):
            continue
        # Skip alignment/dashes row like |---|---|---|
        if re.match(r'^\|\s*[-:]+\s*\|\s*[-:]+\s*\|\s*[-:]+\s*\|\s*$', s):
            continue
        data_rows += 1
    return data_rows >= 2

def index_title_check(text):
    line = first_nonempty_line(text)
    return line.strip() == "# Personas"

def index_links_check(text):
    lines = [l.strip() for l in text.splitlines()]
    link1 = "- [Backend Engineer](personas/backend_engineer.md)"
    link2 = "- [SRE Manager](personas/sre_manager.md)"
    return (link1 in lines) and (link2 in lines)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    backend_path = os.path.join(output_dir, "docs", "personas", "backend_engineer.md")
    sre_path = os.path.join(output_dir, "docs", "personas", "sre_manager.md")
    index_path = os.path.join(output_dir, "docs", "PERSONA.md")

    checks = {
        "has_backend_file": False,
        "has_sre_file": False,
        "has_index_file": False,
        "backend_header_ok": False,
        "sre_header_ok": False,
        "backend_section_order_ok": False,
        "sre_section_order_ok": False,
        "backend_onboarding_phrases_ok": False,
        "sre_onboarding_phrases_ok": False,
        "backend_journey_subsections_ok": False,
        "sre_journey_subsections_ok": False,
        "backend_has_blockquote": False,
        "sre_has_blockquote": False,
        "backend_keywords_ok": False,
        "sre_keywords_ok": False,
        "backend_feature_table_ok": False,
        "sre_feature_table_ok": False,
        "sre_mentions_compliance_or_audit": False,
        "index_title_ok": False,
        "index_links_ok": False,
    }

    # Check existence
    if os.path.isfile(backend_path):
        checks["has_backend_file"] = True
        backend_text = read_text(backend_path)

        # Header must include "LogLamp - Persona:" and "Backend Engineer at a mid-size SaaS"
        checks["backend_header_ok"] = header_check(
            backend_text,
            required_phrase="LogLamp - Persona:",
            persona_indicator="Backend Engineer at a mid-size SaaS",
        )

        # Section order
        checks["backend_section_order_ok"] = section_order_check(backend_text)

        # Onboarding phrases in Onboarding section
        checks["backend_onboarding_phrases_ok"] = onboarding_phrases_check(backend_text)

        # Journey subsections inside User Journey
        checks["backend_journey_subsections_ok"] = journey_subsections_check(backend_text)

        # Blockquote evidence
        checks["backend_has_blockquote"] = contains_blockquote(backend_text)

        # Keywords
        checks["backend_keywords_ok"] = keywords_check(backend_text)

        # Feature Touchpoints table
        checks["backend_feature_table_ok"] = feature_table_check(backend_text)

    if os.path.isfile(sre_path):
        checks["has_sre_file"] = True
        sre_text = read_text(sre_path)

        # Header must include "LogLamp - Persona:" and "SRE Manager"
        checks["sre_header_ok"] = header_check(
            sre_text,
            required_phrase="LogLamp - Persona:",
            persona_indicator="SRE Manager",
        )

        # Section order
        checks["sre_section_order_ok"] = section_order_check(sre_text)

        # Onboarding phrases
        checks["sre_onboarding_phrases_ok"] = onboarding_phrases_check(sre_text)

        # Journey subsections
        checks["sre_journey_subsections_ok"] = journey_subsections_check(sre_text)

        # Blockquote
        checks["sre_has_blockquote"] = contains_blockquote(sre_text)

        # Keywords
        checks["sre_keywords_ok"] = keywords_check(sre_text)

        # Feature table
        checks["sre_feature_table_ok"] = feature_table_check(sre_text)

        # Compliance or audit
        if "compliance" in sre_text.lower() or "audit" in sre_text.lower():
            checks["sre_mentions_compliance_or_audit"] = True

    if os.path.isfile(index_path):
        checks["has_index_file"] = True
        index_text = read_text(index_path)
        checks["index_title_ok"] = index_title_check(index_text)
        checks["index_links_ok"] = index_links_check(index_text)

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline: if no required files exist, reward = 0.0
    if not (checks["has_backend_file"] or checks["has_sre_file"] or checks["has_index_file"]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()