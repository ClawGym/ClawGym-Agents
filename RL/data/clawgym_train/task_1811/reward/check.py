import json
import os
import sys
import hashlib

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def file_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return None

def count_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return None

def sha256_hex(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_nonneg_int(x):
    return isinstance(x, int) and x >= 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict with all required checks defaulting to False
    checks = {
        # plan.md checks
        "has_plan_md": False,
        "plan_has_params": False,
        "plan_has_risk_and_rollback": False,
        # preview.md checks
        "has_preview_md": False,
        "preview_mentions_dry_run": False,
        "preview_mentions_files": False,
        # pruned chatlog checks
        "has_pruned_chatlog": False,
        "pruned_chatlog_non_empty": False,
        "pruned_chatlog_line_limit": False,
        "pruned_chatlog_byte_limit": False,
        # state compacted checks
        "has_state_compacted": False,
        "state_no_debug": False,
        # rotation manifest checks
        "has_rotation_manifest": False,
        "rotation_json_valid_structure": False,
        "rotation_keep_count_is_3": False,
        "rotation_no_overlap": False,
        "rotation_sizes_non_negative": False,
        "rotation_internal_consistency": False,
        # stats json checks
        "has_stats_json": False,
        "stats_valid_structure": False,
        "stats_includes_pruned_chatlog": False,
        "stats_includes_state_compacted": False,
        "stats_metrics_match_chatlog": False,
        "stats_metrics_match_state": False,
        "stats_totals_match": False,
    }

    # Paths to required outputs
    plan_md_path = os.path.join(output_dir, "plan.md")
    preview_md_path = os.path.join(output_dir, "preview.md")
    pruned_chatlog_path = os.path.join(output_dir, "pruned", "chatlog_pruned.txt")
    state_compacted_path = os.path.join(output_dir, "pruned", "state_compacted.md")
    rotation_manifest_path = os.path.join(output_dir, "rotation", "manifest.json")
    stats_json_path = os.path.join(output_dir, "stats.json")

    # plan.md checks
    if os.path.isfile(plan_md_path):
        checks["has_plan_md"] = True
        content = read_text(plan_md_path)
        if content is not None:
            required_params = [
                "max-lines: 120",
                "max-bytes: 4096",
                "remove-before: 2025-06-01",
                "remove-pattern: [DEBUG]",
                "keep: 3",
            ]
            if all(p in content for p in required_params):
                checks["plan_has_params"] = True
            lc = content.lower()
            if ("risk" in lc) and ("rollback" in lc):
                checks["plan_has_risk_and_rollback"] = True

    # preview.md checks
    if os.path.isfile(preview_md_path):
        checks["has_preview_md"] = True
        content = read_text(preview_md_path)
        if content is not None:
            if ("dry run" in content.lower()) or ("dr y run" in content.lower()):  # handle spacing variants conservatively
                checks["preview_mentions_dry_run"] = True if "dry run" in content.lower() else checks["preview_mentions_dry_run"]
            # Accept uppercase "DRY RUN" or any case-insensitive presence
            if "dry run" in content.lower() or "dryrun" in content.lower() or "dry-run" in content.lower():
                checks["preview_mentions_dry_run"] = True
            if ("chatlog.txt" in content) and ("state.md" in content):
                checks["preview_mentions_files"] = True

    # pruned chatlog checks
    if os.path.isfile(pruned_chatlog_path):
        checks["has_pruned_chatlog"] = True
        size = file_size(pruned_chatlog_path)
        if size is not None and size > 0:
            checks["pruned_chatlog_non_empty"] = True
        if size is not None and size <= 4096:
            checks["pruned_chatlog_byte_limit"] = True
        lines = count_lines(pruned_chatlog_path)
        if lines is not None and lines <= 120:
            checks["pruned_chatlog_line_limit"] = True

    # state compacted checks
    if os.path.isfile(state_compacted_path):
        checks["has_state_compacted"] = True
        content = None
        try:
            content = read_text(state_compacted_path)
        except Exception:
            content = None
        if content is not None:
            if "[DEBUG]" not in content:
                checks["state_no_debug"] = True

    # rotation manifest checks
    rotation = None
    if os.path.isfile(rotation_manifest_path):
        checks["has_rotation_manifest"] = True
        rotation = parse_json_file(rotation_manifest_path)
        if isinstance(rotation, dict):
            # Validate structure and types
            keys_required = {"keep_count", "keep", "delete", "retained_bytes", "freed_bytes", "total_bytes"}
            if keys_required.issubset(rotation.keys()):
                keep = rotation.get("keep")
                delete = rotation.get("delete")
                keep_count = rotation.get("keep_count")
                retained_bytes = rotation.get("retained_bytes")
                freed_bytes = rotation.get("freed_bytes")
                total_bytes = rotation.get("total_bytes")
                if isinstance(keep, list) and isinstance(delete, list) and isinstance(keep_count, int) and all(
                    k in rotation for k in keys_required
                ) and is_nonneg_int(retained_bytes) and is_nonneg_int(freed_bytes) and is_nonneg_int(total_bytes):
                    checks["rotation_json_valid_structure"] = True

                    # keep_count and len(keep)
                    if keep_count == 3 and len(keep) == 3:
                        checks["rotation_keep_count_is_3"] = True

                    # no overlap between names
                    try:
                        keep_names = set([str(item.get("name")) for item in keep if isinstance(item, dict) and "name" in item])
                        delete_names = set([str(item.get("name")) for item in delete if isinstance(item, dict) and "name" in item])
                        if keep_names.isdisjoint(delete_names):
                            checks["rotation_no_overlap"] = True
                    except Exception:
                        pass

                    # size fields non-negative integers (top-level and per-item size_bytes)
                    sizes_ok = True
                    for arr in (keep, delete):
                        for item in arr:
                            if not isinstance(item, dict):
                                sizes_ok = False
                                break
                            if "size_bytes" not in item or not is_nonneg_int(item["size_bytes"]):
                                sizes_ok = False
                                break
                    if sizes_ok and is_nonneg_int(retained_bytes) and is_nonneg_int(freed_bytes) and is_nonneg_int(total_bytes):
                        checks["rotation_sizes_non_negative"] = True

                    # internal consistency: retained + freed == total; and retained equals sum keep sizes; freed equals sum delete sizes
                    try:
                        sum_keep = sum(int(item["size_bytes"]) for item in keep if isinstance(item, dict) and "size_bytes" in item)
                        sum_delete = sum(int(item["size_bytes"]) for item in delete if isinstance(item, dict) and "size_bytes" in item)
                        if sum_keep == retained_bytes and sum_delete == freed_bytes and (retained_bytes + freed_bytes) == total_bytes:
                            checks["rotation_internal_consistency"] = True
                    except Exception:
                        pass

    # stats.json checks
    stats = None
    if os.path.isfile(stats_json_path):
        checks["has_stats_json"] = True
        stats = parse_json_file(stats_json_path)
        if isinstance(stats, dict) and "files" in stats and "total_files" in stats and "total_bytes" in stats and "total_lines" in stats:
            files_list = stats.get("files")
            total_files = stats.get("total_files")
            total_bytes_reported = stats.get("total_bytes")
            total_lines_reported = stats.get("total_lines")
            if isinstance(files_list, list) and isinstance(total_files, int) and isinstance(total_bytes_reported, int) and isinstance(total_lines_reported, int):
                checks["stats_valid_structure"] = True

                # look for required entries
                required_entries = {
                    "output/pruned/chatlog_pruned.txt": "stats_includes_pruned_chatlog",
                    "output/pruned/state_compacted.md": "stats_includes_state_compacted",
                }
                # Build mapping from 'file' to entry
                entry_map = {}
                for item in files_list:
                    if isinstance(item, dict) and "file" in item:
                        entry_map[item["file"]] = item

                for rel_path, check_key in required_entries.items():
                    if rel_path in entry_map:
                        item = entry_map[rel_path]
                        if (
                            isinstance(item.get("bytes"), int)
                            and isinstance(item.get("lines"), int)
                            and isinstance(item.get("sha256"), str)
                        ):
                            checks[check_key] = True

                # Metrics must match actual file contents for both files
                # chatlog
                chatlog_rel = "output/pruned/chatlog_pruned.txt"
                state_rel = "output/pruned/state_compacted.md"
                if checks["stats_includes_pruned_chatlog"]:
                    item = entry_map[chatlog_rel]
                    actual_bytes = file_size(pruned_chatlog_path)
                    actual_lines = count_lines(pruned_chatlog_path)
                    actual_sha = sha256_hex(pruned_chatlog_path)
                    if (
                        actual_bytes is not None
                        and actual_lines is not None
                        and actual_sha is not None
                        and item["bytes"] == actual_bytes
                        and item["lines"] == actual_lines
                        and item["sha256"] == actual_sha
                    ):
                        checks["stats_metrics_match_chatlog"] = True

                if checks["stats_includes_state_compacted"]:
                    item = entry_map[state_rel]
                    actual_bytes = file_size(state_compacted_path)
                    actual_lines = count_lines(state_compacted_path)
                    actual_sha = sha256_hex(state_compacted_path)
                    if (
                        actual_bytes is not None
                        and actual_lines is not None
                        and actual_sha is not None
                        and item["bytes"] == actual_bytes
                        and item["lines"] == actual_lines
                        and item["sha256"] == actual_sha
                    ):
                        checks["stats_metrics_match_state"] = True

                # Totals must equal sum of per-file metrics present in files[]
                try:
                    sum_bytes = 0
                    sum_lines = 0
                    for item in files_list:
                        if isinstance(item, dict):
                            b = item.get("bytes")
                            l = item.get("lines")
                            if isinstance(b, int) and isinstance(l, int):
                                sum_bytes += b
                                sum_lines += l
                            else:
                                # Non-integer metrics invalidate totals check
                                sum_bytes = None
                                sum_lines = None
                                break
                        else:
                            sum_bytes = None
                            sum_lines = None
                            break
                    if (
                        sum_bytes is not None
                        and sum_lines is not None
                        and total_files == len(files_list)
                        and total_bytes_reported == sum_bytes
                        and total_lines_reported == sum_lines
                    ):
                        checks["stats_totals_match"] = True
                except Exception:
                    pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Ensure bounds
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()