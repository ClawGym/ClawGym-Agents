import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # memo.md checks
        "memo_exists": False,
        "memo_has_jurisdiction": False,
        "memo_has_disclaimer": False,
        "memo_mentions_binding": False,
        "memo_mentions_persuasive": False,
        "memo_two_irac_issue": False,
        "memo_two_irac_rule": False,
        "memo_two_irac_application": False,
        "memo_two_irac_conclusion": False,
        "memo_practical_or_first_steps": False,
        "memo_contains_get_a_lawyer": False,

        # checklist.json checks
        "checklist_exists_and_valid": False,
        "checklist_has_required_keys": False,
        "checklist_jurisdiction_valid": False,
        "checklist_issues_include_required": False,
        "checklist_risk_ratings_valid": False,
        "checklist_triggers_len_ok": False,

        # issue_list.json checks
        "issue_list_exists_and_valid": False,
        "issue_list_is_array_len_ok": False,
        "issue_list_has_noncompete": False,
        "issue_list_has_arbitration": False,
        "issue_list_has_class": False,
    }

    # 1) memo.md
    memo_path = os.path.join(output_dir, "memo.md")
    memo_text = None
    if os.path.isfile(memo_path):
        memo_text = read_text_file(memo_path)
        if memo_text is not None and memo_text.strip() != "":
            checks["memo_exists"] = True

    if checks["memo_exists"]:
        text_lower = memo_text.lower()

        # Jurisdiction: must include "Jurisdiction: California" or "Jurisdiction: CA" (case-insensitive)
        # Implemented as regex: jurisdiction\s*:\s*(california|ca)
        if re.search(r'(?i)\bjurisdiction\s*:\s*(california|ca)\b', memo_text):
            checks["memo_has_jurisdiction"] = True

        # Disclaimer: must include both "general information" and "not legal advice" (case-insensitive)
        if ("general information" in text_lower) and ("not legal advice" in text_lower):
            checks["memo_has_disclaimer"] = True

        # Mentions binding and persuasive (case-insensitive)
        if "binding" in text_lower:
            checks["memo_mentions_binding"] = True
        if "persuasive" in text_lower:
            checks["memo_mentions_persuasive"] = True

        # IRAC counts: at least two occurrences each of Issue, Rule, Application, Conclusion (case-insensitive)
        def count_word(word):
            # Count whole word occurrences, case-insensitive
            return len(re.findall(rf'(?i)\b{word}\b', memo_text))

        if count_word("Issue") >= 2:
            checks["memo_two_irac_issue"] = True
        if count_word("Rule") >= 2:
            checks["memo_two_irac_rule"] = True
        if count_word("Application") >= 2:
            checks["memo_two_irac_application"] = True
        if count_word("Conclusion") >= 2:
            checks["memo_two_irac_conclusion"] = True

        # Practical guidance: includes either "practical" or "first steps" (case-insensitive)
        if ("practical" in text_lower) or ("first steps" in text_lower):
            checks["memo_practical_or_first_steps"] = True

        # Includes "get a lawyer" (case-insensitive)
        if "get a lawyer" in text_lower:
            checks["memo_contains_get_a_lawyer"] = True

    # 2) checklist.json
    checklist_path = os.path.join(output_dir, "checklist.json")
    checklist = None
    if os.path.isfile(checklist_path):
        checklist = load_json_file(checklist_path)
        if isinstance(checklist, dict):
            checks["checklist_exists_and_valid"] = True

    if checks["checklist_exists_and_valid"]:
        # Required top-level keys with types
        required_keys = ["jurisdiction", "issues", "risk_ratings", "get_a_lawyer_triggers"]
        has_required = all(k in checklist for k in required_keys)
        if has_required and isinstance(checklist.get("jurisdiction"), str) and isinstance(checklist.get("issues"), list) and isinstance(checklist.get("risk_ratings"), dict) and isinstance(checklist.get("get_a_lawyer_triggers"), list):
            checks["checklist_has_required_keys"] = True

        # Jurisdiction exact value: "California" or "CA" (case-sensitive)
        juris = checklist.get("jurisdiction")
        if juris in ("California", "CA"):
            checks["checklist_jurisdiction_valid"] = True

        # Issues must include at least: "non_compete", "mandatory_arbitration", "class_action_waiver"
        issues = checklist.get("issues")
        needed_issues = {"non_compete", "mandatory_arbitration", "class_action_waiver"}
        if isinstance(issues, list) and needed_issues.issubset(set([str(x) for x in issues])):
            checks["checklist_issues_include_required"] = True

        # risk_ratings must have keys for those three, values one of: "strong", "moderate", "weak" (case-sensitive)
        rr = checklist.get("risk_ratings")
        allowed_vals = {"strong", "moderate", "weak"}
        if isinstance(rr, dict):
            has_all_keys = all(k in rr for k in needed_issues)
            vals_ok = has_all_keys and all(rr[k] in allowed_vals for k in needed_issues)
            if has_all_keys and vals_ok:
                checks["checklist_risk_ratings_valid"] = True

        # get_a_lawyer_triggers length >= 3
        triggers = checklist.get("get_a_lawyer_triggers")
        if isinstance(triggers, list) and len(triggers) >= 3:
            checks["checklist_triggers_len_ok"] = True

    # 3) issue_list.json
    issue_list_path = os.path.join(output_dir, "issue_list.json")
    issue_list = None
    if os.path.isfile(issue_list_path):
        data = load_json_file(issue_list_path)
        if isinstance(data, list):
            checks["issue_list_exists_and_valid"] = True
            issue_list = data

    if checks["issue_list_exists_and_valid"]:
        if len(issue_list) >= 3:
            checks["issue_list_is_array_len_ok"] = True
        # Search across all strings
        combined = " ".join([str(x) for x in issue_list if isinstance(x, (str, int, float))])
        combined_lower = combined.lower()
        # Must include strings that contain substrings:
        # - "non-compete" or "non_compete"
        # - "arbitration"
        # - "class"
        if ("non-compete" in combined_lower) or ("non_compete" in combined_lower):
            checks["issue_list_has_noncompete"] = True
        if "arbitration" in combined_lower:
            checks["issue_list_has_arbitration"] = True
        if "class" in combined_lower:
            checks["issue_list_has_class"] = True

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure baseline: if no outputs exist at all, reward = 0.0
    output_exists = os.path.isdir(output_dir) and any(os.path.isfile(os.path.join(output_dir, f)) for f in os.listdir(output_dir)) if os.path.isdir(output_dir) else False
    if not output_exists:
        reward = 0.0

    # Print single JSON line with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()