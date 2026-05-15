import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def find_task_by_title(tasks: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
    for t in tasks:
        if isinstance(t, dict) and t.get("title") == title:
            return t
    return None

def get_id(task: Dict[str, Any]) -> Optional[str]:
    val = task.get("id")
    if val is None:
        return None
    return str(val)

def is_child_of_parent(task: Dict[str, Any], parent_id: Optional[str], parent_title: str) -> bool:
    # Check parent_id direct
    pid = task.get("parent_id", None)
    if pid is not None and parent_id is not None:
        try:
            if str(pid) == str(parent_id):
                return True
        except Exception:
            pass
    # Check parent object
    parent_obj = task.get("parent", None)
    if isinstance(parent_obj, dict):
        if parent_id is not None and parent_obj.get("id") is not None and str(parent_obj.get("id")) == str(parent_id):
            return True
        if parent_obj.get("title") == parent_title:
            return True
    return False

def extract_metadata_priority(task: Dict[str, Any]) -> Optional[str]:
    md = task.get("metadata")
    # metadata may be list of {key, value} or dict
    if isinstance(md, list):
        for item in md:
            if isinstance(item, dict) and item.get("key") == "priority":
                val = item.get("value")
                if isinstance(val, str):
                    return val.strip().lower()
                else:
                    return None
    elif isinstance(md, dict):
        val = md.get("priority")
        if isinstance(val, str):
            return val.strip().lower()
        else:
            return None
    return None

def extract_tag_names(task: Dict[str, Any]) -> Set[str]:
    tags = task.get("tags")
    names: Set[str] = set()
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str):
                    names.add(name.strip().lower())
            elif isinstance(item, str):
                names.add(item.strip().lower())
    return names

def safe_list(val: Any) -> List[Any]:
    return val if isinstance(val, list) else []

def compute_ready_child_count(tasks: List[Dict[str, Any]], parent_id: Optional[str], parent_title: str) -> int:
    count = 0
    for t in tasks:
        if is_child_of_parent(t, parent_id, parent_title):
            if t.get("status") == "ready":
                count += 1
    return count

def only_integer_text(s: str) -> Optional[int]:
    if re.fullmatch(r"\s*\d+\s*", s or ""):
        try:
            return int(s.strip())
        except Exception:
            return None
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        # tasks_tree.json checks
        "tasks_tree_exists": False,
        "tasks_tree_valid_json": False,
        "parent_present": False,
        "parent_status_ready": False,
        "children_present_exact_five": False,
        "child_titles_statuses_correct": False,
        "child_parent_linked_to_parent": False,
        "child_metadata_priority_present": False,
        "tag_security_present": False,
        "tag_improvement_present": False,
        "tag_docs_present": False,

        # parent_task.json checks
        "parent_task_json_exists": False,
        "parent_task_json_valid": False,
        "parent_task_success_true": False,
        "parent_task_children_five": False,
        "parent_task_children_titles_match": False,

        # dependencies.json checks
        "dependencies_json_exists": False,
        "dependencies_valid_json": False,
        "dependencies_keys_match": False,
        "dependencies_relations_correct": False,

        # ready_subtasks.txt checks
        "ready_subtasks_exists": False,
        "ready_subtasks_is_integer": False,
        "ready_subtasks_matches_computed": False,

        # plan.md checks
        "plan_md_exists": False,
        "plan_md_min_words": False,
        "plan_md_mentions_two_inputs": False,
        "plan_md_contains_all_titles": False,
        "plan_md_mentions_kanban_or_status": False,
        "plan_md_mentions_priority_and_dependency": False,
    }

    # Expected constants
    parent_title = "AP Automation Pilot (Q3)"
    expected_children = {
        "Invoice Processing Pipeline": "ready",
        "Approval Routing Design": "backlog",
        "Payment Optimization Setup": "backlog",
        "Vendor Master Data Standards": "icebox",
        "Month-End Close & Fraud Controls": "icebox",
    }
    required_tags = ["security", "improvement", "docs"]
    allowed_priorities = {"critical", "high", "medium", "low"}

    # 1) tasks_tree.json
    tasks_tree_path = os.path.join(output_dir, "tasks_tree.json")
    tasks_tree = None
    tasks: List[Dict[str, Any]] = []

    if os.path.isfile(tasks_tree_path):
        checks["tasks_tree_exists"] = True
        tasks_tree = load_json(tasks_tree_path)
        if isinstance(tasks_tree, dict) and isinstance(tasks_tree.get("tasks"), list):
            checks["tasks_tree_valid_json"] = True
            tasks = tasks_tree.get("tasks")  # type: ignore
        else:
            tasks = []

    parent_task = None
    parent_id: Optional[str] = None
    children_of_parent: Dict[str, Dict[str, Any]] = {}

    if checks["tasks_tree_valid_json"]:
        parent_task = find_task_by_title(tasks, parent_title)
        if parent_task:
            checks["parent_present"] = True
            parent_id = get_id(parent_task)
            if parent_task.get("status") == "ready":
                checks["parent_status_ready"] = True

            # Identify direct children of the parent
            temp_children = []
            for t in tasks:
                if t is parent_task:
                    continue
                if is_child_of_parent(t, parent_id, parent_title):
                    temp_children.append(t)

            # Map by title
            for t in temp_children:
                title = t.get("title")
                if isinstance(title, str):
                    children_of_parent[title] = t

            # Check exactly five required children linked to the parent
            if set(children_of_parent.keys()) == set(expected_children.keys()) and len(children_of_parent) == 5:
                checks["children_present_exact_five"] = True

            # Check titles and statuses correct (among children)
            statuses_ok = True
            for title, expected_status in expected_children.items():
                t = children_of_parent.get(title)
                if not t or t.get("status") != expected_status:
                    statuses_ok = False
                    break
            if statuses_ok:
                checks["child_titles_statuses_correct"] = True

            # Ensure all expected child tasks in global tasks are linked to parent
            linked_ok = True
            for title in expected_children.keys():
                t = find_task_by_title(tasks, title)
                if not t or not is_child_of_parent(t, parent_id, parent_title):
                    linked_ok = False
                    break
            if linked_ok:
                checks["child_parent_linked_to_parent"] = True

            # Metadata priority present and valid for each child
            priorities_ok = True
            for title in expected_children.keys():
                t = children_of_parent.get(title)
                if not t:
                    priorities_ok = False
                    break
                pr = extract_metadata_priority(t)
                if pr not in allowed_priorities:
                    priorities_ok = False
                    break
            if priorities_ok:
                checks["child_metadata_priority_present"] = True

            # Tag checks: at least one child has each required tag
            tag_presence = {tag: False for tag in required_tags}
            for t in children_of_parent.values():
                names = extract_tag_names(t)
                for tag in required_tags:
                    if tag.lower() in names:
                        tag_presence[tag] = True
            if tag_presence.get("security", False):
                checks["tag_security_present"] = True
            if tag_presence.get("improvement", False):
                checks["tag_improvement_present"] = True
            if tag_presence.get("docs", False):
                checks["tag_docs_present"] = True

    # 2) parent_task.json
    parent_task_json_path = os.path.join(output_dir, "parent_task.json")
    if os.path.isfile(parent_task_json_path):
        checks["parent_task_json_exists"] = True
        pt = load_json(parent_task_json_path)
        if isinstance(pt, dict):
            checks["parent_task_json_valid"] = True
            if pt.get("success") is True:
                checks["parent_task_success_true"] = True
            task_obj = pt.get("task")
            children_list = pt.get("children")
            if isinstance(task_obj, dict) and task_obj.get("title") == parent_title and isinstance(children_list, list):
                if len(children_list) == 5:
                    checks["parent_task_children_five"] = True
                # Extract titles of children
                child_titles = set()
                for c in children_list:
                    if isinstance(c, dict) and isinstance(c.get("title"), str):
                        child_titles.add(c.get("title"))
                if child_titles == set(expected_children.keys()):
                    checks["parent_task_children_titles_match"] = True

    # 3) dependencies.json
    dependencies_path = os.path.join(output_dir, "dependencies.json")
    if os.path.isfile(dependencies_path):
        checks["dependencies_json_exists"] = True
        deps = load_json(dependencies_path)
        if isinstance(deps, dict):
            checks["dependencies_valid_json"] = True
            keys_match = set(deps.keys()) == set(expected_children.keys())
            if keys_match:
                checks["dependencies_keys_match"] = True
            relations_ok = True
            # Required relations as pairs
            required_relations: Dict[str, List[str]] = {
                "Approval Routing Design": ["Invoice Processing Pipeline"],
                "Payment Optimization Setup": ["Approval Routing Design"],
                "Vendor Master Data Standards": ["Invoice Processing Pipeline"],
                "Month-End Close & Fraud Controls": ["Vendor Master Data Standards"],
                "Invoice Processing Pipeline": [],  # not specified to be blocked by any
            }
            for child_title, required_blockers in required_relations.items():
                v = deps.get(child_title)
                if not isinstance(v, dict):
                    relations_ok = False
                    break
                arr = v.get("blockedByTitles")
                if not isinstance(arr, list):
                    relations_ok = False
                    break
                arr_titles = set([a for a in arr if isinstance(a, str)])
                for req in required_blockers:
                    if req not in arr_titles:
                        relations_ok = False
                        break
                if not relations_ok:
                    break
            if relations_ok:
                checks["dependencies_relations_correct"] = True

    # 4) ready_subtasks.txt
    ready_subtasks_path = os.path.join(output_dir, "ready_subtasks.txt")
    if os.path.isfile(ready_subtasks_path):
        checks["ready_subtasks_exists"] = True
        s = read_text(ready_subtasks_path)
        val = only_integer_text(s if s is not None else "")
        if isinstance(val, int):
            checks["ready_subtasks_is_integer"] = True
            # Compute from tasks_tree.json if available
            if checks["tasks_tree_valid_json"] and parent_task is not None:
                computed = compute_ready_child_count(tasks, parent_id, parent_title)
                if val == computed:
                    checks["ready_subtasks_matches_computed"] = True

    # 5) plan.md
    plan_path = os.path.join(output_dir, "plan.md")
    if os.path.isfile(plan_path):
        checks["plan_md_exists"] = True
        text = read_text(plan_path) or ""
        # Word count
        words = re.findall(r"\b\w+\b", text)
        if len(words) >= 300:
            checks["plan_md_min_words"] = True
        # Mentions at least two input filenames
        input_files = [
            "input/ap_scope.md",
            "input/assignees.json",
            "input/priorities.json",
            "input/dependencies.yaml",
            "input/tags.yaml",
        ]
        mentions = 0
        for f in input_files:
            if f in text:
                mentions += 1
        if mentions >= 2:
            checks["plan_md_mentions_two_inputs"] = True
        # Contains all five child titles verbatim
        contains_all_titles = True
        for title in expected_children.keys():
            if title not in text:
                contains_all_titles = False
                break
        if contains_all_titles:
            checks["plan_md_contains_all_titles"] = True
        # Contains "kanban" or "status"
        if re.search(r"\bkanban\b", text, flags=re.IGNORECASE) or re.search(r"\bstatus\b", text, flags=re.IGNORECASE):
            checks["plan_md_mentions_kanban_or_status"] = True
        # Contains "priority" and either "dependency" or "blocked"
        has_priority = re.search(r"\bpriority\b", text, flags=re.IGNORECASE) is not None
        has_dep = re.search(r"\bdependency\b", text, flags=re.IGNORECASE) is not None or re.search(r"\bblocked?\b", text, flags=re.IGNORECASE) is not None
        if has_priority and has_dep:
            checks["plan_md_mentions_priority_and_dependency"] = True

    # Compute reward: average of all boolean checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure 0.0 when no artifacts produced (no-op baseline)
    # If none of the artifact existence checks are true, then force reward to 0.0
    existence_flags = [
        checks["tasks_tree_exists"],
        checks["parent_task_json_exists"],
        checks["dependencies_json_exists"],
        checks["ready_subtasks_exists"],
        checks["plan_md_exists"],
    ]
    if not any(existence_flags):
        reward = 0.0

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()