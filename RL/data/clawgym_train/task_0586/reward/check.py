import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def count_words(text):
    if not text:
        return 0
    # Count word-like tokens
    tokens = re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
    return len(tokens)

def is_power_of_two(n):
    return n > 0 and (n & (n - 1)) == 0

def parse_perf_csv(path):
    # Returns (records, names_set, even_count, powers_set)
    records = []
    names = set()
    even_count = 0
    powers = set()
    if not os.path.isfile(path):
        return None, None, None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Use csv module; handle potential header
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return 0, set(), 0, set()
            # Detect header by looking at first row content
            start_idx = 0
            header_like = False
            first = rows[0]
            header_candidates = {"id", "name", "value", "timestamp"}
            # If any cell of first row matches expected headers, treat as header
            if any(cell.strip().lower() in header_candidates for cell in first):
                header_like = True
            if header_like:
                start_idx = 1
            for row in rows[start_idx:]:
                if not row:
                    continue
                # Expect at least 3-4 columns
                rid = row[0] if len(row) > 0 else ""
                name = row[1].strip() if len(row) > 1 else ""
                val_raw = row[2].strip() if len(row) > 2 else ""
                # Collect records
                records.append((rid, name, val_raw))
                if name:
                    names.add(name)
                # Parse value as integer when possible
                val_int = None
                if val_raw != "":
                    # Accept integers and strings that represent integers
                    # Reject floats unless they are exact integer forms like "2" not "2.0"
                    if re.fullmatch(r"[+-]?\d+", val_raw):
                        try:
                            val_int = int(val_raw)
                        except:
                            val_int = None
                if isinstance(val_int, int):
                    if val_int % 2 == 0:
                        even_count += 1
                    if is_power_of_two(val_int):
                        powers.add(val_int)
        return len(records), names, even_count, powers
    except:
        return None, None, None, None

def validate_perf_dashboard(dashboard, expected):
    # expected: (total_records, unique_names_len, even_count, sorted_powers_list)
    # Returns dict of booleans for each validation point
    checks = {
        "perf_dashboard_valid_json": False,
        "perf_dashboard_exact_keys": False,
        "perf_dashboard_types_ok": False,
        "perf_dashboard_total_records_correct": False,
        "perf_dashboard_unique_names_correct": False,
        "perf_dashboard_even_value_count_correct": False,
        "perf_dashboard_power_of_two_values_correct": False,
    }
    if dashboard is None or not isinstance(dashboard, dict):
        return checks
    checks["perf_dashboard_valid_json"] = True

    expected_keys = {"total_records", "unique_names", "even_value_count", "power_of_two_values"}
    keys = set(dashboard.keys())
    if keys == expected_keys:
        checks["perf_dashboard_exact_keys"] = True

    # Type checks
    types_ok = (
        isinstance(dashboard.get("total_records"), int) and
        isinstance(dashboard.get("unique_names"), int) and
        isinstance(dashboard.get("even_value_count"), int) and
        isinstance(dashboard.get("power_of_two_values"), list)
    )
    if types_ok:
        # Additionally ensure all items in power_of_two_values are ints
        pov = dashboard.get("power_of_two_values")
        if all(isinstance(x, int) for x in pov):
            checks["perf_dashboard_types_ok"] = True

    total_records, unique_names_len, even_count, powers_sorted = expected

    if isinstance(dashboard.get("total_records"), int) and total_records is not None:
        if dashboard["total_records"] == total_records:
            checks["perf_dashboard_total_records_correct"] = True

    if isinstance(dashboard.get("unique_names"), int) and unique_names_len is not None:
        if dashboard["unique_names"] == unique_names_len:
            checks["perf_dashboard_unique_names_correct"] = True

    if isinstance(dashboard.get("even_value_count"), int) and even_count is not None:
        if dashboard["even_value_count"] == even_count:
            checks["perf_dashboard_even_value_count_correct"] = True

    pov = dashboard.get("power_of_two_values")
    if isinstance(pov, list) and powers_sorted is not None:
        # must be unique and ascending
        unique_sorted = sorted(set(pov))
        if pov == unique_sorted and pov == powers_sorted:
            checks["perf_dashboard_power_of_two_values_correct"] = True

    return checks

def validate_report_md(text):
    checks = {
        "report_exists": False,
        "report_min_250_words": False,
        "report_contains_binary": False,
        "report_contains_twos_complement": False,
        "report_contains_only_even_prime": False,
        "report_contains_helium": False,
    }
    if text is None:
        return checks
    checks["report_exists"] = True
    # Word count
    if count_words(text) >= 250:
        checks["report_min_250_words"] = True
    t_lower = text.lower()
    if "binary" in t_lower:
        checks["report_contains_binary"] = True
    # two's complement or two’s complement (accept both straight and curly apostrophes)
    if ("two's complement" in t_lower) or ("two’s complement" in text.lower()):
        checks["report_contains_twos_complement"] = True
    if "only even prime" in t_lower:
        checks["report_contains_only_even_prime"] = True
    if "helium" in t_lower:
        checks["report_contains_helium"] = True
    return checks

def validate_stock_analysis(text):
    checks = {
        "stock_analysis_exists": False,
        "stock_analysis_mentions_600519": False,
        "stock_analysis_has_two_week_phrase": False,
        "stock_analysis_score_line_valid": False,
        "stock_analysis_disclaimer_line_present": False,
    }
    if text is None:
        return checks
    checks["stock_analysis_exists"] = True
    t_lower = text.lower()
    if "600519" in t_lower:
        checks["stock_analysis_mentions_600519"] = True
    if ("two-week" in t_lower) or ("2-week" in t_lower):
        checks["stock_analysis_has_two_week_phrase"] = True
    # Score line: exactly "Score: X.YY" format, two decimals, within [-5.00, 5.00]
    # Accept optional leading +/-
    score_match = re.search(r"^\s*score:\s*([+-]?\d+\.\d{2})\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
    if score_match:
        try:
            val = float(score_match.group(1))
            if -5.00 <= val <= 5.00:
                checks["stock_analysis_score_line_valid"] = True
        except:
            pass
    # Disclaimer line containing both phrases in the same line (case-insensitive)
    for line in text.splitlines():
        ll = line.lower()
        if ("informational purposes only" in ll) and ("does not constitute investment advice" in ll):
            checks["stock_analysis_disclaimer_line_present"] = True
            break
    return checks

def validate_plan_json(obj):
    checks = {
        "plan_exists": False,
        "plan_valid_json": False,
        "plan_budget_max_steps_2": False,
        "plan_tasks_len_2": False,
        "plan_output_contract_type_json": False,
        "plan_budget_fields_present": False,
        "plan_mode_is_string": False,
    }
    if obj is None:
        return checks
    checks["plan_exists"] = True
    if isinstance(obj, dict):
        checks["plan_valid_json"] = True
        # mode is string
        if isinstance(obj.get("mode"), str):
            checks["plan_mode_is_string"] = True
        # budget
        budget = obj.get("budget")
        if isinstance(budget, dict):
            if budget.get("max_steps") == 2:
                checks["plan_budget_max_steps_2"] = True
            # presence and int type of required fields
            mtc = budget.get("max_tool_calls")
            mmu = budget.get("max_model_upgrades")
            if isinstance(mtc, int) and isinstance(mmu, int):
                checks["plan_budget_fields_present"] = True
        # tasks exactly length 2
        tasks = obj.get("tasks")
        if isinstance(tasks, list) and len(tasks) == 2:
            checks["plan_tasks_len_2"] = True
        # output_contract.type == "json"
        oc = obj.get("output_contract")
        if isinstance(oc, dict) and oc.get("type") == "json":
            checks["plan_output_contract_type_json"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {}

    # 1) report.md checks
    report_path = os.path.join(output_dir, "report.md")
    report_text = read_text(report_path)
    report_checks = validate_report_md(report_text)
    checks.update(report_checks)

    # 2) perf_dashboard.json checks
    perf_csv_path = os.path.join(input_dir, "perf_logs.csv")
    total_records = unique_names_len = even_count = None
    powers_sorted = None
    recs, names, evens, powers = parse_perf_csv(perf_csv_path)
    if recs is not None and names is not None and evens is not None and powers is not None:
        total_records = recs
        unique_names_len = len(names)
        even_count = evens
        powers_sorted = sorted(powers)

    perf_dashboard_path = os.path.join(output_dir, "perf_dashboard.json")
    perf_dashboard = load_json(perf_dashboard_path)
    checks["perf_dashboard_exists"] = os.path.isfile(perf_dashboard_path)
    # Only validate JSON and details if file exists and we have expected values
    if checks["perf_dashboard_exists"] and total_records is not None:
        perf_checks = validate_perf_dashboard(
            perf_dashboard,
            (total_records, unique_names_len, even_count, powers_sorted),
        )
        checks.update(perf_checks)
    else:
        # Initialize expected keys as False if not already set
        perf_keys = [
            "perf_dashboard_valid_json",
            "perf_dashboard_exact_keys",
            "perf_dashboard_types_ok",
            "perf_dashboard_total_records_correct",
            "perf_dashboard_unique_names_correct",
            "perf_dashboard_even_value_count_correct",
            "perf_dashboard_power_of_two_values_correct",
        ]
        for k in perf_keys:
            if k not in checks:
                checks[k] = False

    # 3) stock_analysis.md checks
    stock_analysis_path = os.path.join(output_dir, "stock_analysis.md")
    stock_text = read_text(stock_analysis_path)
    stock_checks = validate_stock_analysis(stock_text)
    checks.update(stock_checks)

    # 4) plan.json checks
    plan_path = os.path.join(output_dir, "plan.json")
    plan_obj = load_json(plan_path)
    plan_checks = validate_plan_json(plan_obj)
    checks.update(plan_checks)

    # Compute reward as fraction of passed checks
    # Ensure baseline: if no outputs at all, reward remains 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Print exactly one JSON object on the last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()