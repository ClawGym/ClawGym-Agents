import json
import os
import re
import sys

def normalize_header(line: str) -> str:
    s = line.strip()
    i = 0
    while i < len(s) and s[i] == '#':
        i += 1
    return s[i:].strip()

def extract_sections(text: str, required_headers: list[str]) -> dict:
    lines = text.splitlines()
    header_positions = {}
    for i, line in enumerate(lines):
        nh = normalize_header(line)
        if nh in required_headers and nh not in header_positions:
            header_positions[nh] = i
    sections = {}
    sorted_headers = sorted(header_positions.items(), key=lambda x: x[1])
    # Map header to content lines between this header and the next header occurrence
    for idx, (hdr, start_line_idx) in enumerate(sorted_headers):
        # Content starts on next line
        content_start = start_line_idx + 1
        if idx + 1 < len(sorted_headers):
            next_start = sorted_headers[idx + 1][1]
        else:
            next_start = len(lines)
        content = "\n".join(lines[content_start:next_start]).strip("\n")
        sections[hdr] = content
    return sections

def count_words(text: str) -> int:
    # Count words as sequences of non-whitespace
    return len(re.findall(r"\S+", text))

def load_json_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    advice_path = os.path.join(output_dir, "advice.md")
    matrix_path = os.path.join(output_dir, "decision_matrix.json")
    financials_path = os.path.join(input_dir, "financials.json")
    context_path = os.path.join(input_dir, "context.txt")

    required_headers = [
        "Situation Summary",
        "Assumptions & Unknowns",
        "Clarifying Questions",
        "Options & Scenarios",
        "Pros & Cons",
        "Risk Assessment",
        "Recommendation",
        "90-Day Action Plan",
    ]

    checks = {
        "advice_exists": False,
        "advice_has_all_sections": False,
        "situation_summary_word_limit": False,
        "advice_includes_arr_display": False,
        "advice_includes_burn_rate_display": False,
        "advice_includes_cash_display": False,
        "advice_includes_runway_display": False,
        "advice_includes_gross_margin_display": False,
        "advice_includes_nrr_display": False,
        "advice_mentions_offer_amount": False,
        "clarifying_questions_count_ge_10": False,
        "options_section_has_A_B_C": False,
        "pros_cons_section_has_markers": False,
        "risk_section_has_6_likelihood_impact": False,
        "action_plan_has_8_steps": False,
        "matrix_exists": False,
        "matrix_valid_json": False,
        "matrix_criteria_keys_exact": False,
        "matrix_criteria_weights_sum_to_one": False,
        "matrix_options_len_ge_3": False,
        "matrix_options_scores_range_valid": False,
        "matrix_options_structure_valid": False,
        "matrix_weighted_totals_match": False,
    }

    advice_text = ""
    sections = {}
    financial_displays = {}
    # Attempt to load input financials (reference only; does not directly award credit)
    if os.path.isfile(financials_path):
        try:
            financials = load_json_file(financials_path)
            # Extract required display fields if present
            for key in ["arr_display", "burn_rate_display", "cash_display", "runway_display", "gross_margin_display", "nrr_display"]:
                if isinstance(financials, dict) and key in financials and isinstance(financials[key], str):
                    financial_displays[key] = financials[key]
        except Exception:
            financial_displays = {}

    if os.path.isfile(advice_path):
        checks["advice_exists"] = True
        try:
            advice_text = safe_read_text(advice_path)
        except Exception:
            advice_text = ""
        # Extract sections
        sections = extract_sections(advice_text, required_headers)

        # Has all required sections
        checks["advice_has_all_sections"] = all(h in sections for h in required_headers)

        # Situation Summary word limit
        if "Situation Summary" in sections:
            ss = sections["Situation Summary"]
            if count_words(ss) <= 150:
                checks["situation_summary_word_limit"] = True

        # Include financial display strings
        # Only mark True when advice_text contains the exact string value for each metric
        for key, check_name in [
            ("arr_display", "advice_includes_arr_display"),
            ("burn_rate_display", "advice_includes_burn_rate_display"),
            ("cash_display", "advice_includes_cash_display"),
            ("runway_display", "advice_includes_runway_display"),
            ("gross_margin_display", "advice_includes_gross_margin_display"),
            ("nrr_display", "advice_includes_nrr_display"),
        ]:
            if key in financial_displays:
                if financial_displays[key] in advice_text:
                    checks[check_name] = True

        # Offer amount mention (look for '12,000,000' or '$12,000,000' anywhere in advice)
        if "12,000,000" in advice_text or "$12,000,000" in advice_text:
            checks["advice_mentions_offer_amount"] = True

        # Clarifying Questions: at least 10 bullet lines starting with '- '
        if "Clarifying Questions" in sections:
            cq_lines = [ln for ln in sections["Clarifying Questions"].splitlines()]
            bullet_count = 0
            for ln in cq_lines:
                if ln.lstrip().startswith("- "):
                    bullet_count += 1
            if bullet_count >= 10:
                checks["clarifying_questions_count_ge_10"] = True

        # Options & Scenarios: lines labeled 'Option A:', 'Option B:', 'Option C:'
        if "Options & Scenarios" in sections:
            opts_text = sections["Options & Scenarios"]
            has_a = "Option A:" in opts_text
            has_b = "Option B:" in opts_text
            has_c = "Option C:" in opts_text
            if has_a and has_b and has_c:
                checks["options_section_has_A_B_C"] = True

        # Pros & Cons: contains 'Pros:' and 'Cons:' at least once each
        if "Pros & Cons" in sections:
            pc_text = sections["Pros & Cons"]
            if ("Pros:" in pc_text) and ("Cons:" in pc_text):
                checks["pros_cons_section_has_markers"] = True

        # Risk Assessment: at least 6 lines with 'Likelihood: [LMH]' and 'Impact: [LMH]'
        if "Risk Assessment" in sections:
            ra_lines = [ln for ln in sections["Risk Assessment"].splitlines() if ln.strip()]
            pattern_like = re.compile(r"Likelihood:\s*([LMH])\b")
            pattern_imp = re.compile(r"Impact:\s*([LMH])\b")
            valid_count = 0
            for ln in ra_lines:
                if pattern_like.search(ln) and pattern_imp.search(ln):
                    valid_count += 1
            if valid_count >= 6:
                checks["risk_section_has_6_likelihood_impact"] = True

        # 90-Day Action Plan: at least 8 bullet lines starting with '- '
        if "90-Day Action Plan" in sections:
            ap_lines = sections["90-Day Action Plan"].splitlines()
            ap_bullets = sum(1 for ln in ap_lines if ln.lstrip().startswith("- "))
            if ap_bullets >= 8:
                checks["action_plan_has_8_steps"] = True

    # Decision matrix checks
    matrix_data = None
    if os.path.isfile(matrix_path):
        checks["matrix_exists"] = True
        try:
            with open(matrix_path, "r", encoding="utf-8") as f:
                matrix_data = json.load(f)
            checks["matrix_valid_json"] = True
        except Exception:
            matrix_data = None

    if matrix_data is not None and isinstance(matrix_data, dict):
        # Criteria keys
        required_criteria = [
            "Strategic Fit",
            "Financial Outcome (12-month)",
            "Risk",
            "Reversibility",
            "Stakeholder Impact",
        ]
        criteria = matrix_data.get("criteria")
        options = matrix_data.get("options")
        if isinstance(criteria, dict) and set(criteria.keys()) == set(required_criteria):
            checks["matrix_criteria_keys_exact"] = True

            # Weights numeric and sum to 1.0 +/- 0.01
            try:
                weights = [float(criteria[k]) for k in required_criteria]
                if all(isinstance(criteria[k], (int, float)) for k in required_criteria):
                    total_w = sum(weights)
                    if abs(total_w - 1.0) <= 0.01:
                        checks["matrix_criteria_weights_sum_to_one"] = True
            except Exception:
                pass

        # Options array length >= 3
        if isinstance(options, list) and len(options) >= 3:
            checks["matrix_options_len_ge_3"] = True

            # Validate structure and scores range, and weighted totals
            structure_ok = True
            scores_range_ok = True
            totals_match = True

            # Get weights for total check only if criteria valid
            weight_map = {}
            if isinstance(criteria, dict):
                try:
                    for k in required_criteria:
                        weight_map[k] = float(criteria[k])
                except Exception:
                    weight_map = {}

            for opt in options:
                # Structure: name (str), scores object with all criteria keys numeric 1-5, weighted_total numeric
                if not (isinstance(opt, dict) and isinstance(opt.get("name"), str) and isinstance(opt.get("scores"), dict)):
                    structure_ok = False
                    continue
                scores = opt.get("scores")
                # Scores must include all required criteria keys
                if set(scores.keys()) != set(required_criteria):
                    structure_ok = False
                # Validate scores numeric and within 1-5
                for k in required_criteria:
                    v = scores.get(k)
                    if not isinstance(v, (int, float)):
                        scores_range_ok = False
                    else:
                        if not (1 <= float(v) <= 5):
                            scores_range_ok = False
                # weighted_total exists and numeric
                wt = opt.get("weighted_total")
                if not isinstance(wt, (int, float)):
                    structure_ok = False
                # Check total matches if we have valid weights and scores
                if weight_map and isinstance(wt, (int, float)):
                    try:
                        computed = 0.0
                        for k in required_criteria:
                            computed += float(scores[k]) * float(weight_map[k])
                        if abs(computed - float(wt)) > 0.05:
                            totals_match = False
                    except Exception:
                        totals_match = False

            if structure_ok:
                checks["matrix_options_structure_valid"] = True
            if scores_range_ok:
                checks["matrix_options_scores_range_valid"] = True
            if totals_match:
                checks["matrix_weighted_totals_match"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()