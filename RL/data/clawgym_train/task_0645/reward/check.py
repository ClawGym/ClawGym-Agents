import json
import os
import sys
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_jsonl(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                s = raw.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return None, "Invalid JSON line"
                lines.append(obj)
        return lines, None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks with False
    checks = {
        "has_dry_run_md": False,
        "dry_run_contains_phrase": False,
        "dry_run_mentions_3": False,
        "dry_run_mentions_total": False,
        "dry_run_mentions_checkpointing": False,
        "has_log_txt": False,
        "has_results_jsonl": False,
        "has_failed_json": False,
        "has_summary_json": False,
        "summary_counts_consistent": False,
        "results_jsonl_valid": False,
        "failed_json_valid_array": False,
        "counts_match_results_failed_to_summary": False,
        "ids_not_in_both": False,
        "emails_normalized": False,
        "checkpoint_files_present": False,
        "checkpoint_files_valid": False,
        "progress_logs_present": False,
        "has_retry_logs": False
    }

    # Paths
    dry_run_path = os.path.join(output_dir, "dry_run.md")
    log_path = os.path.join(output_dir, "log.txt")
    results_path = os.path.join(output_dir, "results.jsonl")
    failed_path = os.path.join(output_dir, "failed.json")
    summary_path = os.path.join(output_dir, "summary.json")

    # Existence checks
    if os.path.isfile(dry_run_path):
        checks["has_dry_run_md"] = True
    if os.path.isfile(log_path):
        checks["has_log_txt"] = True
    if os.path.isfile(results_path):
        checks["has_results_jsonl"] = True
    if os.path.isfile(failed_path):
        checks["has_failed_json"] = True
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True

    # If summary exists, load and validate it
    summary = None
    if checks["has_summary_json"]:
        summary, err = load_json(summary_path)
        if isinstance(summary, dict):
            total = summary.get("total")
            succeeded = summary.get("succeeded")
            failed = summary.get("failed")
            if isinstance(total, int) and isinstance(succeeded, int) and isinstance(failed, int):
                if total == succeeded + failed:
                    checks["summary_counts_consistent"] = True

    # Parse results.jsonl and failed.json if present
    results = []
    failed_items = []
    results_ok = False
    failed_ok = False

    if checks["has_results_jsonl"]:
        results, err = parse_jsonl(results_path)
        if isinstance(results, list):
            # Validate each line has id and normalized_email strings
            valid_lines = True
            emails_ok = True
            for obj in results:
                if not isinstance(obj, dict):
                    valid_lines = False
                    emails_ok = False
                    break
                if "id" not in obj or "normalized_email" not in obj:
                    valid_lines = False
                    emails_ok = False
                    break
                if not isinstance(obj["id"], str) or not isinstance(obj["normalized_email"], str):
                    valid_lines = False
                    emails_ok = False
                    break
                ne = obj["normalized_email"]
                if ne != ne.strip() or ne != ne.lower():
                    emails_ok = False
            if valid_lines:
                checks["results_jsonl_valid"] = True
            if valid_lines and emails_ok:
                checks["emails_normalized"] = True
            results_ok = valid_lines

    if checks["has_failed_json"]:
        failed_data, err = load_json(failed_path)
        if isinstance(failed_data, list):
            # Ensure each entry is an object with id string (to support ID overlap check)
            failed_items = failed_data
            valid_array = True
            for item in failed_items:
                if not isinstance(item, dict):
                    valid_array = False
                    break
                if "id" not in item or not isinstance(item["id"], str):
                    valid_array = False
                    break
            if valid_array:
                checks["failed_json_valid_array"] = True
                failed_ok = True

    # Counts match with summary
    if summary is not None and results_ok and failed_ok:
        succ_count = len(results)
        fail_count = len(failed_items)
        total = summary.get("total")
        succeeded = summary.get("succeeded")
        failed_count_summary = summary.get("failed")
        if succeeded == succ_count and failed_count_summary == fail_count and total == succ_count + fail_count:
            checks["counts_match_results_failed_to_summary"] = True

    # ID overlap check
    if results_ok and failed_ok:
        success_ids = set()
        for obj in results:
            success_ids.add(obj["id"])
        fail_ids = set()
        for obj in failed_items:
            if "id" in obj and isinstance(obj["id"], str):
                fail_ids.add(obj["id"])
        if success_ids.isdisjoint(fail_ids):
            checks["ids_not_in_both"] = True

    # Dry run content checks
    if checks["has_dry_run_md"]:
        dry_text, _ = load_text(dry_run_path)
        if isinstance(dry_text, str):
            # phrase "Dry run" (case-insensitive to be tolerant)
            if re.search(r"\bdry run\b", dry_text, flags=re.IGNORECASE):
                checks["dry_run_contains_phrase"] = True
            # number 3 as a standalone number
            if re.search(r"\b3\b", dry_text):
                checks["dry_run_mentions_3"] = True
            # mention checkpointing
            if re.search(r"checkpoint", dry_text, flags=re.IGNORECASE):
                checks["dry_run_mentions_checkpointing"] = True
            # include summary.total value somewhere
            if summary is not None and isinstance(summary.get("total"), int):
                total_str = str(summary["total"])
                if total_str in dry_text:
                    checks["dry_run_mentions_total"] = True

    # Progress logs and retry logs
    log_text = None
    if checks["has_log_txt"]:
        log_text, _ = load_text(log_path)
        if isinstance(log_text, str):
            # Retry log: at least one "Retry X/Y in Zs: timeout on id="
            if re.search(r"Retry \d+/\d+ in \d+s: timeout on id=", log_text):
                checks["has_retry_logs"] = True

    # Checkpoints presence and validity + progress log boundaries presence
    checkpoints_ok = True
    checkpoints_valid = True
    progress_ok = True
    if summary is not None and isinstance(summary.get("total"), int):
        total = summary["total"]
        boundaries = list(range(10, total + 1, 10))
        # If no boundaries (total < 10), trivially pass
        if boundaries:
            # Check checkpoint files presence/validity
            for n in boundaries:
                cp_name = f"checkpoint_{n}.json"
                cp_path = os.path.join(output_dir, cp_name)
                if not os.path.isfile(cp_path):
                    checkpoints_ok = False
                    checkpoints_valid = False
                else:
                    cp, err = load_json(cp_path)
                    if not isinstance(cp, dict):
                        checkpoints_valid = False
                    else:
                        # Validate keys and values
                        if not isinstance(cp.get("batch_id", ""), str) or cp.get("batch_id", "") == "":
                            checkpoints_valid = False
                        if cp.get("total") != total:
                            checkpoints_valid = False
                        if cp.get("processed") != n:
                            checkpoints_valid = False
                        if not isinstance(cp.get("last_item_id", ""), str) or cp.get("last_item_id", "") == "":
                            checkpoints_valid = False
                        if not isinstance(cp.get("timestamp", ""), str) or cp.get("timestamp", "") == "":
                            checkpoints_valid = False
            # Progress logs
            if isinstance(log_text, str):
                for n in boundaries:
                    needle = f"{n}/{total} complete ("
                    if needle not in log_text:
                        progress_ok = False
            else:
                progress_ok = False
        # Set checks
        checks["checkpoint_files_present"] = checkpoints_ok
        checks["checkpoint_files_valid"] = checkpoints_valid
        checks["progress_logs_present"] = progress_ok
    else:
        # If summary missing or invalid, these remain False unless trivially true (but summary required for boundaries)
        checks["checkpoint_files_present"] = False
        checks["checkpoint_files_valid"] = False
        checks["progress_logs_present"] = False

    # Compute reward: average of True checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # No-op baseline: if output directory missing or none of the required files exist, reward is 0.0
    required_files = [dry_run_path, log_path, results_path, failed_path, summary_path]
    required_exist = [os.path.isfile(p) for p in required_files]
    if not os.path.isdir(output_dir) or not any(required_exist):
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()