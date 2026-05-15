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

def parse_simple_yaml_map(text):
    """
    Minimal YAML key: value parser for flat maps with string values.
    Ignores comments (# ...) and blank lines. Does not support lists or nesting.
    """
    data = {}
    if not text:
        return data
    for line in text.splitlines():
        # Strip comments
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Remove inline comments, keeping value before unescaped #
        # Simple approach: split at first ' #'
        parts = line.split("#", 1)
        line = parts[0].rstrip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        # Normalize key style
        norm_key = key.lower().replace("-", "_").replace(" ", "_")
        data[norm_key] = val
    return data

def normalize_goal(s):
    s = (s or "").strip().lower()
    if "hybrid" in s or "arbitrage" in s:
        return "Hybrid"
    if "sport" in s:
        return "Sports Betting"
    if "prediction" in s or "market" in s:
        return "Prediction Markets"
    if "research" in s:
        return "Research"
    # Fallback to Research-only path
    return "Research"

def normalize_budget(s):
    s = (s or "").strip().lower()
    if s.startswith("free"):
        return "Free"
    if s.startswith("hobby"):
        return "Hobby"
    if s.startswith("pro"):
        return "Pro"
    # Unknown -> keep raw capitalized first letter if possible
    return s.capitalize() if s else ""

def normalize_level(s):
    s = (s or "").strip().lower()
    if s.startswith("beg"):
        return "Beginner"
    if s.startswith("inter"):
        return "Intermediate"
    if s.startswith("adv"):
        return "Advanced"
    return s.capitalize() if s else ""

def contains_case_insensitive(haystack, needle):
    return needle.lower() in haystack.lower()

def list_contains_substring_ci(items, sub):
    for it in items:
        if isinstance(it, str) and sub.lower() in it.lower():
            return True
    return False

def count_matches_in_list_ci(items, required_subset):
    """Return how many of the required names appear (substring, case-insensitive) in items."""
    count = 0
    for req in required_subset:
        if list_contains_substring_ci(items, req):
            count += 1
    return count

def extract_section(text, start_pattern, end_pattern_list):
    """
    Extract lines between the first line matching start_pattern (case-insensitive substring)
    and the next line matching any pattern in end_pattern_list (case-insensitive substring).
    Returns list of lines in the section (excluding the start line).
    """
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if start_pattern.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return []
    # Find end index
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        for pat in end_pattern_list:
            if pat.lower() in lines[j].lower():
                end_idx = j
                break
        if end_idx != len(lines):
            break
    return lines[start_idx + 1:end_idx]

def get_first_nonempty_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    assessment_path = os.path.join(input_dir, "assessment.yaml")
    stack_md_path = os.path.join(output_dir, "stack.md")
    stack_json_path = os.path.join(output_dir, "stack.json")

    # Allowed guide URLs
    allowed_urls = {
        "/guides/agent-betting-stack/",
        "/guides/openclaw-odds-scanner-skill/",
        "/guides/openclaw-polymarket-monitor-skill/",
        "/guides/openclaw-kalshi-tracker-skill/",
        "/guides/openclaw-arb-finder-skill/",
        "/guides/openclaw-vig-calculator-skill/",
        "/guides/openclaw-kelly-sizer-skill/",
        "/guides/openclaw-ev-calculator-skill/",
        "/guides/openclaw-odds-converter-skill/",
        "/guides/openclaw-clv-tracker-skill/",
        "/guides/openclaw-sharp-line-detector-skill/",
        "/guides/openclaw-bankroll-manager-skill/",
        "/guides/openclaw-world-cup-2026-odds-skill/",
        "/guides/prediction-market-api-reference/",
        "/guides/polymarket-api-guide/",
        "/guides/kalshi-api-guide/",
        "/guides/agent-betting-security/",
    }

    checks = {
        "has_stack_md": False,
        "has_stack_json": False,
        "yaml_parsed": False,  # informational; not scored
        "json_parsed": False,
        "json_has_required_fields": False,
        "json_goal_budget_level_match": False,
        "recommended_len_valid": False,
        "estimated_time_range": False,
        "cost_tier_valid": False,
        "hybrid_mvs_contains_core": False,
        "hybrid_recommended_includes_4": False,
        "layers_L2_has_bankroll_wallet": False,
        "guides_json_valid": False,
        "md_header_ok": False,
        "md_goal_budget_lines": False,
        "md_steps_present": False,
        "md_step3_has_two_try": False,
        "md_guides_section_and_links": False,
        "md_risk_notes_with_readonly_tradeexec": False,
    }

    # Read and parse assessment.yaml
    input_goal_norm = ""
    input_budget_norm = ""
    input_level_norm = ""
    assessment_text = read_text(assessment_path)
    if assessment_text is not None:
        parsed_yaml = parse_simple_yaml_map(assessment_text)
        if parsed_yaml:
            checks["yaml_parsed"] = True
            raw_goal = parsed_yaml.get("goal", "")
            raw_budget = parsed_yaml.get("budget", "")
            raw_level = parsed_yaml.get("technical_level", parsed_yaml.get("technicallevel", ""))
            input_goal_norm = normalize_goal(raw_goal)
            input_budget_norm = normalize_budget(raw_budget)
            input_level_norm = normalize_level(raw_level)

    # Evaluate stack.json
    json_obj = None
    if os.path.isfile(stack_json_path):
        checks["has_stack_json"] = True
        json_text = read_text(stack_json_path)
        try:
            json_obj = json.loads(json_text)
            checks["json_parsed"] = True
        except Exception:
            json_obj = None

    # Determine hybrid condition from input (only if yaml parsed)
    is_hybrid = (input_goal_norm == "Hybrid")

    # Validate JSON fields and content
    if json_obj is not None and isinstance(json_obj, dict):
        required_keys = [
            "goal", "budget", "technical_level",
            "estimated_setup_time_minutes", "cost_tier",
            "minimum_viable_stack", "recommended_skills",
            "layers_covered", "guides"
        ]
        has_all = all(k in json_obj for k in required_keys)
        types_ok = True
        if has_all:
            types_ok = (
                isinstance(json_obj.get("goal"), str) and
                isinstance(json_obj.get("budget"), str) and
                isinstance(json_obj.get("technical_level"), str) and
                isinstance(json_obj.get("estimated_setup_time_minutes"), int) and
                isinstance(json_obj.get("cost_tier"), str) and
                isinstance(json_obj.get("minimum_viable_stack"), list) and
                isinstance(json_obj.get("recommended_skills"), list) and
                isinstance(json_obj.get("layers_covered"), dict) and
                isinstance(json_obj.get("guides"), list)
            )
            lc = json_obj.get("layers_covered", {})
            types_ok = types_ok and all(k in lc for k in ["L2", "L3", "L4"]) and \
                       isinstance(lc.get("L2"), list) and isinstance(lc.get("L3"), list) and isinstance(lc.get("L4"), list)
            # guides array: each should be object with name and url
            guides_ok_shape = True
            for g in json_obj.get("guides", []):
                if not (isinstance(g, dict) and isinstance(g.get("name", ""), str) and isinstance(g.get("url", ""), str)):
                    guides_ok_shape = False
                    break
            types_ok = types_ok and guides_ok_shape

        if has_all and types_ok:
            checks["json_has_required_fields"] = True

            # Match goal/budget/technical_level with input normalized values (case-insensitive)
            if checks["yaml_parsed"]:
                goal_match = json_obj["goal"].strip().lower() == input_goal_norm.strip().lower()
                budget_match = json_obj["budget"].strip().lower() == input_budget_norm.strip().lower()
                level_match = json_obj["technical_level"].strip().lower() == input_level_norm.strip().lower()
                if goal_match and budget_match and level_match:
                    checks["json_goal_budget_level_match"] = True

            # recommended_skills length <= 7
            if isinstance(json_obj.get("recommended_skills"), list) and len(json_obj["recommended_skills"]) <= 7:
                checks["recommended_len_valid"] = True

            # estimated_setup_time_minutes in [10, 90]
            est = json_obj.get("estimated_setup_time_minutes")
            if isinstance(est, int) and 10 <= est <= 90:
                checks["estimated_time_range"] = True

            # cost_tier must be one of allowed tiers
            ct = json_obj.get("cost_tier", "")
            if isinstance(ct, str) and ct.strip().lower() in {"free", "hobby", "pro"}:
                checks["cost_tier_valid"] = True

            # Guides validation in JSON: at least 3 and all URLs from allowed set
            guides = json_obj.get("guides", [])
            guide_urls = []
            for g in guides:
                if isinstance(g, dict) and isinstance(g.get("url"), str):
                    guide_urls.append(g["url"])
            if len(guide_urls) >= 3 and all(u in allowed_urls for u in guide_urls):
                checks["guides_json_valid"] = True

            # Hybrid-specific checks (only assessed if input goal is hybrid)
            if is_hybrid:
                mvs = json_obj.get("minimum_viable_stack", [])
                if isinstance(mvs, list):
                    has_odds = list_contains_substring_ci(mvs, "odds-scanner")
                    has_poly = list_contains_substring_ci(mvs, "polymarket-monitor")
                    has_arb = list_contains_substring_ci(mvs, "arb-finder")
                    if has_odds and has_poly and has_arb:
                        checks["hybrid_mvs_contains_core"] = True

                recs = json_obj.get("recommended_skills", [])
                if isinstance(recs, list):
                    required_four_of = ["cross-market-pricer", "kalshi-tracker", "odds-converter", "kelly-sizer", "bankroll-manager", "wallet-balance-checker"]
                    if count_matches_in_list_ci(recs, required_four_of) >= 4:
                        checks["hybrid_recommended_includes_4"] = True

                # L2 contains bankroll/wallet item
                lc_L2 = json_obj.get("layers_covered", {}).get("L2", [])
                if isinstance(lc_L2, list) and (list_contains_substring_ci(lc_L2, "bankroll") or list_contains_substring_ci(lc_L2, "wallet")):
                    checks["layers_L2_has_bankroll_wallet"] = True
            else:
                # Not hybrid: mark these as N/A but True to avoid penalizing when not applicable
                checks["hybrid_mvs_contains_core"] = True
                checks["hybrid_recommended_includes_4"] = True
                checks["layers_L2_has_bankroll_wallet"] = True

    # Evaluate stack.md
    md_text = None
    if os.path.isfile(stack_md_path):
        checks["has_stack_md"] = True
        md_text = read_text(stack_md_path)

    if md_text:
        # Header check
        first_line = get_first_nonempty_line(md_text)
        if "your agent betting stack".lower() in first_line.lower():
            checks["md_header_ok"] = True

        # Goal and Budget lines
        # Accept any line containing "Goal:" and any line containing "Budget:"
        if re.search(r'(?im)^\s*.*Goal:\s*', md_text) and re.search(r'(?im)^\s*.*Budget:\s*', md_text):
            checks["md_goal_budget_lines"] = True

        # Steps present
        steps_present = all(("step {}".format(i)).lower() in md_text.lower() for i in [1, 2, 3, 4])
        if steps_present:
            checks["md_steps_present"] = True

        # Step 3 has two "Try:" prompts
        step3_section_lines = extract_section(md_text, "Step 3", ["Step 4"])
        try_count = 0
        for line in step3_section_lines:
            if "try:" in line.lower():
                try_count += 1
        if try_count >= 2:
            checks["md_step3_has_two_try"] = True

        # Relevant Guides section with at least 3 allowed URLs
        has_guides_header = "relevant guides" in md_text.lower()
        # Count distinct allowed URLs present
        present_urls = {u for u in allowed_urls if u in md_text}
        if has_guides_header and len(present_urls) >= 3:
            checks["md_guides_section_and_links"] = True

        # Risk & Notes section with "read-only" and "trade execution"
        # Find a line containing both "risk" and "note"
        lines = md_text.splitlines()
        risk_idx = None
        for i, line in enumerate(lines):
            l = line.lower()
            if "risk" in l and "note" in l:
                risk_idx = i
                break
        if risk_idx is not None:
            # Section goes until next markdown header (line starting with '#') or end
            end_idx = len(lines)
            for j in range(risk_idx + 1, len(lines)):
                if lines[j].lstrip().startswith("#"):
                    end_idx = j
                    break
            risk_section = "\n".join(lines[risk_idx+1:end_idx]).lower()
            if ("read-only" in risk_section) and ("trade execution" in risk_section):
                checks["md_risk_notes_with_readonly_tradeexec"] = True

    # Build scored checks list (exclude yaml_parsed from scoring; include hybrid checks only if applicable)
    scored_checks = [
        "has_stack_md",
        "has_stack_json",
        "json_parsed",
        "json_has_required_fields",
        "json_goal_budget_level_match",
        "recommended_len_valid",
        "estimated_time_range",
        "cost_tier_valid",
        "guides_json_valid",
        "md_header_ok",
        "md_goal_budget_lines",
        "md_steps_present",
        "md_step3_has_two_try",
        "md_guides_section_and_links",
        "md_risk_notes_with_readonly_tradeexec",
    ]
    # Hybrid-specific scoring only if hybrid
    if is_hybrid:
        scored_checks.extend([
            "hybrid_mvs_contains_core",
            "hybrid_recommended_includes_4",
            "layers_L2_has_bankroll_wallet",
        ])

    # Compute reward as average of passed scored checks; if no outputs, this yields 0
    if scored_checks:
        total = len(scored_checks)
        passed = sum(1 for k in scored_checks if checks.get(k, False))
        reward = passed / total if total > 0 else 0.0
    else:
        reward = 0.0

    # Ensure reward is 0.0 if both outputs missing or empty
    if not checks["has_stack_md"] and not checks["has_stack_json"]:
        reward = 0.0

    # Print result JSON (single line)
    out = {"reward": float(max(0.0, min(1.0, reward)))}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()