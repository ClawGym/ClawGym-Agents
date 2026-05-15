import json
import os
import sys
import csv
import re

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def parse_csv_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            # skip entirely empty lines
            if len(row) == 0 or (len(row) == 1 and row[0].strip() == ""):
                continue
            rows.append(row)
    return rows

def is_string(x):
    return isinstance(x, str)

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def last_non_empty_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected files
    config_md_path = os.path.join(output_dir, "alert_config.md")
    rules_json_path = os.path.join(output_dir, "alert_rules.json")
    summary_csv_path = os.path.join(output_dir, "alert_summary.csv")

    allowed_categories = {"Rankings", "Traffic", "Technical", "Backlinks", "Competitors", "GEO", "Brand"}
    counted_priorities = ["Critical", "High", "Medium", "Low"]
    allowed_threshold_methods = {"stddev", "percentage", "absolute"}

    checks = {
        # Presence
        "has_alert_config_md": False,
        "has_alert_rules_json": False,
        "has_alert_summary_csv": False,

        # JSON structure
        "rules_json_parses": False,
        "top_level_keys_present": False,
        "notification_channels_structure_valid": False,
        "recipients_is_object": False,
        "rules_array_len_ge_20": False,
        "rules_each_has_required_keys": False,
        "rules_threshold_method_valid": False,
        "rules_stddev_have_baseline": False,
        "rules_percentage_have_comparison_period": False,
        "rules_absolute_have_units": False,
        "categories_covered_all_7": False,

        # MD content checks
        "config_md_has_header_and_domain_and_date": False,
        "config_md_has_alert_categories_table_with_all_7": False,
        "config_md_has_response_plans_section": False,
        "config_md_has_notification_setup_section": False,
        "config_md_has_weekly_review_checklist": False,

        # CSV structure and consistency
        "summary_csv_has_header": False,
        "summary_csv_has_min_rows": False,
        "summary_counts_match_rules": False,
    }

    # Presence checks
    if os.path.isfile(config_md_path):
        checks["has_alert_config_md"] = True
    if os.path.isfile(rules_json_path):
        checks["has_alert_rules_json"] = True
    if os.path.isfile(summary_csv_path):
        checks["has_alert_summary_csv"] = True

    # Parse JSON and validate structure
    rules_data = None
    if checks["has_alert_rules_json"]:
        try:
            rules_data = load_json(rules_json_path)
            checks["rules_json_parses"] = True
        except Exception:
            rules_data = None

    # Validate top-level keys and structures if JSON parsed
    rules_list = []
    rules_counts_by_cat = {cat: {p: 0 for p in counted_priorities} for cat in allowed_categories}
    if checks["rules_json_parses"]:
        top_keys_present = all(k in rules_data for k in ["domain", "configured_date", "notification_channels", "recipients", "rules"])
        if top_keys_present and is_string(rules_data.get("domain")) and is_string(rules_data.get("configured_date")) and isinstance(rules_data.get("notification_channels"), dict) and isinstance(rules_data.get("recipients"), dict) and isinstance(rules_data.get("rules"), list):
            checks["top_level_keys_present"] = True

            # notification_channels validation
            nc = rules_data.get("notification_channels", {})
            nc_valid = True
            for pr in counted_priorities:
                if pr not in nc or not isinstance(nc.get(pr), list):
                    nc_valid = False
                    break
            if nc_valid:
                checks["notification_channels_structure_valid"] = True

            # recipients object type
            if isinstance(rules_data.get("recipients"), dict):
                checks["recipients_is_object"] = True

            # rules presence and length
            rules_list = rules_data.get("rules", [])
            if isinstance(rules_list, list) and len(rules_list) >= 20:
                checks["rules_array_len_ge_20"] = True

            # Validate each rule for required keys
            required_rule_keys = {"category", "name", "metric", "condition", "threshold_method", "threshold", "priority", "data_source", "baseline_source"}
            all_have_required = True
            all_methods_valid = True
            stddev_ok = True
            perc_ok = True
            abs_ok = True
            categories_seen = set()

            for r in rules_list:
                # Required keys
                if not isinstance(r, dict) or not required_rule_keys.issubset(r.keys()):
                    all_have_required = False
                    break

                # Category validity
                cat = r.get("category")
                if cat in allowed_categories:
                    categories_seen.add(cat)

                # threshold_method validity
                tm = r.get("threshold_method")
                if tm not in allowed_threshold_methods:
                    all_methods_valid = False

                # threshold object type
                if not isinstance(r.get("threshold"), dict):
                    all_have_required = False
                    break

                # stddev specific
                if tm == "stddev":
                    base = r.get("baseline")
                    if not isinstance(base, dict) or not is_number(base.get("mean")) or not is_number(base.get("stddev")):
                        stddev_ok = False

                # percentage specific
                if tm == "percentage":
                    cp = r.get("comparison_period")
                    if not is_string(cp) or not cp.strip():
                        perc_ok = False

                # absolute specific
                if tm == "absolute":
                    units = r.get("threshold", {}).get("units")
                    if not is_string(units) or not units.strip():
                        abs_ok = False

                # count for summary
                pr = r.get("priority")
                if cat in allowed_categories and pr in counted_priorities:
                    rules_counts_by_cat[cat][pr] += 1

            if all_have_required:
                checks["rules_each_has_required_keys"] = True
            if all_methods_valid:
                checks["rules_threshold_method_valid"] = True
            if stddev_ok:
                checks["rules_stddev_have_baseline"] = True
            if perc_ok:
                checks["rules_percentage_have_comparison_period"] = True
            if abs_ok:
                checks["rules_absolute_have_units"] = True
            if categories_seen >= allowed_categories:
                checks["categories_covered_all_7"] = True

    # Validate Markdown content
    if checks["has_alert_config_md"]:
        try:
            md = read_text(config_md_path)
            # Header + domain + configured date presence
            has_header = "SEO Alert System Configuration" in md
            # Check for "Domain" and "Configured" terms
            has_domain = re.search(r"\bDomain\b", md, re.IGNORECASE) is not None
            has_configured = re.search(r"\bConfigured\b", md, re.IGNORECASE) is not None or re.search(r"\bConfigured Date\b", md, re.IGNORECASE) is not None
            if has_header and has_domain and has_configured:
                checks["config_md_has_header_and_domain_and_date"] = True

            # Alert Categories table with all seven categories
            has_alert_categories_section = "Alert Categories" in md
            has_all_categories = all(cat in md for cat in allowed_categories)
            if has_alert_categories_section and has_all_categories:
                checks["config_md_has_alert_categories_table_with_all_7"] = True

            # Response plans section
            if re.search(r"Response Plans by Priority", md, re.IGNORECASE):
                checks["config_md_has_response_plans_section"] = True

            # Notification setup section
            if re.search(r"Notification Setup", md, re.IGNORECASE):
                checks["config_md_has_notification_setup_section"] = True

            # Weekly review checklist
            if re.search(r"Weekly Alert Review Checklist", md, re.IGNORECASE):
                checks["config_md_has_weekly_review_checklist"] = True
        except Exception:
            pass

    # Validate CSV summary and compare counts with rules
    if checks["has_alert_summary_csv"]:
        try:
            rows = parse_csv_rows(summary_csv_path)
            if rows:
                header = [c.strip() for c in rows[0]]
                if header == ["Category", "Critical", "High", "Medium", "Low", "Total"]:
                    checks["summary_csv_has_header"] = True
                # Expect at least 8 data rows (7 categories + 1 Total)
                data_rows = rows[1:] if len(rows) > 1 else []
                # Filter out blank-only rows already done
                if len(data_rows) >= 8:
                    checks["summary_csv_has_min_rows"] = True

                # Only proceed to match counts if JSON parsed and categories covered
                if checks["rules_json_parses"] and checks["categories_covered_all_7"] and checks["summary_csv_has_header"]:
                    # Build CSV counts
                    csv_counts_by_cat = {}
                    totals_row = None
                    parse_ok = True
                    for r in data_rows:
                        # Ensure row has exactly 6 fields; if more, ignore extras
                        if len(r) < 6:
                            parse_ok = False
                            break
                        cat = r[0].strip()
                        try:
                            crit = int(str(r[1]).strip())
                            hi = int(str(r[2]).strip())
                            med = int(str(r[3]).strip())
                            low = int(str(r[4]).strip())
                            tot = int(str(r[5]).strip())
                        except Exception:
                            parse_ok = False
                            break
                        # Validate row total
                        if crit + hi + med + low != tot:
                            parse_ok = False
                            break
                        if cat.lower() == "total":
                            totals_row = {"Critical": crit, "High": hi, "Medium": med, "Low": low, "Total": tot}
                        else:
                            csv_counts_by_cat[cat] = {"Critical": crit, "High": hi, "Medium": med, "Low": low, "Total": tot}

                    if parse_ok:
                        # Check that all 7 categories are present in CSV
                        cats_missing = allowed_categories - set(csv_counts_by_cat.keys())
                        if len(cats_missing) == 0 and totals_row is not None:
                            # Compare with JSON-derived counts
                            json_counts_by_cat = {}
                            for cat in allowed_categories:
                                crit = rules_counts_by_cat[cat]["Critical"]
                                hi = rules_counts_by_cat[cat]["High"]
                                med = rules_counts_by_cat[cat]["Medium"]
                                low = rules_counts_by_cat[cat]["Low"]
                                tot = crit + hi + med + low
                                json_counts_by_cat[cat] = {"Critical": crit, "High": hi, "Medium": med, "Low": low, "Total": tot}

                            # Category-level comparison
                            cat_counts_match = True
                            for cat in allowed_categories:
                                if cat not in csv_counts_by_cat:
                                    cat_counts_match = False
                                    break
                                if csv_counts_by_cat[cat] != json_counts_by_cat[cat]:
                                    cat_counts_match = False
                                    break

                            # Total row comparison
                            if cat_counts_match:
                                total_crit = sum(json_counts_by_cat[c]["Critical"] for c in allowed_categories)
                                total_hi = sum(json_counts_by_cat[c]["High"] for c in allowed_categories)
                                total_med = sum(json_counts_by_cat[c]["Medium"] for c in allowed_categories)
                                total_low = sum(json_counts_by_cat[c]["Low"] for c in allowed_categories)
                                total_tot = total_crit + total_hi + total_med + total_low
                                json_totals_row = {"Critical": total_crit, "High": total_hi, "Medium": total_med, "Low": total_low, "Total": total_tot}
                                if totals_row == json_totals_row:
                                    checks["summary_counts_match_rules"] = True
        except Exception:
            pass

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Enforce baseline: if any required artifact missing, reward = 0.0
    required_all_present = checks["has_alert_config_md"] and checks["has_alert_rules_json"] and checks["has_alert_summary_csv"]
    if not required_all_present:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()