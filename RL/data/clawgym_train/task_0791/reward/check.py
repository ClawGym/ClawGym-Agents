import json
import os
import sys
from typing import Any, Dict, List, Set, Tuple

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def load_text(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def load_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def check_checklist_md(path: str) -> Dict[str, bool]:
    checks = {
        "has_checklist_md": False,
        "checklist_has_all_categories": False,
        "checklist_has_min_checkboxes": False,
        "checklist_has_priority_markers": False,
        "checklist_has_access_tiers": False,
        "checklist_mentions_watermark": False,
        "checklist_mentions_download": False,
    }
    if not os.path.isfile(path):
        return checks
    checks["has_checklist_md"] = True
    ok, text = load_text(path)
    if not ok:
        return checks
    lower = text.lower()

    # Categories
    required_categories = [
        "corporate",
        "financial",
        "legal",
        "commercial",
        "product & tech",
        "hr & team",
        "compliance",
    ]
    if all(cat in lower for cat in required_categories):
        checks["checklist_has_all_categories"] = True

    # Checkbox lines
    checkbox_count = 0
    for line in text.splitlines():
        if line.lstrip().startswith("- [ ]"):
            checkbox_count += 1
    if checkbox_count >= 10:
        checks["checklist_has_min_checkboxes"] = True

    # Priority markers
    if ("🔴" in text) and ("🟡" in text) and ("🟢" in text):
        checks["checklist_has_priority_markers"] = True

    # Access tiers
    if ("pre-nda" in lower) and ("post-nda" in lower) and ("management-only" in lower):
        checks["checklist_has_access_tiers"] = True

    # Watermark and download mentions
    if "watermark" in lower:
        checks["checklist_mentions_watermark"] = True
    if "download" in lower:
        checks["checklist_mentions_download"] = True

    return checks

def check_gap_report(path: str) -> Dict[str, bool]:
    checks = {
        "has_gap_json": False,
        "gap_json_has_missing_array": False,
        "gap_missing_items_valid_schema": False,
        "gap_missing_contains_cash_flow": False,
        "gap_missing_contains_tax_return": False,
        "gap_missing_contains_ip_assignment": False,
    }
    if not os.path.isfile(path):
        return checks
    ok, data = load_json(path)
    if not ok:
        return checks
    checks["has_gap_json"] = True

    if isinstance(data, dict) and isinstance(data.get("missing"), list):
        checks["gap_json_has_missing_array"] = True
        missing = data["missing"]
        schema_ok = True
        has_cash_flow = False
        has_tax_return = False
        has_ip_assignment = False
        for item in missing:
            if not isinstance(item, dict):
                schema_ok = False
                break
            doc = item.get("document")
            cat = item.get("category")
            pri = item.get("priority")
            urg = item.get("urgency")
            pth = item.get("prep_time_hours")
            notes = item.get("notes")
            if not (isinstance(doc, str) and isinstance(cat, str) and isinstance(notes, str)):
                schema_ok = False
                break
            if not isinstance(pri, str) or pri.lower() not in {"must-have", "should-have", "nice-to-have"}:
                schema_ok = False
                break
            if not isinstance(urg, str) or urg.lower() not in {"high", "medium", "low"}:
                schema_ok = False
                break
            if not is_number(pth):
                schema_ok = False
                break
            # Substring checks
            dl = doc.lower()
            if "cash flow" in dl:
                has_cash_flow = True
            if "tax return" in dl:
                has_tax_return = True
            if "ip assignment" in dl:
                has_ip_assignment = True
        if schema_ok:
            checks["gap_missing_items_valid_schema"] = True
        if has_cash_flow:
            checks["gap_missing_contains_cash_flow"] = True
        if has_tax_return:
            checks["gap_missing_contains_tax_return"] = True
        if has_ip_assignment:
            checks["gap_missing_contains_ip_assignment"] = True
    return checks

def check_ads_summary(path: str) -> Dict[str, bool]:
    checks = {
        "has_ads_summary": False,
        "ads_has_required_top_keys": False,
        "ads_intent_has_goal_and_90day_timeline": False,
        "ads_handoff_has_platforms_and_kpi": False,
    }
    if not os.path.isfile(path):
        return checks
    ok, data = load_json(path)
    if not ok:
        return checks
    checks["has_ads_summary"] = True

    required_top = ["intent_summary", "findings", "action_plan", "risks_and_guardrails", "handoff_payload"]
    if all(k in data for k in required_top):
        checks["ads_has_required_top_keys"] = True

    intent = data.get("intent_summary")
    if isinstance(intent, dict):
        goal = intent.get("goal")
        scope = intent.get("scope")
        if isinstance(goal, str) and isinstance(scope, dict):
            timeline = scope.get("timeline")
            if isinstance(timeline, str) and "90" in timeline:
                checks["ads_intent_has_goal_and_90day_timeline"] = True

    payload = data.get("handoff_payload")
    if isinstance(payload, dict):
        platforms = payload.get("platforms")
        kpi = payload.get("kpi")
        platforms_ok = isinstance(platforms, list)
        kpi_ok = isinstance(kpi, (str, dict))
        if platforms_ok and kpi_ok:
            checks["ads_handoff_has_platforms_and_kpi"] = True

    return checks

def check_queue_plan(path: str) -> Dict[str, bool]:
    checks = {
        "has_queue_plan": False,
        "queue_has_tasks_array": False,
        "queue_tasks_schema_valid": False,
        "queue_has_required_task_ids": False,
        "queue_assemble_depends_on_both": False,
        "queue_dependencies_exist": False,
        "queue_acyclic": False,
    }
    if not os.path.isfile(path):
        return checks
    ok, data = load_json(path)
    if not ok:
        return checks
    checks["has_queue_plan"] = True

    tasks = None
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        tasks = data["tasks"]
        checks["queue_has_tasks_array"] = True
    else:
        return checks

    # Validate schema for each task
    schema_ok = True
    ids: Set[str] = set()
    for t in tasks:
        if not isinstance(t, dict):
            schema_ok = False
            break
        tid = t.get("id")
        ttype = t.get("type")
        prio = t.get("priority")
        deps = t.get("dependencies")
        retry = t.get("retryPolicy")
        if not (isinstance(tid, str) and isinstance(ttype, str) and is_number(prio) and isinstance(deps, list) and isinstance(retry, dict)):
            schema_ok = False
            break
        max_attempts = retry.get("maxAttempts")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
            schema_ok = False
            break
        # Optional timeoutMs can be any number; do not enforce
        ids.add(tid)
    if schema_ok:
        checks["queue_tasks_schema_valid"] = True

    # Required task IDs
    required_ids = {"prepare-cash-flow", "collect-tax-returns", "audit-ip-assignments", "assemble-financial-package"}
    if required_ids.issubset(ids):
        checks["queue_has_required_task_ids"] = True

    # assemble-financial-package must depend on both
    assemble_ok = False
    deps_exist_ok = True
    adjacency: Dict[str, List[str]] = {}
    for t in tasks:
        tid = t.get("id")
        dlist = t.get("dependencies", [])
        if isinstance(dlist, list):
            adjacency[tid] = [d for d in dlist if isinstance(d, str)]
            # dependencies exist
            for d in adjacency[tid]:
                if d not in ids:
                    deps_exist_ok = False
        if tid == "assemble-financial-package" and isinstance(dlist, list):
            deps_set = set([d for d in dlist if isinstance(d, str)])
            if {"prepare-cash-flow", "collect-tax-returns"}.issubset(deps_set):
                assemble_ok = True
    if assemble_ok:
        checks["queue_assemble_depends_on_both"] = True
    if deps_exist_ok:
        checks["queue_dependencies_exist"] = True

    # Cycle detection
    def is_acyclic(graph: Dict[str, List[str]]) -> bool:
        visited: Set[str] = set()
        onpath: Set[str] = set()
        def dfs(node: str) -> bool:
            if node in onpath:
                return False
            if node in visited:
                return True
            visited.add(node)
            onpath.add(node)
            for nei in graph.get(node, []):
                if nei not in graph:
                    # Unknown nodes are handled by dependencies_exist check; ignore here
                    continue
                if not dfs(nei):
                    return False
            onpath.remove(node)
            return True
        for n in graph.keys():
            if not dfs(n):
                return False
        return True

    if is_acyclic(adjacency):
        checks["queue_acyclic"] = True

    return checks

def check_memory_files(mem_path: str, tasks_path: str) -> Dict[str, bool]:
    checks = {
        "has_memory_md": False,
        "has_tasks_md": False,
        "memory_combined_has_min_lines": False,
        "memory_mentions_seriesA_or_teamlyft": False,
        "tasks_md_has_prepare_or_deliver": False,
    }
    # MEMORY.md
    mem_exists = os.path.isfile(mem_path)
    tasks_exists = os.path.isfile(tasks_path)
    if mem_exists:
        checks["has_memory_md"] = True
        okm, mem_text = load_text(mem_path)
        if not okm:
            mem_text = ""
    else:
        mem_text = ""
    if tasks_exists:
        checks["has_tasks_md"] = True
        okt, tasks_text = load_text(tasks_path)
        if not okt:
            tasks_text = ""
    else:
        tasks_text = ""

    # Combined non-empty lines >= 3
    combined_lines = [line for line in (mem_text.splitlines() + tasks_text.splitlines()) if line.strip() != ""]
    if len(combined_lines) >= 3:
        checks["memory_combined_has_min_lines"] = True

    # Mentions Series A or TeamLyft
    combined_lower = (mem_text + "\n" + tasks_text).lower()
    if ("series a" in combined_lower) or ("teamlyft" in combined_lower):
        checks["memory_mentions_seriesA_or_teamlyft"] = True

    # tasks.md has 'prepare' or 'deliver' in a line
    has_prepare_or_deliver = False
    for line in tasks_text.splitlines():
        l = line.lower()
        if ("prepare" in l) or ("deliver" in l):
            has_prepare_or_deliver = True
            break
    if has_prepare_or_deliver:
        checks["tasks_md_has_prepare_or_deliver"] = True

    return checks

def main() -> None:
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir is defined for completeness, though not used directly
    reward_dir = os.path.join(workspace_root, "reward")

    all_checks: Dict[str, bool] = {}

    # 1) checklist.md
    checklist_path = os.path.join(output_dir, "data_room", "checklist.md")
    all_checks.update(check_checklist_md(checklist_path))

    # 2) gap_report.json
    gap_path = os.path.join(output_dir, "gap_report.json")
    all_checks.update(check_gap_report(gap_path))

    # 3) ads/summary.json
    ads_path = os.path.join(output_dir, "ads", "summary.json")
    all_checks.update(check_ads_summary(ads_path))

    # 4) queue/plan.json
    queue_path = os.path.join(output_dir, "queue", "plan.json")
    all_checks.update(check_queue_plan(queue_path))

    # 5) memory files
    memory_md_path = os.path.join(output_dir, "memory", "MEMORY.md")
    tasks_md_path = os.path.join(output_dir, "memory", "tasks.md")
    all_checks.update(check_memory_files(memory_md_path, tasks_md_path))

    # Compute reward: average of booleans; ensure no-op baseline is 0.0
    total = len(all_checks)
    passed = sum(1 for v in all_checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # If output directory missing or all required files absent, reward will naturally be 0.0
    result = {"reward": reward}
    result.update(all_checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()