import json
import os
import sys
from typing import List

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def safe_load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def contains_all_substrings(text: str, subs: List[str], case_insensitive: bool = True) -> bool:
    hay = text.lower() if case_insensitive else text
    for s in subs:
        needle = s.lower() if case_insensitive else s
        if needle not in hay:
            return False
    return True

def get_section(text: str, start_marker: str, end_markers: List[str]) -> str:
    # Returns text starting from first occurrence of start_marker up to the earliest occurrence of any end_markers after it
    idx = text.find(start_marker)
    if idx == -1:
        return ""
    start = idx + len(start_marker)
    end_positions = [text.find(m, start) for m in end_markers if text.find(m, start) != -1]
    if end_positions:
        end = min(end_positions)
        return text[start:end]
    return text[start:]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks - all False by default
    checks = {
        "has_review_json": False,
        "has_review_md": False,
        "has_fixes_md": False,
        "valid_json": False,
        "all_keys_present": False,
        "ios_target_min_ok": False,
        "booleans_true_set": False,
        "critical_findings_ok": False,
        "md_contains_substrings": False,
        "md_length_ok": False,
        "fixes_has_p0_p1_p2": False,
        "fixes_p0_actions_ok": False,
    }

    review_json_path = os.path.join(output_dir, "review.json")
    review_md_path = os.path.join(output_dir, "review.md")
    fixes_md_path = os.path.join(output_dir, "fixes.md")

    # Existence checks
    if os.path.isfile(review_json_path):
        checks["has_review_json"] = True
    if os.path.isfile(review_md_path) and len(read_text(review_md_path)) > 0:
        checks["has_review_md"] = True
    if os.path.isfile(fixes_md_path) and len(read_text(fixes_md_path)) > 0:
        checks["has_fixes_md"] = True

    # JSON schema/content checks
    required_keys = [
        "ios_target_min",
        "perform_mainactor_violation",
        "perform_timeout_risk",
        "custom_error_localization_missing",
        "swiftdata_persistent_id_issue",
        "entity_query_voice_input_issue",
        "suggested_entities_missing",
        "entity_id_stability_issue",
        "dependency_injection_in_query",
        "nonoptional_parameter_missing_default",
        "parameter_dependency_ios16_guard_missing",
        "shortcuts_phrases_missing_app_name",
        "shortcuts_localization_wrong_file",
        "appintents_in_swift_package_pre17",
        "openAppWhenRun_missing_for_long_ops",
        "critical_findings",
    ]
    expected_true_fields = [
        "perform_mainactor_violation",
        "perform_timeout_risk",
        "custom_error_localization_missing",
        "swiftdata_persistent_id_issue",
        "entity_query_voice_input_issue",
        "suggested_entities_missing",
        "entity_id_stability_issue",
        "dependency_injection_in_query",
        "nonoptional_parameter_missing_default",
        "parameter_dependency_ios16_guard_missing",
        "shortcuts_phrases_missing_app_name",
        "shortcuts_localization_wrong_file",
        "appintents_in_swift_package_pre17",
        "openAppWhenRun_missing_for_long_ops",
    ]
    review_obj = None
    if checks["has_review_json"]:
        review_obj, ok = safe_load_json(review_json_path)
        if ok and isinstance(review_obj, dict):
            checks["valid_json"] = True
            # All required keys present
            if all(k in review_obj for k in required_keys):
                checks["all_keys_present"] = True
                # ios_target_min must equal "iOS 16"
                if review_obj.get("ios_target_min") == "iOS 16":
                    checks["ios_target_min_ok"] = True
                # Following boolean fields must be True
                booleans_ok = True
                for k in expected_true_fields:
                    if review_obj.get(k) is not True:
                        booleans_ok = False
                        break
                checks["booleans_true_set"] = booleans_ok
                # critical_findings validation
                crit = review_obj.get("critical_findings")
                required_concepts = [
                    "@MainActor",
                    "30-second",
                    "CustomLocalizedStringResourceConvertible",
                    "EntityStringQuery",
                    "suggestedEntities",
                    "persistentModelID",
                    "@Dependency",
                    "@IntentParameterDependency",
                    ".applicationName",
                    "AppShortcuts.strings",
                ]
                crit_ok = False
                if isinstance(crit, list) and all(isinstance(x, str) for x in crit):
                    # at least 8 items
                    if len(crit) >= 8:
                        # coverage: at least 8 distinct concepts must appear across items
                        combined = " ".join(crit).lower()
                        covered = 0
                        for concept in required_concepts:
                            if concept.lower() in combined:
                                covered += 1
                        if covered >= 8:
                            crit_ok = True
                checks["critical_findings_ok"] = crit_ok

    # review.md content heuristics
    if checks["has_review_md"]:
        md_text = read_text(review_md_path)
        required_substrings = [
            "@MainActor",
            "30-second timeout",
            "CustomLocalizedStringResourceConvertible",
            "EntityStringQuery",
            "suggestedEntities()",
            "stable identifier",
            "persistentModelID",
            "@Dependency",
            "@IntentParameterDependency",
            "#available(iOS 17",
            ".applicationName",
            "AppShortcuts.strings",
            "Localizable.strings",
            "openAppWhenRun",
        ]
        if contains_all_substrings(md_text, required_substrings, case_insensitive=True):
            checks["md_contains_substrings"] = True
        if len(md_text) >= 1200:
            checks["md_length_ok"] = True

    # fixes.md prioritization checks
    if checks["has_fixes_md"]:
        fixes_text = read_text(fixes_md_path)
        # Check presence of P0, P1, P2 markers (simple substring match)
        has_p0 = "P0" in fixes_text
        has_p1 = "P1" in fixes_text
        has_p2 = "P2" in fixes_text
        if has_p0 and has_p1 and has_p2:
            checks["fixes_has_p0_p1_p2"] = True

        # Extract P0 section and validate required actionable references
        p0_section = get_section(fixes_text, "P0", ["P1", "P2"])
        p0_ok = False
        if p0_section:
            # Must reference "EntityStringQuery", "@IntentParameterDependency" with availability, and ".applicationName"
            has_entity_string_query = "EntityStringQuery" in p0_section
            has_dependency_param = "@IntentParameterDependency" in p0_section
            # Availability hint - accept presence of "#available" within the P0 section
            has_availability = "#available" in p0_section or "availability" in p0_section.lower()
            has_app_name_placeholder = ".applicationName" in p0_section
            if has_entity_string_query and has_dependency_param and has_availability and has_app_name_placeholder:
                p0_ok = True
        checks["fixes_p0_actions_ok"] = p0_ok

    # Compute reward as average of passed checks; no-op baseline => 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if any(checks.values()):
        reward = passed / total

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()