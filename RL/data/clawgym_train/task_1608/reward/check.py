import json
import os
import sys
from datetime import datetime

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        # Minified JSON users
        "has_users_minified_file": False,
        "users_minified_valid_json": False,
        "users_minified_single_line": False,
        "users_minified_no_space_after_colon_comma": False,
        # Minified JSON products
        "has_products_minified_file": False,
        "products_minified_valid_json": False,
        "products_minified_single_line": False,
        "products_minified_no_space_after_colon_comma": False,
        # Index checks
        "index_exists": False,
        "index_is_object": False,
        "index_has_required_keys": False,
        "index_tokens_lowercase_dedup": False,
        "index_tokens_len_ge5": False,
        # Rubric-ish heuristic (not scored)
        "index_quality_tokens_length_ok": False,
        # Search checks
        "search_optimization_exists": False,
        "search_optimization_valid": False,
        "search_security_exists": False,
        "search_security_valid": False,
        # Compacted digest
        "compact_digest_exists": False,
        "compact_digest_title_in_first5": False,
        "compact_digest_has_sources_and_listed": False,
        "compact_digest_min_lines": False,
        "compact_digest_has_keywords": False,
        # Optimization report
        "report_exists": False,
        "report_structure_valid": False,
        "report_paths_match_expected": False,
        "report_values_valid": False,
        # Optional informative check (not scored)
        "report_sizes_match_files": False,
    }

    # Paths
    users_min_path = os.path.join(output_dir, "optimized", "users.min.json")
    products_min_path = os.path.join(output_dir, "optimized", "products.min.json")
    index_path = os.path.join(output_dir, "index", "search-index.json")
    search_opt_path = os.path.join(output_dir, "search", "optimization.json")
    search_sec_path = os.path.join(output_dir, "search", "security.json")
    compact_path = os.path.join(output_dir, "compact", "compacted.md")
    report_path = os.path.join(output_dir, "report", "optimization_report.json")

    # 1) Minified JSON files
    # users
    if os.path.isfile(users_min_path):
        checks["has_users_minified_file"] = True
        content, err = read_text(users_min_path)
        if content is not None:
            # single-line: no newline chars
            if ("\n" not in content) and ("\r" not in content):
                checks["users_minified_single_line"] = True
            # minified style: no ": " or ", "
            if (": " not in content) and (", " not in content):
                checks["users_minified_no_space_after_colon_comma"] = True
            # valid JSON
            try:
                json.loads(content)
                checks["users_minified_valid_json"] = True
            except Exception:
                pass

    # products
    if os.path.isfile(products_min_path):
        checks["has_products_minified_file"] = True
        content, err = read_text(products_min_path)
        if content is not None:
            if ("\n" not in content) and ("\r" not in content):
                checks["products_minified_single_line"] = True
            if (": " not in content) and (", " not in content):
                checks["products_minified_no_space_after_colon_comma"] = True
            try:
                json.loads(content)
                checks["products_minified_valid_json"] = True
            except Exception:
                pass

    # 2) Index checks
    index_data = None
    if os.path.isfile(index_path):
        checks["index_exists"] = True
        index_data, err = load_json_file(index_path)
        if isinstance(index_data, dict):
            checks["index_is_object"] = True
            required_basenames = ["users.json", "products.json", "README.md", "CHANGELOG.md", "notes.txt"]
            if all(k in index_data for k in required_basenames):
                checks["index_has_required_keys"] = True

                # tokens_lowercase_dedup and len>=5 for required basenames
                lower_dedup_ok = True
                len_ge5_ok = True
                for k in required_basenames:
                    v = index_data.get(k)
                    if not isinstance(v, list):
                        lower_dedup_ok = False
                        len_ge5_ok = False
                        break
                    # all strings
                    if not all(isinstance(t, str) for t in v):
                        lower_dedup_ok = False
                    # lowercase
                    if not all(t == t.lower() for t in v if isinstance(t, str)):
                        lower_dedup_ok = False
                    # dedup
                    if len(v) != len(set(v)):
                        lower_dedup_ok = False
                    # length >= 5
                    if len(v) < 5:
                        len_ge5_ok = False
                checks["index_tokens_lowercase_dedup"] = lower_dedup_ok
                checks["index_tokens_len_ge5"] = len_ge5_ok

            # heuristic: token length quality across all entries
            try:
                all_tokens = []
                for k, v in index_data.items():
                    if isinstance(v, list):
                        for t in v:
                            if isinstance(t, str):
                                all_tokens.append(t)
                if len(all_tokens) > 0:
                    short_count = sum(1 for t in all_tokens if len(t) < 2)
                    # Pass if NOT more than 50% are short (i.e., short_ratio <= 0.5)
                    short_ratio = short_count / len(all_tokens)
                    checks["index_quality_tokens_length_ok"] = short_ratio <= 0.5
            except Exception:
                pass

    # 3) Sample searches checks
    index_keys = set(index_data.keys()) if isinstance(index_data, dict) else set()

    # optimization search
    if os.path.isfile(search_opt_path):
        checks["search_optimization_exists"] = True
        opt_json, err = load_json_file(search_opt_path)
        if isinstance(opt_json, dict):
            q = opt_json.get("query")
            res = opt_json.get("results")
            if isinstance(q, str) and q == "optimization" and isinstance(res, list):
                # results: at least 2 basenames and all present in index
                res_ok = all(isinstance(x, str) for x in res)
                res_count_ok = len(res) >= 2
                in_index_ok = all((x in index_keys) for x in res)
                checks["search_optimization_valid"] = res_ok and res_count_ok and in_index_ok

    # security search
    if os.path.isfile(search_sec_path):
        checks["search_security_exists"] = True
        sec_json, err = load_json_file(search_sec_path)
        if isinstance(sec_json, dict):
            q = sec_json.get("query")
            res = sec_json.get("results")
            if isinstance(q, str) and q == "security" and isinstance(res, list):
                res_ok = all(isinstance(x, str) for x in res)
                res_count_ok = len(res) >= 2
                in_index_ok = all((x in index_keys) for x in res)
                checks["search_security_valid"] = res_ok and res_count_ok and in_index_ok

    # 4) Compacted digest
    if os.path.isfile(compact_path):
        checks["compact_digest_exists"] = True
        ctext, err = read_text(compact_path)
        if ctext is not None:
            lines = ctext.splitlines()
            # Title in first 5 lines (exact line contains "Compacted Summary")
            first5 = lines[:5]
            if any("Compacted Summary" in (ln or "") for ln in first5):
                checks["compact_digest_title_in_first5"] = True
            # At least 5 non-empty lines
            non_empty = [ln for ln in lines if ln.strip()]
            if len(non_empty) >= 5:
                checks["compact_digest_min_lines"] = True
            # Sources section: find "Sources:" line, then below must include three basenames
            sources_ok = False
            try:
                src_idx = next(i for i, ln in enumerate(lines) if "Sources:" in ln)
                below_text = "\n".join(lines[src_idx+1:]) if src_idx+1 < len(lines) else ""
                required_sources = ["README.md", "CHANGELOG.md", "notes.txt"]
                if all(s in below_text for s in required_sources):
                    sources_ok = True
            except StopIteration:
                sources_ok = False
            checks["compact_digest_has_sources_and_listed"] = sources_ok
            # Keywords heuristic: at least two of performance, security, indexing, compaction (case-insensitive)
            content_lower = ctext.lower()
            keywords = ["performance", "security", "indexing", "compaction"]
            present = sum(1 for kw in keywords if kw in content_lower)
            if present >= 2:
                checks["compact_digest_has_keywords"] = True

    # 5) Optimization report
    report_data = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_data, err = load_json_file(report_path)
        if isinstance(report_data, dict):
            # structure
            files = report_data.get("files")
            total_reduction_percent = report_data.get("total_reduction_percent")
            timestamp = report_data.get("timestamp")
            method = report_data.get("method")
            notes = report_data.get("notes")

            structure_ok = (
                isinstance(files, list) and len(files) == 2 and
                is_number(total_reduction_percent) and
                isinstance(timestamp, str) and
                isinstance(method, str) and
                isinstance(notes, str)
            )

            details_ok = True
            paths_pair_ok = False
            size_value_ok = True

            expected_pairs = {
                "input/users.json": "output/optimized/users.min.json",
                "input/products.json": "output/optimized/products.min.json",
            }
            seen_pairs = {}

            if structure_ok:
                for item in files:
                    if not isinstance(item, dict):
                        details_ok = False
                        break
                    opath = item.get("original_path")
                    spath = item.get("optimized_path")
                    osize = item.get("original_size_bytes")
                    ssize = item.get("optimized_size_bytes")
                    rperc = item.get("reduction_percent")
                    if not (isinstance(opath, str) and isinstance(spath, str) and isinstance(osize, int) and isinstance(ssize, int) and is_number(rperc)):
                        details_ok = False
                        break
                    # ranges
                    if not (ssize <= osize and 0 <= rperc <= 100):
                        size_value_ok = False
                    seen_pairs[opath] = spath

                checks["report_structure_valid"] = details_ok and structure_ok
                # paths exact matching (unordered)
                paths_pair_ok = (seen_pairs == expected_pairs)
                checks["report_paths_match_expected"] = paths_pair_ok

                # total reduction in 0..100
                values_ok = size_value_ok and (0 <= total_reduction_percent <= 100)
                checks["report_values_valid"] = values_ok

                # Optional: verify sizes match actual files if present
                report_sizes_match = False
                try:
                    # only proceed if minified outputs exist
                    users_input_path = os.path.join(input_dir, "users.json")
                    products_input_path = os.path.join(input_dir, "products.json")
                    users_min_abs = users_min_path
                    products_min_abs = products_min_path

                    # Build expected size mapping
                    if (os.path.isfile(users_input_path) and os.path.isfile(products_input_path) and
                        os.path.isfile(users_min_abs) and os.path.isfile(products_min_abs)) and isinstance(files, list):

                        actual_map = {
                            "input/users.json": os.path.getsize(users_input_path),
                            "input/products.json": os.path.getsize(products_input_path),
                        }
                        actual_min_map = {
                            "output/optimized/users.min.json": os.path.getsize(users_min_abs),
                            "output/optimized/products.min.json": os.path.getsize(products_min_abs),
                        }

                        match_all = True
                        for item in files:
                            opath = item.get("original_path")
                            spath = item.get("optimized_path")
                            osize = item.get("original_size_bytes")
                            ssize = item.get("optimized_size_bytes")
                            if opath not in actual_map or spath not in actual_min_map:
                                match_all = False
                                break
                            if actual_map[opath] != osize or actual_min_map[spath] != ssize:
                                match_all = False
                                break
                        report_sizes_match = match_all
                except Exception:
                    report_sizes_match = False
                checks["report_sizes_match_files"] = report_sizes_match

    # Compute reward from deterministic checks only
    deterministic_keys = [
        "has_users_minified_file",
        "users_minified_valid_json",
        "users_minified_single_line",
        "users_minified_no_space_after_colon_comma",
        "has_products_minified_file",
        "products_minified_valid_json",
        "products_minified_single_line",
        "products_minified_no_space_after_colon_comma",
        "index_exists",
        "index_is_object",
        "index_has_required_keys",
        "index_tokens_lowercase_dedup",
        "index_tokens_len_ge5",
        "search_optimization_exists",
        "search_optimization_valid",
        "search_security_exists",
        "search_security_valid",
        "compact_digest_exists",
        "compact_digest_title_in_first5",
        "compact_digest_has_sources_and_listed",
        "compact_digest_min_lines",
        "compact_digest_has_keywords",
        "report_exists",
        "report_structure_valid",
        "report_paths_match_expected",
        "report_values_valid",
    ]

    passed = sum(1 for k in deterministic_keys if checks.get(k, False))
    total = len(deterministic_keys)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure no-op baseline yields 0.0 (already ensured by lack of outputs)
    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()