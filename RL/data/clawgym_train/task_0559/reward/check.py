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

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_metrics_baseline(metrics_path):
    metrics = load_json(metrics_path)
    if not isinstance(metrics, dict):
        return None, None
    # Primary expected keys
    p95 = metrics.get("p95_ms")
    p99 = metrics.get("p99_ms")
    # Fallbacks if structured differently
    if (p95 is None or p99 is None) and isinstance(metrics.get("latency"), dict):
        lat = metrics["latency"]
        p95 = p95 if p95 is not None else lat.get("p95_ms") or lat.get("p95")
        p99 = p99 if p99 is not None else lat.get("p99_ms") or lat.get("p99")
    # Ensure numeric
    if isinstance(p95, (int, float)) and isinstance(p99, (int, float)):
        return p95, p99
    return None, None

def check_problem_statement(path):
    result = {
        "problem_statement_exists": False,
        "problem_statement_has_endpoint_p95_p99_number": False,
    }
    txt = read_text(path)
    if txt is None:
        return result
    result["problem_statement_exists"] = True
    lower = txt.lower()
    has_endpoint = "/orders" in txt
    has_p95 = "p95" in lower
    has_p99 = "p99" in lower
    has_number = bool(re.search(r"\d", txt))
    if has_endpoint and has_p95 and has_p99 and has_number:
        result["problem_statement_has_endpoint_p95_p99_number"] = True
    return result

def check_analysis_json(path, metrics_p95, metrics_p99):
    result = {
        "analysis_json_exists": False,
        "analysis_json_valid_structure": False,
        "analysis_engine_postgresql": False,
        "analysis_baseline_matches_input": False,
        "analysis_dominant_costs_contains_known": False,
        "analysis_risks_contain_required": False,
    }
    data = load_json(path)
    if data is None:
        return result
    result["analysis_json_exists"] = True

    # Validate required structure
    has_keys = all(k in data for k in ["engine", "baseline", "exact_query_summary", "dominant_costs", "root_cause", "risks"])
    baseline_ok = isinstance(data.get("baseline"), dict) and \
                  isinstance(data["baseline"].get("p95_ms"), (int, float)) and \
                  isinstance(data["baseline"].get("p99_ms"), (int, float))
    eqs_ok = isinstance(data.get("exact_query_summary"), str)
    rc_ok = isinstance(data.get("root_cause"), str)
    dom_ok = isinstance(data.get("dominant_costs"), list)
    risks_ok = isinstance(data.get("risks"), list)

    if has_keys and baseline_ok and eqs_ok and rc_ok and dom_ok and risks_ok:
        result["analysis_json_valid_structure"] = True

    # Engine check
    engine = data.get("engine")
    if isinstance(engine, str) and engine.strip().lower() == "postgresql":
        result["analysis_engine_postgresql"] = True

    # Baseline comparison with input metrics
    try:
        a_p95 = data["baseline"]["p95_ms"]
        a_p99 = data["baseline"]["p99_ms"]
        if metrics_p95 is not None and metrics_p99 is not None and a_p95 == metrics_p95 and a_p99 == metrics_p99:
            result["analysis_baseline_matches_input"] = True
    except Exception:
        pass

    # Dominant costs contains known keywords
    known_subs = ["seq scan", "sort", "hash", "nested loop", "spill"]
    dom_list = data.get("dominant_costs") or []
    found_dom = False
    for el in dom_list:
        if isinstance(el, str):
            low = el.lower()
            if any(k in low for k in known_subs):
                found_dom = True
                break
    if found_dom:
        result["analysis_dominant_costs_contains_known"] = True

    # Risks contain required phrases
    required_risks = ["write amplification", "stale statistics", "parameter sniffing"]
    risks_list = data.get("risks") or []
    risks_joined = " | ".join([str(r) for r in risks_list]).lower()
    if all(req in risks_joined for req in required_risks):
        result["analysis_risks_contain_required"] = True

    return result

def check_proposals(path):
    result = {
        "proposals_exists": False,
        "proposals_has_two_create_index": False,
        "proposals_has_concurrently": False,
        "proposals_has_orders_composite_status_created_at": False,
        "proposals_has_customers_region_index": False,
    }
    txt = read_text(path)
    if txt is None:
        return result
    result["proposals_exists"] = True
    lower = txt.lower()

    # CREATE INDEX count
    create_count = len(re.findall(r"\bcreate\s+index\b", lower))
    if create_count >= 2:
        result["proposals_has_two_create_index"] = True

    # CONCURRENTLY presence
    if "concurrently" in lower:
        result["proposals_has_concurrently"] = True

    # Orders composite index detection near CREATE INDEX lines
    lines = txt.splitlines()
    found_orders_composite = False
    found_customers_region = False
    for i, line in enumerate(lines):
        combined = line
        if i + 1 < len(lines):
            combined_next = line + " " + lines[i + 1]
        else:
            combined_next = line
        l_combined = combined.lower()
        l_next = combined_next.lower()
        # Orders composite: look for a CREATE INDEX line (or next line) mentioning orders and (status, created_at
        if re.search(r"\bcreate\s+index\b", l_combined) or re.search(r"\bcreate\s+index\b", l_next):
            if ("orders" in l_combined or "orders" in l_next) and ("(status, created_at" in l_combined.lower() or "(status, created_at" in l_next.lower()):
                found_orders_composite = True
            # Customers region index
            if (("customers" in l_combined and "(region)" in l_combined.lower()) or
                ("customers" in l_next and "(region)" in l_next.lower())):
                found_customers_region = True
        # Early exit if both found
        if found_orders_composite and found_customers_region:
            break

    if found_orders_composite:
        result["proposals_has_orders_composite_status_created_at"] = True
    if found_customers_region:
        result["proposals_has_customers_region_index"] = True

    return result

def check_rewrite(path):
    result = {
        "rewrite_exists": False,
        "rewrite_is_select_contains_seek_order_limit_no_offset": False,
    }
    txt = read_text(path)
    if txt is None:
        return result
    result["rewrite_exists"] = True
    low = txt.lower()
    has_select = "select" in low
    has_seek = re.search(r"created_at\s*<", low) is not None
    has_order = "order by" in low
    has_limit = "limit" in low
    has_offset = "offset" in low
    if has_select and has_seek and has_order and has_limit and not has_offset:
        result["rewrite_is_select_contains_seek_order_limit_no_offset"] = True
    return result

def check_verification(path):
    result = {
        "verification_exists": False,
        "verification_mentions_required": False,
    }
    txt = read_text(path)
    if txt is None:
        return result
    result["verification_exists"] = True
    low = txt.lower()
    required = [
        "explain analyze",
        "analyze",
        "parameter sniffing",
        "rollback",
        "concurrently",
        "write amplification",
    ]
    has_required = all(req in low for req in required)
    has_buffer_or_cache = ("buffer" in low) or ("cache" in low)
    if has_required and has_buffer_or_cache:
        result["verification_mentions_required"] = True
    return result

def check_rollback(path):
    result = {
        "rollback_exists": False,
        "rollback_has_two_drop_index": False,
    }
    txt = read_text(path)
    if txt is None:
        return result
    result["rollback_exists"] = True
    count = len(re.findall(r"\bdrop\s+index\b", txt, flags=re.IGNORECASE))
    if count >= 2:
        result["rollback_has_two_drop_index"] = True
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but kept for completeness

    # Paths to outputs
    problem_path = os.path.join(output_dir, "problem_statement.md")
    analysis_path = os.path.join(output_dir, "analysis.json")
    proposals_path = os.path.join(output_dir, "proposals.txt")
    rewrite_path = os.path.join(output_dir, "rewrite.txt")
    verification_path = os.path.join(output_dir, "verification.md")
    rollback_path = os.path.join(output_dir, "rollback.txt")

    # Reference input for baseline comparison
    metrics_path = os.path.join(input_dir, "metrics.json")
    metrics_p95, metrics_p99 = get_metrics_baseline(metrics_path)

    checks = {}

    # Problem statement checks
    checks.update(check_problem_statement(problem_path))

    # Analysis checks
    checks.update(check_analysis_json(analysis_path, metrics_p95, metrics_p99))

    # Proposals checks
    checks.update(check_proposals(proposals_path))

    # Rewrite checks
    checks.update(check_rewrite(rewrite_path))

    # Verification checks
    checks.update(check_verification(verification_path))

    # Rollback checks
    checks.update(check_rollback(rollback_path))

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline: if none of the core deliverable files exist, reward = 0.0
    deliverables = [problem_path, analysis_path, proposals_path, rewrite_path, verification_path, rollback_path]
    any_deliverable_exists = any(os.path.isfile(p) for p in deliverables)

    if not any_deliverable_exists:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Bound to [0,1]
        reward = max(0.0, min(1.0, reward))

    # Print result as single JSON object
    result_obj = {"reward": reward}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()