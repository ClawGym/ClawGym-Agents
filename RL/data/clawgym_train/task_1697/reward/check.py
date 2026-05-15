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

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f.readlines()]
    except Exception:
        return None

def count_bullets(lines):
    return sum(1 for ln in lines if ln.strip().startswith("- "))

def extract_bullets(lines):
    return [ln for ln in lines if ln.strip().startswith("- ")]

def has_source_tag(text):
    # Accept only the allowed sources
    pattern = r"\[source:\s*(support_chat-12345|direct_dm-67890)\]"
    return re.search(pattern, text) is not None

def sources_in_text(text):
    return {
        "support": ("[source: support_chat-12345]" in text),
        "direct": ("[source: direct_dm-67890]" in text),
    }

def sources_in_lines(lines):
    support = any("[source: support_chat-12345]" in ln for ln in lines)
    direct = any("[source: direct_dm-67890]" in ln for ln in lines)
    return {"support": support, "direct": direct}

def has_forbidden_terms(text):
    # Case-sensitive exact for "self-reflection" to avoid matching the required "Self-Reflection" heading.
    return ("self-reflection" in text) or ("cron-self-reflection-999" in text)

def parse_memory_sections(lines):
    # Return indices and sections content
    headings = {
        "top": "## Self-Reflection — 2026-04-18",
        "insights": "### Insights",
        "tool_notes": "### Tool Notes",
        "user_context": "### User Context",
        "summary": "### Summary",
    }
    idx = {}
    for i, ln in enumerate(lines):
        if ln.strip() == headings["top"]:
            idx["top"] = i
        elif ln.strip() == headings["insights"]:
            idx["insights"] = i
        elif ln.strip() == headings["tool_notes"]:
            idx["tool_notes"] = i
        elif ln.strip() == headings["user_context"]:
            idx["user_context"] = i
        elif ln.strip() == headings["summary"]:
            idx["summary"] = i

    sections = {}
    # Helper to slice between two indices
    def slice_between(start_key, end_key):
        if start_key not in idx:
            return []
        start = idx[start_key] + 1
        # find next heading after start
        following_keys = [k for k in ["insights", "tool_notes", "user_context", "summary"] if k in idx and idx[k] > idx[start_key]]
        if end_key and end_key in idx and idx[end_key] > idx[start_key]:
            end = idx[end_key]
        else:
            # Compute next nearest heading after start_key
            candidates = [idx[k] for k in following_keys]
            if candidates:
                end = min(candidates)
            else:
                end = len(lines)
        return lines[start:end]

    sections["insights"] = slice_between("insights", None)
    sections["tool_notes"] = slice_between("tool_notes", None)
    sections["user_context"] = slice_between("user_context", None)
    # Summary is from its heading to EOF
    if "summary" in idx:
        sections["summary"] = lines[idx["summary"] + 1 :]
    else:
        sections["summary"] = []

    return headings, idx, sections

def summary_is_single_paragraph_with_sentence_count(summary_lines, min_sent=2, max_sent=4):
    # Determine a single paragraph: contiguous non-empty lines until first blank line
    # After first blank, no further non-empty content allowed
    if summary_lines is None:
        return False
    # Strip trailing spaces
    stripped = [ln.rstrip() for ln in summary_lines]
    # Identify first block (paragraph)
    para = []
    i = 0
    while i < len(stripped) and stripped[i].strip() != "":
        para.append(stripped[i])
        i += 1
    # Allow blank lines; ensure no more non-empty lines after the first blank encountered
    # Skip blank lines
    j = i
    while j < len(stripped) and stripped[j].strip() == "":
        j += 1
    # If there are further non-empty lines beyond the first paragraph, then not a single paragraph
    if j < len(stripped):
        return False
    # Join paragraph to count sentences
    text = " ".join(para).strip()
    if not text:
        return False
    # Count sentence enders ., !, ?
    ends = re.findall(r"[.!?](?=(\s|$))", text)
    n = len(ends)
    return (min_sent <= n <= max_sent)

def line_set(path):
    lines = read_lines(path)
    return set(lines) if lines is not None else set()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    out_agents = os.path.join(output_dir, "AGENTS.md")
    out_tools = os.path.join(output_dir, "TOOLS.md")
    out_mem_dir = os.path.join(output_dir, "memory")
    out_mem_daily = os.path.join(out_mem_dir, "2026-04-18.md")
    out_about_user = os.path.join(out_mem_dir, "about-user.md")

    in_agents = os.path.join(input_dir, "docs", "AGENTS.md")
    in_tools = os.path.join(input_dir, "docs", "TOOLS.md")
    in_about_user = os.path.join(input_dir, "docs", "memory", "about-user.md")

    checks = {
        # Presence checks
        "has_agents_output": False,
        "has_tools_output": False,
        "has_memory_daily_output": False,
        "has_about_user_output": False,

        # Source tag checks
        "agents_has_source_tag": False,
        "tools_has_source_tag": False,
        "memory_has_both_sources": False,

        # Self-reflection skip in outputs
        "no_forbidden_terms_in_outputs": False,

        # AGENTS.md content checks
        "agents_bullets_count_2_5": False,
        "agents_mentions_timezone": False,
        "agents_mentions_path_or_exists": False,
        "agents_no_duplicate_lines_with_input": False,

        # TOOLS.md content checks
        "tools_bullets_count_2_5": False,
        "tools_has_csv_delimiter_semicolon": False,
        "tools_mentions_permission_or_destination": False,
        "tools_no_duplicate_lines_with_input": False,

        # Daily memory structure checks
        "memory_has_required_headings": False,
        "memory_insights_bullets_2_6_with_both_sources": False,
        "memory_tool_notes_has_source_bullet": False,
        "memory_no_cron_self_reflection_substring": False,
        "memory_summary_is_2_4_sentences_single_paragraph": False,

        # About-user updates checks
        "about_user_has_concise_bullet_preference": False,
        "about_user_has_timezone_preference": False,
        "about_user_no_duplicate_lines_with_input": False,
    }

    # Presence checks
    agents_text = read_text(out_agents)
    tools_text = read_text(out_tools)
    mem_daily_text = read_text(out_mem_daily)
    about_user_text = read_text(out_about_user)

    if agents_text is not None and agents_text.strip():
        checks["has_agents_output"] = True
    if tools_text is not None and tools_text.strip():
        checks["has_tools_output"] = True
    if mem_daily_text is not None and mem_daily_text.strip():
        checks["has_memory_daily_output"] = True
    if about_user_text is not None and about_user_text.strip():
        checks["has_about_user_output"] = True

    # If any required output missing or empty, reward must be 0.0 at the end (gated).
    all_outputs_present = all([
        checks["has_agents_output"],
        checks["has_tools_output"],
        checks["has_memory_daily_output"],
        checks["has_about_user_output"],
    ])

    # Proceed with deeper checks only if respective outputs exist
    # Forbidden terms across all outputs
    if all_outputs_present:
        combined_text = "\n".join([agents_text, tools_text, mem_daily_text, about_user_text])
        checks["no_forbidden_terms_in_outputs"] = not has_forbidden_terms(combined_text)
    else:
        checks["no_forbidden_terms_in_outputs"] = False

    # Load input docs for duplication checks
    in_agents_lines = read_lines(in_agents) or []
    in_tools_lines = read_lines(in_tools) or []
    in_about_user_lines = read_lines(in_about_user) or []

    # AGENTS.md content checks
    if checks["has_agents_output"]:
        agents_lines = read_lines(out_agents) or []
        agents_bullets = extract_bullets(agents_lines)
        checks["agents_bullets_count_2_5"] = 2 <= len(agents_bullets) <= 5

        # timezone mention
        checks["agents_mentions_timezone"] = any(
            ("timezone" in ln.lower() or "time zone" in ln.lower())
            for ln in agents_bullets
        )

        # path or exists/existence mention
        checks["agents_mentions_path_or_exists"] = any(
            ("path" in ln.lower() or "exists" in ln.lower() or "existence" in ln.lower())
            for ln in agents_bullets
        )

        # At least one source tag
        checks["agents_has_source_tag"] = has_source_tag("\n".join(agents_lines))

        # No line exactly matches any full line in input/docs/AGENTS.md
        in_agents_set = set(in_agents_lines)
        checks["agents_no_duplicate_lines_with_input"] = not any(
            (ln in in_agents_set) for ln in agents_lines
        )

    # TOOLS.md content checks
    if checks["has_tools_output"]:
        tools_lines_list = read_lines(out_tools) or []
        tools_bullets = extract_bullets(tools_lines_list)
        checks["tools_bullets_count_2_5"] = 2 <= len(tools_bullets) <= 5

        # CSV delimiter semicolon in one bullet (case-insensitive)
        def bullet_has_csv_delim_semicolon(ln):
            low = ln.lower()
            return ("csv" in low) and ("delimiter" in low) and ("semicolon" in low)
        checks["tools_has_csv_delimiter_semicolon"] = any(bullet_has_csv_delim_semicolon(ln) for ln in tools_bullets)

        # permission or placement issues
        def bullet_has_permission_or_destination(ln):
            low = ln.lower()
            return ("permission denied" in low) or ("permission" in low) or ("group" in low) or ("destination" in low)
        checks["tools_mentions_permission_or_destination"] = any(bullet_has_permission_or_destination(ln) for ln in tools_bullets)

        # At least one source tag
        checks["tools_has_source_tag"] = has_source_tag("\n".join(tools_lines_list))

        # No line exactly matches any full line in input/docs/TOOLS.md
        in_tools_set = set(in_tools_lines)
        checks["tools_no_duplicate_lines_with_input"] = not any(
            (ln in in_tools_set) for ln in tools_lines_list
        )

    # Daily memory structure checks
    if checks["has_memory_daily_output"]:
        mem_lines = read_lines(out_mem_daily) or []
        headings, idx, sections = parse_memory_sections(mem_lines)

        # Required headings present exactly
        required_headings_present = (
            any(ln.strip() == headings["top"] for ln in mem_lines) and
            ("insights" in idx) and ("tool_notes" in idx) and ("user_context" in idx) and ("summary" in idx)
        )
        checks["memory_has_required_headings"] = required_headings_present

        # Insights section bullets count 2–6 and has both sources
        insights_bullets = extract_bullets(sections.get("insights", []))
        insights_count_ok = 2 <= len(insights_bullets) <= 6
        insights_sources = sources_in_lines(insights_bullets)
        has_both_insight_sources = insights_sources["support"] and insights_sources["direct"]
        checks["memory_insights_bullets_2_6_with_both_sources"] = insights_count_ok and has_both_insight_sources

        # Tool Notes section at least one bullet with [source: ...] tag
        tool_notes_bullets = extract_bullets(sections.get("tool_notes", []))
        tool_notes_has_source = any(has_source_tag(ln) for ln in tool_notes_bullets)
        checks["memory_tool_notes_has_source_bullet"] = tool_notes_has_source

        # File must not contain substring "cron-self-reflection"
        checks["memory_no_cron_self_reflection_substring"] = ("cron-self-reflection" not in (mem_daily_text or ""))

        # Summary: single paragraph with 2–4 sentences
        checks["memory_summary_is_2_4_sentences_single_paragraph"] = summary_is_single_paragraph_with_sentence_count(
            sections.get("summary", []), 2, 4
        )

        # Memory file must contain both sources somewhere (in its sections)
        mem_sources = sources_in_text(mem_daily_text or "")
        checks["memory_has_both_sources"] = mem_sources["support"] and mem_sources["direct"]

    # About-user updates checks
    if checks["has_about_user_output"]:
        about_lines = read_lines(out_about_user) or []

        # At least one new line containing both "concise" and "bullet"/"bullets"
        checks["about_user_has_concise_bullet_preference"] = any(
            ("concise" in ln.lower() and ("bullet" in ln.lower()))
            for ln in about_lines
        )

        # At least one new line referencing time zone preferences
        tz_keywords = ["timezone", "time zone", "boston", "et"]
        checks["about_user_has_timezone_preference"] = any(
            any(k in ln.lower() for k in tz_keywords) for ln in about_lines
        )

        # No line exactly matches any full line in input/docs/memory/about-user.md
        in_about_set = set(in_about_user_lines)
        checks["about_user_no_duplicate_lines_with_input"] = not any(
            (ln in in_about_set) for ln in about_lines
        )

    # Overall reward
    # Gate: if any required output missing or empty, reward must be 0.0
    if not all_outputs_present:
        reward = 0.0
    else:
        # Count all boolean checks (excluding the four presence ones? Presence also count as checks.)
        # Presence checks also contribute to overall pass/fail visibility, but reward only meaningful if all present due to gate.
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Normalize between 0 and 1
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print final JSON
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()