import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
        if txt.startswith("\ufeff"):
            txt = txt.lstrip("\ufeff")
        return txt
    except Exception:
        return None

def last_non_empty_line(lines):
    for line in reversed(lines):
        if line.strip():
            return line
    return ""

def is_iso_like(dt: str) -> bool:
    # Accept YYYY-MM-DD or full ISO-8601-like with time and optional Z or offset
    pattern = r"^\d{4}-\d{2}-\d{2}([Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"
    return re.match(pattern, dt) is not None

def find_heading_lines(text):
    lines = text.splitlines()
    return [i for i, line in enumerate(lines) if re.match(r"^\s*#{1,6}\s", line)]

def count_checklist_lines(text):
    return sum(1 for line in text.splitlines() if line.startswith("- [ ] "))

def get_files_to_change_paths(text):
    lines = text.splitlines()
    # Find heading containing exact phrase "Files to change"
    heading_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*#{1,6}\s.*Files to change.*$", line):
            heading_idx = i
            break
    if heading_idx is None:
        return [], False
    # Collect lines after heading until next heading or end
    collected = []
    for j in range(heading_idx + 1, len(lines)):
        if re.match(r"^\s*#{1,6}\s", lines[j]):
            break
        collected.append(lines[j].strip())
    # Filter plausible relative paths:
    # - non-empty
    # - not starting with '/'
    # - not Windows drive absolute (C:\ or C:/)
    # - contains at least one slash or backslash
    # - not a URL (no ://)
    paths = []
    for ln in collected:
        if not ln or "://" in ln:
            continue
        if ln.startswith("/"):
            continue
        if re.match(r"^[A-Za-z]:[/\\]", ln):
            continue
        if "/" in ln or "\\" in ln:
            paths.append(ln)
    return paths, True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    change_dir = os.path.join(output_dir, "lightspec", "changes", "team-calendar-digest")
    spec_path = os.path.join(change_dir, "spec.md")
    change_json_path = os.path.join(change_dir, "change.json")
    ac_json_path = os.path.join(change_dir, "acceptance_criteria.json")
    validate_report_path = os.path.join(change_dir, "validate-report.txt")
    apply_plan_path = os.path.join(change_dir, "apply-plan.md")

    required_sections = [
        "Context",
        "Problem",
        "Goals",
        "Non-Goals",
        "Requirements",
        "Acceptance Criteria",
        "Dependencies",
        "Risks",
        "Rollout",
        "Rollback",
        "Metrics",
        "Open Questions",
    ]

    checks = {
        # Existence
        "dir_exists": False,
        "spec_exists": False,
        "change_json_exists": False,
        "ac_json_exists": False,
        "validate_report_exists": False,
        "apply_plan_exists": False,
        # spec.md content
        "spec_title_correct": False,
        "spec_has_all_sections": False,
        "spec_source_line_present": False,
        # change.json content
        "change_json_valid": False,
        "change_json_fields_valid": False,
        "change_json_created_iso": False,
        # acceptance_criteria.json content
        "ac_json_valid": False,
        "ac_json_min_items": False,
        "ac_json_has_bdd_item": False,
        # validate-report.txt content
        "validate_report_has_lines": False,
        "validate_report_missing_none_when_complete": False,
        # apply-plan.md content
        "apply_plan_has_checklist_items": False,
        "apply_plan_has_files_to_change_section_with_paths": False,
        "apply_plan_has_confirmation_sentence": False,
    }

    # Existence checks
    if os.path.isdir(change_dir):
        checks["dir_exists"] = True
    if os.path.isfile(spec_path):
        checks["spec_exists"] = True
    if os.path.isfile(change_json_path):
        checks["change_json_exists"] = True
    if os.path.isfile(ac_json_path):
        checks["ac_json_exists"] = True
    if os.path.isfile(validate_report_path):
        checks["validate_report_exists"] = True
    if os.path.isfile(apply_plan_path):
        checks["apply_plan_exists"] = True

    # spec.md validations
    spec_text = None
    if checks["spec_exists"]:
        spec_text = read_text(spec_path)
        if spec_text is not None:
            lines = spec_text.splitlines()
            if lines:
                first = lines[0].strip()
                if first == "# Team Calendar Digest":
                    checks["spec_title_correct"] = True
            # Headings presence: exact level-2 "## Heading"
            has_all = True
            for sec in required_sections:
                pattern = r"(?m)^## " + re.escape(sec) + r"\s*$"
                if not re.search(pattern, spec_text):
                    has_all = False
                    break
            checks["spec_has_all_sections"] = has_all
            # Source line with path fragment
            source_present = False
            for ln in lines:
                if "Source:" in ln and "input/product_brief.md" in ln:
                    source_present = True
                    break
            checks["spec_source_line_present"] = source_present

    # change.json validations
    change_data = None
    if checks["change_json_exists"]:
        raw = read_text(change_json_path)
        if raw is not None:
            try:
                change_data = json.loads(raw)
                checks["change_json_valid"] = True
            except Exception:
                change_data = None
        if change_data is not None and isinstance(change_data, dict):
            fields_ok = (
                change_data.get("name") == "Team Calendar Digest"
                and change_data.get("slug") == "team-calendar-digest"
                and change_data.get("status") == "draft"
            )
            checks["change_json_fields_valid"] = fields_ok
            created_val = change_data.get("created")
            if isinstance(created_val, str) and is_iso_like(created_val.strip()):
                checks["change_json_created_iso"] = True

    # acceptance_criteria.json validations
    ac_data = None
    if checks["ac_json_exists"]:
        raw = read_text(ac_json_path)
        if raw is not None:
            try:
                ac_data = json.loads(raw)
                if isinstance(ac_data, list):
                    checks["ac_json_valid"] = True
                    if len(ac_data) >= 5:
                        checks["ac_json_min_items"] = True
                    # BDD item check
                    has_bdd = False
                    for item in ac_data:
                        if isinstance(item, str):
                            lower = item.lower()
                            if ("given" in lower) and ("when" in lower) and ("then" in lower):
                                has_bdd = True
                                break
                    checks["ac_json_has_bdd_item"] = has_bdd
            except Exception:
                pass

    # validate-report.txt validations
    validate_text = None
    sections_line_ok = False
    missing_line_value = None
    if checks["validate_report_exists"]:
        validate_text = read_text(validate_report_path)
        if validate_text is not None:
            lines = [ln.rstrip("\n") for ln in validate_text.splitlines()]
            # Find "Sections: <int>"
            for ln in lines:
                m = re.match(r"^Sections:\s+(\d+)\s*$", ln)
                if m:
                    sections_line_ok = True
                    break
            # Find "Missing: ..."
            for ln in lines:
                m2 = re.match(r"^Missing:\s+(.*)\s*$", ln)
                if m2:
                    missing_line_value = "Missing: " + m2.group(1).strip()
                    break
            if sections_line_ok and missing_line_value is not None:
                checks["validate_report_has_lines"] = True
            # If all required sections are present in spec.md, Missing must be exactly "Missing: none"
            if checks["spec_has_all_sections"] and missing_line_value is not None:
                if missing_line_value.strip() == "Missing: none":
                    checks["validate_report_missing_none_when_complete"] = True

    # apply-plan.md validations
    apply_text = None
    if checks["apply_plan_exists"]:
        apply_text = read_text(apply_plan_path)
        if apply_text is not None:
            # Checklist items
            if count_checklist_lines(apply_text) >= 5:
                checks["apply_plan_has_checklist_items"] = True
            # Files to change section and paths
            paths, heading_found = get_files_to_change_paths(apply_text)
            if heading_found and len(paths) >= 3:
                checks["apply_plan_has_files_to_change_section_with_paths"] = True
            # Confirmation sentence
            if "Do not apply without user confirmation." in apply_text:
                checks["apply_plan_has_confirmation_sentence"] = True

    # Compute reward as proportion of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = passed / total if passed > 0 else 0.0

    # Ensure last non-empty stdout line is JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()