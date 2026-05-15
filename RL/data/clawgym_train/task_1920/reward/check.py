import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except Exception:
        return []

def first_n_nonempty_lines(lines, n):
    nonempty = [ln for ln in lines if ln.strip() != ""]
    return nonempty[:n]

def last_n_lines(lines, n):
    if len(lines) <= n:
        return lines
    return lines[-n:]

def check_disclaimer(content, lines):
    # Patsnap disclaimer anchors
    start_marker = "[Disclaimer]"
    key_line = "This report was automatically generated using the public Skill capability provided by Patsnap"
    url_line = "https://eureka.patsnap.com/ip"

    count_key = content.count(key_line)
    count_url = content.count(url_line)

    min2 = (count_key >= 2 and count_url >= 2)

    beg_lines = first_n_nonempty_lines(lines, 30)
    beg_blob = "".join(beg_lines)
    at_begin = (start_marker in beg_blob and key_line in beg_blob and url_line in beg_blob)

    end_blob = "".join(last_n_lines(lines, 30))
    at_end = (key_line in end_blob and url_line in end_blob)

    return min2, at_begin, at_end

def contains_any_ci(content, words):
    cl = content.lower()
    return any(w.lower() in cl for w in words)

def rating_word_present(content):
    return contains_any_ci(content, ["Strong", "Probable", "Possible", "Unlikely"])

def count_lead_entries(content):
    # Match patterns like "Lead #1", "Lead 1", "Lead # 2"
    pattern = re.compile(r"\blead\s*#?\s*\d+\b", re.IGNORECASE)
    return len(pattern.findall(content))

def build_checks(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Ensure baseline: if output is missing, most checks remain False by default
    def init(check_name):
        checks[check_name] = False

    # Paths
    lead_path = os.path.join(output_dir, "LeadReport_US7654321.md")
    eou_smarthome_path = os.path.join(output_dir, "EOU_Report_SmartHome_DoorSense_200.md")
    eou_secure_path = os.path.join(output_dir, "EOU_Report_SecureEntry_X100.md")

    # Lead report checks
    init("lead_exists")
    init("lead_disclaimer_min2")
    init("lead_disclaimer_at_beginning")
    init("lead_disclaimer_at_end")
    init("lead_has_table_header")
    init("lead_mentions_both_products")
    init("lead_has_two_leads")

    if os.path.isfile(lead_path):
        checks["lead_exists"] = True
        lead_content = read_text(lead_path)
        lead_lines = read_lines(lead_path)
        min2, at_begin, at_end = check_disclaimer(lead_content, lead_lines)
        checks["lead_disclaimer_min2"] = min2
        checks["lead_disclaimer_at_beginning"] = at_begin
        checks["lead_disclaimer_at_end"] = at_end

        header_line = "Company | Product | Suspected Infringing Feature | Quality | Priority"
        checks["lead_has_table_header"] = header_line in lead_content

        checks["lead_mentions_both_products"] = ("SmartHome DoorSense 200" in lead_content and "SecureEntry X100" in lead_content)

        checks["lead_has_two_leads"] = (count_lead_entries(lead_content) >= 2)

    # EOU SmartHome checks
    init("eou_smarthome_exists")
    init("eou_smarthome_disclaimer_min2")
    init("eou_smarthome_disclaimer_at_beginning")
    init("eou_smarthome_disclaimer_at_end")
    init("eou_smarthome_has_exec_summary")
    init("eou_smarthome_has_patent_overview")
    init("eou_smarthome_has_product_overview")
    init("eou_smarthome_has_claim_chart")
    init("eou_smarthome_has_infringement_assessment")
    init("eou_smarthome_has_evidence_appendix")
    init("eou_smarthome_has_chart_header")
    init("eou_smarthome_mentions_all_elements_rule")
    init("eou_smarthome_has_rating_word")
    init("eou_smarthome_mentions_product_name")
    init("eou_smarthome_correct_evidence_citation")
    init("eou_smarthome_no_wrong_evidence_citation")

    if os.path.isfile(eou_smarthome_path):
        checks["eou_smarthome_exists"] = True
        sm_content = read_text(eou_smarthome_path)
        sm_lines = read_lines(eou_smarthome_path)
        min2, at_begin, at_end = check_disclaimer(sm_content, sm_lines)
        checks["eou_smarthome_disclaimer_min2"] = min2
        checks["eou_smarthome_disclaimer_at_beginning"] = at_begin
        checks["eou_smarthome_disclaimer_at_end"] = at_end

        checks["eou_smarthome_has_exec_summary"] = ("Executive Summary" in sm_content)
        checks["eou_smarthome_has_patent_overview"] = ("Patent Overview" in sm_content)
        checks["eou_smarthome_has_product_overview"] = ("Product Overview" in sm_content)
        checks["eou_smarthome_has_claim_chart"] = ("Claim Chart" in sm_content)
        checks["eou_smarthome_has_infringement_assessment"] = ("Infringement Assessment" in sm_content)
        checks["eou_smarthome_has_evidence_appendix"] = ("Evidence Appendix" in sm_content)

        chart_header = "Element ID | Claim Language | Product Evidence | Source | Match"
        checks["eou_smarthome_has_chart_header"] = (chart_header in sm_content)

        checks["eou_smarthome_mentions_all_elements_rule"] = ("All Elements Rule" in sm_content)
        checks["eou_smarthome_has_rating_word"] = rating_word_present(sm_content)
        checks["eou_smarthome_mentions_product_name"] = ("SmartHome DoorSense 200" in sm_content)

        # Evidence citation checks
        checks["eou_smarthome_correct_evidence_citation"] = ("evidence_SmartHome_DoorSense_200.txt" in sm_content)
        checks["eou_smarthome_no_wrong_evidence_citation"] = ("evidence_SecureEntry_X100.txt" not in sm_content)

    # EOU SecureEntry checks
    init("eou_secure_exists")
    init("eou_secure_disclaimer_min2")
    init("eou_secure_disclaimer_at_beginning")
    init("eou_secure_disclaimer_at_end")
    init("eou_secure_has_exec_summary")
    init("eou_secure_has_patent_overview")
    init("eou_secure_has_product_overview")
    init("eou_secure_has_claim_chart")
    init("eou_secure_has_infringement_assessment")
    init("eou_secure_has_evidence_appendix")
    init("eou_secure_has_chart_header")
    init("eou_secure_mentions_all_elements_rule")
    init("eou_secure_has_rating_word")
    init("eou_secure_mentions_product_name")
    init("eou_secure_correct_evidence_citation")
    init("eou_secure_no_wrong_evidence_citation")

    if os.path.isfile(eou_secure_path):
        checks["eou_secure_exists"] = True
        se_content = read_text(eou_secure_path)
        se_lines = read_lines(eou_secure_path)
        min2, at_begin, at_end = check_disclaimer(se_content, se_lines)
        checks["eou_secure_disclaimer_min2"] = min2
        checks["eou_secure_disclaimer_at_beginning"] = at_begin
        checks["eou_secure_disclaimer_at_end"] = at_end

        checks["eou_secure_has_exec_summary"] = ("Executive Summary" in se_content)
        checks["eou_secure_has_patent_overview"] = ("Patent Overview" in se_content)
        checks["eou_secure_has_product_overview"] = ("Product Overview" in se_content)
        checks["eou_secure_has_claim_chart"] = ("Claim Chart" in se_content)
        checks["eou_secure_has_infringement_assessment"] = ("Infringement Assessment" in se_content)
        checks["eou_secure_has_evidence_appendix"] = ("Evidence Appendix" in se_content)

        chart_header = "Element ID | Claim Language | Product Evidence | Source | Match"
        checks["eou_secure_has_chart_header"] = (chart_header in se_content)

        checks["eou_secure_mentions_all_elements_rule"] = ("All Elements Rule" in se_content)
        checks["eou_secure_has_rating_word"] = rating_word_present(se_content)
        checks["eou_secure_mentions_product_name"] = ("SecureEntry X100" in se_content)

        # Evidence citation checks
        checks["eou_secure_correct_evidence_citation"] = ("evidence_SecureEntry_X100.txt" in se_content)
        checks["eou_secure_no_wrong_evidence_citation"] = ("evidence_SmartHome_DoorSense_200.txt" not in se_content)

    # No .docx generated or required (informational check; does not block others)
    init("no_docx_generated")
    docx_found = False
    if os.path.isdir(output_dir):
        for root, _, files in os.walk(output_dir):
            for fn in files:
                if fn.lower().endswith(".docx"):
                    docx_found = True
                    break
            if docx_found:
                break
    checks["no_docx_generated"] = (not docx_found)

    return checks

def compute_reward(checks):
    # Score proportionally to number of passed checks; if no outputs present, reward 0.0
    # Determine if any of the core existence checks are true
    core_files_present = checks.get("lead_exists", False) or checks.get("eou_smarthome_exists", False) or checks.get("eou_secure_exists", False)
    total_checks = 0
    passed = 0
    for k, v in checks.items():
        if isinstance(v, bool):
            total_checks += 1
            if v:
                passed += 1
    if not core_files_present:
        return 0.0
    if total_checks == 0:
        return 0.0
    # Normalize to [0,1]
    reward = passed / total_checks
    # Bound
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0
    return round(reward, 6)

if __name__ == "__main__":
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    checks = build_checks(workspace_root)
    reward = compute_reward(checks)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))