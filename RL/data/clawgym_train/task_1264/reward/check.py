import json
import os
import sys
import csv

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "actions_json_exists": False,
        "actions_json_schema_valid": False,
        "delete_set_exact": False,
        "pull_set_exact": False,
        "summary_freed_total_exact": False,
        "summary_per_node_exact": False,
        "summary_post_free_gb_exact": False,
        "disk_usage_csv_exists": False,
        "disk_usage_schema_valid": False,
        "disk_usage_rows_exact": False,
    }

    # Expected values based on task specification
    expected_delete = [
        {"node_id": "gpu-a", "model": "llama3:70b", "size_gb": 40.0, "reason": "unused_21d"},
        {"node_id": "gpu-a", "model": "mistral:7b", "size_gb": 4.1, "reason": "unused_21d"},
        {"node_id": "gpu-a", "model": "phi:3.8b", "size_gb": 2.0, "reason": "unused_21d"},
        {"node_id": "gpu-b", "model": "qwen2.5:14b", "size_gb": 8.0, "reason": "unused_21d"},
        {"node_id": "cpu-c", "model": "mistral:7b", "size_gb": 4.1, "reason": "unused_21d"},
        {"node_id": "cpu-c", "model": "tinyllama:1.1b", "size_gb": 0.8, "reason": "unused_21d"},
    ]
    expected_delete_set = {(d["node_id"], d["model"], round(float(d["size_gb"]), 1), d["reason"]) for d in expected_delete}
    expected_delete_total = 59.0
    expected_per_node = {"gpu-a": 46.1, "gpu-b": 8.0, "cpu-c": 4.9}
    expected_post_free_gb = {"gpu-a": 82.9, "gpu-b": 15.0, "cpu-c": 122.9}

    expected_pull = [
        {"node_id": "gpu-a", "model": "qwen2.5:14b", "size_gb": 8.0, "reason": "recommended"},
        {"node_id": "gpu-a", "model": "llama3.1:8b", "size_gb": 5.2, "reason": "recommended"},
        {"node_id": "gpu-b", "model": "codestral:22b", "size_gb": 13.0, "reason": "recommended"},
        {"node_id": "cpu-c", "model": "phi:3.8b", "size_gb": 2.0, "reason": "recommended"},
    ]
    expected_pull_set = {(p["node_id"], p["model"], round(float(p["size_gb"]), 1), p["reason"]) for p in expected_pull}

    actions_path = os.path.join(output_dir, "actions.json")
    disk_usage_path = os.path.join(output_dir, "disk_usage.csv")

    actions = None
    # Check actions.json existence and schema
    if os.path.isfile(actions_path):
        checks["actions_json_exists"] = True
        try:
            with open(actions_path, "r", encoding="utf-8") as f:
                actions = json.load(f)
            if (
                isinstance(actions, dict)
                and "delete" in actions
                and "pull" in actions
                and "summary" in actions
                and isinstance(actions.get("delete"), list)
                and isinstance(actions.get("pull"), list)
                and isinstance(actions.get("summary"), dict)
            ):
                checks["actions_json_schema_valid"] = True
        except Exception:
            actions = None

    # If schema valid, run deeper checks
    if checks["actions_json_schema_valid"]:
        # Delete set exact match (order-agnostic)
        try:
            delete_list = actions.get("delete", [])
            observed_delete_set = set()
            valid_delete_entries = True
            for item in delete_list:
                if not isinstance(item, dict):
                    valid_delete_entries = False
                    break
                node_id = item.get("node_id")
                model = item.get("model")
                reason = item.get("reason")
                size_gb = item.get("size_gb")
                try:
                    size_gb_val = round(float(size_gb), 1)
                except Exception:
                    valid_delete_entries = False
                    break
                if not (isinstance(node_id, str) and isinstance(model, str) and isinstance(reason, str)):
                    valid_delete_entries = False
                    break
                observed_delete_set.add((node_id, model, size_gb_val, reason))
            if valid_delete_entries and observed_delete_set == expected_delete_set and len(delete_list) == len(expected_delete):
                checks["delete_set_exact"] = True
        except Exception:
            pass

        # Pull set exact match (order-agnostic)
        try:
            pull_list = actions.get("pull", [])
            observed_pull_set = set()
            valid_pull_entries = True
            for item in pull_list:
                if not isinstance(item, dict):
                    valid_pull_entries = False
                    break
                node_id = item.get("node_id")
                model = item.get("model")
                reason = item.get("reason")
                size_gb = item.get("size_gb")
                try:
                    size_gb_val = round(float(size_gb), 1)
                except Exception:
                    valid_pull_entries = False
                    break
                if not (isinstance(node_id, str) and isinstance(model, str) and isinstance(reason, str)):
                    valid_pull_entries = False
                    break
                observed_pull_set.add((node_id, model, size_gb_val, reason))
            if valid_pull_entries and observed_pull_set == expected_pull_set and len(pull_list) == len(expected_pull):
                checks["pull_set_exact"] = True
        except Exception:
            pass

        # Summary checks
        try:
            summary = actions.get("summary", {})
            # freed_gb_total
            freed_val = summary.get("freed_gb_total", None)
            if freed_val is not None:
                try:
                    if round(float(freed_val), 1) == round(expected_delete_total, 1):
                        checks["summary_freed_total_exact"] = True
                except Exception:
                    pass
            # per_node
            per_node = summary.get("per_node", None)
            if isinstance(per_node, dict):
                try:
                    # All expected keys and exact numeric values (one decimal)
                    keys_ok = set(per_node.keys()) == set(expected_per_node.keys())
                    values_ok = all(round(float(per_node[k]), 1) == round(expected_per_node[k], 1) for k in expected_per_node)
                    if keys_ok and values_ok:
                        checks["summary_per_node_exact"] = True
                except Exception:
                    pass
            # post_free_gb
            post_free = summary.get("post_free_gb", None)
            if isinstance(post_free, dict):
                try:
                    keys_ok = set(post_free.keys()) == set(expected_post_free_gb.keys())
                    values_ok = all(round(float(post_free[k]), 1) == round(expected_post_free_gb[k], 1) for k in expected_post_free_gb)
                    if keys_ok and values_ok:
                        checks["summary_post_free_gb_exact"] = True
                except Exception:
                    pass
        except Exception:
            pass

    # disk_usage.csv checks
    if os.path.isfile(disk_usage_path):
        checks["disk_usage_csv_exists"] = True
        try:
            with open(disk_usage_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == ["node_id", "model", "size_gb"]:
                    checks["disk_usage_schema_valid"] = True
                    data_rows = rows[1:]
                    # Expected 10 data rows
                    expected_rows = [
                        ("gpu-a", "llama3:8b", 4.5),
                        ("gpu-a", "mistral:7b", 4.1),
                        ("gpu-a", "phi:3.8b", 2.0),
                        ("gpu-a", "llama3:70b", 40.0),
                        ("gpu-b", "llama3:8b", 4.5),
                        ("gpu-b", "llama3:70b", 40.0),
                        ("gpu-b", "qwen2.5:14b", 8.0),
                        ("cpu-c", "orca-mini:3b", 1.5),
                        ("cpu-c", "mistral:7b", 4.1),
                        ("cpu-c", "tinyllama:1.1b", 0.8),
                    ]
                    expected_set = {(n, m, round(s, 1)) for (n, m, s) in expected_rows}
                    observed_set = set()
                    valid_rows = True
                    for r in data_rows:
                        if len(r) != 3:
                            valid_rows = False
                            break
                        node_id, model, sz_str = r
                        try:
                            sz_val = round(float(sz_str), 1)
                        except Exception:
                            valid_rows = False
                            break
                        observed_set.add((node_id, model, sz_val))
                    if valid_rows and len(data_rows) == 10 and observed_set == expected_set:
                        checks["disk_usage_rows_exact"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks; baseline 0 if no outputs
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure no-op baseline: if neither output file exists, reward is 0.0
    if not checks["actions_json_exists"] and not checks["disk_usage_csv_exists"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()