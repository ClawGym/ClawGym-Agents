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

def split_paragraphs(text):
    # Normalize newlines and split on blank lines
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paras = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                paras.append(" ".join(current).strip())
                current = []
        else:
            current.append(line.strip())
    if current:
        paras.append(" ".join(current).strip())
    return paras

def contains_insurance_performance_same_paragraph(text):
    paras = split_paragraphs(text)
    for p in paras:
        pl = p.lower()
        if "insurance" in pl and "performance" in pl:
            return True
    return False

def contains_disclaimer(text):
    paras = split_paragraphs(text)
    for p in paras:
        pl = p.lower()
        if "informational" in pl and "not legal advice" in pl:
            return True
    return False

def has_sensitive_numbers(text):
    if text is None:
        return False
    # Detect $, USD, or numbers with commas like 1,000 or 10,000,000
    if "$" in text:
        return True
    if re.search(r"\bUSD\b", text, flags=re.IGNORECASE):
        return True
    if re.search(r"\b\d{1,3}(,\d{3})+\b", text):
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Owner-facing explainer checks
        "owner_exists": False,
        "owner_word_count_ok": False,
        "owner_sections_ok": False,
        "owner_terms_ok": False,
        "owner_insurance_perf_ok": False,
        "owner_disclaimer_ok": False,
        "owner_names_ok": False,
        "owner_plain_language_format_ok": False,
        "owner_no_sensitive_numbers": False,
        # Internal plan checks
        "plan_exists": False,
        "plan_parses": False,
        "plan_keys_present": False,
        "plan_exact_values_ok": False,
        "plan_bond_types_ok": False,
        "plan_underwriting_prep_ok": False,
        "plan_claims_mitigation_ok": False,
        "plan_notes_ok": False,
        "plan_no_sensitive_numbers": False,
    }

    # Paths
    owner_path = os.path.join(output_dir, "owner_facing_bond_explainer.md")
    plan_path = os.path.join(output_dir, "internal_bond_plan.json")

    # Owner-facing explainer validation
    owner_text = None
    if os.path.isfile(owner_path):
        checks["owner_exists"] = True
        owner_text = read_text(owner_path)
        if owner_text is None:
            owner_text = ""
        # Word count between 600 and 1200
        words = owner_text.split()
        wc = len(words)
        if 600 <= wc <= 1200:
            checks["owner_word_count_ok"] = True

        # Section headings: check for presence of keywords anywhere (case-insensitive)
        lower_text = owner_text.lower()
        required_sections = [
            "three-party structure",
            "bond types",
            "underwriting",
            "claims",
            "construction",
        ]
        if all(k in lower_text for k in required_sections):
            checks["owner_sections_ok"] = True

        # Key terms
        key_terms = [
            "principal",
            "obligee",
            "surety",
            "bid bond",
            "performance bond",
            "payment bond",
        ]
        if all(term in lower_text for term in key_terms):
            checks["owner_terms_ok"] = True

        # Insurance vs performance in same paragraph
        if contains_insurance_performance_same_paragraph(owner_text):
            checks["owner_insurance_perf_ok"] = True

        # Disclaimer presence
        if contains_disclaimer(owner_text):
            checks["owner_disclaimer_ok"] = True

        # Names presence
        if ("city of westfield public works".lower() in lower_text and
            "westfield public library renovation".lower() in lower_text):
            checks["owner_names_ok"] = True

        # Plain-language format heuristic: at least 5 paragraphs (separated by blank lines) and at least one blank line exists
        paras = split_paragraphs(owner_text)
        has_blank_line = "\n\n" in owner_text.replace("\r\n", "\n")
        if len(paras) >= 5 and has_blank_line:
            checks["owner_plain_language_format_ok"] = True

        # No sensitive numbers
        if not has_sensitive_numbers(owner_text):
            checks["owner_no_sensitive_numbers"] = True

    # Internal plan validation
    plan_text = None
    plan_json = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_text = read_text(plan_path)
        if plan_text is None:
            plan_text = ""
        # Sensitive numbers check on raw text
        if not has_sensitive_numbers(plan_text):
            checks["plan_no_sensitive_numbers"] = True

        # Parse JSON
        try:
            plan_json = json.loads(plan_text)
            checks["plan_parses"] = True
        except Exception:
            plan_json = None

        if plan_json is not None and isinstance(plan_json, dict):
            required_keys = [
                "obligee",
                "obligee_project",
                "principal",
                "bond_types",
                "bond_amounts",
                "bid_deadline",
                "surety_requirements",
                "underwriting_preparation",
                "claims_mitigation",
                "notes",
            ]
            if all(k in plan_json for k in required_keys):
                checks["plan_keys_present"] = True

                # Exact values
                exact_ok = True
                exact_ok = exact_ok and plan_json.get("obligee") == "City of Westfield Public Works"
                exact_ok = exact_ok and plan_json.get("obligee_project") == "Westfield Public Library Renovation"
                exact_ok = exact_ok and plan_json.get("principal") == "Hearthstone GC, Inc."
                exact_ok = exact_ok and plan_json.get("bid_deadline") == "2026-05-20"

                # surety_requirements.treasury_listed === true
                sr = plan_json.get("surety_requirements")
                if not isinstance(sr, dict) or sr.get("treasury_listed") is not True:
                    exact_ok = False

                # bond_amounts numeric checks
                ba = plan_json.get("bond_amounts")
                if not isinstance(ba, dict):
                    exact_ok = False
                else:
                    # ensure numeric equality
                    try:
                        bp = ba.get("bid_percent")
                        pp = ba.get("performance_percent")
                        payp = ba.get("payment_percent")
                        if not (isinstance(bp, (int, float)) and isinstance(pp, (int, float)) and isinstance(payp, (int, float))):
                            exact_ok = False
                        else:
                            if not (bp == 5 and pp == 100 and payp == 100):
                                exact_ok = False
                    except Exception:
                        exact_ok = False

                checks["plan_exact_values_ok"] = bool(exact_ok)

                # bond_types includes "bid", "performance", "payment"
                bt_ok = False
                bt = plan_json.get("bond_types")
                if isinstance(bt, list):
                    bt_lower = [str(x).lower() for x in bt]
                    bt_ok = all(x in bt_lower for x in ["bid", "performance", "payment"])
                checks["plan_bond_types_ok"] = bt_ok

                # underwriting_preparation 5–8 items and includes character, capacity, capital across its items
                up_ok = False
                up = plan_json.get("underwriting_preparation")
                if isinstance(up, list):
                    length_ok = 5 <= len(up) <= 8
                    joined = " ".join([str(x) for x in up]).lower()
                    has_all_three = all(w in joined for w in ["character", "capacity", "capital"])
                    up_ok = length_ok and has_all_three
                checks["plan_underwriting_prep_ok"] = up_ok

                # claims_mitigation 4–6 items
                cm_ok = False
                cm = plan_json.get("claims_mitigation")
                if isinstance(cm, list):
                    cm_ok = 4 <= len(cm) <= 6
                checks["plan_claims_mitigation_ok"] = cm_ok

                # notes non-empty string
                notes_ok = isinstance(plan_json.get("notes"), str) and len(plan_json.get("notes").strip()) > 0
                checks["plan_notes_ok"] = notes_ok

    # Compute reward as fraction of passed checks.
    # Ensure no-op baseline: if both artifacts missing, reward should be exactly 0.0 (it will be, since all checks remain False).
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Print exactly one JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()