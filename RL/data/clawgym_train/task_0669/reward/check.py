import json
import os
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def count_fenced_code_blocks(text):
    # Count fenced code blocks using ``` start/end fences
    if text is None:
        return 0
    count = 0
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            if not in_block:
                count += 1
                in_block = True
            else:
                in_block = False
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        "report_exists": False,
        "report_json_valid": False,
        "report_is_array": False,
        "report_len_ge_6": False,
        "report_items_have_required_fields": False,
        "report_categories_valid": False,
        "report_includes_all_categories": False,
        "report_severities_valid": False,
        "report_at_least_three_high": False,

        "patch_exists": False,
        "patch_has_3_fenced_code_blocks": False,
        "patch_mentions_atomic_fix": False,
        "patch_mentions_copy_from_user_and_bytes_not_copied": False,
        "patch_mentions_goto_err": False,
        "patch_mentions_memory_ordering": False,

        "checklist_exists": False,
        "checklist_has_all_category_names": False,
        "checklist_has_min_8_checkbox_items": False,
        "checklist_mentions_vmalloc": False,
        "checklist_mentions_mutex_trylock": False,
        "checklist_mentions_read_or_write_once": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "report.json")
    patch_path = os.path.join(output_dir, "patch_suggestions.md")
    checklist_path = os.path.join(output_dir, "checklist.txt")

    # Allowed categories and severities
    allowed_categories = {
        "Atomic Context",
        "Allocation Failures",
        "User Pointer Handling",
        "Memory Ordering",
        "Module Error Paths",
        "Locking Mistakes",
    }
    allowed_severities = {"high", "medium", "low"}

    # Validate report.json
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_data = parse_json_file(report_path)
        if isinstance(report_data, list):
            checks["report_json_valid"] = True
            checks["report_is_array"] = True
            if len(report_data) >= 6:
                checks["report_len_ge_6"] = True

            # Validate items
            required_fields = [
                "id",
                "category",
                "severity",
                "description",
                "impact",
                "code_reference",
                "recommended_fix",
            ]
            items_ok = True
            categories_ok = True
            severities_ok = True
            category_coverage = set()
            high_count = 0

            for item in report_data:
                if not isinstance(item, dict):
                    items_ok = False
                    break
                # required fields presence and string type
                for k in required_fields:
                    if k not in item or not isinstance(item[k], str):
                        items_ok = False
                        break
                if not items_ok:
                    break

                # category validation
                cat = item.get("category")
                if cat not in allowed_categories:
                    categories_ok = False
                else:
                    category_coverage.add(cat)

                # severity validation
                sev = item.get("severity")
                if sev not in allowed_severities:
                    severities_ok = False
                if sev == "high":
                    high_count += 1

            if items_ok:
                checks["report_items_have_required_fields"] = True
            if categories_ok:
                checks["report_categories_valid"] = True
            if severities_ok:
                checks["report_severities_valid"] = True
            if category_coverage == allowed_categories:
                checks["report_includes_all_categories"] = True
            if high_count >= 3:
                checks["report_at_least_three_high"] = True

    # Validate patch_suggestions.md
    if os.path.isfile(patch_path):
        checks["patch_exists"] = True
        patch_text = read_text_file(patch_path)

        # at least 3 fenced code blocks
        if count_fenced_code_blocks(patch_text) >= 3:
            checks["patch_has_3_fenced_code_blocks"] = True

        # mentions atomic fix: any of these substrings
        atomic_fix_substrings = ["spin_lock_irqsave", "GFP_ATOMIC", "move allocation outside lock"]
        if patch_text is not None and any(s in patch_text for s in atomic_fix_substrings):
            checks["patch_mentions_atomic_fix"] = True

        # mentions copy_from_user and bytes not copied / returns bytes not copied
        if patch_text is not None and ("copy_from_user" in patch_text) and (("bytes not copied" in patch_text) or ("returns bytes not copied" in patch_text)):
            checks["patch_mentions_copy_from_user_and_bytes_not_copied"] = True

        # mentions goto err_
        if patch_text is not None and "goto err_" in patch_text:
            checks["patch_mentions_goto_err"] = True

        # memory ordering mentions
        memory_order_substrings = ["READ_ONCE", "WRITE_ONCE", "smp_wmb"]
        if patch_text is not None and any(s in patch_text for s in memory_order_substrings):
            checks["patch_mentions_memory_ordering"] = True

    # Validate checklist.txt
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        checklist_text = read_text_file(checklist_path) or ""
        # category names present
        if all(cat in checklist_text for cat in allowed_categories):
            checks["checklist_has_all_category_names"] = True
        # at least 8 lines starting with "- [ ] "
        checkbox_lines = [ln for ln in checklist_text.splitlines() if ln.startswith("- [ ] ")]
        if len(checkbox_lines) >= 8:
            checks["checklist_has_min_8_checkbox_items"] = True
        # required substrings
        if "vmalloc" in checklist_text:
            checks["checklist_mentions_vmalloc"] = True
        if "mutex_trylock" in checklist_text:
            checks["checklist_mentions_mutex_trylock"] = True
        if ("READ_ONCE" in checklist_text) or ("WRITE_ONCE" in checklist_text):
            checks["checklist_mentions_read_or_write_once"] = True

    # Compute reward: fraction of passed checks; baseline 0 if no outputs or missing artifacts
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed_checks > 0:
        reward = passed_checks / total_checks

    # Print single JSON object with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()