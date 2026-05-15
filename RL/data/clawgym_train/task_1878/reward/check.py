import json
import os
import sys
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Report checks
        "report_exists": False,
        "report_valid_json_array": False,
        "report_has_render_pure_memo_App": False,
        "report_has_render_props_once_App": False,
        "report_has_render_merge_setstate_App": False,
        "report_has_render_avoid_same_state_App": False,
        "report_has_list_key_ListScreen": False,
        "report_has_lifecycle_ArkTSPage": False,
        "report_has_bundle_release_build_config": False,

        # App.fixed.txt checks
        "app_fixed_exists": False,
        "app_fixed_has_memo_or_pure": False,
        "app_fixed_has_stable_callbacks": False,
        "app_fixed_has_stylesheet_and_no_inline": False,
        "app_fixed_has_promise_all": False,
        "app_fixed_has_skip_unchanged_guard": False,

        # ListScreen.fixed.txt checks
        "list_fixed_exists": False,
        "list_fixed_has_stable_key": False,
        "list_fixed_no_index_key": False,

        # ArkTSPage.fixed.txt checks
        "arkts_fixed_exists": False,
        "arkts_has_onPageShow_foreground": False,
        "arkts_has_onPageHide_background": False,

        # build_config.release.json checks
        "build_release_exists": False,
        "build_release_valid_json": False,
        "build_release_flags_correct": False,

        # README.md checks
        "readme_exists": False,
        "readme_mentions_all_rules": False,
    }

    # -------- Report validation --------
    report_path = os.path.join(output_dir, "rnoh_report.json")
    report_data = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            if isinstance(report_data, list):
                checks["report_valid_json_array"] = True
        except Exception:
            report_data = None

    # Helper to find rule in report with correct file mapping and description
    def has_finding(rule_id, file_name):
        if not isinstance(report_data, list):
            return False
        for item in report_data:
            if not isinstance(item, dict):
                continue
            rid = item.get("ruleId")
            fn = item.get("file")
            desc = item.get("description")
            if rid == rule_id and fn == file_name and isinstance(desc, str) and len(desc.strip()) > 0:
                return True
        return False

    if checks["report_valid_json_array"]:
        # Required ruleIds mapped to relevant files
        if has_finding("rnoh-render-pure-memo", "input/App.txt"):
            checks["report_has_render_pure_memo_App"] = True
        if has_finding("rnoh-render-props-once", "input/App.txt"):
            checks["report_has_render_props_once_App"] = True
        if has_finding("rnoh-render-merge-setstate", "input/App.txt"):
            checks["report_has_render_merge_setstate_App"] = True
        if has_finding("rnoh-render-avoid-same-state", "input/App.txt"):
            checks["report_has_render_avoid_same_state_App"] = True
        if has_finding("rnoh-list-key", "input/ListScreen.txt"):
            checks["report_has_list_key_ListScreen"] = True
        if has_finding("rnoh-lifecycle-foreground-background", "input/ArkTSPage.txt"):
            checks["report_has_lifecycle_ArkTSPage"] = True
        if has_finding("rnoh-bundle-release", "input/build_config.json"):
            checks["report_has_bundle_release_build_config"] = True

    # -------- Fixed App checks --------
    app_fixed_path = os.path.join(output_dir, "fixed", "App.fixed.txt")
    if os.path.isfile(app_fixed_path):
        checks["app_fixed_exists"] = True
        try:
            with open(app_fixed_path, "r", encoding="utf-8") as f:
                app_content = f.read()
        except Exception:
            app_content = ""

        # Contains either "React.memo(" or "PureComponent"
        if ("React.memo(" in app_content) or ("PureComponent" in app_content):
            checks["app_fixed_has_memo_or_pure"] = True

        # Contains either "useCallback(" or ".bind("
        if ("useCallback(" in app_content) or (".bind(" in app_content):
            checks["app_fixed_has_stable_callbacks"] = True

        # Contains "StyleSheet.create(" and does not contain "style={{"
        if ("StyleSheet.create(" in app_content) and ("style={{" not in app_content):
            checks["app_fixed_has_stylesheet_and_no_inline"] = True

        # Contains "Promise.all("
        if "Promise.all(" in app_content:
            checks["app_fixed_has_promise_all"] = True

        # Guard to skip unchanged updates: look for specific patterns
        guard_patterns = [
            "if (newCount !== this.state.count",
            "return next === prev.count ? prev :",
            "if (newCount !== count"
        ]
        if any(pat in app_content for pat in guard_patterns):
            checks["app_fixed_has_skip_unchanged_guard"] = True

    # -------- Fixed ListScreen checks --------
    list_fixed_path = os.path.join(output_dir, "fixed", "ListScreen.fixed.txt")
    if os.path.isfile(list_fixed_path):
        checks["list_fixed_exists"] = True
        try:
            with open(list_fixed_path, "r", encoding="utf-8") as f:
                list_content = f.read()
        except Exception:
            list_content = ""

        # Must not contain key={index}
        if "key={index}" not in list_content:
            checks["list_fixed_no_index_key"] = True

        # Should contain stable unique key, e.g., key={item.id} or similar
        has_item_id_exact = "key={item.id}" in list_content
        has_item_prop_key = re.search(r'key=\{item\.[A-Za-z_][A-Za-z0-9_]*\}', list_content) is not None
        if (has_item_id_exact or has_item_prop_key) and checks["list_fixed_no_index_key"]:
            checks["list_fixed_has_stable_key"] = True

    # -------- Fixed ArkTSPage checks --------
    arkts_fixed_path = os.path.join(output_dir, "fixed", "ArkTSPage.fixed.txt")
    if os.path.isfile(arkts_fixed_path):
        checks["arkts_fixed_exists"] = True
        try:
            with open(arkts_fixed_path, "r", encoding="utf-8") as f:
                arkts_content = f.read()
        except Exception:
            arkts_content = ""

        if ("onPageShow" in arkts_content) and ("this.rnAbility?.onForeground();" in arkts_content):
            checks["arkts_has_onPageShow_foreground"] = True
        if ("onPageHide" in arkts_content) and ("this.rnAbility?.onBackground();" in arkts_content):
            checks["arkts_has_onPageHide_background"] = True

    # -------- build_config.release.json checks --------
    build_release_path = os.path.join(output_dir, "fixed", "build_config.release.json")
    build_release_data = None
    if os.path.isfile(build_release_path):
        checks["build_release_exists"] = True
        try:
            with open(build_release_path, "r", encoding="utf-8") as f:
                build_release_data = json.load(f)
            checks["build_release_valid_json"] = isinstance(build_release_data, dict)
        except Exception:
            build_release_data = None

        if isinstance(build_release_data, dict):
            bundle_dev = build_release_data.get("bundleDev")
            bundle_minify = build_release_data.get("bundleMinify")
            if bundle_dev is False and bundle_minify is True:
                checks["build_release_flags_correct"] = True

    # -------- README.md checks --------
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_content = f.read()
        except Exception:
            readme_content = ""

        required_rule_ids = [
            "rnoh-render-pure-memo",
            "rnoh-render-props-once",
            "rnoh-render-merge-setstate",
            "rnoh-render-avoid-same-state",
            "rnoh-list-key",
            "rnoh-lifecycle-foreground-background",
            "rnoh-bundle-release",
        ]
        if all(rid in readme_content for rid in required_rule_ids):
            checks["readme_mentions_all_rules"] = True

    # Compute reward as ratio of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0
    # Ensure baseline: if no outputs relevant exist, reward should be 0.0 (passed would be 0)
    if passed == 0:
        reward = 0.0
    # Bound between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()