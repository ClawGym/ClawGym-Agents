import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_list_of_strings(x):
    return isinstance(x, list) and all(isinstance(i, str) for i in x)

def set_from_mixed_list(x):
    if not isinstance(x, list):
        return set()
    return {str(i) for i in x if isinstance(i, str)}

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Expected sets for this dataset (order-insensitive)
    expected_auto_review = {
        "approved": {"node", "npm-package-a"},
        "blocked": {"npm-package-b", "npm-package-c", "openssl@3"},
        "pending": {"npm-package-d", "wget"},
    }
    expected_upgrade_plan = {
        "npm": {"npm-package-a"},
        "brew": {"node"},
        "apt_hold": {"curl", "vim"},
    }
    # Report expectations
    expected_report_lines = {
        "apt": "Actually installed (apt): 2 packages",
        "npm": "Actually installed (npm): 0 packages",
        "brew": "Actually installed (brew): 0 packages",
    }
    expected_upgradable_mentions = {"curl", "libssl1.1", "vim"}
    expected_apt_hold_mentions = {"curl", "vim"}

    # Paths
    auto_review_path = os.path.join(output_dir, "auto_review_decisions.json")
    upgrade_plan_path = os.path.join(output_dir, "upgrade_plan.json")
    report_path = os.path.join(output_dir, "report_9am.txt")

    # ---- Auto review checks ----
    checks["has_auto_review_file"] = os.path.isfile(auto_review_path)
    auto_review_data = None
    if checks["has_auto_review_file"]:
        auto_review_data = load_json_file(auto_review_path)
    checks["auto_review_json_valid"] = checks["has_auto_review_file"] and isinstance(auto_review_data, dict)
    checks["auto_review_has_required_keys"] = False
    checks["auto_review_approved_set_correct"] = False
    checks["auto_review_blocked_set_correct"] = False
    checks["auto_review_pending_set_correct"] = False

    if checks["auto_review_json_valid"]:
        keys_present = all(k in auto_review_data for k in ["approved", "blocked", "pending"])
        if keys_present:
            checks["auto_review_has_required_keys"] = all(
                is_list_of_strings(auto_review_data.get(k)) for k in ["approved", "blocked", "pending"]
            )
            if checks["auto_review_has_required_keys"]:
                approved_set = set_from_mixed_list(auto_review_data.get("approved"))
                blocked_set = set_from_mixed_list(auto_review_data.get("blocked"))
                pending_set = set_from_mixed_list(auto_review_data.get("pending"))

                checks["auto_review_approved_set_correct"] = (approved_set == expected_auto_review["approved"])
                checks["auto_review_blocked_set_correct"] = (blocked_set == expected_auto_review["blocked"])
                checks["auto_review_pending_set_correct"] = (pending_set == expected_auto_review["pending"])

    # ---- Upgrade plan checks ----
    checks["has_upgrade_plan_file"] = os.path.isfile(upgrade_plan_path)
    upgrade_plan_data = None
    if checks["has_upgrade_plan_file"]:
        upgrade_plan_data = load_json_file(upgrade_plan_path)
    checks["upgrade_plan_json_valid"] = checks["has_upgrade_plan_file"] and isinstance(upgrade_plan_data, dict)
    checks["upgrade_plan_has_required_keys"] = False
    checks["upgrade_plan_npm_set_correct"] = False
    checks["upgrade_plan_brew_set_correct"] = False
    checks["upgrade_plan_apt_hold_set_correct"] = False

    if checks["upgrade_plan_json_valid"]:
        keys_present_up = all(k in upgrade_plan_data for k in ["npm", "brew", "apt_hold"])
        if keys_present_up:
            checks["upgrade_plan_has_required_keys"] = all(
                is_list_of_strings(upgrade_plan_data.get(k)) for k in ["npm", "brew", "apt_hold"]
            )
            if checks["upgrade_plan_has_required_keys"]:
                npm_set = set_from_mixed_list(upgrade_plan_data.get("npm"))
                brew_set = set_from_mixed_list(upgrade_plan_data.get("brew"))
                apt_hold_set = set_from_mixed_list(upgrade_plan_data.get("apt_hold"))

                checks["upgrade_plan_npm_set_correct"] = (npm_set == expected_upgrade_plan["npm"])
                checks["upgrade_plan_brew_set_correct"] = (brew_set == expected_upgrade_plan["brew"])
                checks["upgrade_plan_apt_hold_set_correct"] = (apt_hold_set == expected_upgrade_plan["apt_hold"])

    # ---- Report checks ----
    checks["has_report_file"] = os.path.isfile(report_path)
    checks["report_non_empty"] = False
    checks["report_line_apt_installed_correct"] = False
    checks["report_line_npm_installed_zero"] = False
    checks["report_line_brew_installed_zero"] = False
    checks["report_mentions_all_upgradable"] = False
    checks["report_mentions_all_apt_hold"] = False

    if checks["has_report_file"]:
        try:
            with open(report_path, "r", encoding="utf-8") as rf:
                content = rf.read()
        except Exception:
            content = ""
        checks["report_non_empty"] = bool(content.strip())
        if content:
            lines = [ln.rstrip("\n\r") for ln in content.splitlines()]
            checks["report_line_apt_installed_correct"] = any(
                ln == expected_report_lines["apt"] for ln in lines
            )
            checks["report_line_npm_installed_zero"] = any(
                ln == expected_report_lines["npm"] for ln in lines
            )
            checks["report_line_brew_installed_zero"] = any(
                ln == expected_report_lines["brew"] for ln in lines
            )
            # Mentions
            mentions_upgradable = all(pkg in content for pkg in expected_upgradable_mentions)
            mentions_apt_hold = all(pkg in content for pkg in expected_apt_hold_mentions)
            checks["report_mentions_all_upgradable"] = mentions_upgradable
            checks["report_mentions_all_apt_hold"] = mentions_apt_hold

    # Compute reward: proportion of passed checks.
    # Baseline: if output directory missing or none of the three files exist, reward stays 0.0
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        any_file = checks["has_auto_review_file"] or checks["has_upgrade_plan_file"] or checks["has_report_file"]
        if not any_file:
            reward = 0.0
        else:
            reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()