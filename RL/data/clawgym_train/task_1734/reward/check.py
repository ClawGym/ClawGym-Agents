import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def extract_mapping(skill_md_path):
    content = read_text_file(skill_md_path) or ""
    old_name = None
    new_name = None

    # Try to parse front matter "name: <value>"
    # Look within first 2000 chars to limit scan
    head = content[:2000]
    # Capture YAML front-matter block if present
    # Then look for "name:" line
    name_match = re.search(r"(?m)^\s*name\s*:\s*([A-Za-z0-9._\-]+)\s*$", head)
    if name_match:
        old_name = name_match.group(1).strip()

    # Try multiple patterns to find new name
    # 1) "Renamed to <name>"
    m = re.search(r"Renamed to\s+([A-Za-z0-9._\-]+)", content)
    if m:
        new_name = m.group(1).strip()
    # 2) Header pattern "# <old> is now <new>"
    if new_name is None:
        m = re.search(r"is now\s+([A-Za-z0-9._\-]+)", content)
        if m:
            new_name = m.group(1).strip()
    # 3) Command pattern "npx clawhub install <name>"
    if new_name is None:
        m = re.search(r"npx\s+clawhub\s+install\s+([A-Za-z0-9._\-]+)", content)
        if m:
            new_name = m.group(1).strip()

    return old_name, new_name

def scan_input_for_occurrences(input_dir, deprecated_name):
    allowed_exts = {".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".yml", ".xml", ".html", ".py"}
    per_file_counts = {}
    total = 0
    for root, dirs, files in os.walk(input_dir):
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext.lower() not in allowed_exts:
                continue
            fpath = os.path.join(root, fname)
            content = read_text_file(fpath)
            if content is None:
                continue
            count = content.count(deprecated_name)
            if count > 0:
                # Store path relative to input dir with "input/" prefix
                rel = os.path.relpath(fpath, input_dir)
                key_path = os.path.join("input", rel).replace(os.sep, "/")
                per_file_counts[key_path] = count
                total += count
    return per_file_counts, total

def validate_json_plan(json_path, old_name, new_name, expected_counts, expected_total):
    checks = {
        "json_exists": False,
        "json_valid": False,
        "json_old_name": False,
        "json_new_name": False,
        "json_total_match": False,
        "json_per_file_complete": False,
    }
    data = None

    if os.path.isfile(json_path):
        checks["json_exists"] = True
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["json_valid"] = isinstance(data, dict)
        except Exception:
            checks["json_valid"] = False

    if not checks["json_valid"] or not isinstance(data, dict):
        return checks

    # Validate fields
    if data.get("old_name") == old_name:
        checks["json_old_name"] = True
    if data.get("new_name") == new_name:
        checks["json_new_name"] = True
    if isinstance(data.get("total_occurrences"), int) and data.get("total_occurrences") == expected_total:
        checks["json_total_match"] = True

    per_file = data.get("per_file")
    per_file_ok = True
    if not isinstance(per_file, list):
        per_file_ok = False
    else:
        # Build map from json per_file
        json_map = {}
        for item in per_file:
            if not isinstance(item, dict):
                per_file_ok = False
                break
            path = item.get("path")
            occ = item.get("occurrences")
            if not isinstance(path, str) or not isinstance(occ, int):
                per_file_ok = False
                break
            json_map[path] = occ

        if per_file_ok:
            # Ensure all expected files are present with exact counts
            for exp_path, exp_count in expected_counts.items():
                if json_map.get(exp_path) != exp_count:
                    per_file_ok = False
                    break
            # Ensure no mismatch in total across expected set
            # (total check already enforces overall equality)
    checks["json_per_file_complete"] = per_file_ok

    return checks

def validate_preview_md(md_path, old_name, new_name, affected_files):
    checks = {
        "md_exists": False,
        "md_mapping_line": False,
        "md_files_listed": False,
        "md_examples_per_file": False,
    }
    if not os.path.isfile(md_path):
        return checks
    checks["md_exists"] = True

    content = read_text_file(md_path) or ""
    lines = content.splitlines()

    # Mapping line presence (exact substring "old -> new")
    if f"{old_name} -> {new_name}" in content:
        checks["md_mapping_line"] = True

    # Each affected file path mentioned at least once
    files_listed_ok = True
    for p in affected_files:
        if p not in content:
            files_listed_ok = False
            break
    checks["md_files_listed"] = files_listed_ok

    # For each affected file, at least one example replacement line showing old and new string
    # Heuristic: a line that contains both old and new and either includes the file path on the same line
    # or within the next/previous line.
    def has_example_for_file(path_str):
        for i, line in enumerate(lines):
            if path_str in line and (old_name in line and new_name in line):
                return True
            if path_str in line:
                # Check next two lines for example
                for j in range(1, 3):
                    if i + j < len(lines):
                        ln = lines[i + j]
                        if old_name in ln and new_name in ln:
                            return True
                # Check previous two lines for example
                for j in range(1, 3):
                    if i - j >= 0:
                        ln = lines[i - j]
                        if old_name in ln and new_name in ln:
                            return True
        return False

    examples_ok = True
    for p in affected_files:
        if not has_example_for_file(p):
            examples_ok = False
            break
    checks["md_examples_per_file"] = examples_ok

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Prepare paths
    skill_md = os.path.join(input_dir, "SKILL.md")
    json_plan_path = os.path.join(output_dir, "migration_plan.json")
    preview_md_path = os.path.join(output_dir, "preview_changes.md")

    # Extract mapping from SKILL.md
    old_name, new_name = extract_mapping(skill_md)
    # Fallbacks (should not be needed if SKILL.md conforms)
    if not old_name:
        # Try to infer from header pattern "# <old> is now ..."
        content = read_text_file(skill_md) or ""
        mh = re.search(r"#\s+([A-Za-z0-9._\-]+)\s+is now\s+[A-Za-z0-9._\-]+", content)
        if mh:
            old_name = mh.group(1)
    if not old_name:
        old_name = "pm-sim"
    if not new_name:
        # Try common target from notice
        if "polymarket-paper-trader" in (read_text_file(skill_md) or ""):
            new_name = "polymarket-paper-trader"
        else:
            new_name = "polymarket-paper-trader"

    # Scan input for occurrences (case-sensitive exact match)
    per_file_counts, total_occ = scan_input_for_occurrences(input_dir, old_name)
    affected_files = sorted(per_file_counts.keys())

    # Validate outputs
    json_checks = validate_json_plan(json_plan_path, old_name, new_name, per_file_counts, total_occ)
    md_checks = validate_preview_md(preview_md_path, old_name, new_name, affected_files)

    # Aggregate checks
    checks = {}
    checks.update(json_checks)
    checks.update(md_checks)

    # Compute reward using only output-dependent checks
    scoring_keys = [
        "json_exists",
        "json_valid",
        "json_old_name",
        "json_new_name",
        "json_total_match",
        "json_per_file_complete",
        "md_exists",
        "md_mapping_line",
        "md_files_listed",
        "md_examples_per_file",
    ]
    passed = [checks.get(k, False) for k in scoring_keys]
    # No-op baseline: if required outputs missing or invalid, reward should be 0.0 naturally
    reward = sum(1.0 for v in passed if v) / float(len(scoring_keys)) if scoring_keys else 0.0

    result = {"reward": reward}
    # Ensure all fields are booleans in output results
    for k in scoring_keys:
        result[k] = bool(checks.get(k, False))

    # Print single JSON line
    print(json.dumps(result))

if __name__ == "__main__":
    main()