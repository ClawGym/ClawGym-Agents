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

def find_section(content, start_marker, next_markers):
    """Return substring of content starting at start_marker up to the nearest of next_markers (exclusive)."""
    start_idx = content.find(start_marker)
    if start_idx == -1:
        return None
    end_idx_candidates = []
    for m in next_markers:
        i = content.find(m, start_idx + len(start_marker))
        if i != -1:
            end_idx_candidates.append(i)
    if end_idx_candidates:
        end_idx = min(end_idx_candidates)
        return content[start_idx:end_idx]
    return content[start_idx:]

def count_bullets(section_text):
    count = 0
    for line in section_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            count += 1
    return count

def is_positive_number(x):
    return isinstance(x, (int, float)) and x > 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    md_path = os.path.join(output_dir, "market_sizing.md")
    json_path = os.path.join(output_dir, "summary.json")

    checks = {
        "md_exists_nonempty": False,
        "md_title_heading_ok": False,
        "has_method1_section": False,
        "has_method2_section": False,
        "method1_has_subsections": False,
        "method2_has_subsections": False,
        "has_code_block": False,
        "has_ranges_mentions": False,
        "has_blended_acv": False,
        "sources_section_with_table": False,
        "summary_section_with_table": False,
        "has_divergence_note": False,
        "key_assumptions_bullets": False,
        "json_exists_and_valid": False,
        "json_schema_fields_present": False,
        "json_values_positive": False,
        "json_unit_usd": False,
    }

    md_content = None
    if os.path.isfile(md_path):
        md_content = read_text(md_path)
        if md_content is not None and md_content.strip() != "":
            checks["md_exists_nonempty"] = True

    if checks["md_exists_nonempty"]:
        # First non-empty line starts with "# Market Sizing:"
        first_nonempty = None
        for line in md_content.splitlines():
            if line.strip() != "":
                first_nonempty = line.strip()
                break
        if first_nonempty and first_nonempty.startswith("# Market Sizing:"):
            checks["md_title_heading_ok"] = True

        # Method sections
        has_m1 = "## Method 1: Bottom-up" in md_content
        has_m2 = "## Method 2: Top-down" in md_content
        checks["has_method1_section"] = has_m1
        checks["has_method2_section"] = has_m2

        # Subsections under Method 1 and Method 2
        if has_m1:
            # Define end markers likely to appear after Method 1
            m1_section = find_section(
                md_content,
                "## Method 1: Bottom-up",
                ["## Method 2: Top-down", "## Sources", "## Summary", "## Key assumptions", "## Key assumptions to validate"]
            )
            if m1_section:
                has_tam = "### TAM" in m1_section
                has_sam = "### SAM" in m1_section
                has_som = "### SOM" in m1_section
                if has_tam and has_sam and has_som:
                    checks["method1_has_subsections"] = True

        if has_m2:
            # Define end markers likely to appear after Method 2
            m2_section = find_section(
                md_content,
                "## Method 2: Top-down",
                ["## Sources", "## Summary", "## Key assumptions", "## Key assumptions to validate"]
            )
            if m2_section:
                has_tam2 = "### TAM" in m2_section
                has_sam2 = "### SAM" in m2_section
                has_som2 = "### SOM" in m2_section
                if has_tam2 and has_sam2 and has_som2:
                    checks["method2_has_subsections"] = True

        # Code block presence
        backticks_count = md_content.count("```")
        if backticks_count >= 2:
            checks["has_code_block"] = True

        # Ranges
        if md_content.lower().count("range:") >= 2:
            checks["has_ranges_mentions"] = True

        # Blended ACV
        if "blended acv" in md_content.lower():
            checks["has_blended_acv"] = True

        # Sources section with at least one table row with pipes under it
        sources_idx = md_content.find("## Sources")
        if sources_idx != -1:
            # Find end of sources section
            after_sources = md_content[sources_idx + len("## Sources"):]
            # Cut off at next "## "
            next_h2 = after_sources.find("\n## ")
            section_text = after_sources if next_h2 == -1 else after_sources[:next_h2]
            # Check for a line with pipe '|'
            has_pipe_row = any(("|" in line) for line in section_text.splitlines())
            if has_pipe_row:
                checks["sources_section_with_table"] = True

        # Summary section with table and divergence note anywhere
        summary_idx = md_content.find("## Summary")
        if summary_idx != -1:
            after_summary = md_content[summary_idx + len("## Summary"):]
            next_h2b = after_summary.find("\n## ")
            summary_text = after_summary if next_h2b == -1 else after_summary[:next_h2b]
            has_pipe_row_summary = any(("|" in line) for line in summary_text.splitlines())
            if has_pipe_row_summary:
                checks["summary_section_with_table"] = True

        if "diverg" in md_content.lower():
            checks["has_divergence_note"] = True

        # Key assumptions to validate section with at least 3 bullet points
        lower_content = md_content.lower()
        assum_phrase = "key assumptions to validate"
        assum_idx = lower_content.find(assum_phrase)
        if assum_idx != -1:
            after_assum = md_content[assum_idx + len(assum_phrase):]
            # Cut at next h2
            next_h2c = after_assum.find("\n## ")
            assum_text = after_assum if next_h2c == -1 else after_assum[:next_h2c]
            bullets = count_bullets(assum_text)
            if bullets >= 3:
                checks["key_assumptions_bullets"] = True

    # JSON checks
    json_obj = None
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                json_obj = json.load(f)
            checks["json_exists_and_valid"] = True
        except Exception:
            checks["json_exists_and_valid"] = False

    if checks["json_exists_and_valid"]:
        # unit == "USD"
        unit_ok = isinstance(json_obj, dict) and json_obj.get("unit") == "USD"
        checks["json_unit_usd"] = unit_ok

        required_ok = True
        numeric_positive_ok = True

        for branch in ["bottom_up", "top_down"]:
            if branch not in json_obj or not isinstance(json_obj[branch], dict):
                required_ok = False
                continue
            br = json_obj[branch]
            # TAM and SAM
            for bucket in ["TAM", "SAM"]:
                if bucket not in br or not isinstance(br[bucket], dict):
                    required_ok = False
                    continue
                b = br[bucket]
                for field in ["point", "low", "high"]:
                    if field not in b:
                        required_ok = False
                    else:
                        val = b[field]
                        if not isinstance(val, (int, float)):
                            numeric_positive_ok = False
                        elif val <= 0:
                            numeric_positive_ok = False
            # SOM
            if "SOM" not in br or not isinstance(br["SOM"], dict):
                required_ok = False
            else:
                som = br["SOM"]
                for field in ["year1", "year3"]:
                    if field not in som:
                        required_ok = False
                    else:
                        val = som[field]
                        if not isinstance(val, (int, float)):
                            numeric_positive_ok = False
                        elif val <= 0:
                            numeric_positive_ok = False

        checks["json_schema_fields_present"] = required_ok
        checks["json_values_positive"] = numeric_positive_ok

    # Compute reward
    # If required artifacts are missing (md or json), reward must be exactly 0.0
    required_artifacts_present = checks["md_exists_nonempty"] and checks["json_exists_and_valid"]
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_artifacts_present:
        reward = 0.0
    else:
        # Deterministic partial scoring: fraction of checks passed
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Print exactly one JSON object as last non-empty line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()