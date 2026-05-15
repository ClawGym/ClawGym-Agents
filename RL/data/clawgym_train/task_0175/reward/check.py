import json
import os
import sys

def to_str(v):
    try:
        if isinstance(v, bool) or v is None:
            return str(v)
        return v if isinstance(v, str) else str(v)
    except Exception:
        return str(v)

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl_lines(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.read().splitlines():
                if raw.strip() == "":
                    continue
                lines.append(raw)
        return lines
    except Exception:
        return None

def parse_json_line(s):
    try:
        return json.loads(s)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "requests_file_exists": False,
        "summary_file_exists": False,
        "requests_line_count_7": False,
        "global_change_ok": False,
        "adduri_alpha_ok": False,
        "adduri_beta_ok": False,
        "adduri_gamma_ok": False,
        "post_actions_ok": False,
        "summary_global_ok": False,
        "summary_tasks_ok": False
    }

    plan_path = os.path.join(input_dir, "download_plan.json")
    requests_path = os.path.join(output_dir, "requests.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")

    plan = load_json(plan_path)

    # Load outputs
    requests_lines = load_jsonl_lines(requests_path)
    if requests_lines is not None:
        checks["requests_file_exists"] = True
    summary_json = load_json(summary_path)
    if summary_json is not None:
        checks["summary_file_exists"] = True

    # If no output files, reward should be 0.0 at end
    expected_secret = None
    expected_global = {}
    expected_tasks = {}
    expected_post_actions = []

    if plan:
        # Extract expected values from plan
        expected_secret = None
        if isinstance(plan, dict):
            # secret may be under "rpc" or top-level
            if "rpc" in plan and isinstance(plan["rpc"], dict):
                sec = plan["rpc"].get("secret")
                if isinstance(sec, (str, int, float)):
                    expected_secret = to_str(sec)
            if expected_secret is None and isinstance(plan.get("secret"), (str, int, float)):
                expected_secret = to_str(plan.get("secret"))

            if isinstance(plan.get("global_options"), dict):
                expected_global = plan["global_options"].copy()

            # tasks list
            tasks = plan.get("tasks")
            if isinstance(tasks, list):
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    alias = t.get("alias")
                    if not isinstance(alias, str):
                        continue
                    uris = t.get("uris", [])
                    if not isinstance(uris, list):
                        uris = []
                    options = t.get("options", {})
                    if not isinstance(options, dict):
                        options = {}
                    expected_tasks[alias] = {
                        "uris": uris,
                        "options": options
                    }

            # post_actions
            pas = plan.get("post_actions")
            if isinstance(pas, list):
                for pa in pas:
                    if not isinstance(pa, dict):
                        continue
                    action = pa.get("action")
                    alias = pa.get("alias")
                    if isinstance(action, str) and isinstance(alias, str):
                        expected_post_actions.append({"action": action, "alias": alias})

    # Validate requests.jsonl
    if requests_lines is not None:
        # Count non-empty lines must be exactly 7
        if len(requests_lines) == 7:
            checks["requests_line_count_7"] = True

        parsed = [parse_json_line(s) for s in requests_lines] if requests_lines is not None else []
        # Guard against None entries due to parse errors
        # First line: changeGlobalOption
        if len(parsed) >= 1 and isinstance(parsed[0], dict):
            first = parsed[0]
            # Only allowed keys for non-addUri: jsonrpc, id, method, params
            allowed_keys = {"jsonrpc", "id", "method", "params"}
            # No 'alias' allowed here
            if set(first.keys()).issubset(allowed_keys):
                if first.get("jsonrpc") == "2.0" and first.get("id") == "plan" and first.get("method") == "aria2.changeGlobalOption":
                    params = first.get("params")
                    if isinstance(params, list) and len(params) >= 2:
                        token = params[0]
                        opts = params[1]
                        # token must be token:<secret>
                        token_ok = False
                        if expected_secret is not None:
                            token_ok = (token == f"token:{expected_secret}")
                        # opts must contain 'max-overall-download-limit' and 'max-concurrent-downloads'
                        opts_ok = False
                        if isinstance(opts, dict):
                            # Compare two specific keys from expected_global
                            gol = expected_global.get("max-overall-download-limit")
                            gcd = expected_global.get("max-concurrent-downloads")
                            have_gol = "max-overall-download-limit" in opts
                            have_gcd = "max-concurrent-downloads" in opts
                            gol_ok = False
                            gcd_ok = False
                            if have_gol and gol is not None:
                                gol_ok = (to_str(opts.get("max-overall-download-limit")) == to_str(gol))
                            if have_gcd and gcd is not None:
                                gcd_ok = (to_str(opts.get("max-concurrent-downloads")) == to_str(gcd))
                            opts_ok = gol_ok and gcd_ok
                        if token_ok and opts_ok:
                            checks["global_change_ok"] = True

        # Lines 2-4: addUri requests (order-insensitive by alias, but must be lines 2-4)
        adduri_lines_idx = [1, 2, 3]
        adduri_parsed = []
        adduri_valid_by_alias = {}
        adduri_positions_ok = True
        for idx in adduri_lines_idx:
            if idx < len(parsed) and isinstance(parsed[idx], dict):
                obj = parsed[idx]
                # allowed keys include alias
                allowed_add_keys = {"jsonrpc", "id", "method", "params", "alias"}
                if not set(obj.keys()).issubset(allowed_add_keys):
                    adduri_positions_ok = False
                    continue
                if not (obj.get("jsonrpc") == "2.0" and obj.get("id") == "plan" and obj.get("method") == "aria2.addUri"):
                    adduri_positions_ok = False
                    continue
                if "alias" not in obj or not isinstance(obj["alias"], str):
                    adduri_positions_ok = False
                    continue
                params = obj.get("params")
                if not (isinstance(params, list) and len(params) >= 3 and isinstance(params[1], list) and isinstance(params[2], dict)):
                    adduri_positions_ok = False
                    continue
                adduri_parsed.append(obj)
            else:
                adduri_positions_ok = False

        if adduri_positions_ok and expected_tasks:
            # Validate each addUri against expected tasks by alias
            for obj in adduri_parsed:
                alias = obj["alias"]
                params = obj["params"]
                token = params[0]
                uris = params[1]
                options = params[2]

                # token must match
                token_ok = expected_secret is not None and token == f"token:{expected_secret}"
                # alias must be in expected tasks
                alias_ok = alias in expected_tasks
                uris_ok = False
                opts_required_ok = False
                opts_absence_ok = True

                if alias_ok:
                    exp_task = expected_tasks[alias]
                    exp_uris = exp_task["uris"]
                    # URIs must exactly match list and order
                    if isinstance(exp_uris, list) and uris == exp_uris:
                        uris_ok = True

                    exp_opts = exp_task["options"]
                    # Required fields if present in plan should match; some are optional
                    # We also enforce absence of keys not present for specific ones: out, split, user-agent, max-connection-per-server, max-download-limit
                    # Always require dir to match
                    dir_ok = ("dir" in exp_opts and options.get("dir") == exp_opts.get("dir"))
                    # out
                    if "out" in exp_opts:
                        out_ok = options.get("out") == exp_opts.get("out")
                    else:
                        out_ok = "out" not in options
                    # split
                    if "split" in exp_opts:
                        split_ok = to_str(options.get("split")) == to_str(exp_opts.get("split"))
                    else:
                        split_ok = "split" not in options
                    # user-agent
                    if "user-agent" in exp_opts:
                        ua_ok = options.get("user-agent") == exp_opts.get("user-agent")
                    else:
                        ua_ok = "user-agent" not in options
                    # max-connection-per-server
                    if "max-connection-per-server" in exp_opts:
                        mcs_ok = to_str(options.get("max-connection-per-server")) == to_str(exp_opts.get("max-connection-per-server"))
                    else:
                        mcs_ok = "max-connection-per-server" not in options
                    # max-download-limit
                    if "max-download-limit" in exp_opts:
                        mdl_ok = to_str(options.get("max-download-limit")) == to_str(exp_opts.get("max-download-limit"))
                    else:
                        mdl_ok = "max-download-limit" not in options

                    opts_required_ok = dir_ok and out_ok and split_ok and ua_ok and mcs_ok and mdl_ok

                    # No check on extra keys in options beyond these and dir; allow extras

                adduri_valid_by_alias[alias] = (token_ok and alias_ok and uris_ok and opts_required_ok and opts_absence_ok)

            # Set per-alias checks for alpha, beta, gamma specifically if present
            if "alpha" in adduri_valid_by_alias:
                checks["adduri_alpha_ok"] = adduri_valid_by_alias["alpha"]
            if "beta" in adduri_valid_by_alias:
                checks["adduri_beta_ok"] = adduri_valid_by_alias["beta"]
            if "gamma" in adduri_valid_by_alias:
                checks["adduri_gamma_ok"] = adduri_valid_by_alias["gamma"]

        # Lines 5-7: post actions in exact order: pause beta, unpause beta, forceRemove gamma
        post_ok = False
        if len(parsed) >= 7 and isinstance(parsed[4], dict) and isinstance(parsed[5], dict) and isinstance(parsed[6], dict):
            pa1, pa2, pa3 = parsed[4], parsed[5], parsed[6]
            def is_valid_pa(obj, method, alias, secret):
                allowed_keys = {"jsonrpc", "id", "method", "params"}
                if not set(obj.keys()).issubset(allowed_keys):
                    return False
                if not (obj.get("jsonrpc") == "2.0" and obj.get("id") == "plan" and obj.get("method") == method):
                    return False
                params = obj.get("params")
                if not (isinstance(params, list) and len(params) == 2):
                    return False
                token_ok = (secret is not None and params[0] == f"token:{secret}")
                gid_ok = (params[1] == f"GID::{alias}")
                return token_ok and gid_ok

            secret = expected_secret
            p1_ok = is_valid_pa(pa1, "aria2.pause", "beta", secret)
            p2_ok = is_valid_pa(pa2, "aria2.unpause", "beta", secret)
            p3_ok = is_valid_pa(pa3, "aria2.forceRemove", "gamma", secret)
            post_ok = p1_ok and p2_ok and p3_ok

        checks["post_actions_ok"] = post_ok

    # Validate summary.json
    if summary_json is not None and isinstance(summary_json, dict):
        # global_options equality by keys and string value equality
        sg = summary_json.get("global_options")
        sg_ok = False
        if isinstance(sg, dict) and isinstance(expected_global, dict):
            # Exact same keys as expected_global
            if set(sg.keys()) == set(expected_global.keys()):
                values_match = True
                for k, v in expected_global.items():
                    if to_str(sg.get(k)) != to_str(v):
                        values_match = False
                        break
                sg_ok = values_match
        checks["summary_global_ok"] = sg_ok

        # tasks validation
        st = summary_json.get("tasks")
        st_ok = False
        if isinstance(st, dict) and expected_tasks:
            per_task_ok = True
            # Ensure all expected aliases present and only those (no extras)
            if set(st.keys()) != set(expected_tasks.keys()):
                per_task_ok = False
            else:
                allowed_task_keys = {
                    "dir",
                    "out",
                    "split",
                    "user-agent",
                    "max-connection-per-server",
                    "max-download-limit",
                    "uri_count"
                }
                for alias, exp in expected_tasks.items():
                    item = st.get(alias)
                    if not isinstance(item, dict):
                        per_task_ok = False
                        break
                    # Build expected key set: dir + uri_count + any of specific keys present in plan options
                    exp_opts = exp.get("options", {})
                    exp_keys = {"dir", "uri_count"}
                    for k in ["out", "split", "user-agent", "max-connection-per-server", "max-download-limit"]:
                        if k in exp_opts:
                            exp_keys.add(k)
                    # The item must not contain extra keys beyond allowed_task_keys, and must match exactly exp_keys subset of allowed set
                    item_keys = set(item.keys())
                    if not item_keys.issubset(allowed_task_keys):
                        per_task_ok = False
                        break
                    if item_keys != exp_keys:
                        per_task_ok = False
                        break
                    # Validate dir
                    if item.get("dir") != exp_opts.get("dir"):
                        per_task_ok = False
                        break
                    # Validate optional fields values
                    # out
                    if "out" in exp_opts and item.get("out") != exp_opts.get("out"):
                        per_task_ok = False
                        break
                    # split
                    if "split" in exp_opts and to_str(item.get("split")) != to_str(exp_opts.get("split")):
                        per_task_ok = False
                        break
                    # user-agent
                    if "user-agent" in exp_opts and item.get("user-agent") != exp_opts.get("user-agent"):
                        per_task_ok = False
                        break
                    # max-connection-per-server
                    if "max-connection-per-server" in exp_opts and to_str(item.get("max-connection-per-server")) != to_str(exp_opts.get("max-connection-per-server")):
                        per_task_ok = False
                        break
                    # max-download-limit
                    if "max-download-limit" in exp_opts and to_str(item.get("max-download-limit")) != to_str(exp_opts.get("max-download-limit")):
                        per_task_ok = False
                        break
                    # uri_count
                    if item.get("uri_count") != len(exp.get("uris", [])):
                        per_task_ok = False
                        break
            st_ok = per_task_ok
        checks["summary_tasks_ok"] = st_ok

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if required artifacts missing entirely, reward must be 0.0
    # If both output files are missing or requests not present, force 0
    if not checks["requests_file_exists"] and not checks["summary_file_exists"]:
        reward = 0.0

    # Clamp between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()