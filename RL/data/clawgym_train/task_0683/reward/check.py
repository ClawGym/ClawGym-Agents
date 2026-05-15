import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def count_examples(lines):
    count = 0
    for line in lines:
        s = line.strip()
        if s.lower().startswith("luban "):
            count += 1
    return count

def has_add_parser_name(text, name):
    # Matches add_parser("name") or add_parser('name') with optional spaces
    pattern = r"add_parser\s*\(\s*['\"]" + re.escape(name) + r"['\"]\s*\)"
    return re.search(pattern, text) is not None

def last_nonempty_json_print(obj):
    print(json.dumps(obj))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to check
    cli_path = os.path.join(output_dir, "luban.py")
    spec_path = os.path.join(output_dir, "spec", "entities.json")
    usage_path = os.path.join(output_dir, "docs", "USAGE.md")
    arch_path = os.path.join(output_dir, "docs", "ARCHITECTURE.md")
    testplan_path = os.path.join(output_dir, "docs", "TESTPLAN.md")

    checks = {
        # Existence
        "cli_exists": False,
        "spec_exists": False,
        "usage_exists": False,
        "arch_exists": False,
        "testplan_exists": False,

        # CLI structure checks
        "cli_has_argparse_import": False,
        "cli_has_entity_env": False,
        "cli_has_entity_job": False,
        "cli_has_entity_svc": False,
        "cli_env_has_actions_list_create_get_update_delete": False,
        "cli_job_has_actions_list_create_update_delete_stop_logs": False,
        "cli_svc_has_actions_list_create_update_delete_scale_status": False,
        "cli_has_main_guard": False,

        # Spec checks
        "spec_valid": False,
        "spec_has_env_job_svc": False,
        "spec_env_operations": False,
        "spec_job_operations": False,
        "spec_svc_operations": False,
        "spec_required_ops_have_flags": False,

        # Usage docs checks
        "usage_has_5_examples": False,
        "usage_has_svc_scale_example": False,
        "usage_has_svc_status_example": False,
        "usage_has_job_logs_example": False,
        "usage_mentions_help": False,

        # Architecture docs checks
        "arch_mentions_circuit_breaker": False,
        "arch_mentions_retry": False,
        "arch_mentions_saga": False,
        "arch_mentions_api_gateway": False,
        "arch_mentions_health": False,

        # Test plan checks
        "testplan_covers_env_crud": False,
        "testplan_covers_job_logs_stop": False,
        "testplan_covers_svc_scale_status_delete": False,

        # Gate: all required files exist
        "all_required_files_exist": False,
    }

    # CLI checks
    if os.path.isfile(cli_path):
        checks["cli_exists"] = True
        cli_text = read_text(cli_path)
        low = cli_text.lower()
        checks["cli_has_argparse_import"] = ("import argparse" in cli_text) or ("from argparse" in cli_text)
        checks["cli_has_entity_env"] = has_add_parser_name(cli_text, "env")
        checks["cli_has_entity_job"] = has_add_parser_name(cli_text, "job")
        checks["cli_has_entity_svc"] = has_add_parser_name(cli_text, "svc")

        # Actions presence via add_parser for each action
        env_actions_required = ["list", "create", "get", "update", "delete"]
        job_actions_required = ["list", "create", "update", "delete", "stop", "logs"]
        svc_actions_required = ["list", "create", "update", "delete", "scale", "status"]

        env_ok = all(has_add_parser_name(cli_text, a) for a in env_actions_required)
        job_ok = all(has_add_parser_name(cli_text, a) for a in job_actions_required)
        svc_ok = all(has_add_parser_name(cli_text, a) for a in svc_actions_required)

        checks["cli_env_has_actions_list_create_get_update_delete"] = env_ok
        checks["cli_job_has_actions_list_create_update_delete_stop_logs"] = job_ok
        checks["cli_svc_has_actions_list_create_update_delete_scale_status"] = svc_ok

        checks["cli_has_main_guard"] = ('if __name__ == "__main__"' in cli_text) or ("if __name__ == '__main__'" in cli_text)

    # Spec checks
    spec_data = None
    if os.path.isfile(spec_path):
        checks["spec_exists"] = True
        try:
            with open(spec_path, "r", encoding="utf-8") as f:
                spec_data = json.load(f)
            checks["spec_valid"] = isinstance(spec_data, dict)
        except Exception:
            checks["spec_valid"] = False
            spec_data = None

        if checks["spec_valid"]:
            # top-level keys
            has_env = "env" in spec_data
            has_job = "job" in spec_data
            has_svc = "svc" in spec_data
            checks["spec_has_env_job_svc"] = has_env and has_job and has_svc

            def extract_ops(entity_obj):
                ops = entity_obj.get("operations", [])
                names = []
                by_name = {}
                if isinstance(ops, list):
                    for item in ops:
                        if isinstance(item, dict):
                            name = item.get("name") or item.get("action")
                            if isinstance(name, str):
                                names.append(name)
                                by_name[name] = item
                return names, by_name

            required_env_ops = {"list", "create", "get", "update", "delete"}
            required_job_ops = {"list", "create", "update", "delete", "stop", "logs"}
            required_svc_ops = {"list", "create", "update", "delete", "scale", "status"}

            env_ops_ok = False
            job_ops_ok = False
            svc_ops_ok = False
            flags_ok = False

            if has_env and isinstance(spec_data["env"], dict):
                env_names, env_map = extract_ops(spec_data["env"])
                env_ops_ok = required_env_ops.issubset(set(env_names))
            if has_job and isinstance(spec_data["job"], dict):
                job_names, job_map = extract_ops(spec_data["job"])
                job_ops_ok = required_job_ops.issubset(set(job_names))
            if has_svc and isinstance(spec_data["svc"], dict):
                svc_names, svc_map = extract_ops(spec_data["svc"])
                svc_ops_ok = required_svc_ops.issubset(set(svc_names))

            checks["spec_env_operations"] = env_ops_ok
            checks["spec_job_operations"] = job_ops_ok
            checks["spec_svc_operations"] = svc_ops_ok

            # Flags existence for required ops (accept list or object)
            if checks["spec_env_operations"] and checks["spec_job_operations"] and checks["spec_svc_operations"]:
                # rebuild maps
                env_names, env_map = extract_ops(spec_data["env"])
                job_names, job_map = extract_ops(spec_data["job"])
                svc_names, svc_map = extract_ops(spec_data["svc"])

                def op_has_flags(map_obj, name):
                    if name not in map_obj:
                        return False
                    op = map_obj[name]
                    if not isinstance(op, dict):
                        return False
                    if "flags" not in op:
                        return False
                    flags = op["flags"]
                    return isinstance(flags, (list, dict))

                all_required = True
                for n in required_env_ops:
                    all_required = all_required and op_has_flags(env_map, n)
                    if not all_required:
                        break
                if all_required:
                    for n in required_job_ops:
                        all_required = all_required and op_has_flags(job_map, n)
                        if not all_required:
                            break
                if all_required:
                    for n in required_svc_ops:
                        all_required = all_required and op_has_flags(svc_map, n)
                        if not all_required:
                            break
                flags_ok = all_required

            checks["spec_required_ops_have_flags"] = flags_ok

    # Usage docs checks
    if os.path.isfile(usage_path):
        checks["usage_exists"] = True
        usage_text = read_text(usage_path)
        lines = usage_text.splitlines()
        examples_count = count_examples(lines)
        checks["usage_has_5_examples"] = examples_count >= 5

        # Look for specific examples (lines starting with 'luban ')
        has_scale = False
        has_status = False
        has_logs = False
        for line in lines:
            s = line.strip()
            if s.lower().startswith("luban "):
                low = s.lower()
                if "svc scale" in low:
                    has_scale = True
                if "svc status" in low:
                    has_status = True
                if "job logs" in low:
                    has_logs = True
        checks["usage_has_svc_scale_example"] = has_scale
        checks["usage_has_svc_status_example"] = has_status
        checks["usage_has_job_logs_example"] = has_logs
        # Mentions help flag
        checks["usage_mentions_help"] = ("--help" in usage_text) or ("-h" in usage_text)

    # Architecture docs checks
    if os.path.isfile(arch_path):
        checks["arch_exists"] = True
        arch_text = read_text(arch_path).lower()
        checks["arch_mentions_circuit_breaker"] = "circuit breaker" in arch_text
        checks["arch_mentions_retry"] = "retry" in arch_text
        checks["arch_mentions_saga"] = "saga" in arch_text
        checks["arch_mentions_api_gateway"] = "api gateway" in arch_text
        checks["arch_mentions_health"] = "health" in arch_text  # liveness/readiness/health checks

    # Test plan checks
    if os.path.isfile(testplan_path):
        checks["testplan_exists"] = True
        tp_text = read_text(testplan_path).lower()
        env_crud = all(x in tp_text for x in ["env create", "env list", "env update", "env delete"])
        job_ls = all(x in tp_text for x in ["job create", "job logs", "job stop"])
        svc_ops = all(x in tp_text for x in ["svc create", "svc scale", "svc status", "svc delete"])
        checks["testplan_covers_env_crud"] = env_crud
        checks["testplan_covers_job_logs_stop"] = job_ls
        checks["testplan_covers_svc_scale_status_delete"] = svc_ops

    # Gate: all required files exist
    checks["all_required_files_exist"] = checks["cli_exists"] and checks["spec_exists"] and checks["usage_exists"] and checks["arch_exists"] and checks["testplan_exists"]

    # Compute reward
    # If any required artifact missing, reward must be 0.0
    if not checks["all_required_files_exist"]:
        reward = 0.0
    else:
        # Fractional score across all checks
        total_checks = len(checks)
        # Do not count the gate twice; keep it included to reflect its state
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    last_nonempty_json_print(result)

if __name__ == "__main__":
    main()