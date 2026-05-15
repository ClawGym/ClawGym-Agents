import csv
import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            lines = f.read().splitlines()
        if not lines:
            return [], ""
        header_line = lines[0].strip()
        # Parse remaining rows using csv.reader to handle commas/quotes
        reader = csv.reader(lines[1:])
        for r in reader:
            # Normalize to 6 columns if possible
            if len(r) >= 6:
                rows.append([c.strip() for c in r[:6]])
            else:
                # Pad short rows to avoid index errors
                padded = r + ([""] * (6 - len(r)))
                rows.append([c.strip() for c in padded])
        return rows, header_line
    except Exception:
        return [], ""

def find_csv_match(rows, rule_match, location_substrings=None, entity_any=None, before_contains=None, after_contains=None, details_contains_any=None, location_must_contain_any=None, any_field_contains_any=None, case_sensitive=True):
    """
    rows: list of [rule, entity, location, before, after, details]
    Match criteria:
    - rule_match: exact match for rule (case-sensitive unless case_sensitive=False)
    - location_substrings: list of substrings that must all appear in location (respecting case_sensitive)
    - location_must_contain_any: list of substrings where at least one must appear in location
    - before_contains: substring that must appear in before (None to skip)
    - after_contains: substring that must appear in after (None to skip)
    - details_contains_any: list where at least one substring must appear in details (None to skip)
    - any_field_contains_any: list where at least one substring must appear across before/after/details combined (None to skip)
    """
    for row in rows:
        if len(row) < 6:
            continue
        rule, entity, location, before, after, details = row[:6]
        r_rule = rule if case_sensitive else rule.lower()
        target_rule = rule_match if case_sensitive else rule_match.lower()
        if r_rule != target_rule:
            continue

        loc = location if case_sensitive else location.lower()
        bf = before if case_sensitive else before.lower()
        af = after if case_sensitive else after.lower()
        det = details if case_sensitive else details.lower()

        # All required substrings in location
        if location_substrings:
            for sub in location_substrings:
                sub_cmp = sub if case_sensitive else sub.lower()
                if sub_cmp not in loc:
                    break
            else:
                pass
            if any((sub if case_sensitive else sub.lower()) not in loc for sub in location_substrings):
                continue

        # At least one of provided substrings in location
        if location_must_contain_any:
            ok_any = False
            for sub in location_must_contain_any:
                sub_cmp = sub if case_sensitive else sub.lower()
                if sub_cmp in loc:
                    ok_any = True
                    break
            if not ok_any:
                continue

        if before_contains is not None:
            sub_cmp = before_contains if case_sensitive else before_contains.lower()
            if sub_cmp not in bf:
                continue

        if after_contains is not None:
            sub_cmp = after_contains if case_sensitive else after_contains.lower()
            if sub_cmp not in af:
                continue

        if details_contains_any:
            ok_any = False
            for sub in details_contains_any:
                sub_cmp = sub if case_sensitive else sub.lower()
                if sub_cmp in det:
                    ok_any = True
                    break
            if not ok_any:
                continue

        if any_field_contains_any:
            combined = (bf + " " + af + " " + det)
            combined = combined if case_sensitive else combined.lower()
            ok_any = False
            for sub in any_field_contains_any:
                sub_cmp = sub if case_sensitive else sub.lower()
                if sub_cmp in combined:
                    ok_any = True
                    break
            if not ok_any:
                continue

        # entity_any is advisory; do not enforce entity match strictly per spec.
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "diff_json_exists": False,
        "diff_json_valid": False,
        "breaking_csv_exists": False,
        "csv_header_correct": False,
        "csv_has_endpoint_removed": False,
        "csv_has_required_param_added": False,
        "csv_has_field_type_changed": False,
        "csv_has_response_field_removed": False,
        "csv_has_enum_value_removed": False,
        "csv_has_auth_requirement_changed": False,
        "migration_plan_exists": False,
        "migration_sections_present": False,
        "migration_rules_mentioned": False,
    }

    # 1) diff.json checks
    diff_path = os.path.join(output_dir, "diff.json")
    if os.path.isfile(diff_path):
        checks["diff_json_exists"] = True
        if load_json(diff_path) is not None:
            checks["diff_json_valid"] = True

    # 2) breaking_changes.csv checks
    csv_path = os.path.join(output_dir, "breaking_changes.csv")
    rows = []
    header_line = ""
    if os.path.isfile(csv_path):
        checks["breaking_csv_exists"] = True
        rows, header_line = parse_csv_rows(csv_path)
        if header_line == "rule,entity,location,before,after,details":
            checks["csv_header_correct"] = True

        # Required rows
        # a) endpoint-removed for GET /v1/transactions
        checks["csv_has_endpoint_removed"] = find_csv_match(
            rows,
            rule_match="endpoint-removed",
            location_substrings=["GET /v1/transactions"],
            case_sensitive=True
        )

        # b) required-param-added includeBalances on GET /v1/accounts/{id}
        # includeBalances may be in location or details
        found_required_param = False
        # Try includeBalances in location
        if find_csv_match(
            rows,
            rule_match="required-param-added",
            location_substrings=["GET /v1/accounts/{id}"],
            case_sensitive=True
        ):
            # Now ensure includeBalances is in location OR details
            for r in rows:
                if len(r) < 6:
                    continue
                rule, entity, location, before, after, details = r[:6]
                if rule == "required-param-added" and "GET /v1/accounts/{id}" in location and ("includeBalances" in location or "includeBalances" in details):
                    found_required_param = True
                    break
        checks["csv_has_required_param_added"] = found_required_param

        # c) field-type-changed Transaction.amount number -> string
        checks["csv_has_field_type_changed"] = find_csv_match(
            rows,
            rule_match="field-type-changed",
            location_substrings=["#/components/schemas/Transaction", "amount"],
            before_contains="number",
            after_contains="string",
            case_sensitive=False
        )

        # d) response-field-removed Transaction.metadata
        checks["csv_has_response_field_removed"] = find_csv_match(
            rows,
            rule_match="response-field-removed",
            location_substrings=["#/components/schemas/Transaction", "metadata"],
            case_sensitive=False
        )

        # e) enum-value-removed Transaction.currency with EUR mentioned
        checks["csv_has_enum_value_removed"] = find_csv_match(
            rows,
            rule_match="enum-value-removed",
            location_substrings=["#/components/schemas/Transaction", "currency"],
            any_field_contains_any=["EUR"],
            case_sensitive=True
        )

        # f) auth-requirement-changed global security bearer -> api key
        # location must mention security, and combined fields must include both 'bearer' and 'api'
        has_auth_change = False
        for r in rows:
            if len(r) < 6:
                continue
            rule, entity, location, before, after, details = r[:6]
            if rule != "auth-requirement-changed":
                continue
            if "security" not in location.lower():
                continue
            combined = (before + " " + after + " " + details).lower()
            if ("bearer" in combined) and ("api" in combined):
                has_auth_change = True
                break
        checks["csv_has_auth_requirement_changed"] = has_auth_change

    # 3) migration_plan.md checks
    mig_path = os.path.join(output_dir, "migration_plan.md")
    if os.path.isfile(mig_path):
        checks["migration_plan_exists"] = True
        content = read_text(mig_path) or ""
        lower = content.lower()

        # Section keywords (case-insensitive)
        section_keywords = ["breaking changes", "mitigations", "versioning", "communication", "testing", "timeline"]
        if all(k in lower for k in section_keywords):
            checks["migration_sections_present"] = True

        # Rule names mentioned (case-insensitive)
        rule_names = [
            "endpoint-removed",
            "required-param-added",
            "field-type-changed",
            "response-field-removed",
            "enum-value-removed",
            "auth-requirement-changed",
        ]
        if all(rn in lower for rn in rule_names):
            checks["migration_rules_mentioned"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Enforce no-op baseline: if output missing or empty, reward must be exactly 0.0
    # Determine if there are any files in output
    has_any_output = False
    if os.path.isdir(output_dir):
        for _root, _dirs, files in os.walk(output_dir):
            if files:
                has_any_output = True
                break
    if not has_any_output:
        reward = 0.0

    # Print final JSON (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()