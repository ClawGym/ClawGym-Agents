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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_indent(line):
    return len(line) - len(line.lstrip(" "))

def find_block(lines, start_idx):
    # Given a list of lines and the index of a starting key line, return (start_idx, end_idx_exclusive) of its indented block
    base_indent = get_indent(lines[start_idx])
    end_idx = start_idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        if line.strip() == "":
            end_idx += 1
            continue
        if get_indent(line) <= base_indent and not line.lstrip().startswith(("#", "- ")):
            break
        end_idx += 1
    return start_idx, end_idx

def find_line_indices(lines, pattern):
    # returns list of indices where regex pattern matches the entire line (stripped of leading '#' and spaces for headings)
    indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        indices.append(i) if re.search(pattern, stripped) else None
    return indices

def normalize_heading_line(line):
    s = line.strip()
    s = re.sub(r"^#+\s*", "", s)
    return s.strip()

def find_heading_indices(lines, headings):
    # Returns a dict heading -> line index if found as a heading (line equals heading after removing markdown #'s), else -1
    result = {}
    for h in headings:
        idx = -1
        for i, line in enumerate(lines):
            if normalize_heading_line(line) == h:
                idx = i
                break
        result[h] = idx
    return result

def extract_section_text(lines, heading_indices, heading):
    # Extract text between given heading and the next heading (by line index order)
    start_idx = heading_indices.get(heading, -1)
    if start_idx == -1:
        return ""
    # find the next heading that appears after start_idx
    subsequent_indices = [idx for h, idx in heading_indices.items() if idx != -1 and idx > start_idx]
    end_idx = min(subsequent_indices) if subsequent_indices else len(lines)
    # Exclude the heading line itself
    content_lines = lines[start_idx + 1:end_idx]
    return "\n".join(content_lines)

def check_success_metrics(yaml_text):
    # Find the "success_metrics:" line, then count following "- " lines containing at least one digit
    lines = yaml_text.splitlines()
    success_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*success_metrics\s*:\s*", line):
            success_idx = i
            break
    if success_idx == -1:
        return False
    count_with_digits = 0
    for j in range(success_idx + 1, len(lines)):
        l = lines[j]
        # Stop if we hit a non-list item with indent <= success_metrics indent
        if l.strip() == "":
            continue
        if not re.match(r"^\s*-\s+", l):
            # end of list
            # But allow continued lists until next top-level key; conservative stop
            if get_indent(l) <= get_indent(lines[success_idx]):
                break
            else:
                continue
        if re.search(r"\d", l):
            count_with_digits += 1
    return count_with_digits >= 3

def extract_qualification_info(yaml_text):
    # Returns (scores_ok, total_ok, recommendation_ok)
    # scores_ok: each of budget, authority, need, timeline, competition, champion has a score 0-3
    # total_ok: total between 0 and 18 inclusive
    # recommendation_ok: recommendation: non-empty exists anywhere in doc
    lines = yaml_text.splitlines()
    q_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*qualification\s*:\s*$", line):
            q_idx = i
            break
    if q_idx == -1:
        return (False, False, False)

    # Determine block of qualification
    _, end_idx = find_block(lines, q_idx)
    q_lines = lines[q_idx:end_idx]
    keys = ["budget", "authority", "need", "timeline", "competition", "champion"]
    found_scores = {}
    for key in keys:
        # Find the line for this key within qualification block
        key_line_idx = -1
        for i, l in enumerate(q_lines):
            if re.match(r"^\s*{}\s*:\s*$".format(re.escape(key)), l):
                key_line_idx = i
                break
        if key_line_idx == -1:
            found_scores[key] = None
            continue
        # search the following few lines for score:
        score_val = None
        for j in range(key_line_idx + 1, min(key_line_idx + 6, len(q_lines))):
            m = re.search(r"\bscore\s*:\s*([0-9]+)\b", q_lines[j])
            if m:
                try:
                    score_val = int(m.group(1))
                except Exception:
                    score_val = None
                break
        found_scores[key] = score_val

    scores_ok = all(isinstance(found_scores[k], int) and 0 <= found_scores[k] <= 3 for k in keys)

    # total within qualification block
    total_ok = False
    total_val = None
    for l in q_lines:
        m = re.search(r"\btotal\s*:\s*([0-9]+)\b", l)
        if m:
            try:
                total_val = int(m.group(1))
                if 0 <= total_val <= 18:
                    total_ok = True
            except Exception:
                pass
            break

    # recommendation anywhere in file (non-empty on same line)
    recommendation_ok = False
    rec_match = re.search(r"^\s*recommendation\s*:\s*(.+)\s*$", yaml_text, flags=re.MULTILINE)
    if rec_match:
        if rec_match.group(1).strip() != "":
            recommendation_ok = True

    return (scores_ok, total_ok, recommendation_ok)

def pricing_price_rules_valid(pricing):
    try:
        good = pricing["good"]["price"]
        better = pricing["better"]["price"]
        best = pricing["best"]["price"]
        # Prices numeric and integer-like
        def is_int_like(x):
            if isinstance(x, int):
                return True
            if isinstance(x, float) and abs(x - int(x)) < 1e-9:
                return True
            return False
        if not (is_int_like(good) and is_int_like(better) and is_int_like(best)):
            return False
        good = int(good)
        better = int(better)
        best = int(best)
        # Order
        if not (good < better < best):
            return False
        # Ratios
        if not (1.5 <= (better / good) <= 2.5):
            return False
        if not (2.0 <= (best / good) <= 4.0):
            return False
        # Round ending with 0 or 5
        if not (str(good)[-1] in ("0", "5") and str(better)[-1] in ("0", "5") and str(best)[-1] in ("0", "5")):
            return False
        return True
    except Exception:
        return False

def pricing_structure_valid(pricing):
    # Exactly three top-level keys: good, better, best
    if not isinstance(pricing, dict):
        return False
    if set(pricing.keys()) != {"good", "better", "best"}:
        return False
    required_keys = ["name", "price", "description", "includes", "excludes", "timeline", "best_for"]
    # better must include "recommended": true
    try:
        for tier in ["good", "better", "best"]:
            tier_obj = pricing[tier]
            if not isinstance(tier_obj, dict):
                return False
            for k in required_keys:
                if k not in tier_obj:
                    return False
            # includes/excludes arrays of strings
            if not (isinstance(tier_obj["includes"], list) and all(isinstance(x, str) for x in tier_obj["includes"])):
                return False
            if not (isinstance(tier_obj["excludes"], list) and all(isinstance(x, str) for x in tier_obj["excludes"])):
                return False
            # types
            if not isinstance(tier_obj["name"], str):
                return False
            if not isinstance(tier_obj["description"], str):
                return False
            if not isinstance(tier_obj["timeline"], str):
                return False
            if not isinstance(tier_obj["best_for"], str):
                return False
            # price number
            if not (isinstance(tier_obj["price"], (int, float))):
                return False
        # Check recommended true in better
        if "recommended" not in pricing["better"] or pricing["better"]["recommended"] is not True:
            return False
        return True
    except Exception:
        return False

def internal_floor_valid(internal_floor):
    # Keys: hours, blended_rate, materials, buffer, floor_price (numbers)
    try:
        keys = ["hours", "blended_rate", "materials", "buffer", "floor_price"]
        if set(internal_floor.keys()) != set(keys):
            return False
        vals = {}
        for k in keys:
            v = internal_floor[k]
            if not isinstance(v, (int, float)):
                return False
            vals[k] = float(v)
        calc = vals["hours"] * vals["blended_rate"] + vals["materials"] + vals["buffer"]
        return abs(calc - vals["floor_price"]) <= 0.5
    except Exception:
        return False

def proposal_headings_order_valid(text):
    lines = text.splitlines()
    required_order = [
        "Executive Summary",
        "Understanding Your Situation",
        "Proposed Solution",
        "Proof & Credibility",
        "Project Plan & Timeline",
        "Investment",
        "Next Steps & Terms",
    ]
    indices = find_heading_indices(lines, required_order)
    # All must be found
    if any(indices[h] == -1 for h in required_order):
        return (False, {}, lines)
    # In order
    prev = -1
    for h in required_order:
        idx = indices[h]
        if idx <= prev:
            return (False, indices, lines)
        prev = idx
    return (True, indices, lines)

def section_contains(text, heading_indices, lines, heading, must_have_substrings):
    section = extract_section_text(lines, heading_indices, heading)
    lower = section.lower()
    for s in must_have_substrings:
        if s == "$":
            if "$" not in section:
                return False
        else:
            if s.lower() not in lower:
                return False
    return True

def followup_has_all_days(text):
    lower = text.lower()
    needed = ["day_0:", "day_2:", "day_5:", "day_8:", "day_14:", "day_21:", "day_30:"]
    return all(x in lower for x in needed)

def quality_scores_valid_and_total(obj):
    # Must contain integer scores for 10 dimensions and total equals sum and >=70
    dims = [
        "relevance",
        "clarity",
        "proof",
        "value_framing",
        "specificity",
        "objection_handling",
        "visual_quality",
        "call_to_action",
        "risk_reduction",
        "competitive_edge",
    ]
    try:
        if not isinstance(obj, dict):
            return False
        for d in dims:
            if d not in obj:
                return False
            if not isinstance(obj[d], int):
                return False
            if not (0 <= obj[d] <= 10):
                return False
        if "total" not in obj or not isinstance(obj["total"], int):
            return False
        s = sum(obj[d] for d in dims)
        if obj["total"] != s:
            return False
        if obj["total"] < 70:
            return False
        return True
    except Exception:
        return False

def discovery_has_basic_keys(yaml_text):
    # Check presence of key paths as simple regex matches
    needed_patterns = [
        r"^\s*discovery\s*:\s*$",
        r"^\s*client\s*:\s*$",
        r"^\s*company\s*:\s*",
        r"^\s*situation\s*:\s*$",
        r"^\s*current_state\s*:\s*",
        r"^\s*desired_outcome\s*:\s*$",
        r"^\s*success_metrics\s*:\s*",
        r"^\s*decision_process\s*:\s*$",
        r"^\s*timeline\s*:\s*",
        r"^\s*budget_range\s*:\s*",
        r"^\s*value_drivers\s*:\s*$",
    ]
    for pat in needed_patterns:
        if not re.search(pat, yaml_text, flags=re.MULTILINE):
            return False
    return True

def proposal_plan_mentions_client(lines, heading_indices):
    section = extract_section_text(lines, heading_indices, "Project Plan & Timeline")
    s = section.lower()
    return ("client responsibilities" in s) or ("client" in s)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "exists_discovery_yaml": False,
        "discovery_has_basic_keys": False,
        "discovery_success_metrics_3_with_numbers": False,
        "qualification_scores_valid": False,
        "qualification_total_and_recommendation_present": False,

        "exists_pricing_json": False,
        "pricing_structure_valid": False,
        "pricing_price_rules_valid": False,

        "exists_internal_floor_json": False,
        "internal_floor_calc_valid": False,
        "good_above_floor": False,

        "exists_proposal_md": False,
        "proposal_headings_order_valid": False,
        "proposal_investment_contains_roi_and_dollar": False,
        "proposal_next_steps_has_valid_until": False,
        "proposal_plan_mentions_client_responsibilities": False,

        "exists_followup_md": False,
        "followup_has_all_days": False,

        "exists_quality_score_json": False,
        "quality_scores_valid_and_total": False,
    }

    # Paths
    discovery_path = os.path.join(output_dir, "discovery.yaml")
    pricing_path = os.path.join(output_dir, "pricing.json")
    proposal_path = os.path.join(output_dir, "proposal.md")
    followup_path = os.path.join(output_dir, "followup.md")
    quality_path = os.path.join(output_dir, "quality_score.json")
    internal_floor_path = os.path.join(output_dir, "internal_floor.json")

    # discovery.yaml
    discovery_text = read_text(discovery_path)
    if discovery_text is not None:
        checks["exists_discovery_yaml"] = True
        if discovery_has_basic_keys(discovery_text):
            checks["discovery_has_basic_keys"] = True
        if check_success_metrics(discovery_text):
            checks["discovery_success_metrics_3_with_numbers"] = True
        scores_ok, total_ok, recommendation_ok = extract_qualification_info(discovery_text)
        if scores_ok:
            checks["qualification_scores_valid"] = True
        if total_ok and recommendation_ok:
            checks["qualification_total_and_recommendation_present"] = True

    # pricing.json
    pricing_obj = read_json(pricing_path)
    if pricing_obj is not None:
        checks["exists_pricing_json"] = True
        if pricing_structure_valid(pricing_obj):
            checks["pricing_structure_valid"] = True
        if pricing_price_rules_valid(pricing_obj):
            checks["pricing_price_rules_valid"] = True

    # internal_floor.json
    internal_floor_obj = read_json(internal_floor_path)
    if internal_floor_obj is not None:
        checks["exists_internal_floor_json"] = True
        if internal_floor_valid(internal_floor_obj):
            checks["internal_floor_calc_valid"] = True
        # good >= floor
        if pricing_obj is not None and "good" in pricing_obj and "price" in pricing_obj["good"] and "floor_price" in (internal_floor_obj or {}):
            try:
                good_price = pricing_obj["good"]["price"]
                if isinstance(good_price, (int, float)):
                    good_price = float(good_price)
                    floor_price = float(internal_floor_obj["floor_price"])
                    if good_price >= floor_price:
                        checks["good_above_floor"] = True
            except Exception:
                pass

    # proposal.md
    proposal_text = read_text(proposal_path)
    if proposal_text is not None:
        checks["exists_proposal_md"] = True
        valid_order, heading_indices, prop_lines = proposal_headings_order_valid(proposal_text)
        if valid_order:
            checks["proposal_headings_order_valid"] = True
            # Investment section contains ROI or return and $ char
            investment_ok = section_contains(
                proposal_text,
                heading_indices,
                prop_lines,
                "Investment",
                ["ROI or return token placeholder"]  # We will handle combined logic below
            )
            # The above is a placeholder; implement proper check:
            inv_section = extract_section_text(prop_lines, heading_indices, "Investment")
            inv_lower = inv_section.lower()
            has_roi_or_return = ("roi" in inv_lower) or ("return" in inv_lower)
            has_dollar = "$" in inv_section
            if has_roi_or_return and has_dollar:
                checks["proposal_investment_contains_roi_and_dollar"] = True
            # Next Steps & Terms contains "valid until"
            next_steps_section = extract_section_text(prop_lines, heading_indices, "Next Steps & Terms")
            if "valid until" in next_steps_section.lower():
                checks["proposal_next_steps_has_valid_until"] = True
            # Project Plan & Timeline mentions client responsibilities or client
            if proposal_plan_mentions_client(prop_lines, heading_indices):
                checks["proposal_plan_mentions_client_responsibilities"] = True

    # followup.md
    followup_text = read_text(followup_path)
    if followup_text is not None:
        checks["exists_followup_md"] = True
        if followup_has_all_days(followup_text):
            checks["followup_has_all_days"] = True

    # quality_score.json
    quality_obj = read_json(quality_path)
    if quality_obj is not None:
        checks["exists_quality_score_json"] = True
        if quality_scores_valid_and_total(quality_obj):
            checks["quality_scores_valid_and_total"] = True

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    any_required_file_exists = any([
        checks["exists_discovery_yaml"],
        checks["exists_pricing_json"],
        checks["exists_internal_floor_json"],
        checks["exists_proposal_md"],
        checks["exists_followup_md"],
        checks["exists_quality_score_json"],
    ])
    if not any_required_file_exists:
        reward = 0.0
    else:
        reward = passed / total_checks
        # clamp
        reward = max(0.0, min(1.0, reward))

    # Print exactly one JSON object as last non-empty line
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()