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

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def file_nonempty(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def find_section_bullets(markdown_text, section_title):
    # Find section by exact "### <title>" line and count bullet lines until next heading starting with '#'
    lines = markdown_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"### {section_title}":
            start_idx = i + 1
            break
    if start_idx is None:
        return 0
    bullets = 0
    for j in range(start_idx, len(lines)):
        line = lines[j].rstrip()
        if line.startswith("#"):  # next heading encountered
            break
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets += 1
    return bullets

def has_table_row(markdown_text):
    for line in markdown_text.splitlines():
        if line.count("|") >= 2:
            return True
    return False

def compute_overall(dimension_scores, weights):
    # Scores are 1-10; overall out of 100
    weighted_sum = 0.0
    weight_cap_sum = 0.0
    for k, score in dimension_scores.items():
        w = weights.get(k, 0.0)
        weighted_sum += float(score) * float(w)
        weight_cap_sum += 10.0 * float(w)
    if weight_cap_sum == 0:
        return 0.0
    return (weighted_sum / weight_cap_sum) * 100.0

def check_no_external_refs(text):
    # Disallow http(s) URLs and common domain TLD patterns; allow references to input/ and local files
    if text is None:
        return False
    lower = text.lower()
    if "http://" in lower or "https://" in lower or "www." in lower:
        return False
    # Domain-like patterns with common TLDs (word.word) not preceded by '/' to avoid file extensions
    tld_pattern = r"\b[a-z0-9-]+\.(com|net|org|io|ai|co|edu|gov|uk|de|fr|jp|us|ca|au|es|it|nl|se|no|fi|br|in|sg|za)\b"
    if re.search(tld_pattern, lower):
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Required output files
    report_path = os.path.join(output_dir, "evaluation_report.md")
    scores_path = os.path.join(output_dir, "scores.json")
    assumptions_path = os.path.join(output_dir, "assumptions.txt")

    checks = {
        "files_exist_nonempty": False,
        "scores_json_valid": False,
        "vendor_keys_correct": False,
        "weights_correct": False,
        "score_ranges_valid": False,
        "overall_score_consistent": False,
        "recommendation_consistent": False,
        "dimension_difference_present": False,
        "report_vendors_present": False,
        "report_sections_present": False,
        "report_has_use_case_and_overall": False,
        "report_has_table_row": False,
        "critical_risks_bullets": False,
        "negotiation_leverage_bullets": False,
        "assumptions_length_ok": False,
        "assumptions_contains_assumption": False,
        "assumptions_no_external_refs": False,
    }

    # 1) Presence and readability
    files_present = (
        file_nonempty(report_path) and
        file_nonempty(scores_path) and
        file_nonempty(assumptions_path)
    )
    if files_present:
        checks["files_exist_nonempty"] = True

    # Load files if present
    report_text = read_text(report_path) if files_present else None
    assumptions_text = read_text(assumptions_path) if files_present else None
    data = load_json(scores_path) if files_present else None

    # 2) JSON schema and scoring correctness
    expected_vendor_names = ["DataForge MDM", "CleanStack MDM"]
    expected_weights = {
        "financial_stability": 1,
        "technical_fit": 2,
        "security_compliance": 2,
        "pricing_analysis": 1.5,
        "reference_check": 1,
        "support_quality": 1,
        "vendor_lockin_risk": 1.5,
        "roadmap_alignment": 1
    }
    dimension_keys = list(expected_weights.keys())

    vendors_ok = False
    weights_ok_all = False
    scores_range_ok_all = False
    overall_consistent_all = False
    recommendation_ok_all = False
    dimension_difference_ok = False

    if isinstance(data, dict) and "vendors" in data and isinstance(data["vendors"], dict):
        checks["scores_json_valid"] = True
        vendors = data["vendors"]
        # Check exactly the two required vendors
        if set(vendors.keys()) == set(expected_vendor_names):
            checks["vendor_keys_correct"] = True
            vendors_ok = True

        # For each vendor, validate structure
        if vendors_ok:
            weights_ok = True
            ranges_ok = True
            overall_ok = True
            rec_ok = True

            # Prepare to compare dimension scores across vendors
            # Only if both vendors have dimension_scores
            df_scores = None
            cs_scores = None

            for vname in expected_vendor_names:
                vobj = vendors.get(vname, {})
                # weights check
                v_weights = vobj.get("weights")
                if not isinstance(v_weights, dict) or set(v_weights.keys()) != set(expected_weights.keys()):
                    weights_ok = False
                else:
                    # numeric equality allowing float tolerance
                    for k, val in expected_weights.items():
                        try:
                            if abs(float(v_weights[k]) - float(val)) > 1e-9:
                                weights_ok = False
                                break
                        except Exception:
                            weights_ok = False
                            break

                # dimension_scores check
                dim = vobj.get("dimension_scores")
                if not isinstance(dim, dict) or set(dim.keys()) != set(dimension_keys):
                    ranges_ok = False
                else:
                    for k in dimension_keys:
                        val = dim.get(k)
                        try:
                            f = float(val)
                            # must be number and within [1,10]
                            if not (1 <= f <= 10):
                                ranges_ok = False
                                break
                        except Exception:
                            ranges_ok = False
                            break

                # overall score consistency
                try:
                    provided_overall = float(vobj.get("overall_score"))
                    if not (0 <= provided_overall <= 100):
                        overall_ok = False
                    else:
                        recomputed = compute_overall(dim, v_weights)
                        if abs(provided_overall - recomputed) >= 0.5:
                            overall_ok = False
                except Exception:
                    overall_ok = False

                # recommendation consistency
                rec = vobj.get("recommendation")
                if not isinstance(rec, str) or rec not in {"GO", "CAUTION", "NO-GO"}:
                    rec_ok = False
                else:
                    try:
                        s = float(vobj.get("overall_score"))
                        expected_rec = "GO" if s >= 75 else ("CAUTION" if s >= 50 else "NO-GO")
                        if rec != expected_rec:
                            rec_ok = False
                    except Exception:
                        rec_ok = False

                # save for difference check
                if vname == "DataForge MDM" and isinstance(dim, dict):
                    df_scores = dim
                if vname == "CleanStack MDM" and isinstance(dim, dict):
                    cs_scores = dim

            if weights_ok:
                checks["weights_correct"] = True
                weights_ok_all = True
            if ranges_ok:
                checks["score_ranges_valid"] = True
                scores_range_ok_all = True
            if overall_ok:
                checks["overall_score_consistent"] = True
                overall_consistent_all = True
            if rec_ok:
                checks["recommendation_consistent"] = True
                recommendation_ok_all = True

            # dimension difference between vendors
            if isinstance(df_scores, dict) and isinstance(cs_scores, dict):
                for k in dimension_keys:
                    try:
                        if float(df_scores[k]) != float(cs_scores[k]):
                            dimension_difference_ok = True
                            break
                    except Exception:
                        pass
                if dimension_difference_ok:
                    checks["dimension_difference_present"] = True

    # 3) Report structure checks
    if isinstance(report_text, str):
        lower_report = report_text.lower()
        if "dataforge mdm".lower() in lower_report and "cleanstack mdm".lower() in lower_report:
            checks["report_vendors_present"] = True

        # Section titles
        titles_present = all(t in report_text for t in ["### Critical Risks", "### Negotiation Leverage", "### Recommendation"])
        if titles_present:
            checks["report_sections_present"] = True

        # Mentions
        if ("Use Case" in report_text) and ("Overall Score" in report_text):
            checks["report_has_use_case_and_overall"] = True

        # Table row detection
        if has_table_row(report_text):
            checks["report_has_table_row"] = True

        # Bullets under sections
        if find_section_bullets(report_text, "Critical Risks") >= 2:
            checks["critical_risks_bullets"] = True
        if find_section_bullets(report_text, "Negotiation Leverage") >= 2:
            checks["negotiation_leverage_bullets"] = True

    # 4) Assumptions and evidence discipline
    if isinstance(assumptions_text, str):
        if len(assumptions_text) >= 200:
            checks["assumptions_length_ok"] = True
        if "assumption" in assumptions_text.lower():
            checks["assumptions_contains_assumption"] = True
        if check_no_external_refs(assumptions_text):
            checks["assumptions_no_external_refs"] = True

    # Compute reward
    # Enforce no-op baseline: if any required output file missing or empty, reward = 0.0
    if not files_present:
        reward_value = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward_value = passed / total_checks if total_checks > 0 else 0.0

    # Print exactly one JSON object as the last non-empty line
    result = {"reward": reward_value}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()