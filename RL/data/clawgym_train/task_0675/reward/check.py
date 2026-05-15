import json
import os
import re
import sys
from typing import Any, Dict, List

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def file_exists(path: str) -> bool:
    try:
        return os.path.isfile(path)
    except Exception:
        return False

def is_nonneg_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0

def validate_import_log(obj: Any) -> Dict[str, bool]:
    checks = {
        "import_log_has_required_fields": False,
        "import_log_counts_consistent": False,
        "import_log_details_valid": False,
    }
    if not isinstance(obj, dict):
        return checks

    required_keys = {"total_rows", "added", "skipped_duplicates", "errors", "details"}
    if not required_keys.issubset(set(obj.keys())):
        return checks

    total_rows = obj.get("total_rows")
    added = obj.get("added")
    skipped = obj.get("skipped_duplicates")
    errors = obj.get("errors")
    details = obj.get("details")

    # Types and non-negativity
    if not (is_nonneg_int(total_rows) and is_nonneg_int(added) and is_nonneg_int(skipped) and is_nonneg_int(errors)):
        return checks
    if not isinstance(details, list):
        return checks

    checks["import_log_has_required_fields"] = True

    # Sum consistency
    if added + skipped + errors == total_rows:
        checks["import_log_counts_consistent"] = True

    # Details validation
    allowed_status = {"added", "duplicate", "error"}
    details_ok = True
    for item in details:
        if not isinstance(item, dict):
            details_ok = False
            break
        if "email" not in item or "status" not in item:
            details_ok = False
            break
        if not isinstance(item["email"], str):
            details_ok = False
            break
        if item["status"] not in allowed_status:
            details_ok = False
            break

    if details_ok and len(details) == total_rows:
        checks["import_log_details_valid"] = True

    return checks

def validate_actions(content: str) -> Dict[str, bool]:
    checks = {
        "actions_contains_add": False,
        "actions_contains_score": False,
        "actions_contains_follow_up": False,
        "actions_contains_convert": False,
        "actions_contains_pipeline": False,
    }
    if content is None:
        return checks

    # Case-insensitive searches with token boundaries where sensible
    patterns = {
        "actions_contains_add": r"(^|[^a-zA-Z])add([^a-zA-Z]|$)",
        "actions_contains_score": r"(^|[^a-zA-Z])score([^a-zA-Z]|$)",
        "actions_contains_follow_up": r"(^|[^a-zA-Z])follow-up([^a-zA-Z]|$)",
        "actions_contains_convert": r"(^|[^a-zA-Z])convert([^a-zA-Z]|$)",
        "actions_contains_pipeline": r"(^|[^a-zA-Z])pipeline([^a-zA-Z]|$)",
    }
    for key, pat in patterns.items():
        if re.search(pat, content, flags=re.IGNORECASE | re.MULTILINE):
            checks[key] = True
    return checks

def validate_pipeline(content: str) -> Dict[str, bool]:
    checks = {
        "pipeline_header_line_valid_date": False,
        "pipeline_contains_total_leads": False,
        "pipeline_contains_status_keyword": False,
    }
    if content is None:
        return checks

    lines = content.splitlines()

    # Header: look for "Pipeline Report — YYYY-MM" anywhere in a line
    header_ok = any(re.search(r"Pipeline Report — \d{4}-\d{2}", line) for line in lines)
    if header_ok:
        checks["pipeline_header_line_valid_date"] = True

    # Total leads line
    if any("Total leads:" in line for line in lines):
        checks["pipeline_contains_total_leads"] = True

    # Status keywords
    status_regex = re.compile(r"\b(new|contacted|qualified|converted|lost)\b", flags=re.IGNORECASE)
    if status_regex.search(content) is not None:
        checks["pipeline_contains_status_keyword"] = True

    return checks

def validate_docs_links(readme_text: str, pr_text: str) -> Dict[str, bool]:
    checks = {
        "readme_links_pipeline_report_correct": False,
        "pipeline_report_links_pipeline_txt_correct": False,
    }
    if isinstance(readme_text, str):
        # Markdown link to ./pipeline_report.md
        if re.search(r"\[.+?\]\(\./pipeline_report\.md\)", readme_text):
            checks["readme_links_pipeline_report_correct"] = True
    if isinstance(pr_text, str):
        # Markdown link to ../pipeline.txt
        if re.search(r"\[.+?\]\(\.\./pipeline\.txt\)", pr_text):
            checks["pipeline_report_links_pipeline_txt_correct"] = True
    return checks

def validate_lint_report(obj: Any) -> Dict[str, bool]:
    checks = {
        "lint_report_valid_json": False,
        "lint_report_zero_broken": False,
    }
    if not isinstance(obj, dict):
        return checks
    if not {"totalFiles", "brokenLinksCount", "details"}.issubset(set(obj.keys())):
        return checks
    if not (isinstance(obj["totalFiles"], int) and isinstance(obj["brokenLinksCount"], int) and isinstance(obj["details"], list)):
        return checks
    checks["lint_report_valid_json"] = True
    if obj["brokenLinksCount"] == 0:
        checks["lint_report_zero_broken"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # 1) import_log.json checks
    import_log_path = os.path.join(output_dir, "import_log.json")
    checks["has_import_log_file"] = file_exists(import_log_path)
    checks["import_log_valid_json"] = False
    checks["import_log_has_required_fields"] = False
    checks["import_log_counts_consistent"] = False
    checks["import_log_details_valid"] = False
    import_log_obj = None
    if checks["has_import_log_file"]:
        import_log_obj = load_json(import_log_path)
        if isinstance(import_log_obj, dict):
            checks["import_log_valid_json"] = True
            imp_checks = validate_import_log(import_log_obj)
            checks.update(imp_checks)

    # 2) actions.md checks
    actions_path = os.path.join(output_dir, "actions.md")
    checks["has_actions_md"] = file_exists(actions_path)
    checks["actions_contains_add"] = False
    checks["actions_contains_score"] = False
    checks["actions_contains_follow_up"] = False
    checks["actions_contains_convert"] = False
    checks["actions_contains_pipeline"] = False
    if checks["has_actions_md"]:
        actions_content = read_text(actions_path) or ""
        actions_checks = validate_actions(actions_content)
        checks.update(actions_checks)

    # 3) pipeline.txt checks
    pipeline_path = os.path.join(output_dir, "pipeline.txt")
    checks["has_pipeline_txt"] = file_exists(pipeline_path)
    checks["pipeline_header_line_valid_date"] = False
    checks["pipeline_contains_total_leads"] = False
    checks["pipeline_contains_status_keyword"] = False
    if checks["has_pipeline_txt"]:
        pipeline_content = read_text(pipeline_path) or ""
        pipeline_checks = validate_pipeline(pipeline_content)
        checks.update(pipeline_checks)

    # 4) docs existence and links
    readme_path = os.path.join(output_dir, "docs", "README.md")
    pr_path = os.path.join(output_dir, "docs", "pipeline_report.md")
    checks["has_docs_readme"] = file_exists(readme_path)
    checks["has_docs_pipeline_report"] = file_exists(pr_path)
    checks["readme_links_pipeline_report_correct"] = False
    checks["pipeline_report_links_pipeline_txt_correct"] = False
    readme_text = read_text(readme_path) if checks["has_docs_readme"] else None
    pr_text = read_text(pr_path) if checks["has_docs_pipeline_report"] else None
    link_checks = validate_docs_links(readme_text, pr_text)
    checks.update(link_checks)

    # 5) lint_report.json checks
    lint_path = os.path.join(output_dir, "lint_report.json")
    checks["has_lint_report"] = file_exists(lint_path)
    checks["lint_report_valid_json"] = False
    checks["lint_report_zero_broken"] = False
    if checks["has_lint_report"]:
        lint_obj = load_json(lint_path)
        lint_checks = validate_lint_report(lint_obj)
        checks.update(lint_checks)

    # Determine reward: strict pass only if all checks are True
    all_checks = list(checks.values())
    reward = 1.0 if all(all_checks) and len(all_checks) > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()