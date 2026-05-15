import json
import os
import sys
from typing import List, Dict

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize individual checks to False
    checks = {
        "restart_plan_exists": False,
        "restart_plan_keys_exact": False,
        "restart_plan_lists_sorted": False,
        "restart_plan_values_match": False,
        "restart_plan_notes_string": False,
        "restart_plan_ok": False,

        "compose_actions_exists": False,
        "compose_actions_keys_exact": False,
        "compose_actions_values_match": False,
        "compose_actions_sorted": False,
        "compose_actions_ok": False,

        "summary_exists": False,
        "summary_counts_correct": False,
        "summary_names_listed": False,
        "summary_ok": False,
    }

    # Helper to load JSON safely
    def load_json(path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    # Compute expected results from inputs
    containers_path = os.path.join(input_dir, "containers.json")
    compose_projects_path = os.path.join(input_dir, "compose_projects.json")

    containers = load_json(containers_path) or []
    compose_projects = load_json(compose_projects_path) or []

    # Build expected restart plan
    fatal_patterns = ["fatal", "panic:", "outofmemoryerror"]

    def has_fatal_logs(container_name: str) -> bool:
        # input/logs_<container-name>.txt
        logs_path = os.path.join(input_dir, f"logs_{container_name}.txt")
        if not os.path.isfile(logs_path):
            return False
        try:
            with open(logs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().lower()
            for pat in fatal_patterns:
                if pat in content:
                    return True
            return False
        except Exception:
            return False

    to_restart: List[str] = []
    investigate: List[str] = []
    skipped: List[str] = []

    # Containers may be list of dicts
    for c in containers if isinstance(containers, list) else []:
        name = c.get("name")
        state = c.get("state")
        restart_count = c.get("restartCount", 0)
        # Validate name
        if not isinstance(name, str) or not name:
            continue

        # Determine category
        trigger_restart = False
        if state in ("exited", "restarting"):
            trigger_restart = True
        elif state == "running" and has_fatal_logs(name):
            trigger_restart = True
        else:
            trigger_restart = False

        if trigger_restart:
            if isinstance(restart_count, (int, float)) and restart_count > 5:
                investigate.append(name)
            else:
                to_restart.append(name)
        else:
            skipped.append(name)

    # Deduplicate, then sort
    to_restart = sorted(sorted(set(to_restart)))
    investigate = sorted(sorted(set(investigate)))
    skipped = sorted(sorted(set(skipped)))

    # Build expected compose actions
    compose_up: List[str] = []
    for proj in compose_projects if isinstance(compose_projects, list) else []:
        pname = proj.get("name")
        services = proj.get("services", [])
        if not isinstance(pname, str) or not pname:
            continue
        needs_up = False
        if isinstance(services, list):
            for svc in services:
                try:
                    rw = int(svc.get("replicasWanted", 0))
                    rr = int(svc.get("replicasRunning", 0))
                except Exception:
                    rw = svc.get("replicasWanted", 0)
                    rr = svc.get("replicasRunning", 0)
                    # Attempt int conversion
                    try:
                        rw = int(rw)
                    except Exception:
                        rw = 0
                    try:
                        rr = int(rr)
                    except Exception:
                        rr = 0
                if rr < rw:
                    needs_up = True
                    break
        if needs_up:
            compose_up.append(pname)
    compose_up = sorted(sorted(set(compose_up)))
    expected_compose_actions = {"compose_up": compose_up, "compose_down": []}

    # Validate output/restart_plan.json
    restart_plan_path = os.path.join(output_dir, "restart_plan.json")
    if os.path.isfile(restart_plan_path):
        checks["restart_plan_exists"] = True
        out_restart = load_json(restart_plan_path)
        if isinstance(out_restart, dict):
            keys = set(out_restart.keys())
            if keys == {"to_restart", "investigate", "skipped", "notes"} and len(out_restart.keys()) == 4:
                checks["restart_plan_keys_exact"] = True

                # Types
                out_to_restart = out_restart.get("to_restart")
                out_investigate = out_restart.get("investigate")
                out_skipped = out_restart.get("skipped")
                out_notes = out_restart.get("notes")

                lists_type_ok = isinstance(out_to_restart, list) and isinstance(out_investigate, list) and isinstance(out_skipped, list)
                if isinstance(out_notes, str):
                    checks["restart_plan_notes_string"] = True

                if lists_type_ok:
                    # Ensure all elements are strings
                    if all(isinstance(x, str) for x in out_to_restart) and all(isinstance(x, str) for x in out_investigate) and all(isinstance(x, str) for x in out_skipped):
                        # Check sorted order
                        if out_to_restart == sorted(out_to_restart) and out_investigate == sorted(out_investigate) and out_skipped == sorted(out_skipped):
                            checks["restart_plan_lists_sorted"] = True

                        # Compare exact lists with expected
                        if out_to_restart == to_restart and out_investigate == investigate and out_skipped == skipped:
                            checks["restart_plan_values_match"] = True

    checks["restart_plan_ok"] = all([
        checks["restart_plan_exists"],
        checks["restart_plan_keys_exact"],
        checks["restart_plan_lists_sorted"],
        checks["restart_plan_values_match"],
        checks["restart_plan_notes_string"],
    ])

    # Validate output/compose_actions.json
    compose_actions_path = os.path.join(output_dir, "compose_actions.json")
    if os.path.isfile(compose_actions_path):
        checks["compose_actions_exists"] = True
        out_compose = load_json(compose_actions_path)
        if isinstance(out_compose, dict):
            keys = set(out_compose.keys())
            if keys == {"compose_up", "compose_down"} and len(out_compose.keys()) == 2:
                checks["compose_actions_keys_exact"] = True
                out_cu = out_compose.get("compose_up")
                out_cd = out_compose.get("compose_down")
                if isinstance(out_cu, list) and isinstance(out_cd, list):
                    # Check sorted
                    if out_cu == sorted(out_cu):
                        checks["compose_actions_sorted"] = True
                    # Compare with expected exactly
                    if out_cu == expected_compose_actions["compose_up"] and out_cd == []:
                        checks["compose_actions_values_match"] = True

    checks["compose_actions_ok"] = all([
        checks["compose_actions_exists"],
        checks["compose_actions_keys_exact"],
        checks["compose_actions_sorted"],
        checks["compose_actions_values_match"],
    ])

    # Validate output/summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            lines = [ln.strip() for ln in content.splitlines()]
            expected_counts = {
                f"to_restart: {len(to_restart)}",
                f"investigate: {len(investigate)}",
                f"skipped: {len(skipped)}",
                f"compose_up: {len(compose_up)}",
            }
            # Check each expected line is present exactly
            counts_ok = all(any(l == exp for l in lines) for exp in expected_counts)
            if counts_ok:
                checks["summary_counts_correct"] = True

            # Names presence
            lc_content = content.lower()
            names_ok = True
            for name in to_restart:
                if name.lower() not in lc_content:
                    names_ok = False
                    break
            if names_ok:
                for proj in compose_up:
                    if proj.lower() not in lc_content:
                        names_ok = False
                        break
            if names_ok:
                checks["summary_names_listed"] = True
        except Exception:
            pass

    checks["summary_ok"] = all([
        checks["summary_exists"],
        checks["summary_counts_correct"],
        checks["summary_names_listed"],
    ])

    # Compute reward: 3 major deliverables
    total_sections = 3
    passed_sections = sum(1 for k in ["restart_plan_ok", "compose_actions_ok", "summary_ok"] if checks[k])
    reward = passed_sections / total_sections if total_sections > 0 else 0.0

    # Enforce baseline: if output dir missing or empty, reward 0.0
    if not os.path.isdir(output_dir) or len(os.listdir(output_dir)) == 0:
        reward = 0.0

    # Print exactly one JSON object as the last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()