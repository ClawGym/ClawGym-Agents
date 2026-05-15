import json
import os
import re
import sys
from typing import Any, Dict, Tuple, Optional, Union

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None, "not_a_object"
        return data, None
    except Exception as e:
        return None, str(e)

def extract_numbers(text: str) -> list:
    # Matches numbers like $65,100.50 or 65100 or -1,234
    pattern = re.compile(r'[-+]?\$?\d[\d,]*(?:\.\d+)?')
    nums = []
    for m in pattern.finditer(text):
        token = m.group(0)
        token = token.replace("$", "").replace(",", "")
        try:
            nums.append(float(token))
        except Exception:
            continue
    return nums

def approx_equal(val: float, target: float, tol: float) -> bool:
    return abs(val - target) <= tol

def find_any_number_within(text: str, target: float, tol: float) -> bool:
    nums = extract_numbers(text or "")
    for n in nums:
        if approx_equal(n, target, tol):
            return True
    return False

def lines_with_keyword(text: str, keyword: str) -> list:
    if text is None:
        return []
    out = []
    for line in text.splitlines():
        if keyword.lower() in line.lower():
            out.append(line)
    return out

def count_bullet_recommendations(text: str) -> int:
    if text is None:
        return 0
    cnt = 0
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("- ") or s.startswith("* ") or re.match(r'^\d+[\.\)]\s+', s):
            cnt += 1
    return cnt

def contains_case_insensitive(text: str, needle: str) -> bool:
    if text is None:
        return False
    return needle.lower() in text.lower()

def has_heading(text: str, heading: str) -> bool:
    if text is None:
        return False
    # Accept heading anywhere in a line (Markdown heading markers optional)
    for line in text.splitlines():
        if heading.lower() in line.strip().lower():
            return True
    return False

def segment_under_heading(text: str, heading: str, next_headings: list) -> str:
    # Return the text segment from the line containing 'heading' until the next of 'next_headings' or EOF
    if text is None:
        return ""
    lines = text.splitlines()
    start_idx = -1
    for i, line in enumerate(lines):
        if heading.lower() in line.lower():
            start_idx = i + 1
            break
    if start_idx == -1:
        return ""
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        for nh in next_headings:
            if nh.lower() in lines[i].lower():
                end_idx = i
                return "\n".join(lines[start_idx:end_idx])
    return "\n".join(lines[start_idx:end_idx])

def text_contains_all_patterns(text: str, patterns: list) -> bool:
    if text is None:
        return False
    hay = text
    return all(p in hay for p in patterns)

# Minimal YAML parser for simple mapping with nested maps via indentation (2 spaces per level), no lists
Scalar = Union[str, int, float]
YAMLNode = Union[Dict[str, Any], Scalar]

def parse_scalar(value: str) -> Scalar:
    v = value.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        v = v[1:-1]
    # Try number
    try:
        if re.match(r'^-?\d+\.\d+$', v):
            return float(v)
        if re.match(r'^-?\d+$', v):
            return int(v)
    except Exception:
        pass
    return v

def parse_simple_yaml(content: str) -> Optional[Dict[str, Any]]:
    if content is None:
        return None
    root: Dict[str, Any] = {}
    stack: list[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in content.splitlines():
        # Remove comments after a space or start; simplistic: strip trailing inline comments starting with ' #'
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            return None
        level = indent // 2
        entry = line.strip()
        if ":" not in entry:
            return None
        key, rest = entry.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        while stack and level <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        parent = stack[-1][1]
        if rest == "":
            # start of nested mapping
            if key in parent and not isinstance(parent[key], dict):
                return None
            new_map: Dict[str, Any] = {}
            parent[key] = new_map
            stack.append((level, new_map))
        else:
            # scalar value
            parent[key] = parse_scalar(rest)
    return root

def sum_numeric_leaves(node: Any) -> float:
    total = 0.0
    if isinstance(node, dict):
        for v in node.values():
            total += sum_numeric_leaves(v)
    else:
        if isinstance(node, (int, float)):
            total += float(node)
    return total

def find_key_recursive(d: Dict[str, Any], key: str) -> Optional[Scalar]:
    for k, v in d.items():
        if k == key:
            if isinstance(v, (int, float, str)):
                return v  # might be str or number; caller ensures numeric
            # if it's a mapping and they meant the node, skip
        if isinstance(v, dict):
            res = find_key_recursive(v, key)
            if res is not None:
                return res
    return None

def get_nested(d: Dict[str, Any], *keys) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        if k not in cur:
            return None
        cur = cur[k]
    return cur

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but reserved

    checks: Dict[str, bool] = {}

    # 1) metrics.json checks
    metrics_path = os.path.join(output_dir, "metrics.json")
    checks["metrics_exists"] = os.path.isfile(metrics_path)
    metrics_data = None
    if checks["metrics_exists"]:
        metrics_data, err = parse_json_file(metrics_path)
        checks["metrics_valid_json"] = metrics_data is not None
        # Only numbers in required keys
        required_keys = [
            "total_income_2024",
            "total_expenses_2024",
            "savings_2024",
            "savings_rate_2024",
            "net_worth_2024_12_31",
        ]
        # Initialize dependent checks to False
        checks["metrics_has_required_keys"] = False
        checks["metrics_values_types_numeric"] = False
        checks["metrics_values_match_expected"] = False
        if checks["metrics_valid_json"]:
            checks["metrics_has_required_keys"] = all(k in metrics_data for k in required_keys)
            if checks["metrics_has_required_keys"]:
                types_ok = all(is_number(metrics_data.get(k)) for k in required_keys)
                checks["metrics_values_types_numeric"] = types_ok
                if types_ok:
                    inc = float(metrics_data["total_income_2024"])
                    exp = float(metrics_data["total_expenses_2024"])
                    sav = float(metrics_data["savings_2024"])
                    sr = float(metrics_data["savings_rate_2024"])
                    nw = float(metrics_data["net_worth_2024_12_31"])
                    # Tolerances
                    ok_inc = approx_equal(inc, 72000.0, 200.0)
                    ok_exp = approx_equal(exp, 34900.0, 200.0)
                    ok_sav = approx_equal(sav, 37100.0, 200.0)
                    ok_sr = approx_equal(sr, 0.515, 0.01)
                    ok_nw = approx_equal(nw, 65100.0, 500.0)
                    checks["metrics_values_match_expected"] = all([ok_inc, ok_exp, ok_sav, ok_sr, ok_nw])
    else:
        # Ensure all dependent checks are present and False
        checks["metrics_valid_json"] = False
        checks["metrics_has_required_keys"] = False
        checks["metrics_values_types_numeric"] = False
        checks["metrics_values_match_expected"] = False

    # 2) report.md checks
    report_path = os.path.join(output_dir, "report.md")
    checks["report_exists"] = os.path.isfile(report_path)
    report_text = read_text(report_path) if checks["report_exists"] else None

    # Required report checks
    checks["report_mentions_networth_and_date"] = False
    checks["report_has_top5_section"] = False
    checks["report_has_expense_amounts"] = False
    checks["report_has_5_recommendations"] = False
    checks["report_has_disclaimer"] = False

    if checks["report_exists"]:
        has_date = contains_case_insensitive(report_text, "2024-12-31")
        has_nw_val = find_any_number_within(report_text or "", 65100.0, 500.0)
        checks["report_mentions_networth_and_date"] = bool(has_date and has_nw_val)
        checks["report_has_top5_section"] = contains_case_insensitive(report_text, "Top 5 expense categories")

        # Category amount checks; check lines containing the category for approximate amounts
        def category_amount_ok(cat: str, target: float, tol: float) -> bool:
            lines = lines_with_keyword(report_text or "", cat)
            if not lines:
                return False
            for ln in lines:
                if find_any_number_within(ln, target, tol):
                    return True
            # fallback: any number in entire doc close to target (simple substring style)
            return find_any_number_within(report_text or "", target, tol)

        rent_ok = category_amount_ok("Rent", 18000.0, 600.0)
        groceries_ok = category_amount_ok("Groceries", 4800.0, 400.0)
        travel_ok = category_amount_ok("Travel", 2500.0, 400.0)
        dining_ok = category_amount_ok("Dining", 2400.0, 400.0)
        utilities_ok = category_amount_ok("Utilities", 2400.0, 400.0)
        checks["report_has_expense_amounts"] = all([rent_ok, groceries_ok, travel_ok, dining_ok, utilities_ok])

        checks["report_has_5_recommendations"] = count_bullet_recommendations(report_text or "") >= 5
        checks["report_has_disclaimer"] = (
            contains_case_insensitive(report_text, "educational")
            or contains_case_insensitive(report_text, "not financial advice")
        )

    # 3) queries.md checks
    queries_path = os.path.join(output_dir, "queries.md")
    checks["queries_exists"] = os.path.isfile(queries_path)
    queries_text = read_text(queries_path) if checks["queries_exists"] else None

    checks["queries_q1_patterns"] = False
    checks["queries_q2_patterns"] = False
    checks["queries_q3_patterns"] = False

    if checks["queries_exists"]:
        h1 = "Monthly Expenses by Category (2024)"
        h2 = "Net Worth Over Time (USD, Monthly)"
        h3 = "Top 5 Expense Categories for 2024"

        # Ensure headings exist
        h1_ok = has_heading(queries_text or "", h1)
        h2_ok = has_heading(queries_text or "", h2)
        h3_ok = has_heading(queries_text or "", h3)

        seg1 = segment_under_heading(queries_text or "", h1, [h2, h3]) if h1_ok else ""
        seg2 = segment_under_heading(queries_text or "", h2, [h1, h3]) if h2_ok else ""
        seg3 = segment_under_heading(queries_text or "", h3, [h1, h2]) if h3_ok else ""

        q1_patterns = [
            "SELECT year, month",
            "WHERE account ~ 'Expenses:' AND year = 2024",
            "GROUP BY year, month, account",
        ]
        q2_patterns = [
            "account_sortkey(account) < 3",
            "sum(convert(position, 'USD')) AS net_worth",
            "GROUP BY year, month",
        ]
        q3_patterns = [
            "WHERE account ~ 'Expenses:' AND year = 2024",
            "ORDER BY amount DESC",
            "LIMIT 5",
        ]
        checks["queries_q1_patterns"] = h1_ok and text_contains_all_patterns(seg1, q1_patterns)
        checks["queries_q2_patterns"] = h2_ok and text_contains_all_patterns(seg2, q2_patterns)
        checks["queries_q3_patterns"] = h3_ok and text_contains_all_patterns(seg3, q3_patterns)

    # 4) budget.yaml checks
    budget_path = os.path.join(output_dir, "budget.yaml")
    checks["budget_exists"] = os.path.isfile(budget_path)
    checks["budget_valid_yaml_mapping"] = False
    checks["budget_operating_currency_usd"] = False
    checks["budget_monthly_income_approx_6000"] = False
    checks["budget_savings_min_2000"] = False
    checks["budget_allocations_structure_food_dining_travel"] = False
    checks["budget_dining_at_most_160"] = False
    checks["budget_travel_at_most_250"] = False
    checks["budget_allocations_sum_leq_3600"] = False

    if checks["budget_exists"]:
        budget_text = read_text(budget_path) or ""
        parsed = parse_simple_yaml(budget_text)
        if isinstance(parsed, dict):
            checks["budget_valid_yaml_mapping"] = True
            # Keys
            oc = parsed.get("operating_currency")
            mi = parsed.get("monthly_income")
            sv = parsed.get("savings")
            al = parsed.get("allocations")

            checks["budget_operating_currency_usd"] = oc == "USD"
            if is_number(mi):
                checks["budget_monthly_income_approx_6000"] = approx_equal(float(mi), 6000.0, 50.0)
            if is_number(sv):
                checks["budget_savings_min_2000"] = float(sv) >= 2000.0

            # allocations structure and constraints
            if isinstance(al, dict):
                # Find Food -> Dining numeric
                food = al.get("Food")
                dining_ok_flag = False
                if isinstance(food, dict) and "Dining" in food and is_number(food.get("Dining")):
                    dining_val = float(food.get("Dining"))
                    dining_ok_flag = True
                    checks["budget_dining_at_most_160"] = dining_val <= 160.0

                # Find Travel (recursively)
                travel_val = find_key_recursive(al, "Travel")
                travel_ok_flag = False
                if travel_val is not None and is_number(travel_val):
                    travel_ok_flag = True
                    checks["budget_travel_at_most_250"] = float(travel_val) <= 250.0

                checks["budget_allocations_structure_food_dining_travel"] = bool(dining_ok_flag and travel_ok_flag)

                # Sum of allocations numeric leaves
                total_alloc = sum_numeric_leaves(al)
                checks["budget_allocations_sum_leq_3600"] = total_alloc <= 3600.0

    # Compute reward as average of all checks
    check_values = list(checks.values())
    passed = sum(1 for v in check_values if v)
    total = len(check_values)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure no-op baseline yields exactly 0.0 when output dir missing or empty of required artifacts
    # If none of the four primary files exist, force reward to 0.0
    required_files_exist = any([
        checks.get("metrics_exists", False),
        checks.get("report_exists", False),
        checks.get("queries_exists", False),
        checks.get("budget_exists", False),
    ])
    if not required_files_exist:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()