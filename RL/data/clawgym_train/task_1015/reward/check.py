import json
import os
import re
import sys

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_int(n):
    return isinstance(n, int) and not isinstance(n, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Plan checks
        "plan_file_exists": False,
        "plan_non_empty": False,
        "plan_has_required_terms": False,
        "plan_section_pass": False,

        # Runbook checks
        "runbook_file_exists": False,
        "runbook_non_empty": False,
        "runbook_has_required_terms": False,
        "runbook_section_pass": False,

        # Tasks checks
        "tasks_file_exists": False,
        "tasks_json_valid": False,
        "tasks_min_count": False,
        "tasks_all_have_required_fields": False,
        "tasks_statuses_valid": False,
        "tasks_required_titles_present_once": False,
        "tasks_have_hierarchy": False,
        "tasks_have_min_dependencies": False,
        "tasks_section_pass": False,
    }

    # 1) Plan file checks
    plan_path = os.path.join(output_dir, "plan", "community_plan.md")
    if os.path.isfile(plan_path):
        checks["plan_file_exists"] = True
        plan_text = load_text(plan_path)
        if plan_text.strip():
            checks["plan_non_empty"] = True
            lt = plan_text.lower()
            required_terms = [
                "platform selection",
                "channel",
                "role",
                "onboarding",
                "weekly",
                "engagement loop",
                "moderation",
                "decision matrix",
                "growth",
                "referral program",
                "monetization",
                "pricing",
                "events",
                "member lifecycle",
                "champion",
                "health metrics",
                "health score",
                "scaling",
                "difficult situations",
                "audit",
                "banking content safety",
                "compliance",
                "interest",
                "fee",
                "international",
            ]
            checks["plan_has_required_terms"] = all(term in lt for term in required_terms)
    checks["plan_section_pass"] = checks["plan_file_exists"] and checks["plan_non_empty"] and checks["plan_has_required_terms"]

    # 2) Runbook file checks
    runbook_path = os.path.join(output_dir, "operations", "incident_runbook.md")
    if os.path.isfile(runbook_path):
        checks["runbook_file_exists"] = True
        rb_text = load_text(runbook_path)
        if rb_text.strip():
            checks["runbook_non_empty"] = True
            lt = rb_text.lower()
            # lock or locking via regex word boundary to avoid matching "block"
            has_lock = re.search(r"\block(ing)?\b", lt) is not None
            required_phrases = [
                "health check",
                "restart",
                "cooldown",
                "restart loop",
                "version mismatch",
                "orphaned",
                "notification",
            ]
            checks["runbook_has_required_terms"] = has_lock and all(p in lt for p in required_phrases)
    checks["runbook_section_pass"] = checks["runbook_file_exists"] and checks["runbook_non_empty"] and checks["runbook_has_required_terms"]

    # 3) Tasks JSON checks
    tasks_path = os.path.join(output_dir, "roadmap", "tasks.json")
    tasks = None
    if os.path.isfile(tasks_path):
        checks["tasks_file_exists"] = True
        try:
            with open(tasks_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "tasks" in data and isinstance(data["tasks"], list):
                tasks = data["tasks"]
                checks["tasks_json_valid"] = True
            else:
                checks["tasks_json_valid"] = False
        except Exception:
            checks["tasks_json_valid"] = False

    if checks["tasks_json_valid"]:
        # Count
        if len(tasks) >= 12:
            checks["tasks_min_count"] = True

        # Validate schema and statuses
        allowed_statuses = {"icebox", "backlog", "ready", "in_progress", "review", "done", "closed"}

        all_have_fields = True
        statuses_valid = True

        # Build ID set
        ids = set()
        for t in tasks:
            tid = t.get("id", None)
            if is_int(tid):
                ids.add(tid)

        # Validate each task
        for t in tasks:
            has_all = True
            # required keys
            required_keys = ["id", "title", "status", "parent_id", "blockedBy", "blocks", "tags"]
            for k in required_keys:
                if k not in t:
                    has_all = False
                    break
            # types
            if has_all:
                if not is_int(t["id"]):
                    has_all = False
                if not isinstance(t["title"], str):
                    has_all = False
                if not isinstance(t["status"], str):
                    has_all = False
                if t["parent_id"] is not None and not is_int(t["parent_id"]):
                    has_all = False
                if not isinstance(t["blockedBy"], list):
                    has_all = False
                if not isinstance(t["blocks"], list):
                    has_all = False
                if not isinstance(t["tags"], list):
                    has_all = False
            if not has_all:
                all_have_fields = False

            # status validity
            if isinstance(t.get("status"), str):
                if t["status"] not in allowed_statuses:
                    statuses_valid = False
            else:
                statuses_valid = False

        checks["tasks_all_have_required_fields"] = all_have_fields
        checks["tasks_statuses_valid"] = statuses_valid

        # Required titles exactly once
        required_titles = [
            "Banking Content Safety Policy",
            "Referral Program",
            "Weekly Content Calendar",
            "Moderator Guidelines",
            "Health Metrics Dashboard",
            "Premium Tier Design",
            "Event Series Plan",
            "Onboarding Flow",
            "Channel Architecture",
            "Champion Program",
        ]
        title_counts = {rt: 0 for rt in required_titles}
        for t in tasks:
            title = t.get("title")
            if isinstance(title, str) and title in title_counts:
                title_counts[title] += 1
        checks["tasks_required_titles_present_once"] = all(count == 1 for count in title_counts.values())

        # Hierarchy: at least one task with non-null parent_id
        has_hierarchy = any(t.get("parent_id") is not None for t in tasks)
        checks["tasks_have_hierarchy"] = has_hierarchy

        # Dependencies: count edges that reference valid ids
        dep_edges = 0
        for t in tasks:
            tid = t.get("id")
            # blockedBy references blockers of current task
            for b in t.get("blockedBy", []):
                if is_int(b) and b in ids:
                    dep_edges += 1
            # blocks references tasks this one blocks
            for b in t.get("blocks", []):
                if is_int(b) and b in ids:
                    dep_edges += 1
        checks["tasks_have_min_dependencies"] = dep_edges >= 2

    checks["tasks_section_pass"] = all([
        checks["tasks_file_exists"],
        checks["tasks_json_valid"],
        checks["tasks_min_count"],
        checks["tasks_all_have_required_fields"],
        checks["tasks_statuses_valid"],
        checks["tasks_required_titles_present_once"],
        checks["tasks_have_hierarchy"],
        checks["tasks_have_min_dependencies"],
    ])

    # Compute reward: average of the three sections
    section_passes = [
        checks["plan_section_pass"],
        checks["runbook_section_pass"],
        checks["tasks_section_pass"],
    ]
    reward = sum(1.0 for p in section_passes if p) / 3.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()