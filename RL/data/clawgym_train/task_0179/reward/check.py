import os
import sys
import json
import hashlib

def safe_key(label: str) -> str:
    out = []
    for ch in label:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append('_')
    return ''.join(out)

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    extracted_dir = os.path.join(output_dir, "extracted")
    report_path = os.path.join(output_dir, "report.json")

    # Expected markers (relative to output/extracted)
    expected_marker_rel_dirs = [
        "top",
        "top/inner",
        "top/extra",
        "top/another",
        "top/another/pack",
        "top/inner/nested/more/notes.txt",
        "solo.txt",
    ]

    # Expected text files and their exact contents
    expected_files = {
        "top/readme.txt": b"Top level README\n",
        "top/inner/nested/data.csv": b"id,value\n1,foo\n2,bar\n",
        "top/inner/nested/more/notes.txt/notes.txt": b"These are nested notes.\n",
        "top/extra/alpha.txt": b"alpha\n",
        "top/another/doc.md": b"# Doc\n",
        "top/another/pack/leaf.txt": b"leaf\n",
        "solo.txt/solo.txt": b"a solo line\n",
    }
    expected_paths_set = set(expected_files.keys())

    checks = {}

    # Check extracted directory exists
    extracted_exists = os.path.isdir(extracted_dir)
    checks["extracted_dir_exists"] = extracted_exists

    # Marker checks
    marker_checks = {}
    for rel_dir in expected_marker_rel_dirs:
        key = f"marker_{safe_key(rel_dir)}"
        marker_file = os.path.join(extracted_dir, rel_dir, ".extracted_success")
        marker_checks[key] = extracted_exists and os.path.isfile(marker_file)
        checks[key] = marker_checks[key]

    # File content checks
    content_checks = {}
    for rel_path, expected_content in expected_files.items():
        abs_path = os.path.join(extracted_dir, rel_path)
        key = f"file_ok_{safe_key(rel_path)}"
        ok = False
        if extracted_exists and os.path.isfile(abs_path):
            try:
                with open(abs_path, 'rb') as f:
                    data = f.read()
                ok = data == expected_content
            except Exception:
                ok = False
        content_checks[key] = ok
        checks[key] = ok

    # Report checks
    report_exists = os.path.isfile(report_path)
    checks["report_exists"] = report_exists

    report_is_array = False
    report_exact_paths = False
    per_entry_checks = {}

    report_data = None
    if report_exists:
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report_data = json.load(f)
            if isinstance(report_data, list):
                report_is_array = True
        except Exception:
            report_is_array = False

    checks["report_is_array"] = report_is_array

    # Validate exact set of paths and length
    report_paths = []
    if report_is_array:
        # Collect paths if objects
        unique_paths = set()
        all_have_required_fields = True
        for item in report_data:
            if not isinstance(item, dict) or "path" not in item or "sha256" not in item or "size" not in item:
                all_have_required_fields = False
                break
            path_val = item["path"]
            if not isinstance(path_val, str):
                all_have_required_fields = False
                break
            report_paths.append(path_val)
            unique_paths.add(path_val)
        # Exact match required: length 7, unique 7, set equals expected
        if all_have_required_fields and len(report_paths) == 7 and len(unique_paths) == 7 and set(report_paths) == expected_paths_set:
            report_exact_paths = True

    checks["report_exact_paths"] = report_exact_paths

    # Per-entry hash and size checks
    if report_is_array and report_exact_paths and extracted_exists:
        # Map from path to entry
        entry_by_path = {item["path"]: item for item in report_data}
        for rel_path in expected_paths_set:
            key = f"report_sha_size_match_{safe_key(rel_path)}"
            ok = False
            entry = entry_by_path.get(rel_path)
            if entry is not None and isinstance(entry, dict):
                sha = entry.get("sha256")
                size = entry.get("size")
                abs_path = os.path.join(extracted_dir, rel_path)
                if isinstance(sha, str) and isinstance(size, int) and os.path.isfile(abs_path):
                    try:
                        actual_sha = sha256_file(abs_path)
                        actual_size = os.path.getsize(abs_path)
                        ok = (sha == actual_sha) and (size == actual_size)
                    except Exception:
                        ok = False
            per_entry_checks[key] = ok
            checks[key] = ok
    else:
        # Fill per-entry checks as False for visibility
        for rel_path in expected_paths_set:
            key = f"report_sha_size_match_{safe_key(rel_path)}"
            checks[key] = False

    # Compute reward with weighted scoring
    reward = 0.0
    # Weights
    w_extracted_dir_exists = 0.05
    w_marker_each = 0.03  # 7 markers -> 0.21
    w_file_content_each = 0.07  # 7 files -> 0.49
    w_report_exists = 0.05
    w_report_exact_paths = 0.10
    w_report_entry_each = 0.10 / 7.0  # -> 0.10 total

    if checks["extracted_dir_exists"]:
        reward += w_extracted_dir_exists

    for rel_dir in expected_marker_rel_dirs:
        key = f"marker_{safe_key(rel_dir)}"
        if checks.get(key, False):
            reward += w_marker_each

    for rel_path in expected_files.keys():
        key = f"file_ok_{safe_key(rel_path)}"
        if checks.get(key, False):
            reward += w_file_content_each

    if checks["report_exists"]:
        reward += w_report_exists

    if checks["report_exact_paths"]:
        reward += w_report_exact_paths

    for rel_path in expected_files.keys():
        key = f"report_sha_size_match_{safe_key(rel_path)}"
        if checks.get(key, False):
            reward += w_report_entry_each

    # Ensure baseline 0.0 if no artifacts (output empty)
    # If nothing under output or extracted missing and report missing, reward likely 0 already.
    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()