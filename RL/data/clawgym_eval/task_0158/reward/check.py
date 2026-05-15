import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_analysis_json": False,
        "analysis_counts_match": False,
        "has_plan_json": False,
        "plan_delete_dup2": False,
        "plan_update_news_tracked": False,
        "plan_update_insecure": False,
        "plan_delete_fld_old": False,
        "plan_move_solo_to_bar": False,
        "plan_delete_fld_single": False,
        "plan_rename_weakname": False,
    }

    # Paths
    analysis_path = os.path.join(output_dir, "analysis.json")
    plan_path = os.path.join(output_dir, "plan.json")

    # Load analysis.json
    analysis = None
    if os.path.isfile(analysis_path):
        analysis = load_json(analysis_path)
        if isinstance(analysis, dict):
            checks["has_analysis_json"] = True

    # Verify analysis summary counts
    expected_counts = {
        "total_bookmarks": 9,
        "duplicate_exact_groups": 1,
        "duplicate_semantic_groups": 2,
        "tracking_variant_groups": 1,
        "http_links": 1,
        "empty_folders": 1,
        "singleton_folders": 1,
        "deep_folders": 2,
        "weak_names": 1,
        "invalid_urls": 1,
    }
    if checks["has_analysis_json"]:
        summary = analysis.get("summary") if isinstance(analysis, dict) else None
        if isinstance(summary, dict):
            ok = True
            for k, v in expected_counts.items():
                if summary.get(k) != v:
                    ok = False
                    break
            checks["analysis_counts_match"] = ok

    # Load plan.json
    plan = None
    if os.path.isfile(plan_path):
        plan = load_json(plan_path)
        if isinstance(plan, dict):
            checks["has_plan_json"] = True

    # Helper to inspect operations
    ops = []
    if checks["has_plan_json"]:
        ops = plan.get("operations")
        if not isinstance(ops, list):
            ops = []

    def selector_guid(sel):
        if isinstance(sel, dict):
            guid = sel.get("guid")
            if isinstance(guid, str):
                return guid
        return None

    # Finders for required operations
    if ops:
        # delete guid "url-dup2"
        for op in ops:
            if isinstance(op, dict) and op.get("action") == "delete":
                sel = op.get("selector")
                if selector_guid(sel) == "url-dup2":
                    checks["plan_delete_dup2"] = True
                    break

        # update_url guid "url-news-tracked" -> "https://example.com/news"
        for op in ops:
            if isinstance(op, dict) and op.get("action") == "update_url":
                sel = op.get("selector")
                if selector_guid(sel) == "url-news-tracked" and op.get("new_url") == "https://example.com/news":
                    checks["plan_update_news_tracked"] = True
                    break

        # update_url guid "url-insecure" -> "https://insecure.example.com/page"
        for op in ops:
            if isinstance(op, dict) and op.get("action") == "update_url":
                sel = op.get("selector")
                if selector_guid(sel) == "url-insecure" and op.get("new_url") == "https://insecure.example.com/page":
                    checks["plan_update_insecure"] = True
                    break

        # delete guid "fld-old"
        for op in ops:
            if isinstance(op, dict) and op.get("action") == "delete":
                sel = op.get("selector")
                if selector_guid(sel) == "fld-old":
                    checks["plan_delete_fld_old"] = True
                    break

        # move guid "url-solo" to root bookmark_bar
        for op in ops:
            if isinstance(op, dict) and op.get("action") == "move":
                sel = op.get("selector")
                if selector_guid(sel) == "url-solo":
                    target = op.get("target") or op.get("parent")
                    if isinstance(target, dict):
                        root_ok = target.get("root") == "bookmark_bar"
                        path_val = target.get("path")
                        path_ok = path_val in ("/bookmark_bar", "/bookmark_bar/")
                        if root_ok or path_ok:
                            checks["plan_move_solo_to_bar"] = True
                            break

        # delete guid "fld-single"
        for op in ops:
            if isinstance(op, dict) and op.get("action") == "delete":
                sel = op.get("selector")
                if selector_guid(sel) == "fld-single":
                    checks["plan_delete_fld_single"] = True
                    break

        # rename guid "url-weakname" -> "Docs"
        for op in ops:
            if isinstance(op, dict) and op.get("action") == "rename":
                sel = op.get("selector")
                if selector_guid(sel) == "url-weakname" and op.get("new_name") == "Docs":
                    checks["plan_rename_weakname"] = True
                    break

    # Compute reward: average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Explicit no-op baseline: if output dir missing OR both required files missing, reward = 0.0
    if (not os.path.isdir(output_dir)) or (not os.path.isfile(analysis_path) and not os.path.isfile(plan_path)):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()