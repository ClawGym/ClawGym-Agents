import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""

def parse_skills(input_skills_dir):
    names = []
    for root, dirs, files in os.walk(input_skills_dir):
        for fn in files:
            if fn == "SKILL.md":
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        content = f.read()
                except Exception:
                    continue
                # Extract name field from YAML front matter line starting with "name:"
                name_match = re.search(r'(?mi)^\s*name\s*:\s*["\']?([A-Za-z0-9._\- ]+)["\']?', content)
                if name_match:
                    name = name_match.group(1).strip()
                    if name:
                        names.append(name)
    return sorted(set(names))

def count_pending_successes_for_pair(learnings_text, skill_pair):
    # Count blocks with Category: emergent_capability, Status: pending, Skills combined: <pair>
    # We'll parse by splitting on headings "## " which denotes entries
    blocks = re.split(r'(?m)^\s*##\s+', learnings_text)
    count = 0
    for b in blocks:
        # Normalize
        if not b.strip():
            continue
        cat = re.search(r'(?mi)^\s*\*\*Category\*\*:\s*([^\n\r]+)', b)
        if not cat:
            cat = re.search(r'(?mi)^\s*Category\s*:\s*([^\n\r]+)', b)
        status = re.search(r'(?mi)^\s*\*\*Status\*\*:\s*([^\n\r]+)', b)
        if not status:
            status = re.search(r'(?mi)^\s*Status\s*:\s*([^\n\r]+)', b)
        skills = re.search(r'(?mi)^\s*\*\*Skills combined\*\*:\s*([^\n\r]+)', b)
        if not skills:
            skills = re.search(r'(?mi)^\s*Skills combined\s*:\s*([^\n\r]+)', b)
        cat_v = cat.group(1).strip().lower() if cat else ""
        status_v = status.group(1).strip().lower() if status else ""
        skills_v = skills.group(1).strip().lower() if skills else ""
        if cat_v == "emergent_capability" and status_v == "pending" and skills_v == skill_pair.lower():
            count += 1
    return count

def count_pair_status_in_output(learnings_text, skill_pair, status_value):
    # Count blocks with given pair and status_value (case-insensitive)
    blocks = re.split(r'(?m)^\s*##\s+', learnings_text)
    count = 0
    for b in blocks:
        if not b.strip():
            continue
        status = re.search(r'(?mi)^\s*\*\*Status\*\*:\s*([^\n\r]+)', b)
        if not status:
            status = re.search(r'(?mi)^\s*Status\s*:\s*([^\n\r]+)', b)
        skills = re.search(r'(?mi)^\s*\*\*Skills combined\*\*:\s*([^\n\r]+)', b)
        if not skills:
            skills = re.search(r'(?mi)^\s*Skills combined\s*:\s*([^\n\r]+)', b)
        status_v = status.group(1).strip().lower() if status else ""
        skills_v = skills.group(1).strip().lower() if skills else ""
        if skills_v == skill_pair.lower() and status_v == status_value.lower():
            count += 1
    return count

def find_blocks_with_proven_status(combos_text):
    # Return list of blocks (text) that contain "Status: proven"
    blocks = re.split(r'(?m)^\s*##\s+\[', combos_text)  # entry titles like ## [YYYY-MM-DD] Name
    proven_blocks = []
    for b in blocks:
        if not b.strip():
            continue
        if re.search(r'(?mi)^\s*Status\s*:\s*proven\b', b):
            proven_blocks.append(b)
    return proven_blocks

def block_has_expected_fields_for_pair(block_text, skill_pair):
    # Check required lines exist and non-empty
    # Skills involved: exact pair
    skills_line = re.search(r'(?mi)^\s*\*\*Skills involved\*\*:\s*([^\n\r]+)', block_text)
    if not skills_line:
        skills_line = re.search(r'(?mi)^\s*Skills involved\s*:\s*([^\n\r]+)', block_text)
    if not skills_line:
        return False
    skills_v = skills_line.group(1).strip().lower()
    if skills_v != skill_pair.lower():
        return False
    # Mission context non-empty
    mission = re.search(r'(?mi)^\s*\*\*Mission context\*\*:\s*([^\n\r]+)', block_text)
    if not mission:
        mission = re.search(r'(?mi)^\s*Mission context\s*:\s*([^\n\r]+)', block_text)
    if not mission or not mission.group(1).strip():
        return False
    # Emergent capability non-empty
    emergent = re.search(r'(?mi)^\s*\*\*Emergent capability\*\*:\s*([^\n\r]+)', block_text)
    if not emergent:
        emergent = re.search(r'(?mi)^\s*Emergent capability\s*:\s*([^\n\r]+)', block_text)
    if not emergent or not emergent.group(1).strip():
        return False
    # Mechanism non-empty
    mech = re.search(r'(?mi)^\s*\*\*Mechanism\*\*:\s*([^\n\r]+)', block_text)
    if not mech:
        mech = re.search(r'(?mi)^\s*Mechanism\s*:\s*([^\n\r]+)', block_text)
    if not mech or not mech.group(1).strip():
        return False
    # Performance line format
    perf = re.search(r'(?mi)^\s*\*\*Performance\*\*:\s*([^\n\r]+)', block_text)
    if not perf:
        perf = re.search(r'(?mi)^\s*Performance\s*:\s*([^\n\r]+)', block_text)
    if not perf:
        return False
    perf_v = perf.group(1)
    if not re.search(r'(?i)tested\s+\d+\s+times\s*\|\s*success rate\s+\d+%$', perf_v.strip()):
        return False
    # Status proven
    if not re.search(r'(?mi)^\s*\*\*Status\*\*:\s*proven\b', block_text) and not re.search(r'(?mi)^\s*Status\s*:\s*proven\b', block_text):
        return False
    # Confidence medium
    if not re.search(r'(?mi)^\s*\*\*Confidence\*\*:\s*medium\b', block_text) and not re.search(r'(?mi)^\s*Confidence\s*:\s*medium\b', block_text):
        return False
    # ROI multiplier like 2x
    roi = re.search(r'(?mi)^\s*\*\*ROI multiplier\*\*:\s*([^\n\r]+)', block_text)
    if not roi:
        roi = re.search(r'(?mi)^\s*ROI multiplier\s*:\s*([^\n\r]+)', block_text)
    if not roi:
        return False
    roi_v = roi.group(1).strip()
    if not re.search(r'^\d+(\.\d+)?x$', roi_v):
        return False
    # Logged by present
    if not re.search(r'(?mi)^\s*\*\*Logged by\*\*:\s*([^\n\r]+)', block_text) and not re.search(r'(?mi)^\s*Logged by\s*:\s*([^\n\r]+)', block_text):
        return False
    return True

def extract_section(text, header):
    # Return the section content from header line to next all-caps section or end
    # We look for the header line and then until next line that looks like a section title in all caps or starts with an emoji bullet
    lines = text.splitlines()
    content = []
    in_section = False
    for i, line in enumerate(lines):
        if in_section:
            # Next section headers (basic heuristic)
            if re.match(r'(?i)^\s*(EMERGENT CAPABILITIES DISCOVERED|TOP PROVEN COMBINATIONS|NEW SKILL PROPOSALS|ECOSYSTEM HEALTH|SKILLS INVENTORY|SKILL COMBINATOR — Weekly Report|SKILL COMBINATOR - Weekly Report)', line):
                if line.strip().upper() != header.strip().upper():
                    break
            content.append(line)
        else:
            if line.strip().upper() == header.strip().upper():
                in_section = True
                content.append(line)
    return "\n".join(content) if in_section else ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    input_learnings_path = os.path.join(input_dir, ".learnings", "LEARNINGS.md")
    input_combos_path = os.path.join(input_dir, "COMBINATIONS.md")
    input_feature_req_path = os.path.join(input_dir, ".learnings", "FEATURE_REQUESTS.md")
    input_skills_dir = os.path.join(input_dir, "skills")

    output_combos_path = os.path.join(output_dir, "COMBINATIONS.md")
    output_learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    output_weekly_report_path = os.path.join(output_dir, "weekly_report.txt")
    output_memory_path = os.path.join(output_dir, "memory", "2026-04-16.md")
    output_agents_path = os.path.join(output_dir, "AGENTS.md")  # should not exist

    # Load inputs for reference (do not award credit for this)
    input_learnings_text = read_text(input_learnings_path)
    input_combos_text = read_text(input_combos_path)
    # Count pending successes for schema-markup + roi
    target_pair = "schema-markup + roi"
    pending_successes_target = count_pending_successes_for_pair(input_learnings_text, target_pair)
    # Also check for presence of non-proven pair searxng + schema-markup in input
    other_pair = "searxng + schema-markup"
    pending_other_pair = count_pending_successes_for_pair(input_learnings_text, other_pair)

    # Parse installed skill names from input
    installed_skills = parse_skills(input_skills_dir)

    checks = {
        "combinations_md_exists": False,
        "combinations_has_expected_proven_entry": False,
        "combinations_only_expected_proven": False,
        "learnings_updated_resolve_expected": False,
        "learnings_non_proven_not_resolved": False,
        "weekly_report_exists": False,
        "weekly_report_inventory_has_skills": False,
        "weekly_report_promotion_count_one": False,
        "weekly_report_failed_count_present": False,
        "weekly_report_top_proven_includes_pair": False,
        "weekly_report_proposals_contains_jobposting": False,
        "weekly_report_ecosystem_health_present": False,
        "memory_file_exists": False,
        "memory_summary_mentions_promotion_and_proposals": False,
        "no_output_agents_md": False
    }

    # Check COMBINATIONS.md
    if os.path.isfile(output_combos_path):
        checks["combinations_md_exists"] = True
        combos_text = read_text(output_combos_path)
        proven_blocks = find_blocks_with_proven_status(combos_text)
        # Must have exactly one proven block and it must be for schema-markup + roi with required fields
        if len(proven_blocks) == 1:
            block = proven_blocks[0]
            # Check the block has expected fields and matches target pair AND there are >=3 successes in input
            if pending_successes_target >= 3 and block_has_expected_fields_for_pair(block, target_pair):
                checks["combinations_has_expected_proven_entry"] = True
        # Ensure no other combinations are marked proven (i.e., only expected pair)
        only_expected = True
        if len(proven_blocks) == 0:
            only_expected = False
        for b in proven_blocks:
            # If this proven block is not the target pair, fail
            skills_line = re.search(r'(?mi)^\s*(?:\*\*)?Skills involved(?:\*\*)?\s*:\s*([^\n\r]+)', b)
            skills_v = skills_line.group(1).strip().lower() if skills_line else ""
            if skills_v != target_pair.lower():
                only_expected = False
        if only_expected and len(proven_blocks) == 1:
            checks["combinations_only_expected_proven"] = True

    # Check updated LEARNINGS.md
    if os.path.isfile(output_learnings_path):
        output_learnings_text = read_text(output_learnings_path)
        # For the target pair, all pending successes from input should be resolved in output (at least that many)
        resolved_count_out = count_pair_status_in_output(output_learnings_text, target_pair, "resolved")
        pending_count_out_target = count_pair_status_in_output(output_learnings_text, target_pair, "pending")
        if pending_successes_target >= 3 and resolved_count_out >= pending_successes_target and pending_count_out_target == 0:
            checks["learnings_updated_resolve_expected"] = True
        # For non-proven pair "searxng + schema-markup", ensure not resolved (if present in input, it must remain pending)
        if pending_other_pair > 0:
            # Ensure there is no resolved entry for this pair in output and at least one pending remains
            resolved_other = count_pair_status_in_output(output_learnings_text, other_pair, "resolved")
            pending_other_out = count_pair_status_in_output(output_learnings_text, other_pair, "pending")
            if resolved_other == 0 and pending_other_out >= pending_other_pair:
                checks["learnings_non_proven_not_resolved"] = True
        else:
            # If not present in input, require that output file exists to avoid granting credit on no-op
            checks["learnings_non_proven_not_resolved"] = True

    # Check weekly_report.txt
    if os.path.isfile(output_weekly_report_path):
        checks["weekly_report_exists"] = True
        report_text = read_text(output_weekly_report_path)
        # Header present
        header_ok = bool(re.search(r'(?mi)^\s*SKILL COMBINATOR — Weekly Report', report_text))
        # SKILLS INVENTORY section includes installed skills
        inv_section = extract_section(report_text, "SKILLS INVENTORY")
        inv_ok = bool(inv_section)
        # Ensure at least required skills are listed
        required_skill_names = []
        for nm in installed_skills:
            # The dataset requires at least these names: schema-markup, searxng, roi
            if nm in ["schema-markup", "searxng", "roi"]:
                required_skill_names.append(nm)
        skills_listed = all((re.search(r'(?mi)\b' + re.escape(nm) + r'\b', inv_section) is not None) for nm in required_skill_names) if inv_section else False
        if header_ok and inv_ok and skills_listed:
            checks["weekly_report_inventory_has_skills"] = True
        # Promoted count = 1
        if re.search(r'(?mi)Promoted to COMBINATIONS\.md:\s*1\b', report_text):
            checks["weekly_report_promotion_count_one"] = True
        # Failed combinations logged: N (ensure line with number exists)
        if re.search(r'(?mi)Failed combinations logged:\s*\d+', report_text):
            checks["weekly_report_failed_count_present"] = True
        # EMERGENT CAPABILITIES DISCOVERED includes newly proven line with A + B = ...
        emergent_section = extract_section(report_text, "EMERGENT CAPABILITIES DISCOVERED")
        if emergent_section and re.search(r'(?mi)schema\-markup\s*\+\s*roi', emergent_section) and re.search(r'=', emergent_section):
            checks["weekly_report_top_proven_includes_pair"] = True  # using this flag name for inclusion; will also check TOP PROVEN COMBINATIONS next
        # TOP PROVEN COMBINATIONS includes pair with confidence and ROI
        top_section = extract_section(report_text, "TOP PROVEN COMBINATIONS")
        if top_section and re.search(r'(?mi)schema\-markup\s*\+\s*roi', top_section) and re.search(r'(?mi)confidence\s*:\s*(low|medium|high)', top_section) and re.search(r'(?mi)ROI\s*:\s*\d+(\.\d+)?x', top_section):
            checks["weekly_report_top_proven_includes_pair"] = True
        # NEW SKILL PROPOSALS contains "JobPosting schema generator"
        prop_section = extract_section(report_text, "NEW SKILL PROPOSALS")
        if prop_section and re.search(r'(?mi)JobPosting schema generator', prop_section):
            checks["weekly_report_proposals_contains_jobposting"] = True
        # ECOSYSTEM HEALTH section present with counts
        eco_section = extract_section(report_text, "ECOSYSTEM HEALTH")
        if eco_section and (re.search(r'\d', eco_section) is not None):
            checks["weekly_report_ecosystem_health_present"] = True

    # Memory summary file
    if os.path.isfile(output_memory_path):
        checks["memory_file_exists"] = True
        mem_text = read_text(output_memory_path)
        # Should mention reviewed files and promotions and proposals
        reviewed_ok = all(k in mem_text for k in ["LEARNINGS.md", "COMBINATIONS.md"])
        promotions_ok = bool(re.search(r'(?mi)promotions?\s*:\s*1', mem_text)) or bool(re.search(r'(?mi)promoted\s*:\s*1', mem_text))
        proposals_ok = re.search(r'(?mi)JobPosting schema generator', mem_text) is not None
        if reviewed_ok and promotions_ok and proposals_ok:
            checks["memory_summary_mentions_promotion_and_proposals"] = True

    # Ensure no output/AGENTS.md written
    checks["no_output_agents_md"] = not os.path.exists(output_agents_path)

    # Compute reward: only include checks that depend on output artifacts and their content
    scoring_keys = [
        "combinations_md_exists",
        "combinations_has_expected_proven_entry",
        "combinations_only_expected_proven",
        "learnings_updated_resolve_expected",
        "learnings_non_proven_not_resolved",
        "weekly_report_exists",
        "weekly_report_inventory_has_skills",
        "weekly_report_promotion_count_one",
        "weekly_report_failed_count_present",
        "weekly_report_top_proven_includes_pair",
        "weekly_report_proposals_contains_jobposting",
        "weekly_report_ecosystem_health_present",
        "memory_file_exists",
        "memory_summary_mentions_promotion_and_proposals",
    ]
    # Ensure artifact-dependent checks are only True if their corresponding files exist
    # This is already enforced above, but we guard again here conceptually.

    passed = sum(1 for k in scoring_keys if checks.get(k, False))
    total = len(scoring_keys)
    reward = (passed / total) if total > 0 else 0.0
    # No-op baseline: if the agent produced nothing (no required artifacts), reward should be 0.0 automatically since most checks will be False.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()