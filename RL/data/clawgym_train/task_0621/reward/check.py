import json
import os
import sys
import csv
import math

def main():
    # Resolve workspace root
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    report_path = os.path.join(output_dir, "enterprise_shadow_ai_report.md")
    flagged_csv_path = os.path.join(output_dir, "flagged_ai_transactions.csv")
    summary_json_path = os.path.join(output_dir, "shadow_ai_summary.json")
    input_csv_path = os.path.join(input_dir, "expenses.csv")

    # Initialize checks (all False by default)
    checks = {
        "report_exists": False,
        "report_has_headings": False,
        "report_length_ok": False,
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_no_non_ai": False,
        "has_azure_openai_row": False,
        "has_aws_bedrock_row": False,
        "has_pinecone_row": False,
        "has_anthropic_api_row": False,
        "has_chatgpt_row": False,
        "has_claude_row": False,
        "has_midjourney_row": False,
        "csv_zdr_chatgpt_high_risk": False,
        "csv_zdr_azure_openai_safe": False,
        "json_exists": False,
        "json_valid": False,
        "json_has_required_keys": False,
        "json_totals_match": False,
        "json_departments_match": False,
    }

    # Helper functions
    def read_text(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read()

    def norm_col_name(name):
        # normalize column names: lowercase alphanumeric only
        return "".join(ch for ch in name.lower() if ch.isalnum())

    def approx_equal(a, b, tol=0.01):
        try:
            return abs(float(a) - float(b)) <= tol
        except Exception:
            return False

    # Section 1: Validate Markdown report
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            report_content = read_text(report_path)
            lc = report_content.lower()
            required_headings = [
                "data leakage warnings",
                "zdr security matrix",
                "departmental waste analysis",
                "infrastructure exposure",
            ]
            if all(h in lc for h in required_headings):
                checks["report_has_headings"] = True
            if len(report_content) > 600:
                checks["report_length_ok"] = True
        except Exception:
            # keep defaults
            pass

    # Section 2: Validate flagged AI transactions CSV
    csv_col_map = {}
    csv_rows = []
    if os.path.isfile(flagged_csv_path):
        checks["csv_exists"] = True
        try:
            with open(flagged_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is not None:
                    # Build normalized column map
                    colnames = reader.fieldnames
                    present_norm = set(norm_col_name(c) for c in colnames)
                    required = {
                        "date",
                        "description",
                        "department",
                        "currency",
                        "amount",
                        "normalizedusd",  # Normalized_USD
                        "tool",
                        "zdr",
                    }
                    if required.issubset(present_norm):
                        checks["csv_header_ok"] = True
                    # Map normalized to actual
                    for c in colnames:
                        csv_col_map[norm_col_name(c)] = c
                    for row in reader:
                        csv_rows.append(row)
                else:
                    # No header, leave as invalid
                    pass
        except Exception:
            # keep defaults
            pass

        # Further CSV checks that depend on header and rows
        if checks["csv_header_ok"] and csv_rows:
            # Non-AI items exclusion
            no_non_ai = True
            has_tool = {
                "azure openai": False,
                "aws bedrock": False,
                "pinecone": False,
                "anthropic api": False,
                "chatgpt": False,
                "claude": False,
                "midjourney": False,
            }
            zdr_chatgpt_ok = False
            zdr_azure_ok = False

            for row in csv_rows:
                desc = (row.get(csv_col_map.get("description", ""), "") or "")
                tool_val = (row.get(csv_col_map.get("tool", ""), "") or "")
                zdr_val = (row.get(csv_col_map.get("zdr", ""), "") or "")
                combo = (tool_val + " " + desc).lower()
                # Non-AI terms check in Description only
                if "description" in csv_col_map:
                    dfield = row.get(csv_col_map["description"], "") or ""
                    dlow = dfield.lower()
                    if ("slack subscription" in dlow) or ("office supplies" in dlow):
                        no_non_ai = False

                # Tool presence checks (substring)
                for key in list(has_tool.keys()):
                    if key in combo:
                        has_tool[key] = True

                # ZDR classification checks
                if "chatgpt" in combo and ("high risk" in zdr_val.lower()):
                    zdr_chatgpt_ok = True
                if "azure openai" in combo and ("enterprise safe" in zdr_val.lower()):
                    zdr_azure_ok = True

            checks["csv_no_non_ai"] = no_non_ai
            checks["has_azure_openai_row"] = has_tool["azure openai"]
            checks["has_aws_bedrock_row"] = has_tool["aws bedrock"]
            checks["has_pinecone_row"] = has_tool["pinecone"]
            checks["has_anthropic_api_row"] = has_tool["anthropic api"]
            checks["has_chatgpt_row"] = has_tool["chatgpt"]
            checks["has_claude_row"] = has_tool["claude"]
            checks["has_midjourney_row"] = has_tool["midjourney"]
            checks["csv_zdr_chatgpt_high_risk"] = zdr_chatgpt_ok
            checks["csv_zdr_azure_openai_safe"] = zdr_azure_ok

    # Section 3: Validate summary JSON against expected computed from input/expenses.csv
    output_json = None
    if os.path.isfile(summary_json_path):
        checks["json_exists"] = True
        try:
            with open(summary_json_path, "r", encoding="utf-8") as jf:
                output_json = json.load(jf)
            checks["json_valid"] = True
        except Exception:
            output_json = None

    # If JSON is valid, check structure and compute expected values
    expected_totals = {"safe_usd": 0.0, "high_risk_usd": 0.0}
    expected_dept_high = {}
    input_ok = False

    # Compute expected from input CSV if present
    if os.path.isfile(input_csv_path):
        try:
            # Detection mapping
            enterprise_safe = ["Azure OpenAI", "AWS Bedrock", "Anthropic API", "Pinecone"]
            high_risk = ["ChatGPT", "Claude", "Midjourney"]

            rates = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "SAR": 0.27, "JPY": 0.0065}

            def detect_tool_and_category(description):
                dlow = description.lower()
                for t in enterprise_safe:
                    if t.lower() in dlow:
                        return t, "Enterprise Safe"
                for t in high_risk:
                    if t.lower() in dlow:
                        return t, "High Risk"
                return None, None

            with open(input_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    raise ValueError("Input CSV missing header")
                # Normalize column access
                in_col_map = {norm_col_name(c): c for c in reader.fieldnames}
                # Required minimal columns for reading
                # We'll gracefully handle missing optional columns (Currency, Department)
                for row in reader:
                    desc = (row.get(in_col_map.get("description", ""), "") or "")
                    amt_raw = row.get(in_col_map.get("amount", ""), "")
                    cur = (row.get(in_col_map.get("currency", ""), "") or "USD").strip().upper()
                    dept = (row.get(in_col_map.get("department", ""), "") or "Unknown").strip() or "Unknown"
                    if desc.strip() == "" or amt_raw is None or amt_raw == "":
                        continue
                    tool, cat = detect_tool_and_category(desc)
                    if tool is None:
                        continue  # not AI related
                    try:
                        amount = float(amt_raw)
                    except Exception:
                        # If parsing fails, skip row
                        continue
                    rate = rates.get(cur, 1.0)
                    usd = amount * rate
                    if cat == "Enterprise Safe":
                        expected_totals["safe_usd"] += usd
                    elif cat == "High Risk":
                        expected_totals["high_risk_usd"] += usd
                        expected_dept_high[dept] = expected_dept_high.get(dept, 0.0) + usd
            input_ok = True
        except Exception:
            input_ok = False

    if checks["json_valid"] and output_json is not None:
        # Structure check
        try:
            totals = output_json.get("totals", {})
            depts = output_json.get("departments_high_risk_usd", {})
            if isinstance(totals, dict) and isinstance(depts, dict):
                # Ensure required keys exist and are numeric-like
                su = totals.get("safe_usd", None)
                hr = totals.get("high_risk_usd", None)
                if su is not None and hr is not None:
                    # Try converting to float
                    _ = float(su)
                    _ = float(hr)
                    checks["json_has_required_keys"] = True
        except Exception:
            pass

        # Compare computed expected values to JSON values (only if input OK and keys exist)
        if input_ok and checks["json_has_required_keys"]:
            try:
                su_out = float(output_json["totals"]["safe_usd"])
                hr_out = float(output_json["totals"]["high_risk_usd"])
                su_exp = float(expected_totals["safe_usd"])
                hr_exp = float(expected_totals["high_risk_usd"])
                if approx_equal(su_out, su_exp, tol=0.01) and approx_equal(hr_out, hr_exp, tol=0.01):
                    checks["json_totals_match"] = True
            except Exception:
                pass

            # Departments per high risk
            try:
                depts_out = output_json.get("departments_high_risk_usd", {})
                # Check all expected departments present and within tolerance
                dep_match = True
                for dep, val in expected_dept_high.items():
                    if dep not in depts_out:
                        dep_match = False
                        break
                    try:
                        if not approx_equal(float(depts_out[dep]), float(val), tol=0.01):
                            dep_match = False
                            break
                    except Exception:
                        dep_match = False
                        break
                checks["json_departments_match"] = dep_match
            except Exception:
                pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty, reward must be 0.0
    # Enforce: if none of the critical existence checks are true, set reward to 0.0
    critical_any = checks["report_exists"] or checks["csv_exists"] or checks["json_exists"]
    if not critical_any:
        reward = 0.0

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()