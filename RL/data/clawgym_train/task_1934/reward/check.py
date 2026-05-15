import json
import os
import sys
import csv
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "openclaw_exists": False,
        "openclaw_json_valid": False,
        "openclaw_defaults_correct": False,
        "openclaw_agents_list_correct": False,
        "openclaw_workspaces_correct": False,
        "openclaw_main_override_correct": False,
        "openclaw_tools_policy_correct": False,
        "openclaw_no_abs_or_home_paths": False,
        "heartbeats_valid": False,
        "spawn_plan_valid": False,
        # identity checks will be added per agent after reading CSV
    }

    # Load agents.csv to get expected agents, names, roles
    agents_csv_path = os.path.join(input_dir, "agents.csv")
    agents_expected = {}  # id -> {"name": ..., "role": ...}
    try:
        with open(agents_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                agent_id = (row.get("id") or "").strip()
                name = (row.get("name") or "").strip()
                role = (row.get("role") or "").strip()
                if agent_id:
                    agents_expected[agent_id] = {"name": name, "role": role}
    except Exception:
        # If we cannot read the input file, all dependent checks remain False
        pass

    # Ensure we have identity checks initialized for known target IDs if present
    for aid in ["main", "researcher", "writer"]:
        checks[f"identity_{aid}"] = False

    # Helper: recursively collect all string values from a JSON-like structure
    def collect_strings(obj):
        found = []
        if isinstance(obj, dict):
            for v in obj.values():
                found.extend(collect_strings(v))
        elif isinstance(obj, list):
            for v in obj:
                found.extend(collect_strings(v))
        elif isinstance(obj, str):
            found.append(obj)
        return found

    # Check openclaw.json
    openclaw_path = os.path.join(output_dir, "openclaw.json")
    if os.path.isfile(openclaw_path):
        checks["openclaw_exists"] = True
        openclaw_data = None
        try:
            with open(openclaw_path, "r", encoding="utf-8") as f:
                openclaw_data = json.load(f)
            checks["openclaw_json_valid"] = True
        except Exception:
            openclaw_data = None

        if openclaw_data is not None:
            # Defaults under agents.defaults.subagents
            try:
                defaults = openclaw_data["agents"]["defaults"]["subagents"]
                conds = []
                conds.append(defaults.get("model") == "anthropic/claude-haiku-4-5")
                conds.append(defaults.get("thinking") == "basic")
                conds.append(defaults.get("maxSpawnDepth") == 2)
                conds.append(defaults.get("maxChildrenPerAgent") == 3)
                conds.append(defaults.get("maxConcurrent") == 4)
                conds.append(defaults.get("runTimeoutSeconds") == 900)
                conds.append(defaults.get("archiveAfterMinutes") == 30)
                if all(conds):
                    checks["openclaw_defaults_correct"] = True
            except Exception:
                pass

            # Agents list correctness and workspaces
            try:
                agents_list = openclaw_data["agents"]["list"]
                if isinstance(agents_list, list):
                    # Expected IDs are exactly three: main, researcher, writer (from CSV)
                    expected_ids = [aid for aid in ["main", "researcher", "writer"] if aid in agents_expected]
                    # If CSV didn't include them all, still enforce exactly these three IDs per spec
                    expected_ids = ["main", "researcher", "writer"]
                    ids_in_json = [a.get("id") for a in agents_list if isinstance(a, dict)]
                    set_expected = set(expected_ids)
                    set_json = set(ids_in_json)
                    if len(agents_list) == 3 and set_json == set_expected:
                        checks["openclaw_agents_list_correct"] = True

                    # Workspaces must be exactly "output/workspace-<id>" and not start with "/" or "~"
                    work_ok_all = True
                    for a in agents_list:
                        aid = a.get("id")
                        ws = a.get("workspace")
                        if aid not in set_expected:
                            work_ok_all = False
                            break
                        expected_ws = f"output/workspace-{aid}"
                        if ws != expected_ws:
                            work_ok_all = False
                            break
                        if isinstance(ws, str) and (ws.startswith("/") or ws.startswith("~")):
                            work_ok_all = False
                            break
                    if work_ok_all and checks["openclaw_agents_list_correct"]:
                        checks["openclaw_workspaces_correct"] = True
            except Exception:
                pass

            # Main agent per-agent subagent override
            try:
                agents_list = openclaw_data["agents"]["list"]
                main_agent = None
                for a in agents_list:
                    if a.get("id") == "main":
                        main_agent = a
                        break
                if main_agent and isinstance(main_agent.get("subagents"), dict):
                    subcfg = main_agent["subagents"]
                    allow = subcfg.get("allowAgents")
                    thinking = subcfg.get("thinking")
                    allow_ok = isinstance(allow, list) and set(allow) == {"researcher", "writer"} and len(allow) == 2
                    thinking_ok = (thinking == "none")
                    if allow_ok and thinking_ok:
                        checks["openclaw_main_override_correct"] = True
            except Exception:
                pass

            # Global subagents tools policy denies gateway and cron
            try:
                deny = openclaw_data["tools"]["subagents"]["tools"]["deny"]
                if isinstance(deny, list) and "gateway" in deny and "cron" in deny:
                    checks["openclaw_tools_policy_correct"] = True
            except Exception:
                pass

            # No absolute or home-directory paths anywhere in JSON string values
            try:
                all_strings = collect_strings(openclaw_data)
                bad = False
                for s in all_strings:
                    if isinstance(s, str) and (s.startswith("/") or s.startswith("~")):
                        bad = True
                        break
                if not bad:
                    checks["openclaw_no_abs_or_home_paths"] = True
            except Exception:
                pass

    # Identity and memory files per agent
    # We require exactly main, researcher, writer as per spec
    for aid in ["main", "researcher", "writer"]:
        key = f"identity_{aid}"
        # Initialize if not present
        if key not in checks:
            checks[key] = False
        # We need name and role from CSV for each
        if aid not in agents_expected:
            continue
        agent_dir = os.path.join(output_dir, f"workspace-{aid}")
        soul_path = os.path.join(agent_dir, "SOUL.md")
        agents_md_path = os.path.join(agent_dir, "AGENTS.md")
        hb_path = os.path.join(agent_dir, "HEARTBEAT.md")
        mem_dir = os.path.join(agent_dir, "memory")
        working_path = os.path.join(mem_dir, "WORKING.md")
        memory_path = os.path.join(mem_dir, "MEMORY.md")

        try:
            # Check SOUL.md
            if not os.path.isfile(soul_path):
                continue
            with open(soul_path, "r", encoding="utf-8") as f:
                soul_lines = [line.rstrip("\n") for line in f.readlines()]
            # Find lines starting with "Name:" and "Role:" and match exact contents
            name_line_ok = False
            role_line_ok = False
            for line in soul_lines:
                if line.startswith("Name:"):
                    value = line[len("Name:"):].strip()
                    if value == agents_expected[aid]["name"]:
                        name_line_ok = True
                if line.startswith("Role:"):
                    value = line[len("Role:"):].strip()
                    if value == agents_expected[aid]["role"]:
                        role_line_ok = True
            if not (name_line_ok and role_line_ok):
                continue

            # Check AGENTS.md
            if not os.path.isfile(agents_md_path):
                continue
            with open(agents_md_path, "r", encoding="utf-8") as f:
                agents_md = f.read()
            # Must contain exact line "Session Key: agent:<id>:main"
            has_session_line = False
            for line in agents_md.splitlines():
                if line.strip() == f"Session Key: agent:{aid}:main":
                    has_session_line = True
                    break
            if not has_session_line:
                continue
            # Must mention WORKING.md and MEMORY.md somewhere
            if ("WORKING.md" not in agents_md) or ("MEMORY.md" not in agents_md):
                continue

            # Check HEARTBEAT.md
            if not os.path.isfile(hb_path):
                continue
            with open(hb_path, "r", encoding="utf-8") as f:
                hb_text = f.read()
            if "HEARTBEAT_OK" not in hb_text:
                continue

            # Memory files
            if not os.path.isdir(mem_dir):
                continue
            if not (os.path.isfile(working_path) and os.path.isfile(memory_path)):
                continue

            checks[key] = True
        except Exception:
            # Any error leaves it False
            continue

    # Heartbeats TSV
    heartbeats_path = os.path.join(output_dir, "heartbeats.tsv")
    if os.path.isfile(heartbeats_path):
        try:
            with open(heartbeats_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines() if ln.strip() != "" or ln == "\n"]
            if lines:
                header = lines[0]
                if header == "agent_id\tcron\tstagger_minute":
                    rows = lines[1:]
                    if len(rows) == 3:
                        mapping = {}
                        ok = True
                        for row in rows:
                            parts = row.split("\t")
                            if len(parts) != 3:
                                ok = False
                                break
                            agent_id = parts[0]
                            cron = parts[1]
                            stagger_str = parts[2]
                            # Validate integer stagger
                            try:
                                stagger = int(stagger_str)
                            except ValueError:
                                ok = False
                                break
                            mapping[agent_id] = (cron, stagger)
                        expected_ids = {"main", "researcher", "writer"}
                        if set(mapping.keys()) == expected_ids:
                            # Cron must match exact string
                            cron_ok = all(mapping[aid][0] == "0,15,30,45 * * * *" for aid in expected_ids)
                            # Stagger mapping: main=0, researcher=2, writer=4
                            stagger_ok = (
                                mapping.get("main", (None, None))[1] == 0 and
                                mapping.get("researcher", (None, None))[1] == 2 and
                                mapping.get("writer", (None, None))[1] == 4
                            )
                            if cron_ok and stagger_ok:
                                checks["heartbeats_valid"] = True
        except Exception:
            pass

    # Spawn plan JSON
    spawn_plan_path = os.path.join(output_dir, "spawn_plan.json")
    if os.path.isfile(spawn_plan_path):
        try:
            with open(spawn_plan_path, "r", encoding="utf-8") as f:
                spawn = json.load(f)
            # Validate structure
            orch = spawn.get("orchestrator_task")
            workers = spawn.get("worker_tasks")
            orch_ok = False
            workers_ok = False
            if isinstance(orch, dict):
                model_ok = orch.get("model") == "anthropic/claude-sonnet-4-5"
                thinking_ok = orch.get("thinking") == "basic"
                mode_ok = orch.get("mode") == "run"
                rts = orch.get("runTimeoutSeconds")
                rts_ok = isinstance(rts, int) and (900 <= rts <= 1800)
                task = orch.get("task", "")
                if isinstance(task, str):
                    low = task.lower()
                    has_orchestrator = "orchestrator" in low
                    has_two = ("two" in low) or ("2" in task)
                    orch_ok = model_ok and thinking_ok and mode_ok and rts_ok and has_orchestrator and has_two
            if isinstance(workers, list) and len(workers) == 2:
                per_ok = True
                has_research = False
                has_writing = False
                for wk in workers:
                    if not isinstance(wk, dict):
                        per_ok = False
                        break
                    if wk.get("model") != "anthropic/claude-haiku-4-5":
                        per_ok = False
                        break
                    if wk.get("thinking") != "none":
                        per_ok = False
                        break
                    if wk.get("cleanup") != "delete":
                        per_ok = False
                        break
                    wrts = wk.get("runTimeoutSeconds")
                    if not (isinstance(wrts, int) and wrts <= 600):
                        per_ok = False
                        break
                    t = wk.get("task", "")
                    if isinstance(t, str):
                        lt = t.lower()
                        if "research" in lt:
                            has_research = True
                        if ("write" in lt) or ("writing" in lt):
                            has_writing = True
                workers_ok = per_ok and has_research and has_writing
            if orch_ok and workers_ok:
                checks["spawn_plan_valid"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v is True)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Baseline: if no output artifacts exist, reward should be 0.0
    # Already satisfied since no checks would pass if files are missing.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()