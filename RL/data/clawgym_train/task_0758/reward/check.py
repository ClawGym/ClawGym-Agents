import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def extract_section(text: str, start_header: str, other_headers: List[str]) -> str:
    # Case-insensitive section extraction: content from start_header to next header or end
    lower = text.lower()
    start_idx = lower.find(start_header.lower())
    if start_idx == -1:
        return ""
    # Find end index: next occurrence of any other header after start
    end_idx_candidates = []
    for h in other_headers:
        pos = lower.find(h.lower(), start_idx + 1)
        if pos != -1:
            end_idx_candidates.append(pos)
    end_idx = min(end_idx_candidates) if end_idx_candidates else len(text)
    return text[start_idx:end_idx]

def is_iso8601(dt: str) -> bool:
    # Accept YYYY-MM-DDTHH:MM:SS with optional 'Z' or timezone offset
    # Also accept fractional seconds optionally
    # Patterns:
    # 2026-03-10T12:34:56
    # 2026-03-10T12:34:56Z
    # 2026-03-10T12:34:56+00:00
    # 2026-03-10T12:34:56.123
    # 2026-03-10T12:34:56.123Z
    # 2026-03-10T12:34:56.123+00:00
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
    return bool(re.match(pattern, dt))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # processor.py checks
        "processor_py_exists": False,
        "processor_py_has_functions": False,
        # directory_report.json checks
        "directory_report_exists": False,
        "directory_report_parseable": False,
        "directory_report_keys_present": False,
        "directory_report_services_by_category_valid": False,
        # marketing_plan.md checks
        "marketing_plan_exists": False,
        "marketing_plan_has_sections": False,
        "marketing_plan_sequence_has_nine_steps": False,
        # book_status.json checks
        "book_status_exists": False,
        "book_status_parseable_array": False,
        "book_status_items_valid": False,
        "book_status_availability_consistent": False,
        "book_status_last_checked_iso8601": False,
        # completion_report.md checks
        "completion_report_exists": False,
        "completion_report_has_sections": False,
        "completion_report_files_listed": False,
    }

    # 1) output/processor.py
    processor_path = os.path.join(output_dir, "processor.py")
    if os.path.isfile(processor_path) and processor_path.endswith(".py"):
        checks["processor_py_exists"] = True
        text = read_text(processor_path) or ""
        needed_funcs = ["def process_services", "def generate_marketing_plan", "def evaluate_books"]
        if all(s in text for s in needed_funcs):
            checks["processor_py_has_functions"] = True

    # 2) output/directory_report.json
    dir_report_path = os.path.join(output_dir, "directory_report.json")
    dir_report = None
    if os.path.isfile(dir_report_path):
        checks["directory_report_exists"] = True
        dir_report = read_json(dir_report_path)
        if isinstance(dir_report, dict):
            checks["directory_report_parseable"] = True
            has_keys = all(k in dir_report for k in ["total_services", "categories", "services_by_category", "notes"])
            if has_keys and isinstance(dir_report.get("total_services"), int) and isinstance(dir_report.get("categories"), list) and isinstance(dir_report.get("services_by_category"), dict) and isinstance(dir_report.get("notes"), str):
                checks["directory_report_keys_present"] = True
                categories = dir_report.get("categories", [])
                services_by_category = dir_report.get("services_by_category", {})
                # keys subset of categories
                sbc_keys = set(services_by_category.keys())
                if sbc_keys.issubset(set(categories)):
                    # every category listed has an array in services_by_category
                    per_cat_arrays = all(isinstance(services_by_category.get(cat, []), list) for cat in categories)
                    if per_cat_arrays:
                        checks["directory_report_services_by_category_valid"] = True

    # 3) output/marketing_plan.md
    mk_plan_path = os.path.join(output_dir, "marketing_plan.md")
    mk_text = None
    if os.path.isfile(mk_plan_path):
        checks["marketing_plan_exists"] = True
        mk_text = read_text(mk_plan_path) or ""
        lt = mk_text.lower()
        required_headers = ["bottom line", "sequence", "owners & deadlines", "risks & mitigations", "next steps"]
        if all(h in lt for h in required_headers):
            checks["marketing_plan_has_sections"] = True
            # Extract Sequence section
            seq_section = extract_section(
                mk_text,
                "Sequence",
                ["Owners & Deadlines", "Risks & Mitigations", "Next Steps", "Bottom Line"]
            ).lower()

            # Check for nine conceptual steps (order-insensitive presence)
            concepts_present = []
            def has_all(subs: List[str]) -> bool:
                return all(s in seq_section for s in subs)

            steps = [
                lambda: ("context" in seq_section or "foundation" in seq_section),
                lambda: (("launch" in seq_section) and ("strategy" in seq_section or "plan" in seq_section)),
                lambda: (("content" in seq_section) and ("plan" in seq_section or "calendar" in seq_section)),
                lambda: ("page copy" in seq_section or ("copy" in seq_section and "page" in seq_section) or "landing page" in seq_section),
                lambda: ("email" in seq_section and "sequence" in seq_section),
                lambda: ("social" in seq_section and ("content" in seq_section or "posts" in seq_section)),
                lambda: (("paid" in seq_section or "ads" in seq_section) and ("creative" in seq_section or "ad creative" in seq_section)),
                lambda: ("tracking" in seq_section or "analytics" in seq_section or "setup" in seq_section),
                lambda: ("analysis" in seq_section or "measure results" in seq_section or "performance" in seq_section),
            ]
            concepts_present = [fn() for fn in steps]
            if all(concepts_present) and len(steps) == 9:
                checks["marketing_plan_sequence_has_nine_steps"] = True

    # 4) output/book_status.json
    book_status_path = os.path.join(output_dir, "book_status.json")
    holdings_path = os.path.join(input_dir, "holdings.json")
    holdings = read_json(holdings_path) if os.path.isfile(holdings_path) else {}
    if os.path.isfile(book_status_path):
        checks["book_status_exists"] = True
        book_status = read_json(book_status_path)
        if isinstance(book_status, list):
            checks["book_status_parseable_array"] = True
            all_items_have_keys_types = True
            all_availability_consistent = True
            all_last_checked_iso = True
            for item in book_status:
                # Validate keys and types
                required_keys = ["title", "author", "isbn", "available", "locations", "last_checked", "monitor"]
                if not (isinstance(item, dict) and all(k in item for k in required_keys)):
                    all_items_have_keys_types = False
                    break
                if not (isinstance(item["title"], str) and isinstance(item["author"], str) and isinstance(item["isbn"], str) and isinstance(item["available"], bool) and isinstance(item["locations"], list) and isinstance(item["last_checked"], str) and isinstance(item["monitor"], bool)):
                    all_items_have_keys_types = False
                    break
                # Availability consistency with holdings
                isbn = item["isbn"]
                locations_from_holdings = []
                if isinstance(holdings, dict) and isbn in holdings and isinstance(holdings[isbn], list):
                    locations_from_holdings = holdings[isbn]
                if locations_from_holdings:
                    if not (item["available"] is True and isinstance(item["locations"], list) and len(item["locations"]) > 0):
                        all_availability_consistent = False
                        break
                else:
                    if not (item["available"] is False and isinstance(item["locations"], list) and len(item["locations"]) == 0):
                        all_availability_consistent = False
                        break
                # last_checked ISO 8601
                if not is_iso8601(item["last_checked"]):
                    all_last_checked_iso = False
                    break
            if all_items_have_keys_types:
                checks["book_status_items_valid"] = True
            if all_availability_consistent:
                checks["book_status_availability_consistent"] = True
            if all_last_checked_iso:
                checks["book_status_last_checked_iso8601"] = True

    # 5) output/completion_report.md
    comp_report_path = os.path.join(output_dir, "completion_report.md")
    comp_text = None
    if os.path.isfile(comp_report_path):
        checks["completion_report_exists"] = True
        comp_text = read_text(comp_report_path) or ""
        lt = comp_text.lower()
        required_sections = ["files created", "decisions & assumptions", "verification", "conventions matched"]
        if all(s in lt for s in required_sections):
            checks["completion_report_has_sections"] = True
            files_section = extract_section(
                comp_text,
                "Files Created",
                ["Decisions & Assumptions", "Verification", "Conventions Matched"]
            )
            # Must list four deliverables by exact relative paths
            required_paths = [
                "output/processor.py",
                "output/directory_report.json",
                "output/marketing_plan.md",
                "output/book_status.json",
            ]
            if all(p in files_section for p in required_paths):
                checks["completion_report_files_listed"] = True

    # Compute reward as fraction of checks passed (no-op baseline yields 0.0)
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if passed_checks > 0 else 0.0
    # Ensure 0 <= reward <= 1
    reward = max(0.0, min(1.0, reward))

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()