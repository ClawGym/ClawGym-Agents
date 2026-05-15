import json
import os
import sys

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_int(n):
    return isinstance(n, int) and not isinstance(n, bool)

def non_empty_str(s):
    return isinstance(s, str) and len(s.strip()) > 0

def check_readme_anchors(text):
    if not isinstance(text, str):
        return False
    lower = text.lower()
    needed = ["overview", "valid documents", "invalid documents", "recommendations"]
    return all(term in lower for term in needed)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "report_json_valid": False,
        "report_has_required_keys": False,
        "report_counts_types_valid": False,
        "report_sums_consistent": False,
        "per_file_constraints_valid": False,
        "invalid_samples_valid": False,
        "normalized_outputs_presence": False,
        "normalized_json_content_valid": False,
        "normalized_jsonl_content_valid": False,
        "readme_exists": False,
        "readme_has_anchors": False,
    }

    report_path = os.path.join(output_dir, "report.json")
    per_file_entries = []
    report = None

    # Check report existence and validity
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report, err = read_json_file(report_path)
        if report is not None and isinstance(report, dict):
            checks["report_json_valid"] = True

    # Proceed only if report is a proper dict
    if checks["report_json_valid"]:
        # Required keys and types
        required_keys = ["documents_total", "documents_valid", "documents_invalid", "per_file", "invalid_samples"]
        has_keys = all(k in report for k in required_keys)

        counts_types_ok = False
        per_file_list_ok = False
        invalid_samples_list_ok = False

        if has_keys:
            # Validate top-level counts are ints and nonnegative
            dt = report.get("documents_total")
            dv = report.get("documents_valid")
            di = report.get("documents_invalid")
            counts_types_ok = all(is_int(v) and v >= 0 for v in [dt, dv, di])

            # Validate per_file is list
            per_file = report.get("per_file")
            per_file_list_ok = isinstance(per_file, list)

            # Validate invalid_samples is list
            invalid_samples = report.get("invalid_samples")
            invalid_samples_list_ok = isinstance(invalid_samples, list)

        checks["report_has_required_keys"] = has_keys and counts_types_ok and per_file_list_ok and invalid_samples_list_ok

        # Validate per_file constraints and sums
        sums_ok = False
        per_file_ok = False
        if checks["report_has_required_keys"]:
            per_file = report["per_file"]
            total_docs_sum = 0
            total_valid_sum = 0
            total_invalid_sum = 0
            per_file_ok = True  # assume true until a violation
            for entry in per_file:
                # Each entry must be dict with fields: path, type, documents, valid, invalid
                if not isinstance(entry, dict):
                    per_file_ok = False
                    break
                path = entry.get("path")
                ftype = entry.get("type")
                documents = entry.get("documents")
                valid = entry.get("valid")
                invalid = entry.get("invalid")

                # Basic type checks
                if not (non_empty_str(path) and non_empty_str(ftype) and is_int(documents) and is_int(valid) and is_int(invalid)):
                    per_file_ok = False
                    break
                if documents < 0 or valid < 0 or invalid < 0:
                    per_file_ok = False
                    break
                # Type constraints
                if ftype == "json":
                    # exactly one document; valid+invalid == 1
                    if documents != 1 or (valid + invalid) != 1:
                        per_file_ok = False
                        break
                elif ftype == "jsonl":
                    # documents == valid + invalid
                    if documents != (valid + invalid):
                        per_file_ok = False
                        break
                else:
                    per_file_ok = False
                    break

                total_docs_sum += documents
                total_valid_sum += valid
                total_invalid_sum += invalid

            # Now sums
            if per_file_ok:
                sums_ok = (
                    total_docs_sum == report["documents_total"]
                    and total_valid_sum == report["documents_valid"]
                    and total_invalid_sum == report["documents_invalid"]
                )

            per_file_entries = per_file if per_file_ok else []

        checks["per_file_constraints_valid"] = per_file_ok
        checks["report_sums_consistent"] = sums_ok

        # Validate invalid_samples constraints
        invalid_samples = report.get("invalid_samples", [])
        inv_ok = False
        if isinstance(invalid_samples, list) and checks["report_has_required_keys"]:
            max_expected = min(5, report["documents_invalid"])
            # must be <= 5 and equal to min(5, documents_invalid)
            length_ok = (len(invalid_samples) <= 5) and (len(invalid_samples) == max_expected)
            item_checks_ok = True
            for item in invalid_samples:
                if not isinstance(item, dict):
                    item_checks_ok = False
                    break
                path_ok = non_empty_str(item.get("path", ""))
                # line can be int or None
                line_val = item.get("line", None)
                line_ok = (line_val is None) or is_int(line_val)
                err_ok = non_empty_str(item.get("error_message", ""))
                snip = item.get("snippet", "")
                snippet_ok = isinstance(snip, str) and (1 <= len(snip.strip()) <= 80)
                if not (path_ok and line_ok and err_ok and snippet_ok):
                    item_checks_ok = False
                    break
            inv_ok = length_ok and item_checks_ok
        checks["invalid_samples_valid"] = inv_ok

        # Normalized outputs presence and content checks
        presence_ok = True
        json_content_ok = True
        jsonl_content_ok = True

        valid_dir = os.path.join(output_dir, "valid")

        if checks["per_file_constraints_valid"]:
            for entry in per_file_entries:
                path = entry["path"]
                ftype = entry["type"]
                valid_count = entry["valid"]
                base = os.path.basename(path)
                name, ext = os.path.splitext(base)

                if ftype == "json":
                    expected = os.path.join(valid_dir, f"{name}.json")
                    if valid_count > 0:
                        # must exist
                        if not os.path.isfile(expected):
                            presence_ok = False
                        else:
                            # content must be valid JSON
                            content, err = read_json_file(expected)
                            if content is None:
                                json_content_ok = False
                    else:
                        # must not exist
                        if os.path.exists(expected):
                            presence_ok = False

                elif ftype == "jsonl":
                    expected = os.path.join(valid_dir, f"{name}.jsonl")
                    if valid_count > 0:
                        # must exist
                        if not os.path.isfile(expected):
                            presence_ok = False
                        else:
                            try:
                                with open(expected, "r", encoding="utf-8") as fh:
                                    lines = fh.read().splitlines()
                                non_empty = [ln for ln in lines if ln.strip() != ""]
                                # Must have no blank lines and exact count of valid docs
                                if len(lines) != len(non_empty) or len(lines) != valid_count:
                                    jsonl_content_ok = False
                                else:
                                    for ln in lines:
                                        try:
                                            json.loads(ln)
                                        except Exception:
                                            jsonl_content_ok = False
                                            break
                            except Exception:
                                jsonl_content_ok = False
                    else:
                        # must not exist
                        if os.path.exists(expected):
                            presence_ok = False
                else:
                    # Should not happen due to earlier validation
                    presence_ok = False

        # If there were no per_file entries (e.g., empty list), then presence checks trivially pass?
        # But documents_total would then be 0, and there should be no normalized outputs. We'll accept presence_ok as computed.

        checks["normalized_outputs_presence"] = presence_ok and checks["per_file_constraints_valid"]
        checks["normalized_json_content_valid"] = json_content_ok and checks["per_file_constraints_valid"]
        checks["normalized_jsonl_content_valid"] = jsonl_content_ok and checks["per_file_constraints_valid"]

    # README checks
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_text = f.read()
            if check_readme_anchors(readme_text):
                checks["readme_has_anchors"] = True
        except Exception:
            pass

    # Compute reward
    # Enforce no-op baseline: if report.json is missing, reward = 0.0
    if not checks["report_exists"]:
        reward = 0.0
    else:
        # Average of all checks
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()