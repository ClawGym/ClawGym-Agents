import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_scalar(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool)) or x is None

def contains_nested_object(value: Any, depth: int = 0) -> bool:
    # We consider any dict that is not the root dict (depth >= 1) as a nested object.
    # Also any dict found anywhere inside arrays counts as nested.
    if isinstance(value, dict):
        if depth >= 1:
            return True
        # For root dict (depth 0), we need to inspect children (depth 1)
        for v in value.values():
            if contains_nested_object(v, depth + 1):
                return True
        return False
    elif isinstance(value, list):
        for item in value:
            if contains_nested_object(item, depth + 1):
                return True
        return False
    else:
        # scalars don't contain nested objects
        return False

def compute_structure(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        top_keys = sorted(list(obj.keys()))
        nested = contains_nested_object(obj, depth=0)
    else:
        # If the root is not an object, there are no top-level keys.
        top_keys = []
        nested = contains_nested_object(obj, depth=0)
    schema_sig = ",".join(top_keys)
    return {
        "top_level_keys": top_keys,
        "key_count": len(top_keys),
        "has_nested_objects": nested,
        "schema_signature": schema_sig,
    }

def get_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            idx = i
            break
    if idx is None:
        return ""
    # Find next heading
    end = len(lines)
    for j in range(idx + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    return "\n".join(lines[idx + 1:end])

def text_contains_list(section_text: str, items: List[str]) -> bool:
    """
    Check if section_text contains the expected list in common formats:
    - JSON-like with quotes and brackets, e.g., ["a","b","c"] or ["a", "b", "c"]
    - Bracketed without quotes: [a, b, c]
    - Comma-separated without brackets: a, b, c
    We normalize whitespace for robust matching.
    """
    if not items:
        # Empty list edge case: accept "[]" or empty representation
        normalized = re.sub(r"\s+", "", section_text)
        return "[]" in normalized or "Union: []" in normalized or "Intersection: []" in normalized

    # Build candidates
    json_style_spaced = json.dumps(items)
    json_style_nospace = "[" + ",".join(json.dumps(x) for x in items) + "]"
    bracket_no_quotes_spaced = "[" + ", ".join(items) + "]"
    bracket_no_quotes_nospace = "[" + ",".join(items) + "]"
    comma_sep_spaced = ", ".join(items)
    comma_sep_nospace = ",".join(items)

    candidates = [
        json_style_spaced,
        json_style_nospace,
        bracket_no_quotes_spaced,
        bracket_no_quotes_nospace,
        comma_sep_spaced,
        comma_sep_nospace,
    ]

    normalized_section = re.sub(r"\s+", "", section_text)
    for cand in candidates:
        cand_norm = re.sub(r"\s+", "", cand)
        if cand in section_text or cand_norm in normalized_section:
            return True
    return False

def isoish(s: str) -> bool:
    # Basic ISO-8601 sanity check: YYYY-MM-DDThh... with optional Z
    if not isinstance(s, str) or not s:
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T.+Z?$", s))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    required_files = [
        "input/app_config.json",
        "input/user_profile.json",
        "input/products.json",
        "input/status.json",
    ]

    # Initialize checks with False
    checks: Dict[str, bool] = {}

    # Analysis output checks
    checks["analysis_exists"] = False
    checks["analysis_json_parsed"] = False
    checks["analysis_schema_fields"] = False
    checks["files_entries_complete"] = False
    checks["generated_at_isoish"] = False

    # Per-file checks will be added dynamically
    file_shortnames = {
        "input/app_config.json": "app_config",
        "input/user_profile.json": "user_profile",
        "input/products.json": "products",
        "input/status.json": "status",
    }

    # Union/Intersection checks
    checks["union_ok"] = False
    checks["intersection_ok"] = False

    # Report checks
    checks["report_exists"] = False
    checks["report_nonempty"] = False
    checks["report_has_headings"] = False
    checks["report_schemas_section_ok"] = False
    checks["report_no_nested_section_ok"] = False
    checks["report_keys_union_list_present"] = False
    checks["report_keys_intersection_list_present"] = False

    # Read and parse input files to compute expected structures
    expected_per_file: Dict[str, Dict[str, Any]] = {}
    for rel_path in required_files:
        abs_path = os.path.join(workspace_root, rel_path)
        ok, data = load_json(abs_path)
        if not ok:
            # If any input fails to parse, expected cannot be computed properly; leave checks to fail
            expected_per_file[rel_path] = {
                "top_level_keys": [],
                "key_count": 0,
                "has_nested_objects": False,
                "schema_signature": "",
            }
            continue
        expected_per_file[rel_path] = compute_structure(data)

    # Compute union and intersection from expected
    key_sets = []
    for rel_path in required_files:
        keys = expected_per_file.get(rel_path, {}).get("top_level_keys", [])
        key_sets.append(set(keys))
    if key_sets:
        union_expected = sorted(list(set().union(*key_sets)))
        intersection_expected = sorted(list(set.intersection(*key_sets))) if all(key_sets) else sorted(list(set()))
    else:
        union_expected = []
        intersection_expected = []

    # Validate analysis.json
    analysis_path = os.path.join(output_dir, "analysis.json")
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        parsed_ok, analysis_obj = load_json(analysis_path)
        if parsed_ok and isinstance(analysis_obj, dict):
            checks["analysis_json_parsed"] = True
            # Schema fields
            has_fields = (
                "generated_at" in analysis_obj
                and "files" in analysis_obj
                and "keys_union" in analysis_obj
                and "keys_intersection" in analysis_obj
                and isinstance(analysis_obj.get("files"), list)
                and isinstance(analysis_obj.get("keys_union"), list)
                and isinstance(analysis_obj.get("keys_intersection"), list)
                and isinstance(analysis_obj.get("generated_at"), str)
            )
            checks["analysis_schema_fields"] = bool(has_fields)

            if isinstance(analysis_obj.get("generated_at"), str):
                checks["generated_at_isoish"] = isoish(analysis_obj["generated_at"])

            # Files entries
            files_list = analysis_obj.get("files") if isinstance(analysis_obj.get("files"), list) else []
            # Create mapping from file path to entry
            file_entries: Dict[str, Dict[str, Any]] = {}
            for entry in files_list:
                if isinstance(entry, dict) and "file" in entry and isinstance(entry["file"], str):
                    file_entries[entry["file"]] = entry

            expected_set = set(required_files)
            actual_set = set(file_entries.keys())
            checks["files_entries_complete"] = (len(files_list) == 4 and actual_set == expected_set)

            # Per-file validations
            for rel_path in required_files:
                short = file_shortnames[rel_path]
                present_key = f"{short}_entry_present"
                keys_ok_key = f"{short}_keys_ok"
                key_count_ok_key = f"{short}_key_count_ok"
                nested_ok_key = f"{short}_nested_ok"
                schema_sig_ok_key = f"{short}_schema_signature_ok"
                checks[present_key] = False
                checks[keys_ok_key] = False
                checks[key_count_ok_key] = False
                checks[nested_ok_key] = False
                checks[schema_sig_ok_key] = False

                if rel_path in file_entries:
                    checks[present_key] = True
                    entry = file_entries[rel_path]
                    exp = expected_per_file.get(rel_path, {})
                    exp_keys = exp.get("top_level_keys", [])
                    exp_key_count = exp.get("key_count", 0)
                    exp_nested = exp.get("has_nested_objects", False)
                    exp_sig = exp.get("schema_signature", "")

                    top_level_keys = entry.get("top_level_keys")
                    if isinstance(top_level_keys, list) and all(isinstance(k, str) for k in top_level_keys):
                        # Ensure sorted
                        if top_level_keys == sorted(top_level_keys) and top_level_keys == exp_keys:
                            checks[keys_ok_key] = True
                    key_count = entry.get("key_count")
                    if isinstance(key_count, int) and key_count == len(top_level_keys) if isinstance(top_level_keys, list) else key_count == 0:
                        if key_count == exp_key_count:
                            checks[key_count_ok_key] = True
                    nested_val = entry.get("has_nested_objects")
                    if isinstance(nested_val, bool) and nested_val == exp_nested:
                        checks[nested_ok_key] = True
                    schema_sig = entry.get("schema_signature")
                    if isinstance(schema_sig, str) and schema_sig == exp_sig:
                        checks[schema_sig_ok_key] = True

            # Union / Intersection checks
            keys_union = analysis_obj.get("keys_union")
            if isinstance(keys_union, list) and all(isinstance(k, str) for k in keys_union):
                if keys_union == union_expected:
                    checks["union_ok"] = True
            keys_intersection = analysis_obj.get("keys_intersection")
            if isinstance(keys_intersection, list) and all(isinstance(k, str) for k in keys_intersection):
                if keys_intersection == intersection_expected:
                    checks["intersection_ok"] = True

    # Validate report.md
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        rpt_text = read_text(report_path)
        if isinstance(rpt_text, str) and len(rpt_text.strip()) > 0:
            checks["report_nonempty"] = True

            # Headings presence
            has_schemas = "## Schemas" in rpt_text
            has_no_nested = "## No nested objects" in rpt_text
            has_key_sets = "## Key sets" in rpt_text
            checks["report_has_headings"] = bool(has_schemas and has_no_nested and has_key_sets)

            # Schemas section validation
            schemas_section = get_section(rpt_text, "## Schemas")
            schemas_ok = True
            # Build signature -> list of files mapping from analysis (only if analysis_json_parsed and files_entries_complete)
            signature_to_files: Dict[str, List[str]] = {}
            if checks.get("analysis_json_parsed") and checks.get("files_entries_complete"):
                # Reload analysis to get signatures and associated files reliably
                _, analysis_obj = load_json(os.path.join(output_dir, "analysis.json"))
                file_entries = analysis_obj.get("files", []) if isinstance(analysis_obj.get("files"), list) else []
                for entry in file_entries:
                    if not isinstance(entry, dict):
                        continue
                    f = entry.get("file")
                    sig = entry.get("schema_signature")
                    if isinstance(f, str) and isinstance(sig, str):
                        signature_to_files.setdefault(sig, []).append(f)
                # For each signature, ensure it appears in the section and that the files sharing it are referenced near it
                section_lines = schemas_section.splitlines()
                for sig, files in signature_to_files.items():
                    # Find any line containing the signature
                    found_for_sig = False
                    for i, line in enumerate(section_lines):
                        if sig in line:
                            window = "\n".join(section_lines[i:i+3])  # line with sig and next two lines
                            if all(f in window for f in files):
                                found_for_sig = True
                                break
                    if not found_for_sig:
                        schemas_ok = False
                        break
            else:
                schemas_ok = False
            checks["report_schemas_section_ok"] = bool(schemas_ok and len(schemas_section.strip()) > 0)

            # No nested objects section validation
            no_nested_section = get_section(rpt_text, "## No nested objects")
            no_nested_ok = False
            if len(no_nested_section.strip()) > 0:
                # Determine expected flat files (has_nested_objects == False)
                expected_flat = [rel for rel, exp in expected_per_file.items() if not exp.get("has_nested_objects", True)]
                # Section must contain each flat file and must not contain any that are nested
                contains_all_flat = all(rel in no_nested_section for rel in expected_flat)
                contains_no_nested = all(
                    (rel not in no_nested_section)
                    for rel, exp in expected_per_file.items()
                    if exp.get("has_nested_objects", True)  # files with nested objs should not be listed
                )
                no_nested_ok = contains_all_flat and contains_no_nested
            checks["report_no_nested_section_ok"] = no_nested_ok

            # Key sets section: includes union and intersection (as lists)
            key_sets_section = get_section(rpt_text, "## Key sets")
            checks["report_keys_union_list_present"] = text_contains_list(key_sets_section, union_expected)
            checks["report_keys_intersection_list_present"] = text_contains_list(key_sets_section, intersection_expected)

    # Compute reward
    # Ensure no-op baseline: if both main outputs missing, reward = 0.0
    outputs_present = checks["analysis_exists"] or checks["report_exists"]

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if outputs_present and total_checks > 0:
        reward = passed_checks / total_checks
    else:
        reward = 0.0

    # Print single JSON line with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()