import json
import os
import sys
import re

def is_number(x):
    if isinstance(x, bool):
        return False
    return isinstance(x, (int, float))

def in_range_1_10(x):
    return is_number(x) and 1 <= float(x) <= 10

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def extract_report_recommendation(report_text):
    # Find line starting with "Recommendation:"
    for line in report_text.splitlines():
        if line.strip().startswith("Recommendation:"):
            val = line.split("Recommendation:", 1)[1].strip()
            return val
    return None

def count_sources_bullets(report_text):
    lines = report_text.splitlines()
    # Find the index of "Research Sources" section
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Research Sources" or line.strip().startswith("## Research Sources"):
            header_idx = i
            break
    if header_idx is None:
        return 0
    count = 0
    # Count bullet lines after header that reference input/
    for j in range(header_idx + 1, len(lines)):
        ln = lines[j]
        # Stop if a new top-level or second-level header starts
        if ln.strip().startswith("# " ) or ln.strip().startswith("## "):
            break
        s = ln.lstrip()
        if (s.startswith("- ") or s.startswith("* ")) and ("input/" in s):
            count += 1
    return count

def line_starts_with(text, prefix):
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return None

def has_all_dimension_names(text):
    required = [
        "Security Posture",
        "Data Handling",
        "Compliance",
        "Financial Stability",
        "Operational Resilience",
        "Contractual Terms",
    ]
    return all(name in text for name in required)

def check_summary_weights(weights_obj, sensitivity):
    # Required keys
    keys_required = [
        "security_posture",
        "data_handling",
        "compliance",
        "financial_stability",
        "operational_resilience",
        "contractual_terms",
    ]
    # Verify keys and numeric
    if set(weights_obj.keys()) != set(keys_required):
        return False
    for k in keys_required:
        if not is_number(weights_obj.get(k, None)):
            return False
    sp = weights_obj["security_posture"]
    dh = weights_obj["data_handling"]
    comp = weights_obj["compliance"]
    fin = weights_obj["financial_stability"]
    opr = weights_obj["operational_resilience"]
    ct = weights_obj["contractual_terms"]

    if sensitivity == "high":
        return sp == 3 and dh == 3 and comp == 2 and fin == 1 and opr == 1 and ct == 1
    elif sensitivity == "critical":
        return sp == 4 and dh == 4 and comp == 3 and fin == 2 and opr == 1 and ct == 1
    elif sensitivity in ("low", "medium"):
        # Equal weighting for all six (not necessarily 1, but all equal)
        vals = [sp, dh, comp, fin, opr, ct]
        return all(v == vals[0] for v in vals)
    else:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Existence and parse checks
        "has_risk_report_md": False,
        "has_summary_json_file": False,
        "summary_json_parseable": False,

        # summary.json content checks
        "summary_vendor_product_valid": False,
        "summary_data_sensitivity_valid": False,
        "summary_dimension_scores_valid": False,
        "summary_dimension_weights_valid": False,
        "summary_overall_score_valid": False,
        "summary_risk_rating_valid": False,
        "summary_recommendation_valid": False,
        "summary_critical_findings_valid": False,
        "summary_mitigation_requirements_valid": False,
        "summary_sources_valid": False,

        # risk_report.md structure checks
        "report_title_valid": False,
        "report_overall_line_valid": False,
        "report_dimension_scores_section_present": False,
        "report_all_dimension_names_present": False,
        "report_recommendation_line_valid": False,
        "report_sources_section_valid": False,
        "report_mitigation_section_if_required": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "risk_report.md")
    summary_path = os.path.join(output_dir, "summary.json")

    # Check existence
    if os.path.isfile(report_path):
        checks["has_risk_report_md"] = True
        report_text = read_text(report_path) or ""
    else:
        report_text = ""

    if os.path.isfile(summary_path):
        checks["has_summary_json_file"] = True
        summary_obj = load_json(summary_path)
        if isinstance(summary_obj, dict):
            checks["summary_json_parseable"] = True
        else:
            summary_obj = None
    else:
        summary_obj = None

    # summary.json validations
    if summary_obj is not None:
        # vendor_name and product_name
        vendor_name = summary_obj.get("vendor_name")
        product_name = summary_obj.get("product_name")
        if isinstance(vendor_name, str) and vendor_name.strip() and isinstance(product_name, str) and product_name.strip():
            checks["summary_vendor_product_valid"] = True

        # data_sensitivity
        data_sensitivity = summary_obj.get("data_sensitivity")
        if data_sensitivity in ("low", "medium", "high", "critical"):
            checks["summary_data_sensitivity_valid"] = True

        # dimension_scores
        dim_scores = summary_obj.get("dimension_scores")
        required_dim_keys = {
            "security_posture",
            "data_handling",
            "compliance",
            "financial_stability",
            "operational_resilience",
            "contractual_terms",
        }
        dim_scores_ok = False
        if isinstance(dim_scores, dict) and set(dim_scores.keys()) == required_dim_keys:
            values_ok = all(in_range_1_10(dim_scores[k]) for k in required_dim_keys)
            if values_ok:
                dim_scores_ok = True
        if dim_scores_ok:
            checks["summary_dimension_scores_valid"] = True

        # dimension_weights
        dim_weights = summary_obj.get("dimension_weights")
        weights_ok = False
        if isinstance(dim_weights, dict) and data_sensitivity in ("low", "medium", "high", "critical"):
            weights_ok = check_summary_weights(dim_weights, data_sensitivity)
        if weights_ok:
            checks["summary_dimension_weights_valid"] = True

        # overall_score
        overall_score = summary_obj.get("overall_score")
        if in_range_1_10(overall_score):
            checks["summary_overall_score_valid"] = True

        # risk_rating
        risk_rating = summary_obj.get("risk_rating")
        if risk_rating in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            checks["summary_risk_rating_valid"] = True

        # recommendation
        recommendation = summary_obj.get("recommendation")
        allowed_recs = ("APPROVE", "APPROVE WITH CONDITIONS", "REJECT")
        if recommendation in allowed_recs:
            checks["summary_recommendation_valid"] = True

        # critical_findings array, length >=2 if risk HIGH/CRITICAL
        crit_findings = summary_obj.get("critical_findings")
        cf_ok = False
        if isinstance(crit_findings, list):
            if risk_rating in ("HIGH", "CRITICAL"):
                cf_ok = len(crit_findings) >= 2
            else:
                cf_ok = True
        if cf_ok:
            checks["summary_critical_findings_valid"] = True

        # mitigation_requirements array; if APPROVE WITH CONDITIONS then len >=1
        mitigs = summary_obj.get("mitigation_requirements")
        mr_ok = False
        if isinstance(mitigs, list):
            if recommendation == "APPROVE WITH CONDITIONS":
                mr_ok = len(mitigs) >= 1
            else:
                mr_ok = True
        if mr_ok:
            checks["summary_mitigation_requirements_valid"] = True

        # sources array length >=2 and each contains "input/"
        sources = summary_obj.get("sources")
        src_ok = False
        if isinstance(sources, list) and len(sources) >= 2:
            src_ok = all(isinstance(s, str) and ("input/" in s) for s in sources)
        if src_ok:
            checks["summary_sources_valid"] = True

    # risk_report.md structure validations
    if report_text:
        # Title line
        title_line = line_starts_with(report_text, "# Vendor Risk Assessment:")
        if title_line:
            # Ensure vendor name is present after colon
            after = title_line.split(":", 1)[1].strip() if ":" in title_line else ""
            if len(after) > 0:
                checks["report_title_valid"] = True

        # Overall Risk Score line: includes /10 and a risk word
        overall_line = line_starts_with(report_text, "Overall Risk Score:")
        if overall_line and "/10" in overall_line and any(w in overall_line for w in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]):
            checks["report_overall_line_valid"] = True

        # Dimension Scores section presence
        if "Dimension Scores" in report_text:
            checks["report_dimension_scores_section_present"] = True

        # All six dimension names present somewhere
        if has_all_dimension_names(report_text):
            checks["report_all_dimension_names_present"] = True

        # Recommendation line valid
        rec_line = None
        for line in report_text.splitlines():
            if line.strip().startswith("Recommendation:"):
                rec_line = line
                break
        if rec_line is not None:
            rec_val = rec_line.split("Recommendation:", 1)[1].strip()
            if rec_val in ("APPROVE", "APPROVE WITH CONDITIONS", "REJECT"):
                checks["report_recommendation_line_valid"] = True

        # Research Sources section with at least two bullet lines referencing input/
        sources_count = count_sources_bullets(report_text)
        if sources_count >= 2:
            checks["report_sources_section_valid"] = True

        # If report recommendation is "APPROVE WITH CONDITIONS", ensure "Mitigation Requirements" section exists
        report_rec = extract_report_recommendation(report_text)
        if report_rec == "APPROVE WITH CONDITIONS":
            if "Mitigation Requirements" in report_text:
                checks["report_mitigation_section_if_required"] = True
        else:
            # If not required, consider this check as passed only when not required? The requirement is conditional; if not required, we'll treat it as True to avoid penalizing.
            checks["report_mitigation_section_if_required"] = True

    # Compute reward as average of checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure reward is 0.0 if no outputs created (baseline no-op)
    if not checks["has_risk_report_md"] and not checks["has_summary_json_file"]:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()