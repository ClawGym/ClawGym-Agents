import json
import os
import re
import sys
from collections import OrderedDict

def is_non_ascii_present(s: str) -> bool:
    return any(ord(ch) > 127 for ch in s)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    translations_path = os.path.join(output_dir, "translations.jsonl")
    summary_path = os.path.join(output_dir, "summary.md")

    # Initialize checks (all False by default)
    checks = OrderedDict([
        ("translations_file_exists", False),
        ("translations_jsonl_valid", False),
        ("translations_notes_array", False),
        ("contains_aml_entry", False),
        ("contains_unknown_requires_manual", False),
        ("en_to_cn_non_ascii", False),
        ("no_not_supported_placeholder", False),
        ("summary_exists_sections", False),
        ("summary_coverage_line_present", False),
        ("summary_counts_match_total", False),
        ("summary_unknown_count_match", False),
    ])

    parsed_objects = []
    non_empty_lines_count = 0

    # Validate translations.jsonl existence and parse content
    if os.path.isfile(translations_path) and os.path.getsize(translations_path) > 0:
        checks["translations_file_exists"] = True
        expected_keys = {"original", "source_lang", "target_lang", "translated", "notes"}
        jsonl_valid = True
        notes_array_valid = True
        try:
            with open(translations_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line.strip():
                        # Ignore empty lines, but they should not exist in a strict JSONL
                        continue
                    non_empty_lines_count += 1
                    try:
                        obj = json.loads(line)
                    except Exception:
                        jsonl_valid = False
                        # keep reading to avoid partial reads affecting subsequent checks
                        continue
                    if not isinstance(obj, dict):
                        jsonl_valid = False
                    else:
                        # exact keys check
                        if set(obj.keys()) != expected_keys:
                            jsonl_valid = False
                        else:
                            # notes array check deferred aggregate
                            if not isinstance(obj.get("notes"), list):
                                notes_array_valid = False
                            parsed_objects.append(obj)
            # Valid if all non-empty lines parsed to objects and exact-key dicts
            if jsonl_valid and non_empty_lines_count == len(parsed_objects) and non_empty_lines_count > 0:
                checks["translations_jsonl_valid"] = True
                if notes_array_valid:
                    checks["translations_notes_array"] = True
        except Exception:
            # On any unexpected IO error, leave checks as False
            pass

        # Additional content checks rely on successfully parsed objects
        if checks["translations_jsonl_valid"]:
            # contains AML entry: original == "急性髓系白血病" and translated exactly "Acute Myeloid Leukemia (AML)"
            for obj in parsed_objects:
                if obj.get("original") == "急性髓系白血病" and obj.get("translated") == "Acute Myeloid Leukemia (AML)":
                    checks["contains_aml_entry"] = True
                    break

            # contains unknown requires manual confirmation for "重症肌无力"
            for obj in parsed_objects:
                if obj.get("original") == "重症肌无力" and isinstance(obj.get("translated"), str) and obj["translated"].startswith("[Requires manual confirmation] "):
                    checks["contains_unknown_requires_manual"] = True
                    break

            # English -> Chinese with non-ASCII characters in translated
            for obj in parsed_objects:
                if obj.get("source_lang") == "English" and obj.get("target_lang") == "Chinese":
                    translated = obj.get("translated", "")
                    if isinstance(translated, str) and is_non_ascii_present(translated):
                        checks["en_to_cn_non_ascii"] = True
                        break

            # Ensure no translated field contains "[Not supported yet]"
            no_placeholder = True
            for obj in parsed_objects:
                translated = obj.get("translated", "")
                if isinstance(translated, str) and "[Not supported yet]" in translated:
                    no_placeholder = False
                    break
            if no_placeholder:
                checks["no_not_supported_placeholder"] = True

    # Validate summary.md
    coverage_N = None
    coverage_X = None
    coverage_Y = None
    if os.path.isfile(summary_path) and os.path.getsize(summary_path) > 0:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f]
            stripped_lines = [ln.strip() for ln in lines]

            required_headings = [
                "Objective",
                "Inputs Received",
                "Assumptions",
                "Workflow",
                "Deliverable",
                "Risks and Limits",
                "Next Checks",
            ]
            headings_present = all(any(sl == h for sl in stripped_lines) for h in required_headings)
            if headings_present:
                checks["summary_exists_sections"] = True

            # Find Deliverable section range
            deliverable_start = None
            for idx, sl in enumerate(stripped_lines):
                if sl == "Deliverable":
                    deliverable_start = idx
                    break

            if deliverable_start is not None:
                # Determine next heading after Deliverable
                next_heading_idx = None
                for idx in range(deliverable_start + 1, len(stripped_lines)):
                    if stripped_lines[idx] in required_headings:
                        next_heading_idx = idx
                        break
                section_end = next_heading_idx if next_heading_idx is not None else len(stripped_lines)
                deliverable_section = stripped_lines[deliverable_start + 1:section_end]

                # Regex for coverage line
                pattern = re.compile(r'^Total terms:\s*(\d+);\s*Confirmed:\s*(\d+);\s*Requires manual confirmation:\s*(\d+)$')
                matches = [m for ln in deliverable_section if (m := pattern.match(ln))]
                if len(matches) == 1:
                    checks["summary_coverage_line_present"] = True
                    coverage_N = int(matches[0].group(1))
                    coverage_X = int(matches[0].group(2))
                    coverage_Y = int(matches[0].group(3))
        except Exception:
            pass

    # Cross-file consistency checks
    if checks["translations_jsonl_valid"] and checks["summary_coverage_line_present"]:
        # N equals number of parsed objects (non-empty JSON lines)
        if coverage_N == len(parsed_objects):
            checks["summary_counts_match_total"] = True

        # Y equals count of requires manual confirmation entries
        manual_count = sum(1 for obj in parsed_objects if isinstance(obj.get("translated"), str) and obj["translated"].startswith("[Requires manual confirmation] "))
        if coverage_Y == manual_count:
            checks["summary_unknown_count_match"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()