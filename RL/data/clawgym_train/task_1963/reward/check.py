import json
import os
import sys

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    txt = read_text_file(path)
    if txt is None:
        return None
    # Normalize newlines, drop final newline-only at end if present
    lines = txt.splitlines()
    return lines

def is_strictly_sorted(lst):
    return all(lst[i] < lst[i+1] for i in range(len(lst) - 1))

def ext_from_path(p):
    # p like "input/dir/file.ext" - use last dot in basename
    base = p.split("/")[-1]
    if base.startswith("."):
        # hidden files like ".env" considered no extension
        name_part = base[1:]
        if "." not in name_part:
            return ""
    if "." not in base:
        return ""
    # full extension after last dot (e.g., ".jsonl")
    idx = base.rfind(".")
    if idx <= 0:
        return ""
    return base[idx:]

def count_occurrences(haystack, needle):
    return haystack.count(needle)

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # tree.txt checks
        "tree_exists": False,
        "tree_lines_valid": False,
        "tree_exact_set": False,
        "tree_sorted_no_dupes": False,

        # inventory.csv checks
        "inventory_exists": False,
        "inventory_header_ok": False,
        "inventory_rowcount_matches_tree": False,
        "inventory_paths_align_tree": False,
        "inventory_sizes_nonneg_int": False,

        # files_by_ext.json checks
        "extjson_exists": False,
        "extjson_is_object": False,
        "extjson_sum_matches_tree": False,
        "extjson_counts_match_tree": False,

        # summary.md checks
        "summary_exists": False,
        "summary_has_two_term_occurrences": False,
        "summary_mentions_all_artifacts": False,
    }

    # Expected file list (relative paths starting with "input/")
    expected_paths = [
        "input/src/app.py",
        "input/src/utils/helpers.py",
        "input/README.md",
        "input/docs/spec.md",
        "input/data/sample.json",
        "input/data/config.yaml",
        "input/notes/todo.txt",
        "input/index.html",
        "input/manifest.xml",
        "input/CHANGELOG.md",
        "input/data/events.jsonl",
    ]
    expected_sorted = sorted(expected_paths)

    # 1) Validate output/tree.txt
    tree_path = os.path.join(output_dir, "tree.txt")
    tree_lines = None
    if os.path.isfile(tree_path):
        checks["tree_exists"] = True
        tree_lines = read_lines(tree_path)

        if isinstance(tree_lines, list) and len(tree_lines) > 0:
            # Validate each line:
            # - starts with "input/"
            # - no trailing spaces (strict)
            # - forward slashes only
            # - not empty
            starts_ok = all(line.startswith("input/") for line in tree_lines)
            no_trailing = all(line == line.rstrip() for line in tree_lines)
            forward_slashes_only = all("\\" not in line for line in tree_lines)
            not_empty = all(len(line) > 0 for line in tree_lines)
            checks["tree_lines_valid"] = bool(starts_ok and no_trailing and forward_slashes_only and not_empty)

            # Exact set match
            set_match = set(tree_lines) == set(expected_paths) and len(tree_lines) == len(expected_paths)
            checks["tree_exact_set"] = bool(set_match)

            # Sorted strictly ascending and no duplicates
            no_dupes = len(tree_lines) == len(set(tree_lines))
            sorted_strict = is_strictly_sorted(tree_lines)
            checks["tree_sorted_no_dupes"] = bool(no_dupes and sorted_strict)

    # 2) Validate output/inventory.csv
    inventory_path = os.path.join(output_dir, "inventory.csv")
    if os.path.isfile(inventory_path):
        checks["inventory_exists"] = True
        inv_lines = read_lines(inventory_path)
        if isinstance(inv_lines, list) and len(inv_lines) >= 1:
            header = inv_lines[0].lstrip("\ufeff")  # strip UTF-8 BOM if present
            checks["inventory_header_ok"] = (header == "path,size_bytes")

            data_rows = inv_lines[1:] if len(inv_lines) > 1 else []
            n_tree = len(tree_lines) if isinstance(tree_lines, list) else None

            if n_tree is not None:
                checks["inventory_rowcount_matches_tree"] = (len(data_rows) == n_tree)

                # Verify path alignment and size format
                paths_align = True
                sizes_nonneg = True

                if len(data_rows) == n_tree:
                    for i, row in enumerate(data_rows):
                        # CSV with exactly two fields separated by a single comma
                        # Allow commas only as separator (no quoting expected)
                        parts = row.split(",")
                        if len(parts) != 2:
                            paths_align = False
                            sizes_nonneg = False
                            break
                        path_field = parts[0]
                        size_field = parts[1]

                        # Path must exactly match tree line i
                        if not isinstance(tree_lines, list) or path_field != tree_lines[i]:
                            paths_align = False

                        # size must be a non-negative integer
                        s = size_field.strip()
                        try:
                            val = int(s, 10)
                            if val < 0:
                                sizes_nonneg = False
                        except Exception:
                            sizes_nonneg = False

                    checks["inventory_paths_align_tree"] = bool(paths_align)
                    checks["inventory_sizes_nonneg_int"] = bool(sizes_nonneg)

    # 3) Validate output/files_by_ext.json
    extjson_path = os.path.join(output_dir, "files_by_ext.json")
    ext_map = None
    if os.path.isfile(extjson_path):
        checks["extjson_exists"] = True
        try:
            with open(extjson_path, "r", encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed, dict):
                # Ensure keys are strings and values are integers >= 0
                key_types_ok = all(isinstance(k, str) for k in parsed.keys())
                val_types_ok = all(isinstance(v, int) and v >= 0 for v in parsed.values())
                checks["extjson_is_object"] = bool(key_types_ok and val_types_ok)
                if checks["extjson_is_object"]:
                    ext_map = parsed
        except Exception:
            pass

        # Only compute if tree_lines available and ext_map parsed
        if isinstance(tree_lines, list) and isinstance(ext_map, dict):
            # Build expected extension counts from tree.txt
            expected_counts = {}
            for p in tree_lines:
                ex = ext_from_path(p)
                expected_counts[ex] = expected_counts.get(ex, 0) + 1

            # Sum of values must equal number of files in tree.txt
            sum_values = sum(ext_map.values()) if ext_map else 0
            checks["extjson_sum_matches_tree"] = (sum_values == len(tree_lines))

            # Counts must match exactly
            checks["extjson_counts_match_tree"] = (ext_map == expected_counts)

    # 4) Validate output/summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary_txt = read_text_file(summary_path)
        if isinstance(summary_txt, str):
            # At least two occurrences of "/term "
            checks["summary_has_two_term_occurrences"] = (count_occurrences(summary_txt, "/term ") >= 2)

            # Must reference the three generated artifacts
            mentions = all(s in summary_txt for s in [
                "output/tree.txt",
                "output/inventory.csv",
                "output/files_by_ext.json",
            ])
            checks["summary_mentions_all_artifacts"] = bool(mentions)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Model no-op baseline: if output dir missing or empty, ensure reward is 0.0
    # If no output files exist, passed will be 0 and reward 0.0 already.
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()