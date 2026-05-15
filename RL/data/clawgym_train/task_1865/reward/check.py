import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def file_non_empty(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def has_heading_with_label(text, label):
    # Check for a likely section/heading: line starting with '#' and containing label, or line starting with the label itself
    label_lower = label.lower()
    for line in text.splitlines():
        s = line.strip().lower()
        if label_lower in s:
            if s.startswith("#") or s.startswith(label_lower):
                return True
    return False

def recommendation_has_confidence(text):
    t_lower = text.lower()
    idx = t_lower.find("recommendation")
    if idx == -1:
        return False
    # Look ahead in the next 1000 characters for confidence words
    snippet = t_lower[idx: idx + 1000]
    for word in ["high", "medium", "low"]:
        if word in snippet:
            return True
    return False

def count_domain_tokens(text):
    t_lower = text.lower()
    tokens = [
        "dscr",
        "ltv",
        "ltc",
        "debt yield",
        "draw schedule",
        "draw schedules",
        "lien waiver",
        "lien waivers",
    ]
    count = 0
    for tok in tokens:
        if tok in t_lower:
            count += 1
    return count

def parse_csv(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                # Keep lines including empty for robustness, but strip newline
                rows.append(line.rstrip("\n"))
    except Exception:
        return []
    return rows

def validate_summary_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return (False, False, False, False)

    # Fields existence and types
    ok_fields = all(k in data for k in ["tam", "sam", "som", "assumptions", "confidence"])
    if not ok_fields:
        return (False, False, False, False)

    # Numeric fields and order
    try:
        tam = float(data["tam"])
        sam = float(data["sam"])
        som = float(data["som"])
        nums_ok = tam > 0 and sam > 0 and som > 0 and tam >= sam >= som
    except Exception:
        nums_ok = False

    # Assumptions array len
    assumptions_ok = isinstance(data.get("assumptions"), list) and len(data["assumptions"]) >= 2

    # Confidence value
    conf = str(data.get("confidence", "")).strip().lower()
    confidence_ok = conf in {"high", "medium", "low"}

    return (True, nums_ok, assumptions_ok, confidence_ok)

def memory_file_has_bullets(path):
    if not file_non_empty(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("- "):
                    return True
    except Exception:
        return False
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_decision_memo": False,
        "memo_has_preamble_labels": False,
        "memo_has_tam_sam_som_sections": False,
        "memo_has_triage_labels": False,
        "memo_has_recommendation_with_confidence": False,
        "memo_has_loan_domain_considerations_and_tokens": False,
        "has_competitor_csv": False,
        "competitor_csv_has_header": False,
        "competitor_csv_min_rows": False,
        "has_output_summary_json": False,
        "summary_json_valid_numbers_and_order": False,
        "summary_json_assumptions_len": False,
        "summary_json_confidence_valid": False,
        "memory_wisdom_exists_and_bullets": False,
        "memory_goals_exists_and_bullets": False,
        "memory_mistakes_exists_and_bullets": False,
        "memory_preferences_exists_and_bullets": False,
    }

    # 1) decision_memo.md checks
    memo_path = os.path.join(output_dir, "decision_memo.md")
    if file_non_empty(memo_path):
        checks["has_decision_memo"] = True
        memo_text = read_text(memo_path)

        # Preamble labels
        pre_labels = ["Objective:", "Constraints:", "Load-bearing variables:", "Mechanism:", "Fragile assumption:"]
        if all(lbl in memo_text for lbl in pre_labels):
            checks["memo_has_preamble_labels"] = True

        # TAM/SAM/SOM sections (as headings or section lines)
        has_tam = has_heading_with_label(memo_text, "TAM")
        has_sam = has_heading_with_label(memo_text, "SAM")
        has_som = has_heading_with_label(memo_text, "SOM")
        if has_tam and has_sam and has_som:
            checks["memo_has_tam_sam_som_sections"] = True

        # Triangulation labels
        tri_labels = ["Market structure data", "Behavior data", "Direct customer evidence"]
        if all(lbl in memo_text for lbl in tri_labels):
            checks["memo_has_triage_labels"] = True

        # RECOMMENDATION with confidence
        if ("recommendation" in memo_text.lower()) and recommendation_has_confidence(memo_text):
            checks["memo_has_recommendation_with_confidence"] = True

        # Loan Domain Considerations section and tokens
        if "loan domain considerations" in memo_text.lower():
            token_count = count_domain_tokens(memo_text)
            if token_count >= 2:
                checks["memo_has_loan_domain_considerations_and_tokens"] = True

    # 2) competitor_matrix.csv checks
    comp_path = os.path.join(output_dir, "competitor_matrix.csv")
    if os.path.isfile(comp_path):
        checks["has_competitor_csv"] = True
        rows = parse_csv(comp_path)
        if rows:
            header_ok = rows[0].strip() == "name,type,positioning,price_anchor"
            checks["competitor_csv_has_header"] = header_ok
            # Count data rows with 4 columns (non-empty)
            data_rows = 0
            for r in rows[1:]:
                if not r.strip():
                    continue
                parts = r.split(",")
                if len(parts) == 4:
                    data_rows += 1
            if data_rows >= 3:
                checks["competitor_csv_min_rows"] = True

    # 3) output_summary.json checks
    summary_path = os.path.join(output_dir, "output_summary.json")
    if os.path.isfile(summary_path):
        checks["has_output_summary_json"] = True
        valid_json, nums_ok, assumptions_ok, conf_ok = validate_summary_json(summary_path)
        # valid_json ensures parsing success; but we count numbers/order etc only if parse succeeded
        if valid_json and nums_ok:
            checks["summary_json_valid_numbers_and_order"] = True
        if valid_json and assumptions_ok:
            checks["summary_json_assumptions_len"] = True
        if valid_json and conf_ok:
            checks["summary_json_confidence_valid"] = True

    # 4) memory files
    mem_wisdom = os.path.join(output_dir, "memory", "wisdom.md")
    mem_goals = os.path.join(output_dir, "memory", "goals.md")
    mem_mistakes = os.path.join(output_dir, "memory", "mistakes.md")
    mem_prefs = os.path.join(output_dir, "memory", "preferences.md")

    if memory_file_has_bullets(mem_wisdom):
        checks["memory_wisdom_exists_and_bullets"] = True
    if memory_file_has_bullets(mem_goals):
        checks["memory_goals_exists_and_bullets"] = True
    if memory_file_has_bullets(mem_mistakes):
        checks["memory_mistakes_exists_and_bullets"] = True
    if memory_file_has_bullets(mem_prefs):
        checks["memory_preferences_exists_and_bullets"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # No-op baseline: if output directory is missing or empty of required artifacts, ensure 0.0
    # If none of the artifact existence checks passed, reward should be 0.0
    artifact_exists = any([
        checks["has_decision_memo"],
        checks["has_competitor_csv"],
        checks["has_output_summary_json"],
        checks["memory_wisdom_exists_and_bullets"],
        checks["memory_goals_exists_and_bullets"],
        checks["memory_mistakes_exists_and_bullets"],
        checks["memory_preferences_exists_and_bullets"],
    ])
    if not artifact_exists:
        reward = 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()