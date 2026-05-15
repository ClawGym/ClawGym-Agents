import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "plan_exists": False,
        "plan_json_valid": False,
        "plan_has_filters": False,
        "plan_filters_are_A": False,
        "plan_has_scenarios_count": False,
        "plan_scenarios_fields": False,
        "plan_routes_fields": False,
        "plan_memo_handling": False,
        "safety_exists": False,
        "safety_has_keywords": False,
        "tests_exist": False,
        "tests_imports_and_asserts": False,
        "docs_citations_exists": False,
        "docs_citations_lines": False,
        "memory_exists": False,
        "memory_has_headings": False,
    }

    # Paths
    plan_path = os.path.join(output_dir, "plan.json")
    safety_path = os.path.join(output_dir, "safety.md")
    tests_path = os.path.join(output_dir, "tests", "test_plan.py")
    docs_citations_path = os.path.join(output_dir, "docs_citations.md")
    memory_path = os.path.join(output_dir, "memory.md")

    # 1) plan.json checks
    plan_data = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
            checks["plan_json_valid"] = True
        except Exception:
            plan_data = None

    scenarios_list = []
    if checks["plan_json_valid"]:
        # Accept either a top-level array of scenarios or object with "scenarios" key
        if isinstance(plan_data, list):
            scenarios_list = plan_data
        elif isinstance(plan_data, dict):
            if "scenarios" in plan_data and isinstance(plan_data["scenarios"], list):
                scenarios_list = plan_data["scenarios"]
            else:
                scenarios_list = []
        else:
            scenarios_list = []

        if isinstance(scenarios_list, list) and len(scenarios_list) >= 1:
            checks["plan_has_scenarios_count"] = True

        # Filters: Either present at root or per-scenario, must be "A"
        kyc_filter_root = None
        log_filter_root = None
        if isinstance(plan_data, dict):
            kyc_filter_root = plan_data.get("kyc_filter")
            log_filter_root = plan_data.get("log_filter")

        has_filters = False
        filters_are_A = False
        if kyc_filter_root is not None and log_filter_root is not None:
            has_filters = True
            if kyc_filter_root == "A" and log_filter_root == "A":
                filters_are_A = True
        else:
            # Check per-scenario
            all_have = True
            all_A = True
            for sc in scenarios_list:
                if not isinstance(sc, dict):
                    all_have = False
                    all_A = False
                    break
                kf = sc.get("kyc_filter")
                lf = sc.get("log_filter")
                if kf is None or lf is None:
                    all_have = False
                    all_A = False
                    break
                if kf != "A" or lf != "A":
                    all_A = False
            has_filters = all_have
            filters_are_A = all_A
        if has_filters:
            checks["plan_has_filters"] = True
        if filters_are_A:
            checks["plan_filters_are_A"] = True

        # Scenario fields and routes
        required_scenario_fields = [
            "scenario_id", "from", "to", "from_network", "to_network",
            "amount_from", "address", "address_valid", "min_ok",
            "minimum_discovered", "bridge_considered", "routes"
        ]
        scenario_fields_ok = True
        routes_ok = True
        memo_ok_global = True  # will remain True if no memo-coin present or all memo-coin scenarios handled
        memo_coin_present = False

        for sc in scenarios_list:
            if not isinstance(sc, dict):
                scenario_fields_ok = False
                routes_ok = False
                memo_ok_global = False
                break

            # Check scenario required fields present
            for fld in required_scenario_fields:
                if fld not in sc:
                    scenario_fields_ok = False
                    break
            if not scenario_fields_ok:
                break

            # Type checks for some fields
            if not isinstance(sc.get("scenario_id"), str):
                scenario_fields_ok = False
            if not isinstance(sc.get("from"), str) or not isinstance(sc.get("to"), str):
                scenario_fields_ok = False
            if not isinstance(sc.get("from_network"), str) or not isinstance(sc.get("to_network"), str):
                scenario_fields_ok = False
            if not is_number(sc.get("amount_from")):
                scenario_fields_ok = False
            if not isinstance(sc.get("address"), str):
                scenario_fields_ok = False
            if not isinstance(sc.get("address_valid"), bool):
                scenario_fields_ok = False
            if not isinstance(sc.get("min_ok"), bool):
                scenario_fields_ok = False
            # minimum_discovered can be number or None
            md = sc.get("minimum_discovered")
            if not (md is None or is_number(md)):
                scenario_fields_ok = False
            if not isinstance(sc.get("bridge_considered"), bool):
                scenario_fields_ok = False

            # Routes checks
            routes = sc.get("routes")
            if not isinstance(routes, list) or len(routes) < 2:
                routes_ok = False
            else:
                for r in routes:
                    if not isinstance(r, dict):
                        routes_ok = False
                        break
                    # Required route fields
                    rf_required = ["provider", "engine", "kyc", "log_policy", "fixed", "eta", "amount_from", "amount_to"]
                    for rf in rf_required:
                        if rf not in r:
                            routes_ok = False
                            break
                    if not routes_ok:
                        break
                    # Types
                    if not isinstance(r.get("provider"), str):
                        routes_ok = False
                    if not isinstance(r.get("engine"), str):
                        routes_ok = False
                    if not isinstance(r.get("kyc"), str):
                        routes_ok = False
                    if not isinstance(r.get("log_policy"), str):
                        routes_ok = False
                    if not isinstance(r.get("fixed"), bool):
                        routes_ok = False
                    if not is_number(r.get("eta")):
                        routes_ok = False
                    if not is_number(r.get("amount_from")):
                        routes_ok = False
                    if not is_number(r.get("amount_to")):
                        routes_ok = False
                    if not routes_ok:
                        break

            # Memo coins handling
            sc_from = (sc.get("from") or "").lower()
            sc_to = (sc.get("to") or "").lower()
            memo_required = sc_from in ("xrp", "xlm") or sc_to in ("xrp", "xlm")
            if memo_required:
                memo_coin_present = True
                # Must include memo field (string or None) and memo_required True
                if "memo_required" not in sc:
                    memo_ok_global = False
                else:
                    if sc.get("memo_required") is not True:
                        memo_ok_global = False
                # memo can be string or None (null)
                if "memo" not in sc:
                    memo_ok_global = False
                else:
                    mv = sc.get("memo")
                    if not (mv is None or isinstance(mv, str)):
                        memo_ok_global = False

        if scenario_fields_ok:
            checks["plan_scenarios_fields"] = True
        if routes_ok:
            checks["plan_routes_fields"] = True
        # Memo handling passes if either no memo coin present OR all memo-coin scenarios satisfied
        if not memo_coin_present or memo_ok_global:
            checks["plan_memo_handling"] = True

    # 2) safety.md checks
    if os.path.isfile(safety_path):
        checks["safety_exists"] = True
        content = read_text(safety_path) or ""
        kw = ["minimum", "address", "memo", "refund", "regulatory", "poll", "backoff", "expiry"]
        found = set()
        lower = content.lower()
        for k in kw:
            if k in lower:
                found.add(k)
        if len(found) >= 5:
            checks["safety_has_keywords"] = True

    # 3) tests file checks
    if os.path.isfile(tests_path):
        checks["tests_exist"] = True
        tcontent = read_text(tests_path) or ""
        # Minimal structural checks
        has_import_json = "import json" in tcontent
        has_test_fn = re.search(r"\ndef\s+test_[A-Za-z0-9_]*\s*\(", tcontent) is not None
        has_assert = "assert " in tcontent
        mentions_plan = "plan.json" in tcontent
        if has_import_json and has_test_fn and has_assert and mentions_plan:
            checks["tests_imports_and_asserts"] = True

    # 4) docs_citations.md
    if os.path.isfile(docs_citations_path):
        checks["docs_citations_exists"] = True
        dcontent = read_text(docs_citations_path) or ""
        lines = [ln.strip() for ln in dcontent.splitlines() if ln.strip()]
        cnt = 0
        for ln in lines:
            if ln.startswith("Doc:"):
                # Must include a path ending with .md and an em dash with reason
                # Accept any text but require '.md' and '—' present
                if (".md" in ln) and ("—" in ln):
                    cnt += 1
        if cnt >= 2:
            checks["docs_citations_lines"] = True

    # 5) memory.md
    if os.path.isfile(memory_path):
        checks["memory_exists"] = True
        mcontent = read_text(memory_path) or ""
        required_headings = [
            "# Self-Improving Memory",
            "## Confirmed Preferences",
            "## Active Patterns",
            "## Recent (last 7 days)",
        ]
        if all(h in mcontent for h in required_headings):
            checks["memory_has_headings"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    # Ensure no-op baseline: if no artifacts (plan missing), set reward to 0.0
    if not checks["plan_exists"]:
        reward = 0.0

    # Print JSON result (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()