import json
import os
import re
import sys

def parse_markdown_total(text):
    # Match "Total Estimated Revenue Recovery: ₹[amount]"
    # Allow spaces and commas in amount, optional decimals
    pattern = re.compile(r"Total Estimated Revenue Recovery:\s*₹\s*([0-9][0-9,]*\.?[0-9]*)", re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return None
    amt_str = m.group(1).replace(",", "")
    try:
        amt = float(amt_str)
        return amt
    except ValueError:
        return None

def find_table_header_and_row(lines):
    # Header must be exactly the line "Item in Notes | Status in Bill | Estimated Leakage" (trimmed)
    header = "Item in Notes | Status in Bill | Estimated Leakage"
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            header_idx = i
            break
    if header_idx is None:
        return False, False

    # Find at least one non-alignment row after header
    def is_alignment_row(s):
        # Remove pipes and spaces, check remaining chars are only '-' or ':'
        t = s.replace("|", "").replace(" ", "")
        return len(t) > 0 and all(c in "-:" for c in t)

    has_row = False
    for j in range(header_idx + 1, len(lines)):
        row_line = lines[j].strip()
        if not row_line:
            continue
        if "|" not in row_line:
            # If a section ended, stop searching
            continue
        if row_line.strip() == header:
            continue
        if is_alignment_row(row_line):
            # Skip typical Markdown alignment row
            continue
        # Consider this a data row
        has_row = True
        break

    return True, has_row

def validate_json_structure(obj):
    # Top-level structure checks
    if not isinstance(obj, dict):
        return False, False, False
    has_required_keys = "discrepancies" in obj and "total_estimated_recovery" in obj
    if not has_required_keys:
        return True, False, False

    discrepancies = obj.get("discrepancies")
    total = obj.get("total_estimated_recovery")

    items_structure_valid = True
    status_values_valid = True
    allowed_status = {"missing", "under_billed", "billed"}

    if not isinstance(discrepancies, list):
        items_structure_valid = False
        status_values_valid = False
    else:
        for item in discrepancies:
            if not isinstance(item, dict):
                items_structure_valid = False
                status_values_valid = False
                break
            if "item" not in item or "status" not in item or "estimated_leakage" not in item:
                items_structure_valid = False
            else:
                if not isinstance(item["item"], str):
                    items_structure_valid = False
                if not isinstance(item["status"], str):
                    items_structure_valid = False
                    status_values_valid = False
                else:
                    if item["status"] not in allowed_status:
                        status_values_valid = False
                if not isinstance(item["estimated_leakage"], (int, float)):
                    items_structure_valid = False

    return True, has_required_keys and items_structure_valid, status_values_valid

def sum_matches_total(discrepancies, total, tol=1e-2):
    try:
        s = sum(float(d.get("estimated_leakage", 0.0)) for d in discrepancies)
        return abs(s - float(total)) <= tol
    except Exception:
        return False

def compare_totals(report_total, json_total, tol=1e-2):
    if report_total is None or json_total is None:
        return False
    try:
        return abs(float(report_total) - float(json_total)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_report_file": False,
        "has_json_file": False,
        "report_has_table_header": False,
        "report_has_table_row": False,
        "report_has_total_line": False,
        "report_has_whatsapp_and_approval": False,
        "report_has_privacy_disclaimer": False,
        "report_has_methodology_section": False,
        "report_has_assumptions_section": False,
        "json_valid": False,
        "json_has_required_keys": False,
        "json_items_structure_valid": False,
        "json_status_values_valid": False,
        "json_total_matches_sum": False,
        "report_total_matches_json": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "audit_report.md")
    json_path = os.path.join(output_dir, "discrepancies.json")

    report_text = ""
    report_total_value = None

    # Check report file
    if os.path.isfile(report_path):
        checks["has_report_file"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""

        lines = report_text.splitlines()

        # Table header and row
        header_found, row_found = find_table_header_and_row(lines)
        checks["report_has_table_header"] = header_found
        checks["report_has_table_row"] = row_found if header_found else False

        # Total line
        report_total_value = parse_markdown_total(report_text)
        if report_total_value is not None and report_total_value > 0:
            checks["report_has_total_line"] = True

        # WhatsApp Message Draft and approval phrase
        lower_text = report_text.lower()
        has_whatsapp = "whatsapp message draft:" in lower_text
        has_approval_phrase = "approval to update the bill" in lower_text
        checks["report_has_whatsapp_and_approval"] = bool(has_whatsapp and has_approval_phrase)

        # Privacy disclaimer line containing either "privacy" or "de-identify"
        checks["report_has_privacy_disclaimer"] = ("privacy" in lower_text) or ("de-identify" in lower_text)

        # Methodology and Assumptions & Notes
        checks["report_has_methodology_section"] = ("methodology" in lower_text)
        checks["report_has_assumptions_section"] = ("assumptions & notes" in lower_text)

    # Check JSON file
    json_obj = None
    if os.path.isfile(json_path):
        checks["has_json_file"] = True
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                json_obj = json.load(f)
            checks["json_valid"] = True
        except Exception:
            json_obj = None
            checks["json_valid"] = False

        if json_obj is not None and checks["json_valid"]:
            valid_top, has_keys_and_items, status_values_valid = validate_json_structure(json_obj)
            # valid_top indicates top-level is dict; incorporate into json_valid already
            checks["json_has_required_keys"] = has_keys_and_items
            checks["json_items_structure_valid"] = has_keys_and_items
            checks["json_status_values_valid"] = status_values_valid

            if has_keys_and_items:
                discrepancies = json_obj.get("discrepancies", [])
                total_json = json_obj.get("total_estimated_recovery", None)
                checks["json_total_matches_sum"] = sum_matches_total(discrepancies, total_json, tol=1e-2)
                # Compare with report total
                checks["report_total_matches_json"] = compare_totals(report_total_value, total_json, tol=1e-2) if checks["report_has_total_line"] else False

    # Compute reward: ratio of passed checks to total checks
    passed = sum(1 for v in checks.values() if v)
    total_checks = len(checks)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure no-op baseline is 0.0: if output dir missing or both files missing, force 0.0
    output_exists = os.path.isdir(output_dir)
    if (not output_exists) or (not checks["has_report_file"] and not checks["has_json_file"]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()