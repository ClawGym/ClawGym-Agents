import json
import os
import sys
import csv

def read_non_empty_lines(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s != "":
                    lines.append(s)
    except FileNotFoundError:
        pass
    return lines

def count_contacts_rows(path):
    count = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Use DictReader to skip header
            reader = csv.DictReader(f)
            for row in reader:
                # Count row if any non-empty value exists
                if any((str(v).strip() != "" for v in row.values())):
                    count += 1
    except FileNotFoundError:
        pass
    except Exception:
        # Fallback: simple line-based count excluding first non-empty line as header
        try:
            with open(path, "r", encoding="utf-8") as f2:
                lines = [ln.strip() for ln in f2 if ln.strip() != ""]
                if len(lines) > 1:
                    count = len(lines) - 1
                else:
                    count = 0
        except Exception:
            count = 0
    return count

def is_number_equal(val, target):
    if isinstance(val, (int, float)):
        return float(val) == float(target)
    return False

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def file_contains_labels(path, labels):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return all(label in content for label in labels)
    except FileNotFoundError:
        return False
    except Exception:
        return False

def compute_reward(checks):
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    if total == 0:
        return 0.0
    return round(passed / total, 6)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir available if needed
    # reward_dir = os.path.join(workspace_root, "reward")

    # Compute expected counts from inputs
    queries_path = os.path.join(input_dir, "queries.txt")
    sens_path = os.path.join(input_dir, "sensitive_terms.txt")
    contacts_path = os.path.join(input_dir, "contacts.csv")

    queries = read_non_empty_lines(queries_path)
    sens_terms = read_non_empty_lines(sens_path)
    Q = len(queries)
    S = len(sens_terms)
    total_contacts = count_contacts_rows(contacts_path)

    # Initialize checks (all False)
    checks = {
        # report.md checks
        "report_exists": False,
        "report_has_executive_summary": False,
        "report_has_thread_findings": False,
        "report_has_sensitive_terms": False,
        # matches.json checks
        "matches_exists": False,
        "matches_has_required_keys_and_types": False,
        "matches_executed_searches_count_correct": False,
        "matches_executed_searches_items_valid": False,
        "matches_threads_items_type_valid": False,
        # audit.json checks
        "audit_exists": False,
        "audit_fields_present_and_types": False,
        "audit_counts_correct": False,
        "audit_total_executed_searches_correct": False,
        "audit_redaction_object_valid": False,
        # cost_estimate.txt checks
        "cost_estimate_exists": False,
        "cost_estimate_has_all_required_sections": False,
    }

    # 1) report.md
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        # Check exact section labels present anywhere in file
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "Executive Summary" in content:
                checks["report_has_executive_summary"] = True
            if "Thread Findings" in content:
                checks["report_has_thread_findings"] = True
            if "Sensitive Terms" in content:
                checks["report_has_sensitive_terms"] = True
        except Exception:
            pass

    # 2) matches.json
    matches_path = os.path.join(output_dir, "matches.json")
    matches = None
    if os.path.isfile(matches_path):
        checks["matches_exists"] = True
        matches, err = load_json(matches_path)
        if isinstance(matches, dict):
            # Required keys and types
            has_keys = all(k in matches for k in ["schema_version", "threads", "executed_searches"])
            schema_ok = isinstance(matches.get("schema_version"), str)
            threads_ok = isinstance(matches.get("threads"), list)
            exec_ok = isinstance(matches.get("executed_searches"), list)
            if has_keys and schema_ok and threads_ok and exec_ok:
                checks["matches_has_required_keys_and_types"] = True

                # executed_searches count
                exec_list = matches.get("executed_searches", [])
                if len(exec_list) == (Q + S):
                    checks["matches_executed_searches_count_correct"] = True

                # executed_searches items validity
                items_valid = True
                if isinstance(exec_list, list) and len(exec_list) > 0:
                    for item in exec_list:
                        if not isinstance(item, dict):
                            items_valid = False
                            break
                        if not isinstance(item.get("query", ""), str) or item.get("query", "").strip() == "":
                            items_valid = False
                            break
                        if not is_number_equal(item.get("days"), 60):
                            items_valid = False
                            break
                        if not is_number_equal(item.get("limit"), 50):
                            items_valid = False
                            break
                        if not is_number_equal(item.get("context"), 2):
                            items_valid = False
                            break
                        if not is_number_equal(item.get("window_minutes"), 60):
                            items_valid = False
                            break
                # If zero items but expected zero, items_valid should be True
                if len(exec_list) == 0 and (Q + S) == 0:
                    items_valid = True
                if items_valid:
                    checks["matches_executed_searches_items_valid"] = True

                # threads items type
                threads_list = matches.get("threads", [])
                threads_items_ok = isinstance(threads_list, list)
                if threads_items_ok and len(threads_list) > 0:
                    for t in threads_list:
                        if not isinstance(t, dict):
                            threads_items_ok = False
                            break
                if threads_items_ok:
                    checks["matches_threads_items_type_valid"] = True

    # 3) audit.json
    audit_path = os.path.join(output_dir, "audit.json")
    audit = None
    if os.path.isfile(audit_path):
        checks["audit_exists"] = True
        audit, err = load_json(audit_path)
        if isinstance(audit, dict):
            # presence and type checks
            req_fields_present = all(k in audit for k in [
                "total_queries",
                "total_contacts",
                "sensitive_terms_checked",
                "total_executed_searches",
                "redaction",
            ])
            types_ok = (
                isinstance(audit.get("total_queries"), int) and
                isinstance(audit.get("total_contacts"), int) and
                isinstance(audit.get("sensitive_terms_checked"), int) and
                isinstance(audit.get("total_executed_searches"), int) and
                isinstance(audit.get("redaction"), dict)
            )
            if req_fields_present and types_ok:
                checks["audit_fields_present_and_types"] = True

                # counts correct
                counts_ok = (
                    audit.get("total_queries") == Q and
                    audit.get("sensitive_terms_checked") == S and
                    audit.get("total_contacts") == total_contacts
                )
                if counts_ok:
                    checks["audit_counts_correct"] = True

                # total_executed_searches correct and matches matches.json length
                exec_total_ok = False
                if "matches_exists" in checks and checks["matches_exists"] and isinstance(matches, dict):
                    exec_len = len(matches.get("executed_searches", []))
                    exec_total_ok = (
                        audit.get("total_executed_searches") == (Q + S) and
                        audit.get("total_executed_searches") == exec_len
                    )
                else:
                    # If matches.json missing or invalid, cannot pass this check
                    exec_total_ok = False
                if exec_total_ok:
                    checks["audit_total_executed_searches_correct"] = True

                # redaction object valid
                red = audit.get("redaction")
                red_valid = (
                    isinstance(red, dict) and
                    "applied" in red and isinstance(red.get("applied"), bool) and
                    "policy" in red and isinstance(red.get("policy"), str)
                )
                if red_valid:
                    checks["audit_redaction_object_valid"] = True

    # 4) cost_estimate.txt
    cost_path = os.path.join(output_dir, "cost_estimate.txt")
    if os.path.isfile(cost_path):
        checks["cost_estimate_exists"] = True
        required_labels = [
            "AI Agent Cost Estimate",
            "Estimated tokens per run:",
            "Estimated cost per run:",
            "Primary cost drivers:",
            "Optimization suggestions:",
        ]
        if file_contains_labels(cost_path, required_labels):
            checks["cost_estimate_has_all_required_sections"] = True

    # Compute reward; model no-op baseline: if output directory missing or empty, reward must be 0.0
    if not os.path.isdir(output_dir) or len([name for name in os.listdir(output_dir) if not name.startswith(".")]) == 0:
        reward_value = 0.0
    else:
        reward_value = compute_reward(checks)

    result = {"reward": reward_value}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()