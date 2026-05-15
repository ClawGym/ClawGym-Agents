import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def get_workspace_root() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_json_file(path: str) -> Tuple[bool, Any]:
    if not os.path.isfile(path):
        return False, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def load_text_file(path: str) -> Tuple[bool, str]:
    if not os.path.isfile(path):
        return False, ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    if isinstance(v, (int, float)):
        return v != 0
    return bool(v)

def parse_queries_file(path: str) -> List[str]:
    ok, content = load_text_file(path)
    if not ok:
        return []
    lines = [ln.strip() for ln in content.splitlines()]
    return [ln for ln in lines if ln != ""]

def count_category_headings(md_text: str) -> int:
    # Count distinct "## " headings that are not "Next Steps"
    headings = set()
    for line in md_text.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            if title and title.lower() != "next steps":
                headings.add(title)
    return len(headings)

def find_next_steps_recommendations(md_text: str) -> int:
    # Find a heading containing "Next Steps" (any # level), then count bullet-like lines until next heading
    lines = md_text.splitlines()
    next_steps_idx = -1
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") and "next steps" in line.lower():
            next_steps_idx = i
            break
    if next_steps_idx == -1:
        return 0
    rec_count = 0
    for j in range(next_steps_idx + 1, len(lines)):
        line = lines[j]
        if line.lstrip().startswith("#"):
            break
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped):
            # Count non-empty recommendation lines
            text_only = stripped.lstrip("-*0123456789. ").strip()
            if text_only:
                rec_count += 1
    return rec_count

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to expected output artifacts
    export_path = os.path.join(output_dir, "learnings_export.json")
    summary_json_path = os.path.join(output_dir, "learning_summary.json")
    search_results_path = os.path.join(output_dir, "search_results.json")
    summary_txt_path = os.path.join(output_dir, "learning_summary.txt")
    playbook_md_path = os.path.join(output_dir, "learning_playbook.md")

    # Reference input for validating search coverage
    queries_path = os.path.join(input_dir, "search_queries.txt")

    # Initialize all checks to False
    checks: Dict[str, bool] = {
        # Export checks
        "export_exists": False,
        "export_valid_json": False,
        "export_keys_present": False,
        "export_learnings_min_8": False,
        "export_categories_distinct_4": False,
        "export_errors_min_4": False,
        "export_has_unresolved_error": False,
        "export_has_bugfix_learning_fixed_or_resolved": False,
        # Summary JSON checks
        "summary_json_exists": False,
        "summary_json_valid": False,
        "summary_json_keys_present": False,
        "summary_json_consistent_with_export": False,
        "summary_json_unresolved_ge_1": False,
        # Search results checks
        "search_results_exists": False,
        "search_results_valid_json": False,
        "search_results_covers_all_queries": False,
        "search_results_has_JSON_and_timeout_keys": False,
        "search_results_JSON_and_timeout_non_empty": False,
        "search_results_items_have_required_fields": False,
        # Summary text checks
        "summary_txt_exists": False,
        "summary_txt_non_empty": False,
        "summary_txt_contains_total_learnings_and_numbers": False,
        "summary_txt_contains_error_section_marker": False,
        # Playbook checks
        "playbook_exists": False,
        "playbook_non_empty": False,
        "playbook_has_two_or_more_category_sections": False,
        "playbook_has_next_steps_with_3_recommendations": False,
    }

    # Load outputs
    export_ok, export_obj = load_json_file(export_path)
    if export_ok and isinstance(export_obj, dict):
        checks["export_exists"] = True
        checks["export_valid_json"] = True

        # Validate keys
        if (
            "learnings" in export_obj
            and "errors" in export_obj
            and "exported_at" in export_obj
            and isinstance(export_obj.get("learnings"), list)
            and isinstance(export_obj.get("errors"), list)
            and isinstance(export_obj.get("exported_at"), str)
        ):
            checks["export_keys_present"] = True

            learnings = export_obj.get("learnings", [])
            errors = export_obj.get("errors", [])

            # Learnings count
            if isinstance(learnings, list) and len(learnings) >= 8:
                checks["export_learnings_min_8"] = True

            # Distinct categories >= 4
            categories = set()
            for l in learnings:
                cat = l.get("category") if isinstance(l, dict) else None
                if isinstance(cat, str) and cat.strip():
                    categories.add(cat.strip())
            if len(categories) >= 4:
                checks["export_categories_distinct_4"] = True

            # Errors count
            if isinstance(errors, list) and len(errors) >= 4:
                checks["export_errors_min_4"] = True

            # Has unresolved error
            has_unresolved = False
            for e in errors:
                if isinstance(e, dict):
                    if not truthy(e.get("resolved", False)):
                        has_unresolved = True
                        break
            if has_unresolved:
                checks["export_has_unresolved_error"] = True

            # Has bug-fix learning with content starting with "Fixed:" or "Resolved:"
            has_bugfix_prefixed = False
            for l in learnings:
                if isinstance(l, dict):
                    if l.get("category") == "bug-fix":
                        content = l.get("content")
                        if isinstance(content, str):
                            s = content.strip()
                            if s.startswith("Fixed:") or s.startswith("Resolved:"):
                                has_bugfix_prefixed = True
                                break
            if has_bugfix_prefixed:
                checks["export_has_bugfix_learning_fixed_or_resolved"] = True

    # Load summary JSON
    summary_ok, summary_obj = load_json_file(summary_json_path)
    if summary_ok and isinstance(summary_obj, dict):
        checks["summary_json_exists"] = True
        checks["summary_json_valid"] = True

        # Validate keys structure
        sj_has_keys = (
            "total_learnings" in summary_obj
            and "learnings_by_category" in summary_obj
            and "error_statistics" in summary_obj
            and isinstance(summary_obj.get("total_learnings"), int)
            and isinstance(summary_obj.get("learnings_by_category"), dict)
            and isinstance(summary_obj.get("error_statistics"), dict)
        )
        if sj_has_keys:
            checks["summary_json_keys_present"] = True

            # Consistency with export
            if checks["export_valid_json"] and checks["export_keys_present"]:
                total_learnings = summary_obj.get("total_learnings")
                error_stats = summary_obj.get("error_statistics", {})
                total_errors = error_stats.get("total_errors")
                resolved_cnt = error_stats.get("resolved")
                unresolved_cnt = error_stats.get("unresolved")

                exp_learnings_len = len(export_obj.get("learnings", [])) if isinstance(export_obj, dict) else None
                exp_errors_len = len(export_obj.get("errors", [])) if isinstance(export_obj, dict) else None

                consistent = (
                    isinstance(total_learnings, int)
                    and isinstance(total_errors, int)
                    and isinstance(resolved_cnt, int)
                    and isinstance(unresolved_cnt, int)
                    and exp_learnings_len == total_learnings
                    and exp_errors_len == total_errors
                )
                if consistent:
                    checks["summary_json_consistent_with_export"] = True

                if isinstance(unresolved_cnt, int) and unresolved_cnt >= 1:
                    checks["summary_json_unresolved_ge_1"] = True

    # Load search results
    search_ok, search_obj = load_json_file(search_results_path)
    if search_ok and isinstance(search_obj, dict):
        checks["search_results_exists"] = True
        checks["search_results_valid_json"] = True

        # Coverage of all queries
        queries = parse_queries_file(queries_path)
        covers_all = True
        for q in queries:
            if q not in search_obj:
                covers_all = False
                break
        if queries and covers_all:
            checks["search_results_covers_all_queries"] = True

        # Keys for "JSON" and "timeout"
        has_json_key = "JSON" in search_obj
        has_timeout_key = "timeout" in search_obj
        if has_json_key and has_timeout_key:
            checks["search_results_has_JSON_and_timeout_keys"] = True

            # Non-empty arrays for these queries
            json_arr = search_obj.get("JSON", [])
            timeout_arr = search_obj.get("timeout", [])
            if isinstance(json_arr, list) and len(json_arr) > 0 and isinstance(timeout_arr, list) and len(timeout_arr) > 0:
                checks["search_results_JSON_and_timeout_non_empty"] = True

        # Validate that each result item has required fields
        items_ok = True
        for key, arr in search_obj.items():
            if not isinstance(arr, list):
                items_ok = False
                break
            for itm in arr:
                if not isinstance(itm, dict):
                    items_ok = False
                    break
                if not all(k in itm for k in ("id", "category", "content")):
                    items_ok = False
                    break
            if not items_ok:
                break
        if items_ok and len(search_obj) > 0:
            checks["search_results_items_have_required_fields"] = True

    # Summary text file checks
    txt_exists, txt_content = load_text_file(summary_txt_path)
    if txt_exists:
        checks["summary_txt_exists"] = True
        if isinstance(txt_content, str) and txt_content.strip():
            checks["summary_txt_non_empty"] = True

            # Contains markers and counts consistent with summary JSON if available
            has_total_marker = "Total Learnings" in txt_content
            counts_ok = False
            error_marker_ok = ("error" in txt_content.lower())

            if checks.get("summary_json_valid"):
                tl = summary_obj.get("total_learnings")
                es = summary_obj.get("error_statistics", {})
                res = es.get("resolved")
                unres = es.get("unresolved")
                # Check numbers appear somewhere in the text
                if isinstance(tl, int) and isinstance(res, int) and isinstance(unres, int):
                    tl_present = str(tl) in txt_content
                    res_present = str(res) in txt_content
                    unres_present = str(unres) in txt_content
                    counts_ok = has_total_marker and tl_present and res_present and unres_present
            else:
                # If no summary JSON, at least ensure "Total Learnings" keyword appears (but we do not mark consistency)
                counts_ok = has_total_marker

            if counts_ok:
                checks["summary_txt_contains_total_learnings_and_numbers"] = True
            if error_marker_ok:
                checks["summary_txt_contains_error_section_marker"] = True

    # Playbook checks
    pb_exists, pb_content = load_text_file(playbook_md_path)
    if pb_exists:
        checks["playbook_exists"] = True
        if isinstance(pb_content, str) and pb_content.strip():
            checks["playbook_non_empty"] = True
            if count_category_headings(pb_content) >= 2:
                checks["playbook_has_two_or_more_category_sections"] = True
            if find_next_steps_recommendations(pb_content) >= 3:
                checks["playbook_has_next_steps_with_3_recommendations"] = True

    # Compute reward as average of passed checks (all are output-dependent)
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure baseline no-op yields 0.0 (if output dir missing or all key files missing, no checks pass → reward stays 0.0)
    result = {"reward": reward}
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()