import json
import os
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return (isinstance(x, int) and not isinstance(x, bool)) or isinstance(x, float)

def get_first_non_empty_line(lines):
    for ln in lines:
        if ln.strip():
            return ln.rstrip("\n")
    return ""

def find_line_index(lines, target):
    for i, ln in enumerate(lines):
        if ln.strip() == target:
            return i
    return -1

def find_section_start(lines, section_name):
    # Section identified by a line containing the exact section_name (case-sensitive)
    for i, ln in enumerate(lines):
        if section_name in ln:
            return i
    return -1

def count_bullets_in_section(lines, start_idx):
    if start_idx < 0:
        return 0
    # Search until next major section heading or end
    end_idx = len(lines)
    headings = ["Executive Summary", "Per-Document Analysis", "Comparison", "Limitations", "Recommendations", "Appendix"]
    for i in range(start_idx + 1, len(lines)):
        for h in headings:
            if h in lines[i] and i > start_idx:
                end_idx = i
                break
        if end_idx != len(lines):
            break
    count = 0
    for ln in lines[start_idx+1:end_idx]:
        s = ln.lstrip()
        if s.startswith("-") or s.startswith("*"):
            count += 1
    return count

def section_quote_check(lines, start_idx, next_start_idx):
    if start_idx < 0:
        return False
    end_idx = next_start_idx if next_start_idx is not None and next_start_idx > start_idx else len(lines)
    # Count double quote characters within the section; require at least a pair
    quote_count = 0
    for ln in lines[start_idx+1:end_idx]:
        quote_count += ln.count('"')
    return quote_count >= 2

def risk_level_from_score(norm):
    if norm < 5:
        return "LOW"
    elif norm < 15:
        return "MODERATE"
    else:
        return "HIGH"

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # existence
        "has_analysis_json": False,
        "has_report_md": False,
        # analysis.json structure checks
        "analysis_json_is_object": False,
        "analysis_json_has_exact_five_keys": False,
        "analysis_entries_have_required_fields_and_types": False,
        "analysis_normalized_scores_in_range": False,
        "analysis_risk_levels_consistent": False,
        "analysis_flags_valid": False,
        # report.md structure checks
        "report_title_line_valid": False,
        "report_has_executive_summary": False,
        "report_ranking_line_valid": False,
        "report_has_per_document_analysis": False,
        "report_has_required_subheadings": False,
        "report_quotes_customer_email": False,
        "report_quotes_social_post": False,
        "report_quotes_internal_memo": False,
        "report_quotes_press_release": False,
        "report_quotes_scam_sms": False,
        "report_has_comparison_section": False,
        "report_has_limitations_section": False,
        "report_limitations_has_required_phrase": False,
        "report_has_recommendations_section": False,
        "report_recommendations_has_at_least_five_bullets": False,
        "report_has_appendix_word": False,
        "report_has_detection_criteria_phrase": False,
        # cross-artifact consistency
        "report_subheadings_match_analysis_keys": False,
    }

    allowed_files = [
        "customer_email.txt",
        "social_post.txt",
        "internal_memo.txt",
        "press_release.txt",
        "scam_sms.txt",
    ]
    allowed_flags = {
        "urgency",
        "authority_claims",
        "social_proof",
        "fear_uncertainty",
        "grandiosity",
        "dominance_assertions",
        "us_vs_them",
        "emotional_manipulation",
    }

    # Paths
    analysis_path = os.path.join(output_dir, "analysis.json")
    report_path = os.path.join(output_dir, "report.md")

    # Existence checks
    if os.path.isfile(analysis_path):
        checks["has_analysis_json"] = True
    if os.path.isfile(report_path):
        checks["has_report_md"] = True

    # Parse and validate analysis.json
    analysis_obj = None
    if checks["has_analysis_json"]:
        analysis_obj = parse_json_file(analysis_path)
        if isinstance(analysis_obj, dict):
            checks["analysis_json_is_object"] = True

            keys = list(analysis_obj.keys())
            if set(keys) == set(allowed_files) and len(keys) == 5:
                checks["analysis_json_has_exact_five_keys"] = True

                # Validate entries
                fields_ok = True
                norm_range_ok = True
                risk_consistent_ok = True
                flags_ok = True

                for k in allowed_files:
                    entry = analysis_obj.get(k)
                    if not isinstance(entry, dict):
                        fields_ok = False
                        risk_consistent_ok = False
                        norm_range_ok = False
                        flags_ok = False
                        break

                    required_fields = ["word_count", "raw_score", "normalized_score", "risk_level", "flags"]
                    for rf in required_fields:
                        if rf not in entry:
                            fields_ok = False

                    # Type checks and ranges
                    wc = entry.get("word_count")
                    rs = entry.get("raw_score")
                    ns = entry.get("normalized_score")
                    rl = entry.get("risk_level")
                    fl = entry.get("flags")

                    if not (isinstance(wc, int) and not isinstance(wc, bool) and wc >= 1):
                        fields_ok = False
                    if not is_number(rs):
                        fields_ok = False
                    if not is_number(ns):
                        fields_ok = False
                    else:
                        if not (0 <= float(ns) <= 100):
                            norm_range_ok = False

                    if not (isinstance(rl, str) and rl in {"LOW", "MODERATE", "HIGH"}):
                        fields_ok = False
                    else:
                        # Consistency check
                        expected_rl = risk_level_from_score(float(ns)) if is_number(ns) else None
                        if expected_rl is None or rl != expected_rl:
                            risk_consistent_ok = False

                    if not isinstance(fl, list):
                        fields_ok = False
                    else:
                        for item in fl:
                            if not isinstance(item, str) or item not in allowed_flags:
                                flags_ok = False

                if fields_ok:
                    checks["analysis_entries_have_required_fields_and_types"] = True
                if norm_range_ok:
                    checks["analysis_normalized_scores_in_range"] = True
                if risk_consistent_ok:
                    checks["analysis_risk_levels_consistent"] = True
                if flags_ok:
                    checks["analysis_flags_valid"] = True

    # Validate report.md
    report_text = None
    report_lines = []
    if checks["has_report_md"]:
        report_text = read_text_file(report_path)
        if isinstance(report_text, str):
            report_lines = report_text.splitlines()

            # Title line must be exactly "Manipulation Risk Review" on the first non-empty line
            first_line = get_first_non_empty_line(report_lines)
            if first_line.strip() == "Manipulation Risk Review":
                checks["report_title_line_valid"] = True

            # Required section headings
            if find_section_start(report_lines, "Executive Summary") >= 0:
                checks["report_has_executive_summary"] = True

            exec_idx = find_section_start(report_lines, "Executive Summary")
            ranking_valid = False
            if exec_idx >= 0:
                # Search for a line starting with required prefix
                prefix = "Ranking (most to least risky):"
                for i in range(exec_idx, min(exec_idx + 100, len(report_lines))):
                    ln = report_lines[i].strip()
                    if ln.startswith(prefix):
                        content = ln[len(prefix):].strip()
                        # Check presence of all filenames and at least four '>' separators
                        gt_count = content.count(">")
                        present_all = all(name in content for name in allowed_files)
                        if gt_count >= 4 and present_all:
                            ranking_valid = True
                        break
            if ranking_valid:
                checks["report_ranking_line_valid"] = True

            if find_section_start(report_lines, "Per-Document Analysis") >= 0:
                checks["report_has_per_document_analysis"] = True

            # Required exact subheadings
            subheads = {
                "customer_email.txt": "### customer_email.txt",
                "social_post.txt": "### social_post.txt",
                "internal_memo.txt": "### internal_memo.txt",
                "press_release.txt": "### press_release.txt",
                "scam_sms.txt": "### scam_sms.txt",
            }
            subhead_indices = {}
            all_subheads_present = True
            for key, heading in subheads.items():
                idx = find_line_index(report_lines, heading)
                if idx < 0:
                    all_subheads_present = False
                subhead_indices[key] = idx
            if all_subheads_present:
                checks["report_has_required_subheadings"] = True

            # Quotes presence beneath each subheading (at least one quoted phrase → at least a pair of double quotes)
            # Determine next subheading index for each
            order_keys = ["customer_email.txt", "social_post.txt", "internal_memo.txt", "press_release.txt", "scam_sms.txt"]
            for i, key in enumerate(order_keys):
                start_idx = subhead_indices.get(key, -1)
                # next start
                next_idx = None
                for j in range(i+1, len(order_keys)):
                    ni = subhead_indices.get(order_keys[j], -1)
                    if ni != -1:
                        next_idx = ni
                        break
                has_quotes = section_quote_check(report_lines, start_idx, next_idx)
                if key == "customer_email.txt" and has_quotes:
                    checks["report_quotes_customer_email"] = True
                if key == "social_post.txt" and has_quotes:
                    checks["report_quotes_social_post"] = True
                if key == "internal_memo.txt" and has_quotes:
                    checks["report_quotes_internal_memo"] = True
                if key == "press_release.txt" and has_quotes:
                    checks["report_quotes_press_release"] = True
                if key == "scam_sms.txt" and has_quotes:
                    checks["report_quotes_scam_sms"] = True

            if find_section_start(report_lines, "Comparison") >= 0:
                checks["report_has_comparison_section"] = True

            if find_section_start(report_lines, "Limitations") >= 0:
                checks["report_has_limitations_section"] = True

            # Limitations required phrase
            lt_idx = find_section_start(report_lines, "Limitations")
            limitations_phrase_ok = False
            if lt_idx >= 0:
                section_text = "\n".join(report_lines[lt_idx: lt_idx + 200])
                lower = section_text.lower()
                if ("patterns, not intent" in lower) or ("not a truth detector" in lower):
                    limitations_phrase_ok = True
            if limitations_phrase_ok:
                checks["report_limitations_has_required_phrase"] = True

            if find_section_start(report_lines, "Recommendations") >= 0:
                checks["report_has_recommendations_section"] = True
                rec_idx = find_section_start(report_lines, "Recommendations")
                bullet_count = count_bullets_in_section(report_lines, rec_idx)
                if bullet_count >= 5:
                    checks["report_recommendations_has_at_least_five_bullets"] = True

            # Appendix and Detection Criteria presence
            if find_section_start(report_lines, "Appendix") >= 0 or any("Appendix" in ln for ln in report_lines):
                checks["report_has_appendix_word"] = True
            if any("Detection Criteria" in ln for ln in report_lines):
                checks["report_has_detection_criteria_phrase"] = True

    # Cross-artifact consistency: subheadings match analysis keys
    if checks["analysis_json_is_object"] and checks["report_has_required_subheadings"]:
        analysis_keys = set(analysis_obj.keys()) if isinstance(analysis_obj, dict) else set()
        subheading_keys = set([
            "customer_email.txt",
            "social_post.txt",
            "internal_memo.txt",
            "press_release.txt",
            "scam_sms.txt",
        ])
        checks["report_subheadings_match_analysis_keys"] = (analysis_keys == subheading_keys)

    # Compute reward
    # If either required artifact is missing -> reward 0.0
    if not (checks["has_analysis_json"] and checks["has_report_md"]):
        reward = 0.0
    else:
        total_checks = len(checks)
        passed_checks = sum(1 for v in checks.values() if v)
        # Scale reward to [0,1]
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()